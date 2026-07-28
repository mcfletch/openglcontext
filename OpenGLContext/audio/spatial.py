"""Where a sound is, and how loud it is from where you are standing.

Every function here is a pure function of geometry returning a **linear
amplitude multiplier** in ``[0, 1]``.  The engine multiplies them together --
distance, cone, emitter gain, source gain -- and hands the product to the mixer,
so each curve can be reasoned about, plotted and tested on its own.

Two attenuation models live here because two specifications describe sounds in
this codebase:

* **The glTF model** (:func:`distance_gain`, :func:`cone_gain`).  A distance
  curve plus a directional cone, from ``KHR_audio_emitter``, which takes them
  from the Web Audio API's ``PannerNode``.  This is the model authoring tools
  export and the one new content should use.
* **The VRML97 model** (:func:`ellipsoid_reach`, :func:`ellipsoid_gain`).  Two
  ellipsoids sharing a focus at the sound, with a ramp between them that is
  linear in decibels.  A VRML97 ``Sound`` node says exactly this and nothing
  else can express it, so it is implemented rather than approximated.

Panning is shared: :meth:`Listener.azimuth_elevation` puts the source in the
listener's own frame and :func:`equal_power_pan` turns the azimuth into a pair
of ear gains.

References:
    ``KHR_audio_emitter``
    https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/KHR_audio_emitter

    Web Audio API, "Spatialization"
    https://webaudio.github.io/web-audio-api/#Spatialization

    ISO/IEC 14772-1:1997 (VRML97) 6.42 ``Sound``
    https://www.web3d.org/documents/specifications/14772/V2.0/part1/nodesRef.html#Sound
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence, Tuple, Union

import numpy as np

#: Radians in a full turn.  ``KHR_audio_emitter`` defaults both cone angles to
#: this, meaning "not a cone at all".
TAU = 2.0 * math.pi

#: The attenuation VRML97 puts at the outer ellipsoid, in decibels.  It calls
#: that inaudible, so the gain is forced to zero beyond it; the resulting step
#: from 0.1 to 0 is smoothed by the mixer's per-block gain ramp rather than
#: being fudged here, so this function stays the specification's own curve.
INAUDIBLE_DB = -20.0


class DistanceModel(str, Enum):
    """How an emitter's gain falls off with distance (``KHR_audio_emitter``).

    The values are the strings the glTF extension writes, so a parsed document's
    ``distanceModel`` is usable as a member without translation.
    """

    LINEAR = 'linear'
    INVERSE = 'inverse'
    EXPONENTIAL = 'exponential'


class ShapeType(str, Enum):
    """Whether a positional emitter radiates evenly or within a cone."""

    OMNIDIRECTIONAL = 'omnidirectional'
    CONE = 'cone'


Vector = Union[Sequence[float], np.ndarray]


def _unit(vector: Vector) -> np.ndarray:
    """``vector`` scaled to unit length; a zero vector is returned unchanged."""
    array = np.asarray(vector, dtype='d')[:3]
    length = float(np.linalg.norm(array))
    return array if length == 0.0 else array / length


def distance_gain(
    distance: float,
    model: Union[DistanceModel, str] = DistanceModel.INVERSE,
    ref_distance: float = 1.0,
    max_distance: float = 0.0,
    rolloff_factor: float = 1.0,
) -> float:
    """Gain for a source ``distance`` away under one of the glTF distance models.

    ``ref_distance`` is where the curve reads 1.0 and inside which nothing is
    attenuated; ``rolloff_factor`` is how sharply it falls; ``max_distance`` is
    where it stops falling -- **zero means unbounded**, which is the extension's
    own default.

    The ``linear`` model is the only one that reaches silence, and it does so at
    ``max_distance``; the other two approach it asymptotically.  A ``linear``
    emitter therefore needs a ``max_distance`` to mean anything, and one greater
    than ``ref_distance``.

    Raises:
        ValueError: if ``ref_distance`` is not positive, which every model
            divides by.
    """
    if ref_distance <= 0.0:
        raise ValueError('ref_distance must be greater than zero, not %r' % (ref_distance,))
    model = DistanceModel(model)
    # Both ends are clamped before the curve: inside the reference distance the
    # gain is 1, and past the maximum it simply stops falling.
    if max_distance > 0.0:
        distance = min(distance, max_distance)
    distance = max(distance, ref_distance)
    if model is DistanceModel.INVERSE:
        return ref_distance / (ref_distance + rolloff_factor * (distance - ref_distance))
    if model is DistanceModel.EXPONENTIAL:
        return float((distance / ref_distance) ** -rolloff_factor)
    if max_distance <= ref_distance:
        # A linear ramp with no room to ramp: audible at the reference distance
        # and silent everywhere past it.
        return 1.0 if distance <= ref_distance else 0.0
    span = (distance - ref_distance) / (max_distance - ref_distance)
    return max(0.0, min(1.0, 1.0 - rolloff_factor * span))


def cone_gain(
    angle: float,
    inner_angle: float = TAU,
    outer_angle: float = TAU,
    outer_gain: float = 0.0,
) -> float:
    """Gain for a listener ``angle`` radians off an emitter's forward axis.

    ``inner_angle`` and ``outer_angle`` are *angular diameters* -- the whole cone
    from side to side -- so the boundaries are at half of each.  Inside the inner
    cone there is no attenuation; outside the outer cone the gain is
    ``outer_gain``; between them it interpolates linearly.

    The defaults describe a full sphere, which is why an emitter that never sets
    them is never attenuated by direction.
    """
    inner = abs(inner_angle) / 2.0
    outer = abs(outer_angle) / 2.0
    angle = abs(angle)
    if angle <= inner:
        return 1.0
    if angle >= outer:
        return outer_gain
    across = (angle - inner) / (outer - inner)
    return (1.0 - across) + outer_gain * across


def ellipsoid_reach(front: float, back: float, cos_theta: float) -> float:
    """Distance from a VRML97 ``Sound``'s location to its ellipsoid surface.

    The four distance fields describe an ellipsoid **with one focus at the
    sound**, reaching ``front`` along ``direction`` and ``back`` against it.
    Measuring from the focus rather than the centre makes the surface a focal
    conic, whose polar form collapses to::

        reach(theta) = 2 * front * back / ((front + back) - (front - back) * cos(theta))

    -- the harmonic mean of the two distances at right angles, and each distance
    itself along the axis.  ``cos_theta`` is the cosine of the angle between the
    sound's ``direction`` and the direction to the listener.

    A ``front`` or ``back`` of zero describes an ellipsoid with no interior, so
    the reach is zero in every direction.
    """
    if front <= 0.0 or back <= 0.0:
        return 0.0
    return 2.0 * front * back / ((front + back) - (front - back) * cos_theta)


def ellipsoid_gain(
    distance: float,
    cos_theta: float,
    min_front: float = 1.0,
    min_back: float = 1.0,
    max_front: float = 10.0,
    max_back: float = 10.0,
) -> float:
    """VRML97's gain between a ``Sound``'s inner and outer ellipsoids.

    Full volume inside the inner ellipsoid, silence outside the outer, and
    between them a ramp that is linear **in decibels** from 0 dB down to
    :data:`INAUDIBLE_DB`.  Linear in decibels rather than in amplitude is what
    makes the sound fade the way a listener expects instead of vanishing at the
    end of the ramp.

    Coincident ellipsoids leave no room to ramp, so the sound is at full volume
    inside them and silent outside.
    """
    inner = ellipsoid_reach(min_front, min_back, cos_theta)
    outer = ellipsoid_reach(max_front, max_back, cos_theta)
    if distance <= inner:
        return 1.0
    if distance > outer:
        return 0.0
    across = (distance - inner) / (outer - inner)
    return float(10.0 ** (INAUDIBLE_DB * across / 20.0))


def equal_power_pan(azimuth: float) -> Tuple[float, float]:
    """Left and right gains for a mono source ``azimuth`` radians off centre.

    Positive azimuth is to the listener's right.  The two gains trace a quarter
    circle, so ``left**2 + right**2`` is 1 at every angle: panning moves a sound
    across the stereo field without changing how loud it is.

    A source behind the listener is folded onto its mirror image in front --
    behind-and-right pans right.  Two loudspeakers cannot put a sound behind
    anybody, and the fold is what the Web Audio API specifies rather than
    something chosen here.
    """
    if azimuth < -math.pi / 2:
        azimuth = -math.pi - azimuth
    elif azimuth > math.pi / 2:
        azimuth = math.pi - azimuth
    across = (azimuth + math.pi / 2) / math.pi
    return math.cos(across * math.pi / 2), math.sin(across * math.pi / 2)


@dataclass(frozen=True)
class Listener:
    """Where the ears are, and which way they face.

    One per engine, refreshed each frame from the view platform.  ``forward``
    and ``up`` are normalised on construction so callers may pass whatever
    length falls out of their own maths.
    """

    #: World-space position of the listener.
    position: np.ndarray
    #: Unit vector the listener faces; ``-Z`` in the glTF and VRML97 default view.
    forward: np.ndarray
    #: Unit vector out of the top of the listener's head.
    up: np.ndarray

    def __init__(self, position: Vector = (0.0, 0.0, 0.0),
                 forward: Vector = (0.0, 0.0, -1.0),
                 up: Vector = (0.0, 1.0, 0.0)) -> None:
        object.__setattr__(self, 'position', np.asarray(position, dtype='d')[:3])
        object.__setattr__(self, 'forward', _unit(forward))
        object.__setattr__(self, 'up', _unit(up))

    @property
    def right(self) -> np.ndarray:
        """Unit vector out of the listener's right ear."""
        return _unit(np.cross(self.forward, self.up))

    @classmethod
    def from_view_platform(cls, platform: Any) -> 'Listener':
        """The listener implied by a :class:`~OpenGLContext.move.viewplatform.ViewPlatform`.

        The camera *is* the listener: a scene with sound in it wants the two to
        agree, and there is nothing an application would have to keep in step if
        the pose is read from the platform every frame.
        """
        rotation = platform.quaternion
        forward = np.asarray(rotation * [0.0, 0.0, -1.0, 0.0], dtype='d')[:3]
        up = np.asarray(rotation * [0.0, 1.0, 0.0, 0.0], dtype='d')[:3]
        return cls(position=np.asarray(platform.position, dtype='d')[:3],
                   forward=forward, up=up)

    def distance_to(self, point: Vector) -> float:
        """Straight-line distance from the listener to ``point``."""
        return float(np.linalg.norm(np.asarray(point, dtype='d')[:3] - self.position))

    def azimuth_elevation(self, point: Vector) -> Tuple[float, float]:
        """``point`` as a bearing from the listener, in radians.

        Azimuth is measured in the listener's horizontal plane: 0 dead ahead,
        positive to the right, ``+-pi`` behind.  Elevation is the angle out of
        that plane, positive overhead.

        A point *at* the listener has no bearing at all; it is reported as dead
        ahead so that a sound placed on the camera pans to the centre rather
        than producing a division by zero.
        """
        offset = np.asarray(point, dtype='d')[:3] - self.position
        length = float(np.linalg.norm(offset))
        if length == 0.0:
            return 0.0, 0.0
        offset = offset / length
        vertical = float(np.dot(offset, self.up))
        horizontal = offset - vertical * self.up
        elevation = math.asin(max(-1.0, min(1.0, vertical)))
        if not np.any(horizontal):
            # Directly overhead or underfoot: no horizontal bearing exists.
            return 0.0, elevation
        azimuth = math.atan2(float(np.dot(horizontal, self.right)),
                             float(np.dot(horizontal, self.forward)))
        return azimuth, elevation
