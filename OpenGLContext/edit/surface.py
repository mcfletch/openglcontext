"""Finding the point under the cursor, dragging it about, and reading the slope.

An editor's first question is *where on the world did they click?* and its
second is *where are they dragging it to?*. They have different answers.

The first is already read back by the pick: the selection pass writes depth as
well as an object id, so a mouse event arrives knowing how far away what it hit
was, and unprojecting that gives the point on the surface --
:func:`pointer_from`. It is exact, it costs nothing, and it works for streamed
terrain because terrain writes depth like any other geometry.

The second cannot use the depth, because once something is being dragged the
depth under the cursor is the thing being dragged. So a drag runs against a
*plane*: usually the level plane through where the drag began, so a point moves
across the ground without climbing the thing it is standing on --
:func:`ray_from` and :func:`ray_plane`.

The ground's *slope* comes from neither. Picking gives a point, not a normal;
the normal is the gradient of the height function, which the editor has --
:func:`surface_normal`, and :func:`height_gradient` for the slope itself.

The gradient answers a third question too: **where is the nearest ground at a
given height?** The shortest way to a contour is straight up or down the hill,
so it is a step along the gradient -- :func:`snap_to_height`. A road held to a
grade round a hillside runs *along* a contour, and an editor that can put a
point on one is the difference between drawing that road and approximating it.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

import numpy as np

from OpenGLContext.edit.tools import Pointer

__all__ = ['pointer_from', 'ray_from', 'ray_plane', 'horizon_plane',
           'surface_normal', 'height_gradient', 'snap_to_height']

#: How far apart the samples a slope is read from are, in metres. Small enough
#: to be local, large enough that a height function with noise in it reports
#: the slope of the ground rather than the slope of a grain of it.
GRADIENT_STEP = 2.0

#: How many times a snap steps towards its contour. The step is exact for
#: ground that rises evenly, so the rest is for ground that curves under it.
SNAP_STEPS = 4

#: A depth of 1 is the far plane: the pick found nothing there, so there is no
#: surface under the cursor to speak of.
NOTHING_THERE = 1.0 - 1e-6

UP = np.array([0.0, 1.0, 0.0])


def pointer_from(event: Any, node: Any = None) -> Pointer:
    """Where an event's cursor is, on the screen and on the world.

    The world position is the point the pick's depth puts under the cursor, or
    ``None`` where nothing was drawn there. ``node`` is what was picked, when
    the caller knows; nothing here goes looking for it.
    """
    x, y = event.getPickPoint()
    world = None
    view = tuple(getattr(event, 'viewCoordinate', ()) or ())
    if len(view) == 3 and float(view[-1]) < NOTHING_THERE:
        world = np.asarray(event.unproject(), dtype='d')
    shift, control, alt = event.getModifiers()
    return Pointer(x=x, y=y, world=world, node=node,
                   button=int(getattr(event, 'button', 0)),
                   modifiers=(shift, control, alt))


def ray_from(event: Any) -> Tuple[np.ndarray, np.ndarray]:
    """The eye ray through the cursor: ``(origin, unit direction)``.

    Taken from the near and far planes rather than from the camera's position,
    so it is right whatever the projection is -- an orthographic map view has
    no eye point for the rays to come from, and its rays are parallel.
    """
    x, y = event.getPickPoint()
    near = np.asarray(event.unproject((x, y, 0.0)), dtype='d')
    far = np.asarray(event.unproject((x, y, 1.0)), dtype='d')
    direction = far - near
    length = float(np.linalg.norm(direction))
    return near, direction / (length or 1.0)


def ray_plane(origin: Any, direction: Any, point: Any, normal: Any
              ) -> Optional[np.ndarray]:
    """Where a ray meets a plane, or ``None`` if it never does.

    ``None`` covers both ways that happens: a ray running along the plane, and
    one pointing away from it. Neither is a place the cursor is.
    """
    origin = np.asarray(origin, dtype='d')
    direction = np.asarray(direction, dtype='d')
    normal = np.asarray(normal, dtype='d')
    along = float(np.dot(direction, normal))
    if abs(along) < 1e-9:
        return None
    distance = float(np.dot(np.asarray(point, dtype='d') - origin, normal)) / along
    if distance < 0.0:
        return None
    hit: np.ndarray = origin + direction * distance
    return hit


def horizon_plane(height: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """The level plane at a height, as the ``(point, normal)`` a ray wants.

    What a drag runs against when the thing being dragged should stay at the
    height it started at rather than climbing whatever it passes over.
    """
    return np.array([0.0, float(height), 0.0]), UP.copy()


def surface_normal(height_fn: Callable[[Any, Any], Any], x: Any, z: Any,
                   step: float = 0.5) -> np.ndarray:
    """The up-vector of a height function at a point, from its gradient.

    ``step`` is the distance the gradient is measured over, in metres: small
    enough to be local, large enough that a height function with noise in it
    reports the slope of the ground rather than the slope of a grain of it.

    Answers a point with a ``(3,)`` vector and arrays with ``(N,3)``.
    """
    x = np.asarray(x, dtype='d')
    z = np.asarray(z, dtype='d')
    half = float(step) / 2.0
    dx = (np.asarray(height_fn(x + half, z), dtype='d')
          - np.asarray(height_fn(x - half, z), dtype='d')) / step
    dz = (np.asarray(height_fn(x, z + half), dtype='d')
          - np.asarray(height_fn(x, z - half), dtype='d')) / step
    normal = np.stack([-dx, np.ones_like(dx), -dz], axis=-1)
    length = np.linalg.norm(normal, axis=-1, keepdims=True)
    return np.asarray(normal / np.where(length > 0, length, 1.0))


def height_gradient(height_fn: Callable[[Any, Any], Any], x: Any, z: Any,
                    step: float = GRADIENT_STEP) -> Tuple[Any, Any]:
    """How fast the ground rises east and north at a point.

    A pair of rates, not a direction: the length of the pair is the steepness
    and its direction is straight up the hill. Central differences either side
    of the point, so a slope read on a valley floor is the valley's rather than
    that of whichever side the samples were taken from.
    """
    x = np.asarray(x, dtype='d')
    z = np.asarray(z, dtype='d')
    half = float(step) / 2.0
    east = (np.asarray(height_fn(x + half, z), dtype='d')
            - np.asarray(height_fn(x - half, z), dtype='d')) / float(step)
    north = (np.asarray(height_fn(x, z - half), dtype='d')
             - np.asarray(height_fn(x, z + half), dtype='d')) / float(step)
    return (east, north)


def snap_to_height(height_fn: Callable[[Any, Any], Any], x: float, z: float,
                   height: Optional[float] = None,
                   interval: float = 25.0, reach: float = 250.0,
                   step: float = GRADIENT_STEP) -> Tuple[float, float]:
    """The nearest ground at a given height, from a point.

    ``height`` is the elevation to land on; with none, the nearest multiple of
    ``interval``, which is the contour a designer is looking at. ``reach`` is
    how far the point may be moved: a contour half a kilometre away is not what
    the pointer meant, and a snap that drags a point across the map is worse
    than no snap.

    A step along the gradient, taken a few times: for ground that rises evenly
    the first step is exact, and the rest are for ground that curves under it.
    Flat ground has no nearest contour, so the point stays where it is.
    """
    at_x, at_z = float(x), float(z)
    here = float(np.asarray(height_fn(np.asarray([at_x]),
                                      np.asarray([at_z])))[0])
    target = (round(here / float(interval)) * float(interval)
              if height is None else float(height))
    for _ in range(SNAP_STEPS):
        east, north = height_gradient(height_fn, np.asarray([at_x]),
                                      np.asarray([at_z]), step)
        rise = float(east[0]) ** 2 + float(north[0]) ** 2
        if rise <= 1e-12:
            break
        current = float(np.asarray(height_fn(np.asarray([at_x]),
                                             np.asarray([at_z])))[0])
        # Straight up or down the hill by however far the ground has to rise:
        # for an even slope this lands exactly on the contour.
        scale = (target - current) / rise
        moved_x = at_x + float(east[0]) * scale
        # North is -z in the world, so a step north is a step down in z.
        moved_z = at_z - float(north[0]) * scale
        travelled = float(np.hypot(moved_x - float(x), moved_z - float(z)))
        if travelled > float(reach):
            fraction = float(reach) / max(travelled, 1e-9)
            return (float(x) + (moved_x - float(x)) * fraction,
                    float(z) + (moved_z - float(z)) * fraction)
        at_x, at_z = moved_x, moved_z
    return (at_x, at_z)
