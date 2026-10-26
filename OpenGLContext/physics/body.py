"""Body: the handle the physics service gives for each thing in the world.

A body is made by one of the ``add_*`` calls of :class:`~OpenGLContext.physics.service.Physics`
and lives until it is removed. Reading one answers the last published state of
the world, which is at most one tick old; on the worker thread it answers the
live world. Writing one is a command that takes effect on the next tick; on the
worker thread it takes effect at once, so the same handler runs in either place.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np
from omi_physics import model

from OpenGLContext.physics.checks import number, vector
from OpenGLContext.physics.proxy import Proxy

if TYPE_CHECKING:
    from OpenGLContext.physics.handlers import Handler
    from OpenGLContext.physics.materials import PhysicsMaterial
    from OpenGLContext.physics.service import Physics

__all__ = ['Body']

Vector = tuple[float, float, float]


class Body:
    """One body of a physics service: its node, its shape and its place in the world."""

    def __init__(self, physics: Physics, uid: int, kind: str, node: Any, proxy: Proxy | None,
                 position: Any, axis_angle: Any, mass: float,
                 linear_damping: float = 0.0, angular_damping: float = 0.0) -> None:
        self.physics = physics
        #: Distinguishes this body from every other the service has made.
        self.uid = uid
        #: ``'static'``, ``'dynamic'``, ``'kinematic'`` or ``'trigger'``.
        self.kind = kind
        #: The scenegraph node the body drives; touch it on the render thread only.
        self.node = node
        #: The shape; None for scenery whose triangles are still being cooked.
        self.proxy = proxy
        #: Whether the service made this body from a shape of the scene, rather than
        #: the application adding it.
        self.derived = False
        #: The name of the body's material, or None for the world's default.
        self.material: str | None = None
        #: The coefficients the body's surface has: its material's, with any
        #: :meth:`set_friction` or :meth:`set_restitution` since.
        self._surface = model.Material()
        self._pending = False
        #: Writes made before the body was in the world, sent when it is.
        self._deferred: list[tuple[str, tuple[Any, ...]]] = []
        #: Kilograms; 0 for a body that is not dynamic.
        self.mass = mass
        #: False once the body has been removed.
        self.alive = True
        self._linear_damping = float(linear_damping)
        self._angular_damping = float(angular_damping)
        self._position = np.asarray(position, dtype='d')
        self._axis_angle = np.asarray(axis_angle, dtype='d')
        #: A write the world has not yet applied: (sequence, position or None, axis-angle or None).
        self._placed: tuple[int, np.ndarray | None, np.ndarray | None] | None = None

    def __repr__(self) -> str:
        return 'Body(%d, %s)' % (self.uid, self.kind)

    # -- reading ----------------------------------------------------------
    @property
    def position(self) -> np.ndarray:
        """Where the body is, in metres."""
        return self.physics._state(self).position

    @property
    def rotation(self) -> np.ndarray:
        """How the body is turned, as an axis and an angle in radians: ``(x, y, z, angle)``."""
        return self.physics._state(self).axis_angle

    @property
    def velocity(self) -> np.ndarray:
        """How fast the body moves, in metres a second."""
        return self.physics._state(self).velocity

    @property
    def angular_velocity(self) -> np.ndarray:
        """How fast the body turns, in radians a second about the world axes."""
        return self.physics._state(self).angular_velocity

    @property
    def speed(self) -> float:
        """The length of :attr:`velocity`."""
        return float(np.linalg.norm(self.velocity))

    @property
    def friction(self) -> float:
        """The friction coefficient of the body's surface while it slides."""
        return float(self._surface.dynamicFriction)

    @property
    def restitution(self) -> float:
        """The fraction of the closing speed a bounce off the body's surface keeps."""
        return float(self._surface.restitution)

    @property
    def asleep(self) -> bool:
        """Whether the world has put the body to sleep, which it does once it is still."""
        return self.physics._state(self).asleep

    # -- writing ----------------------------------------------------------
    def _send(self, op: str, *args: Any) -> int:
        return self.physics._command(op, self, *args)

    def apply_impulse(self, impulse: Any, at: Any = None) -> None:
        """Change the velocity by ``impulse / mass``; ``impulse`` is in newton-seconds.

        ``at`` is a world point to push at: off the body's centre the push also spins it.
        Raises ValueError for a value that is not finite.
        """
        self._send('impulse', vector(impulse, 'impulse'), None if at is None else vector(at, 'at'))

    def apply_torque_impulse(self, impulse: Any) -> None:
        """Change the spin by an angular impulse about the world axes, in newton-metre-seconds."""
        self._send('torque_impulse', vector(impulse, 'impulse'))

    def set_force(self, force: Any) -> None:
        """Push the body through its centre with ``force`` newtons until it is set again."""
        self._send('force', vector(force, 'force'))

    def set_velocity(self, velocity: Any) -> None:
        """Make the velocity ``velocity``, in metres a second."""
        self._send('velocity', vector(velocity, 'velocity'))

    def set_angular_velocity(self, velocity: Any) -> None:
        """Make the spin ``velocity``, in radians a second about the world axes."""
        self._send('angular_velocity', vector(velocity, 'velocity'))

    def set_transform(self, translation: Any = None, rotation: Any = None) -> None:
        """Put the body at ``translation`` and turn it to ``rotation`` (an axis and an angle).

        Either may be left out. Reading the body answers the new place at once,
        and goes on answering it until the world has applied it, which for
        scenery still being cooked is once it joins the world.
        """
        position = None if translation is None else np.asarray(vector(translation, 'translation'))
        axis_angle = None if rotation is None else np.asarray(vector(rotation, 'rotation', 4))
        seq = self._send('place', None if position is None else tuple(position),
                         None if axis_angle is None else tuple(axis_angle))
        if self.alive:
            self._placed = (seq, position, axis_angle)
            # Where a body the snapshots do not list (static, trigger) is read from.
            if position is not None:
                self._position = position
            if axis_angle is not None:
                self._axis_angle = axis_angle

    def set_mass(self, mass: float) -> None:
        """Make the body weigh ``mass`` kilograms, with the inertia its shape has at that mass.

        :attr:`mass` answers the new mass at once; the world uses it from its
        next step. Raises ValueError for a mass that is not finite and above
        zero, and for a body that is not dynamic.
        """
        kilograms = number(mass, 'mass', positive=True)
        if self.kind != 'dynamic':
            raise ValueError('only a dynamic body has a mass to set, not a %s one' % self.kind)
        self.mass = kilograms
        self._send('mass', kilograms)

    def set_material(self, material: str | PhysicsMaterial) -> None:
        """Give the body's surface ``material``: a preset or defined name, or a defined material.

        :attr:`material`, :attr:`friction` and :attr:`restitution` answer the new
        material's at once, and a strike on the body plays its sound; the world
        uses it from its next step. Raises ValueError for a name no material has
        and for a trigger, which has no surface.
        """
        name = material if isinstance(material, str) else material.name
        found = self.physics.materials.get(name)
        self._surfaced()
        self.material = name
        self._surface = found.material
        self.physics._take_sound(self)
        self._send('body_material', name)

    def set_friction(self, friction: float) -> None:
        """Make the friction coefficient of the body's surface ``friction``, sliding and at rest.

        The rest of the surface, and :attr:`material` with its sound, stay as
        they are. Raises ValueError for a value that is not finite and at or
        above zero, and for a trigger.
        """
        value = number(friction, 'friction', non_negative=True)
        self._resurface(dataclasses.replace(self._surface, staticFriction=value,
                                            dynamicFriction=value))

    def set_restitution(self, restitution: float) -> None:
        """Make the fraction of the closing speed a bounce off the body keeps ``restitution``.

        The rest of the surface, and :attr:`material` with its sound, stay as
        they are. Raises ValueError for a value that is not finite and at or
        above zero, and for a trigger.
        """
        value = number(restitution, 'restitution', non_negative=True)
        self._resurface(dataclasses.replace(self._surface, restitution=value))

    def _surfaced(self) -> None:
        """Raise ValueError for a body with no surface to change."""
        if self.kind == 'trigger':
            raise ValueError('a trigger has no surface to give a material, friction or restitution')

    def _resurface(self, surface: model.Material) -> None:
        self._surfaced()
        self._surface = surface
        self._send('body_material', surface)

    @property
    def linear_damping(self) -> float:
        """How quickly the velocity falls away on its own, per second."""
        return self._linear_damping

    @linear_damping.setter
    def linear_damping(self, value: float) -> None:
        self._linear_damping = number(value, 'linear_damping', non_negative=True)
        self._send('damping', self._linear_damping, None)

    @property
    def angular_damping(self) -> float:
        """How quickly the spin falls away on its own, per second."""
        return self._angular_damping

    @angular_damping.setter
    def angular_damping(self, value: float) -> None:
        self._angular_damping = number(value, 'angular_damping', non_negative=True)
        self._send('damping', None, self._angular_damping)

    def drive(self, pose: Callable[[float], Any]) -> None:
        """Move this kinematic body by ``pose(time)``, called at the end of each step.

        ``pose`` returns ``(translation, rotation)``, the rotation an axis and an
        angle or None to leave it as it is, for the time in seconds on the
        world's clock. The body is given the velocity that takes it there, so a
        body resting on it is carried and a strike against it has the right
        closing speed. ``pose`` must be marked
        :func:`~OpenGLContext.physics.callbacks.physics_callback`; it is held
        for as long as the body lives.
        """
        from OpenGLContext.physics.callbacks import is_physics_callback  # noqa: PLC0415 only a driven body needs it

        if self.kind != 'kinematic':
            raise ValueError('only a kinematic body can be driven, not a %s one' % self.kind)
        if not is_physics_callback(pose):
            raise ValueError('a pose function runs inside the step; mark it with @physics_callback')
        self._send('drive', pose)

    def wake(self) -> None:
        """Wake the body if the world has put it to sleep."""
        self._send('wake')

    def remove(self) -> None:
        """Take the body out of the world. Removing twice is harmless."""
        self.physics.remove(self)

    # -- events -----------------------------------------------------------
    def addEventHandler(self, event: str, function: Callable[..., Any] | None = None,
                        **filters: Any) -> Handler | None:
        """Call ``function(collision)`` for each ``event`` that happens to this body.

        ``event`` is one of ``hit``, ``touching``, ``separate``, ``enter``, ``stay``,
        ``exit``, ``sleep`` and ``wake``. ``above`` is a closing speed in metres a
        second a contact must exceed; ``other`` is a body, or a list of them, that
        the other side must be. The function is held weakly, so a bound method
        of a live object is called and a lambda with no other reference is not.
        The handler runs on the render thread unless the function is marked
        :func:`~OpenGLContext.physics.callbacks.physics_callback`. ``function=None``
        removes this body's handlers for ``event``. Returns the handler.
        """
        return self.physics._add_handler(event, function, (self,), **filters)
