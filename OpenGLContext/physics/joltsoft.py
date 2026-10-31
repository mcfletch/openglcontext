"""Ragdolls and soft bodies on a pyjoltphysics world: the Jolt engine's commands for them.

:class:`JoltRagdollsAndSoftBodies` is a part of
:class:`~OpenGLContext.physics.joltengine.JoltEngine`. It turns the service's
:class:`~OpenGLContext.physics.ragdolls.RagdollSpec` and
:class:`~OpenGLContext.physics.softbodies.SoftBodySpec` into pyjoltphysics
settings, keeps the service uid of every bone and soft body bound to the
uid pyjoltphysics gave it, and reads soft-body vertices from the newest
snapshot. A ragdoll's bones are movers like any dynamic body, so their poses
reach the service's snapshot, interpolated with the rest.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
import pyjoltphysics as pj

from OpenGLContext.physics.ragdolls import RagdollMode, RagdollSpec, forward_kinematics
from OpenGLContext.physics.softbodies import SoftBodyFrame, SoftBodySpec

if TYPE_CHECKING:
    from OpenGLContext.physics.types import CollisionFilter

log = logging.getLogger(__name__)

__all__ = ['JoltRagdollsAndSoftBodies', 'ragdoll_settings', 'soft_body_settings']

_MODES = {RagdollMode.KINEMATIC: pj.RagdollMode.KINEMATIC,
          RagdollMode.POWERED: pj.RagdollMode.POWERED,
          RagdollMode.LIMP: pj.RagdollMode.LIMP}
_BENDS = {'none': pj.Bend.NONE, 'distance': pj.Bend.DISTANCE, 'dihedral': pj.Bend.DIHEDRAL}
_LONG_RANGE = {'none': pj.LongRange.NONE, 'euclidean': pj.LongRange.EUCLIDEAN,
               'geodesic': pj.LongRange.GEODESIC}
#: A filter index pyjoltphysics reads as "no filter".
_NO_FILTER = 0


def ragdoll_settings(spec: RagdollSpec, filter_index: int = _NO_FILTER,
                     material: int = 0) -> pj.RagdollSettings:
    """The pyjoltphysics settings of ``spec``: a capsule a bone, placed along its axis."""
    bones = []
    for bone in spec.bones:
        axis = np.asarray(bone.axis, dtype='d')
        axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
        if bone.length > 2.0 * bone.radius:
            shape = pj.Shape.capsule(bone.radius, bone.length - 2.0 * bone.radius)
        else:
            shape = pj.Shape.sphere(max(bone.radius, bone.length / 2.0))
        bones.append(pj.Bone(
            name=bone.name, parent=bone.parent, translation=bone.translation,
            rotation=bone.rotation, shape=shape,
            shape_offset=_vector(axis * bone.length / 2.0),
            shape_rotation=_between((0.0, 1.0, 0.0), axis), mass=bone.mass,
            twist_axis=_vector(axis), plane_axis=bone.plane_axis, twist=bone.twist,
            swing=bone.swing, bend=bone.bend, strength=bone.strength, friction=bone.friction))
    return pj.RagdollSettings(
        bones=bones, self_collision=spec.self_collision, motor_frequency=spec.motor_frequency,
        motor_damping=spec.motor_damping, root_frequency=spec.root_frequency,
        root_damping=spec.root_damping, root_force=spec.root_force,
        root_torque=spec.root_torque, friction=spec.friction, restitution=spec.restitution,
        linear_damping=spec.linear_damping, angular_damping=spec.angular_damping,
        gravity_factor=spec.gravity_factor, filter=filter_index, material=material)


def soft_body_settings(spec: SoftBodySpec, filter_index: int = _NO_FILTER,
                       material: int = 0) -> pj.SoftBodySettings:
    """The pyjoltphysics settings of ``spec``; the field names are the same."""
    return pj.SoftBodySettings(
        spec.positions, faces=spec.faces, edges=spec.edges,
        edge_compliance=spec.edge_compliance, tetrahedra=spec.tetrahedra, mass=spec.mass,
        masses=spec.masses, compliance=spec.compliance,
        shear_compliance=spec.shear_compliance, bend_compliance=spec.bend_compliance,
        bend=_BENDS[spec.bend], volume_compliance=spec.volume_compliance,
        pressure=spec.pressure, long_range=_LONG_RANGE[spec.long_range],
        long_range_stretch=spec.long_range_stretch, iterations=spec.iterations,
        linear_damping=spec.linear_damping, max_velocity=spec.max_velocity,
        friction=spec.friction, restitution=spec.restitution,
        gravity_factor=spec.gravity_factor, vertex_radius=spec.vertex_radius,
        allow_sleep=spec.allow_sleep, double_sided=spec.double_sided, filter=filter_index,
        material=material, grid=spec.grid)


class JoltRagdollsAndSoftBodies:
    """The Jolt engine's ragdoll and soft-body commands, and the soft bodies' vertices.

    A part of :class:`~OpenGLContext.physics.joltengine.JoltEngine`, which
    provides the world, the uid tables and the mover list these commands
    write to.
    """

    ragdolls = True
    soft_bodies = True

    if TYPE_CHECKING:
        world: pj.World
        given: dict[int, tuple[float, int]]
        _kinds: dict[int, str]
        _movers: list[int]
        _movers_dirty: bool
        _poses: dict[int, tuple[tuple[float, ...], tuple[float, ...]]]
        _dynamic: Any
        _filters: list[CollisionFilter]

        def _bind(self, uid: int, jolt: int) -> None: ...
        def _unbind(self, uid: int) -> int | None: ...
        def jolt_uid(self, uid: int) -> int | None: ...

    def _init_soft(self) -> None:
        #: Each ragdoll's pyjoltphysics handle and its bones' service uids, by service ragdoll id.
        self._ragdoll_handles: dict[int, tuple[pj.Ragdoll, tuple[int, ...]]] = {}
        #: Each soft body's pyjoltphysics handle, by service uid.
        self._soft_handles: dict[int, pj.SoftBody] = {}
        #: Each soft body's last frame read, by service uid: ((tick, applied sequence), frame).
        self._soft_frames: dict[int, tuple[tuple[int, int], SoftBodyFrame]] = {}
        #: The snapshot's (tick, applied sequence) and the row of each soft body's uid in it.
        self._soft_rows: tuple[tuple[int, int], dict[int, int]] = ((-1, -1), {})

    # -- ragdolls ---------------------------------------------------------
    def _op_ragdoll(self, uid: int, ident: int, bones: Sequence[int],  # noqa: ARG002 named by the ragdoll
                    spec: RagdollSpec, position: Sequence[float], rotation: Sequence[float],
                    mode: RagdollMode, filter_index: int) -> None:
        settings = ragdoll_settings(spec, max(int(filter_index), 0))
        doll = self.world.add_ragdoll(settings, position=tuple(position),
                                      rotation=tuple(rotation), mode=_MODES[mode])
        places, turns = forward_kinematics(spec, position=position, rotation=rotation)
        for row, (bone_uid, jolt) in enumerate(zip(bones, doll.bones.tolist(), strict=True)):
            self._bind(bone_uid, int(jolt))
            self._kinds[bone_uid] = 'dynamic'
            self.given[bone_uid] = (float(spec.bones[row].mass), 0)
            self._poses[bone_uid] = (tuple(places[row]), tuple(turns[row]))
            self._movers.append(bone_uid)
        self._dynamic.set(doll.bones)
        self._movers_dirty = True
        self._ragdoll_handles[ident] = (doll, tuple(bones))

    def _op_ragdoll_mode(self, uid: int, ident: int, mode: RagdollMode,  # noqa: ARG002 named by the ragdoll
                         blend: float) -> None:
        found = self._ragdoll_handles.get(ident)
        if found is not None:
            found[0].set_mode(_MODES[mode], blend)

    def _op_ragdoll_pose(self, uid: int, ident: int, rotations: Any, translations: Any,  # noqa: ARG002 named by the ragdoll
                         position: Any, rotation: Any) -> None:
        found = self._ragdoll_handles.get(ident)
        if found is not None:
            found[0].set_pose(rotations, translations, position, rotation)

    def _op_ragdoll_clip(self, uid: int, ident: int, times: Any, rotations: Any,  # noqa: ARG002 named by the ragdoll
                         translations: Any, loop: bool) -> None:
        found = self._ragdoll_handles.get(ident)
        if found is None:
            return
        if len(times):
            found[0].play(times, rotations, translations, loop)
        else:
            found[0].stop()

    def _op_ragdoll_strength(self, uid: int, ident: int, strength: Any) -> None:  # noqa: ARG002 named by the ragdoll
        found = self._ragdoll_handles.get(ident)
        if found is not None:
            found[0].set_strength(strength)

    def _op_ragdoll_remove(self, uid: int, ident: int) -> None:  # noqa: ARG002 named by the ragdoll
        found = self._ragdoll_handles.pop(ident, None)
        if found is None:
            return
        doll, bones = found
        for bone_uid in bones:
            self._unbind(bone_uid)
            self.given.pop(bone_uid, None)
        self._movers_dirty = True
        self.world.remove_ragdolls([doll.id])

    # -- soft bodies ------------------------------------------------------
    def _op_soft_body(self, uid: int, spec: SoftBodySpec, position: Sequence[float],
                      rotation: Sequence[float], pins: tuple[Any, Any, Any],
                      filter_index: int) -> None:
        vertices, points, owners = pins
        settings = soft_body_settings(spec, max(int(filter_index), 0))
        bodies = self._pin_bodies(owners)
        handle = self.world.add_soft_body(
            settings, position=tuple(position), rotation=tuple(rotation),
            pins=(list(vertices), points) if len(vertices) else None,
            pin_bodies=bodies if len(vertices) else None)
        self._bind(uid, handle.uid)
        self._kinds[uid] = 'soft'
        self.given[uid] = (spec.total_mass(), 0)
        self._poses[uid] = (tuple(position), tuple(rotation))
        self._soft_handles[uid] = handle

    def _pin_bodies(self, owners: Sequence[int | None]) -> list[int]:
        """The pyjoltphysics uid of each pin's body, 0 for the world."""
        out = []
        for owner in owners:
            jolt = None if owner is None else self.jolt_uid(int(owner))
            out.append(0 if jolt is None else int(jolt))
        return out

    def _op_soft_pins(self, uid: int, vertices: Any, points: Any,
                      owners: Sequence[int | None]) -> None:
        handle = self._soft_handles.get(uid)
        if handle is not None:
            handle.pin(list(vertices), points, self._pin_bodies(owners))

    def _op_wind(self, uid: int, force: Sequence[float]) -> None:
        handle = self._soft_handles.get(uid)
        if handle is not None:
            handle.set_wind(force)

    def _forget_soft(self, uid: int) -> None:
        """Let go of soft body ``uid``'s handle and frame, as the body is removed."""
        self._soft_handles.pop(uid, None)
        self._soft_frames.pop(uid, None)

    def soft_body_frame(self, uid: int) -> SoftBodyFrame | None:
        """Soft body ``uid``'s vertices from the newest snapshot, or None before it holds them."""
        handle = self._soft_handles.get(uid)
        snapshot = self.world.latest()
        if handle is None or snapshot is None:
            return None
        tick = int(snapshot.tick)
        # A flush publishes again at the same tick with what it applied: the sequence tells them apart.
        key = (tick, int(snapshot.applied_seq))
        held = self._soft_frames.get(uid)
        if held is not None and held[0] == key:
            return held[1]
        rows = snapshot.soft_bodies
        if self._soft_rows[0] != key:
            self._soft_rows = (key, rows.rows())
        i = self._soft_rows[1].get(handle.uid)
        if i is None:
            return None
        frame = SoftBodyFrame(int(rows.version[i]), tick, np.array(rows.origin[i], dtype='d'),
                              rows.vertices(i), rows.normals_of(i))
        self._soft_frames[uid] = (key, frame)
        return frame

    def world_costs(self) -> dict[str, float]:
        """Mean world-thread milliseconds a tick on ragdolls and on soft bodies, and their counts."""
        stats = self.world.stats()
        return {'ragdolls': float(len(self._ragdoll_handles)),
                'soft bodies': float(len(self._soft_handles)),
                'ragdolls ms': float(stats.get('ragdolls_ms', 0.0)),
                'soft bodies ms': float(stats.get('soft_bodies_ms', 0.0))}


def _vector(values: Any) -> tuple[float, float, float]:
    x, y, z = (float(v) for v in values)
    return (x, y, z)


def _between(a: Sequence[float], b: np.ndarray) -> tuple[float, float, float, float]:
    """The shortest rotation taking unit ``a`` to unit ``b``."""
    u = np.asarray(a, dtype='d')
    d = float(np.dot(u, b))
    if d < -0.999999:
        axis = np.cross(u, (1.0, 0.0, 0.0))
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(u, (0.0, 0.0, 1.0))
        axis /= np.linalg.norm(axis)
        return (float(axis[0]), float(axis[1]), float(axis[2]), 0.0)
    c = np.cross(u, b)
    q = np.array([c[0], c[1], c[2], 1.0 + d])
    q /= np.linalg.norm(q)
    return (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
