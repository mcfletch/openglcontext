"""Opening an OGC 3D Tiles dataset (``tileset.json``) in a viewer.

Reading is :class:`~OpenGLContext.loaders.tiles3d.reader.TilesReader`'s; this
adds what a viewer asks of the scene: the dataset as a :class:`ViewerScene`
that opens inside it, and the per-frame work of paging tiles in against the
camera, from the viewer's idle loop (:meth:`TilesAdapter.update`).  An adapter
is instantiated per scene because the streaming runtime lives on it.
"""
from typing import Any

import numpy as np

from OpenGLContext.loaders.tiles3d.reader import (
    TilesReader, leaf_tile, opening_aim, opening_eye,
)
from OpenGLContext.viewer.adapters.base import SceneAdapter, ViewerScene

__all__ = ['TilesAdapter', 'leaf_tile', 'opening_aim', 'opening_pose']


def opening_pose(center: Any, radius: float, tile_radius: float = 0.0) -> Any:
    """The camera pose that arrives *in* a dataset rather than outside it.

    Looks at the content from :func:`~OpenGLContext.loaders.tiles3d.reader.opening_eye`.
    The near plane comes from the height rather than from the whole dataset, or
    a camera a few hundred metres up over a city would clip away everything
    below it.
    """
    from OpenGLContext.viewer import framing
    center = np.asarray(center, dtype='d')
    eye, height = opening_eye(center, radius, tile_radius)
    pose = framing.look_from(eye, center, radius)
    if pose is None:                    # pragma: no cover - height is never 0
        return None
    return pose._replace(near=max(0.05, height * 0.005), far=max(radius * 8.0,
                                                                height * 100.0))


def _forward(quaternion: Any) -> np.ndarray:
    """World-space look direction for a view platform's orientation."""
    rotation = np.asarray(quaternion.matrix())[:3, :3]
    forward: np.ndarray = rotation.T @ np.array([0.0, 0.0, -1.0])
    return forward


class TilesAdapter(TilesReader, SceneAdapter):
    """A streamed 3D Tiles dataset: bigger than memory, and still arriving."""

    #: Never re-centred.  A tileset's coordinates are the world's -- often
    #: Earth-centred, already shifted to the origin by the runtime for float
    #: precision -- and its tiles are placed in them.
    recentres = False

    def present(self, native: Any) -> ViewerScene:
        """The dataset as a scene, opening over its content when it is big enough.

        The stand-off follows the tile aimed at, so a dataset that is one
        object is seen whole rather than from inside it.
        """
        return self.sceneFor(native)

    def sceneFor(self, group: Any) -> ViewerScene:
        pose = opening_pose(self.aim, self.radius, self.aimRadius)
        return ViewerScene(group=group, center=tuple(self.center),
                           radius=self.radius, pose=pose,
                           metric=self.isGeospatial())

    def update(self, viewer: Any) -> bool:
        """Page tiles in for wherever the camera now is.  Once a frame."""
        if self.terrain is None:
            return False
        platform = getattr(viewer, 'platform', None)
        eye = self._eye(platform)
        self.terrain.update_for_camera(
            eye, viewer.getViewPort()[1] or 700,
            view_projection=self._viewProjection(viewer, platform, eye))
        return True

    # -- where the camera is ----------------------------------------------
    def _eye(self, platform: Any) -> tuple[float, ...]:
        if platform is None:
            return tuple(float(v) for v in self.center)
        return tuple(float(v) for v in platform.position[:3])

    def _viewProjection(self, viewer: Any, platform: Any,
                        eye: tuple[float, ...]) -> np.ndarray:
        """The matrix the streamer culls and measures error against.

        Built here rather than read from the renderer because the streamer runs
        *before* the frame it is preparing tiles for, and because a dataset
        spanning metres to kilometres needs near and far planes scaled to its
        own size rather than the viewer's defaults.
        """
        from OpenGLContext.loaders.tiles3d.frustum import view_projection
        quaternion = getattr(platform, 'quaternion', None)
        if quaternion is not None:
            forward = _forward(quaternion)
        else:
            forward = self.center - np.asarray(eye)
            if not np.asarray(forward).any():       # the eye is at the centre
                forward = np.array([0.0, 0.0, -1.0])
        target = np.asarray(eye) + np.asarray(forward) * self.radius
        width, height = viewer.getViewPort()
        aspect = (width / max(1, height)) or 1.0
        return view_projection(eye, tuple(target), (0, 1, 0), self.fov, aspect,
                               max(1e-4, self.radius * 0.02), self.radius * 60.0)
