"""Character: a walker the physics service steps each frame.

A character is a :class:`~omi_physics.character.CharacterController` stepped on
the render thread, in the frame, against the render thread's copy of the bodies
(:class:`~OpenGLContext.physics.replica.Replica`). Input reaches it with no tick
between, and a ray cast or a step answers in the call.

The world sees a **stand-in**: a kinematic body, a little wider than the
capsule, placed at the capsule each frame with the velocity it moved at. The
solver pushes a crate the stand-in runs into, and a crate that strikes the
stand-in knocks the character back by the impulse it delivered. A body heavier
than ``pushMass`` is ignored by the stand-in, so it blocks the character instead.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple

import numpy as np
from omi_physics.character import CharacterCapabilities, CharacterController, CharacterState

from OpenGLContext.character.facing import Facing
from OpenGLContext.character.locomotion import Locomotion, LocomotionInput

from OpenGLContext.physics.handlers import weak_reference
from OpenGLContext.physics.proxy import Proxy

if TYPE_CHECKING:
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
        centre = np.asarray(feet, dtype='d') + _UP * (capabilities.standHeight / 2.0)
        replica = physics._character_replica()
        #: The stand-in the world sees. Events about the character are events of this body.
        self.body: Body = physics._add_standin(
            centre, capabilities, CharacterController.PUSH_REACH)
        self.controller = CharacterController(
            replica.query, capabilities, centre, gravity=gravity,
            ignore=[replica.index_of(self.body.uid)])
        self._slot = replica.index_of(self.body.uid)
        self._knocks: list[np.ndarray] = []
        self._listeners: dict[str, list[Callable[[], Callable[[Any], Any] | None]]] = {}
        self._last_velocity = np.zeros(3)
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

    def slide(self, duration: float, rise: float = 0.3) -> bool:
        """Slide low with the speed the character has, rising over the last ``rise`` seconds."""
        return bool(self.controller.slide(duration, rise))

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
        ``'footstep'`` calls it with a :class:`Footstep`; every other name is an
        event of the character's body
        (:meth:`Body.addEventHandler <OpenGLContext.physics.body.Body.addEventHandler>`).
        """
        if event not in ('landed', 'footstep'):
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
        """Step the character by ``dt`` seconds and show the world where it is."""
        controller = self.controller
        for knock in self._knocks:
            controller.knockback(knock)
        self._knocks.clear()
        controller.update(dt)
        pushing = controller.pushing
        self._place_stand_in(pushing[1] if pushing is not None else controller.velocity)
        self._place_node()
        self._animate(dt)
        landing = controller.landing
        if landing is not None:
            self._tell('landed', Landing(self, float(landing)))

    def _animate(self, dt: float) -> None:
        """Play the clips for what the character did this frame and turn the body."""
        controller = self.controller
        velocity = np.asarray(controller.velocity)
        if self.locomotion is not None:
            self.settled = self.locomotion.update(LocomotionInput(
                speed=float(np.hypot(velocity[0], velocity[2])), vertical_speed=float(velocity[1]),
                grounded=bool(controller.grounded), state=controller.state.value,
                slide_progress=float(controller.slide_progress),
                landing_speed=controller.landing, crouching=bool(controller.crouching),
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
        physics, body = self.physics, self.body
        physics._command('place', body, tuple(float(v) for v in self.controller.position), None)
        physics._command('velocity', body, tuple(float(v) for v in velocity))
        if np.any(np.asarray(velocity) != 0.0):
            physics._command('wake', body)

    def _place_node(self) -> None:
        if self.node is not None:
            self.node.translation = tuple(float(v) for v in self.position)

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
