"""A character seen from behind: keys relative to the camera, and a camera that follows it.

:class:`FollowMode` is a movement mode that turns the movement keys into the
moves of a character, relative to the way the camera looks, and the turn keys
into swinging the camera round it. :class:`ThirdPersonPlatform` is what the
mode drives: a :class:`~OpenGLContext.move.physicsplatform.PhysicsViewPlatform`
over a physics character whose camera is a
:class:`~OpenGLContext.move.followcam.FollowCamera` standing behind it, kept out
of the scenery by a sphere sweep. :class:`FollowController` ties both to a
context; ``context.follow(character)`` makes one::

    hero = self.physics.add_character(model='hero.glb', animations='ual')
    self.follow(hero)
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
from vrml import field

from OpenGLContext.events import systemtime
from OpenGLContext.events.framestep import FrameStep
from OpenGLContext.move.followcam import FollowCamera, Sweep
from OpenGLContext.move.modes import KeyBinding, WalkMode
from OpenGLContext.move.navigation import NavigationManager
from OpenGLContext.move.navigationdefinition import Navigation
from OpenGLContext.move.physicsplatform import PhysicsViewPlatform

if TYPE_CHECKING:
    from OpenGLContext.physics.character import Character

__all__ = ['FollowController', 'FollowMode', 'ThirdPersonPlatform', 'followMode']

_UP = np.array([0.0, 1.0, 0.0])
#: Metres a second below which a character's way of going does not swing the camera.
SWING_SPEED = 0.5


def _(text: str) -> str:
    return text


class FollowMode(WalkMode):
    """Move a character relative to the camera, and swing the camera round it with the turn keys."""

    PROTO = 'FollowMode'
    #: Metres a second at the ``sprint`` key.
    sprintSpeed = field.newField('sprintSpeed', 'SFFloat', 1, 9.0)
    #: A forward move held without a key, from 0 (none) to 1; the keys steer. For a runner.
    autoForward = field.newField('autoForward', 'SFFloat', 1, 0.0)

    UI_HINTS: ClassVar[dict[str, dict[str, Any]]] = {
        **WalkMode.UI_HINTS,
        'sprintSpeed': {'label': 'Sprinting speed', 'minimum': 0.5, 'maximum': 60.0,
                        'step': 0.5, 'suffix': ' m/s'},
        'autoForward': {'skip': True},
    }
    commands: Sequence[str] = tuple(WalkMode.commands) + ('sprint', 'slide')

    def __init__(self, **named: Any) -> None:
        super().__init__(**named)
        if not self.name:
            self.name = 'follow'

    def defaultBindings(self) -> Sequence[KeyBinding]:
        return list(super().defaultBindings()) + [
            KeyBinding(command='sprint', label=_('Sprint'), keys=['<ctrl>']),
            KeyBinding(command='slide', label=_('Slide'), keys=['c']),
        ]

    def update(self, dt: float, inputs: Any, platform: Any) -> None:
        """Make the moves the keys ask for, relative to the camera, and swing the camera."""
        forward, strafe = self._movement(inputs)
        if self.autoForward:
            forward = float(self.autoForward)
        self._turn(dt, inputs, platform, self.turnRate)
        self._look(dt, inputs, platform)
        if inputs.held(*self.keys_for('sprint')):
            tier, speed = 'sprint', self.sprintSpeed
        elif inputs.held(*self.keys_for('run')):
            tier, speed = 'run', self.runSpeed
        else:
            tier, speed = 'walk', self.walkSpeed
        platform.set_move(forward=forward, strafe=strafe, mode=tier, speed=float(speed))
        if inputs.pressed(*self.keys_for('jump')):
            platform.jump()
        if inputs.pressed(*self.keys_for('slide')):
            platform.slide()


def followMode(scale: float = 1.0) -> FollowMode:
    """``follow``: moving a character seen from behind, relative to the camera"""
    from OpenGLContext.move import modes  # noqa: PLC0415 the defaults are the walk mode's

    return FollowMode(name='follow', walkSpeed=modes.WALK_SPEED * scale,
                      runSpeed=modes.RUN_SPEED * scale, sprintSpeed=1.5 * modes.RUN_SPEED * scale,
                      turnRate=modes.TURN_RATE, turnAcceleration=modes.TURN_ACCELERATION)


class ThirdPersonPlatform(PhysicsViewPlatform):
    """A platform over a physics character that puts the camera behind it.

    ``yaw`` and ``pitch`` are where the camera looks, as they are for the
    first-person platform: the moves are relative to the yaw, and the camera
    stands ``distance`` metres back along it and as far above as the pitch asks,
    looking at a point ``height`` metres above the character's feet.

    With a ``swing`` of some seconds the yaw also eases round behind the way
    the character is moving, taking about that long, the short way round; a
    character going slower than :data:`SWING_SPEED` leaves it where it is.
    """

    camera: FollowCamera
    distance: float
    height: float
    slide_time: float
    swing: float = 0.0

    @classmethod
    def over(cls, character: Any, yaw: float = 0.0, *, camera: Any = None,
             distance: float = 4.5, height: float = 1.7, sweep: Sweep | None = None,
             slide_time: float = 0.8, swing: float = 0.0,
             **camera_options: Any) -> ThirdPersonPlatform:
        """A platform over ``character`` that drives ``camera``, a view platform.

        ``swing`` is the seconds the camera takes to come round behind the
        way the character moves, or 0 to leave the yaw to the keys.

        ``sweep`` keeps the camera out of the scenery
        (:class:`~OpenGLContext.move.followcam.FollowCamera`); ``camera_options``
        are its other settings.
        """
        platform = super().over(character, yaw)
        assert isinstance(platform, cls)
        platform.distance = float(distance)
        platform.height = float(height)
        platform.slide_time = float(slide_time)
        platform.swing = float(swing)
        platform._dt = 0.0
        camera_options.setdefault('look_ahead', 0.1)
        camera_options.setdefault('smooth_time', 0.12)
        platform.camera = FollowCamera(camera, (0.0, height, distance), sweep=sweep,
                                       **camera_options)
        return platform

    _dt: float = 0.0

    def slide(self) -> bool:
        """Slide the character for ``slide_time`` seconds."""
        return bool(self.managed.slide(self.slide_time))

    def update(self, dt: float) -> None:
        """Note the frame's time; the service steps the character."""
        self._dt = dt
        super().update(dt)

    def _swing_behind(self, velocity: Any) -> None:
        """Ease the yaw toward the way ``velocity`` goes, by this frame's share of :attr:`swing`."""
        if self.swing <= 0.0 or self._dt <= 0.0 or math.hypot(velocity[0], velocity[2]) < SWING_SPEED:
            return
        wanted = math.atan2(float(velocity[0]), -float(velocity[2]))
        turn = math.remainder(wanted - self.yaw, 2.0 * math.pi)
        self.yaw = math.remainder(self.yaw + turn * (1.0 - math.exp(-self._dt / self.swing)),
                                  2.0 * math.pi)

    def apply(self, context: Any = None) -> None:
        """Put the camera behind the character, ``distance`` back along the yaw."""
        character = self.managed
        self._swing_behind(character.velocity)
        sine, cosine = math.sin(self.pitch), math.cos(self.pitch)
        forward = np.array([math.sin(self.yaw), 0.0, -math.cos(self.yaw)])
        camera = self.camera
        camera.offset = -forward * self.distance * cosine + _UP * self.distance * sine
        camera.target(character.drawn_position + _UP * self.height, character.velocity)
        camera.advance(self._dt, float(np.hypot(character.velocity[0], character.velocity[2])))
        camera.apply()


class FollowController:
    """Has a character obey the keys of a :class:`FollowMode` and a camera follow it."""

    platform: PhysicsViewPlatform

    def __init__(self, context: Any, character: Character, mode: FollowMode | None = None,
                 distance: float = 4.5, height: float = 1.7, **camera_options: Any) -> None:
        physics = context.physics
        platform = ThirdPersonPlatform.over(
            character, camera=context.getViewPlatform(), distance=distance, height=height,
            sweep=lambda origin, direction, length, radius: physics.sweep_sphere(
                origin, direction, length, radius, skip=character.body),
            **camera_options)
        self.drive(context, character, platform, [mode if mode is not None else FollowMode()])

    def drive(self, context: Any, character: Character, platform: PhysicsViewPlatform,
              modes: Sequence[Any]) -> None:
        """Have ``modes`` (the first in force) move ``character`` through ``platform``."""
        self.context = context
        self.character = character
        self.platform = platform
        self.mode = modes[0]
        navigation = Navigation(modes=list(modes), mode=self.mode.name)
        self.navigation = NavigationManager(SimpleNamespace(navigation=navigation), platform)
        self.navigation.listeners.append(self._entered)
        self.stopped = False
        self._steps = FrameStep(longest=0.1)
        self._dt = 0.0
        #: The free-fly navigator this took the camera from, given it back by :meth:`stop`.
        self._freed: Any = None

    def _entered(self, mode: Any) -> None:
        """Put the character in the state of ``mode``, the mode now in force."""
        if mode is not None:
            mode.applyTo(self.platform)

    def start(self) -> None:
        """Take the keys, the camera and the frame: input before the world steps, the camera after.

        A free-fly navigator holding the camera is unbound, so that it and the
        platform do not both move it.
        """
        context = self.context
        for _name, binding in self.navigation.binding_table():
            for key in binding.keys:
                for state in (1, 0):
                    context.addEventHandler('keyboard', name=key, state=state,
                                            function=self._wake)
        manager = getattr(context, 'movementManager', None)
        if manager is not None:
            manager.unbind(context)
            context.movementManager = None
            self._freed = manager
        queue = context.renderQueue
        queue.on_frame(self._input, first=True)
        queue.on_frame(self._camera)

    def stop(self) -> None:
        """Stop obeying the keys and following; the character keeps the last move it was given.

        The free-fly navigator :meth:`start` took the camera from is given it back.
        """
        self.stopped = True
        for _name, binding in self.navigation.binding_table():
            for key in binding.keys:
                for state in (1, 0):
                    self.context.addEventHandler('keyboard', name=key, state=state, function=None)
        if self._freed is not None:
            self._freed.bind(self.context)
            self.context.movementManager, self._freed = self._freed, None

    def _wake(self, event: Any) -> None:
        self.context.triggerRedraw(1)

    def _input(self) -> None:
        if self.stopped:
            return
        self._dt = self._steps.step(systemtime.systemTime())
        self.navigation.update(self._dt, self.context.getInputState())

    def _camera(self) -> None:
        if self.stopped:
            return
        self.platform.update(self._dt)
        self.platform.apply(self.context)
        if self.character.busy:
            self.context.triggerRedraw(1)
