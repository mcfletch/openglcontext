#! /usr/bin/env python
"""PBR glTF sample browser (``oglc-gltf-demo``) -- a thin wrapper over the viewer.

Streams every model in the KhronosGroup/glTF-Sample-Models 2.0 catalogue and shows
it with the shared ``oglc-gltf`` viewer's PBR scene/lighting/framing, adding only what
is specific to browsing: catalogue navigation and the reference-screenshot thumbnail
overlaid top-right so a rendering can be compared against the reference.

    n / Page Down   next model
    p / Page Up     previous model
    F2              save a screenshot (iso-dated PNG in the current directory)

(The arrow keys are left free for camera navigation.)

Models are downloaded on a background thread, so switching models never freezes the
window: the current model keeps rendering (with a "Loading ..." overlay) until the
next one is decoded and ready to upload to the card.

The model name is drawn top-left (white); a download/decode failure is shown there
in red. Models are centred, auto-framed and slowly turned -- embedded cameras are
authored for the model's original placement and don't survive centring, so the
viewer's ``--no-cameras`` framing is used.

Run:  oglc-gltf-demo
Start elsewhere:  MODEL=DamagedHelmet oglc-gltf-demo

Every ``oglc-gltf`` command-line option applies (``--shadows/--no-shadows``,
``--lights``, ``--ibl-intensity``, ...); see ``oglc-gltf-demo -h``.
"""
import argparse
import os
import sys
import urllib.request
from dataclasses import dataclass
from typing import Any

os.environ.setdefault('OPENGLCONTEXT_SHADOWS', '1')

from OpenGLContext.bin.gltf_view import (
    TestContext as ViewerContext, apply_render_env, build_parser,
)
from OpenGLContext.loaders import gltf
from OpenGLContext.loaders import resolver
from OpenGLContext.loaders import gltf_demos


# -- per-model demo profiles -------------------------------------------------
# The browser can't frame every model the same way: an object (a helmet) wants a
# slow turntable while *facing* the camera; a building (Sponza) wants to be walked
# through from the courtyard; a city wants a free-fly camera *inside* it. This
# table sets, per model, the facing yaw, whether to turntable, and whether to run
# physics (and start flying). Unlisted models get DEFAULT_PROFILE. Grow it from the
# conformance harness (plans/GLTF-DEMO-CONFORMANCE.md) as reference poses are dialed
# in; --no-rotate / --yaw / --physics still override per run.

@dataclass(frozen=True)
class ModelProfile:
    yaw: float = 0.0          # facing rotation about +Y (radians) on first load
    turntable: bool = True    # slowly rotate the model
    physics: bool = False     # walk/fly the scene with collision
    fly: bool = False         # start in free-fly (vs grounded walk) when physics on
    background: str = ''      # '' (black), 'sky', or 'cube' (env cubemap skybox)
    bloom: bool = False        # HDR bloom (emissive glow) -- for emissive-heavy demos


DEFAULT_PROFILE = ModelProfile()

# Sub-demos whose materials need a lit environment to read correctly: transmissive
# glass refracts the backdrop (a black one renders rough glass opaque) and metals
# reflect it. The roster is shared with the capture/regression tools via
# gltf_demos so the demo and the harness never drift on which models need an env;
# the demo lights them with the cheap analytic 'sky' (see the loop below).
_ENV_BACKGROUND = tuple(sorted(gltf_demos.ENV_BACKGROUND_MODELS))

# Emissive-heavy sub-demos whose reference shows a bloom/glow. Bloom is HDR + a
# post-process (OPENGLCONTEXT_BLOOM); it is enabled per-model so it does not change
# the tone-mapping of the (majority) non-emissive demos.
_BLOOM_MODELS = ('EmissiveStrengthTest', 'IridescenceLamp')

MODEL_PROFILES = {
    # Architecture / scenes: walk or fly, no turntable. "Start in the courtyard" /
    # "inside the city" is handled by the character spawn sampling clear floor.
    'Sponza': ModelProfile(turntable=False, physics=True),
    'VirtualCity': ModelProfile(turntable=False, physics=True, fly=True),
    # Objects (DamagedHelmet, Duck, ...) are correct at the default yaw 0 (verified:
    # the helmet's visor faces the camera) with a slow turntable, so they need no
    # entry. Add a `yaw=` here only for a model the conformance harness shows facing
    # away at 0 -- do not guess (a wrong yaw turns a front-facing model backwards).
}
# Fold the env-background list into the profile table (same mechanism as yaw/physics).
# 'sky' (the lit gradient) is used rather than 'cube': it reliably gives glass a lit
# backdrop to refract (a black one renders rough glass opaque) and metals a lit
# reflection, without the image-cube skybox's per-face load cost in the browser.
for _name in _ENV_BACKGROUND:
    _base = MODEL_PROFILES.get(_name, DEFAULT_PROFILE)
    MODEL_PROFILES[_name] = ModelProfile(
        yaw=_base.yaw, turntable=_base.turntable, physics=_base.physics,
        fly=_base.fly, background='sky', bloom=_base.bloom)
for _name in _BLOOM_MODELS:
    _base = MODEL_PROFILES.get(_name, DEFAULT_PROFILE)
    MODEL_PROFILES[_name] = ModelProfile(
        yaw=_base.yaw, turntable=_base.turntable, physics=_base.physics,
        fly=_base.fly, background=_base.background, bloom=True)


def default_env_prefix() -> str | None:
    """Path prefix of the bundled demo environment cubemap (or an override).

    ``OPENGLCONTEXT_ENV_CUBEMAP`` wins; otherwise the faces shipped under the
    package's ``resources/environment`` are used so the ``cube`` background works
    out of the box. Returns None if no face set is found.
    """
    override = os.environ.get('OPENGLCONTEXT_ENV_CUBEMAP', '').strip()
    if override:
        return override
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # OpenGLContext/
    prefix = os.path.join(here, 'resources', 'environment', 'pimbackground_')
    if os.path.exists(prefix + 'UP.jpg'):
        return prefix
    return None


def profile_for(name: str) -> ModelProfile:
    """Return the :class:`ModelProfile` for a model name (default if unlisted)."""
    return MODEL_PROFILES.get(name, DEFAULT_PROFILE)


def resolve_bloom(name: str) -> bool:
    """Whether the per-model profile asks for HDR bloom (emissive glow)."""
    return profile_for(name).bloom


def resolve_background(config: argparse.Namespace, name: str) -> Any:
    """Background spec for a model: explicit --background wins, else the per-model
    profile ('cube'/'sky'), else the demo default (black 'none')."""
    if getattr(config, '_background_explicit', False):
        return config.background
    prof = profile_for(name)
    if prof.background == 'cube':
        return 'cube'
    if prof.background == 'sky':
        return 'sky'
    return config.background


def resolve_view(config: argparse.Namespace, name: str) -> tuple[float, bool]:
    """(yaw, turntable) for a model, honouring --no-rotate / explicit --turntable /
    explicit --yaw over the per-model profile."""
    prof = profile_for(name)
    if getattr(config, 'no_rotate', False):
        turntable = False
    elif getattr(config, '_turntable_explicit', False):
        turntable = True
    else:
        turntable = prof.turntable
    yaw = config.yaw if getattr(config, '_yaw_explicit', False) else prof.yaw
    return yaw, turntable


def resolve_physics(config: argparse.Namespace, name: str) -> tuple[bool, bool]:
    """(physics, fly) for a model. A --capture run never walks (deterministic
    frame); an explicit --physics/--no-physics overrides the per-model profile."""
    prof = profile_for(name)
    if getattr(config, 'capture', None):
        return False, False
    if getattr(config, '_physics_explicit', False):
        return bool(config.physics), prof.fly
    return prof.physics, prof.fly


class TestContext(ViewerContext):
    """The viewer, browsing the sample catalogue instead of one file."""

    def _prepare_source(self) -> None:
        self.source = None
        self.overlay_error = False
        self._ref_textures: dict[str, Any] = {}     # model name -> (Texture, aspect) or False
        self._ref_current: Any = None
        try:
            self.catalog: Any = gltf.fetch_sample_catalog()
        except Exception as err:
            print("Could not fetch the model catalogue: %s" % err)
            self.catalog = [{'name': n, 'display': n, 'screenshot_url': None}
                            for n in gltf.SAMPLE_MODELS]
        start = os.environ.get('MODEL', '')
        names = [e['name'] for e in self.catalog]
        if start and not start.isnumeric():
            self.index = names.index(start) if start in names else 0
        elif start:
            self.index = int(start) % len(self.catalog)
        else:
            self.index = 0

    def _load_scene(self) -> Any:
        entry = self.catalog[self.index]
        label = "[%d/%d] %s" % (self.index + 1, len(self.catalog), entry['display'])
        self._ref_current = entry['name']
        print("Loading %s ..." % label)
        try:
            scene = gltf.load_sample(entry['name'])
        except Exception as err:
            self._label = "%s\nFAILED: %s" % (label, str(err).splitlines()[0][:50])
            self.overlay_error = True
            print("  " + self._label.replace("\n", "  "))
            return None
        self._label = label
        self.overlay_error = False
        return scene

    # -- async catalogue loading -----------------------------------------
    def _request_initial_scene(self) -> None:
        """Pull the initial catalogue model in the background instead of a file."""
        self._request_current_model()

    def _request_current_model(self) -> None:
        """Kick off a background load of the model at ``self.index``. The window keeps
        rendering the previous model (with a "Loading ..." overlay) until it lands."""
        entry = self.catalog[self.index]
        name = entry['name']
        label = "[%d/%d] %s" % (self.index + 1, len(self.catalog), entry['display'])
        self._pending_name = name
        self._pending_label = label
        print("Loading %s ..." % label)
        self._request_scene(lambda: gltf.load_sample(name),
                            label="Loading %s ..." % label)

    def _apply_loaded(self, scene: Any) -> None:
        # _build_scenegraph reads _ref_current for the per-model profile, so set the
        # newly loaded model's identity before building.
        self._ref_current = self._pending_name
        self._label = self._pending_label
        self.overlay_error = False
        self._build_scenegraph(scene)
        self._on_scene_ready()

    def _apply_failed(self, error: BaseException | None) -> None:
        self._ref_current = self._pending_name
        self.overlay_error = True
        msg = str(error).splitlines()[0][:50] if error else 'load failed'
        self._label = "%s\nFAILED: %s" % (self._pending_label, msg)
        self.overlay_text = self._label
        print("  " + self._label.replace("\n", "  "))

    def _on_scene_ready(self) -> None:
        self._scene_loaded = True
        self._apply_physics_profile()

    def _build_scenegraph(self, scene: Any) -> None:
        # Apply the per-model facing/turntable/background BEFORE the base builds the
        # scenegraph (it reads config.yaw/turntable and calls _make_background there).
        self.config.yaw, self.config.turntable = resolve_view(
            self.config, self._ref_current)
        self.config.background = resolve_background(self.config, self._ref_current)
        # Bloom is read per frame from the env var, so toggling it per model works.
        os.environ['OPENGLCONTEXT_BLOOM'] = '1' if resolve_bloom(self._ref_current) else '0'
        ViewerContext._build_scenegraph(self, scene)
        self.overlay_text = self._label

    def _setup_physics(self) -> None:
        # Enable physics for the *initial* model only if its profile asks for it.
        physics, fly = resolve_physics(self.config, getattr(self, '_ref_current', ''))
        self.config.physics = physics
        ViewerContext._setup_physics(self)
        if physics and self._physics is not None:
            self._physics_scene = self.sg
            if fly:
                self._physics.set_fly(True)

    def _apply_physics_profile(self) -> None:
        """Turn physics on/off for the newly loaded model per its profile.

        Called on model *switch* (after `_setup_physics` has captured the free-fly
        manager). Rebuilds the collision world when the scene changed so a physics
        model gets its own world, and hands control back to free-fly otherwise.
        """
        if getattr(self, 'sg', None) is None or self.config.capture:
            return
        physics, fly = resolve_physics(self.config, self._ref_current)
        if physics:
            if getattr(self, '_physics_scene', None) is not self.sg:
                self._physics = None          # force a rebuild for this scene
            if self._set_physics(True):
                self._physics_scene = self.sg
                if fly and self._physics is not None:
                    self._physics.set_fly(True)
        elif getattr(self, '_physics_on', False):
            self._set_physics(False)

    # Catalogue navigation keys. Deliberately NOT the arrow keys: those drive
    # free-fly camera movement, so binding them to next/prev model made walking
    # around a model a pain (every turn also jumped to another model).
    NEXT_MODEL_KEYS = ('n', '<pagedown>')
    PREV_MODEL_KEYS = ('p', '<pageup>')

    # -- catalogue navigation --------------------------------------------
    def setupCallbacks(self) -> None:  # pragma: no cover - binds live event handlers
        # Skip the viewer's PageUp/PageDown viewpoint bindings (this browser has no
        # per-model cameras); n/p and PageUp/PageDown advance the *model* instead.
        from OpenGLContext import testingcontext
        testingcontext.getInteractive().setupCallbacks(self)
        for key in self.NEXT_MODEL_KEYS:
            self.addEventHandler('keyboard', name=key, function=self._next_model)
        for key in self.PREV_MODEL_KEYS:
            self.addEventHandler('keyboard', name=key, function=self._prev_model)
        self.addEventHandler('keyboard', name='<F2>', function=self._request_screenshot)

    def _next_model(self, event: Any = None) -> None:
        self._go(1)

    def _prev_model(self, event: Any = None) -> None:
        self._go(-1)

    def _go(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.catalog)
        self._request_current_model()

    # -- overlays --------------------------------------------------------
    def _draw_overlay(self, shader: Any) -> None:  # pragma: no cover - GL text overlay draw
        vp = self._viewport()
        if vp is None or not self.overlay_text:
            return
        tw, th = vp
        try:
            from OpenGLContext.scenegraph.text.shadertext import get_text_renderer
            renderer = get_text_renderer(18)
            color = (1.0, 0.25, 0.2, 1.0) if self.overlay_error else (1.0, 1.0, 1.0, 1.0)
            renderer.render_text(
                self.overlay_text, x=10, y=th - 8 - renderer.char_height,
                shader_program=shader, viewport_width=tw, viewport_height=th,
                color=color, background_color=(0.0, 0.0, 0.0, 0.55))
        except Exception:
            pass

    def _extra_overlay(self, shader: Any) -> None:  # pragma: no cover - GL thumbnail blit
        """Draw the model's reference screenshot thumbnail, top-right."""
        if self.overlay_error:
            return
        ref = self._reference_texture()
        vp = self._viewport()
        if ref is None or vp is None:
            return
        tex, aspect = ref
        if not getattr(tex, 'texture', None):
            return
        tw, th = vp
        margin = 0.03
        x1, y1 = 1.0 - margin, 1.0 - margin
        height = 0.55                                   # NDC height
        view_aspect = tw / float(th or 1)
        width = min(height * aspect / view_aspect, 0.6)
        x0, y0 = x1 - width, y1 - height
        try:
            _blit_texture(shader, tex.texture, ndc_rect=(x0, y0, x1, y1))
            from OpenGLContext.scenegraph.text.shadertext import get_text_renderer
            r = get_text_renderer(14)
            lx = int((x0 + 1.0) * 0.5 * tw) + 2
            ly = int((y0 + 1.0) * 0.5 * th) - r.char_height - 2
            r.render_text("reference", x=lx, y=ly, shader_program=shader,
                          viewport_width=tw, viewport_height=th, color=(1, 1, 1, 1),
                          background_color=(0, 0, 0, 0.5))
        except Exception:
            pass

    def _reference_texture(self) -> Any:
        """Return (Texture, aspect) for the current model's reference image, or None."""
        name = self._ref_current
        if name in self._ref_textures:
            return self._ref_textures[name] or None
        entry = self.catalog[self.index]
        url = entry.get('screenshot_url')
        result: Any = False
        if url:
            try:
                from io import BytesIO
                from PIL import Image
                from OpenGLContext import texture as texture_module
                data = urllib.request.urlopen(resolver.safe_url(url), timeout=20).read()
                img = Image.open(BytesIO(data)).convert('RGB')
                aspect = img.size[0] / float(img.size[1] or 1)
                result = (texture_module.Texture(image=img), aspect)
            except Exception:
                result = False
        self._ref_textures[name] = result
        return result or None


def _blit_texture(shader: Any, texture_id: Any, ndc_rect: Any) -> None:  # pragma: no cover - raw GL quad blit
    """Draw a textured quad in NDC space using the unlit program's texture mode."""
    import ctypes
    import numpy as np
    from OpenGL.GL import (
        glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays,
        glGenBuffers, glBindBuffer, glBufferData, glDeleteBuffers,
        GL_ARRAY_BUFFER, GL_DYNAMIC_DRAW, GL_FLOAT, GL_FALSE, GL_TRIANGLES,
        glEnableVertexAttribArray, glDisableVertexAttribArray, glVertexAttribPointer,
        glDrawArrays, glActiveTexture, glBindTexture, GL_TEXTURE0, GL_TEXTURE_2D,
        glGetAttribLocation, glGetUniformLocation, glUniform1i,
        glEnable, glDisable, GL_DEPTH_TEST,
    )
    x0, y0, x1, y1 = ndc_rect
    # texcoords flipped vertically: Texture.fromPIL stores the image flipped
    verts = np.array([
        x0, y0, 0, 0.0, 1.0,  x1, y0, 0, 1.0, 1.0,  x1, y1, 0, 1.0, 0.0,
        x0, y0, 0, 0.0, 1.0,  x1, y1, 0, 1.0, 0.0,  x0, y1, 0, 0.0, 0.0,
    ], 'f')
    prog = shader.unlit_program
    shader.use(lit=False)
    ident = np.identity(4, 'f')
    shader.set_matrices(ident, ident, program=prog)
    shader.set_text_mode(enabled=False)
    glActiveTexture(GL_TEXTURE0)
    glBindTexture(GL_TEXTURE_2D, texture_id)
    loc = glGetUniformLocation(prog, 'diffuseTexture')
    if loc >= 0:
        glUniform1i(loc, 0)
    loc = glGetUniformLocation(prog, 'useTexture')
    if loc >= 0:
        glUniform1i(loc, 1)
    shader.set_solid_color((1, 1, 1, 1))

    vao = glGenVertexArrays(1)
    vbo = glGenBuffers(1)
    glBindVertexArray(vao)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    glBufferData(GL_ARRAY_BUFFER, verts.nbytes, verts, GL_DYNAMIC_DRAW)
    pos = glGetAttribLocation(prog, 'aPosition')
    tc = glGetAttribLocation(prog, 'aTexCoord')
    stride = 5 * 4
    if pos >= 0:
        glEnableVertexAttribArray(pos)
        glVertexAttribPointer(pos, 3, GL_FLOAT, GL_FALSE, stride, None)
    if tc >= 0:
        glEnableVertexAttribArray(tc)
        glVertexAttribPointer(tc, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(12))
    glDisable(GL_DEPTH_TEST)
    glDrawArrays(GL_TRIANGLES, 0, 6)
    glEnable(GL_DEPTH_TEST)
    if pos >= 0:
        glDisableVertexAttribArray(pos)
    if tc >= 0:
        glDisableVertexAttribArray(tc)
    loc = glGetUniformLocation(prog, 'useTexture')
    if loc >= 0:
        glUniform1i(loc, 0)
    glBindTexture(GL_TEXTURE_2D, 0)
    glBindBuffer(GL_ARRAY_BUFFER, 0)
    glBindVertexArray(0)
    glDeleteBuffers(1, [vbo])
    glDeleteVertexArrays(1, [vao])
    shader.use(lit=True)


def demo_config(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse + massage the browser's config (no GL). Separated so it is testable.

    The browser centres + turntables every model and ignores embedded cameras, so
    it also defaults to **free-fly, not physics**: a turntable model has no ground,
    and walk mode just drops the avatar until the model is out of view. An explicit
    ``--physics``/``--no-physics`` on the command line is still honoured.
    """
    parser = build_parser(prog='oglc-gltf-demo')
    args = parser.parse_args(argv)
    args.no_cameras = True
    args.turntable = True
    # Most models read cleanest on black; the per-model profile (resolve_background)
    # injects a lit/cube background only for the sub-demos that need one (glass to
    # refract, metals to reflect). An explicit --background always wins.
    if args.background is None:
        args.background = 'none'
    tokens = sys.argv[1:] if argv is None else argv
    # Record which view/physics knobs the user set explicitly, so the per-model
    # profiles (resolve_view/resolve_physics) can defer to them.
    args._physics_explicit = any(t in ('--physics', '--no-physics') for t in tokens)
    args._turntable_explicit = '--turntable' in tokens
    args._yaw_explicit = '--yaw' in tokens
    args._background_explicit = '--background' in tokens
    if not args._physics_explicit:
        args.physics = False
    # A --capture run wants a fixed, reference-comparable orientation; the
    # turntable would spin the model away from the reference pose. Freeze it for
    # captures (honour an explicit --turntable).
    if args.capture and not args._turntable_explicit:
        args.turntable = False
    return args


def apply_environment(args: argparse.Namespace) -> None:
    """Set the render env so metals reflect a real environment in the browser.

    Loads the bundled environment cubemap into the IBL probe and pins full IBL, so
    metals / dielectric specular / sheen reflect it instead of a near-black env
    (SpecularTest, ToyCar, MetalRoughSpheres, NegativeScaleTest, ...). Safe on heavy
    models (the earlier stall was the CubeBackground skybox, now built only for a
    'cube' background). Reflections read too dim at the shadow-tuned 0.4 IBL
    intensity, so lift it for browsing (an explicit --ibl-intensity still wins).
    """
    # An explicit --environment (a cubemap prefix, an .hdr, or a bundled HDRI name)
    # is owned entirely by apply_render_env; only fall back to the bundled cubemap
    # when the user named no environment of their own.
    env = default_env_prefix()
    if env and not getattr(args, 'environment', None):
        os.environ.setdefault('OPENGLCONTEXT_ENV_CUBEMAP', env)
        os.environ.setdefault('OPENGLCONTEXT_IBL', 'full')
    if args.ibl_intensity is None:
        os.environ['OPENGLCONTEXT_IBL_INTENSITY'] = '0.9'


def main(argv: list[str] | None = None) -> Any:
    args = demo_config(argv)
    apply_environment(args)
    apply_render_env(args)             # an explicit --ibl-intensity still wins here
    TestContext.config = args
    return TestContext.ContextMainLoop(size=args.size) if args.size \
        else TestContext.ContextMainLoop()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
