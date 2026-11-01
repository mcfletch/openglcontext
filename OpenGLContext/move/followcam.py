"""A follow camera for third-person / overhead demos.

The camera sits at an offset from a target and looks at it - no user control,
no orbiting.  Each frame the caller sets the target (usually a moving object's
position) and calls :meth:`apply`, which writes the position and orientation
onto a :class:`~OpenGLContext.move.viewplatform.ViewPlatform`.

It also supports **holding**: freeze on the current target and ignore new ones
until released.  The marble demo uses this to keep the view locked on the square a
marble fell from while the respawn penalty elapses, instead of chasing the marble
into the void.

And it supports **pulling back**: a camera at one fixed distance shows the same
amount of world at every speed, which is least useful exactly when the target is
moving fastest and the player most needs to see what is coming.  Give it a
``pull_back`` fraction and feed :meth:`advance` the target's speed each frame, and
the offset eases outward with speed and back in again as the target slows.  The
default is zero, so a camera that does not ask for it behaves exactly as before.

A chase camera adds four things to the fixed offset, each off by default and
each taking effect in :meth:`advance`, which a frame calls with its time step
between :meth:`target` and :meth:`apply`:

* **Looking ahead.** With ``look_ahead`` seconds the point looked at moves
  along the target's velocity, given to :meth:`target` or taken from how far
  the target moved since the last frame.
* **Gliding.** With ``smooth_time`` seconds the point looked at follows the
  target as a critically damped spring does: it reaches the target in about
  that time, never passes it, and takes the same time at any frame rate.
* **Keeping out of the scenery.** Given a ``sweep(origin, direction,
  distance, radius)`` that answers the distance to the first thing a sphere
  of ``radius`` meets going from ``origin`` along ``direction``, or None, the
  arm from the look point to the camera shortens to what the sphere meets
  between the camera and the subject (the target, or the ``subject`` given
  to :meth:`target`) at once, and eases back out at ``arm_ease`` per second.
  The sweep starts where the arm passes the subject, so what lies between the
  subject and a look point ahead of it does not pull the camera in, and the
  camera stays at least ``min_arm`` metres further out along the arm than
  the subject. A physics service's ``sweep_sphere`` is such a function, and
  so is any ray cast against a collision mesh.
* **A game's own rule.** :meth:`constrain` adds ``rule(eye, look)`` returning
  the ``(eye, look)`` to use, applied in the order added and before the sweep.

``max_step`` limits how far the camera moves in one frame, in metres. A frame
the sweep pulls the camera in is exempt, since a camera held back inside a wall
is worse than one that jumps in front of it. :meth:`snap` puts the camera on the
target at once, which is how a teleport is shown.

Orientation convention: this targets the **core-profile** view path, where
``ViewPlatform`` builds the modelview from ``modelMatrix`` /
``quaternion.matrix``.  :func:`look_at_orientation` returns the VRML axis-angle
that (after ``setOrientation`` negates it, as it does for every VRML orientation)
places the target on the camera's view -Z axis - verified end-to-end against
``ViewPlatform.modelMatrix`` in ``tests/test_followcam.py``.
"""
import math
from collections.abc import Callable
from typing import Any, Optional

import numpy as np

from OpenGLContext import quaternion


#: ``sweep(origin, direction, distance, radius)``: how far a sphere goes along
#: ``direction`` before meeting something, or None if it goes ``distance``.
Sweep = Callable[[np.ndarray, np.ndarray, float, float], Optional[float]]
#: ``rule(eye, look)``: the ``(eye, look)`` to use instead.
Rule = Callable[[np.ndarray, np.ndarray], tuple[Any, Any]]


def _normalize(v: Any) -> np.ndarray:
    v = np.asarray(v, dtype='d')
    n = np.linalg.norm(v)
    return np.asarray(v / n) if n > 1e-12 else v


def look_at_orientation(eye: Any, target: Any,
                        up: Any = (0.0, 1.0, 0.0)) -> tuple[float, float, float, float]:
    """VRML axis-angle ``(x, y, z, radians)`` orienting a camera at ``eye`` to
    look at ``target``.

    Builds the camera basis (right, up, backward) in world space and converts the
    resulting rotation matrix to an axis-angle.  ``up`` is the desired world up;
    pass a different up (e.g. ``(0,0,-1)``) when looking straight down, where the
    default up is degenerate.
    """
    eye = np.asarray(eye, dtype='d')
    target = np.asarray(target, dtype='d')

    backward = _normalize(eye - target)             # camera local +Z
    right = _normalize(np.cross(_normalize(up), backward))  # camera local +X
    true_up = np.cross(backward, right)             # camera local +Y
    # Columns are where the camera's local x/y/z land in world space (the
    # camera-local → world rotation).  ViewPlatform.setOrientation negates the
    # angle and the core modelMatrix consumes it so this basis becomes the view.
    R = np.column_stack([right, true_up, backward])
    return _matrix_to_axis_angle(R)


def _matrix_to_axis_angle(R: np.ndarray) -> tuple[float, float, float, float]:
    """A 3x3 rotation matrix as VRML axis-angle ``(x, y, z, radians)``.

    ``R``'s columns are where the rotated frame's axes land, which is the
    column-vector convention; :func:`quaternion.fromMatrix` reads the
    row-vector one the rest of the engine composes in, so it is handed the
    transpose.
    """
    x, y, z, r = quaternion.fromMatrix(np.asarray(R, 'd').T).XYZR()
    return float(x), float(y), float(z), float(r)


class FollowCamera:
    """Drive a ``ViewPlatform`` to an offset from a target, looking at it."""

    def __init__(self, platform: Any, offset: Any = (0.0, 14.0, 14.0),
                 up: Any = (0.0, 1.0, 0.0), pull_back: float = 0.0,
                 pull_back_speed: float = 1.0, pull_back_rate: float = 3.0,
                 *, look_ahead: float = 0.0, smooth_time: float = 0.0,
                 sweep: Optional[Sweep] = None, avoid_radius: float = 0.3,
                 min_arm: float = 0.5, arm_ease: float = 4.0,
                 max_step: Optional[float] = None) -> None:
        """Follow ``platform``'s target from ``offset``, ``up`` fixing the roll.

        ``pull_back`` is the extra fraction of ``offset`` the camera reaches at
        ``pull_back_speed`` -- 0.5 means half again as far away -- ramping
        linearly from nothing at a standstill and holding at the limit above that
        speed.  ``pull_back_rate`` is how quickly the distance eases toward the
        one the current speed asks for, in nats per second: higher is snappier,
        and the easing is what keeps a speed spike from snapping the view.

        With the default ``pull_back`` of zero the distance never changes and
        :meth:`advance` need not be called at all.

        ``look_ahead`` is seconds of the target's velocity the look point is
        moved by, and ``smooth_time`` the seconds the look point takes to
        glide to the target. ``sweep`` keeps the arm out of the scenery: its
        sphere has radius ``avoid_radius`` metres, the arm is no shorter than
        ``min_arm`` metres, and it eases back out at ``arm_ease`` per second.
        ``max_step`` is the furthest in metres the camera moves in a frame, or
        None for no limit.
        """
        self.platform = platform
        self.offset = np.asarray(offset, dtype='d')
        self.up = np.asarray(up, dtype='d')
        self.pull_back = float(pull_back)
        # A zero or negative full-speed would divide by nothing / invert the ramp.
        self.pull_back_speed = max(float(pull_back_speed), 1e-6)
        self.pull_back_rate = float(pull_back_rate)
        self.look_ahead = float(look_ahead)
        self.smooth_time = float(smooth_time)
        self.sweep = sweep
        self.avoid_radius = float(avoid_radius)
        self.min_arm = float(min_arm)
        self.arm_ease = float(arm_ease)
        self.max_step = None if max_step is None else float(max_step)
        self._distance_scale = 1.0
        self._target = np.zeros(3)
        self._subject: Optional[np.ndarray] = None
        self._held_target: Optional[np.ndarray] = None
        self._rules: list[Rule] = []
        self._given_velocity: Optional[np.ndarray] = None
        self._velocity = np.zeros(3)
        self._last_target: Optional[np.ndarray] = None
        self._glide: Optional[np.ndarray] = None
        self._glide_velocity = np.zeros(3)
        self._squeeze = 1.0
        self._pose: Optional[tuple[np.ndarray, np.ndarray]] = None
        self._solved = False

    def target(self, position: Any, velocity: Any = None, subject: Any = None) -> None:
        """Record the live point to follow, and optionally how fast it moves.

        Always updates the live target; while holding, :meth:`apply` simply
        ignores it, so on :meth:`release` the camera snaps to the most recent
        live target rather than a stale one. ``velocity`` is what ``look_ahead``
        looks along; left out, it is worked out from how far the target moved
        since the last :meth:`advance`. ``subject`` is the point the camera
        has to keep in view, where the target is a point ahead of it, such as
        a chase camera's look point ahead of a runner; left out, it is the
        target. The sweep keeps the arm clear from the camera to the subject.
        """
        self._target = np.asarray(position, dtype='d')[:3]
        self._subject = None if subject is None else np.asarray(subject, dtype='d')[:3]
        self._given_velocity = (None if velocity is None
                                else np.asarray(velocity, dtype='d')[:3])
        self._solved = False

    def hold(self) -> None:
        """Freeze the camera on the current target until :meth:`release`."""
        if self._held_target is None:
            self._held_target = self._target.copy()

    def release(self) -> None:
        """Resume following live targets."""
        self._held_target = None

    @property
    def is_holding(self) -> bool:
        return self._held_target is not None

    @property
    def active_target(self) -> np.ndarray:
        return self._held_target if self._held_target is not None else self._target

    @property
    def distance_scale(self) -> float:
        """What the offset is currently multiplied by; 1.0 at a standstill."""
        return self._distance_scale

    def constrain(self, rule: Rule) -> Rule:
        """Add ``rule(eye, look)``, which returns the ``(eye, look)`` to use.

        Rules apply in the order added, to the pose the offset gives, before
        the sweep. Returns ``rule`` so it can be given to :meth:`unconstrain`.
        """
        self._rules.append(rule)
        self._solved = False
        return rule

    def unconstrain(self, rule: Rule) -> None:
        """Take a rule added by :meth:`constrain` away."""
        self._rules.remove(rule)
        self._solved = False

    def snap(self) -> None:
        """Forget where the camera was, so the next frame puts it on the target.

        What a teleport needs: no step limit and no eased arm, and the glide
        started where it settles behind the target at the target's velocity,
        so a camera snapped onto a moving target holds its place from the
        first frame.
        """
        self._glide = None
        self._glide_velocity = np.zeros(3)
        self._last_target = None
        self._squeeze = 1.0
        self._pose = None
        self._solved = False

    @property
    def eye(self) -> np.ndarray:
        """Where the camera is for the current state."""
        return self._current()[0]

    @property
    def look(self) -> np.ndarray:
        """The point the camera looks at for the current state."""
        return self._current()[1]

    def advance(self, dt: float, speed: float = 0.0) -> None:
        """Move the camera's state on by ``dt`` seconds, then solve its pose.

        Call once a frame with the elapsed time and the target's speed, after
        :meth:`target` and before :meth:`apply`. The easing is exponential in
        *elapsed time* rather than in frames, so the same run frames the same
        way on a fast machine and a slow one. ``speed`` is what the pull-back
        reads; a camera with no pull-back ignores it.
        """
        if self.pull_back != 0.0 and dt > 0.0:
            wanted = 1.0 + self.pull_back * min(speed / self.pull_back_speed, 1.0)
            approach = 1.0 - math.exp(-self.pull_back_rate * dt)
            self._distance_scale += (wanted - self._distance_scale) * approach
        if self._engaged:
            self._solve(max(dt, 0.0))

    def apply(self) -> None:
        """Write the camera pose onto the platform for this frame."""
        eye, look = self._current()
        self.platform.setPosition(tuple(eye))
        self.platform.setOrientation(look_at_orientation(eye, look, self.up))

    # -- the pose ---------------------------------------------------------
    @property
    def _engaged(self) -> bool:
        """Whether anything beyond the fixed offset is switched on."""
        return bool(self.look_ahead or self.smooth_time > 0.0
                    or self.sweep is not None or self._rules
                    or self.max_step is not None)

    def _current(self) -> tuple[np.ndarray, np.ndarray]:
        target = self.active_target
        if not self._engaged:
            return target + self.offset * self._distance_scale, target
        if self._solved and self._pose is not None:
            return self._pose
        return self._solve(0.0)

    def _solve(self, dt: float) -> tuple[np.ndarray, np.ndarray]:
        """Work out the eye and look point for a step of ``dt`` seconds."""
        target = self.active_target
        velocity = self._velocity_of(target, dt)
        look = self._glided(target + velocity * self.look_ahead, velocity, dt)
        eye = look + self.offset * self._distance_scale
        for rule in self._rules:
            eye, look = (np.asarray(part, dtype='d') for part in rule(eye, look))
        subject = target if self._subject is None or self._held_target is not None else self._subject
        eye, pulled_in = self._clear_of_scenery(eye, look, subject, dt)
        if self._pose is not None and self.max_step is not None and not pulled_in:
            step = eye - self._pose[0]
            length = float(np.linalg.norm(step))
            if length > self.max_step:
                eye = self._pose[0] + step * (self.max_step / length)
        self._last_target = target.copy()
        self._pose = (eye, look)
        self._solved = True
        return self._pose

    def _velocity_of(self, target: np.ndarray, dt: float) -> np.ndarray:
        """How fast the target is going: as told, or from how far it moved."""
        if self._held_target is not None:
            return np.zeros(3)
        if self._given_velocity is not None:
            self._velocity = self._given_velocity
        elif dt > 0.0 and self._last_target is not None:
            self._velocity = (target - self._last_target) / dt
        return self._velocity

    def _glided(self, aim: np.ndarray, velocity: np.ndarray, dt: float) -> np.ndarray:
        """Where the look point has glided to, toward ``aim``, which moves at ``velocity``.

        A critically damped spring, solved exactly for an aim moving at a
        constant velocity through the step: it settles ``smooth_time``
        seconds of the velocity behind the aim, the same at any frame rate,
        which ``look_ahead`` of the same length cancels, and it comes to rest
        on an aim that stops in about ``smooth_time``. The first frame, and the
        first after :meth:`snap`, starts the glide settled.
        """
        if self.smooth_time <= 0.0:
            self._glide, self._glide_velocity = aim.copy(), np.zeros(3)
            return self._glide
        velocity = np.asarray(velocity, dtype='d')
        settled = aim - velocity * self.smooth_time
        if self._glide is None:
            self._glide, self._glide_velocity = settled, velocity.copy()
            return self._glide
        omega = 2.0 / self.smooth_time
        # The glide's distance from where it settles, measured at the step's start (the aim a
        # step of the velocity back), and how fast that distance changes.
        apart = self._glide - (settled - velocity * dt)
        closing = self._glide_velocity - velocity
        carried = (closing + omega * apart) * dt
        decay = math.exp(-omega * dt)
        self._glide = settled + (apart + carried) * decay
        self._glide_velocity = velocity + (closing - omega * carried) * decay
        return self._glide

    def _clear_of_scenery(self, eye: np.ndarray, look: np.ndarray, subject: np.ndarray,
                          dt: float) -> tuple[np.ndarray, bool]:
        """The eye with the arm shortened to the first thing it meets behind ``subject``.

        Also whether the arm was pulled in by something this frame.
        """
        arm = eye - look
        length = float(np.linalg.norm(arm))
        if self.sweep is None or length <= 1e-9:
            return eye, False
        direction = arm / length
        passes = min(max(float(np.dot(subject - look, direction)), 0.0), length)
        hit = self.sweep(look + direction * passes, direction, length - passes, self.avoid_radius)
        wanted = 1.0 if hit is None else min(1.0, max(
            passes + hit, min(passes + self.min_arm, length)) / length)
        pulled_in = wanted < self._squeeze
        if pulled_in:
            self._squeeze = wanted
        else:
            self._squeeze += (wanted - self._squeeze) * (
                1.0 - math.exp(-self.arm_ease * dt))
        return look + arm * self._squeeze, pulled_in
