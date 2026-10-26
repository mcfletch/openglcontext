#! /usr/bin/env python
"""Collision events: a yard where things are struck, and each strike calls the handler registered for it.

Walk around with the arrow keys and press the keys it prints:

    oglc-physics-events

    d      drop the crates; each landing thuds, louder the harder it lands
    l      launch a ball at each pane of glass
    L      launch them gently, too softly to break anything
    m      mend the glass
    space  fire the gun where you are looking; a crate it hits is knocked away
    w      put the weight on the pressure plate, or take it off
    c      cap the frame rate at 20 fps, or lift the cap

The left pane breaks after the solve: its handler reads how hard it was hit
and shatters it, and the ball has already bounced. The right pane breaks
before the solve: a contact filter lets the ball through, and the ball carries
on. The door opens while anything is on the plate. With the frame rate capped
every landing still thuds, because the world steps at a fixed 120 steps a
second whatever the frame rate is. docs/physics.rst describes each of these,
and this file is the working code for them.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from typing import Any, Optional

import numpy as np

from omi_audio.clip import DEFAULT_SAMPLE_RATE
from omi_physics import model
from omi_physics.contactevents import PairPreview, Verdict

from OpenGLContext.audio import sounds
from OpenGLContext.audio.manager import Audio
from OpenGLContext.events.framestep import FrameStep
from OpenGLContext.physics.body import Body
from OpenGLContext.physics.callbacks import physics_callback
from OpenGLContext.physics.events import Collision
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

__all__ = ['CollisionYard', 'definition', 'main']

#: Steps a second the yard's world takes.
TICK_HZ = 120.0

CRATE_SIZE = 0.8
#: Where the crates stand, and the heights they are dropped from, in metres.
CRATE_SPOTS = [(-3.0, 2.0), (-1.5, 3.0), (0.0, 2.0), (1.5, 3.0), (3.0, 2.0)]
DROP_HEIGHTS = [2.5, 3.5, 4.5, 3.0, 4.0]
#: Closing speed below which a landing is not a thud, and the one that is full
#: level, in metres per second.
IMPACT_FLOOR = 0.6
IMPACT_FULL = 8.0

#: The panes stand across the yard at this depth, one either side.
PANE_Z = -4.0
PANE_SIZE = (1.8, 1.8, 0.06)
PANE_X = {'after': -3.0, 'before': 3.0}
#: The impulse a pane survives, in N*s.
PANE_STRENGTH = 6.0
#: Pieces a broken pane falls into, across and up.
FRAGMENT_GRID = (3, 2)
FRAGMENTS = FRAGMENT_GRID[0] * FRAGMENT_GRID[1]
BALL_RADIUS = 0.25
BALL_MASS = 2.0
#: How far in front of its pane a ball is launched from, and how fast.
LAUNCH_DISTANCE = 2.0
LAUNCH_SPEED = 8.0

#: The gun: how far it reaches, and the push of a round, in N*s.
GUN_RANGE = 60.0
GUN_IMPULSE = 15.0

PLATE_CENTRE = (7.0, 0.0, 2.0)
PLATE_SIZE = (1.6, 0.4, 1.6)
WEIGHT_PARKED = (9.5, 0.4, 2.0)
DOOR_CENTRE = (7.0, 1.2, -1.0)
DOOR_SIZE = (2.0, 2.4, 0.2)
#: How far the door rises, in metres, and how fast, in metres per second.
DOOR_TRAVEL = 2.2
DOOR_SPEED = 1.5

#: The frame time the ``c`` key caps the demo at: 20 fps.
CAPPED_FRAME = 1.0 / 20.0
MASTER_GAIN = 0.5


def definition() -> PhysicsDefinition:
    """The world the yard runs in, for the context's ``ContextDefinition.physics``.

    The yard changes the live world between steps (its collision filters and
    its contact verdict), which ``mode='inline'`` allows, and every body it has
    is added by name, so the shapes it draws as decoration are not bodies
    too (``colliders='explicit'``).
    """
    return PhysicsDefinition(mode='inline', tickHz=TICK_HZ, maxCatchUp=0.1,
                             colliders='explicit')


class Finishes:
    """The yard's materials, made once: stone, brick, metals and glass."""

    def __init__(self) -> None:
        self.floor = surfaces.pbr_material(surfaces.checkered_marble(512, tiles=8))
        self.crates = [
            surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.STEEL, 0.3)),
            surfaces.pbr_material(surfaces.sandstone(256)),
            surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.COPPER, 0.3)),
            surfaces.pbr_material(surfaces.brick(256)),
            surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.BRONZE, 0.35)),
        ]
        self.glass = PhysicalMaterial(baseColor=(0.75, 0.88, 0.95), metallic=0.0,
                                      roughness=0.04, transparency=0.6)
        self.ball = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.STEEL, 0.15))
        self.plate = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.BRONZE, 0.4))
        self.door = surfaces.pbr_material(surfaces.plaster(256), relief=0.5)
        self.stone = surfaces.pbr_material(surfaces.sandstone(256))
        self.weight = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.GOLD, 0.25))


def _shape(geometry: Any, material: Any) -> Any:
    return basenodes.Shape(geometry=geometry,
                           appearance=basenodes.Appearance(material=material))


class CollisionYard:
    """The demo's bodies, handlers and sounds, with no GL and no window.

    ``physics`` is an inline :class:`~OpenGLContext.physics.service.Physics`
    (see :func:`definition`) and ``audio`` the :class:`~OpenGLContext.audio.manager.Audio`
    that plays what is struck. The context puts :meth:`scene` in front of the
    camera and forwards key presses to :meth:`drop`, :meth:`launch`,
    :meth:`mend`, :meth:`fire`, :meth:`toggle_weight` and :meth:`toggle_cap`.
    The service steps the world; nothing here is called each frame.
    """

    def __init__(self, physics: Physics, audio: Audio,
                 sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.physics = physics
        self.audio = audio
        self.finish = Finishes()
        #: Everything the yard adds and takes away while it runs.
        self.root = basenodes.Group(children=[])
        for name, restitution in (('stone', 0.1), ('glass', 0.3), ('steel', 0.5)):
            physics.materials.define(name, restitution=restitution)
        world = physics.world
        # The shards of a pane do not deflect the ball that broke it: a ball let
        # through before the solve is still passing the place they appear.
        self._filters = {
            'ball': world.add_filter(model.CollisionFilter(collisionSystems=('ball',))),
            'shard': world.add_filter(model.CollisionFilter(
                collisionSystems=('shard',), notCollideWithSystems=('ball',))),
        }
        #: The frame rate the ``c`` key caps the demo at, held for the context's loop.
        self.frames = FrameStep(longest=0.1)

        self._box((30.0, 1.0, 30.0), (0.0, -0.5, 0.0), self.finish.floor, 'static')
        self.crates = [
            self._box((CRATE_SIZE,) * 3, (x, CRATE_SIZE / 2, z), finish, 'dynamic', mass=20.0)
            for (x, z), finish in zip(CRATE_SPOTS, self.finish.crates)]
        self.balls = {name: self._ball(name) for name in PANE_X}
        self.panes: dict[str, Body] = {}
        self.broken: set[str] = set()
        self.fragments: list[Body] = []
        self.on_plate: set[Body] = set()
        self.plate = self._plate()
        self.weight = self._box((0.7, 0.7, 0.7), WEIGHT_PARKED, self.finish.weight,
                                'dynamic', mass=40.0)
        self.door = self._box(DOOR_SIZE, DOOR_CENTRE, self.finish.door, 'kinematic')
        self._lift = 0.0
        self._door_time: Optional[float] = None
        self.door.drive(self._door_pose)
        for x in PANE_X.values():
            self._frame(x, PANE_Z, PANE_SIZE[0], PANE_SIZE[1])
        self._frame(DOOR_CENTRE[0], DOOR_CENTRE[2], DOOR_SIZE[0],
                    DOOR_SIZE[1] + DOOR_TRAVEL)

        for body in (*self.crates, *self.balls.values()):
            body.addEventHandler('hit', function=self._thud, above=IMPACT_FLOOR)
        self.plate.addEventHandler('enter', function=self._stepped_on)
        self.plate.addEventHandler('exit', function=self._stepped_off)
        self._pane_handlers = {'after': self._after_struck, 'before': self._before_struck}
        world.set_contact_filter(self._verdict)
        self.mend()

        self.clips = {
            'thud': sounds.rumble(0.3, sample_rate=sample_rate, decay=16.0, cutoff=320.0,
                                  pitch=95.0, pitch_end=50.0, tone=0.5, drive=2.0, seed=3),
            'ping': sounds.impact(0.12, sample_rate=sample_rate, seed=9),
            'shatter': sounds.noise(0.5, sample_rate=sample_rate, amplitude=0.5, seed=13),
        }
        self.placed = sounds.positional(near=3.0, rolloff=0.8)

    # -- building ------------------------------------------------------------
    def _box(self, size: Sequence[float], position: Sequence[float], finish: Any,
             kind: str, mass: float = 1.0, material: str = 'stone',
             collision_filter: int = -1, solid: bool = True) -> Body:
        """A box of ``kind`` (``'static'``, ``'dynamic'`` or ``'kinematic'``), drawn and in the world."""
        node = basenodes.Transform(translation=tuple(position), children=[
            _shape(basenodes.Box(size=tuple(size), solid=solid), finish)])
        self.root.children.append(node)
        shape = Proxy.box(size)
        if kind == 'dynamic':
            return self.physics.add_dynamic(node, proxy=shape, mass=mass, material=material,
                                            collision_filter=collision_filter)
        if kind == 'kinematic':
            return self.physics.add_kinematic(node, proxy=shape, material=material)
        return self.physics.add_static(node, proxy=shape, material=material)

    def _ball(self, name: str) -> Body:
        node = basenodes.Transform(
            translation=(PANE_X[name], BALL_RADIUS, PANE_Z + LAUNCH_DISTANCE + 1.0),
            children=[_shape(basenodes.Sphere(radius=BALL_RADIUS), self.finish.ball)])
        self.root.children.append(node)
        return self.physics.add_dynamic(
            node, proxy=Proxy.sphere(BALL_RADIUS), mass=BALL_MASS, material='steel',
            collision_filter=self._filters['ball'])

    def _frame(self, x: float, z: float, width: float, height: float) -> None:
        """Two stone posts and a lintel around an opening ``width`` by ``height``."""
        post = 0.25
        for side in (-1.0, 1.0):
            self._box((post, height + post, post),
                      (x + side * (width + post) / 2, (height + post) / 2, z),
                      self.finish.stone, 'static')
        self._box((width + 2 * post, post, post), (x, height + post / 2, z),
                  self.finish.stone, 'static')

    def _plate(self) -> Body:
        x, y, z = PLATE_CENTRE
        width, height, depth = PLATE_SIZE
        self.root.children.append(basenodes.Transform(
            translation=(x, 0.02, z),
            children=[_shape(basenodes.Box(size=(width, 0.04, depth)), self.finish.plate)]))
        node = basenodes.Transform(translation=(x, y + height / 2, z))
        return self.physics.add_trigger(node, proxy=Proxy.box(PLATE_SIZE))

    def _discard(self, body: Body) -> None:
        body.remove()
        if body.node in self.root.children:
            self.root.children.remove(body.node)

    def scene(self) -> Any:
        """The scenegraph: a light, a sky and everything in the yard."""
        return basenodes.sceneGraph(children=[
            basenodes.DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=1.0),
            basenodes.DirectionalLight(direction=(0.5, -0.3, 0.8), intensity=0.35),
            self.root,
            basenodes.SimpleBackground(color=(0.55, 0.62, 0.72)),
        ])

    # -- the handlers --------------------------------------------------------
    def _play(self, name: str, point: Any, gain: float) -> None:
        self.audio.play(self.clips[name], at=tuple(float(v) for v in point), gain=gain,
                        priority=0.4, emitter=self.placed)

    def _thud(self, hit: Collision) -> None:
        self._play('thud', hit.point, min(1.0, hit.speed / IMPACT_FULL))

    def _after_struck(self, hit: Collision) -> None:
        self._pane_struck('after', hit)

    def _before_struck(self, hit: Collision) -> None:
        self._pane_struck('before', hit)

    def _pane_struck(self, name: str, hit: Collision) -> None:
        """Shatter a pane the blow was too much for.

        The ``after`` pane reads the impulse the solver applied. The
        ``before`` pane was let through by :meth:`_verdict`, so its hit
        arrives unsolved.
        """
        breaks = hit.impulse > PANE_STRENGTH if name == 'after' else not hit.solved
        if breaks and name not in self.broken:
            self._shatter(name, hit.point, hit.normal)

    def _verdict(self, pair: PairPreview) -> Verdict:
        """Let a ball through the ``before`` pane when the blow would break it."""
        pane = self.panes.get('before')
        if pane is not None and pair.impulse > PANE_STRENGTH:
            world = self.physics.world
            if pane.uid in (world.handle_of(pair.a), world.handle_of(pair.b)):
                return Verdict.IGNORE_PAIR
        return Verdict.SOLVE

    def _stepped_on(self, hit: Collision) -> None:
        if hit.other is not None:
            self.on_plate.add(hit.other)

    def _stepped_off(self, hit: Collision) -> None:
        self.on_plate.discard(hit.other)

    @property
    def plate_pressed(self) -> bool:
        """Whether anything is standing on the pressure plate."""
        return bool(self.on_plate)

    @physics_callback
    def _door_pose(self, until: float) -> tuple[tuple[float, float, float], None]:
        """Where the door is at the end of a step: it rises while the plate is pressed and sinks when not."""
        if self._door_time is not None:
            reach = DOOR_SPEED * (until - self._door_time)
            target = DOOR_TRAVEL if self.plate_pressed else 0.0
            self._lift += max(-reach, min(reach, target - self._lift))
        self._door_time = until
        x, y, z = DOOR_CENTRE
        return (x, y + self._lift, z), None

    # -- the panes ------------------------------------------------------------
    def _shatter(self, name: str, point: np.ndarray, push: np.ndarray) -> None:
        """Replace pane ``name`` with the pieces it broke into, pushed along ``push``."""
        pane = self.panes.pop(name)
        self._discard(pane)
        self.broken.add(name)
        self._play('shatter', point, 1.0)
        columns, rows = FRAGMENT_GRID
        width, height, depth = PANE_SIZE
        piece = (width / columns, height / rows, depth)
        x0, z0 = PANE_X[name], PANE_Z
        for column in range(columns):
            for row in range(rows):
                centre = (x0 - width / 2 + piece[0] * (column + 0.5),
                          piece[1] * (row + 0.5), z0)
                fragment = self._box(piece, centre, self.finish.glass, 'dynamic', mass=0.5,
                                     material='glass', solid=False,
                                     collision_filter=self._filters['shard'])
                fragment.set_velocity(1.5 * np.asarray(push))
                self.fragments.append(fragment)

    def mend(self) -> None:
        """Sweep up the pieces and put both panes back."""
        for fragment in self.fragments:
            self._discard(fragment)
        self.fragments = []
        for name, x in PANE_X.items():
            if name in self.panes:
                continue
            pane = self._box(PANE_SIZE, (x, PANE_SIZE[1] / 2, PANE_Z), self.finish.glass,
                             'static', material='glass', solid=False)
            pane.addEventHandler('hit', function=self._pane_handlers[name])
            self.panes[name] = pane
        self.broken = set()

    # -- keys ---------------------------------------------------------------------
    def drop(self) -> None:
        """Lift every crate to its drop height and let go."""
        for crate, (x, z), height in zip(self.crates, CRATE_SPOTS, DROP_HEIGHTS):
            self._place(crate, (x, height, z))

    def launch(self, speed: float = LAUNCH_SPEED) -> None:
        """Throw a ball at each pane at ``speed`` metres per second."""
        for name, ball in self.balls.items():
            self._place(ball, (PANE_X[name], 1.2, PANE_Z + LAUNCH_DISTANCE),
                        velocity=(0.0, 0.0, -speed))

    def fire(self, origin: Sequence[float], direction: Sequence[float]) -> Optional[Body]:
        """Fire the gun from ``origin`` along ``direction``; return the body it hit, or None.

        A round that strikes a crate pushes it by :data:`GUN_IMPULSE` at the
        point it hit, and the crate pings.
        """
        found = self.physics.raycast(origin, direction, max_distance=GUN_RANGE)
        if found is None or found.body is None:
            return None
        heading = np.asarray(direction, dtype='d')
        found.body.apply_impulse(heading / np.linalg.norm(heading) * GUN_IMPULSE,
                                 at=found.point)
        if found.body in self.crates:
            self._play('ping', found.point, 0.8)
        return found.body

    def toggle_weight(self) -> None:
        """Drop the weight onto the plate, or put it back where it was parked."""
        x, _y, z = PLATE_CENTRE
        on_plate = abs(float(self.weight.position[0]) - x) < 1.0
        self._place(self.weight, WEIGHT_PARKED if on_plate else (x, 1.5, z))

    @property
    def frame_cap(self) -> Optional[float]:
        """The shortest frame the demo keeps to, in seconds; None for no cap."""
        return self.frames.cap

    def toggle_cap(self) -> Optional[float]:
        """Cap the frame time at :data:`CAPPED_FRAME`, or lift the cap; return the cap."""
        return self.frames.toggle_cap(CAPPED_FRAME)

    @staticmethod
    def _place(body: Body, position: Sequence[float],
               velocity: Sequence[float] = (0.0, 0.0, 0.0)) -> None:
        body.set_transform(translation=position, rotation=(0.0, 0.0, 1.0, 0.0))
        body.set_velocity(velocity)
        body.set_angular_velocity((0.0, 0.0, 0.0))
        body.wake()

    def door_height(self) -> float:
        """How high the middle of the door is, in metres."""
        return float(self.door.position[1])


def main() -> int:                              # pragma: no cover - needs a window
    """Open the yard in a window."""
    argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0]).parse_args()
    from OpenGLContext.contextdefinition import ContextDefinition
    from OpenGLContext.events import systemtime

    from OpenGLContext.context import Context as BaseContext

    class EventsContext(BaseContext):
        #: The yard is dressed in metallic/roughness materials.
        renderer = 'pbr'
        initialPosition = (0, 2.2, 9)

        def OnInit(self) -> None:
            self.yard = CollisionYard(self.physics, self.audio)
            self.sg = self.yard.scene()
            self.audio.mix = MASTER_GAIN
            for key, handler in (('d', self.OnDrop), ('l', self.OnLaunch),
                                 ('L', self.OnLaunchSlow),
                                 ('m', self.OnMend), (' ', self.OnFire),
                                 ('w', self.OnToggleWeight), ('c', self.OnCap)):
                if key.lower() != key:
                    self.addEventHandler(
                        'keypress',
                        name=key,
                        function=handler,
                        modifiers=(True, False, False),
                    )
                else:
                    self.addEventHandler('keypress', name=key, function=handler)
            self.yard.frames.step(systemtime.systemTime())
            print(__doc__, flush=True)

        def OnDrop(self, event: Any = None) -> None:
            """Handle a drop request"""
            self.yard.drop()

        def OnLaunchSlow(self, event: Any = None) -> None:
            """Trigger launch at 1m/s"""
            self.yard.launch(speed=1.0)

        def OnLaunch(self, event: Any = None) -> None:
            """Trigger launch at the full speed"""
            self.yard.launch()

        def OnMend(self, event: Any = None) -> None:
            """Fix up broken bits"""
            self.yard.mend()

        def OnToggleWeight(self, event: Any = None) -> None:
            """Trigger the pressure plate with the weight"""
            self.yard.toggle_weight()

        def OnFire(self, event: Any = None) -> None:
            platform = self.getViewPlatform()
            self.yard.fire(platform.position[:3], platform.forward())

        def OnCap(self, event: Any = None) -> None:
            cap = self.yard.toggle_cap()
            print('frame rate capped at 20 fps' if cap else 'frame rate uncapped',
                  flush=True)

        def OnIdle(self, *arguments: Any) -> int:
            """Hold the frame rate to the cap; the physics service steps the world."""
            frames = self.yard.frames
            time.sleep(frames.wait(systemtime.systemTime()))
            frames.step(systemtime.systemTime())
            return 1

    EventsContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext collision events', size=(1280, 720), physics=definition()))
    return 0


if __name__ == '__main__':                      # pragma: no cover
    sys.exit(main())
