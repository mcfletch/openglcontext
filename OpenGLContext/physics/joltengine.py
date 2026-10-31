"""JoltEngine: the service's world as a Jolt world, stepped by pyjoltphysics on its own thread.

The world thread belongs to pyjoltphysics and is the only thread that steps
Jolt. It runs in one of two ways:

* lockstep - :meth:`JoltEngine.collect` runs exactly the ticks the frame owes
  (``run_ticks``), while the render thread waits with the GIL released. A
  world in ``'inline'`` mode, one held there by ``Physics.pin_inline`` (a
  capture, a replay), and any world with framed characters runs this way.
  Each character's moves for a tick are submitted before that tick runs, so
  an input reaches its character at the next tick with no wait, and a run
  along a course is steered at every tick.
* free-running - the world thread ticks at the definition's rate and the
  render thread reads the newest snapshot each frame.

Commands keep the service's vocabulary
(:class:`~OpenGLContext.physics.records.Command`); each becomes one or more
pyjoltphysics batches. Bodies keep the service's uids: the engine holds the
uid pyjoltphysics assigned to each, and turns event records and query results
back into service uids.

A ground given by a sample function (``Physics.add_ground``) is held as
height field tiles around the places that need ground: the characters, the
awake dynamic bodies and the points :meth:`JoltEngine.add_focus` names. Tiles
are sampled on the render thread and swapped in one batch.
"""
from __future__ import annotations

import collections
import dataclasses
import logging
import math
import os
import sys
import threading
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
import pyjoltphysics as pj

from OpenGLContext.events.framestep import FixedSteps
from OpenGLContext.physics.engine import Engine, LivePose, Outbox, RawHit
from OpenGLContext.physics.poses import vrml_rotation_to_quat
from OpenGLContext.physics.records import (
    BodyBatch, BodySpec, Command, PhysicsEvent, Snapshot, Step,
)
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.types import (
    CharacterState, CollisionFilter, EngineInfo, Material, WorldCounts,
)

if TYPE_CHECKING:
    from OpenGLContext.physics.proxy import Proxy

__all__ = ['GroundTiles', 'JoltController', 'JoltEngine', 'axis_angles']

log = logging.getLogger(__name__)

_ZERO3 = np.zeros(3)
#: The filter index of a body with no collision filter: outside every table, so it meets every filter.
NO_FILTER = 0xFFFF
#: Removed bodies' uids kept for turning their last event records back into service uids.
RETIRED_KEPT = 4096
#: A dynamic body whose shape reaches less than this, in metres, gets continuous collision detection.
CCD_BELOW = 0.1
#: Metres a resting body may sink into what it rests on before the solver separates them.
PENETRATION_SLOP = 0.005
#: Metres below its feet a new character looks for the ground it stands on.
SEAT_SEARCH = 0.05
#: Metres the edges of a box that does not move are rounded by.
STATIC_ROUNDING = 0.001
#: The OMI combine modes, by the names the service's materials use.
_COMBINE = {'average': pj.Combine.AVERAGE, 'minimum': pj.Combine.MINIMUM,
            'multiply': pj.Combine.MULTIPLY, 'maximum': pj.Combine.MAXIMUM}
_STATE = {pj.CharacterState.STANDING: CharacterState.STANDING,
          pj.CharacterState.CROUCHING: CharacterState.CROUCHING,
          pj.CharacterState.SLIDING: CharacterState.SLIDING,
          pj.CharacterState.AIRBORNE: CharacterState.AIRBORNE,
          pj.CharacterState.DOWN: CharacterState.DOWN,
          pj.CharacterState.SWIMMING: CharacterState.SWIMMING,
          pj.CharacterState.FLYING: CharacterState.FLYING}
#: The field of the capabilities that names each mode's speed.
_MODE_SPEEDS = {'walk': 'walkSpeed', 'run': 'runSpeed', 'sprint': 'sprintSpeed',
                'crouch': 'crouchSpeed'}
_PHASE = {pj.EventPhase.BEGIN: 'begin', pj.EventPhase.PERSIST: 'persist', pj.EventPhase.END: 'end'}
_TRIGGER_PHASE = {pj.EventPhase.BEGIN: 'enter', pj.EventPhase.PERSIST: 'stay',
                  pj.EventPhase.END: 'exit'}


def default_threads() -> int:
    """Jolt job threads: 4, or the core count less two where that is smaller, and at least 1."""
    return max(1, min(4, (os.cpu_count() or 1) - 2))


def axis_angles(quaternions: np.ndarray) -> np.ndarray:
    """Unit quaternions ``(n, 4)`` as VRML axis-angle rows ``(n, 4)``; no rotation is ``(0, 1, 0, 0)``."""
    q = np.asarray(quaternions, dtype='d')
    out = np.zeros((len(q), 4))
    if not len(q):
        return out
    norm = np.linalg.norm(q, axis=1)
    q = q / np.maximum(norm, 1e-12)[:, None]
    w = np.clip(q[:, 3], -1.0, 1.0)
    s = np.sqrt(np.maximum(1.0 - w * w, 0.0))
    turned = s >= 1e-9
    out[:, 1] = 1.0
    out[turned, :3] = q[turned, :3] / s[turned, None]
    out[turned, 1] = q[turned, 1] / s[turned]
    out[:, 3] = np.where(turned, 2.0 * np.arccos(w), 0.0)
    return out


class _Bits:
    """A growable boolean per pyjoltphysics uid."""

    def __init__(self) -> None:
        self.bits = np.zeros(1024, dtype=bool)

    def set(self, uids: Any, on: bool = True) -> None:
        ids = np.atleast_1d(np.asarray(uids, dtype=np.int64))
        if not len(ids):
            return
        top = int(ids.max())
        if top >= len(self.bits):
            grown = np.zeros(max(top + 1, 2 * len(self.bits)), dtype=bool)
            grown[:len(self.bits)] = self.bits
            self.bits = grown
        self.bits[ids] = on

    def of(self, uids: Any) -> np.ndarray:
        ids = np.asarray(uids, dtype=np.int64)
        inside = ids < len(self.bits)
        found = np.zeros(len(ids), dtype=bool)
        found[inside] = self.bits[ids[inside]]
        return found


class GroundTiles:
    """Height field tiles of a sample function, kept around foci.

    ``cells`` is the tile's side in cells of ``spacing`` metres; tiles within
    ``ring`` tiles of a focus's tile are kept.
    """

    def __init__(self, uid: int, proxy: Proxy, material: int, filter_index: int,
                 cells: int = 32, ring: int = 1) -> None:
        params = proxy.params
        self.uid = uid
        self.sample = params['sample']
        self.vectorized = bool(params.get('vectorized'))
        self.extent = params.get('extent')
        feature = float(params.get('feature') or 1.0)
        self.spacing = float(min(max(feature * 0.5, 0.25), 2.0))
        self.cells = int(cells)
        self.ring = int(ring)
        self.material = material
        self.filter = filter_index
        #: Whether strikes on the ground are reported to the service.
        self.reported = False
        #: The pyjoltphysics uid of each tile held, by tile coordinate.
        self.tiles: dict[tuple[int, int], int] = {}
        #: Tiles a query asked for, kept until the frame count given.
        self.asked: dict[tuple[int, int], int] = {}

    @property
    def side(self) -> float:
        """A tile's side, in metres."""
        return self.cells * self.spacing

    def wanted(self, foci: np.ndarray) -> set[tuple[int, int]]:
        """The tiles within the ring of each focus, clipped to the extent."""
        if not len(foci):
            return set()
        side = self.side
        centres = np.unique(np.floor(np.asarray(foci, dtype='d')[:, [0, 2]] / side).astype(np.int64),
                            axis=0)
        found: set[tuple[int, int]] = set()
        ring = range(-self.ring, self.ring + 1)
        for i, j in centres.tolist():
            for di in ring:
                for dj in ring:
                    found.add((i + di, j + dj))
        if self.extent is not None:
            (x0, z0), (x1, z1) = self.extent
            found = {(i, j) for i, j in found
                     if (i + 1) * side >= x0 and i * side <= x1
                     and (j + 1) * side >= z0 and j * side <= z1}
        return found

    def along(self, start: np.ndarray, end: np.ndarray) -> set[tuple[int, int]]:
        """The tiles under the segment from ``start`` to ``end``, and the ring around each, at most 64 samples."""
        span = float(np.linalg.norm((end - start)[[0, 2]]))
        count = min(64, max(2, int(span / self.side) + 2))
        points = start[None] + (end - start)[None] * np.linspace(0.0, 1.0, count)[:, None]
        return self.wanted(points)

    def batch(self, tile: tuple[int, int], flags: int) -> pj.BodyBatch:
        """The static body of one tile: the function sampled at its grid, its body at its corner."""
        i, j = tile
        n = self.cells + 1
        x0, z0 = i * self.side, j * self.side
        xs, zs = np.meshgrid(x0 + np.arange(n) * self.spacing, z0 + np.arange(n) * self.spacing)
        if self.vectorized:
            heights = np.asarray(self.sample(xs, zs), dtype='d').reshape(n, n)
        else:
            heights = np.vectorize(lambda x, z: float(self.sample(x, z)))(xs, zs)
        return pj.BodyBatch.heightfield(heights, origin=(x0, 0.0, z0), spacing=self.spacing,
                                        bits_per_sample=16, material=self.material,
                                        filter=self.filter, flags=flags)


class JoltController:
    """A Jolt character as :class:`~OpenGLContext.physics.character.Character` drives a controller.

    Inputs become character batches; readings come from the character rows of
    the newest snapshot the engine has read. An input that changes what the
    character is doing (a knock-down, a slide, a crouch, flight, swimming) is
    read back at once and held until the world reports the tick that applied
    it. ``update(dt)`` advances the world by the ticks ``dt`` owes, moving
    every character: the world thread moves characters inside its ticks.
    """

    def __init__(self, engine: JoltEngine, character: pj.Character, capabilities: Any,
                 centre: np.ndarray, gravity: float = 9.81) -> None:
        self.engine = engine
        #: The character's own gravity, m/s2 downward.
        self.gravity = float(gravity)
        self.native = character
        self.capabilities = capabilities
        #: The capabilities the native character was made with.
        self._made_with = capabilities
        self.position = np.asarray(centre, dtype='d').copy()
        self.velocity = np.zeros(3)
        self.previous = self.position.copy()
        self.eye_point = self.position + np.array(
            [0.0, float(capabilities.eyeHeight) - float(capabilities.standHeight) / 2.0, 0.0])
        self.grounded = False
        self.native_state = pj.CharacterState.AIRBORNE
        self.height = float(capabilities.standHeight)
        self.slide_progress = 0.0
        self.ground_normal: np.ndarray | None = None
        self.ground_uid = 0
        self.ground_material = 0
        self.stuck = False
        self.landing: float | None = None
        self._advancing = False
        self.move_dir = np.zeros(3)
        self.push = np.zeros(3)
        self.pushing = None
        #: The capabilities under the omi controller's name, which the movement modes read
        #: and retune: a changed speed reaches the world as the move's speed.
        self.caps = _Capabilities(self, capabilities)
        self._move_speed: float | None = None
        self._mode = 'walk'
        #: A state an input asked for, held until a snapshot includes the input's batch.
        self._expected: tuple[int, pj.CharacterState] | None = None
        self._landed_tick = 0
        #: The bodies the character passes through, by service uid; edits reach the world.
        self.ignore = _IgnoreSet(self)
        #: A position a teleport put the capsule at, held until a snapshot includes it.
        self._placed: tuple[int, np.ndarray] | None = None

    # -- readings ---------------------------------------------------------
    def read(self, rows: Any, row: int, tick: int, applied_seq: int) -> None:
        """Take this character's row ``row`` of ``rows``, from a snapshot of ``tick``."""
        if self._placed is not None:
            if applied_seq < self._placed[0]:
                return
            self._placed = None
        expected = self._expected
        if expected is not None and applied_seq >= expected[0]:
            self._expected = expected = None
        self.position = np.array(rows.position[row], dtype='d')
        self.previous = np.array(rows.previous[row], dtype='d')
        self.velocity = np.array(rows.velocity[row], dtype='d')
        self.eye_point = np.array(rows.eye[row], dtype='d')
        self.grounded = bool(rows.grounded[row])
        if expected is None:
            self.native_state = pj.CharacterState(int(rows.state[row]))
            self.height = self._exact(float(rows.height[row]))
        self.slide_progress = float(rows.slide_progress[row])
        self.ground_normal = np.array(rows.ground_normal[row], dtype='d') if self.grounded else None
        self.ground_uid = int(rows.ground_uid[row])
        self.ground_material = int(rows.ground_material[row])
        self.stuck = bool(rows.stuck[row])
        landed = int(rows.landed_tick[row])
        if landed == tick and landed != self._landed_tick:
            self._landed_tick = landed
            speed = float(rows.landing_speed[row])
            # Within one advance of several ticks a landing stays until the advance ends.
            self.landing = speed if not self._advancing else max(self.landing or 0.0, speed)
        elif not self._advancing:
            self.landing = None

    def _exact(self, height: float) -> float:
        """``height`` as the capabilities give it where it is one of theirs read back in float32."""
        for given in (self.capabilities.standHeight, self.capabilities.crouchHeight):
            if abs(height - float(given)) < 1e-5:
                return float(given)
        return height

    @property
    def vy(self) -> float:
        return float(self.velocity[1])

    @vy.setter
    def vy(self, speed: float) -> None:
        """Launch the capsule at its velocity with the vertical part ``speed``, m/s."""
        self.velocity = np.array([self.velocity[0], float(speed), self.velocity[2]])
        self.native.apply_impulse(tuple(float(v) for v in self.velocity))

    def place(self, centre: Any) -> None:
        """Put the capsule's centre at ``centre`` as it is, with no search for a floor; a flier flies on."""
        at = np.asarray(centre, dtype='d')[:3].copy()
        flying = self.flying
        seq = self.native.teleport(tuple(float(v) for v in at), 0.0)
        self._placed = (seq, at)
        self.eye_point = self.eye_point + (at - self.position)
        # In place: a platform holding the controller's position array sees the move.
        self.position[:] = at
        if flying:
            self._expect(pj.CharacterState.FLYING, self.native.set_fly(True))

    @property
    def state(self) -> Any:
        """The state as the omi controller's enumeration has it where omi_physics is installed, else the service's."""
        neutral = _STATE[self.native_state]
        return _engine_state(neutral)

    @property
    def swimming(self) -> bool:
        return self.native_state == pj.CharacterState.SWIMMING

    @property
    def crouching(self) -> bool:
        return self.native_state in (pj.CharacterState.CROUCHING, pj.CharacterState.SLIDING)

    def base(self) -> np.ndarray:
        """Where the feet are."""
        return self.position - np.array([0.0, self.height / 2.0, 0.0])

    def eye(self) -> np.ndarray:
        """Where the eyes are."""
        return self.eye_point.copy()

    @property
    def move_speed(self) -> float | None:
        """The speed the moves go at, m/s, or None for the speed of the move's mode."""
        return self._move_speed

    @move_speed.setter
    def move_speed(self, speed: float | None) -> None:
        self._move_speed = speed
        self.native.set_move(self.move_dir, self._mode, speed)

    def _retuned(self) -> float | None:
        """The mode's speed where the capabilities were retuned since the character was made, else None."""
        name = _MODE_SPEEDS.get(self._mode, 'walkSpeed')
        now = getattr(self.capabilities, name)
        return None if now == getattr(self._made_with, name) else float(now)

    def _expect(self, state: pj.CharacterState, seq: int) -> None:
        self.native_state = state
        self._expected = (seq, state)

    def speed(self) -> float:
        if self._move_speed is not None:
            return float(self._move_speed)
        return float(getattr(self.capabilities, _MODE_SPEEDS.get(self._mode, 'walkSpeed')))

    # -- inputs -----------------------------------------------------------
    def set_move(self, direction: Any, mode: str = 'walk', speed: float | None = None) -> None:
        heading = np.asarray(direction, dtype='d')[:3]
        self.move_dir = np.array([heading[0], 0.0, heading[2]])
        self._mode = mode
        self._move_speed = speed
        self.native.set_move(self.move_dir, mode, speed if speed is not None else self._retuned())

    def set_fly_move(self, direction: Any) -> None:
        self.move_dir = np.asarray(direction, dtype='d')[:3].copy()
        self.native.set_fly_move(self.move_dir)

    def jump(self) -> bool:
        if not self.capabilities.canJump or self.native_state in (
                pj.CharacterState.DOWN, pj.CharacterState.FLYING):
            return False
        seq = self.native.jump()
        if self.grounded:
            # Read back at once: the launch speed the world gives the jump.
            launch = math.sqrt(2.0 * max(self.gravity, 0.0) * float(self.capabilities.jumpHeight))
            self.velocity = np.array([self.velocity[0], launch, self.velocity[2]])
            self.grounded = False
            self._expect(pj.CharacterState.AIRBORNE, seq)
        return True

    def apply_impulse(self, velocity: Any) -> None:
        given = np.asarray(velocity, dtype='d')[:3]
        seq = self.native.apply_impulse(tuple(float(v) for v in given))
        self.velocity = given.copy()
        if given[1] > 0.0:
            self.grounded = False
            self._expect(pj.CharacterState.AIRBORNE, seq)

    def knockback(self, impulse: Any) -> None:
        given = np.asarray(impulse, dtype='d')[:3]
        seq = self.native.knockback(tuple(float(v) for v in given))
        self.velocity = self.velocity + given / max(float(self.capabilities.mass), 1e-9)
        if given[1] > 0.0:
            self.grounded = False
            self._expect(pj.CharacterState.AIRBORNE, seq)

    def set_crouch(self, crouch: bool) -> bool:
        if crouch and not self.capabilities.canCrouch:
            return False
        seq = self.native.set_crouch(bool(crouch))
        if self.native_state in (pj.CharacterState.STANDING, pj.CharacterState.CROUCHING):
            self._expect(pj.CharacterState.CROUCHING if crouch else pj.CharacterState.STANDING, seq)
            self._resize(float(self.capabilities.crouchHeight if crouch
                               else self.capabilities.standHeight))
        return bool(crouch)

    def _resize(self, height: float) -> None:
        """Read the capsule back at ``height``, its feet where they are."""
        feet = float(self.position[1]) - self.height / 2.0
        self.height = height
        self.position = np.array([self.position[0], feet + height / 2.0, self.position[2]])

    @property
    def flying(self) -> bool:
        return self.native_state == pj.CharacterState.FLYING

    def set_fly(self, flying: bool) -> bool:
        if flying and not self.capabilities.canFly:
            return False
        seq = self.native.set_fly(bool(flying))
        self._expect(pj.CharacterState.FLYING if flying else pj.CharacterState.AIRBORNE, seq)
        return bool(flying)

    def set_swim(self, swimming: bool, buoyancy: float = 0.9) -> None:
        seq = self.native.set_swim(bool(swimming), float(buoyancy))
        if swimming:
            self._expect(pj.CharacterState.SWIMMING, seq)

    def slide(self, duration: float, rise: float = 0.3, steer: bool = False) -> bool:
        if not self.grounded:
            return False
        seq = self.native.slide(float(duration), float(rise), bool(steer))
        self._expect(pj.CharacterState.SLIDING, seq)
        self._resize(float(self.capabilities.crouchHeight))
        return True

    def extend_slide(self, duration: float) -> bool:
        if self.native_state != pj.CharacterState.SLIDING:
            return False
        self.native.extend_slide(float(duration))
        return True

    def end_slide(self) -> bool:
        if self.native_state != pj.CharacterState.SLIDING:
            return False
        self._expect(pj.CharacterState.STANDING, self.native.end_slide())
        self._resize(float(self.capabilities.standHeight))
        return True

    def knock_down(self) -> None:
        self._expect(pj.CharacterState.DOWN, self.native.knock_down())

    def get_up(self, start_speed: float | None = None) -> None:
        self.native.get_up(start_speed)

    #: Metres below the feet a teleport looks for a floor to stand on.
    SEARCH = 4.0

    def safe_bind(self, centre: Any) -> bool:
        """Teleport the capsule's centre to ``centre``, standing on the floor under it.

        The floor is the first surface a ray meets down the capsule's axis from
        its top to :attr:`SEARCH` metres below its feet: a capsule whose feet
        are inside a floor is raised onto it, and one above a floor drops onto
        it, as the omi controller's teleport does. With no floor in reach it
        stays where it is put.
        """
        at = np.asarray(centre, dtype='d')[:3].copy()
        half = self.height / 2.0
        top = self.engine.floor_under(at, half, self.native.id, below=self.SEARCH)
        if top is not None:
            at[1] = top + half
        seq = self.native.teleport(tuple(float(v) for v in at))
        self._placed = (seq, at)
        self.position = at
        self.previous = at.copy()
        self.eye_point = at + np.array(
            [0.0, float(self.capabilities.eyeHeight) - float(self.capabilities.standHeight) / 2.0, 0.0])
        self.velocity = np.zeros(3)
        return True

    def set_pass_group(self, group: int) -> None:
        self.native.set_pass_group(int(group))

    def update(self, dt: float) -> None:
        """Advance the world by the ticks ``dt`` owes; the world thread moves the character in them.

        A landing in any of those ticks is :attr:`landing` once the advance ends.
        """
        self.landing = None
        self._advancing = True
        try:
            self.engine.advance(dt)
        finally:
            self._advancing = False


class _Capabilities:
    """A Jolt character's capabilities as the movement modes read and retune them.

    Reads answer the character's capabilities. Setting a mode's speed sends the
    character's move again at the speed of its mode; the other capabilities are
    the ones it was made with.
    """

    def __init__(self, controller: JoltController, capabilities: Any) -> None:
        object.__setattr__(self, '_controller', controller)
        object.__setattr__(self, '_values', capabilities)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, '_values'), name)

    def __setattr__(self, name: str, value: Any) -> None:
        values = object.__getattribute__(self, '_values')
        updated = dataclasses.replace(values, **{name: value})
        object.__setattr__(self, '_values', updated)
        controller = object.__getattribute__(self, '_controller')
        controller.capabilities = updated
        if name.endswith('Speed') and controller._move_speed is None:
            controller.native.set_move(controller.move_dir, controller._mode, controller._retuned())


class _IgnoreSet(set[int]):
    """The service uids a Jolt character passes through; each edit is sent to the world."""

    def __init__(self, controller: JoltController) -> None:
        super().__init__()
        self._controller = controller

    def _sent(self) -> None:
        engine = self._controller.engine
        engine.world.set_character_ignore(
            self._controller.native.id, [engine.jolt_uid(uid) for uid in self
                                         if engine.jolt_uid(uid) is not None])

    def add(self, uid: int) -> None:
        if uid not in self:
            super().add(uid)
            self._sent()

    def discard(self, uid: object) -> None:
        if uid in self:
            super().discard(uid)
            self._sent()


def _engine_state(state: CharacterState) -> Any:
    """``state`` as omi_physics' enumeration has it, where omi_physics is installed."""
    try:
        from OpenGLContext.physics.omi_adapter import engine_character_state  # noqa: PLC0415 optional
    except ImportError:
        return state
    return engine_character_state(state)


class JoltEngine(Engine):
    """A Jolt world, stepped by pyjoltphysics on its world thread."""

    name = 'jolt'
    stand_ins = False

    def __init__(self, definition: PhysicsDefinition, wake: Callable[[], Any] | None = None) -> None:
        super().__init__(definition)
        self._wake = wake
        self._tick_hz = float(definition.tickHz)
        self._max_catch_up = float(definition.maxCatchUp)
        gravity = tuple(float(v) for v in definition.gravity)
        self.world = pj.World(pj.WorldSettings(
            tick_hz=self._tick_hz, max_catch_up=self._max_catch_up, gravity=gravity,
            threads=default_threads(), penetration_slop=PENETRATION_SLOP))
        self._mode = str(definition.mode)
        self._pinned = False
        self._running = False
        self._clock = FixedSteps(1.0 / self._tick_hz, self._max_catch_up)
        #: How many ticks the last :meth:`collect` ran, and how far into the next it ends.
        self.owed = 0
        self.alpha = 1.0
        # -- uids
        self._jolt: dict[int, int] = {}
        self._svc: dict[int, int] = {}
        self._retired: collections.deque[int] = collections.deque()
        self._kinds: dict[int, str] = {}
        self._batches: dict[int, np.ndarray] = {}
        self._grounds: dict[int, GroundTiles] = {}
        self._poses: dict[int, tuple[tuple[float, ...], tuple[float, ...]]] = {}
        #: The mass and the material row each body was given, by service uid.
        self.given: dict[int, tuple[float, int]] = {}
        self._dynamic = _Bits()
        self._reported = _Bits()
        self._report_all = False
        self._persist = False
        self._state_events = False
        self._filter_contacts = False
        # -- movers, for snapshots
        self._movers: list[int] = []
        self._mover_jolt = np.zeros(0, dtype=np.uint32)
        self._mover_dynamic = np.zeros(0, dtype=bool)
        self._movers_dirty = False
        self._rows_full: dict[int, int] = {}
        self._version = 0
        self._published: Snapshot | None = None
        self._published_live = np.zeros(0, dtype=bool)
        self._last_tick = -1
        self._last_applied = -1
        self._published_jolt = 0
        # -- sequences: (service seq, pyjoltphysics seq) not yet applied
        self._pending: collections.deque[tuple[int, int]] = collections.deque()
        self._applied_svc = 0
        self._markers: list[tuple[int, threading.Event]] = []
        # -- world-wide state
        self._shapes: dict[tuple[int, bool], Any] = {}
        self._materials: dict[Any, int] = {}
        self._filters: list[CollisionFilter] = []
        self._zones: list[Any] = []
        self._joints: dict[int, int] = {}
        self._joint_kinds: dict[int, str] = {}
        #: The two bodies of each joint, by service uid; ``to`` is 0 for the world.
        self._joint_bodies: dict[int, tuple[int, int]] = {}
        #: A motor joint's bodies, its axes in the frame of ``to`` and the turn of
        #: ``body`` in that frame when it was made: what its angles are read from.
        self._motors: dict[int, tuple[int, int, np.ndarray, np.ndarray]] = {}
        self._forces: dict[int, np.ndarray] = {}
        self._torques: dict[int, np.ndarray] = {}
        self._posted: list[tuple[Callable[..., Any], tuple[Any, ...]]] = []
        self._posted_lock = threading.Lock()
        self._contact_filter: Callable[[Any], Any] | None = None
        self._contacts = 0
        # -- characters
        self._controllers: dict[int, JoltController] = {}
        self._pass_groups: dict[str, int] = {}
        #: Extra points tiles of a sampled ground are kept around, by name.
        self._foci: dict[str, np.ndarray] = {}
        self._frames = 0
        self._callbacks_set = False
        self._events_set = False
        #: The world thread's identity, once a callback has run on it.
        self.thread_id: int | None = None
        #: Pairs the contact filter let through, for unsolved begin events: (a, b, point,
        #: normal, approach, impulse), pyjoltphysics uids.
        self._refused: list[tuple[int, int, np.ndarray, np.ndarray, float, float]] = []
        self._refused_lock = threading.Lock()
        self._switch_interval: float | None = None
        self._local = threading.local()
        self._error: BaseException | None = None

    # -- uids ---------------------------------------------------------------
    def jolt_uid(self, uid: int) -> int | None:
        """The pyjoltphysics uid of service body ``uid``, or None."""
        return self._jolt.get(uid)

    def service_uid(self, jolt: int) -> int | None:
        """The service uid of pyjoltphysics body ``jolt``, or None."""
        return self._svc.get(jolt)

    def _bind(self, uid: int, jolt: int) -> None:
        self._jolt[uid] = jolt
        self._svc[jolt] = uid

    def _unbind(self, uid: int) -> int | None:
        jolt = self._jolt.pop(uid, None)
        if jolt is not None:
            self._retired.append(jolt)
            while len(self._retired) > RETIRED_KEPT:
                self._svc.pop(self._retired.popleft(), None)
        return jolt

    # -- stepping -------------------------------------------------------------
    @property
    def error(self) -> BaseException | None:
        return self._error if self._error is not None else self.world.error

    @property
    def step_dt(self) -> float:
        return 1.0 / self._tick_hz

    @property
    def max_catch_up(self) -> float:
        return self._max_catch_up

    def on_engine_thread(self) -> bool:
        return bool(getattr(self._local, 'inside', False))

    @property
    def mode(self) -> str:
        return 'inline' if self._lockstep() else 'thread'

    def set_mode(self, mode: str) -> None:
        self._mode = mode

    def pin(self, on: bool) -> None:
        """Hold the world in lockstep with the frame whatever the mode, or let it go."""
        self._pinned = bool(on)

    def _lockstep(self) -> bool:
        return self._pinned or self._mode == 'inline' or bool(self._controllers)

    def live_time(self) -> float:
        snapshot = self.world.latest()
        return 0.0 if snapshot is None else float(snapshot.time)

    def character_steps(self, dt: float) -> tuple[int, float]:  # noqa: ARG002 the ticks ran in collect
        return 0, self.alpha

    def counts(self, published: Snapshot | None) -> WorldCounts:
        """The bodies the world holds now, the waiting adds applied first, and the touching pairs."""
        if not self.on_engine_thread():
            self.world.flush()
        return WorldCounts(int(self.world.stats()['bodies']), self._contacts)

    def info(self) -> EngineInfo:
        options = pj.build_options()
        return EngineInfo('jolt', pj.jolt_version(), self._tick_hz,
                          'double' if options.double_precision else 'single')

    def start(self) -> None:
        if not self._lockstep() and not self._running and self.world.error is None:
            self.world.start()
            self._running = True

    def stop(self) -> bool:
        """Stop a free-running world; a world in lockstep runs no tick it is not asked for.

        From the stepping thread (a handler pausing the game inside a tick) a
        lockstep run in progress finishes its ticks.
        """
        if self._running:
            self.world.stop()
            self._running = False
        return True

    def close(self) -> None:
        if not self.on_engine_thread():
            self.world.stop()
        self._running = False
        self._restore_switch_interval()

    def flush(self) -> None:
        """Apply the commands waiting for the world now, without stepping it.

        From the stepping thread itself it does nothing: that thread's
        commands apply at the next tick.
        """
        if not self.on_engine_thread():
            self.world.flush()

    def _sync(self) -> None:
        """Before a query: apply what is waiting, so the query meets the bodies just added."""
        if self.on_engine_thread():
            return
        latest = self.world.latest()
        submitted = int(self.world.submitted_seq)
        if latest is None or int(latest.applied_seq) < submitted:
            self.world.flush()

    def step(self, dt: float) -> None:
        """Run the ticks ``dt`` owes in lockstep, publishing the result for the next :meth:`collect`."""
        self._run(self._clock.owed(dt))

    def advance(self, dt: float) -> None:
        """Run the ticks ``dt`` owes for a character its owner steps, and read the characters.

        Sampled ground is kept around the characters for those ticks, as a
        frame keeps it.
        """
        ticks = self._clock.owed(dt)
        if not ticks:
            return
        self._stream_ground()
        for _ in range(ticks):
            self._run_ticks(1)
            self._read_characters(self.world.latest())
        self._keep_characters_above_ground()

    def collect(self, dt: float) -> Outbox:
        self._check_failed()
        self._update_callbacks()
        self._stream_ground()
        previous = None
        if self._lockstep():
            if self._running:
                self._running = False
            ticks = self._clock.owed(dt)
            self.owed, self.alpha = ticks, self._clock.alpha
            if not ticks:
                # A frame that owes no tick applies what is waiting, as an inline omi world does.
                if self._posted:
                    self._run_posted()
                self._sync()
            previous = self._run(ticks)
        else:
            self.owed, self.alpha = 0, 1.0
            self.start()
        snapshot = self.world.latest()
        events = self._events()
        self._read_characters(snapshot)
        self._keep_characters_above_ground()
        self._settle_markers(snapshot)
        published = self._publish(snapshot, previous)
        return Outbox(published, events)

    def _run(self, ticks: int) -> Any:
        """Run ``ticks`` ticks in lockstep; the snapshot of the tick before the last, or None."""
        if ticks <= 0:
            return None
        characters = [one for one in self.framed_characters() if one.alive]
        if characters:
            previous = None
            guard = self.guard
            for _ in range(ticks):
                previous = self.world.latest()
                for character in characters:
                    guard(character, character._before_tick, self.step_dt)
                self._run_ticks(1)
                snapshot = self.world.latest()
                self._read_characters(snapshot)
                for character in characters:
                    guard(character, character._after_tick, self.step_dt)
            return previous
        if ticks > 1:
            self._run_ticks(ticks - 1)
        previous = self.world.latest()
        self._run_ticks(1)
        return previous

    def _run_ticks(self, count: int) -> None:
        try:
            self.world.run_ticks(count)
        except pj.WorldError as error:
            self._error = error.__cause__ if error.__cause__ is not None else error
            raise RuntimeError('the physics world stopped: %s' % (self._error,)) from self._error

    def _check_failed(self) -> None:
        error = self.world.error
        if error is not None and self._error is None:
            self._error = error

    # -- callbacks on the world thread ---------------------------------------
    def callbacks_changed(self) -> None:
        if not self.on_engine_thread():
            self._update_callbacks()

    def _update_callbacks(self) -> None:
        """Register the world-thread callbacks while anything needs them, and only then.

        A world with no callback never takes the GIL. While one is registered
        the switch interval is 1 ms, so a world-thread callback waits at most
        that long for a render thread running Python.
        """
        hearing = self.wants_events()
        if hearing != self._events_set:
            self._events_set = hearing
            self.world.set_on_events(self._world_events if hearing else None)
            self._switch_interval_for(hearing or self._callbacks_set)
        wanted = bool(self._forces or self._torques or self._posted
                      or any(want() for want in self.wants_steps))
        if wanted == self._callbacks_set:
            return
        self._callbacks_set = wanted
        if wanted:
            self.world.set_before_step(self._before)
            self.world.set_after_step(self._after)
        else:
            self.world.set_before_step(None)
            self.world.set_after_step(None)
        self._switch_interval_for(wanted or self._events_set)

    def _switch_interval_for(self, callbacks: bool) -> None:
        """A 1 ms switch interval while a world-thread callback is registered, the one before otherwise."""
        if callbacks and self._switch_interval is None:
            self._switch_interval = sys.getswitchinterval()
            sys.setswitchinterval(min(self._switch_interval, 0.001))
        elif not callbacks:
            self._restore_switch_interval()

    def _world_events(self, records: Any, tick: int, time: float) -> None:  # noqa: ARG002 the records carry their ticks
        """On the world thread after a tick that made records: the physics-thread handlers hear them."""
        self.thread_id = threading.get_ident()
        made = self._converted(records)
        if made:
            self._tell(made)

    def _restore_switch_interval(self) -> None:
        if self._switch_interval is not None:
            sys.setswitchinterval(self._switch_interval)
            self._switch_interval = None

    def _before(self, tick: int, time: float) -> None:
        self._local.inside = True
        try:
            self._run_posted()
            if self._forces or self._torques:
                self._push_forces()
            step = Step(self.step_dt, int(tick), float(time))
            for hook in list(self.before_step):
                try:
                    hook(step)
                except Exception:
                    log.exception('physics hook %r failed', hook)
        finally:
            self._local.inside = False

    def _after(self, tick: int, time: float) -> None:
        self._local.inside = True
        try:
            step = Step(self.step_dt, int(tick) - 1, float(time) - self.step_dt)
            for hook in list(self.after_step):
                try:
                    hook(step)
                except Exception:
                    log.exception('physics hook %r failed', hook)
        finally:
            self._local.inside = False

    def _run_posted(self) -> None:
        """Call the functions :meth:`Physics.post` queued, in order, as the stepping thread."""
        with self._posted_lock:
            posted, self._posted = self._posted, []
        was = getattr(self._local, 'inside', False)
        self._local.inside = True
        try:
            for function, arguments in posted:
                try:
                    function(*arguments)
                except Exception:
                    log.exception('physics post %r failed', function)
        finally:
            self._local.inside = was

    def _push_forces(self) -> None:
        """Give each body its standing force and torque for the next tick."""
        for table, send in ((self._forces, self.world.add_forces),
                            (self._torques, self.world.add_torques)):
            if not table:
                continue
            uids, values = [], []
            for uid, value in table.items():
                jolt = self._jolt.get(uid)
                if jolt is not None:
                    uids.append(jolt)
                    values.append(value)
            if uids:
                send(np.asarray(uids, dtype=np.uint32), np.asarray(values, dtype='d'))

    # -- publishing -----------------------------------------------------------
    def _mover_table(self) -> None:
        if not self._movers_dirty:
            return
        self._movers_dirty = False
        self._movers = [uid for uid in self._movers if uid in self._jolt]
        self._mover_jolt = np.array([self._jolt[uid] for uid in self._movers], dtype=np.uint32)
        self._mover_dynamic = np.array([self._kinds[uid] == 'dynamic' for uid in self._movers],
                                       dtype=bool)
        self._rows_full = {uid: row for row, uid in enumerate(self._movers)}
        self._published = None

    def _note_applied(self, applied_jolt: int) -> None:
        pending = self._pending
        while pending and pending[0][1] <= applied_jolt:
            seq, _jolt = pending.popleft()
            if seq > self._applied_svc:
                self._applied_svc = seq

    def _publish(self, snapshot: Any, previous: Any) -> Snapshot | None:
        """The service's snapshot of the movers from ``snapshot``, or None when nothing is new."""
        if snapshot is None:
            return None
        self._note_applied(int(snapshot.applied_seq))
        self._mover_table()
        tick, applied = int(snapshot.tick), self._applied_svc
        if (tick == self._last_tick and applied == self._last_applied
                and self._published is not None and previous is None):
            return None
        self._last_tick, self._last_applied = tick, applied
        rows = snapshot.rows_of(self._mover_jolt)
        present = rows >= 0
        if present.all():
            take, table, dynamic = rows, self._rows_full, self._mover_dynamic
        else:
            keep = np.flatnonzero(present)
            take = rows[keep]
            table = {self._movers[index]: row for row, index in enumerate(keep.tolist())}
            dynamic = self._mover_dynamic[keep]
        position = np.array(snapshot.position[take], dtype='d')
        orientation = np.array(snapshot.orientation[take], dtype='d')
        linear = np.array(snapshot.linear_velocity[take], dtype='d')
        angular = np.array(snapshot.angular_velocity[take], dtype='d')
        awake = np.array(snapshot.awake[take], dtype=bool)
        live = np.where(dynamic, awake, linear.any(axis=1) | angular.any(axis=1))
        step_position = step_orientation = None
        alpha = self.alpha
        if self.owed and alpha < 1.0 and live.any():
            if present.all():
                uids, jolt = self._movers, self._mover_jolt
            else:
                kept = np.flatnonzero(present)
                uids, jolt = [self._movers[i] for i in kept.tolist()], self._mover_jolt[kept]
            moving = np.flatnonzero(live)
            old_position, old_orientation = self._previous_poses(previous, jolt, uids, moving)
            if len(moving):
                step_position, step_orientation = position.copy(), orientation.copy()
                position[moving] = old_position * (1.0 - alpha) + position[moving] * alpha
                blend = old_orientation * (1.0 - alpha) + orientation[moving] * alpha
                orientation[moving] = blend / np.maximum(
                    np.linalg.norm(blend, axis=1), 1e-12)[:, None]
        last = self._published
        changed = None
        base = -1
        if last is not None and last.rows is table:
            differs = (live | self._published_live
                       | (position != last.position).any(axis=1)
                       | (orientation != last.orientation).any(axis=1)
                       | (awake != last.awake))
            changed = np.flatnonzero(differs)
            base = last.version
        self._version += 1
        published = Snapshot(self._version, tick, float(snapshot.time), applied, table, position,
                             axis_angles(orientation), orientation, linear, angular, awake,
                             dynamic, changed, base, step_position, step_orientation,
                             self._joint_readings(snapshot), int(snapshot.count), self._contacts)
        self._published = published
        self._published_live = live
        return published

    def _previous_poses(self, previous: Any, jolt: np.ndarray, uids: Sequence[int],
                        moving: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """The poses of the rows ``moving`` at the tick before the last: from ``previous``, or as
        added for a body that snapshot does not hold. ``jolt`` and ``uids`` name each row."""
        position = np.empty((len(moving), 3))
        orientation = np.empty((len(moving), 4))
        found = np.zeros(len(moving), dtype=bool)
        if previous is not None:
            rows = previous.rows_of(jolt[moving])
            found = rows >= 0
            take = rows[found]
            position[found] = previous.position[take]
            orientation[found] = previous.orientation[take]
        for out in np.flatnonzero(~found).tolist():
            placed = self._poses.get(uids[int(moving[out])],
                                     ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
            position[out], orientation[out] = placed
        return position, orientation

    def _joint_readings(self, snapshot: Any) -> dict[int, tuple[float, ...]]:
        if not self._joints:
            return {}
        joints = snapshot.joints
        rows = joints.rows
        found: dict[int, tuple[float, ...]] = {}
        for uid, jid in self._joints.items():
            row = rows.get(jid)
            if row is None:
                continue
            kind = self._joint_kinds[uid]
            value, value2 = float(joints.value[row]), float(joints.value2[row])
            if kind in ('hinge', 'slider'):
                found[uid] = (value,)
            elif kind == 'wheel':
                found[uid] = (value, value2)
        for uid, (body, to, axes, start) in self._motors.items():
            turned = self._turn_in(snapshot, body, to)
            if turned is not None:
                delta = _multiply(turned, _conjugate(start))
                found[uid] = tuple(float(2.0 * math.atan2(np.dot(delta[:3], axis), delta[3]))
                                   for axis in axes)
        return found

    def _turn_in(self, snapshot: Any, body: int, to: int) -> np.ndarray | None:
        """The turn of service body ``body`` in the frame of ``to`` (0 for the world), from ``snapshot``."""
        rows = snapshot.rows
        jolt = self._jolt.get(body)
        row = None if jolt is None else rows.get(jolt)
        if row is None:
            return None
        turn = np.asarray(snapshot.orientation[row], dtype='d')
        if to == 0:
            return turn
        other = self._jolt.get(to)
        frame_row = None if other is None else rows.get(other)
        if frame_row is None:
            return None
        return _multiply(_conjugate(np.asarray(snapshot.orientation[frame_row], dtype='d')), turn)

    def _settle_markers(self, snapshot: Any) -> None:
        if not self._markers or snapshot is None:
            return
        waiting = []
        for seq, marker in self._markers:
            if snapshot.includes(seq):
                marker.set()
            else:
                waiting.append((seq, marker))
        self._markers = waiting

    # -- events ---------------------------------------------------------------
    def _events(self) -> list[PhysicsEvent]:
        records = self.world.drain_events()
        if len(records):
            kind = records['kind']
            contact = kind == pj.EventKind.CONTACT
            phase = records['phase']
            begins = int(np.count_nonzero(contact & (phase == pj.EventPhase.BEGIN)))
            ends = int(np.count_nonzero(contact & (phase == pj.EventPhase.END)))
            self._contacts = max(0, self._contacts + begins - ends)
        made = self._converted(records) + self._unsolved()
        if made and self.on_events and not self._events_set:
            self._tell(made)
        return made

    def _tell(self, made: list[PhysicsEvent]) -> None:
        """Give ``made`` to the physics-thread listeners, as the stepping thread."""
        was = getattr(self._local, 'inside', False)
        self._local.inside = True
        try:
            for listener in list(self.on_events):
                try:
                    listener(made)
                except Exception:
                    log.exception('physics hook %r failed', listener)
        finally:
            self._local.inside = was

    def _unsolved(self) -> list[PhysicsEvent]:
        """A begin event, unsolved, for each pair the contact filter let through since the last call."""
        with self._refused_lock:
            refused, self._refused = self._refused, []
        made = []
        tick = int(self.world.tick)
        for a, b, point, normal, approach, impulse in refused:
            first, second = self._svc.get(a), self._svc.get(b)
            if first is None or second is None:
                continue
            made.append(PhysicsEvent('contact', 'begin', first, second, point, normal, approach,
                                     impulse, 0.0, 0.0, 0.0, tick, tick * self.step_dt,
                                     solved=False))
        return made

    def _converted(self, records: Any) -> list[PhysicsEvent]:
        """The service's events of the event ``records`` it listens for."""
        if not len(records):
            return []
        kind = records['kind']
        phase = records['phase']
        contact = kind == pj.EventKind.CONTACT
        if self._report_all:
            wanted = contact.copy()
        else:
            wanted = contact & (self._reported.of(records['a']) | self._reported.of(records['b']))
        if not self._persist:
            wanted &= phase != pj.EventPhase.PERSIST
        wanted |= kind == pj.EventKind.TRIGGER
        if self._state_events:
            wanted |= kind == pj.EventKind.STATE
        wanted |= (kind == pj.EventKind.CHARACTER) & (
            (phase == pj.EventPhase.BEGIN) | (phase == pj.EventPhase.END))
        made: list[PhysicsEvent] = []
        dt = self.step_dt
        for record in records[wanted]:
            converted = self._convert(record, dt)
            if converted is not None:
                made.append(converted)
        return made

    def _convert(self, record: Any, dt: float) -> PhysicsEvent | None:
        kind = int(record['kind'])
        a = self._svc.get(int(record['a']))
        tick = int(record['tick'])
        time = tick * dt
        reason = 'removed' if int(record['reason']) == int(pj.EndReason.REMOVED) else None
        phase = int(record['phase'])
        if kind == pj.EventKind.STATE:
            if a is None:
                return None
            name = 'sleep' if phase == pj.EventPhase.SLEEP else 'wake'
            return PhysicsEvent('state', name, a, None, np.array(record['point'], dtype='d'),
                                _ZERO3, 0.0, 0.0, 0.0, 0.0, 0.0, tick, time)
        b = self._svc.get(int(record['b']))
        if a is None or b is None:
            return None
        point = np.array(record['point'], dtype='d')
        normal = np.array(record['normal'], dtype='d')
        if kind == pj.EventKind.TRIGGER:
            return PhysicsEvent('trigger', _TRIGGER_PHASE[pj.EventPhase(phase)], a, b, point, _ZERO3,
                                0.0, 0.0, 0.0, 0.0, 0.0, tick, time, reason=reason)
        if kind == pj.EventKind.CHARACTER:
            # The service's characters meet moving bodies as a kinematic body meets them.
            if self._kinds.get(b) != 'dynamic':
                return None
            impulse = self._strike(int(record['b']), normal) if phase == pj.EventPhase.BEGIN else 0.0
            return PhysicsEvent('contact', _PHASE[pj.EventPhase(phase)], a, b, point, normal,
                                float(record['approach']), impulse, 0.0, 0.0, 0.0, tick, time,
                                reason=reason)
        return PhysicsEvent('contact', _PHASE[pj.EventPhase(phase)], a, b, point, normal,
                            float(record['approach']), float(record['impulse']), 0.0, 0.0,
                            float(record['depth']), tick, time, reason=reason)

    def _strike(self, jolt: int, normal: np.ndarray) -> float:
        """The momentum a dynamic body brings onto a character, along ``normal`` (character to body).

        A body the character walks into brings none; one moving toward the
        character brings its mass times that speed.
        """
        uid = self._svc.get(jolt)
        if uid is None or self._kinds.get(uid) != 'dynamic':
            return 0.0
        snapshot = self.world.latest()
        row = None if snapshot is None else snapshot.rows.get(jolt)
        if row is None:
            return 0.0
        closing = -float(np.dot(np.asarray(snapshot.linear_velocity[row], dtype='d'), normal))
        body = self.body_of(uid)
        mass = float(getattr(body, 'mass', 0.0) or 0.0)
        return mass * closing if closing > 0.5 else 0.0

    # -- characters -----------------------------------------------------------
    def _read_characters(self, snapshot: Any) -> None:
        if not self._controllers or snapshot is None:
            return
        rows = snapshot.characters
        table = rows.rows
        tick, applied = int(snapshot.tick), int(snapshot.applied_seq)
        for controller in self._controllers.values():
            row = table.get(controller.native.id)
            if row is not None:
                controller.read(rows, row, tick, applied)

    def make_character(self, physics: Any, centre: np.ndarray, capabilities: Any,
                       gravity: float) -> tuple[Any, Any]:
        from OpenGLContext.physics.character import stand_in_proxy  # noqa: PLC0415 imports the service's types

        caps = _capabilities(capabilities)
        centre = self._above_ground(np.asarray(centre, dtype='d'), float(capabilities.standHeight))
        self._stream_ground(extra=centre[None])
        native = self.world.add_character(tuple(float(v) for v in centre), caps, gravity=gravity)
        # Seated in the tick that adds it, so a character made standing on the ground is
        # grounded from its first tick, as the omi controller is from its first step.
        seated = native.teleport(tuple(float(v) for v in centre), SEAT_SEARCH)
        body = physics._register_body('kinematic', stand_in_proxy(capabilities, 0.0), centre)
        self._bind(body.uid, native.id)
        self._kinds[body.uid] = 'character'
        controller = JoltController(self, native, capabilities, centre, gravity)
        half = float(capabilities.standHeight) / 2.0
        floor = self.floor_under(np.asarray(centre, dtype='d'), half, native.id, below=SEAT_SEARCH)
        if floor is not None and abs(float(centre[1]) - half - floor) <= SEAT_SEARCH:
            controller.grounded = True
            controller._expect(pj.CharacterState.STANDING, seated)
        self._controllers[body.uid] = controller
        return body, controller

    def _ground_under(self, x: float, z: float) -> float | None:
        """The highest sampled ground at ``(x, z)``, or None with no sampled ground there."""
        found = None
        for ground in self._grounds.values():
            if ground.extent is not None:
                (x0, z0), (x1, z1) = ground.extent
                if not (x0 <= x <= x1 and z0 <= z <= z1):
                    continue
            height = float(np.asarray(ground.sample(np.array([x]), np.array([z])) if ground.vectorized
                                      else ground.sample(x, z)).reshape(-1)[0])
            found = height if found is None else max(found, height)
        return found

    def _above_ground(self, centre: np.ndarray, height: float) -> np.ndarray:
        """``centre`` of a capsule ``height`` tall, raised where its feet are below a sampled ground.

        Everything below a sampled ground is solid, as the omi engine holds it;
        a height field tile collides from above only.
        """
        ground = self._ground_under(float(centre[0]), float(centre[2]))
        if ground is not None and centre[1] - height / 2.0 < ground:
            centre = centre.copy()
            centre[1] = ground + height / 2.0
        return centre

    def _keep_characters_above_ground(self) -> None:
        """Lift each character whose feet are below a sampled ground back onto it."""
        if not self._grounds:
            return
        for controller in self._controllers.values():
            ground = self._ground_under(float(controller.position[0]), float(controller.position[2]))
            feet = float(controller.position[1]) - controller.height / 2.0
            if ground is not None and feet < ground - 0.05 and controller._placed is None:
                controller.place((controller.position[0], ground + controller.height / 2.0,
                                  controller.position[2]))

    def floor_under(self, centre: np.ndarray, half: float, own: int,
                    below: float = 0.0) -> float | None:
        """The top of what is under a capsule's axis at ``centre``, from its top to ``below`` metres
        under its feet; None for nothing.

        Read with a ray down from the capsule's top, passing over character
        ``own``, the characters' capsules and triggers.
        """
        start = np.array([centre[0], centre[1] + half, centre[2]], dtype='d')
        reach = 2.0 * half + max(float(below), 0.0)
        self._ground_for_query(start, start - np.array([0.0, reach, 0.0]))
        self._sync()
        hit = self.world.raycast(start, (0.0, -1.0, 0.0), reach,
                                 filter=pj.QueryFilter(exclude=[own], characters=False))
        return None if hit is None else float(hit.point[1])

    def pass_group_id(self, name: str | None) -> int:
        """The native pass group of the characters given the name ``name``; 0 for none."""
        if name is None:
            return 0
        return self._pass_groups.setdefault(name, len(self._pass_groups) + 1)

    def ground_material(self, controller: JoltController) -> str | None:
        """The name of the material under a character, where its ground has one."""
        uid = self._svc.get(controller.ground_uid)
        if uid is None or False:
            return None
        body = self.body_of(uid)
        return None if body is None else getattr(body, 'material', None)

    # -- ground tiles ---------------------------------------------------------
    def add_focus(self, name: str, position: Any) -> None:
        """Keep sampled ground around ``position`` as well, under ``name``; None forgets it."""
        if position is None:
            self._foci.pop(name, None)
        else:
            self._foci[name] = np.asarray(position, dtype='d')[:3]

    def _foci_now(self, extra: np.ndarray | None) -> np.ndarray:
        points = [controller.position for controller in self._controllers.values()]
        points.extend(self._foci.values())
        snapshot = self._published
        if snapshot is not None and len(snapshot.position):
            moving = snapshot.dynamic & snapshot.awake
            if moving.any():
                points.extend(snapshot.position[moving])
        if extra is not None:
            points.extend(extra)
        return np.asarray(points, dtype='d').reshape(-1, 3)

    def _stream_ground(self, extra: np.ndarray | None = None) -> None:
        if not self._grounds:
            return
        foci = self._foci_now(extra)
        self._frames += 1
        for ground in self._grounds.values():
            ground.asked = {tile: until for tile, until in ground.asked.items()
                            if until >= self._frames}
            wanted = ground.wanted(foci) | set(ground.asked)
            gone = [tile for tile in ground.tiles if tile not in wanted]
            new = [tile for tile in sorted(wanted) if tile not in ground.tiles]
            if not gone and not new:
                continue
            removed = [ground.tiles.pop(tile) for tile in gone]
            for jolt in removed:
                self._svc.pop(jolt, None)
            flags = self._flags('static')
            if new:
                batch = _concat([ground.batch(tile, flags) for tile in new])
                uids, seq = self.world.swap_bodies(np.asarray(removed, dtype=np.uint32), batch)
                for tile, jolt in zip(new, uids.tolist(), strict=True):
                    ground.tiles[tile] = int(jolt)
                    self._svc[int(jolt)] = ground.uid
                self._reported.set(uids, ground.reported)
            else:
                self.world.remove_bodies(np.asarray(removed, dtype=np.uint32))

    #: Frames a tile a query asked for is kept.
    ASKED_FRAMES = 120

    def _ground_for_query(self, start: Any, end: Any) -> None:
        """Hold the tiles of each sampled ground under a query's path, so the query meets the ground."""
        if not self._grounds:
            return
        first = np.asarray(start, dtype='d')[:3]
        last = np.asarray(end, dtype='d')[:3]
        added = False
        for ground in self._grounds.values():
            for tile in ground.along(first, last):
                if tile not in ground.tiles:
                    added = True
                ground.asked[tile] = self._frames + self.ASKED_FRAMES
        if added:
            self._stream_ground()

    # -- commands ---------------------------------------------------------------
    def submit(self, command: Command) -> None:
        operation = getattr(self, '_op_' + command.op, None)
        if operation is None:
            log.warning('unknown physics command %r', command.op)
            return
        if command.uid and command.op not in ('add',) and command.uid not in self._jolt \
                and command.uid not in self._grounds and command.uid not in self._batches:
            self._done(command.seq)
            return
        try:
            operation(command.uid, *command.args)
        except Exception:
            log.exception('physics command %s for body %s failed', command.op, command.uid)
        self._done(command.seq)

    def _done(self, seq: int) -> None:
        """Count service command ``seq`` applied once every batch submitted so far is."""
        if seq:
            self._pending.append((seq, int(self.world.submitted_seq)))

    def _flags(self, kind: str, extent: float = 1.0, report: bool = False) -> int:
        flags = pj.BodyFlag.NONE
        if kind == 'trigger':
            flags |= pj.BodyFlag.SENSOR
        if kind == 'dynamic' and extent < CCD_BELOW:
            flags |= pj.BodyFlag.CONTINUOUS
        if kind == 'dynamic':
            # A dynamic body rolls across the seam between static bodies laid
            # flush as across one surface, as it does on omi_physics.
            flags |= pj.BodyFlag.SMOOTH_EDGES
        if report and self._persist:
            flags |= pj.BodyFlag.REPORT
        if self._filter_contacts and (report or self._report_all):
            flags |= pj.BodyFlag.FILTER_CONTACTS
        return int(flags)

    def _material_index(self, material: Any) -> int:
        """The world's material row for a name, a Material or None."""
        if isinstance(material, str):
            key: Any = ('name', material)
            found = self._materials.get(key)
            if found is not None:
                return found
            resolved = self.material_of(material) if self.material_of is not None else Material()
            index = self._define(resolved)
            self._materials[key] = index
            return index
        made = Material.coerce(material)
        key = ('values', made.staticFriction, made.dynamicFriction, made.restitution,
               made.frictionCombine, made.restitutionCombine)
        found = self._materials.get(key)
        if found is None:
            found = self._materials[key] = self._define(made)
        return found

    def _define(self, material: Material) -> int:
        return self.world.materials.define(
            static_friction=float(material.staticFriction),
            dynamic_friction=float(material.dynamicFriction),
            restitution=float(material.restitution),
            friction_combine=_COMBINE.get(str(material.frictionCombine), pj.Combine.AVERAGE),
            restitution_combine=_COMBINE.get(str(material.restitutionCombine), pj.Combine.AVERAGE))

    def _shape(self, proxy: Proxy, moving: bool) -> Any:
        """The pyjoltphysics shape id of ``proxy``, built once a proxy."""
        key = (proxy.uid, moving)
        found = self._shapes.get(key)
        if found is None:
            found = self._shapes[key] = self.world.add_shape(_shape_of(proxy, moving))
        return found

    def _add_bodies(self, uids: Sequence[int], batch: pj.BodyBatch) -> np.ndarray:
        made, _seq = self.world.add_bodies(batch)
        for uid, jolt in zip(uids, made.tolist(), strict=True):
            self._bind(uid, int(jolt))
        return made

    def _op_add(self, uid: int, spec: BodySpec) -> None:
        proxy = spec.proxy
        kind = spec.kind
        material = self._material_index(spec.material)
        filter_index = NO_FILTER if spec.collision_filter < 0 else int(spec.collision_filter)
        self._kinds[uid] = kind
        if proxy.kind == 'heightfield' and proxy.params.get('sample') is not None:
            ground = GroundTiles(uid, proxy, material, filter_index)
            self._grounds[uid] = ground
            self._report(uid, spec.report)
            self._stream_ground()
            return
        moving = kind in ('dynamic', 'kinematic')
        shape = self._shape(proxy, kind == 'dynamic')
        motion = {'static': pj.MotionType.STATIC, 'trigger': pj.MotionType.STATIC,
                  'kinematic': pj.MotionType.KINEMATIC,
                  'dynamic': pj.MotionType.DYNAMIC}[kind]
        info = self.world.shape_info(shape)
        extent = float(np.min(np.asarray(info.bounds_max) - np.asarray(info.bounds_min)))
        given = spec.motion
        values: dict[str, Any] = {
            'motion': motion, 'orientations': np.asarray(spec.orientation, dtype='d')[None],
            'material': material, 'filter': filter_index,
            'flags': self._flags(kind, extent, spec.report),
        }
        if moving:
            values.update(mass=float(given.mass) if kind == 'dynamic' else 1.0,
                          linear_damping=float(given.linear_damping),
                          angular_damping=float(given.angular_damping),
                          gravity_factor=float(given.gravity_factor))
        batch = pj.BodyBatch.of_shape(np.asarray(spec.position, dtype='d')[None], shape, **values)
        made = self._add_bodies([uid], batch)
        self.given[uid] = (float(given.mass) if kind == 'dynamic' else 0.0, material)
        if kind == 'dynamic':
            self._dynamic.set(made)
        self._report(uid, spec.report)
        self._poses[uid] = (tuple(spec.position), tuple(spec.orientation))
        if moving:
            self._movers.append(uid)
            self._movers_dirty = True

    def _op_add_many(self, uid: int, batch: BodyBatch) -> None:  # noqa: ARG002 named by the batch
        shape = self._shape(batch.proxy, False)
        filter_index = NO_FILTER if batch.collision_filter < 0 else int(batch.collision_filter)
        made, _seq = self.world.add_bodies(pj.BodyBatch.of_shape(
            np.asarray(batch.positions, dtype='d'), shape, motion=pj.MotionType.STATIC,
            material=self._material_index(batch.material), filter=filter_index))
        self._batches[batch.first] = made
        for offset, jolt in enumerate(made.tolist()):
            self._svc[int(jolt)] = batch.first + offset
            self._kinds[batch.first + offset] = 'static'

    def _op_remove_many(self, uid: int, first: int, count: int) -> None:  # noqa: ARG002 named by the range
        made = self._batches.pop(first, None)
        if made is not None:
            self.world.remove_bodies(made)
            for jolt in made.tolist():
                self._retired.append(int(jolt))

    def _op_remove(self, uid: int) -> None:
        ground = self._grounds.pop(uid, None)
        if ground is not None:
            tiles = list(ground.tiles.values())
            if tiles:
                self.world.remove_bodies(np.asarray(tiles, dtype=np.uint32))
            return
        controller = self._controllers.pop(uid, None)
        self.given.pop(uid, None)
        for joint in [joint for joint, pair in self._joint_bodies.items() if uid in pair]:
            self._forget_joint(joint)
        jolt = self._unbind(uid)
        self._forces.pop(uid, None)
        self._torques.pop(uid, None)
        if jolt is None:
            return
        if controller is not None:
            self.world.remove_characters([jolt])
        else:
            self.world.remove_bodies([jolt])
        if uid in self._kinds and self._kinds[uid] in ('dynamic', 'kinematic'):
            self._movers_dirty = True

    def _current_pose(self, uid: int) -> tuple[np.ndarray, np.ndarray]:
        jolt = self._jolt[uid]
        snapshot = self.world.latest()
        row = None if snapshot is None else snapshot.rows.get(jolt)
        if row is None:
            position, orientation = self._poses.get(uid, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0)))
            return np.asarray(position, dtype='d'), np.asarray(orientation, dtype='d')
        return (np.array(snapshot.position[row], dtype='d'),
                np.array(snapshot.orientation[row], dtype='d'))

    def _op_impulse(self, uid: int, impulse: Any, at: Any) -> None:
        jolt = self._jolt[uid]
        push = np.asarray(impulse, dtype='d')
        self.world.add_impulses([jolt], push)
        if at is not None:
            arm = np.asarray(at, dtype='d') - self._current_pose(uid)[0]
            self.world.add_torques([jolt], np.cross(arm, push) / self.step_dt)

    def _op_torque_impulse(self, uid: int, impulse: Any) -> None:
        self.world.add_torques([self._jolt[uid]], np.asarray(impulse, dtype='d') / self.step_dt)

    def _op_force(self, uid: int, force: Any) -> None:
        value = np.asarray(force, dtype='d')
        if value.any():
            self._forces[uid] = value
            self.world.add_forces([self._jolt[uid]], value)
        else:
            self._forces.pop(uid, None)
        self.callbacks_changed()

    def _op_torque(self, uid: int, torque: Any) -> None:
        value = np.asarray(torque, dtype='d')
        if value.any():
            self._torques[uid] = value
            self.world.add_torques([self._jolt[uid]], value)
        else:
            self._torques.pop(uid, None)
        self.callbacks_changed()

    def _op_velocity(self, uid: int, velocity: Any) -> None:
        self.world.set_velocities([self._jolt[uid]], linear=np.asarray(velocity, dtype='d'))

    def _op_angular_velocity(self, uid: int, velocity: Any) -> None:
        self.world.set_velocities([self._jolt[uid]], angular=np.asarray(velocity, dtype='d'))

    def _op_place(self, uid: int, translation: Any, axis_angle: Any) -> None:
        position, orientation = self._current_pose(uid)
        if translation is not None:
            position = np.asarray(translation, dtype='d')[:3]
        if axis_angle is not None:
            orientation = vrml_rotation_to_quat(np.asarray(axis_angle, dtype='d'))
        self._poses[uid] = (tuple(position.tolist()), tuple(orientation.tolist()))
        self.world.set_transforms([self._jolt[uid]], position[None], orientation[None])

    def _op_gravity(self, uid: int, vector: Any) -> None:  # noqa: ARG002 gravity belongs to the world
        self.world.set_gravity(tuple(float(v) for v in vector))

    def _op_gravity_factor(self, uid: int, factor: float) -> None:
        self.world.set_motion([self._jolt[uid]], gravity_factor=float(factor))

    def _op_damping(self, uid: int, linear: float | None, angular: float | None) -> None:
        self.world.set_motion([self._jolt[uid]], linear_damping=linear, angular_damping=angular)

    def _op_mass(self, uid: int, mass: float) -> None:
        self.world.set_motion([self._jolt[uid]], mass=float(mass))
        self.given[uid] = (float(mass), self.given.get(uid, (0.0, 0))[1])

    def _op_body_material(self, uid: int, material: Any) -> None:
        index = self._material_index(material)
        self.world.set_body_materials([self._jolt[uid]], index)
        self.given[uid] = (self.given.get(uid, (0.0, 0))[0], index)
        self.world.activate([self._jolt[uid]])

    def _op_wake(self, uid: int) -> None:
        self.world.activate([self._jolt[uid]])

    def _op_config(self, uid: int, tick_hz: float, max_catch_up: float) -> None:  # noqa: ARG002 world-wide
        if abs(float(tick_hz) - self._tick_hz) > 1e-9:
            log.warning('a Jolt world steps at the rate it was made with (%g Hz), not %g Hz',
                        self._tick_hz, tick_hz)
        self._max_catch_up = float(max_catch_up)
        self._clock.longest = self._max_catch_up

    def _op_drop_remainder(self, uid: int) -> None:  # noqa: ARG002 world-wide
        self._clock.drop()

    def _op_logging(self, uid: int, on: bool) -> None:
        """Nothing: a Jolt world always reports begin and end records."""

    def _op_backend(self, uid: int, name: str) -> None:
        """Nothing: Jolt has no compute backends to choose."""

    def _op_standin(self, uid: int, body: int, push_mass: float) -> None:
        """Nothing: a Jolt character pushes by its own mass and push limits."""

    def _op_noop(self, uid: int) -> None:
        """Nothing; a command whose arrival changes nothing."""

    def _op_joint_watch(self, uid: int, joint: int) -> None:
        """Nothing: every joint's readings are in every snapshot."""

    def _op_run(self, uid: int, function: Callable[[Any], Any],  # noqa: ARG002 world-wide
                future: Any) -> None:
        if future.set_running_or_notify_cancel():
            future.set_exception(RuntimeError(
                'Physics.run hands over an omi_physics world; the Jolt engine has none. '
                'Use physics.on_step, physics.poses and the add_* joint calls'))

    def _op_post(self, uid: int, function: Callable[..., Any],  # noqa: ARG002 world-wide
                 arguments: tuple[Any, ...]) -> None:
        if self.on_engine_thread():
            function(*arguments)
            return
        with self._posted_lock:
            self._posted.append((function, arguments))
        self._update_callbacks()

    def _op_settle(self, uid: int, marker: threading.Event) -> None:
        self._markers.append((int(self.world.submitted_seq), marker))

    def _op_report(self, uid: int, on: bool) -> None:
        self._report(uid, bool(on))

    def _report(self, uid: int, on: bool) -> None:
        jolt = self._jolt.get(uid)
        if jolt is None:
            ground = self._grounds.get(uid)
            if ground is not None:
                ground.reported = on
                if ground.tiles:
                    self._reported.set(list(ground.tiles.values()), on)
            return
        self._reported.set([jolt], on)
        if self._persist:
            self.world.set_flags([jolt], pj.BodyFlag.REPORT, on)
        if self._filter_contacts:
            self.world.set_flags([jolt], pj.BodyFlag.FILTER_CONTACTS, on)

    def _op_report_all(self, uid: int, on: bool) -> None:  # noqa: ARG002 world-wide
        self._report_all = bool(on)
        if on and self._filter_contacts and self._jolt:
            self.world.set_flags(list(self._jolt.values()), pj.BodyFlag.FILTER_CONTACTS, True)

    def _op_persist(self, uid: int, on: bool) -> None:  # noqa: ARG002 world-wide
        self._persist = bool(on)
        if self._report_all:
            targets = [jolt for svc, jolt in self._jolt.items()
                       if self._kinds.get(svc) in ('dynamic', 'kinematic')]
        else:
            targets = [jolt for jolt in self._jolt.values() if self._reported.of([jolt])[0]]
        if targets:
            self.world.set_flags(targets, pj.BodyFlag.REPORT, self._persist)

    def _op_state_events(self, uid: int, on: bool) -> None:  # noqa: ARG002 world-wide
        self._state_events = bool(on)

    def _op_filter(self, uid: int, index: int, given: Any) -> None:  # noqa: ARG002 filters are the world's
        made = CollisionFilter.coerce(given)
        while len(self._filters) <= index:
            self._filters.append(CollisionFilter())
        self._filters[index] = made
        count = len(self._filters)
        table = np.array([[self._filters[i].collides_with(self._filters[j]) for j in range(count)]
                          for i in range(count)], dtype=bool)
        self.world.set_filter_table(table)

    def _op_material(self, uid: int, name: str, material: Any) -> None:  # noqa: ARG002 world-wide
        self._materials[('name', name)] = self._define(Material.coerce(material))

    def _op_pair_friction(self, uid: int, first: str, second: str,  # noqa: ARG002 world-wide
                          static: float, dynamic: float) -> None:
        self.world.materials.pair(self._material_index(first), self._material_index(second),
                                  static_friction=float(static), dynamic_friction=float(dynamic))

    def _op_gravity_zone(self, uid: int, zone: Any) -> None:  # noqa: ARG002 world-wide
        self._zones.append(zone)
        self._send_zones()

    def _op_gravity_zones(self, uid: int, kind: type, zones: list[Any]) -> None:  # noqa: ARG002 world-wide
        self._zones = [zone for zone in self._zones if not isinstance(zone.region, kind)] + list(zones)
        self._send_zones()

    def _send_zones(self) -> None:
        made = [found for found in (_zone_of(zone) for zone in self._zones) if found is not None]
        self.world.set_gravity_zones(made)

    def _op_drive(self, uid: int, function: Callable[[float], Any] | None) -> None:
        jolt = self._jolt[uid]
        if function is None:
            self.world.drive(jolt, None)
            return

        def pose(time: float) -> Any:
            self._local.inside = True
            try:
                translation, rotation = function(time)
            finally:
                self._local.inside = False
            position = tuple(float(v) for v in translation)
            if rotation is None:
                return position, tuple(float(v) for v in self._current_pose(uid)[1])
            return position, tuple(float(v) for v in vrml_rotation_to_quat(rotation))

        self.world.drive(jolt, pose)

    # -- joints -----------------------------------------------------------------
    def _op_joint(self, uid: int, joint: int, spec: Any) -> None:
        body = self._jolt[uid]
        to = 0 if spec.to == 0 else self._jolt.get(spec.to)
        if to is None:
            return
        if spec.kind == 'distance':
            anchor = spec.anchor if spec.anchor is not None else tuple(self._current_pose(uid)[0])
            to_anchor = spec.to_anchor
            if to_anchor is None:
                to_anchor = anchor if spec.to == 0 else tuple(self._current_pose(spec.to)[0])
            spec = dataclasses.replace(spec, anchor=anchor, to_anchor=to_anchor)
        made = _joint_of(spec, body, to, self._body_mass(uid))
        jid = self.world.add_joint(made)
        self._joints[joint] = int(jid)
        self._joint_kinds[joint] = spec.kind
        self._joint_bodies[joint] = (uid, int(spec.to))
        if spec.kind == 'motor':
            frame = (np.array([0.0, 0.0, 0.0, 1.0]) if spec.to == 0
                     else self._current_pose(spec.to)[1])
            axes = np.array([_rotate(_conjugate(frame), np.asarray(axis, dtype='d'))
                             for axis in spec.axes])
            turn = _multiply(_conjugate(frame), self._current_pose(uid)[1])
            self._motors[joint] = (uid, int(spec.to), axes, turn)

    def _forget_joint(self, joint: int) -> None:
        self._joints.pop(joint, None)
        self._joint_kinds.pop(joint, None)
        self._joint_bodies.pop(joint, None)
        self._motors.pop(joint, None)

    def _body_mass(self, uid: int) -> float:
        body = self.body_of(uid)
        return float(getattr(body, 'mass', 1.0) or 1.0)

    def _op_unjoint(self, uid: int, joint: int) -> None:  # noqa: ARG002 named by the joint
        jid = self._joints.pop(joint, None)
        self._forget_joint(joint)
        if jid is not None:
            self.world.remove_joints([jid])

    def _op_joint_motor(self, uid: int, joint: int, speed: float,  # noqa: ARG002 named by the joint
                        force: float) -> None:
        jid = self._joints.get(joint)
        if jid is None:
            return
        axis = {'hinge': 3, 'slider': 0, 'wheel': 5}.get(self._joint_kinds.get(joint, ''), 0)
        if self._joint_kinds.get(joint) in ('hinge', 'slider'):
            axis = 0
        self.world.set_joint_motors([jid], pj.MotorMode.VELOCITY, float(speed),
                                    float(force) if force > 0.0 else math.inf, axis=axis)

    def _op_joint_torques(self, uid: int, joint: int,  # noqa: ARG002 named by the joint
                          torques: tuple[float, ...]) -> None:
        jid = self._joints.get(joint)
        if jid is None:
            return
        for axis, torque in enumerate(torques):
            self.world.set_joint_motors([jid], pj.MotorMode.VELOCITY, float(torque), axis=axis)

    # -- the contact filter -------------------------------------------------------
    def set_contact_filter(self, function: Callable[[Any], Any] | None) -> None:
        """Ask ``function(approach)`` about each pair with a body that has a handler, as it first touches.

        None asks nothing. The bodies with handlers carry
        ``BodyFlag.FILTER_CONTACTS``, and the world asks where either body of
        a pair carries it.
        """
        from OpenGLContext.physics.filters import Approach  # noqa: PLC0415 filters import the service's types

        self._contact_filter = function
        if function is None:
            self.world.set_contact_filter(None)
            return
        if not self._filter_contacts:
            self._filter_contacts = True
            marked = [jolt for jolt in self._jolt.values()
                      if self._report_all or self._reported.of([jolt])[0]]
            if marked:
                self.world.set_flags(marked, pj.BodyFlag.FILTER_CONTACTS, True)
        body_of = self.body_of
        failed: list[bool] = []

        def verdict(a: int, b: int, point: Any, normal: Any, approach: float) -> bool:
            first, second = self._svc.get(int(a)), self._svc.get(int(b))
            one = None if first is None else body_of(first)
            two = None if second is None else body_of(second)
            masses = [float(getattr(body, 'mass', 0.0) or 0.0) for body in (one, two)]
            moving = [mass for mass in masses if mass > 0.0]
            reduced = (moving[0] if len(moving) == 1 else
                       (moving[0] * moving[1] / (moving[0] + moving[1])) if moving else 0.0)
            impulse = reduced * max(float(approach), 0.0)
            where = np.asarray(point, dtype='d')
            along = np.asarray(normal, dtype='d')
            self._local.inside = True
            try:
                answer = function(Approach(one, two, float(approach), impulse, where, along))
            except Exception:
                if not failed:
                    failed.append(True)
                    log.exception('the contact filter %r failed; the pair is solved', function)
                return True
            finally:
                self._local.inside = False
            if answer is False:
                with self._refused_lock:
                    self._refused.append((int(a), int(b), where.copy(), along.copy(),
                                          float(approach), impulse))
                return False
            return True

        self.world.set_contact_filter(verdict, either=True)

    # -- reading on the stepping thread -------------------------------------------
    def live_poses(self, uids: Sequence[int]) -> dict[int, LivePose]:
        """The bodies of ``uids`` as Jolt holds them now: inside a tick, after its batches."""
        known = [(uid, self._jolt[uid]) for uid in uids if uid in self._jolt]
        if not known:
            return {}
        state = self.world.bodies_state(np.array([jolt for _uid, jolt in known], dtype=np.uint32))
        found: dict[int, LivePose] = {}
        for row, (uid, _jolt) in enumerate(known):
            if not bool(state.found[row]):
                continue
            found[uid] = LivePose(np.array(state.position[row], dtype='d'),
                                  np.array(state.orientation[row], dtype='d'),
                                  np.array(state.linear_velocity[row], dtype='d'),
                                  np.array(state.angular_velocity[row], dtype='d'),
                                  not bool(state.awake[row]) and self._kinds.get(uid) == 'dynamic')
        return found

    def joint_reading(self, joint: Any, published: Snapshot | None) -> tuple[float, ...]:
        from OpenGLContext.physics.joints import READINGS  # noqa: PLC0415 joints import the service

        none = (0.0,) * (len(joint.spec.axes) if joint.kind == 'motor'
                         else len(READINGS.get(joint.kind, ())))
        snapshot = self.world.latest()
        if snapshot is None:
            return none
        found = self._joint_readings(snapshot).get(joint.uid)
        return none if found is None else found

    # -- queries ------------------------------------------------------------------
    def _filter(self, skip: set[int], triggers: bool = False) -> pj.QueryFilter:
        exclude = [jolt for jolt in (self._jolt.get(uid) for uid in skip) if jolt is not None]
        return pj.QueryFilter(exclude=exclude, triggers=triggers)

    def _raw(self, hit: Any) -> RawHit:
        return RawHit(self._svc.get(int(hit.uid)), np.array(hit.point, dtype='d'),
                      np.array(hit.normal, dtype='d'), float(hit.distance),
                      self.world.triangle_of(int(hit.uid), int(hit.sub_shape)))

    def raycast(self, origin: Any, direction: Any, max_distance: float,
                skip: set[int]) -> RawHit | None:
        heading = np.asarray(direction, dtype='d')
        length = float(np.linalg.norm(heading))
        if length < 1e-12 or max_distance <= 0.0:
            return None
        start = np.asarray(origin, dtype='d')
        self._ground_for_query(start, start + heading / length * float(max_distance))
        self._sync()
        hit = self.world.raycast(np.asarray(origin, dtype='d'), heading / length,
                                 float(max_distance), filter=self._filter(skip))
        return None if hit is None else self._raw(hit)

    def raycast_many(self, origins: Any, directions: Any, max_distance: float,
                     skip: set[int]) -> list[RawHit | None]:
        starts = np.asarray(origins, dtype='d').reshape(-1, 3)
        headings = np.asarray(directions, dtype='d').reshape(-1, 3)
        lengths = np.linalg.norm(headings, axis=1)
        unit = np.divide(headings, lengths[:, None], out=np.zeros_like(headings),
                         where=lengths[:, None] > 1e-12)
        for start, ahead in zip(starts, unit, strict=True):
            self._ground_for_query(start, start + ahead * float(max_distance))
        self._sync()
        hits = self.world.raycast_batch(starts, unit, float(max_distance), filter=self._filter(skip))
        found: list[RawHit | None] = []
        for index in range(len(starts)):
            if not bool(hits.hit[index]):
                found.append(None)
                continue
            uid = int(hits.uid[index])
            found.append(RawHit(self._svc.get(uid), np.array(hits.point[index], dtype='d'),
                                np.array(hits.normal[index], dtype='d'),
                                float(hits.distance[index]),
                                self.world.triangle_of(uid, int(hits.sub_shape[index]))))
        return found

    def sweep_sphere(self, origin: Any, direction: Any, distance: float, radius: float,
                     skip: set[int]) -> float | None:
        start = np.asarray(origin, dtype='d')
        heading = np.asarray(direction, dtype='d')
        length = float(np.linalg.norm(heading))
        if length < 1e-12:
            return None
        end = start + heading / length * max(float(distance), 0.0)
        self._ground_for_query(start, end)
        self._sync()
        found = self._filter(skip)
        hit = self.world.sweep_sphere(float(radius), start, end, filter=found)
        if hit is None:
            # A sphere starting inside a solid is met at once, though Jolt's cast reports
            # only surfaces it reaches.
            inside = self.world.overlap(pj.Shape.sphere(float(radius)), start, filter=found)
            return 0.0 if len(inside) else None
        if float(hit.depth) > 0.0 and float(hit.fraction) <= 0.0:
            return 0.0
        return float(hit.fraction) * max(float(distance), 0.0)

    def overlap(self, proxy: Proxy, translation: Any, quaternion: Any, skip: set[int],
                triggers: bool) -> list[int]:
        at = np.asarray(translation, dtype='d')[:3]
        self._ground_for_query(at, at)
        self._sync()
        found = self.world.overlap(_shape_of(proxy, True), np.asarray(translation, dtype='d')[:3],
                                   tuple(float(v) for v in quaternion),
                                   filter=self._filter(skip, triggers))
        uids = []
        for jolt in found.tolist():
            uid = self._svc.get(int(jolt))
            if uid is None:
                continue
            is_trigger = self._kinds.get(uid) == 'trigger'
            if is_trigger == bool(triggers) and uid not in uids:
                uids.append(uid)
        return uids

    # -- state ----------------------------------------------------------------------
    def save_state(self) -> bytes:
        return self.world.save_state()

    def restore_state(self, data: bytes) -> None:
        self.world.restore_state(data)


def _conjugate(q: np.ndarray) -> np.ndarray:
    return np.array([-q[0], -q[1], -q[2], q[3]], dtype='d')


def _multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The quaternion product ``a b``, quaternions ``(x, y, z, w)``."""
    ax, ay, az, aw = (float(v) for v in a)
    bx, by, bz, bw = (float(v) for v in b)
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz])


def _rotate(q: np.ndarray, v: np.ndarray) -> np.ndarray:
    return _multiply(_multiply(q, np.array([v[0], v[1], v[2], 0.0])), _conjugate(q))[:3]


def _capabilities(capabilities: Any) -> pj.CharacterCapabilities:
    """pyjoltphysics' capabilities with the service's values, field by field.

    A capsule is at least its own diameter tall: a crouch height under twice
    the radius is raised to it, and the standing height to the crouch height.
    """
    fields = {name: getattr(capabilities, name) for name in (
        'walkSpeed', 'runSpeed', 'sprintSpeed', 'crouchSpeed', 'canSprint', 'canCrouch', 'canJump',
        'canFly', 'flySpeed', 'swimSpeed', 'swimDrag', 'jumpHeight', 'jumpFollowsSlope',
        'stepHeight', 'maxSlope', 'eyeHeight', 'standHeight', 'crouchHeight', 'radius',
        'airControl', 'pushFriction', 'terminalVelocity', 'suppressOverVoid', 'coyoteTime',
        'jumpBuffer', 'mass', 'pushMass', 'pushSpeed') if hasattr(capabilities, name)}
    radius = float(fields.get('radius', 0.3))
    crouch = max(float(fields.get('crouchHeight', 1.0)), 2.0 * radius)
    fields['crouchHeight'] = crouch
    fields['standHeight'] = max(float(fields.get('standHeight', 1.8)), crouch)
    return pj.CharacterCapabilities(**fields)


def _concat(batches: list[pj.BodyBatch]) -> pj.BodyBatch:
    """One batch of the bodies of ``batches``, each of one height field tile."""
    if len(batches) == 1:
        return batches[0]
    first = batches[0]
    return pj.BodyBatch(
        positions=np.concatenate([np.asarray(one.positions) for one in batches]),
        shape=[one.shape for one in batches], motion=pj.MotionType.STATIC,
        material=first.material, filter=first.filter, flags=first.flags)


def _shape_of(proxy: Proxy, dynamic: bool) -> pj.Shape:
    """The pyjoltphysics shape of ``proxy``, for a dynamic body where ``dynamic``.

    A triangle mesh collides from both faces, as the omi engine's does, so each
    triangle is listed in both windings. A moving body cannot be a mesh in
    Jolt: a dynamic mesh is held as the hull of its points. A box of a body
    that is not dynamic is rounded by :data:`STATIC_ROUNDING`.
    """
    params = proxy.params
    kind = proxy.kind
    if kind == 'box':
        # A box that does not move keeps its edges as drawn; Jolt's default 5 cm
        # rounding would make the lip of a step a ramp for a fast body.
        return pj.Shape.box(tuple(float(v) for v in params['size']),
                            rounding=None if dynamic else STATIC_ROUNDING)
    if kind == 'sphere':
        return pj.Shape.sphere(float(params['radius']))
    if kind == 'capsule':
        return pj.Shape.capsule(float(params['radius']), max(float(params['height']), 1e-4))
    if kind == 'cylinder':
        bottom = float(params['radius'])
        top = float(params.get('radius_top', bottom))
        height = float(params['height'])
        if abs(top - bottom) < 1e-9:
            return pj.Shape.cylinder(bottom, height)
        angles = np.linspace(0.0, 2.0 * math.pi, 24, endpoint=False)
        ring = np.stack([np.cos(angles), np.sin(angles)], axis=1)
        points = np.concatenate([
            np.column_stack([ring[:, 0] * bottom, np.full(24, -height / 2.0), ring[:, 1] * bottom]),
            np.column_stack([ring[:, 0] * max(top, 1e-3), np.full(24, height / 2.0),
                             ring[:, 1] * max(top, 1e-3)])])
        return pj.Shape.convex(points)
    if kind == 'convex':
        return pj.Shape.convex(np.asarray(params['points'], dtype='d').reshape(-1, 3))
    if kind == 'trimesh':
        points = np.asarray(params['points'], dtype='d').reshape(-1, 3)
        indices = np.asarray(params['indices'], dtype=np.int64).reshape(-1, 3)
        if dynamic:
            return pj.Shape.convex(points)
        numbers = np.arange(len(indices), dtype=np.uint32)
        return pj.Shape.mesh(points, np.concatenate([indices, indices[:, ::-1]]),
                             ids=np.concatenate([numbers, numbers]))
    if kind == 'compound':
        parts = [(_shape_of(part, dynamic), tuple(float(v) for v in position),
                  tuple(float(v) for v in orientation))
                 for part, position, orientation in params['parts']]
        return pj.Shape.compound(parts)
    if kind == 'heightfield':
        spacing = params.get('spacing', 1.0)
        return pj.Shape.heightfield(np.asarray(params['heights'], dtype='d'),
                                    origin=tuple(float(v) for v in params.get('origin', (0, 0, 0))),
                                    spacing=spacing if np.ndim(spacing) == 0 else tuple(spacing),
                                    bits_per_sample=16)
    raise ValueError('the Jolt engine has no shape for a %s proxy' % (kind,))


def _zone_of(zone: Any) -> pj.GravityZone | None:
    """pyjoltphysics' zone for a service :class:`~OpenGLContext.physics.types.GravityZone`."""
    from OpenGLContext.physics.zones import Box, Sphere, ZoneRegion  # noqa: PLC0415 zones import the scenegraph

    region = zone.region
    values: dict[str, Any] = {'gravity': float(zone.gravity), 'priority': int(zone.priority),
                              'replace': bool(zone.replace), 'stop': bool(zone.stop)}
    if zone.toward is not None:
        values.update(field=pj.ZoneField.POINT, center=tuple(float(v) for v in zone.toward))
    else:
        values.update(field=pj.ZoneField.DIRECTIONAL,
                      direction=tuple(float(v) for v in zone.direction))
    if isinstance(region, Box):
        return pj.GravityZone.box(tuple(region.center), tuple(region.size), **values)
    if isinstance(region, Sphere):
        return pj.GravityZone.sphere(tuple(region.center), float(region.radius), **values)
    if isinstance(region, ZoneRegion):
        shape = region.shape
        centre = tuple(float(v) for v in shape.centre)
        if shape.kind == 'sphere':
            return pj.GravityZone.sphere(centre, float(shape.params[0]), **values)
        reach = tuple(2.0 * float(v) for v in shape.reach)
        return pj.GravityZone.box(centre, reach, **values)
    log.warning('the Jolt engine has no gravity zone for a region %r', region)
    return None


def _motor(speed: float, force: float) -> pj.Motor | None:
    if force <= 0.0:
        return None
    return pj.Motor(pj.MotorMode.VELOCITY, float(speed), float(force))


def _limits(lower: float, upper: float) -> tuple[float, float] | None:
    if math.isinf(lower) and math.isinf(upper):
        return None
    return (max(lower, -math.pi) if not math.isinf(lower) else -math.pi,
            min(upper, math.pi) if not math.isinf(upper) else math.pi)


def _joint_of(spec: Any, body: int, to: int, mass: float) -> pj.Joint:
    """pyjoltphysics' joint for a service :class:`~OpenGLContext.physics.joints.JointSpec`."""
    common: dict[str, Any] = {'collide': bool(spec.collide)}
    kind = spec.kind
    if kind == 'hinge':
        return pj.Joint.hinge(body, to, anchor=spec.anchor, axis=spec.axis,
                              limits=_limits(spec.lower, spec.upper),
                              motor=_motor(spec.speed, spec.force), **common)
    if kind == 'ball':
        return pj.Joint.ball(body, to, anchor=spec.anchor, **common)
    if kind == 'slider':
        limits = None
        if not (math.isinf(spec.lower) and math.isinf(spec.upper)):
            limits = (min(spec.lower, 0.0) if not math.isinf(spec.lower) else -1e6,
                      max(spec.upper, 0.0) if not math.isinf(spec.upper) else 1e6)
        return pj.Joint.slider(body, to, axis=spec.axis, anchor=spec.anchor, limits=limits,
                               motor=_motor(spec.speed, spec.force), **common)
    if kind == 'distance':
        return pj.Joint.distance(body, to, anchor=spec.anchor, to_anchor=spec.to_anchor,
                                 length=spec.length, **common)
    if kind == 'universal':
        return pj.Joint.universal(body, to, anchor=spec.anchor, axis1=spec.to_axis,
                                  axis2=spec.axis, **common)
    if kind == 'wheel':
        suspension = None
        if spec.stiffness > 0.0:
            frequency = math.sqrt(spec.stiffness / mass) / (2.0 * math.pi)
            ratio = spec.damping / (2.0 * math.sqrt(spec.stiffness * mass))
            suspension = (frequency, ratio)
        return pj.Joint.two_axis_hinge(
            body, to, anchor=spec.anchor, axis1=spec.axis, axis2=spec.to_axis,
            limits1=_limits(spec.lower, spec.upper),
            motor1=_motor(spec.steer_speed, spec.steer_force),
            motor2=_motor(spec.speed, spec.force), suspension=suspension, **common)
    if kind == 'motor':
        return pj.Joint.motor(body, to, axes=spec.axes, torques=spec.torques, **common)
    raise ValueError('the Jolt engine has no joint of kind %r' % (kind,))
