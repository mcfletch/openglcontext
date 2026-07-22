"""Radiance HDR (equirectangular) Background node.

Draws a high-dynamic-range equirectangular panorama (a Radiance ``.hdr`` file,
the common HDRI interchange format) as the skybox, and registers the same
panorama as the image-based-lighting environment so metals and glass reflect the
scene they sit in. The panorama is loaded from a URL (fetched and cached through
the Resolver) or a local path.

Unlike :class:`CubeBackground` (six LDR JPEG faces), this node carries the full
HDR radiance, so both the visible sky and the reflections it drives keep values
well above 1.0 -- the reason to use an HDRI in the first place. The visible skybox
is exposure-scaled and filmic-tone-mapped to match how the PBR pass finishes lit
geometry, so the background and the objects lit by it share one response.
"""
import logging
import os
import threading

import numpy as np
from OpenGL.GL import *
from OpenGL.GL import shaders as GL_shaders
from OpenGL.GL import glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays
from OpenGL.arrays import vbo

from vrml import field, fieldtypes, node, protofunctions
from vrml.vrml97 import nodetypes

from OpenGLContext import context
from OpenGLContext.arrays import array

log = logging.getLogger(__name__)


class HDRURLField(fieldtypes.MFString):
    """URL field that kicks off an async load+decode of the panorama on assignment.

    Mirrors :class:`imagetexture.ImageURLField`: the network fetch and RGBE decode
    run off the render thread, and the decoded panorama is handed back to the node
    (which registers it with the IBL probe and triggers a redraw)."""

    fieldType = "MFString"

    def __set__(self, client, value, notify=True):
        value = super(HDRURLField, self).fset(client, value, notify=True)
        if value:
            threading.Thread(
                name="HDR background load %s" % (value,),
                target=client.loadBackground,
                args=(value, context.Context.allContexts),
                daemon=True,
            ).start()
        return value

    fset = __set__

    def fdel(self, client, notify=1):
        value = super(HDRURLField, self).fdel(client, notify)
        client.setImage(None)
        return value

    __delete__ = fdel


# A large cube whose vertices double as sky directions; drawn with depth writes
# masked and the depth buffer cleared afterwards, so it sits behind everything.
_CUBE_VERTICES = array([
    -100.0,  100.0,  100.0,  -100.0, -100.0,  100.0,
     100.0, -100.0,  100.0,   100.0,  100.0,  100.0,
    -100.0,  100.0, -100.0,  -100.0, -100.0, -100.0,
     100.0, -100.0, -100.0,   100.0,  100.0, -100.0,
], 'f')
_CUBE_INDICES = array([
    3, 2, 1,  3, 1, 0,   0, 1, 5,  0, 5, 4,
    7, 6, 2,  7, 2, 3,   4, 5, 6,  4, 6, 7,
    4, 7, 3,  4, 3, 0,   1, 2, 6,  1, 6, 5,
], 'H')


def _free_render_data(render_data):
    """Delete the GL objects of one compiled skybox (texture, cube VBOs, VAO).

    The shader program is shared on the class and kept. Must run on the GL thread,
    so a decode-thread env change queues its stale data for the next compile rather
    than deleting here."""
    if not render_data:
        return
    tex, vert_vbo, index_vbo, program, locations, vao = render_data
    try:
        glDeleteTextures([tex])
    except Exception as err:
        log.debug("HDR skybox texture teardown: %s", err)
    for buffer in (vert_vbo, index_vbo):
        try:
            buffer.delete()
        except Exception as err:
            log.debug("HDR skybox buffer teardown: %s", err)
    try:
        glDeleteVertexArrays(1, [vao])
    except Exception as err:
        log.debug("HDR skybox VAO teardown: %s", err)


class _HDRBackground(object):
    """Mix-in implementing the equirectangular-HDR skybox + IBL registration."""

    url = HDRURLField('url')
    exposure = field.newField('exposure', 'SFFloat', 1, 1.0)
    bound = field.newField('bound', 'SFBool', 1, 0)

    # Load-thread / render-thread contract for _equirect and _render_data:
    # the daemon loader thread (HDRURLField) decodes off the render thread and
    # calls setImage, which stores the new _equirect reference and nulls
    # _render_data so the next frame re-uploads. The render thread only ever
    # *reads* these two references. Each is a single attribute store, atomic under
    # the GIL, so the render thread sees either the whole old reference or the
    # whole new one -- never a torn value. There is no lock: the worst case is one
    # stale frame (the previous sky, or a skipped draw) between the store and the
    # triggerRedraw setImage issues. GL object *deletion* must stay on the render
    # thread, so setImage queues the superseded compiled skybox in
    # _stale_render_data instead of deleting it.
    # Decoded (H, W, 3) linear float32 panorama, or None until it loads.
    _equirect = None

    _shader = None
    _shader_locations = None
    # Compiled skybox GL objects from a superseded panorama, awaiting deletion on
    # the GL thread (see setImage / _drain_stale_render_data).
    _stale_render_data = None

    # -- loading -----------------------------------------------------------
    def loadBackground(self, url, contexts=()):
        """Fetch + decode the panorama (off the render thread) and install it.

        ``url`` is an MFString; the first entry that decodes wins. http(s) URLs are
        fetched into the shared asset cache (origin-locked, size-capped) via the
        Resolver; a local path is decoded directly. On success the panorama is
        registered as the IBL environment and every live context is redrawn.
        """
        from OpenGLContext.loaders import hdr
        from OpenGLContext.loaders.resolver import fetch_to_cache

        urls = [url] if isinstance(url, str) else list(url)
        for u in urls:
            try:
                if u.startswith(('http://', 'https://')):
                    path = fetch_to_cache(u)
                else:
                    path = os.path.abspath(u)
                image = hdr.load_hdr(path)
            except Exception as err:
                log.warning("HDR background: failed to load %s: %s", u, err)
                continue
            return self.setImage(image, contexts)
        log.warning("HDR background: no usable url in %s", urls)

    def setImage(self, image, contexts=()):
        """Install a decoded ``(H, W, 3)`` float panorama (or None to clear).

        Registers it as the IBL probe environment and triggers a redraw of every
        live context so the new sky and reflections appear.
        """
        from OpenGLContext.passes import ibl

        self._equirect = None if image is None else np.ascontiguousarray(
            image, dtype=np.float32)
        # Invalidate the compiled skybox so the next frame re-uploads. This may run
        # on the async loader thread, so the old GL objects cannot be deleted here;
        # queue them for the GL thread to free (else every env change leaks a float
        # panorama texture plus its cube VBOs/VAO).
        if self._render_data is not None:
            stale = self._stale_render_data
            if stale is None:
                stale = self._stale_render_data = []
            stale.append(self._render_data)
            self._render_data = None
        ibl.set_equirect_env(self._equirect)
        for c_reference in contexts:
            c = c_reference()
            if c is not None:
                c.triggerRedraw(1)
        return self._equirect

    # -- shader ------------------------------------------------------------
    @classmethod
    def _compile_shader(cls):
        if cls._shader is not None:
            return cls._shader, cls._shader_locations
        from OpenGLContext.passes.shaderpass import preprocess_shader
        vert = preprocess_shader('hdr_background.vert')
        frag = preprocess_shader('hdr_background.frag')
        program = GL_shaders.compileProgram(
            GL_shaders.compileShader(vert, GL_VERTEX_SHADER),
            GL_shaders.compileShader(frag, GL_FRAGMENT_SHADER),
            validate=False)
        cls._shader = program
        cls._shader_locations = {
            'aPosition': glGetAttribLocation(program, 'aPosition'),
            'mvpMatrix': glGetUniformLocation(program, 'mvpMatrix'),
            'equirectMap': glGetUniformLocation(program, 'equirectMap'),
            'exposure': glGetUniformLocation(program, 'exposure'),
            'hdrOutput': glGetUniformLocation(program, 'hdrOutput'),
        }
        return cls._shader, cls._shader_locations

    _render_data = None

    def compile(self, mode=None):
        """Build (once) the float panorama texture + cube VBOs + VAO for the skybox."""
        if self._equirect is None:
            return None
        arr = self._equirect
        h, w = arr.shape[0], arr.shape[1]
        tex = glGenTextures(1)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, tex)
        self._upload_panorama(arr, w, h)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glBindTexture(GL_TEXTURE_2D, 0)

        vert_vbo = vbo.VBO(_CUBE_VERTICES)
        index_vbo = vbo.VBO(_CUBE_INDICES, target=GL_ELEMENT_ARRAY_BUFFER)
        vao = glGenVertexArrays(1)
        program, locations = self._compile_shader()
        self._render_data = (tex, vert_vbo, index_vbo, program, locations, vao)
        return self._render_data

    def _upload_panorama(self, arr, w, h):
        """Upload the panorama to the bound 2D texture, float if the GPU supports it.

        The skybox shader expects linear radiance and finishes it itself (exposure,
        tone map, sRGB), so the float path uploads GL_RGB16F untouched. A driver
        without float-render support samples such a texture as black; there the
        radiance is clamped to [0,1] and uploaded as linear GL_RGBA8 -- reduced
        dynamic range, but a visible sky that still runs through the same shader
        finish, rather than a silently-black background.
        """
        from OpenGLContext.passes import ibl
        if ibl.probe_float_render_capability():
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB16F, w, h, 0, GL_RGB, GL_FLOAT, arr)
            return
        log.warning("HDR background: float textures unsupported; uploading a "
                    "clamped LDR sky (reduced dynamic range)")
        rgba = np.ones((h, w, 4), dtype=np.float32)
        rgba[..., :3] = np.clip(arr, 0.0, 1.0)
        rgba8 = np.ascontiguousarray((rgba * 255.0 + 0.5).astype(np.uint8))
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA,
                     GL_UNSIGNED_BYTE, rgba8)

    def _drain_stale_render_data(self):
        """Delete skybox GL objects queued by a superseded panorama (GL thread)."""
        stale = self._stale_render_data
        if not stale:
            return
        self._stale_render_data = []
        for render_data in stale:
            _free_render_data(render_data)

    def dispose(self):
        """Free every skybox GL object this node holds. Call on the GL thread."""
        self._drain_stale_render_data()
        if self._render_data is not None:
            _free_render_data(self._render_data)
            self._render_data = None

    # -- rendering ---------------------------------------------------------
    def _render(self, mode, clear=True):
        if getattr(mode, 'passCount', 0) != 0 or not self.bound:
            return 0
        self._drain_stale_render_data()   # free GL objects a prior env change queued
        if self._equirect is None:
            return 0
        render_data = self._render_data or self.compile(mode)
        if render_data is None:
            return 0
        tex, vert_vbo, index_vbo, program, locations, vao = render_data

        if clear:
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)

        shader_mode = getattr(mode, 'shader_mode', False)
        if not shader_mode:
            glDisable(GL_LIGHTING)
        depth_test = glIsEnabled(GL_DEPTH_TEST)
        cull = glIsEnabled(GL_CULL_FACE)
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)
        glDepthMask(GL_FALSE)

        from OpenGLContext.arrays import dot
        mvp = dot(mode.matrix, mode.projection).astype('f')
        glUseProgram(program)
        glBindVertexArray(vao)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, tex)
        if locations['equirectMap'] != -1:
            glUniform1i(locations['equirectMap'], 0)
        if locations['mvpMatrix'] != -1:
            glUniformMatrix4fv(locations['mvpMatrix'], 1, GL_FALSE, mvp)
        if locations['exposure'] != -1:
            glUniform1f(locations['exposure'], float(self._effective_exposure(mode)))
        if locations['hdrOutput'] != -1:
            glUniform1i(locations['hdrOutput'], 1 if getattr(mode, '_bloom_active', False) else 0)

        vert_vbo.bind()
        loc = locations['aPosition']
        glEnableVertexAttribArray(loc)
        glVertexAttribPointer(loc, 3, GL_FLOAT, GL_FALSE, 0, None)
        index_vbo.bind()
        try:
            glDrawElements(GL_TRIANGLES, 36, GL_UNSIGNED_SHORT, None)
        finally:
            glDisableVertexAttribArray(loc)
            vert_vbo.unbind()
            index_vbo.unbind()
            glBindVertexArray(0)
            glUseProgram(0)
            glBindTexture(GL_TEXTURE_2D, 0)
            glDepthMask(GL_TRUE)
            # Clear depth so the skybox sits behind the scene geometry.
            glClear(GL_DEPTH_BUFFER_BIT)
            if depth_test:
                glEnable(GL_DEPTH_TEST)
            if cull:
                glEnable(GL_CULL_FACE)
            if not shader_mode:
                glEnable(GL_LIGHTING)
        return 1

    def _effective_exposure(self, mode):
        """The camera exposure to render the sky at, matching the lit pass.

        A glTF scene with absolute-unit lights sets ``gltf_exposure`` on the
        context; the sky must use the same value so it is neither blown out nor
        black relative to the geometry. The node's own ``exposure`` field scales on
        top of that."""
        ctx = getattr(mode, 'context', None)
        cam = float(getattr(ctx, 'gltf_exposure', 1.0)) if ctx is not None else 1.0
        return cam * float(self.exposure)

    def RenderShader(self, mode, clear=True):
        """Shader-mode (core-profile) skybox render."""
        return self._render(mode, clear=clear)

    def Render(self, mode, clear=True):
        """Compatibility-mode render (also shader-based; HDR has no fixed path)."""
        return self._render(mode, clear=clear)


class HDRBackground(_HDRBackground, nodetypes.Background, nodetypes.Children,
                    node.Node):
    """Equirectangular Radiance-HDR skybox + IBL environment Background node.

    Fields:

        url -- MFString URL(s) or local path(s) of a Radiance ``.hdr`` panorama;
            the first that decodes is used. Loaded asynchronously and cached.
        exposure -- SFFloat multiplier on the sky's brightness (default 1.0).
        bound -- SFBool, whether this is the active background.

    The loaded panorama is registered as the IBL probe environment (see
    :mod:`OpenGLContext.passes.ibl`), so with full IBL active, scene metals reflect
    the same sky drawn behind them.
    """

    PROTO = "HDRBackground"

    def __init__(self, image=None, **named):
        super(HDRBackground, self).__init__(**named)
        if image is not None:
            self.setImage(image)
