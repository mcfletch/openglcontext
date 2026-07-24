"""Image-based lighting for the PBR pass: mode resolution + probe precompute.

Metals are almost entirely their reflected environment, so realistic metal needs
a real environment probe, not a flat ambient term. This module provides:

* :func:`resolve_ibl_mode` -- pick ``'full'`` / ``'analytic'`` / ``'off'`` from the
  GL renderer string, overridable by ``OPENGLCONTEXT_IBL`` (the same capability
  pattern as :mod:`OpenGLContext.passes.transmission`).
* :class:`IBLProbe` -- builds (once) and holds the GPU textures the ``full`` path
  samples: an irradiance cube (diffuse), a roughness-mip prefiltered specular cube,
  and a split-sum BRDF integration LUT. The source environment is a procedural
  *studio* cube (gradient + soft "softbox" panels), so the probe is self-contained
  -- no external HDR asset required.
* :class:`IBLController` -- resolves the effective mode per frame with fps-adaptive
  degradation (``full`` -> ``analytic`` -> ``off`` when the frame rate sags,
  re-upgrading after sustained headroom), mirroring the shadow cascades' adaptive
  logic.

The ``analytic`` path needs no probe: it evaluates the same procedural environment
plus Karis's analytic env-BRDF directly in ``pbr.frag``. It is both the software-
rasteriser fallback and the degraded tier, and is a correct fix in its own right
(the pre-fix ambient specular used bare Fresnel, omitting the BRDF integral).
"""
from __future__ import annotations

import os
import logging
from typing import Any, Callable, Optional

import numpy as np

from OpenGL.GL import (
    GL_TRIANGLES, GL_TEXTURE_2D, GL_TEXTURE0,
    GL_RGBA16F, GL_RGB16F, GL_TEXTURE_CUBE_MAP, GL_TEXTURE_CUBE_MAP_POSITIVE_X,
    GL_TEXTURE_CUBE_MAP_SEAMLESS,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_TEXTURE_WRAP_R,
    GL_LINEAR, GL_LINEAR_MIPMAP_LINEAR, GL_CLAMP_TO_EDGE, GL_REPEAT,
    GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_FRAMEBUFFER_COMPLETE,
    GL_FRAMEBUFFER_BINDING, GL_TEXTURE_BINDING_2D,
    GL_VIEWPORT, GL_DEPTH_TEST, GL_CULL_FACE, GL_BLEND,
    GL_VERTEX_SHADER, GL_FRAGMENT_SHADER,
    GL_RGB, GL_FLOAT,
    glGenTextures, glDeleteTextures, glBindTexture, glActiveTexture,
    glTexStorage2D, glTexSubImage2D, glTexParameteri, glGenerateMipmap,
    glGenFramebuffers, glDeleteFramebuffers, glBindFramebuffer,
    glFramebufferTexture2D, glCheckFramebufferStatus,
    glGenVertexArrays, glDeleteVertexArrays, glBindVertexArray,
    glDrawArrays, glViewport, glUseProgram, glEnable, glDisable,
    glGetIntegerv, glGetUniformLocation, glUniform1i, glUniform1f,
    glGetString, GL_VERSION,
)
from OpenGL.GL import shaders as GL_shaders

from OpenGLContext.passes.shaderpass import preprocess_shader

log = logging.getLogger(__name__)

# IBL probe sampler units, kept within the 16-unit budget; see the
# unit map in pbrpass.PBR_UNITS. These sit at the top of the free range (13-15).
IBL_UNITS = {'irradiance': 13, 'prefilter': 14, 'brdf': 15}
_IBL_SAMPLER = {'irradiance': 'irradianceMap', 'prefilter': 'prefilterMap',
                'brdf': 'brdfLUT'}

_SOFTWARE = ('llvmpipe', 'softpipe', 'swrast', 'software')

# iblMode integer uploaded to pbr.frag.
MODE_CODE = {'off': 0, 'analytic': 1, 'full': 2}


# Image-based environment cubemap: face suffix -> GL cube-face offset
# (GL_TEXTURE_CUBE_MAP_POSITIVE_X + offset). A face set named
# ``<prefix>{RT,LF,UP,DN,FR,BK}.<ext>`` becomes the ``full``-IBL environment, so
# metals reflect a real scene instead of the procedural studio env.
_CUBE_FACES = (('RT', 0), ('LF', 1), ('UP', 2), ('DN', 3), ('FR', 4), ('BK', 5))
_CUBE_EXTS = ('.jpg', '.jpeg', '.png', '.bmp')


def environment_cubemap_prefix() -> Optional[str]:
    """Path prefix of an environment cubemap face set, or None.

    ``OPENGLCONTEXT_ENV_CUBEMAP=/path/pimbackground_`` selects the six faces
    ``/path/pimbackground_RT.jpg`` ... ``_BK.jpg``.
    """
    val = os.environ.get('OPENGLCONTEXT_ENV_CUBEMAP', '').strip()
    return val or None


# Registered equirectangular HDR environment (H, W, 3 linear float32), set by the
# HDR background node once its panorama has loaded. A generation counter lets a
# probe that was already built notice the env changed and rebuild -- the panorama
# loads asynchronously, after the first 'full' frame may already have built the
# procedural probe.
_EQUIRECT_ENV: dict[str, Any] = {'array': None, 'generation': 0}


def set_equirect_env(array: Optional[np.ndarray]) -> int:
    """Register an equirectangular HDR panorama as the IBL probe env source.

    ``array`` is an ``(H, W, 3)`` linear float32 image (2:1 equirectangular), or
    None to clear. Returns the new generation number; every call bumps it so a
    built :class:`IBLProbe` rebuilds against the new environment.
    """
    if array is None:
        _EQUIRECT_ENV['array'] = None
    else:
        _EQUIRECT_ENV['array'] = np.ascontiguousarray(array, dtype=np.float32)
    _EQUIRECT_ENV['generation'] += 1
    return _EQUIRECT_ENV['generation']


def get_equirect_env() -> Optional[np.ndarray]:
    """The registered equirectangular HDR env array, or None."""
    return _EQUIRECT_ENV['array']


def equirect_env_generation() -> int:
    """Monotonic counter bumped on every :func:`set_equirect_env` call."""
    return _EQUIRECT_ENV['generation']


def equirect_hdr_path() -> Optional[str]:
    """Path or URL of an equirect HDR env from ``OPENGLCONTEXT_ENV_HDR``, or None.

    Lets the regression/capture harness point the probe at a ``.hdr`` without a
    scenegraph node. A URL is fetched and cached on first use by
    :func:`load_equirect_hdr`.
    """
    val = os.environ.get('OPENGLCONTEXT_ENV_HDR', '').strip()
    return val or None


def load_equirect_hdr(source: str) -> np.ndarray:
    """Decode an equirect Radiance ``.hdr`` from a path or http(s) URL.

    A URL is fetched into the shared asset cache (origin-locked, size-capped) via
    the Resolver, so repeated loads of the same panorama hit the disk cache.
    Returns an ``(H, W, 3)`` linear float32 array.
    """
    from OpenGLContext.loaders import hdr
    if source.startswith(('http://', 'https://')):
        from OpenGLContext.loaders.resolver import fetch_to_cache
        source = fetch_to_cache(source)
    return hdr.load_hdr(source)


def resolve_equirect_source() -> Optional[np.ndarray]:
    """The equirect HDR env to build the probe from, or None.

    A node-registered panorama (:func:`set_equirect_env`) wins; otherwise
    ``OPENGLCONTEXT_ENV_HDR`` is decoded. Returns an ``(H, W, 3)`` float32 array or
    None when no equirect source is configured. Never raises -- a bad
    ``OPENGLCONTEXT_ENV_HDR`` is logged and treated as unset.
    """
    arr = get_equirect_env()
    if arr is not None:
        return arr
    src = equirect_hdr_path()
    if src:
        try:
            return load_equirect_hdr(src)
        except Exception as err:
            log.error("failed to load OPENGLCONTEXT_ENV_HDR %r: %s", src, err)
    return None


def _srgb_to_linear(a: np.ndarray) -> np.ndarray:
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def load_cubemap_faces(prefix: str, size: int) -> Optional[dict[int, np.ndarray]]:
    """Load a 6-face cubemap into ``{gl_face_offset: (size,size,3) linear float32}``.

    Faces are resized to ``size`` and decoded sRGB->linear (the env feeds linear
    lighting math). Returns None if the face files are not all present.
    """
    from PIL import Image
    faces: dict[int, np.ndarray] = {}
    for suffix, offset in _CUBE_FACES:
        path = None
        for ext in _CUBE_EXTS:
            cand = prefix + suffix + ext
            if os.path.exists(cand):
                path = cand
                break
        if path is None:
            return None
        img = Image.open(path).convert('RGB')
        if img.size != (size, size):
            # Image.BILINEAR is a runtime module-level resampling constant Pillow's
            # type stubs no longer expose (moved to Image.Resampling).
            img = img.resize((size, size), Image.BILINEAR)  # type: ignore[attr-defined]
        arr = np.asarray(img, dtype=np.float32) / 255.0
        faces[offset] = np.ascontiguousarray(
            _srgb_to_linear(arr).astype(np.float32))
    return faces


# Whether this GL context can render the RGBA16F cube the 'full' probe builds.
# Probed once against the live context and cached, so a driver that passes the
# renderer-name check but still cannot render a float cube degrades to analytic
# up front instead of when IBLProbe._build's completeness check raises.
_FLOAT_RENDER_CAP: dict[str, bool] = {'checked': False, 'ok': False}


def _gl_context_present() -> bool:
    """True if a current GL context can answer queries.

    ``glGetString(GL_VERSION)`` returns None with no current context, letting the
    probe tell 'no context to test yet' (assume capable, don't cache) apart from
    'a context that fails the test' (degrade).
    """
    try:
        return bool(glGetString(GL_VERSION))
    except Exception:
        return False


def _run_float_render_capability_probe() -> bool:
    """Trial an RGBA16F FBO: create 4x4 RGBA16F, attach, check completeness.

    Assumes a current context. Restores the prior FBO binding and frees the trial
    objects before returning. Any failure (missing immutable storage, an
    incomplete framebuffer, a raised GL error) yields False.
    """
    if not bool(glTexStorage2D):
        return False
    # Restore the caller's FBO and GL_TEXTURE_2D binding: the probe may run in the
    # middle of another routine's texture setup (the HDR skybox upload), so leaving
    # a different texture/FBO bound would corrupt that in-progress work.
    prev_fbo = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
    prev_tex = int(glGetIntegerv(GL_TEXTURE_BINDING_2D))
    tex = fbo = None
    try:
        tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA16F, 4, 4)
        fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, tex, 0)
        return int(glCheckFramebufferStatus(GL_FRAMEBUFFER)) == GL_FRAMEBUFFER_COMPLETE
    except Exception as err:
        log.warning("RGBA16F render capability probe failed: %s", err)
        return False
    finally:
        glBindFramebuffer(GL_FRAMEBUFFER, prev_fbo)
        glBindTexture(GL_TEXTURE_2D, prev_tex)
        if fbo is not None:
            glDeleteFramebuffers(1, [fbo])
        if tex is not None:
            glDeleteTextures([tex])


def probe_float_render_capability(force: bool = False) -> bool:
    """Whether the GPU can drive the 'full' IBL path (render an RGBA16F cube).

    Runs :func:`_run_float_render_capability_probe` once and caches the verdict
    for the process. With no current context the check is deferred (returns True,
    uncached) so headless mode resolution stays on the renderer-name path; a later
    call with a live context does the real probe. ``force`` re-probes (tests).
    """
    if _FLOAT_RENDER_CAP['checked'] and not force:
        return _FLOAT_RENDER_CAP['ok']
    if not _gl_context_present():
        return True
    ok = _run_float_render_capability_probe()
    _FLOAT_RENDER_CAP['checked'] = True
    _FLOAT_RENDER_CAP['ok'] = ok
    return ok


def resolve_ibl_mode(renderer: str = '',
                     probe: Optional[Callable[[], bool]] = None) -> str:
    """Choose the base IBL path: 'full', 'analytic', or 'off'.

    ``OPENGLCONTEXT_IBL`` overrides (full/on, analytic/approx, off/none).
    Unset or 'auto': full on a hardware GPU, analytic on a software rasteriser
    (the prefilter/importance-sample precompute is too slow on llvmpipe).

    'full' -- whether reached by the auto path or an explicit override -- is kept
    only when the GPU can actually render the RGBA16F cube the probe builds.
    ``probe`` (a no-arg callable returning bool, defaulting to
    :func:`probe_float_render_capability`) that reports False degrades the result
    to 'analytic' up front, rather than letting the shortfall surface mid-build.
    """
    env = os.environ.get('OPENGLCONTEXT_IBL', '').strip().lower()
    if env in ('off', 'none', '0'):
        return 'off'
    if env in ('analytic', 'approx', 'analytical'):
        return 'analytic'
    forced_full = env in ('full', 'on', '1', 'ibl')
    r = (renderer or '').lower()
    if not forced_full and any(s in r for s in _SOFTWARE):
        return 'analytic'
    if probe is None:
        probe = probe_float_render_capability
    if not probe():
        return 'analytic'
    return 'full'


def ibl_is_adaptive() -> bool:
    """Whether IBL should fps-adaptively degrade. An explicit ``OPENGLCONTEXT_IBL``
    mode (full/analytic/off) pins that mode; only ``auto``/unset adapts. Pinning
    matters for deterministic captures and for a loaded environment cubemap, which
    only the ``full`` probe samples."""
    env = os.environ.get('OPENGLCONTEXT_IBL', '').strip().lower()
    return env in ('', 'auto')


def _compile(frag_name: str) -> int:
    # preprocess_shader resolves the shared #includes (_common/_brdf/_cubemap);
    # the fullscreen vert has none but round-trips unchanged.
    vert = preprocess_shader('ibl_fullscreen.vert')
    frag = preprocess_shader(frag_name)
    v = GL_shaders.compileShader(vert, GL_VERTEX_SHADER)
    fr = GL_shaders.compileShader(frag, GL_FRAGMENT_SHADER)
    return GL_shaders.compileProgram(v, fr, validate=False)


def _uni1i(prog: int, name: str, value: int) -> None:
    loc = glGetUniformLocation(prog, name)
    if loc != -1:
        glUniform1i(loc, int(value))


def _uni1f(prog: int, name: str, value: float) -> None:
    loc = glGetUniformLocation(prog, name)
    if loc != -1:
        glUniform1f(loc, float(value))


class IBLProbe(object):
    """Precomputed IBL textures (irradiance + prefiltered-specular cubes + BRDF LUT)."""

    ENV_SIZE = 128
    IRR_SIZE = 32
    PRE_SIZE = 128
    PRE_LEVELS = 5
    LUT_SIZE = 256

    def __init__(self) -> None:
        self._built = False
        self._failed = False
        self._source_gen: Optional[int] = None   # equirect_env_generation() at last build
        self.env: Optional[int] = None
        self.irradiance: Optional[int] = None
        self.prefilter: Optional[int] = None
        self.brdf: Optional[int] = None

    @property
    def ready(self) -> bool:
        return self._built and not self._failed

    @property
    def max_lod(self) -> float:
        return float(self.PRE_LEVELS - 1)

    def ensure_built(self) -> bool:
        """Build the probe, rebuilding if the registered equirect env changed.

        A node-registered HDR panorama arrives asynchronously (after the first
        'full' frame may have built the procedural probe), so each call compares
        the env generation and rebuilds when it advanced. Returns True if usable.
        """
        gen = equirect_env_generation()
        if self._built and self._source_gen == gen:
            return self.ready
        if self._built:
            self.release()           # env changed -> discard and rebuild
        self._built = True
        self._failed = False
        self._source_gen = gen
        try:
            self._build()
            log.info("IBL probe built (env %d, irradiance %d, prefilter %d/%d mips, "
                     "lut %d)", self.ENV_SIZE, self.IRR_SIZE, self.PRE_SIZE,
                     self.PRE_LEVELS, self.LUT_SIZE)
        except Exception as err:
            log.error("IBL probe build failed, falling back to analytic: %s", err)
            self._failed = True
            self.release()
        return self.ready

    # -- construction ------------------------------------------------------
    def _make_cube(self, size: int, levels: int = 1) -> int:
        # Immutable storage: glTexStorage2D allocates all 6 faces x all mip levels
        # consistently, so every level is attachment-complete. Per-level
        # glTexImage2D left higher mips incomplete on this driver. glTexStorage is
        # GL 4.2 core / ARB_texture_storage (present on every desktop GPU since
        # ~2012); it lifts the effective floor for the IBL path above the 3.3 the
        # shaders target. A driver without it raises here and IBL falls back to
        # analytic (ensure_built), rather than there being a glTexImage path.
        tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_CUBE_MAP, tex)
        glTexStorage2D(GL_TEXTURE_CUBE_MAP, levels, GL_RGBA16F, size, size)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE)
        minf = GL_LINEAR_MIPMAP_LINEAR if levels > 1 else GL_LINEAR
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, minf)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glBindTexture(GL_TEXTURE_CUBE_MAP, 0)
        return tex

    def _upload_env_faces(self, faces: dict[int, np.ndarray]) -> None:
        """Upload loaded cubemap faces (linear float) into ``self.env``."""
        glBindTexture(GL_TEXTURE_CUBE_MAP, self.env)
        for offset, arr in faces.items():
            glTexSubImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + offset, 0, 0, 0,
                            arr.shape[1], arr.shape[0], GL_RGB, GL_FLOAT,
                            np.ascontiguousarray(arr, dtype=np.float32))
        glBindTexture(GL_TEXTURE_CUBE_MAP, 0)

    def _render_equirect_env(self, fbo: int, equirect: np.ndarray) -> None:
        """Project an equirectangular HDR panorama onto the six env-cube faces.

        Uploads ``equirect`` (H, W, 3 linear float32) to a temporary float 2D
        texture with longitude-wrapping, then renders each cube face by sampling it
        through ``ibl_equirect.frag``. The temporary texture and program are freed
        before returning.
        """
        arr = np.ascontiguousarray(equirect, dtype=np.float32)
        h, w = arr.shape[0], arr.shape[1]
        src = glGenTextures(1)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, src)
        # A mip chain on the source panorama: the 128^2 env-cube faces minify a far
        # larger equirect, so sampling only the base level aliases the sun into a
        # jagged sparkle. glGenerateMipmap + a trilinear min filter pre-average it.
        src_levels = max(1, max(w, h).bit_length())
        glTexStorage2D(GL_TEXTURE_2D, src_levels, GL_RGB16F, w, h)
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGB, GL_FLOAT, arr)
        # Longitude wraps around the sphere; latitude clamps at the poles.
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glGenerateMipmap(GL_TEXTURE_2D)

        prog = _compile('ibl_equirect.frag')

        def bind_equirect(p: int) -> None:
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, src)
            _uni1i(p, 'equirectMap', 0)
        try:
            self._render_cube_faces(fbo, prog, self.env, self.ENV_SIZE, 0,
                                    setup=bind_equirect)
        finally:
            try:
                glDeleteTextures([src])
            except Exception as err:
                log.debug("IBL equirect source-texture teardown: %s", err)
            try:
                glDeleteProgram(prog)
            except Exception as err:
                log.debug("IBL equirect program teardown: %s", err)

    def _render_cube_faces(self, fbo: int, prog: int, cube: Optional[int], size: int,
                           level: int,
                           setup: Optional[Callable[[int], None]] = None) -> None:
        for face in range(6):
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                   GL_TEXTURE_CUBE_MAP_POSITIVE_X + face, cube, level)
            if face == 0:
                st = int(glCheckFramebufferStatus(GL_FRAMEBUFFER))
                if st != GL_FRAMEBUFFER_COMPLETE:
                    raise RuntimeError("cube FBO incomplete 0x%x (size %d level %d)"
                                       % (st, size, level))
            glViewport(0, 0, size, size)
            glUseProgram(prog)
            _uni1i(prog, 'faceIndex', face)
            if setup is not None:
                setup(prog)
            glDrawArrays(GL_TRIANGLES, 0, 3)

    def _build_env_cube(self, fbo: int, env_prog: int) -> None:
        """Build the environment cube (mip-chained) from the best available source.

        Source priority: a registered/loaded equirectangular HDR panorama
        (OPENGLCONTEXT_ENV_HDR or an HDRBackground node), then a cubemap image set
        (OPENGLCONTEXT_ENV_CUBEMAP), else the procedural studio env -- so metals
        reflect whatever real environment is configured. The mip chain lets the
        prefilter sample lower mips to suppress fireflies.
        """
        env_levels = max(1, self.ENV_SIZE.bit_length())
        self.env = self._make_cube(self.ENV_SIZE, levels=env_levels)
        equirect = resolve_equirect_source()
        prefix = environment_cubemap_prefix()
        faces = (load_cubemap_faces(prefix, self.ENV_SIZE)
                 if (equirect is None and prefix) else None)
        if equirect is not None:
            self._render_equirect_env(fbo, equirect)
            log.info("IBL environment loaded from equirect HDR %s", equirect.shape)
        elif faces is not None:
            self._upload_env_faces(faces)
            log.info("IBL environment loaded from cubemap %r", prefix)
        else:
            self._render_cube_faces(fbo, env_prog, self.env, self.ENV_SIZE, 0)
        glBindTexture(GL_TEXTURE_CUBE_MAP, self.env)
        glGenerateMipmap(GL_TEXTURE_CUBE_MAP)
        glBindTexture(GL_TEXTURE_CUBE_MAP, 0)

    def _build_irradiance(self, fbo: int, irr_prog: int) -> None:
        """Convolve the env cube into a diffuse-irradiance cube (Lambertian ambient)."""
        self.irradiance = self._make_cube(self.IRR_SIZE, levels=1)

        def bind_env(prog: int) -> None:
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_CUBE_MAP, self.env)
            _uni1i(prog, 'envMap', 0)
        self._render_cube_faces(fbo, irr_prog, self.irradiance, self.IRR_SIZE, 0,
                                setup=bind_env)

    def _build_prefilter(self, fbo: int, pre_prog: int) -> None:
        """GGX-importance-sample the env cube into a per-roughness specular mip chain."""
        self.prefilter = self._make_cube(self.PRE_SIZE, levels=self.PRE_LEVELS)
        for lvl in range(self.PRE_LEVELS):
            size = max(1, self.PRE_SIZE >> lvl)
            roughness = lvl / float(max(1, self.PRE_LEVELS - 1))

            def bind_env_rough(prog: int, roughness: float = roughness) -> None:
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_CUBE_MAP, self.env)
                _uni1i(prog, 'envMap', 0)
                _uni1f(prog, 'roughness', roughness)
                _uni1f(prog, 'envResolution', float(self.ENV_SIZE))
            self._render_cube_faces(fbo, pre_prog, self.prefilter, size, lvl,
                                    setup=bind_env_rough)

    def _build_brdf_lut(self, fbo: int, brdf_prog: int) -> int:
        """Render the environment-independent split-sum BRDF integration LUT.

        RGBA: .rg = the GGX split-sum (scale, bias); .b = the Charlie sheen
        directional albedo (KHR_materials_sheen energy compensation + IBL sheen).
        Returns the framebuffer completeness status after the final draw; the
        caller raises on it only once GL state has been restored.
        """
        self.brdf = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, self.brdf)
        glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA16F, self.LUT_SIZE, self.LUT_SIZE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self.brdf, 0)
        glViewport(0, 0, self.LUT_SIZE, self.LUT_SIZE)
        glUseProgram(brdf_prog)
        glDrawArrays(GL_TRIANGLES, 0, 3)
        return int(glCheckFramebufferStatus(GL_FRAMEBUFFER))

    def _build(self) -> None:
        prev_fbo = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
        prev_vp = glGetIntegerv(GL_VIEWPORT)
        # The build binds a private probe FBO/viewport and disables depth+cull. If
        # any step raises -- most importantly the framebuffer-completeness check on a
        # GPU that cannot render a float cube (exactly the case the analytic fallback
        # exists for) -- the caller's GL state and this frame's target must be
        # restored regardless, or every subsequent frame renders into the orphaned
        # probe FBO with depth testing off. So the transient objects and the state
        # restore live in a finally; the completeness verdict is raised after it.
        vao = fbo = None
        progs = []
        status = None
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)
        glDisable(GL_BLEND)
        glEnable(GL_TEXTURE_CUBE_MAP_SEAMLESS)
        try:
            vao = glGenVertexArrays(1)
            glBindVertexArray(vao)
            fbo = glGenFramebuffers(1)
            glBindFramebuffer(GL_FRAMEBUFFER, fbo)

            env_prog = _compile('ibl_env.frag')
            irr_prog = _compile('ibl_irradiance.frag')
            pre_prog = _compile('ibl_prefilter.frag')
            brdf_prog = _compile('ibl_brdf.frag')
            progs = [env_prog, irr_prog, pre_prog, brdf_prog]

            self._build_env_cube(fbo, env_prog)
            self._build_irradiance(fbo, irr_prog)
            self._build_prefilter(fbo, pre_prog)
            status = self._build_brdf_lut(fbo, brdf_prog)
        finally:
            # Free transient objects and restore the caller's target/viewport/state
            # whether the build succeeded or raised. Persistent probe textures are
            # left for release() (called by ensure_built on failure). Seamless-cube
            # and blend are intentionally left as set, matching the success path the
            # PBR sampling relies on.
            glUseProgram(0)
            glBindVertexArray(0)
            if vao is not None:
                glDeleteVertexArrays(1, [vao])
            glBindFramebuffer(GL_FRAMEBUFFER, prev_fbo)
            if fbo is not None:
                glDeleteFramebuffers(1, [fbo])
            for prog in progs:
                try:
                    glDeleteProgram(prog)
                except Exception as err:
                    log.debug("IBL build program teardown: %s", err)
            glActiveTexture(GL_TEXTURE0)
            glViewport(int(prev_vp[0]), int(prev_vp[1]), int(prev_vp[2]), int(prev_vp[3]))
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_CULL_FACE)

        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("IBL framebuffer incomplete: 0x%x" % status)

    # -- per-frame binding -------------------------------------------------
    def bind(self, program: Any) -> None:
        """Bind the probe textures to their units and set prefilterMaxLod."""
        glActiveTexture(GL_TEXTURE0 + IBL_UNITS['irradiance'])
        glBindTexture(GL_TEXTURE_CUBE_MAP, self.irradiance)
        glActiveTexture(GL_TEXTURE0 + IBL_UNITS['prefilter'])
        glBindTexture(GL_TEXTURE_CUBE_MAP, self.prefilter)
        glActiveTexture(GL_TEXTURE0 + IBL_UNITS['brdf'])
        glBindTexture(GL_TEXTURE_2D, self.brdf)
        glActiveTexture(GL_TEXTURE0)
        program._set_uniform1f('prefilterMaxLod', self.max_lod, program.program)

    def release(self) -> None:
        for attr in ('env', 'irradiance', 'prefilter'):
            tex = getattr(self, attr, None)
            if tex is not None:
                try:
                    glDeleteTextures([tex])
                except Exception as err:
                    log.debug("IBL %s texture teardown: %s", attr, err)
                setattr(self, attr, None)
        if self.brdf is not None:
            try:
                glDeleteTextures([self.brdf])
            except Exception as err:
                log.debug("IBL brdf texture teardown: %s", err)
            self.brdf = None


# glDeleteProgram is imported lazily (not in the top GL import list on all builds).
try:
    from OpenGL.GL import glDeleteProgram
except Exception:  # pragma: no cover
    def glDeleteProgram(_prog: Any) -> None:
        pass


class IBLController(object):
    """Resolve the effective IBL mode per frame with fps-adaptive degradation.

    The base mode comes from :func:`resolve_ibl_mode`. While in ``full`` the
    controller drops to ``analytic`` (then ``off``) when the recent frame rate
    sags below a floor, and steps back up after sustained headroom -- the same
    hysteresis the shadow cascades use, so IBL never pins a scene below 60 fps.
    """

    FPS_DOWN = 45.0
    FPS_UP = 75.0
    UP_FRAMES = 45
    COOLDOWN = 60

    _ORDER = ['off', 'analytic', 'full']

    def __init__(self, base_mode: str, adaptive: bool = True) -> None:
        self.base_mode = base_mode if base_mode in self._ORDER else 'off'
        self.adaptive = adaptive
        self._effective = self.base_mode
        self._up_streak = 0
        self._cooldown = 0

    def _cap_index(self) -> int:
        return self._ORDER.index(self.base_mode)

    def effective_mode(self, fps: float = 0.0) -> str:
        cap = self._cap_index()
        # Never auto-degrade below 'analytic': it is nearly free (a few ALU) and
        # keeps metals reflecting, whereas 'off' removes reflection entirely. Only
        # an explicit OPENGLCONTEXT_IBL=off selects 'off'. So adaptation moves
        # between 'full' and 'analytic' only.
        floor = 1 if cap >= 1 else 0
        if not self.adaptive or cap <= floor:
            self._effective = self.base_mode
            return self._effective
        cur = min(self._ORDER.index(self._effective), cap)
        if self._cooldown > 0:
            self._cooldown -= 1
        if fps and fps < self.FPS_DOWN and cur > floor:
            cur -= 1
            self._up_streak = 0
            self._cooldown = self.COOLDOWN
        elif fps > self.FPS_UP and cur < cap and self._cooldown == 0:
            self._up_streak += 1
            if self._up_streak >= self.UP_FRAMES:
                cur += 1
                self._up_streak = 0
        else:
            self._up_streak = 0
        self._effective = self._ORDER[cur]
        return self._effective
