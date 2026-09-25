"""A geometry drawn under a mirroring transform is the mirror image of itself.

A transform whose determinant is negative -- a scale of -1 on one axis, a
glTF node mirrored in its modelling tool -- turns every triangle's winding
over. A geometry that culls its back faces has to turn its front face over
with it (:mod:`OpenGLContext.scenegraph.winding`), and its normals have to
follow; one that does not draws its inside, or nothing, or lights the wrong
side.

:func:`check_mirrored_render` draws a geometry in front of the camera, then
the same geometry inside a transform that mirrors the world across the plane
``x = 0``, which the camera looks along. The second picture is the first
turned left to right, and the helper fails where it is not::

    from OpenGLContext.testing.mirrored import check_mirrored_render

    def test_my_geometry_mirrors(scene_context):
        check_mirrored_render(MyGeometry(size=2.0))

The geometry is drawn in a ``Shape`` of a plain lit material unless an
``appearance`` is given, ``distance`` in front of a camera at the origin
looking down -z, through the renderer the ``environment`` names.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

import numpy as np

__all__ = ['MirroredRender', 'NotMirrored', 'check_mirrored_render',
           'mirrored_render']


class NotMirrored(AssertionError):
    """A geometry under a mirroring transform is not the mirror image of itself."""


@dataclass
class MirroredRender:
    """The two pictures, and how far the mirrored one is from the turned plain one.

    ``plain`` and ``mirrored`` are ``(H, W, 3)`` uint8 frames; ``drawn`` is
    the share of the plain frame the geometry covers, and ``differing`` the
    share of pixels whose largest channel differs by more than the
    tolerance between the mirrored frame and the plain one turned over.
    """

    plain: np.ndarray
    mirrored: np.ndarray
    drawn: float
    differing: float


def _scene(geometry: Any, appearance: Any, distance: float, mirror: bool) -> list:
    from OpenGLContext.scenegraph import basenodes
    shape = basenodes.Shape(geometry=geometry, appearance=appearance)
    placed = basenodes.Transform(translation=(0.0, 0.0, -float(distance)),
                                 children=[shape])
    if mirror:
        placed = basenodes.Transform(scale=(-1.0, 1.0, 1.0), children=[placed])
    return [basenodes.Viewpoint(position=(0.0, 0.0, 0.0)), placed]


def _frame(children: list, size: Tuple[int, int],
           environment: Optional[Mapping[str, str]], frames: int) -> np.ndarray:
    from OpenGLContext.testing.scenes import drawn_image, scene_context
    with scene_context(children, size=size, environment=environment) as context:
        for _ in range(frames):
            context.OnDraw(force=1)
        return drawn_image(context)


def mirrored_render(geometry: Any, *, appearance: Any = None,
                    distance: float = 4.0, size: Tuple[int, int] = (64, 64),
                    environment: Optional[Mapping[str, str]] = None,
                    tolerance: int = 24, frames: int = 2) -> MirroredRender:
    """Draw ``geometry`` plain and mirrored, and compare the two pictures."""
    from OpenGLContext.scenegraph import basenodes
    if appearance is None:
        appearance = basenodes.Appearance(material=basenodes.Material(
            diffuseColor=(0.8, 0.5, 0.2)))
    plain = _frame(_scene(geometry, appearance, distance, False), size,
                   environment, frames)
    mirrored = _frame(_scene(geometry, appearance, distance, True), size,
                      environment, frames)
    background = plain[0, 0].astype(int)
    drawn = float(np.mean(np.abs(plain.astype(int) - background).max(axis=2) > tolerance))
    turned = plain[:, ::-1]
    differing = float(np.mean(
        np.abs(mirrored.astype(int) - turned.astype(int)).max(axis=2) > tolerance))
    return MirroredRender(plain, mirrored, drawn, differing)


def check_mirrored_render(geometry: Any, *, most_differing: float = 0.02,
                          least_drawn: float = 0.01, **named: Any) -> MirroredRender:
    """The :class:`MirroredRender` of ``geometry``; raise where it does not mirror.

    Raises :class:`NotMirrored` where more than ``most_differing`` of the
    pixels differ, or where the plain picture shows the geometry over less
    than ``least_drawn`` of the frame (a picture of nothing mirrors
    trivially). ``named`` is passed to :func:`mirrored_render`.
    """
    found = mirrored_render(geometry, **named)
    name = type(geometry).__name__
    if found.drawn < least_drawn:
        raise NotMirrored('%s covers %.1f%% of the frame; place it where it is '
                          'seen' % (name, 100 * found.drawn))
    if found.differing > most_differing:
        raise NotMirrored('%s under a mirroring transform differs from its '
                          'mirror image over %.1f%% of the frame (%.1f%% '
                          'allowed): its winding or its normals do not follow '
                          'the transform' % (name, 100 * found.differing,
                                             100 * most_differing))
    return found
