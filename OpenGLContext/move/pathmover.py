"""Running along a course and hopping between its lanes; no GL, no physics.

A game with a course rather than open land wants its character to follow a line
and to hop sideways between parallel lanes of it. :class:`PathMover` answers,
each frame, the horizontal velocity that does that for a character at a given
position:

    mover = PathMover(course, speed=10.0)
    ...
    step = mover.update(character.position, dt)
    character.set_move(step.direction, speed=step.speed)
    ...
    mover.hop_to(2.0, over=0.16)                # one lane to the right

The course is a :class:`~OpenGLContext.scenegraph.roadcourse.RoadCourse`.
The velocity is ``speed`` metres a second along the course's tangent at the
character's station, plus the sideways velocity that brings the character onto
its lane: the rate the lane itself is moving at during a hop, and a correction
of the character's offset from the lane. A character the controller pushed off
the line is steered back to it, and the height is the controller's: the
velocity has no vertical part.

A lane is a distance in metres to the right of the centreline, the right being
the side ``cross(tangent, up)`` names (``+x`` for a course running toward
``-z``). A hop eases the lane to a new one with a smoothstep over a given time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from OpenGLContext.scenegraph.roadcourse import RoadCourse

__all__ = ['PathMover', 'PathStep']


@dataclass(frozen=True)
class PathStep:
    """What a character should do this frame to stay on its course."""

    #: Metres a second, horizontal: ``(x, 0, z)``.
    velocity: tuple[float, float, float]
    #: The unit vector of ``velocity``, or zeros when it is zero.
    direction: tuple[float, float, float]
    #: The length of ``velocity``.
    speed: float
    #: Metres along the course the character is.
    station: float
    #: Metres the character is to the right of the centreline.
    lateral_error: float


def _smoothstep(fraction: float) -> float:
    return fraction * fraction * (3.0 - 2.0 * fraction)


class PathMover:
    """The velocity that keeps one character on a lane of a course.

    ``speed`` is the metres a second travelled along the course, and may be set
    at any time. ``lane`` is the starting lateral offset. ``steer_gain`` is the
    rate per second at which an offset from the lane is closed; it is limited
    to the reciprocal of the frame time so a long frame corrects once and does
    not overshoot.
    """

    def __init__(self, course: RoadCourse, speed: float = 0.0, *,
                 lane: float = 0.0, steer_gain: float = 12.0) -> None:
        self.course = course
        self.speed = float(speed)
        self.steer_gain = float(steer_gain)
        #: True once an open course has been run to its end.
        self.finished = False
        self._tracker = course.tracker()
        points = course.centreline
        stations = course.stations
        if course.closed:
            points = np.vstack([points, points[:1]])
            stations = np.append(stations, course.length)
        self._points = points
        self._stations = stations
        self._tangents = self._tangents_of(points)
        self._from = self._to = float(lane)
        self._over = 0.0
        self._elapsed = 0.0

    @staticmethod
    def _tangents_of(points: np.ndarray) -> np.ndarray:
        """The unit horizontal direction of each segment of ``points``.

        A segment of no length takes the direction of the nearest one that
        has some, and a course with none runs toward -z.
        """
        delta = np.diff(points[:, [0, 2]], axis=0)
        length = np.linalg.norm(delta, axis=1)
        known = np.flatnonzero(length > 1e-9)
        if not len(known):
            return np.tile([0.0, -1.0], (len(delta), 1))
        nearest = known[np.abs(np.arange(len(delta))[:, None] - known).argmin(axis=1)]
        return np.asarray(delta[nearest] / length[nearest, None])

    # -- lanes ------------------------------------------------------------
    @property
    def lane(self) -> float:
        """The lateral offset the character is steered toward now, in metres."""
        return self._lane_at(self._elapsed)

    @property
    def hopping(self) -> bool:
        """Whether the lane is still moving to a new one."""
        return self._elapsed < self._over

    def hop_to(self, offset: float, over: float = 0.16) -> None:
        """Move the lane to ``offset`` metres right of the line over ``over`` seconds.

        A hop begun during another starts from the lane the first had reached.
        """
        self._from = self.lane
        self._to = float(offset)
        self._over = max(float(over), 0.0)
        self._elapsed = 0.0

    def _lane_at(self, elapsed: float) -> float:
        if elapsed >= self._over:
            return self._to
        return self._from + (self._to - self._from) * _smoothstep(elapsed / self._over)

    def reset(self) -> None:
        """Forget where the character was, so the next frame searches the whole
        course, and run it again if it had ended."""
        self._tracker.forget()
        self.finished = False

    # -- the frame --------------------------------------------------------
    def update(self, position: Any, dt: float) -> PathStep:
        """The step for a character at ``position``, ``dt`` seconds after the last."""
        here = np.asarray(position, dtype='d').reshape(-1)[:3]
        station = self._tracker.station_of(here)
        centre, tangent = self._frame_at(station)
        right = np.array([-tangent[1], tangent[0]])
        offset = float((here[[0, 2]] - centre) @ right)
        before = self.lane
        if dt > 0.0:
            self._elapsed += dt
        after = self.lane
        rate = (after - before) / dt if dt > 0.0 else 0.0
        gain = self.steer_gain if dt <= 0.0 else min(self.steer_gain, 1.0 / dt)
        sideways = rate + gain * (before - offset)
        self.finished = not self.course.closed and station >= self.course.length - 1e-6
        forward = 0.0 if self.finished else self.speed
        move = forward * tangent + (0.0 if self.finished else sideways) * right
        length = float(math.hypot(*move))
        velocity = (float(move[0]), 0.0, float(move[1]))
        direction = ((float(move[0] / length), 0.0, float(move[1] / length))
                     if length > 1e-12 else (0.0, 0.0, 0.0))
        return PathStep(velocity, direction, length, station, offset)

    def _frame_at(self, station: float) -> tuple[np.ndarray, np.ndarray]:
        """The centreline point and unit tangent at ``station``, on the ground."""
        stations = self._stations
        at = min(max(station, float(stations[0])), float(stations[-1]))
        point = np.array([np.interp(at, stations, self._points[:, axis])
                          for axis in (0, 2)])
        segment = min(max(int(np.searchsorted(stations, at, side='right')) - 1, 0),
                      len(self._tangents) - 1)
        return point, self._tangents[segment]
