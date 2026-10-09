"""Texture projectors in the compatibility profile: a fixed-function texture unit each

The shader passes cast X3D's texture projectors in the lit programs
(:mod:`OpenGLContext.passes.projectorpass`). The fixed-function pipeline
casts each through a texture unit of its own, from unit 1, as many as the
context has units past the first, up to
:data:`~OpenGLContext.passes.projectorpass.MAX_PROJECTORS`:

- The unit's texture is the projector's *cast factor*
  (:func:`cast_factor`): X_ITE's ``mix(1, picture * color, alpha *
  intensity)`` worked out once from the picture, so a ``GL_MODULATE`` of the
  fragment's colour by it is what the shader paths multiply the diffuse
  colour by. Outside the picture the border is white and leaves the colour.
- Its coordinates are generated eye-linear and taken by the texture matrix
  into the projector's picture (:func:`projector_matrix
  <OpenGLContext.scenegraph.textureprojector.projector_matrix>`).
- A projector's scope is a light's: its unit is switched off for a draw
  outside it.

The factor is read from the picture's image on the CPU, so a projector
casting an ``ImageTexture`` or a ``PixelTexture`` is drawn and one casting a
texture the pass draws (``RenderedTexture``, ``MovieTexture``) is not. The
modulation falls on the lit colour, the specular too, where the shaders
modulate the diffuse colour before lighting, and on every face, behind the
projector as well as before it.
"""
from __future__ import annotations

import logging
import weakref
from collections.abc import Sequence
from typing import Any, Optional

import numpy as np
from OpenGL import GL

from OpenGLContext.passes import lightscope
from OpenGLContext.passes.projectorpass import MAX_PROJECTORS, _picture, cast_projectors
from OpenGLContext.scenegraph.sampler import SMALL_IMAGE
from OpenGLContext.scenegraph.textureprojector import projector_matrix

log = logging.getLogger(__name__)

__all__ = ['BIAS', 'FixedProjectorsMixin', 'cast_factor', 'picture_image', 'picture_pixels']

#: Clip space's -1..1 into texture space's 0..1, as a row-vector matrix.
BIAS = np.array([[0.5, 0.0, 0.0, 0.0], [0.0, 0.5, 0.0, 0.0],
                 [0.0, 0.0, 0.5, 0.0], [0.5, 0.5, 0.5, 1.0]])

#: The generated coordinates and the eye plane each is measured along.
_COORDINATES = ((GL.GL_S, GL.GL_TEXTURE_GEN_S, (1.0, 0.0, 0.0, 0.0)),
                (GL.GL_T, GL.GL_TEXTURE_GEN_T, (0.0, 1.0, 0.0, 0.0)),
                (GL.GL_R, GL.GL_TEXTURE_GEN_R, (0.0, 0.0, 1.0, 0.0)),
                (GL.GL_Q, GL.GL_TEXTURE_GEN_Q, (0.0, 0.0, 0.0, 1.0)))


def cast_factor(pixels: np.ndarray, color: Sequence[float], intensity: float) -> np.ndarray:
    """What a projector's picture multiplies a colour by: ``(h, w, 3)`` uint8

    `pixels` is ``(h, w, c)`` uint8, one to four channels; the factor is
    ``1 - a + a * rgb * color`` with ``a`` the texel's alpha (1 without one)
    times `intensity`, clamped to 0..1.
    """
    values = np.asarray(pixels, np.float64) / 255.0
    channels = values.shape[-1]
    rgb = values[..., :3] if channels >= 3 else np.repeat(values[..., :1], 3, axis=-1)
    alpha = values[..., -1:] if channels in (2, 4) else np.ones(values.shape[:-1] + (1,))
    weight = np.clip(alpha * float(intensity), 0.0, 1.0)
    found = 1.0 - weight + weight * rgb * np.asarray(color, np.float64)[:3]
    return np.round(np.clip(found, 0.0, 1.0) * 255.0).astype(np.uint8)


def picture_image(texture: Any) -> Any:
    """The PIL image of a 2D texture node's picture; None where it has none on the CPU"""
    from OpenGLContext.scenegraph.texturebackground import side_image  # noqa: PLC0415 imports nodes
    return getattr(side_image(texture), 'image', None)


def picture_pixels(image: Any) -> np.ndarray:
    """A PIL image's ``(h, w, c)`` pixels, top row first"""
    pixels = np.asarray(image)
    return pixels[..., None] if pixels.ndim == 2 else pixels


class _Cast:
    """One projector's unit for a view: its factor texture and where it falls"""

    def __init__(self, unit: int, path: Any) -> None:
        self.unit = unit
        self.path = path
        self.on = False


class FixedProjectorsMixin:
    """The compatibility pass's side of texture projectors"""

    #: Each projector's factor texture: (what it was made from, GL name).
    _factorTextures: Optional[weakref.WeakKeyDictionary[Any, tuple[Any, int]]] = None
    #: The units this view casts through, in slot order.
    _fixedCasts: list[_Cast] = []
    _fixedScopes: lightscope.ScopeMasks = lightscope.ScopeMasks()

    def disposeResources(self) -> None:
        """Delete the projectors' factor textures"""
        held = self._factorTextures
        self._factorTextures = None
        if held:
            names = [name for _signature, name in held.values()]
            try:
                GL.glDeleteTextures(np.asarray(names, np.uint32))
            except Exception:     # pragma: no cover - teardown after the context
                log.debug('projector factor teardown failed', exc_info=True)
        super().disposeResources()  # type: ignore[misc]  # the pass's chain of mixins ends in one

    def setupFixedProjectors(self, light_paths: Sequence[Any], view: Any) -> None:
        """Give each cast projector of `light_paths` a texture unit for this view

        `view` is the view's modelview, world to eye.
        """
        self.endFixedProjectors()
        units = int(GL.glGetIntegerv(GL.GL_MAX_TEXTURE_UNITS))
        casts: list[_Cast] = []
        try:
            inverse = np.linalg.inv(np.asarray(view, np.float64))
        except np.linalg.LinAlgError:
            return
        for path in cast_projectors(light_paths):
            unit = len(casts) + 1
            if unit >= min(units, MAX_PROJECTORS + 1):
                break
            node = path[-1]
            picture = _picture(node.texture)
            image = picture_image(picture) if picture is not None else None
            if image is None:
                continue
            width, height = image.size
            found = projector_matrix(node, path.transformMatrix(),
                                     width / height if height else 1.0)
            if found is None:
                continue
            texture = self._factorTexture(node, image)
            self._configureUnit(unit, texture, inverse @ np.asarray(found.matrix, np.float64)
                                @ BIAS)
            casts.append(_Cast(unit, path))
        GL.glActiveTexture(GL.GL_TEXTURE0)
        self._fixedCasts = casts
        self._fixedScopes = self._fixedScopes.following(
            lightscope.scoped_lights([cast.path for cast in casts]))

    def _factorTexture(self, node: Any, image: Any) -> int:
        """The GL texture of `node`'s cast factor, made again when its image,
        colour or intensity changes"""
        held = self._factorTextures
        if held is None:
            held = self._factorTextures = weakref.WeakKeyDictionary()
        tint = (tuple(float(v) for v in node.color), float(node.intensity))
        found = held.get(node)
        if found is not None and found[0][0] is image and found[0][1] == tint:
            return found[1]
        name = int(GL.glGenTextures(1)) if found is None else found[1]
        signature = (image, tint)
        # Turned so the picture's top row is at t=1, where the projection puts it
        factor = np.ascontiguousarray(
            cast_factor(picture_pixels(image), node.color, node.intensity)[::-1])
        GL.glBindTexture(GL.GL_TEXTURE_2D, name)
        GL.glPixelStorei(GL.GL_UNPACK_ALIGNMENT, 1)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGB8, factor.shape[1], factor.shape[0], 0,
                        GL.GL_RGB, GL.GL_UNSIGNED_BYTE, factor)
        for wrap in (GL.GL_TEXTURE_WRAP_S, GL.GL_TEXTURE_WRAP_T):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, wrap, GL.GL_CLAMP_TO_BORDER)
        GL.glTexParameterfv(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_BORDER_COLOR, (1.0, 1.0, 1.0, 1.0))
        # A small picture's texels are drawn as squares, as a document's are
        filtered = GL.GL_LINEAR if max(factor.shape[:2]) >= SMALL_IMAGE else GL.GL_NEAREST
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, filtered)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, filtered)
        held[node] = (signature, name)
        return name

    @staticmethod
    def _configureUnit(unit: int, texture: int, matrix: np.ndarray) -> None:
        """Point `unit` at `texture` through eye-linear coordinates and `matrix`"""
        GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
        GL.glBindTexture(GL.GL_TEXTURE_2D, texture)
        GL.glTexEnvi(GL.GL_TEXTURE_ENV, GL.GL_TEXTURE_ENV_MODE, GL.GL_MODULATE)
        GL.glMatrixMode(GL.GL_MODELVIEW)
        GL.glPushMatrix()
        # An eye plane is taken through the modelview as it is set
        GL.glLoadIdentity()
        for coordinate, _switch, plane in _COORDINATES:
            GL.glTexGeni(coordinate, GL.GL_TEXTURE_GEN_MODE, GL.GL_EYE_LINEAR)
            GL.glTexGenfv(coordinate, GL.GL_EYE_PLANE, plane)
        GL.glPopMatrix()
        GL.glMatrixMode(GL.GL_TEXTURE)
        GL.glLoadMatrixf(np.ascontiguousarray(matrix, np.float32))
        GL.glMatrixMode(GL.GL_MODELVIEW)

    def applyFixedProjectors(self, path: Any) -> None:
        """Switch each projector's unit on for the draw of `path`, or off outside its scope"""
        if not self._fixedCasts:
            return
        mask = self._fixedScopes.mask(path)
        for slot, cast in enumerate(self._fixedCasts):
            self._switchUnit(cast, not mask & (1 << slot))
        GL.glActiveTexture(GL.GL_TEXTURE0)

    @staticmethod
    def _switchUnit(cast: _Cast, on: bool) -> None:
        if cast.on == on:
            return
        GL.glActiveTexture(GL.GL_TEXTURE0 + cast.unit)
        switch = GL.glEnable if on else GL.glDisable
        switch(GL.GL_TEXTURE_2D)
        for _coordinate, generator, _plane in _COORDINATES:
            switch(generator)
        cast.on = on

    def endFixedProjectors(self) -> None:
        """Switch every projector's unit off and its texture matrix back"""
        casts = self._fixedCasts
        self._fixedCasts = []
        for cast in casts:
            self._switchUnit(cast, False)
            GL.glActiveTexture(GL.GL_TEXTURE0 + cast.unit)
            GL.glMatrixMode(GL.GL_TEXTURE)
            GL.glLoadIdentity()
            GL.glMatrixMode(GL.GL_MODELVIEW)
        if casts:
            GL.glActiveTexture(GL.GL_TEXTURE0)
