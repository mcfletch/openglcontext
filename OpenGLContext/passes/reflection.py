"""The scene mirrored in a body of water, for the water to reflect.

A lake looks like a lake because of what is in it: the far shore, the trees,
the jetty, the fire on the bank. The image-based-lighting probe holds only the
sky, so without this a sheet of water reflects a gradient and reads as a
rippled plate. Each view with water in it is drawn once more, through the
camera mirrored in the water's plane, into :class:`ReflectionBuffer`; the water
samples that at its own screen position, displaced by its ripple.

The arithmetic is here and holds no GL: which plane the frame's water gives
(:func:`water_plane`), the matrix that mirrors the world in it
(:func:`mirror_matrix`), and the projection whose near plane is the water
(:func:`oblique_projection`), which clips everything below the surface in every
program the pass draws with. Matrices are row-vector, as the engine's are:
``point @ matrix``.

The pass that uses them is
:meth:`~OpenGLContext.passes.flateffects._FlatEffectsMixin.renderWaterReflection`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence, Tuple

import numpy as np
from numpy.typing import ArrayLike

log = logging.getLogger(__name__)

__all__ = ['REFLECTION_UNIT', 'REFLECTION_UNITS_NEEDED', 'SCALE', 'Plane',
           'Reflection', 'water_plane', 'mirror_matrix', 'eye_plane',
           'oblique_projection', 'plan', 'is_water', 'ReflectionBuffer']

#: The texture unit the reflection is read from: past the joint palette (30),
#: so it exists only on a driver whose fragment stage has more units than that.
REFLECTION_UNIT = 31

#: How many fragment texture units a driver needs for the reflection to be
#: compiled in at all.
REFLECTION_UNITS_NEEDED = REFLECTION_UNIT + 1

#: The reflection target's size as a share of the view's, each way. The ripple
#: displaces every lookup by more than a texel of it, so the quarter of the
#: pixels a half-size target costs does not show.
SCALE = 0.5

#: A plane in the world: a point on it and its unit normal, which points to
#: the side the water is seen from.
Plane = Tuple[np.ndarray, np.ndarray]


def _sheet_plane(record: Any) -> Optional[Plane]:
    """The plane of one water record's sheet, or None for a sheet with no extent."""
    geometry = record[5].geometry
    positions = np.asarray(getattr(geometry, 'positions', ()), dtype='d')
    if not len(positions):
        return None
    tmatrix = np.asarray(record[2], dtype='d')
    level = float(positions[:, 1].mean())
    point = (np.array([0.0, level, 0.0, 1.0]) @ tmatrix)[:3]
    # The sheet's own x and z, carried into the world: their cross product is
    # the surface's normal under any scale or shear the placement applies.
    across = np.array([1.0, 0.0, 0.0]) @ tmatrix[:3, :3]
    along = np.array([0.0, 0.0, 1.0]) @ tmatrix[:3, :3]
    normal = np.cross(along, across)
    length = float(np.linalg.norm(normal))
    if length == 0.0:
        return None
    return point, normal / length


def water_plane(records: Iterable[Any], eye: ArrayLike) -> Optional[Plane]:
    """The plane of the water nearest ``eye`` that ``eye`` looks down on.

    ``records`` are a view's draw records; water is any whose geometry carries
    a ``wave_style``, meshed flat in its own space. None where there is no
    water, and where the camera is under every sheet there is: looking up
    through a surface is not looking into a mirror.
    """
    where = np.asarray(eye, dtype='d')[:3]
    nearest: Optional[Plane] = None
    closest = np.inf
    for record in records:
        if not is_water(record):
            continue
        plane = _sheet_plane(record)
        if plane is None:
            continue
        height = float(np.dot(where - plane[0], plane[1]))
        if height <= 0.0:
            continue
        if height < closest:
            nearest, closest = plane, height
    return nearest


def mirror_matrix(point: ArrayLike, normal: ArrayLike) -> np.ndarray:
    """The world reflected in the plane through ``point`` facing ``normal``."""
    n = np.asarray(normal, dtype='d')[:3]
    n = n / np.linalg.norm(n)
    distance = float(np.dot(n, np.asarray(point, dtype='d')[:3]))
    mirror = np.identity(4)
    mirror[:3, :3] -= 2.0 * np.outer(n, n)
    mirror[3, :3] = 2.0 * distance * n
    return mirror


def eye_plane(point: ArrayLike, normal: ArrayLike, view: Any) -> np.ndarray:
    """A world plane in the eye space ``view`` takes the world to.

    Returned as the four coefficients ``(a, b, c, d)`` whose dot product with
    an eye-space point ``(x, y, z, 1)`` is positive on the side ``normal``
    faces.
    """
    n = np.asarray(normal, dtype='d')[:3]
    world = np.append(n, -float(np.dot(n, np.asarray(point, dtype='d')[:3])))
    return np.asarray(np.linalg.inv(np.asarray(view, dtype='d')) @ world, dtype='d')


def oblique_projection(projection: Any, plane: ArrayLike) -> np.ndarray:
    """``projection`` with its near plane moved onto ``plane``, in eye space.

    What is on the negative side of the plane is clipped by the near plane,
    in every shader, with nothing in any shader to do it; where a kept point
    lands on screen is unchanged, and only depth is bent. The camera has to
    stand on the negative side, as a camera mirrored below the water does.
    This is Lengyel's oblique near-plane clipping.
    """
    column = np.array(projection, dtype='d').T
    clip = np.asarray(plane, dtype='d')
    corner = np.linalg.inv(column) @ np.array(
        [np.sign(clip[0]), np.sign(clip[1]), 1.0, 1.0])
    scaled = clip * (2.0 / float(np.dot(clip, corner)))
    column[2] = scaled - column[3]
    return column.T


def is_water(record: Any) -> bool:
    """Whether a draw record is a body of water: its geometry has a wave."""
    return getattr(getattr(record[5], 'geometry', None), 'wave_style', None) is not None


@dataclass(frozen=True)
class Reflection:
    """How one view's water reflection is drawn.

    ``modelView`` is the view's camera mirrored in the water's plane and
    ``projection`` the view's, with its near plane on the water; ``size`` is
    the target in texels.
    """

    point: np.ndarray
    normal: np.ndarray
    modelView: np.ndarray
    projection: np.ndarray
    size: Tuple[int, int]

    @property
    def modelproj(self) -> np.ndarray:
        """World to clip space, through the mirror."""
        return np.asarray(self.modelView @ self.projection, dtype='d')


def plan(records: Iterable[Any], model_view: Any, projection: Any,
         rect: Sequence[int], scale: float = SCALE) -> Optional[Reflection]:
    """The reflection a view with these records asks for, or None.

    None where the view holds no water, or none its camera looks down on.
    """
    view = np.asarray(model_view, dtype='d')
    eye = np.linalg.inv(view)[3, :3]
    plane = water_plane(records, eye)
    if plane is None:
        return None
    point, normal = plane
    mirrored = mirror_matrix(point, normal) @ view
    clipped = oblique_projection(projection, eye_plane(point, normal, mirrored))
    size = (max(1, int(rect[2] * scale)), max(1, int(rect[3] * scale)))
    return Reflection(point, normal, mirrored, clipped, size)


class ReflectionBuffer:
    """Where one view's mirrored scene is drawn: linear HDR colour and depth.

    Allocated on first use and whenever the size it is asked for changes. The
    colour target is cleared to alpha 0 before each draw and the scene writes
    alpha 1, so the water can tell the mirrored scene from the sky behind it.
    """

    UNIT = REFLECTION_UNIT

    def __init__(self) -> None:
        self.size: Tuple[int, int] = (0, 0)
        self.framebuffer = 0
        self.texture = 0
        self.depth = 0

    def ensure_size(self, width: int, height: int) -> None:
        """Hold a target of ``width`` by ``height`` texels."""
        from OpenGL import GL as gl
        width, height = max(1, int(width)), max(1, int(height))
        if (width, height) == self.size and self.framebuffer:
            return
        self.release()
        self.texture = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glTexStorage2D(gl.GL_TEXTURE_2D, 1, gl.GL_RGBA16F, width, height)
        for name, value in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
                            (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                            (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                            (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, name, value)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self.depth = int(gl.glGenRenderbuffers(1))
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self.depth)
        gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24,
                                 width, height)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, 0)
        previous = int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING))
        self.framebuffer = int(gl.glGenFramebuffers(1))
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.framebuffer)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0,
                                  gl.GL_TEXTURE_2D, self.texture, 0)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT,
                                     gl.GL_RENDERBUFFER, self.depth)
        gl.glDrawBuffers(1, [gl.GL_COLOR_ATTACHMENT0])
        status = gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, previous)
        if status != gl.GL_FRAMEBUFFER_COMPLETE:
            self.release()
            raise RuntimeError('the water reflection target is incomplete (0x%x)'
                               % int(status))
        self.size = (width, height)

    def begin(self) -> None:
        """Draw into the target from here, cleared to nothing."""
        from OpenGL import GL as gl
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.framebuffer)
        gl.glViewport(0, 0, *self.size)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

    def bind(self) -> None:
        """Put the reflection on :data:`REFLECTION_UNIT` for the water to read."""
        from OpenGL import GL as gl
        gl.glActiveTexture(gl.GL_TEXTURE0 + self.UNIT)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def release(self) -> None:
        """Give back the target's GL names; the next use allocates again."""
        from OpenGL import GL as gl
        if self.framebuffer:
            gl.glDeleteFramebuffers(1, [self.framebuffer])
        if self.texture:
            gl.glDeleteTextures([self.texture])
        if self.depth:
            gl.glDeleteRenderbuffers(1, [self.depth])
        self.framebuffer = self.texture = self.depth = 0
        self.size = (0, 0)
