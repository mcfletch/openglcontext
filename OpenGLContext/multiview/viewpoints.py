"""The cameras a scene carries, and pointing a view through one.

A VRML97 world declares its cameras as ``Viewpoint`` nodes, and the glTF
loader builds a ``Viewpoint`` for each camera a file defines, so to a view
they are one thing. The render pass keeps a path to every one of them and
publishes those paths as ``SceneGraph.viewpointPaths`` each frame (see
:mod:`OpenGLContext.passes.viewpointbinding`); :func:`scene_cameras` reads
them as :class:`SceneCamera` records, each where it stands in the world --
a Viewpoint inside a ``Transform`` is where that transform puts it::

    cameras = scene_cameras(context.getSceneGraph())
    look_through(view, first_camera(cameras))

A window is told when the set changes through
:meth:`~OpenGLContext.context.Context.OnViewpointsChanged`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Callable, Sequence
from typing import Any, Optional

import numpy as np

__all__ = [
    'SceneCamera', 'CameraChooser', 'scene_cameras', 'camera_at',
    'first_camera', 'look_through', 'platform_camera',
]

Vector = tuple[float, float, float]

#: Which camera of a scene's a view opens on: given them all, in the order the
#: scene declares them, answers one, or None for none of them.
CameraChooser = Callable[[Sequence['SceneCamera']], Optional['SceneCamera']]


@dataclass(frozen=True)
class SceneCamera:
    """One of a scene's cameras, where it stands in the world.

    ``forward`` and ``up`` are unit world directions. ``fov`` is the
    Viewpoint's ``fieldOfView`` in radians, read as the angle down the screen,
    as the view platform reads it. ``viewpoint`` is the node, and ``path`` the
    route to it the render pass found; either is None for a camera made some
    other way.
    """

    name: str
    position: Vector
    forward: Vector
    up: Vector
    fov: float
    viewpoint: Any = None
    path: Any = None


def _turned(vector: np.ndarray, axis: Sequence[float], angle: float) -> np.ndarray:
    """``vector`` turned ``angle`` radians about ``axis``, right-handed."""
    unit = np.asarray(axis, 'd')[:3]
    length = float(np.linalg.norm(unit))
    if length < 1e-12 or not angle:
        return vector
    unit = unit / length
    cos, sin = math.cos(angle), math.sin(angle)
    turned: np.ndarray = (vector * cos + np.cross(unit, vector) * sin
                          + unit * float(unit @ vector) * (1.0 - cos))
    return turned


def _unit(vector: np.ndarray) -> Vector:
    length = float(np.linalg.norm(vector)) or 1.0
    x, y, z = (float(value) / length for value in vector[:3])
    return (x, y, z)


def camera_at(viewpoint: Any, matrix: Any = None, name: str = '',
              path: Any = None) -> SceneCamera:
    """A Viewpoint as a camera, under a row-vector world ``matrix`` (None for none).

    ``name`` is used where the Viewpoint has no ``description``.
    """
    world = np.identity(4) if matrix is None else np.asarray(matrix, 'd')
    x, y, z, angle = (float(value) for value in viewpoint.orientation)
    forward = _turned(np.array([0.0, 0.0, -1.0]), (x, y, z), angle)
    up = _turned(np.array([0.0, 1.0, 0.0]), (x, y, z), angle)
    place = np.append(np.asarray(viewpoint.position, 'd')[:3], 1.0) @ world
    px, py, pz = (float(value) for value in place[:3] / (place[3] or 1.0))
    return SceneCamera(
        name=str(viewpoint.description) or name,
        position=(px, py, pz),
        forward=_unit(np.append(forward, 0.0) @ world),
        up=_unit(np.append(up, 0.0) @ world),
        fov=float(viewpoint.fieldOfView),
        viewpoint=viewpoint, path=path)


def platform_camera(platform: Any, name: str = '') -> SceneCamera:
    """Where a :class:`~OpenGLContext.move.viewplatform.ViewPlatform` stands, as a camera.

    What a view drawn through the window's own camera is seeded from when it
    is given one of its own. It names no Viewpoint.
    """
    position = np.asarray(platform.position, 'd')[:3]
    up = np.asarray(platform.quaternion * [0.0, 1.0, 0.0, 0.0], 'd')[:3]
    return SceneCamera(
        name=name,
        position=(float(position[0]), float(position[1]), float(position[2])),
        forward=_unit(platform.forward()), up=_unit(up),
        fov=math.radians(float(platform.frustum[0])))


def scene_cameras(scenegraph: Any) -> list[SceneCamera]:
    """Every camera the render pass has found in ``scenegraph``, in its order.

    Empty for a scene with none, for None, and for a scene no frame has drawn
    yet, since it is the pass that finds them. A Viewpoint with no
    ``description`` is named by its ``DEF``, or by its place in the list.
    """
    paths = getattr(scenegraph, 'viewpointPaths', None) or ()
    cameras = []
    for index, path in enumerate(paths):
        viewpoint = path[-1]
        cameras.append(camera_at(
            viewpoint, path.transformMatrix(),
            name=str(getattr(viewpoint, 'DEF', '') or '') or 'Camera %d' % (index + 1),
            path=path))
    return cameras


def first_camera(cameras: Sequence[SceneCamera]) -> Optional[SceneCamera]:
    """The first camera the scene declares, or None: VRML97's initial Viewpoint."""
    return cameras[0] if cameras else None


def look_through(view: Any, camera: SceneCamera,
                 distance: Optional[float] = None) -> bool:
    """Point ``view`` through ``camera``; False where there is no way to.

    A view with a camera of its own is given a perspective camera standing
    where ``camera`` stands, orbiting a point ``distance`` ahead of it (the
    distance it already orbited at where None). An orbiting camera is moved in
    place, so whatever else holds it goes on working. A view drawn through the
    window's own camera binds the Viewpoint instead, which the render pass
    moves the window's camera to; that needs a camera the pass found.
    """
    if view.camera is None:
        return _bind(camera)
    from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
    from OpenGLContext.multiview.cameras import shown_by
    orbit = getattr(view.camera, 'view', None)
    if not isinstance(orbit, OrbitView):
        if orbit is None:
            return False
        _centre, span = shown_by(orbit)
        replacement = OrbitView(nearest=1e-6, lowest=-OrbitView.HIGHEST)
        replacement.distance = span / 2.0 / math.tan(
            math.radians(replacement.fov) / 2.0)
        view.camera = OrbitViewPlatform(
            replacement, getattr(view.camera, 'viewport', (1, 1)))
        orbit = replacement
    orbit.fov = math.degrees(camera.fov)
    orbit.orthographic = False
    orbit.stand_at(camera.position, camera.forward,
                   orbit.distance if distance is None else distance)
    return True


def _bind(camera: SceneCamera) -> bool:
    """Bind the camera's Viewpoint in place of the one its scene has bound."""
    viewpoint, path = camera.viewpoint, camera.path
    if viewpoint is None or path is None:
        return False
    graph = path[0]
    bound = getattr(graph, 'boundViewpoint', None)
    if bound and bound is not viewpoint:
        bound.isBound = False
    viewpoint.isBound = True
    return True
