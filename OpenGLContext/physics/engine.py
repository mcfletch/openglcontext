"""The engine a physics service steps its world with, and how one is chosen.

:class:`~OpenGLContext.physics.service.Physics` keeps the handles, the
handlers and the scene in step with the world. Everything it asks of the world
goes through an :class:`Engine`: the commands, stepping and publishing, live
reads on the stepping thread, queries, joint readings, characters and state.

Two engines implement it. ``'jolt'``, the default
(:class:`~OpenGLContext.physics.joltengine.JoltEngine`), steps a Jolt world
from pyjoltphysics on its native world thread: free-running at the tick rate,
or in lockstep with the frame, which runs exactly the ticks the frame owes.
``'omi'`` (:class:`~OpenGLContext.physics.omiengine.OmiEngine`) steps an
omi_physics world inline in the frame or on a Python thread; omi_physics is
deprecated and is installed only by the ``omi-physics`` extra, for programs that still
name it. ``PhysicsDefinition.engine`` chooses (env:
OPENGLCONTEXT_PHYSICS_ENGINE); :func:`make_engine` makes the one it names.
"""
from __future__ import annotations

import abc
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple

import numpy as np

from OpenGLContext.physics.records import Command, PhysicsEvent, Snapshot, Step
from OpenGLContext.physics.settings import ENGINES, PhysicsDefinition
from OpenGLContext.physics.types import EngineInfo, WorldCounts

if TYPE_CHECKING:
    from OpenGLContext.physics.proxy import Proxy
    from OpenGLContext.physics.vehicles import Surface, VehicleSettings, VehicleState

__all__ = ['ENGINES', 'OMI_EXTRA', 'Engine', 'EngineUnavailable', 'LivePose', 'Outbox', 'RawHit',
           'make_engine', 'require_omi']

#: What installs omi_physics beside the engine.
OMI_EXTRA = 'pip install OpenGLContext[omi-physics]'

class EngineUnavailable(RuntimeError):
    """The engine a definition names cannot be made here: its package is not installed."""


def require_omi(feature: str) -> None:
    """Raise :class:`EngineUnavailable` naming ``feature`` where omi_physics cannot be imported.

    The parts of the engine still built on an omi_physics world call this
    before they make one, so a program without the ``omi-physics`` extra is told
    which extra to install.
    """
    try:
        import omi_physics  # noqa: F401, PLC0415 asked when a feature is used
    except ImportError as error:
        raise EngineUnavailable('%s needs the deprecated omi_physics (%s); install it with %s'
                                % (feature, error, OMI_EXTRA)) from error


class Outbox(NamedTuple):
    """What the engine hands the render thread: a snapshot if a new one was published, and events."""
    snapshot: Snapshot | None
    events: list[PhysicsEvent]


class RawHit(NamedTuple):
    """What a ray met: a body by uid (None for one the service has no uid for), where and how far."""
    uid: int | None
    point: np.ndarray
    normal: np.ndarray
    distance: float
    triangle: int


class LivePose(NamedTuple):
    """A body as the world holds it on the stepping thread."""
    position: np.ndarray
    orientation: np.ndarray
    velocity: np.ndarray
    angular_velocity: np.ndarray
    asleep: bool


class Engine(abc.ABC):
    """What the physics service needs of the engine that steps its world.

    Bodies, joints and characters are named by the service's own uids;
    commands are :class:`~OpenGLContext.physics.records.Command` records with
    the service's sequence numbers, and a snapshot's ``applied_seq`` counts in
    them.
    """

    #: The engine's name, one of :data:`ENGINES`.
    name: str = ''
    #: Whether a character stands in the world as a kinematic body the service places.
    stand_ins: bool = False
    #: How far beyond its capsule a character's controller meets the bodies it pushes, in
    #: metres; the stand-in's box reaches this far.
    push_reach: float = 0.0
    #: Whether the engine carries vehicles (:meth:`add_vehicle`).
    vehicles: bool = False

    def __init__(self, definition: PhysicsDefinition) -> None:
        self.definition = definition
        #: Called with each :class:`Step` before and after the world steps, on the stepping thread.
        self.before_step: list[Callable[[Step], Any]] = []
        self.after_step: list[Callable[[Step], Any]] = []
        #: Called with the events a step made, on the stepping thread.
        self.on_events: list[Callable[[list[PhysicsEvent]], Any]] = []
        #: Asked whether the world must keep stepping while nothing moves.
        self.wants_steps: list[Callable[[], bool]] = []
        #: Gives the characters the frame steps; the service sets it.
        self.framed_characters: Callable[[], Sequence[Any]] = tuple
        #: Gives the service's body of a uid, or None; the service sets it.
        self.body_of: Callable[[int], Any] = _no_body
        #: Gives a material name's coefficients; the service sets it.
        self.material_of: Callable[[str], Any] | None = None
        #: Gives the render thread's copy of the bodies, for an engine that queries one; the service sets it.
        self.replica: Callable[[], Any] | None = None
        #: ``guard(owner, function, *arguments)`` calls a character's code, logging a failure once.
        self.guard: Callable[..., Any] = _call
        #: Asked whether a handler of bodies' events runs on the stepping thread; the service sets it.
        self.wants_events: Callable[[], bool] = _never

    # -- stepping -------------------------------------------------------
    @property
    @abc.abstractmethod
    def error(self) -> BaseException | None:
        """The exception that stopped the engine's thread, or None."""

    @property
    @abc.abstractmethod
    def step_dt(self) -> float:
        """The fixed step, in seconds."""

    @property
    @abc.abstractmethod
    def max_catch_up(self) -> float:
        """The longest span of time one frame steps, in seconds."""

    @abc.abstractmethod
    def on_engine_thread(self) -> bool:
        """Whether the calling thread is stepping the world right now (a step hook or a physics callback)."""

    @abc.abstractmethod
    def submit(self, command: Command) -> None:
        """Make ``command``, from any thread."""

    @abc.abstractmethod
    def collect(self, dt: float) -> Outbox:
        """Take what the engine has published; a world the frame steps runs the steps ``dt`` owes first."""

    @abc.abstractmethod
    def step(self, dt: float) -> None:
        """Advance by ``dt`` seconds by hand, for a service nothing else steps."""

    @abc.abstractmethod
    def flush(self) -> None:
        """Apply waiting commands now, where the engine can without stepping."""

    @abc.abstractmethod
    def start(self) -> None:
        """Begin stepping, where the engine steps on its own."""

    @abc.abstractmethod
    def stop(self) -> bool:
        """Stop stepping; whether the thread that stepped has ended."""

    @abc.abstractmethod
    def callbacks_changed(self) -> None:
        """A handler, step hook or posted call was added or removed: register what the world needs now."""

    @abc.abstractmethod
    def pin(self, on: bool) -> None:
        """Hold the world in step with the frame whatever the mode (a capture, a replay), or let it go."""

    @abc.abstractmethod
    def set_contact_filter(self, function: Callable[[Any], Any] | None) -> None:
        """Ask ``function(approach)`` about each pair as it first touches; None asks nothing."""

    def pass_group_id(self, name: str | None) -> int:
        """The engine's number for the characters' pass group ``name``; 0 for none."""
        return 0

    def ground_material(self, controller: Any) -> str | None:
        """The name of the material under a character, where the engine reports it."""
        return None

    @abc.abstractmethod
    def set_mode(self, mode: str) -> None:
        """Step ``'inline'`` (with the frame) or ``'thread'`` (on its own), carrying waiting commands over."""

    @property
    @abc.abstractmethod
    def mode(self) -> str:
        """``'inline'`` or ``'thread'``: whether the frame steps the world or it steps on its own."""

    @abc.abstractmethod
    def live_time(self) -> float:
        """The world's clock as the stepping thread sees it, in seconds."""

    @abc.abstractmethod
    def character_steps(self, dt: float) -> tuple[int, float]:
        """The fixed steps the service's own characters owe this frame, and the part step left."""

    @abc.abstractmethod
    def info(self) -> EngineInfo:
        """The engine's name, version, step rate and precision."""

    def counts(self, published: Snapshot | None) -> WorldCounts:
        """How many bodies the world holds and how many pairs touch; from ``published`` by default."""
        if published is None:
            return WorldCounts(0, 0)
        return WorldCounts(published.bodies, published.contacts)

    # -- reading on the stepping thread ----------------------------------
    @abc.abstractmethod
    def live_poses(self, uids: Sequence[int]) -> dict[int, LivePose]:
        """The bodies of ``uids`` the world holds, as it holds them; for the stepping thread."""

    @abc.abstractmethod
    def joint_reading(self, joint: Any, published: Snapshot | None) -> tuple[float, ...]:
        """``joint``'s readings, live where the engine can read them, else from ``published``."""

    # -- queries ----------------------------------------------------------
    @abc.abstractmethod
    def raycast(self, origin: Any, direction: Any, max_distance: float,
                skip: set[int]) -> RawHit | None:
        """The first body a ray meets, passing through the bodies of uids ``skip``."""

    @abc.abstractmethod
    def raycast_many(self, origins: Any, directions: Any, max_distance: float,
                     skip: set[int]) -> list[RawHit | None]:
        """Several rays, each answered as :meth:`raycast` answers one."""

    @abc.abstractmethod
    def sweep_sphere(self, origin: Any, direction: Any, distance: float, radius: float,
                     skip: set[int]) -> float | None:
        """How far a sphere travels before it touches a body; None where it goes ``distance`` clear."""

    @abc.abstractmethod
    def overlap(self, proxy: Proxy, translation: Any, quaternion: Any, skip: set[int],
                triggers: bool) -> list[int]:
        """The uids of the solid bodies (or with ``triggers`` the triggers) a placed shape overlaps."""

    # -- characters -------------------------------------------------------
    @abc.abstractmethod
    def make_character(self, physics: Any, centre: np.ndarray, capabilities: Any,
                       gravity: float) -> tuple[Any, Any]:
        """The body and the controller of a new character with its capsule's centre at ``centre``."""

    # -- vehicles ---------------------------------------------------------
    def add_vehicle(self, vid: int, chassis: int, settings: VehicleSettings) -> None:
        """Make vehicle ``vid`` on the dynamic body of uid ``chassis``, after the commands sent before it."""
        raise NotImplementedError('the %s engine has no vehicles; vehicles need the jolt engine'
                                  % (self.name,))

    def remove_vehicle(self, vid: int) -> None:
        """Take vehicle ``vid`` out of the world; its chassis stays a body."""
        raise NotImplementedError('the %s engine has no vehicles' % (self.name,))

    def vehicle_input(self, vid: int, values: tuple[float, float, float, float]) -> None:
        """Hold vehicle ``vid``'s (throttle, steer, brake, handbrake) for the next tick, from any thread."""
        raise NotImplementedError('the %s engine has no vehicles' % (self.name,))

    def vehicle_surface(self, vid: int, wheel: int | None, surface: Surface | None) -> None:
        """The ground under one wheel of vehicle ``vid`` (all for None); None gives them to the materials."""
        raise NotImplementedError('the %s engine has no vehicles' % (self.name,))

    def vehicle_state(self, vid: int) -> VehicleState | None:
        """Vehicle ``vid`` as the newest tick left it; None before the world has stepped it."""
        return None

    # -- stand-ins (an engine whose characters step against a copy of the bodies) --
    def build_replica(self, specs: dict[int, Any], published: Snapshot | None) -> Any:
        """The render thread's copy of the bodies ``specs`` holds, posed as ``published`` left them."""
        raise NotImplementedError('the %s engine keeps no copy of the bodies' % (self.name,))

    def proxy_bounds(self, proxy: Proxy, position: Any,
                     quaternion: Any) -> tuple[np.ndarray, np.ndarray]:
        """The world box of ``proxy`` at ``position`` turned by ``quaternion``, as the copy holds it."""
        raise NotImplementedError('the %s engine keeps no copy of the bodies' % (self.name,))

    # -- state ------------------------------------------------------------
    def save_state(self) -> bytes:
        """The world's bodies and joints as bytes :meth:`restore_state` reads back."""
        raise NotImplementedError('the %s engine does not save its state' % (self.name,))

    def restore_state(self, data: bytes) -> None:
        """Put the bodies and joints back as :meth:`save_state` found them, from the next step."""
        raise NotImplementedError('the %s engine does not restore a state' % (self.name,))

    def close(self) -> None:
        """Stop stepping and let go of the world."""
        self.stop()


def _no_body(uid: int) -> Any:
    return None


def _never() -> bool:
    return False


def _call(owner: Any, function: Callable[..., Any], *arguments: Any) -> Any:
    return function(*arguments)


def make_engine(definition: PhysicsDefinition, wake: Callable[[], Any] | None = None) -> Engine:
    """The engine ``definition.engine`` names, made for ``definition``.

    Raises :class:`EngineUnavailable` where that engine's package is not
    installed; the service does not fall back to the other.
    """
    if definition.engine == 'jolt':
        try:
            from OpenGLContext.physics.joltengine import JoltEngine  # noqa: PLC0415 the engine loads on use
        except ImportError as error:
            raise EngineUnavailable(
                "PhysicsDefinition.engine is 'jolt' and pyjoltphysics cannot be imported (%s); "
                'OpenGLContext requires pyjoltphysics: install it' % (error,)) from error
        return JoltEngine(definition, wake=wake)
    try:
        from OpenGLContext.physics.omiengine import OmiEngine  # noqa: PLC0415 omi_physics loads with its engine
    except ImportError as error:
        raise EngineUnavailable(
            "PhysicsDefinition.engine is 'omi' and omi_physics cannot be imported (%s); "
            'install it with %s, or choose the jolt engine' % (error, OMI_EXTRA)) from error
    return OmiEngine(definition, wake=wake)
