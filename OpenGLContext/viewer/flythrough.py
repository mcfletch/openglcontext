"""Moving the camera along the viewpoints a scene brought with it.

A recording of a scene that does not move is a picture with a file size. What
to move along is already in most scenes: the cameras their author placed. A
fly-through treats them as waypoints and walks the camera from the first to the
last over the length of the recording, so the path is the one the author chose
rather than one a viewer invented.

Nothing here touches GL or the scenegraph -- it is the arithmetic of where the
camera is at a given point along a path, which is what makes it checkable.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

from OpenGLContext.quaternion import Quaternion

__all__ = ['Pose', 'ease', 'pose_at', 'segment_at']

#: A place to be and a way to face: a position and an orientation quaternion.
Pose = Tuple[Sequence[float], Quaternion]


def ease(fraction: float) -> float:
    """Smooth the ends of a move, so it starts and stops rather than jerks.

    The classic smoothstep. A camera that begins at full speed reads as a cut
    and makes the first second of a recording unusable.
    """
    t = min(1.0, max(0.0, float(fraction)))
    return t * t * (3.0 - 2.0 * t)


def segment_at(count: int, fraction: float) -> Tuple[int, float]:
    """Which leg of a ``count``-waypoint path ``fraction`` is on, and how far.

    Returns the index of the waypoint the leg starts at and how far along that
    leg we are. At the very end it is the last leg, complete, rather than a
    leg that does not exist.
    """
    if count < 2:
        return 0, 0.0
    legs = count - 1
    place = min(1.0, max(0.0, float(fraction))) * legs
    index = min(legs - 1, int(place))
    return index, place - index


def pose_at(poses: Sequence[Pose], fraction: float,
            smooth: bool = True) -> Pose:
    """Where the camera is at ``fraction`` of the way along ``poses``.

    Positions are interpolated straight and orientations along the shorter arc,
    which is what makes a turn between two cameras look like a turn rather than
    a tumble. ``smooth`` eases each leg's ends.
    """
    if not poses:
        raise ValueError('a fly-through needs at least one viewpoint')
    if len(poses) == 1:
        return poses[0]
    index, along = segment_at(len(poses), fraction)
    if smooth:
        along = ease(along)
    (start, facing), (end, turned) = poses[index], poses[index + 1]
    position = [a + (b - a) * along for a, b in zip(start, end)]
    return position, facing.slerp(turned, along)


def poses_from(viewpoints: Sequence) -> List[Pose]:
    """The scene's ``Viewpoint`` nodes as a path, in the order they are declared.

    A viewpoint states its orientation the way VRML97 does -- an axis and an
    angle -- and the platform is turned by the reverse of it, which is the same
    convention :meth:`~OpenGLContext.move.viewplatform.ViewPlatform.setOrientation`
    applies when it is handed one.
    """
    from OpenGLContext import quaternion

    found: List[Pose] = []
    for viewpoint in viewpoints:
        x, y, z, angle = (float(v) for v in viewpoint.orientation)
        found.append(([float(v) for v in viewpoint.position],
                      quaternion.fromXYZR(x, y, z, -angle)))
    return found
