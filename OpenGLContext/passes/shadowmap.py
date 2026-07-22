"""Framebuffer Objects for rendering shadow maps.

To keep the lit program inside the baseline GL 3.3 fragment texture-unit budget
, the maps are packed rather than allocated one-per-light:

- :class:`ShadowMapArray` -- one layered depth texture holding every spot map and
  directional CSM cascade (slot ``s`` cascade ``c`` -> layer ``s*MAX_CASCADES+c``;
  spot lights use cascade 0). Sampled through a single ``sampler2DArrayShadow``.
- :class:`ShadowMapCubeArray` -- one cube-map-array holding every point light's
  cube (cube ``c`` face ``f`` -> layer-face ``c*6+f``), sampled through a single
  ``samplerCubeArrayShadow``. Needs GL 4.0 / ARB_texture_cube_map_array.
- :class:`ShadowMapCube` -- a single-cube fallback for drivers without cube-arrays.

Every depth texture uses hardware shadow comparison so the lit shader gets free
2x2 PCF. Each follows the create / resize / completeness-check / cleanup
lifecycle of ``SelectionFBO`` in :mod:`OpenGLContext.passes._flat`.
"""
from __future__ import annotations

import logging
from typing import Optional

from OpenGL.GL import (
    GL_FRAMEBUFFER, GL_FRAMEBUFFER_COMPLETE, GL_DEPTH_ATTACHMENT,
    GL_DEPTH_COMPONENT24,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_LINEAR,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_BORDER,
    GL_CLAMP_TO_EDGE, GL_TEXTURE_BORDER_COLOR,
    GL_TEXTURE_COMPARE_MODE, GL_TEXTURE_COMPARE_FUNC,
    GL_COMPARE_REF_TO_TEXTURE, GL_LEQUAL, GL_NONE, GL_DEPTH_BUFFER_BIT,
    GL_TEXTURE_2D_ARRAY, GL_TEXTURE_CUBE_MAP, GL_TEXTURE_CUBE_MAP_POSITIVE_X,
    GL_TEXTURE_CUBE_MAP_SEAMLESS, GL_TEXTURE_CUBE_MAP_ARRAY,
    glGenFramebuffers, glBindFramebuffer, glGenTextures, glBindTexture,
    glTexImage2D, glTexImage3D, glTexStorage2D, glTexStorage3D,
    glTexParameteri, glTexParameterfv,
    glFramebufferTexture2D, glFramebufferTextureLayer,
    glCheckFramebufferStatus, glDeleteFramebuffers, glDeleteTextures,
    glDrawBuffer, glReadBuffer, glViewport, glClear, glGetIntegerv, glEnable,
    GL_FRAMEBUFFER_BINDING, GL_VIEWPORT,
)

log = logging.getLogger(__name__)


def _save_target():
    fbo = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
    viewport = tuple(int(v) for v in glGetIntegerv(GL_VIEWPORT))
    return fbo, viewport


def _restore_target(fbo, viewport):
    glBindFramebuffer(GL_FRAMEBUFFER, fbo)
    if viewport is not None:
        glViewport(*viewport)


def _set_compare_params(target: int) -> None:
    """Linear filter + hardware depth comparison for shadow sampling."""
    glTexParameteri(target, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(target, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(target, GL_TEXTURE_COMPARE_MODE, GL_COMPARE_REF_TO_TEXTURE)
    glTexParameteri(target, GL_TEXTURE_COMPARE_FUNC, GL_LEQUAL)


class ShadowMapArray:
    """A layered depth texture (GL_TEXTURE_2D_ARRAY) for directional CSM cascades.

    One layer per cascade; sampled in the shader through a sampler2DArrayShadow.
    """

    def __init__(self, size: int = 2048, layers: int = 4):
        self.size = int(size)
        self.layers = int(layers)
        self.fbo: Optional[int] = None
        self.depth_texture: Optional[int] = None
        self._initialized = False
        self._saved = None
        self._validated = False  # FBO completeness checked once, then trusted

    @property
    def texture(self) -> Optional[int]:
        return self.depth_texture

    def _ensure(self, size: int, layers: int) -> bool:
        if self._initialized and size == self.size and layers == self.layers:
            return True
        self.cleanup()
        self.size, self.layers = int(size), int(layers)
        try:
            self.fbo = glGenFramebuffers(1)
            self.depth_texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D_ARRAY, self.depth_texture)
            # Immutable storage: mutable depth arrays (glTexImage3D) miss the GPU
            # fast depth-clear path per array layer, which made each extra cascade
            # ~6-13ms instead of ~0.2ms. glTexStorage3D restores fast clear.
            glTexStorage3D(
                GL_TEXTURE_2D_ARRAY, 1, GL_DEPTH_COMPONENT24,
                self.size, self.size, self.layers,
            )
            _set_compare_params(GL_TEXTURE_2D_ARRAY)
            glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_BORDER)
            glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_BORDER)
            glTexParameterfv(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_BORDER_COLOR, [1.0, 1.0, 1.0, 1.0])
            self._initialized = True
            return True
        except Exception as err:
            log.warning("Failed to create CSM array FBO: %s", err)
            self.cleanup()
            return False

    def bind_layer(self, layer: int, size: Optional[int] = None,
                   layers: Optional[int] = None) -> bool:
        """Bind one cascade layer for depth rendering (clears it)."""
        if not self._ensure(size or self.size, layers or self.layers):
            return False
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glFramebufferTextureLayer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                  self.depth_texture, 0, int(layer))
        glDrawBuffer(GL_NONE)
        glReadBuffer(GL_NONE)
        if not self._validated:
            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if status != GL_FRAMEBUFFER_COMPLETE:
                log.warning("CSM layer FBO incomplete: status=%s", status)
                return False
            self._validated = True
        glViewport(0, 0, self.size, self.size)
        glClear(GL_DEPTH_BUFFER_BIT)
        return True

    def unbind(self) -> None:
        pass  # target restored once per batch by the caller

    def cleanup(self) -> None:
        if self.fbo is not None:
            try:
                glDeleteFramebuffers(1, [self.fbo])
            except Exception:
                pass
            self.fbo = None
        if self.depth_texture is not None:
            try:
                glDeleteTextures([self.depth_texture])
            except Exception:
                pass
            self.depth_texture = None
        self._initialized = False
        self._validated = False


class ShadowMapCubeArray:
    """A cube-map-array depth texture packing every point light's cube shadow.

    Holds ``num_cubes`` cubes (``6 * num_cubes`` layer-faces); cube ``c`` face
    ``f`` is layer-face ``c*6 + f``. Sampled through a single
    ``samplerCubeArrayShadow``, so all point shadows cost one
    fragment texture image unit regardless of light count. Requires GL 4.0 /
    GL_ARB_texture_cube_map_array.
    """

    def __init__(self, size: int = 1024, num_cubes: int = 4):
        self.size = int(size)
        self.num_cubes = int(num_cubes)
        self.fbo: Optional[int] = None
        self.depth_texture: Optional[int] = None
        self._initialized = False
        self._validated = False

    @property
    def texture(self) -> Optional[int]:
        return self.depth_texture

    def _ensure(self, size: int, num_cubes: int) -> bool:
        if self._initialized and size == self.size and num_cubes == self.num_cubes:
            return True
        self.cleanup()
        self.size, self.num_cubes = int(size), int(num_cubes)
        try:
            glEnable(GL_TEXTURE_CUBE_MAP_SEAMLESS)
            self.fbo = glGenFramebuffers(1)
            self.depth_texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_CUBE_MAP_ARRAY, self.depth_texture)
            glTexStorage3D(
                GL_TEXTURE_CUBE_MAP_ARRAY, 1, GL_DEPTH_COMPONENT24,
                self.size, self.size, 6 * self.num_cubes,
            )
            _set_compare_params(GL_TEXTURE_CUBE_MAP_ARRAY)
            glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_CUBE_MAP_ARRAY, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE)
            self._initialized = True
            return True
        except Exception as err:
            log.warning("Failed to create cube-array shadow FBO: %s", err)
            self.cleanup()
            return False

    def bind_face(self, cube_index: int, face: int, size: Optional[int] = None,
                  num_cubes: Optional[int] = None) -> bool:
        """Bind one cube's one face (layer-face cube*6+face) for depth rendering."""
        if not self._ensure(size or self.size, num_cubes or self.num_cubes):
            return False
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glFramebufferTextureLayer(
            GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, self.depth_texture, 0,
            int(cube_index) * 6 + int(face),
        )
        glDrawBuffer(GL_NONE)
        glReadBuffer(GL_NONE)
        if not self._validated:
            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if status != GL_FRAMEBUFFER_COMPLETE:
                log.warning("Cube-array face FBO incomplete: status=%s", status)
                return False
            self._validated = True
        glViewport(0, 0, self.size, self.size)
        glClear(GL_DEPTH_BUFFER_BIT)
        return True

    def unbind(self) -> None:
        pass  # target restored once per batch by the caller

    def cleanup(self) -> None:
        if self.fbo is not None:
            try:
                glDeleteFramebuffers(1, [self.fbo])
            except Exception:
                pass
            self.fbo = None
        if self.depth_texture is not None:
            try:
                glDeleteTextures([self.depth_texture])
            except Exception:
                pass
            self.depth_texture = None
        self._initialized = False
        self._validated = False


class ShadowMapCube:
    """A cube-map depth texture for omnidirectional point-light shadows.

    Six faces of projective depth; sampled in the shader via a samplerCubeShadow.
    """

    def __init__(self, size: int = 1024):
        self.size = int(size)
        self.fbo: Optional[int] = None
        self.depth_texture: Optional[int] = None
        self._initialized = False
        self._saved = None
        self._validated = False  # FBO completeness checked once, then trusted

    @property
    def texture(self) -> Optional[int]:
        return self.depth_texture

    def _ensure(self, size: int) -> bool:
        if self._initialized and size == self.size:
            return True
        self.cleanup()
        self.size = int(size)
        try:
            glEnable(GL_TEXTURE_CUBE_MAP_SEAMLESS)
            self.fbo = glGenFramebuffers(1)
            self.depth_texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_CUBE_MAP, self.depth_texture)
            # Immutable storage: one glTexStorage2D allocates all six faces and
            # keeps the GPU depth fast-clear path (mutable per-face glTexImage2D
            # misses it), matching the 2D-array/cube-array rationale above
            #.
            glTexStorage2D(
                GL_TEXTURE_CUBE_MAP, 1, GL_DEPTH_COMPONENT24, self.size, self.size,
            )
            _set_compare_params(GL_TEXTURE_CUBE_MAP)
            glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE)
            self._initialized = True
            return True
        except Exception as err:
            log.warning("Failed to create cube shadow FBO: %s", err)
            self.cleanup()
            return False

    def bind_face(self, face: int, size: Optional[int] = None) -> bool:
        """Bind one cube face for depth rendering (clears it).

        Does not save/restore the render target -- the caller brackets the whole
        shadow batch with one save/restore -- and validates completeness only
        once, so the six faces don't each stall the pipeline with a
        glCheckFramebufferStatus + glGetIntegerv round-trip every frame.
        """
        if not self._ensure(size or self.size):
            return False
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glFramebufferTexture2D(
            GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
            GL_TEXTURE_CUBE_MAP_POSITIVE_X + int(face), self.depth_texture, 0,
        )
        glDrawBuffer(GL_NONE)
        glReadBuffer(GL_NONE)
        if not self._validated:
            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if status != GL_FRAMEBUFFER_COMPLETE:
                log.warning("Cube face FBO incomplete: status=%s", status)
                return False
            self._validated = True
        glViewport(0, 0, self.size, self.size)
        glClear(GL_DEPTH_BUFFER_BIT)
        return True

    def unbind(self) -> None:
        pass  # target restored once per batch by the caller

    def cleanup(self) -> None:
        if self.fbo is not None:
            try:
                glDeleteFramebuffers(1, [self.fbo])
            except Exception:
                pass
            self.fbo = None
        if self.depth_texture is not None:
            try:
                glDeleteTextures([self.depth_texture])
            except Exception:
                pass
            self.depth_texture = None
        self._initialized = False
        self._validated = False
