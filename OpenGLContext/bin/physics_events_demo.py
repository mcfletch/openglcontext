#! /usr/bin/env python
"""Collision events: a yard where things are struck, and each strike calls the subscriber registered for it.

Walk around with the arrow keys and press the keys it prints:

    oglc-physics-events

    d      drop the crates; each landing thuds, louder the harder it lands
    l      launch a ball at each pane of glass
    L      launch them gently, too softly to break anything
    m      mend the glass
    space  fire the gun where you are looking; a crate it hits is knocked away
    w      put the weight on the pressure plate, or take it off
    c      cap the frame rate at 20 fps, or lift the cap

The left pane breaks after the solve: its subscriber reads how hard it was hit
and shatters it, and the ball has already bounced. The right pane breaks
before the solve: a contact filter lets the ball through, and the ball carries
on. The door opens while anything is on the plate. With the frame rate capped
every landing still thuds, because the physics world records every step.
docs/physics.rst describes each of these, and this file is the working code
for them.
"""
from __future__ import annotations

import argparse
import sys
import time
from functools import partial
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from omi_audio import model as audiomodel
from omi_audio import synth
from omi_audio.clip import DEFAULT_SAMPLE_RATE
from omi_physics import model
from omi_physics.contactevents import PairPreview, Verdict
from omi_physics.raycast import raycast

from OpenGLContext.physics.events import Collision
from OpenGLContext.physics.manager import PhysicsManager
from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.physicsbody import PhysicsBody

__all__ = ['CollisionYard', 'main']

STEP = 1.0 / 120.0
GRAVITY = model.Gravity(gravity=9.81, direction=(0, -1, 0))

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
#: The impulse a pane survives, in N·s.
PANE_STRENGTH = 6.0
#: Pieces a broken pane falls into, across and up.
FRAGMENT_GRID = (3, 2)
FRAGMENTS = FRAGMENT_GRID[0] * FRAGMENT_GRID[1]
BALL_RADIUS = 0.25
BALL_MASS = 2.0
#: How far in front of its pane a ball is launched from, and how fast.
LAUNCH_DISTANCE = 2.0
LAUNCH_SPEED = 8.0

#: The gun: how far it reaches, and the push and speed of a round.
GUN_RANGE = 60.0
GUN_IMPULSE = 15.0
GUN_SPEED = 400.0

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
        self.glass = PBRMaterial(baseColor=(0.75, 0.88, 0.95), metallic=0.0,
                                 roughness=0.04, transparency=0.6,
                                 alphaMode='BLEND', doubleSided=True)
        self.ball = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.STEEL, 0.15))
        self.plate = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.BRONZE, 0.4))
        self.door = surfaces.pbr_material(surfaces.plaster(256), relief=0.5)
        self.stone = surfaces.pbr_material(surfaces.sandstone(256))
        self.weight = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.GOLD, 0.25))


def _index(body: PhysicsBody) -> int:
    """The world index of a body the yard keeps for as long as it runs."""
    if body.index is None:
        raise ValueError('%r is not in the physics world' % (body,))
    return body.index


def _shape(geometry: Any, material: Any) -> Any:
    return basenodes.Shape(geometry=geometry,
                           appearance=basenodes.Appearance(material=material))


class CollisionYard:
    """The demo's world, its subscriptions and its sounds, with no GL and no window.

    The context puts :meth:`scene` in front of the camera, calls :meth:`step`
    once a frame and forwards key presses to :meth:`drop`, :meth:`launch`,
    :meth:`mend`, :meth:`fire`, :meth:`toggle_weight` and :meth:`toggle_cap`.
    """

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.manager = PhysicsManager(gravity=GRAVITY, fixed_dt=STEP)
        self.world = self.manager.world
        self.events = self.manager.events
        self.finish = Finishes()
        #: Everything the yard adds and takes away while it runs.
        self.root = basenodes.Group(children=[])
        self._materials = {
            'stone': self.world.add_material(model.Material(restitution=0.1)),
            'glass': self.world.add_material(model.Material(restitution=0.3)),
            'steel': self.world.add_material(model.Material(restitution=0.5)),
        }
        # The shards of a pane do not deflect the ball that broke it: a ball let
        # through before the solve is still passing the place they appear.
        self._filters = {
            'ball': self.world.add_filter(model.CollisionFilter(collisionSystems=('ball',))),
            'shard': self.world.add_filter(model.CollisionFilter(
                collisionSystems=('shard',), notCollideWithSystems=('ball',))),
        }
        self.frame_cap: Optional[float] = None
        self.sounds: List[Tuple[str, np.ndarray, float]] = []

        self._box((30.0, 1.0, 30.0), (0.0, -0.5, 0.0), self.finish.floor,
                  model.STATIC, material='stone')
        self.crates = [
            self._box((CRATE_SIZE,) * 3, (x, CRATE_SIZE / 2, z), finish, model.DYNAMIC,
                      mass=20.0)
            for (x, z), finish in zip(CRATE_SPOTS, self.finish.crates)]
        self.balls = {name: self._ball(name) for name in PANE_X}
        self.panes: Dict[str, PhysicsBody] = {}
        self.broken: Set[str] = set()
        self.fragments: List[PhysicsBody] = []
        self.plate = self._plate()
        self.weight = self._box((0.7, 0.7, 0.7), WEIGHT_PARKED, self.finish.weight,
                                model.DYNAMIC, mass=40.0)
        self.door = self._box(DOOR_SIZE, DOOR_CENTRE, self.finish.door, model.KINEMATIC)
        for x in PANE_X.values():
            self._frame(x, PANE_Z, PANE_SIZE[0], PANE_SIZE[1])
        self._frame(DOOR_CENTRE[0], DOOR_CENTRE[2], DOOR_SIZE[0],
                    DOOR_SIZE[1] + DOOR_TRAVEL)
        self._on_plate: Set[Any] = set()

        self.events.subscribe(self._thud, body=self.crates + list(self.balls.values()),
                              phases=('begin', 'persist'), above=IMPACT_FLOOR)
        self.events.subscribe(self._struck, body=self.crates, kinds=('hit',))
        self.events.subscribe(self._on_plate_changed, body=self.plate,
                              kinds=('trigger',), phases=('enter', 'exit'))
        self.world.set_contact_filter(self._verdict)
        self.mend()

        self.clips = {
            'thud': synth.rumble(0.3, sample_rate=sample_rate, decay=16.0, cutoff=320.0,
                                 pitch=95.0, pitch_end=50.0, tone=0.5, drive=2.0, seed=3),
            'ping': synth.impact(0.12, sample_rate=sample_rate, seed=9),
            'shatter': synth.noise(0.5, sample_rate=sample_rate, amplitude=0.5, seed=13),
        }
        self.placed = audiomodel.AudioEmitter(positional=audiomodel.PositionalProperties(
            refDistance=3.0, rolloffFactor=0.8))

    # -- building ------------------------------------------------------------
    def _box(self, size: Sequence[float], position: Sequence[float], finish: Any,
             motion_type: str, mass: float = 1.0, material: str = 'stone',
             collision_filter: int = -1) -> PhysicsBody:
        shape = self.world.add_shape(model.Shape.box(tuple(size)))
        transform = basenodes.Transform(translation=tuple(position), children=[
            _shape(basenodes.Box(size=tuple(size)), finish)])
        return self._add(transform, model.Motion(type=motion_type, mass=mass),
                         model.Collider(shape=shape,
                                        physicsMaterial=self._materials[material],
                                        collisionFilter=collision_filter))

    def _ball(self, name: str) -> PhysicsBody:
        shape = self.world.add_shape(model.Shape.sphere(BALL_RADIUS))
        transform = basenodes.Transform(
            translation=(PANE_X[name], BALL_RADIUS, PANE_Z + LAUNCH_DISTANCE + 1.0),
            children=[_shape(basenodes.Sphere(radius=BALL_RADIUS), self.finish.ball)])
        return self._add(transform, model.Motion(type=model.DYNAMIC, mass=BALL_MASS),
                         model.Collider(shape=shape, physicsMaterial=self._materials['steel'],
                                        collisionFilter=self._filters['ball']))

    def _frame(self, x: float, z: float, width: float, height: float) -> None:
        """Two stone posts and a lintel around an opening ``width`` by ``height``."""
        post = 0.25
        for side in (-1.0, 1.0):
            self._box((post, height + post, post),
                      (x + side * (width + post) / 2, (height + post) / 2, z),
                      self.finish.stone, model.STATIC)
        self._box((width + 2 * post, post, post), (x, height + post / 2, z),
                  self.finish.stone, model.STATIC)

    def _plate(self) -> PhysicsBody:
        x, y, z = PLATE_CENTRE
        width, height, depth = PLATE_SIZE
        self.root.children.append(basenodes.Transform(
            translation=(x, 0.02, z),
            children=[_shape(basenodes.Box(size=(width, 0.04, depth)), self.finish.plate)]))
        shape = self.world.add_shape(model.Shape.box(PLATE_SIZE))
        transform = basenodes.Transform(translation=(x, y + height / 2, z))
        return self._add(transform, model.Motion(type=model.STATIC),
                         trigger=model.Trigger(shape=shape))

    def _add(self, transform: Any, motion: model.Motion, collider: Any = None,
             trigger: Any = None) -> PhysicsBody:
        body: PhysicsBody = self.manager.add(PhysicsBody(transform, motion, collider, trigger))
        self.root.children.append(transform)
        return body

    def _discard(self, body: PhysicsBody) -> None:
        self.manager.remove(body)
        if body.transform in self.root.children:
            self.root.children.remove(body.transform)

    def scene(self) -> Any:
        """The scenegraph: a light, a sky and everything in the yard."""
        return basenodes.sceneGraph(children=[
            basenodes.DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=1.0),
            basenodes.DirectionalLight(direction=(0.5, -0.3, 0.8), intensity=0.35),
            self.root,
            basenodes.SimpleBackground(color=(0.55, 0.62, 0.72)),
        ])

    # -- the collision subscribers -------------------------------------------
    def _thud(self, hit: Collision) -> None:
        self.sounds.append(('thud', hit.point, min(1.0, hit.approach / IMPACT_FULL)))

    def _struck(self, hit: Collision) -> None:
        self.sounds.append(('ping', hit.point, 0.8))

    def _pane_struck(self, name: str, hit: Collision) -> None:
        """Shatter a pane the blow was too much for.

        The ``after`` pane reads the impulse the solver applied. The
        ``before`` pane was let through by :meth:`_verdict`, so its begin
        arrives unsolved.
        """
        breaks = hit.impulse > PANE_STRENGTH if name == 'after' else not hit.solved
        if breaks and name not in self.broken:
            self._shatter(name, hit.point, hit.normal)

    def _verdict(self, pair: PairPreview) -> Verdict:
        """Let a ball through the ``before`` pane when the blow would break it."""
        pane = self.panes.get('before')
        if (pane is not None and pane.index in (pair.a.index, pair.b.index)
                and pair.impulse > PANE_STRENGTH):
            return Verdict.IGNORE_PAIR
        return Verdict.SOLVE

    def _on_plate_changed(self, hit: Collision) -> None:
        if hit.phase == 'enter':
            self._on_plate.add(hit.other)
        else:
            self._on_plate.discard(hit.other)

    @property
    def plate_pressed(self) -> bool:
        """Whether anything is standing on the pressure plate."""
        return bool(self._on_plate)

    # -- the panes ------------------------------------------------------------
    def _shatter(self, name: str, point: np.ndarray, push: np.ndarray) -> None:
        """Replace pane ``name`` with the pieces it broke into, pushed along ``push``."""
        pane = self.panes.pop(name)
        self._discard(pane)
        self.broken.add(name)
        self.sounds.append(('shatter', point, 1.0))
        columns, rows = FRAGMENT_GRID
        width, height, depth = PANE_SIZE
        piece = (width / columns, height / rows, depth)
        x0, z0 = PANE_X[name], PANE_Z
        for column in range(columns):
            for row in range(rows):
                centre = (x0 - width / 2 + piece[0] * (column + 0.5),
                          piece[1] * (row + 0.5), z0)
                fragment = self._box(piece, centre, self.finish.glass, model.DYNAMIC,
                                     mass=0.5, material='glass',
                                     collision_filter=self._filters['shard'])
                self.world.linear_velocity[fragment.index] = 1.5 * np.asarray(push)
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
                             model.STATIC, material='glass')
            self.events.subscribe(partial(self._pane_struck, name), body=pane)
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

    def fire(self, origin: Sequence[float], direction: Sequence[float]) -> Any:
        """Fire the gun from ``origin`` along ``direction``; return the body it hit, or None."""
        hit = raycast(self.world, origin, direction, max_distance=GUN_RANGE)
        if hit is None:
            return None
        self.events.report_hit(hit, direction=direction, impulse=GUN_IMPULSE,
                               speed=GUN_SPEED, payload='rifle')
        return self.manager.handle(self.world.ref(hit.body))

    def toggle_weight(self) -> None:
        """Drop the weight onto the plate, or put it back where it was parked."""
        x, _y, z = PLATE_CENTRE
        on_plate = abs(self.world.position[self.weight.index][0] - x) < 1.0
        self._place(self.weight, WEIGHT_PARKED if on_plate else (x, 1.5, z))

    def toggle_cap(self) -> Optional[float]:
        """Cap the frame time at :data:`CAPPED_FRAME`, or lift the cap; return the cap."""
        self.frame_cap = None if self.frame_cap else CAPPED_FRAME
        return self.frame_cap

    def _place(self, body: PhysicsBody, position: Sequence[float],
               velocity: Sequence[float] = (0.0, 0.0, 0.0)) -> None:
        index = _index(body)
        world = self.world
        world.place_body(index, position=position, orientation=(0, 0, 0, 1))
        world.linear_velocity[index] = velocity
        world.angular_velocity[index] = 0.0
        world.wake(index)

    # -- the frame ----------------------------------------------------------------
    def door_height(self) -> float:
        """How high the middle of the door is, in metres."""
        return float(self.world.position[self.door.index][1])

    def _drive_door(self, dt: float) -> None:
        """Move the door towards open or shut, stopping exactly at either."""
        target = DOOR_CENTRE[1] + (DOOR_TRAVEL if self.plate_pressed else 0.0)
        height = self.door_height()
        gap = target - height
        speed = 0.0 if abs(gap) < 1e-6 else float(np.sign(gap)) * DOOR_SPEED
        if abs(gap) <= DOOR_SPEED * dt:
            x, _y, z = DOOR_CENTRE
            self.world.place_body(_index(self.door), position=(x, target, z))
            speed = 0.0
        self.world.linear_velocity[self.door.index] = (0.0, speed, 0.0)

    def step(self, dt: float, engine: Any) -> List[str]:
        """Advance the yard by ``dt`` seconds and play what was struck; return the sounds' names."""
        self._drive_door(dt)
        self.manager.advance(dt)
        sounds, self.sounds = self.sounds, []
        if engine is not None:
            for name, point, gain in sounds:
                engine.play(self.clips[name], emitter=self.placed, position=point,
                            gain=gain, priority=0.4)
        return [name for name, _point, _gain in sounds]


def main() -> int:                              # pragma: no cover - needs a window
    """Open the yard in a window."""
    import os
    # The yard is dressed in metallic/roughness materials, which the PBR pass draws.
    os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
    argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0]).parse_args()
    from OpenGLContext import testingcontext
    from OpenGLContext.audio import scene as audioscene
    from OpenGLContext.contextdefinition import ContextDefinition

    base: Any = testingcontext.getInteractive()

    class EventsContext(base):
        initialPosition = (0, 2.2, 9)

        def OnInit(self) -> None:
            self.yard = CollisionYard()
            self.sg = self.yard.scene()
            engine = audioscene.engine_for(self)
            if engine is not None:
                engine.master_gain = MASTER_GAIN
            for key, handler in (('d', self.yard.drop), ('l', self.yard.launch),
                                 ('L', lambda: self.yard.launch(speed=1.0)),
                                 ('m', self.yard.mend), (' ', self.OnFire),
                                 ('w', self.yard.toggle_weight), ('c', self.OnCap)):
                self.addEventHandler('keypress', name=key,
                                     function=lambda event, handler=handler: handler())
            self._last = time.time()
            print(__doc__, flush=True)

        def OnFire(self) -> None:
            platform = self.getViewPlatform()
            forward = platform.quaternion * [0.0, 0.0, -1.0, 0.0]
            self.yard.fire(platform.position[:3], forward[:3])

        def OnCap(self) -> None:
            cap = self.yard.toggle_cap()
            print('frame rate capped at 20 fps' if cap else 'frame rate uncapped',
                  flush=True)

        def OnIdle(self, *args: Any) -> int:
            cap = self.yard.frame_cap
            if cap:
                time.sleep(max(0.0, cap - (time.time() - self._last)))
            now = time.time()
            dt, self._last = min(now - self._last, 0.1), now
            self.yard.step(dt, audioscene.existing_engine(self))
            self.triggerRedraw(1)
            return 1

    EventsContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext collision events', size=(1280, 720)))
    return 0


if __name__ == '__main__':                      # pragma: no cover
    sys.exit(main())
