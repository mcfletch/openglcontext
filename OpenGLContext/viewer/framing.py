"""Where to put the camera to see a thing.

Two ways of aiming, both returning a :class:`CameraPose` rather than moving
anything: a viewer applies one to its view platform, and the arithmetic can be
checked without a window.

* :func:`fit_sphere` -- back off far enough that a sphere of a given radius fits
  in the field of view, slightly raised and tilted down.  What a viewer does
  when it is asked to show a whole model.
* :func:`look_from` -- stand at a given point and look at another.  For the
  shots the on-axis fit cannot express, such as standing inside a building
  looking along its arcade.
"""
from math import asin, atan2, pi, sin
from typing import Any, NamedTuple, Optional, Sequence, Tuple

import numpy as np

__all__ = ['CameraPose', 'fit_sphere', 'look_from', 'DEFAULT_FOV',
           'DEFAULT_MARGIN', 'DEFAULT_ELEVATION', 'DEFAULT_TILT']

#: Vertical field of view a viewer frames with, in radians -- a touch under 60
#: degrees, wide enough to give a sense of the space without visible distortion
#: at the edges.
DEFAULT_FOV = pi / 3.2

#: Fit factor: how much bigger than the model's bounding sphere the framed view
#: is.  Below 1 pulls the camera in, which is what a wide flat model wants --
#: its bounding sphere overstates the footprint that is actually visible.
DEFAULT_MARGIN = 1.15
#: Camera height as a fraction of the model radius.
DEFAULT_ELEVATION = 0.22
#: Downward camera tilt, in radians.
DEFAULT_TILT = 0.10


class CameraPose(NamedTuple):
    """A place to stand, a way to face, and the frustum to see it through."""

    position: Tuple[float, float, float]
    #: VRML axis/angle, or None when :attr:`quaternion` carries the aim instead.
    orientation: Optional[Tuple[float, float, float, float]]
    fov: float
    near: float
    far: float
    #: Set when the aim cannot be said as a single axis/angle rotation.
    quaternion: Any = None


def fit_sphere(radius: float, margin: Optional[float] = None,
               elevation: Optional[float] = None,
               tilt: Optional[float] = None,
               fov: float = DEFAULT_FOV) -> CameraPose:
    """Frame a centred model of ``radius``, looking down -Z.

    The distance is what it takes for a sphere of that radius to fill ``fov``,
    scaled by ``margin``; the camera is lifted by ``elevation`` of the radius
    and tilted ``tilt`` down, so the model is seen slightly from above rather
    than dead level.  The three-quarter angle comes from turning the *model*,
    not the camera, so the framing stays the same whatever the model's facing.

    The near and far planes are set from the radius as well.  A fixed near
    plane cannot serve a viewer that opens both a bolt and a city: too far and
    the bolt is clipped away, too near and the city has no depth precision left.
    """
    margin = DEFAULT_MARGIN if margin is None else margin
    elevation = DEFAULT_ELEVATION if elevation is None else elevation
    tilt = DEFAULT_TILT if tilt is None else tilt
    distance = radius / max(1e-3, sin(fov / 2.0)) * margin
    return CameraPose(
        position=(0.0, radius * elevation, distance),
        orientation=(1.0, 0.0, 0.0, tilt),
        fov=fov, near=max(1e-4, radius * 0.02), far=radius * 60.0)


def look_from(eye: Sequence[float], target: Sequence[float], radius: float,
              fov: float = DEFAULT_FOV) -> Optional[CameraPose]:
    """Stand at ``eye`` and look at ``target``, both in world space.

    None when the two coincide, which names no direction at all -- the caller
    leaves the camera where it was rather than aiming it at nothing.

    The aim is a yaw about +Y and a pitch about X, because a camera at identity
    looks down -Z; it comes back as a quaternion since composing two rotations
    is not an axis/angle.

    A view platform holds the rotation that takes the *world* into the camera's
    frame, which is the inverse of the camera's own: the pitch turns the other
    way, and it is applied before the yaw rather than after. Composed the
    intuitive way round, an aim below the horizon renders as the same angle
    above it -- which is why
    :meth:`tests.unit.test_viewer_framing.TestLookFromAimsWhereItSays` checks
    the direction the platform's matrix really faces rather than the angles
    that went in.
    """
    from OpenGLContext import quaternion
    origin = np.asarray(eye, dtype='d')
    forward = np.asarray(target, dtype='d') - origin
    length = float(np.linalg.norm(forward))
    if length < 1e-9:
        return None
    forward = forward / length
    yaw = atan2(forward[0], -forward[2])                    # 0 looks down -Z
    pitch = asin(max(-1.0, min(1.0, forward[1])))           # + looks up
    aim = (quaternion.fromXYZR(1, 0, 0, -pitch)
           * quaternion.fromXYZR(0, 1, 0, yaw))
    return CameraPose(
        position=(float(origin[0]), float(origin[1]), float(origin[2])),
        orientation=None,
        fov=fov, near=max(1e-3, radius * 0.01), far=radius * 8.0,
        quaternion=aim)
