"""The pass's side of texture projectors: their pictures, places and scope

Each view, :meth:`ProjectorsMixin.setupProjectors` finds the scene's
``TextureProjector`` and ``TextureProjectorParallel`` nodes that are ``on``
and whose texture has a picture, the first :data:`MAX_PROJECTORS` of them in
the order of their paths, and hands the lit program where each casts
(:func:`~OpenGLContext.scenegraph.textureprojector.projector_matrix`), its
colour and intensity, and its picture, copied into a layer of one array
texture of :data:`PICTURE_SIZE` texels a side (:class:`ProjectorImages`). A
projector past the first four is reported once and casts nothing. Its scope
is a light's, and its bit of the program's ``lightsOff`` is
:data:`PROJECTOR_SCOPE_BIT` plus its slot.

The compatibility profile casts no projectors.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Optional

import numpy as np
from OpenGL.GL import (
    GL_CLAMP_TO_EDGE, GL_COLOR_ATTACHMENT0, GL_COLOR_BUFFER_BIT, GL_DRAW_FRAMEBUFFER,
    GL_DRAW_FRAMEBUFFER_BINDING, GL_FALSE, GL_LINEAR, GL_READ_FRAMEBUFFER,
    GL_READ_FRAMEBUFFER_BINDING, GL_RGBA, GL_RGBA8, GL_TEXTURE0, GL_TEXTURE_2D,
    GL_TEXTURE_2D_ARRAY, GL_TEXTURE_HEIGHT, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WIDTH, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_UNSIGNED_BYTE,
    glActiveTexture, glBindFramebuffer, glBindTexture, glBlitFramebuffer,
    glDeleteFramebuffers, glDeleteTextures, glFramebufferTexture2D,
    glFramebufferTextureLayer, glGenFramebuffers, glGenTextures, glGetIntegerv,
    glGetTexLevelParameteriv, glTexImage3D, glTexParameteri, glUniformMatrix4fv,
    glUniform4fv,
)

from OpenGLContext.passes import lightscope
from OpenGLContext.scenegraph.textureprojector import is_projector, projector_matrix

log = logging.getLogger(__name__)

__all__ = ['MAX_PROJECTORS', 'PICTURE_SIZE', 'PROJECTOR_SCOPE_BIT', 'ProjectorImages',
           'ProjectorsMixin', 'cast_projectors']

#: How many projectors cast at once (_projectors_inc.glsl's MAX_PROJECTORS).
MAX_PROJECTORS = 4
#: The first bit of ``lightsOff`` a projector's scope takes.
PROJECTOR_SCOPE_BIT = 16
#: The side, in texels, a projector's picture is resampled to.
PICTURE_SIZE = 512

_reported: set[str] = set()


def _report(message: str) -> None:
    if message not in _reported:
        _reported.add(message)
        log.warning(message)


def cast_projectors(light_paths: Sequence[Any]) -> list[Any]:
    """The paths of the projectors that cast this frame: on, at most :data:`MAX_PROJECTORS`"""
    found = [path for path in light_paths
             if is_projector(path[-1]) and bool(path[-1].on) and path[-1].texture]
    if len(found) > MAX_PROJECTORS:
        _report('%d texture projectors are on; the first %d cast'
                % (len(found), MAX_PROJECTORS))
    return found[:MAX_PROJECTORS]


class ProjectorImages:
    """The array texture the projectors' pictures are copied into, a layer each"""

    def __init__(self, size: int = PICTURE_SIZE) -> None:
        self.size = int(size)
        self.texture: Optional[int] = None
        self._fbos: Optional[tuple[int, int]] = None
        #: What each layer last had copied into it: the source texture holder.
        self._held: list[Any] = [None] * MAX_PROJECTORS

    def _ensure(self) -> None:
        if self.texture is not None:
            return
        texture = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D_ARRAY, texture)
        glTexImage3D(GL_TEXTURE_2D_ARRAY, 0, GL_RGBA8, self.size, self.size, MAX_PROJECTORS,
                     0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        for name, value in ((GL_TEXTURE_MIN_FILTER, GL_LINEAR), (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
                            (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                            (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            glTexParameteri(GL_TEXTURE_2D_ARRAY, name, value)
        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)
        self.texture = texture
        self._fbos = (int(glGenFramebuffers(1)), int(glGenFramebuffers(1)))

    def copy(self, layer: int, holder: Any, again: bool) -> None:
        """Copy the 2D texture ``holder`` into ``layer``, resampled

        Skipped where the layer already holds this texture and ``again`` is
        false: a texture that changes in place (a movie, a rendered texture)
        asks for ``again``.
        """
        if not again and self._held[layer] is holder:
            return
        self._ensure()
        assert self._fbos is not None and self.texture is not None
        read, draw = self._fbos
        previous = (int(glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING)),
                    int(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING)))
        glBindTexture(GL_TEXTURE_2D, holder.texture)
        width = int(glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH))
        height = int(glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_HEIGHT))
        glBindTexture(GL_TEXTURE_2D, 0)
        try:
            glBindFramebuffer(GL_READ_FRAMEBUFFER, read)
            glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                                   holder.texture, 0)
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, draw)
            glFramebufferTextureLayer(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, self.texture,
                                      0, layer)
            glBlitFramebuffer(0, 0, max(1, width), max(1, height), 0, 0, self.size, self.size,
                              GL_COLOR_BUFFER_BIT, GL_LINEAR)
        finally:
            glBindFramebuffer(GL_READ_FRAMEBUFFER, previous[0])
            glBindFramebuffer(GL_DRAW_FRAMEBUFFER, previous[1])
        self._held[layer] = holder

    def release(self) -> None:
        """Let go of the GL objects"""
        try:
            if self._fbos is not None:
                glDeleteFramebuffers(2, np.array(self._fbos, dtype=np.uint32))
            if self.texture is not None:
                glDeleteTextures(1, np.array([self.texture], dtype=np.uint32))
        except Exception as err:     # pragma: no cover - teardown after the context
            log.debug('projector images teardown: %s', err)
        self.texture = None
        self._fbos = None
        self._held = [None] * MAX_PROJECTORS


def _dynamic(texture: Any) -> bool:
    """Whether a texture changes its picture in place"""
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept beside its one use
    return isinstance(texture, (x3d.MovieTexture, x3d.RenderedTexture))


def _picture(texture: Any) -> Any:
    """The 2D texture node a projector casts: its texture, or a MultiTexture's first"""
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept beside its one use
    if isinstance(texture, x3d.MultiTexture):
        flat = [child for child in texture.texture
                if isinstance(child, x3d.X3DTexture2DNode)]
        return flat[0] if flat else None
    return texture if isinstance(texture, x3d.X3DTexture2DNode) else None


class ProjectorsMixin:
    """Setting up the frame's texture projectors on the lit program"""

    _projectorImages: Optional[ProjectorImages] = None
    #: The projectors' paths this view casts, in slot order.
    castProjectors: list[Any] = []

    def disposeResources(self) -> None:
        """Release the projectors' pictures"""
        if self._projectorImages is not None:
            self._projectorImages.release()
            self._projectorImages = None
        super().disposeResources()  # type: ignore[misc]  # the pass's chain of mixins ends in one

    def projectorScopes(self) -> lightscope.Scoped:
        """The cast projectors whose ``global`` is false, with their ``lightsOff`` bits"""
        return lightscope.scoped_lights(self.castProjectors, first=PROJECTOR_SCOPE_BIT)

    def setupProjectors(self, light_paths: Sequence[Any]) -> None:
        """Hand the lit program this view's projectors; none where it has no unit for them"""
        owner: Any = self
        shader = owner.shader_program
        unit = getattr(shader, 'projector_unit', lambda: None)()
        program = getattr(shader, 'program', None)
        if unit is None or not program:
            self.castProjectors = []
            return
        cast: list[tuple[Any, Any, Any]] = []
        images = self._projectorImages
        for path in cast_projectors(light_paths):
            node = path[-1]
            picture = _picture(node.texture)
            holder = picture.cached(owner) if picture is not None else None
            if holder is None or not getattr(holder, 'texture', None) or int(
                    getattr(holder, 'target', GL_TEXTURE_2D)) != GL_TEXTURE_2D:
                continue
            aspect = self._aspect(picture, holder)
            if node.__dict__.get('_sentAspect') != aspect:
                node.__dict__['_sentAspect'] = aspect
                node.aspectRatio = aspect
            found = projector_matrix(node, path.transformMatrix(), aspect)
            if found is None:
                continue
            if images is None:
                images = self._projectorImages = ProjectorImages()
            slot = len(cast)
            images.copy(slot, holder, _dynamic(picture))
            cast.append((path, node, found))
        self.castProjectors = [path for path, _node, _found in cast]
        shader._set_uniform1i('projectorCount', len(cast), program)
        if not cast:
            return
        matrices = np.zeros((MAX_PROJECTORS, 4, 4), np.float32)
        colours = np.zeros((MAX_PROJECTORS, 4), np.float32)
        places = np.zeros((MAX_PROJECTORS, 4), np.float32)
        aims = np.zeros((MAX_PROJECTORS, 4), np.float32)
        for slot, (_path, node, found) in enumerate(cast):
            matrices[slot] = found.matrix
            colours[slot] = tuple(node.color)[:3] + (float(node.intensity),)
            places[slot] = found.location + (1.0 if found.perspective else 0.0,)
            aims[slot] = found.direction + (float(found.bounded[0] | (found.bounded[1] << 1)),)
        location = shader._get_location('projectorMatrix', program)
        if location != -1:
            # Row vectors, as the engine's matrices are, which GL reads as the
            # column-vector matrix the shader multiplies by.
            glUniformMatrix4fv(location, MAX_PROJECTORS, GL_FALSE, matrices)
        for name, values in (('projectorColor', colours), ('projectorPlace', places),
                             ('projectorAim', aims)):
            location = shader._get_location(name, program)
            if location != -1:
                glUniform4fv(location, MAX_PROJECTORS, values)
        assert images is not None and images.texture is not None
        glActiveTexture(GL_TEXTURE0 + unit)
        glBindTexture(GL_TEXTURE_2D_ARRAY, images.texture)
        glActiveTexture(GL_TEXTURE0)

    @staticmethod
    def _aspect(picture: Any, holder: Any) -> float:
        """The picture's width over its height, sent as the projector's ``aspectRatio``"""
        glBindTexture(GL_TEXTURE_2D, holder.texture)
        width = int(glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH))
        height = int(glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_HEIGHT))
        glBindTexture(GL_TEXTURE_2D, 0)
        return width / height if width > 0 and height > 0 else 1.0
