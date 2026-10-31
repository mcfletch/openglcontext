"""The Jolt engine's vehicles: the service's vehicles as pyjoltphysics vehicles, and their reads.

:class:`JoltVehicles` belongs to one :class:`~OpenGLContext.physics.joltengine.JoltEngine`.
It keeps the service's vehicle ids against pyjoltphysics' :class:`~pyjoltphysics.Vehicle`
handles, collects the inputs every :class:`~OpenGLContext.physics.vehicles.Vehicle`
gives into one ``vehicle_inputs`` batch, and builds each vehicle's
:class:`~OpenGLContext.physics.vehicles.VehicleState` from the newest snapshot,
once a vehicle a published tick.

Where inputs land: the engine sends the waiting inputs before a lockstep run
of ticks (so a frame's inputs drive its first tick), once a frame for a
free-running world, and after the ``'before-step'`` handlers of each tick (so
inputs a handler gives drive that tick).
"""
from __future__ import annotations

import math
import threading
from typing import TYPE_CHECKING, Any

import numpy as np
import pyjoltphysics as pj

from OpenGLContext.physics.records import PhysicsEvent
from OpenGLContext.physics.vehicles import KINDS, WHEEL_CASTS, Impact, VehicleState, WheelState

if TYPE_CHECKING:
    from OpenGLContext.physics.joltengine import JoltEngine
    from OpenGLContext.physics.vehicles import Surface, VehicleSettings

__all__ = ['JoltVehicles', 'native_settings']

_PHASES = {int(pj.EventPhase.IMPACT): 'impact', int(pj.EventPhase.CRASH): 'crash'}


def native_settings(settings: VehicleSettings) -> pj.VehicleSettings:
    """``settings`` as pyjoltphysics' settings of the same field names."""
    plain = settings.as_dict()
    plain['kind'] = int(pj.VehicleKind(KINDS.index(settings.kind)))
    plain['cast'] = int(pj.WheelCast(WHEEL_CASTS.index(settings.cast)))
    return pj.VehicleSettings.from_dict(plain)


class JoltVehicles:
    """The vehicles of one Jolt engine, by the service's vehicle id."""

    def __init__(self, engine: JoltEngine) -> None:
        self.engine = engine
        self._native: dict[int, pj.Vehicle] = {}
        #: The chassis's service uid of each vehicle.
        self._chassis: dict[int, int] = {}
        #: The service's vehicle id of each pyjoltphysics vehicle id.
        self._ids: dict[int, int] = {}
        self._inputs: dict[int, tuple[float, float, float, float]] = {}
        self._lock = threading.Lock()
        #: The states built from the snapshot of ``_read_at``: (tick, applied batch).
        self._states: dict[int, VehicleState] = {}
        self._read_at: tuple[int, int] | None = None

    def __len__(self) -> int:
        return len(self._native)

    def add(self, vid: int, chassis: int, settings: VehicleSettings) -> None:
        """Make vehicle ``vid`` on the body of service uid ``chassis``."""
        world = self.engine.world
        jolt = self.engine.jolt_uid(chassis)
        if jolt is None:
            raise ValueError('vehicle %d: body %d is not in the world' % (vid, chassis))
        made = world.add_vehicle(jolt, native_settings(settings))
        # Blows held against the chassis (a car pressed into a wall) are persist
        # records, which pyjoltphysics reports for a body flagged REPORT.
        world.set_flags([jolt], pj.BodyFlag.REPORT, True)
        self._native[vid] = made
        self._chassis[vid] = chassis
        self._ids[made.id] = vid

    def remove(self, vid: int) -> None:
        """Take vehicle ``vid`` out; its chassis stays a body."""
        made = self._forget(vid)
        if made is not None:
            made.remove()

    def chassis_removed(self, chassis: int) -> list[int]:
        """Forget the vehicles on the body of uid ``chassis``, which the world removes with it."""
        gone = [vid for vid, uid in self._chassis.items() if uid == chassis]
        for vid in gone:
            self._forget(vid)
        return gone

    def _forget(self, vid: int) -> pj.Vehicle | None:
        made = self._native.pop(vid, None)
        self._chassis.pop(vid, None)
        with self._lock:
            self._inputs.pop(vid, None)
        self._states.pop(vid, None)
        if made is not None:
            self._ids.pop(made.id, None)
        return made

    # -- inputs ---------------------------------------------------------
    def input(self, vid: int, values: tuple[float, float, float, float]) -> None:
        """Hold ``values`` (throttle, steer, brake, handbrake) for the next :meth:`send`."""
        if vid in self._native:
            with self._lock:
                self._inputs[vid] = values

    def send(self) -> None:
        """Send the inputs given since the last call, as one batch."""
        with self._lock:
            if not self._inputs:
                return
            waiting, self._inputs = self._inputs, {}
        ids = [self._native[vid].id for vid in waiting if vid in self._native]
        rows = [values for vid, values in waiting.items() if vid in self._native]
        if ids:
            self.engine.world.vehicle_inputs(np.asarray(ids, dtype=np.uint32),
                                             np.asarray(rows, dtype=np.float32))

    def surface(self, vid: int, wheel: int | None, surface: Surface | None) -> None:
        """Set the ground under one wheel of ``vid``, or all of them; None gives them to the materials."""
        made = self._native.get(vid)
        if made is None:
            return
        grip = None if surface is None else float(surface.grip)
        rolling = 0.0 if surface is None else float(surface.rolling)
        self.engine.world.set_vehicle_surfaces(
            [made.id], [-1 if wheel is None else int(wheel)], [grip], [rolling])

    # -- reads ------------------------------------------------------------
    def state(self, vid: int) -> VehicleState | None:
        """Vehicle ``vid`` as the newest snapshot holds it; None before a tick has stepped it."""
        made = self._native.get(vid)
        snapshot = self.engine.world.latest()
        if made is None or snapshot is None:
            return None
        at = (int(snapshot.tick), int(snapshot.applied_seq))
        if at != self._read_at:
            self._read_at, self._states = at, {}
        found = self._states.get(vid)
        if found is None:
            found = self._build(made, snapshot)
            if found is not None:
                self._states[vid] = found
        return found

    def _build(self, made: pj.Vehicle, snapshot: Any) -> VehicleState | None:
        rows = snapshot.vehicles
        index = np.flatnonzero(rows.id == made.id)
        if not len(index):
            return None
        i = int(index[0])
        row = snapshot.rows.get(made.chassis)
        velocity = (np.zeros(3) if row is None
                    else np.asarray(snapshot.linear_velocity[row], dtype='d'))
        speed = float(np.linalg.norm(velocity))
        first, count = int(rows.first_wheel[i]), int(rows.wheel_count[i])
        wheels = rows.wheels
        names = self._material_names()
        made_wheels = []
        for w in range(first, first + count):
            slip_ratio, slip_angle = (float(v) for v in wheels.slip[w])
            grounded = bool(wheels.contact[w])
            ground = self._body(int(wheels.ground[w])) if grounded else None
            made_wheels.append(WheelState(
                position=np.array(wheels.position[w], dtype='d'),
                orientation=np.array(wheels.orientation[w], dtype='d'),
                length=float(wheels.length[w]), compression=float(wheels.compression[w]),
                steer=float(wheels.steer[w]), angle=float(wheels.angle[w]),
                spin=float(wheels.spin[w]), load=float(wheels.load[w]),
                slip_ratio=slip_ratio, slip_angle=slip_angle,
                slip=speed * math.sin(slip_angle) if grounded else 0.0,
                grounded=grounded, ground=ground,
                material=names.get(int(wheels.material[w])) if grounded else None,
                grip=float(wheels.grip[w]),
                contact=np.array(wheels.contact_point[w], dtype='d'),
                normal=np.array(wheels.contact_normal[w], dtype='d')))
        struck = int(rows.impact_uid[i])
        impact = None
        if struck:
            impact = Impact(self._body(struck), float(rows.impact_speed[i]),
                            float(rows.impact_impulse[i]))
        throttle, steer, brake, handbrake = (float(v) for v in rows.input[i])
        return VehicleState(
            speed=speed, forward_speed=float(rows.forward_speed[i]), rpm=float(rows.rpm[i]),
            gear=int(rows.gear[i]), steer_angle=float(rows.steer[i]), throttle=throttle,
            steer=steer, brake=brake, handbrake=handbrake, wheels=tuple(made_wheels),
            impact=impact, step=int(snapshot.tick))

    def _body(self, jolt: int) -> Any:
        uid = self.engine.service_uid(jolt)
        return None if uid is None else self.engine.body_of(uid)

    def _material_names(self) -> dict[int, str]:
        return {index: key[1] for key, index in self.engine.material_rows().items()
                if key[0] == 'name'}

    # -- events -----------------------------------------------------------
    def event(self, record: Any, dt: float) -> PhysicsEvent | None:
        """The service's ``'impact'`` or ``'crash'`` event of a VEHICLE record, naming the chassis."""
        vid = self._ids.get(int(record['a']))
        phase = _PHASES.get(int(record['phase']))
        if vid is None or phase is None:
            return None
        chassis = self._chassis.get(vid)
        if chassis is None:
            return None
        tick = int(record['tick'])
        return PhysicsEvent('vehicle', phase, chassis, self.engine.service_uid(int(record['b'])),
                            np.array(record['point'], dtype='d'),
                            np.array(record['normal'], dtype='d'), float(record['approach']),
                            float(record['impulse']), 0.0, 0.0, 0.0, tick, tick * dt)
