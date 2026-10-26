"""Character: a walker the physics service steps each frame.

A character is a :class:`~omi_physics.character.CharacterController` stepped on
the render thread, in the frame, against the render thread's copy of the bodies
(:class:`~OpenGLContext.physics.replica.Replica`). Input reaches it with no tick
between, and a ray cast or a step answers in the call.

A character takes the same steps as the world: the frame steps it once for each
fixed step the frame owes (``tickHz`` a second, 120 by default), each of the
fixed length and each with the latest moves, so its path and its jump arc do not
depend on the frame rate. Its node and the camera over it are drawn between its
last two steps, by the part step the frame leaves over (:attr:`Character.drawn_position`).

The world sees a **stand-in**: a kinematic body, a little wider than the
capsule, placed at the capsule each frame with the velocity it moved at. The
solver pushes a crate the stand-in runs into, and a crate that strikes the
stand-in knocks the character back by the impulse it delivered. A body heavier
than ``pushMass`` is ignored by the stand-in, so it blocks the character instead.

The lone character of an inline service writes its stand-in to the world when
something can see it: a dynamic body, a trigger or a sensor within reach of it
in a step, or a ray, sweep or overlap that reaches it. Until then the stand-in
waits, still, where it was last written, and a step finds it where it would have
been had it been written at every step. Read from its body, a waiting stand-in's
pose is that of the last step it was written in.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import numpy as np
from omi_physics.character import CharacterCapabilities, CharacterController, CharacterState

from OpenGLContext.character.facing import Facing
from OpenGLContext.character.locomotion import Locomotion, LocomotionInput

from OpenGLContext.physics.handlers import weak_reference
from OpenGLContext.physics.proxy import Proxy

if TYPE_CHECKING:
    from OpenGLContext.move.pathmover import PathMover
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.events import Collision
    from OpenGLContext.physics.service import Physics

__all__ = ['Character', 'Footstep', 'Landing']

_UP = np.array([0.0, 1.0, 0.0])


class Landing(NamedTuple):
    """A character coming down onto the ground: who, and how fast, in metres a second."""
    character: Character
    speed: float


class Footstep(NamedTuple):
    """A foot landing: who, which foot, how far through the stride, where, and on what material."""
    character: Character
    foot: str
    phase: float
    point: np.ndarray
    material: str | None


class Character:
    """A walker in a physics service."""

    def __init__(self, physics: Physics, node: Any, capabilities: CharacterCapabilities,
                 feet: Any, gravity: float, *, model: Any = None, clip_map: Any = None,
                 facing: Facing | None = None, turn_node: Any = None) -> None:
        self.physics = physics
        #: The node placed at the feet each frame, or None.
        self.node = node
        #: The rigged model the character wears, or None.
        self.model = model
        #: Plays the model's clips for what the character is doing, or None.
        self.locomotion: Locomotion | None = (
            None if clip_map is None else Locomotion(clip_map, model))
        #: What the locomotion settled on in the last frame, or None.
        self.settled: Any = None
        #: Turns the body toward where it goes or aims, and tilts it to the ground; or None.
        self.facing = facing
        #: The node the facing rotates, holding the model.
        self.turn_node = turn_node
        #: A direction to face instead of the one the character moves in, or None.
        self.aim: Any = None
        #: True makes the locomotion play the death clip.
        self.dead = False
        self.capabilities = capabilities
        #: False once the character has been removed.
        self.alive = True
        #: Whether :meth:`Physics.frame <OpenGLContext.physics.service.Physics.frame>` steps
        #: the character, once for each fixed step the world owes. A game that steps
        #: with its own clock sets this false and calls :meth:`update` or :meth:`step`.
        self.framed = True
        centre = np.asarray(feet, dtype='d') + _UP * (capabilities.standHeight / 2.0)
        replica = physics._character_replica()
        #: The stand-in the world sees. Events about the character are events of this body.
        self.body: Body = physics._add_standin(
            centre, capabilities, CharacterController.PUSH_REACH)
        self.controller = CharacterController(
            replica.query, capabilities, centre, gravity=gravity,
            ignore=[replica.index_of(self.body.uid), *physics.passable_slots()])
        self._slot = replica.index_of(self.body.uid)
        #: Where the capsule's centre was before and after its latest step, and how far
        #: from the one toward the other the frame draws it.
        self._previous = self.controller.position.copy()
        self._stepped = self._previous.copy()
        self._alpha = 1.0
        self._knocks: list[np.ndarray] = []
        self._listeners: dict[str, list[Callable[[], Callable[[Any], Any] | None]]] = {}
        self._last_velocity = np.zeros(3)
        #: Where the capsule was when the frame began, and the hardest landing since.
        self._marked = self.controller.position.copy()
        #: The position and velocity the stand-in was last given, so that a character
        #: that has not moved sends the world nothing.
        self._stand_in_at: tuple[tuple[float, ...], tuple[float, ...]] | None = None
        #: Whether the world's stand-in is where :attr:`_stand_in_at` and the steps
        #: since put it; while it is not, the write waits (:meth:`_settle`).
        self._written = True
        #: The steps the world has taken since the waiting write was asked for.
        self._behind = 0
        #: The velocity the world's stand-in has.
        self._given_velocity: tuple[float, ...] = (0.0, 0.0, 0.0)
        #: Whether a write was asked for since the service last collected a frame.
        self._fresh = False
        self._landed: float | None = None
        self._path: PathMover | None = None
        self._path_mode = 'run'
        self._arrived = False
        if self.locomotion is not None:
            self.locomotion.on_footstep(self._footfall)
        self.body.addEventHandler('hit', function=self._struck)
        physics._send_world('standin', self.body.uid, float(capabilities.pushMass))
        self._place_node()

    def __repr__(self) -> str:
        return 'Character(%s)' % (np.round(self.position, 2).tolist(),)

    # -- reading ----------------------------------------------------------
    @property
    def busy(self) -> bool:
        """Whether the character is moving, falling or being told to move, so the frame is not idle."""
        controller = self.controller
        return bool(not controller.grounded or controller.state != CharacterState.STANDING
                    or np.any(controller.velocity) or np.any(controller.move_dir)
                    or np.any(controller.push) or controller.landing is not None)

    @property
    def position(self) -> np.ndarray:
        """Where the feet are."""
        return self.controller.base()

    @property
    def eye(self) -> np.ndarray:
        """Where the eyes are."""
        return self.controller.eye()

    @property
    def drawn_position(self) -> np.ndarray:
        """Where the frame draws the feet: between the last two steps, by the part step left over.

        The same as :attr:`position` for a character its owner steps.
        """
        return self.position - self._lag()

    @property
    def drawn_eye(self) -> np.ndarray:
        """Where the frame puts a camera at the eyes, between the last two steps as :attr:`drawn_position`."""
        return self.eye - self._lag()

    def _lag(self) -> np.ndarray:
        """How far the drawn place is behind the capsule: the part of the latest step not yet shown.

        A move made to the capsule since the step, such as a host lifting a flier
        back onto its ground, moves the drawn place with it, and where on an axis
        it takes the step back, that much of the step is not shown either.
        """
        step = self._stepped - self._previous
        heading = np.sign(step)
        undone = np.clip(-(np.asarray(self.controller.position) - self._stepped) * heading,
                         0.0, np.abs(step))
        return (1.0 - self._alpha) * (step - heading * undone)

    @property
    def velocity(self) -> np.ndarray:
        """How fast the capsule moved over the last frame, in metres a second."""
        return self.controller.velocity

    @property
    def grounded(self) -> bool:
        """Whether the feet are on the ground."""
        return bool(self.controller.grounded)

    @property
    def swimming(self) -> bool:
        """Whether the character is in water."""
        return bool(self.controller.swimming)

    @property
    def crouching(self) -> bool:
        """Whether the character is crouched."""
        return bool(self.controller.crouching)

    @property
    def state(self) -> CharacterState:
        """What the character is doing: standing, crouching, sliding, airborne, down, swimming, flying."""
        return self.controller.state

    @property
    def landing(self) -> float | None:
        """The speed the character landed at over the last frame, else None."""
        return self.controller.landing

    @property
    def arrived(self) -> bool:
        """Whether the character has reached the end of the route :meth:`run_along` gave it."""
        return self._arrived

    @property
    def heading(self) -> float:
        """The way the body faces, in radians from +Z about +Y; 0 for a character with no facing."""
        return 0.0 if self.facing is None else float(self.facing.heading)

    # -- doing --------------------------------------------------------------
    def set_move(self, direction: Any, mode: str = 'walk') -> None:
        """Walk toward ``direction`` (flattened to the ground) at the speed of ``mode``.

        ``mode`` is ``'walk'``, ``'run'``, ``'sprint'`` or ``'crouch'``. A zero
        direction stops. The move holds until the next call.
        """
        self.controller.set_move(direction, mode)

    def set_fly_move(self, direction: Any) -> None:
        """Fly toward ``direction``, vertical part included."""
        self.controller.set_fly_move(direction)

    def run_along(self, course: Any, speed: float | None = None, mode: str = 'run',
                  lane: float = 0.0) -> None:
        """Run along ``course``: a :class:`~OpenGLContext.scenegraph.roadcourse.RoadCourse`, or points.

        A list of two or more points, such as a route from a navigation mesh,
        is an open course through them. The character stops at the end of an
        open course, :attr:`arrived` turns true and ``'arrived'`` handlers are
        called with the character.

        The character runs at ``speed`` metres a second (its own ``mode`` speed
        where that is left out) on a lane ``lane`` metres right of the line,
        steering back to it each frame; height and jumps are still the
        controller's. :meth:`hop_to` changes lane. The moves it makes replace
        those of :meth:`set_move` until :meth:`stop_running_along`.
        """
        from OpenGLContext.move.pathmover import PathMover  # noqa: PLC0415 only a character on a course needs it
        from OpenGLContext.scenegraph.roadcourse import RoadCourse  # noqa: PLC0415 only a character on a course needs it

        if not isinstance(course, RoadCourse):
            course = RoadCourse(course)

        names = {'walk': 'walkSpeed', 'run': 'runSpeed', 'sprint': 'sprintSpeed',
                 'crouch': 'crouchSpeed'}
        field = names.get(mode, 'runSpeed')
        if speed is not None:
            setattr(self.capabilities, field, float(speed))
        self._path_mode = mode
        self._path = PathMover(course, float(getattr(self.capabilities, field)), lane=lane)
        self._arrived = False

    def hop_to(self, offset: float, over: float = 0.16) -> None:
        """Move to the lane ``offset`` metres right of the course, taking ``over`` seconds."""
        if self._path is None:
            raise RuntimeError('hop_to changes lane on a course; run_along(course) puts the '
                               'character on one')
        self._path.hop_to(offset, over)

    def stop_running_along(self) -> None:
        """Give the character's moves back to :meth:`set_move`."""
        self._path = None

    def jump(self) -> bool:
        """Leave the ground; False where the character cannot."""
        return bool(self.controller.jump())

    def apply_impulse(self, velocity: Any) -> None:
        """Add ``velocity`` to the character's motion, a shove that ground friction bleeds off."""
        self.controller.apply_impulse(velocity)

    def knockback(self, impulse: Any) -> None:
        """Change the velocity by ``impulse`` newton-seconds over the character's mass."""
        self.controller.knockback(impulse)

    def set_crouch(self, crouch: bool) -> bool:
        """Crouch or stand; returns whether the character is crouching afterwards."""
        return bool(self.controller.set_crouch(crouch))

    def set_fly(self, flying: bool) -> bool:
        """Fly without gravity or collision with the ground, or stop."""
        return bool(self.controller.set_fly(flying))

    def set_swim(self, swimming: bool, buoyancy: float = 0.9) -> None:
        """Swim, pulled by what ``buoyancy`` leaves of gravity, or stop."""
        self.controller.set_swim(swimming, buoyancy)

    def slide(self, duration: float, rise: float = 0.3, steer: bool = False) -> bool:
        """Slide low with the speed the character has, rising over the last ``rise`` seconds.

        With ``steer`` the slide takes no momentum and the moves of :meth:`set_move` still go,
        at the speed of their mode.
        """
        return bool(self.controller.slide(duration, rise, steer))

    def extend_slide(self, duration: float) -> bool:
        """Slide for ``duration`` seconds more from now, low again; False if not sliding."""
        return bool(self.controller.extend_slide(duration))

    def end_slide(self) -> bool:
        """End a slide at once and stand, or crouch where there is no room; False if not sliding."""
        return bool(self.controller.end_slide())

    def knock_down(self) -> None:
        """Fall and stay down, ignoring input, until :meth:`get_up`."""
        self.controller.knock_down()

    def get_up(self, start_speed: float | None = None) -> None:
        """Stand and run again, from ``start_speed`` where given."""
        self.controller.get_up(start_speed)

    def teleport(self, feet: Any) -> bool:
        """Put the feet at ``feet``, or at the nearest place with room; False if none was found."""
        found = bool(self.controller.safe_bind(
            np.asarray(feet, dtype='d') + _UP * (self.controller.height / 2.0)))
        self._marked = self.controller.position.copy()
        self._previous, self._alpha = self.controller.position.copy(), 1.0
        self._stepped = self._previous.copy()
        self._place_stand_in(np.zeros(3))
        self._place_node()
        return found

    def remove(self) -> None:
        """Take the character out of the world. Removing twice is harmless."""
        if not self.alive:
            return
        self.alive = False
        self.physics._characters.remove(self)
        self.body.remove()

    # -- events -------------------------------------------------------------
    def addEventHandler(self, event: str, function: Callable[..., Any] | None = None,
                        **filters: Any) -> Any:
        """Call ``function`` when ``event`` happens to the character.

        ``'landed'`` calls ``function(landing)`` with a :class:`Landing`, and
        ``'footstep'`` calls it with a :class:`Footstep`, ``'arrived'`` calls it
        with the character at the end of a route; every other name is an
        event of the character's body
        (:meth:`Body.addEventHandler <OpenGLContext.physics.body.Body.addEventHandler>`).
        """
        if event not in ('landed', 'footstep', 'arrived'):
            return self.body.addEventHandler(event, function, **filters)
        if function is None:
            self._listeners.pop(event, None)
        else:
            self._listeners.setdefault(event, []).append(weak_reference(function))
        return None

    def play_action(self, name: str, layer: str = 'upper', **named: Any) -> Any:
        """Play a clip on a layer over the locomotion, such as a wave on the arms.

        Raises RuntimeError for a character with no model to play it on.
        """
        if self.locomotion is None:
            raise RuntimeError('this character has no model; add_character(model=..., '
                               'animations=...) gives it one')
        return self.locomotion.play_action(name, layer, **named)

    def _struck(self, hit: Collision) -> None:
        """A body hit the stand-in: the blow it delivered becomes a knock, unless it was pushed."""
        other = hit.other
        if (not hit.solved or self.controller.pushing is not None or other is None
                or other.kind != 'dynamic'):
            return
        self._knocks.append(np.asarray(hit.normal, dtype='d') * float(hit.impulse))

    # -- the frame ------------------------------------------------------------
    def update(self, dt: float) -> None:
        """Step the character by ``dt`` seconds, show the world where it is and animate it."""
        self.step(dt)
        self.animate(dt)

    def _frame(self, steps: int, step: float, dt: float, alpha: float) -> None:
        """The frame's share for a framed character: ``steps`` steps of ``step`` seconds, the
        clips for the ``dt`` seconds of the frame, and the node drawn ``alpha`` of the way
        from the last step's start to its end."""
        for _ in range(steps):
            self.step(step)
        self.animate(dt)
        self._alpha = float(alpha)
        self._place_node()

    def step(self, dt: float) -> None:
        """Move the character by ``dt`` seconds and show the world where it is, without animating it.

        A game that steps in pieces shorter than its frame calls this for each piece and
        :meth:`animate` once for the frame. ``landed`` is told here.
        """
        controller = self.controller
        self._previous, self._alpha = controller.position.copy(), 1.0
        for knock in self._knocks:
            controller.knockback(knock)
        self._knocks.clear()
        if self._path is not None:
            controller.set_move(self._path.update(self.position, dt).direction, self._path_mode)
            if self._path.finished and not self._arrived:
                self._arrived = True
                self._tell('arrived', self)
        controller.update(dt)
        self._stepped = controller.position.copy()
        pushing = controller.pushing
        self._place_stand_in(pushing[1] if pushing is not None else controller.velocity)
        self._place_node()
        landing = controller.landing
        if landing is not None:
            self._landed = max(self._landed or 0.0, float(landing))
            self._tell('landed', Landing(self, float(landing)))

    def animate(self, dt: float) -> None:
        """Play the clips for what the character did over the last ``dt`` seconds and turn the body.

        The speed it moves at is the distance it covered since the last animation over ``dt``,
        and a landing in any of the steps since is the landing the clips hear.
        """
        controller = self.controller
        here = np.asarray(controller.position)
        velocity = (here - self._marked) / dt if dt > 0.0 else np.asarray(controller.velocity)
        self._marked = here.copy()
        landed, self._landed = self._landed, None
        if self.locomotion is not None:
            self.settled = self.locomotion.update(LocomotionInput(
                speed=float(np.hypot(velocity[0], velocity[2])), vertical_speed=float(velocity[1]),
                grounded=bool(controller.grounded), state=controller.state.value,
                slide_progress=float(controller.slide_progress),
                landing_speed=landed, crouching=bool(controller.crouching),
                dead=self.dead), dt)
            if self.model is not None and hasattr(self.model, 'update'):
                self.model.update(dt)
        if self.facing is not None and dt > 0.0:
            normal = controller.ground_normal if controller.ground_normal is not None else _UP
            pose = self.facing.update(dt, velocity=velocity, aim=self.aim, normal=normal,
                                      acceleration=(velocity - self._last_velocity) / dt)
            if self.turn_node is not None:
                self.turn_node.rotation = pose.rotation
        self._last_velocity = velocity.copy()

    def _footfall(self, foot: str, phase: float) -> None:
        """A foot landed: tell the handlers, and play the footstep of the ground under it."""
        feet = self.position
        under = self.physics.raycast(feet + _UP * 0.3, (0.0, -1.0, 0.0), 0.8, skip=self.body)
        material = None if under is None or under.body is None else under.body.material
        step = Footstep(self, foot, float(phase), feet.copy(), material)
        self._tell('footstep', step)
        physics = self.physics
        sound = physics.materials.footstep_of(material) if physics._audio is not None else None
        if sound is not None and physics._audio is not None:
            physics._audio().play(sound, at=tuple(float(v) for v in feet), gain=0.5)

    def _place_stand_in(self, velocity: Any) -> None:
        """Put the stand-in at the capsule with ``velocity``, unless it is already so.

        Placing a body and setting its velocity each wake it. Where the service
        defers stand-ins (:meth:`Physics._defers_stand_ins
        <OpenGLContext.physics.service.Physics._defers_stand_ins>`) the write
        waits for something that can see it.
        """
        here = tuple(float(v) for v in self.controller.position)
        moving = tuple(float(v) for v in velocity)
        if (here, moving) == self._stand_in_at:
            return
        self._stand_in_at = (here, moving)
        if self.physics._defers_stand_ins():
            self._written, self._behind, self._fresh = False, 0, True
        else:
            self._write(here, moving)

    def _write(self, here: tuple[float, ...], moving: tuple[float, ...]) -> None:
        """Place the stand-in at ``here`` with velocity ``moving``."""
        physics, body = self.physics, self.body
        physics._command('place', body, here, None)
        physics._command('velocity', body, moving)
        self._given_velocity = moving
        self._written = True

    def _due(self) -> tuple[float, ...]:
        """Where the world's stand-in would be had the waiting write been made: the place
        asked for, moved on by its velocity for each step since, as a step moves it."""
        here, moving = cast(tuple[tuple[float, ...], tuple[float, ...]], self._stand_in_at)
        if not self._behind:
            return here
        dt = self.physics.worker.runtime.step_dt
        x, y, z = here
        vx, vy, vz = moving
        for _ in range(self._behind):
            x, y, z = x + vx * dt, y + vy * dt, z + vz * dt
        return x, y, z

    def _bring_up(self) -> None:
        """Make the waiting write now."""
        if not self._written:
            self._write(self._due(), cast(tuple[tuple[float, ...], tuple[float, ...]],
                                          self._stand_in_at)[1])

    def _settle(self, seen: Callable[[Character, tuple[float, ...]], bool]) -> None:
        """Before a step: make the waiting write where ``seen(self, due)`` says something can see
        the stand-in, else keep it waiting, still, and count the step."""
        if self._written:
            return
        due = self._due()
        if seen(self, due):
            self._write(due, cast(tuple[tuple[float, ...], tuple[float, ...]],
                                  self._stand_in_at)[1])
            return
        if any(self._given_velocity):
            self.physics._command('velocity', self.body, (0.0, 0.0, 0.0))
            self._given_velocity = (0.0, 0.0, 0.0)
        self._behind += 1

    def _stand_in_reach(self, grow: float) -> tuple[float, float]:
        """How far the stand-in's box, grown by ``grow`` metres, reaches from its centre: across,
        and up and down."""
        caps = self.capabilities
        across = caps.radius + CharacterController.PUSH_REACH + grow
        return across, 0.5 * max(caps.standHeight - 2.0 * caps.radius, 1e-3) + across

    def _stand_in_box(self, centre: Any, grow: float) -> tuple[np.ndarray, np.ndarray]:
        """The box of the stand-in centred at ``centre``, grown by ``grow`` metres."""
        across, up = self._stand_in_reach(grow)
        half = np.array([across, up, across])
        middle = np.asarray(centre, dtype='d')
        return middle - half, middle + half

    def _place_node(self) -> None:
        if self.node is not None:
            self.node.translation = tuple(float(v) for v in self.drawn_position)

    def _tell(self, event: str, argument: Any) -> None:
        kept = []
        for reference in self._listeners.get(event, ()):
            function = reference()
            if function is None:
                continue
            kept.append(reference)
            try:
                function(argument)
            except Exception:
                self.physics.log_handler_failure(function, argument)
        if event in self._listeners:
            self._listeners[event] = kept


def stand_in_proxy(capabilities: CharacterCapabilities, reach: float) -> Proxy:
    """The capsule the world sees for a character: the controller's, widened by ``reach``."""
    middle = max(capabilities.standHeight - 2.0 * capabilities.radius, 1e-3)
    return Proxy.capsule(middle, capabilities.radius + reach)
