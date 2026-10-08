#! /usr/bin/env python
'''=Creating a Game with the Physics Engine=

[using_physics.py-screen-0001.png Screenshot]

This tutorial walks through the process of creating a game using the 
OpenGLContext renderer and the omi_physics engine for simulating a 
physical environment.

As with any game, the first question is what we're going to build.
To keep it simple, we'll use a classic game that's been available
on computers since the early 80s. It's a canon game where you try
to hit a target on a platform by controlling your canon's bearing,
elevation and power.

Most of the code in this tutorial is about the game itself, since 
the rendering and physics are handled by the engine.

We'll create a class that models the Game itself, it's responsible
for tracking the Game's attempts, win state, loss state, and 
generating the (randomised) worlds. We'll use the :py:mod:`OpenGLContext.surfaces` 
module to generate simple cartoonish structures for the game.

The rules are approximately these:

* two random platforms are created, one with a canon, one with a target
* the player adjusts the bearing, elevation and power of the canon
* the player hits space to fire the cannon
* if the player fires more than 10 shots without hitting the target, they lose
* if the player hits the target within the 10 shots, they win

When the player wins, we display a "wash" over the screen and a
space causes the next game to play.
'''
from __future__ import annotations

import functools
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy
from omi_audio import model as audiomodel
from omi_audio import synth
from omi_audio.clip import Clip
from omi_physics import model

''':py:mod:`OpenGLContext.entropy` provides a random number generator that shares
the world's seed, that allows test suites to test the random value
by using the same seed on each test run.'''
from OpenGLContext import entropy
'''The audio scene will allow us to to play a canon's roar when the canon fires'''
from OpenGLContext.audio import scene as audioscene
'''For this game, perspective views alone don't work very well, so we'll use
the MultiViewContext to provide a 4-tile view with overhead, front, side and
perspective views of the same scene.'''
from OpenGLContext.context import MultiViewContext as BaseContext
''':py:mod:`OpenGLContext.events.systemtime` is the internal timer, the thing
that Timer and TimeSensors use to set the actual time for the simulation'''
from OpenGLContext.events import systemtime
from OpenGLContext.events.timer import Timer
from OpenGLContext.physics.manager import PhysicsManager
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Coordinate, DirectionalLight, IndexedLineSet, Material,
    Shape, Transform, Viewpoint, sceneGraph,
)
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.nodepath import NodePath
from OpenGLContext.scenegraph.physicsbody import PhysicsBody
from OpenGLContext.ui.hudwidgets import HUDLayer, ScreenWash, TextBlock
from OpenGLContext.viewer.environment import sky_background

'''A 4-tile layout view means that the on-screen items are about 1/4 of normal
size, so we'll make the window larger than we normally do for a demo.'''
#: The window is larger than most of these scripts', since it holds four views.
SIZE = (900, 700)

'''Game parameters are just regular python variables. We have a lot of knobs
we can tweak to change the gameplay or the presentation of the game.'''
#: Radius (metres) and mass (kilograms) of the ball, and the distance from the
#: barrel's pivot to its mouth.
BALL_RADIUS = 0.3
BALL_MASS = 5.0
BARREL = 2.0

#: Half the width of each tower, in metres.  The target is small: at forty
#: metres it is under two degrees across.
CANNON_HALF, TARGET_HALF = 2.0, 1.25

#: Seconds the world advances in one step.  A ball at full power crosses
#: less than its own radius in a step, so it cannot pass through a surface.
STEP = 1.0 / 240.0

#: Where the camera sits in the barrel's frame: behind the pivot, above the
#: barrel, and 0.3 m to its right so the barrel is not between the camera and a
#: target it is aimed at.
EYE = (-1.0, 0.8, 0.3)

#: How far the target's trigger slab stands over the top of the tower and how
#: far it reaches down into it, in metres.  The ball is in it when its surface
#: is within PAD_ABOVE of the top, so a ball that passes higher over the target
#: is a miss; the depth lets one that arrives hard still be inside it.
PAD_ABOVE, PAD_DEPTH = 0.05, 0.30

#: Shots a course allows before it is lost.
MAX_SHOTS = 10

#: The longest a shot is followed, in seconds, and how far below the ground
#: a ball may fall before the shot is over.
LONGEST = 40.0
FALLEN = -10.0

#: What one key press changes: degrees of bearing and elevation, and metres per
#: second of power.
TURN, RAISE, PUSH = 0.2, 0.2, 0.2

#: How far the aim may be moved: bearing either side of straight ahead and the
#: elevation, in degrees, and the power in metres per second.
BEARING_LIMIT = (-60.0, 60.0)
ELEVATION_LIMIT = (-10.0, 85.0)
POWER_LIMIT = (5.0, 40.0)

#: The colours of the screen wash for a win and for a lost game, and how solid
#: it is: the world still shows through.
WIN_WASH, LOSE_WASH, WASH_STRENGTH = (0.1, 0.8, 0.2), (0.85, 0.1, 0.1), 0.4

'''Defines our control scheme. Here we use the three left-most columns of the
US keyboard layout's alphabetic keys, each column being an up/down pair for
a particular field.'''

#: What each aiming key changes.
AIM_KEYS = {
    'q': dict(bearing=TURN), 'a': dict(bearing=-TURN),
    'w': dict(elevation=RAISE), 's': dict(elevation=-RAISE),
    'e': dict(power=PUSH), 'd': dict(power=-PUSH),
}

'''World geometry created as PBR material compatible objects with procedural textures.'''
@functools.cache
def looks() -> dict[str, Any]:
    """The surfaces the game is drawn in, made once: no GL is needed to make them."""
    return {
        'ground': surfaces.pbr_material(surfaces.sandstone(256)),
        'cannon': surfaces.pbr_material(surfaces.brick(256)),
        'target': surfaces.pbr_material(surfaces.checkered_marble(256, tiles=2)),
        'mark': PhysicalMaterial(baseColor=(0.8, 0.08, 0.06), metallic=0.0, roughness=0.5),
        'steel': PhysicalMaterial(baseColor=surfaces.STEEL, metallic=1.0, roughness=0.25),
        'bronze': PhysicalMaterial(baseColor=surfaces.BRONZE, metallic=1.0, roughness=0.35),
    }

'''Model a single platform as to where it is and how large it is.'''
@dataclass(frozen=True)
class Platform:
    """A square tower: centre on the ground plane, height and half its width."""

    x: float
    z: float
    top: float
    half: float


class Report:
    """The sound of the cannon firing, made from arithmetic.

    '''=The report=

    `omi_audio.synth` makes sounds with no files: `rumble` is noise with the
    top taken off over a falling tone, which is what a detonation is, and
    `reverberated` puts the tail of an open field behind it.  The clip is made
    once, and each shot plays it from the muzzle through an emitter, so it is
    placed in the stereo field and falls off with the distance from the
    camera.'''
    """

    def __init__(self, sample_rate: int | None = None) -> None:
        options = {} if sample_rate is None else {'sample_rate': sample_rate}
        boom = synth.rumble(0.9, decay=7.0, cutoff=600.0, tilt=-6.0, pitch=90.0,
                            pitch_end=40.0, tone=0.2, drive=3.0, seed=21, **options)
        self.clip: Clip = synth.reverberated(boom, seconds=0.9, level=0.35, seed=5)
        self.emitter = audiomodel.AudioEmitter(positional=audiomodel.PositionalProperties(
            refDistance=3.0, rolloffFactor=0.8))

    def play(self, engine: Any, position: Any) -> Any:
        """Start the report at ``position``; None where there is no engine to play it."""
        if engine is None:
            return None
        return engine.play(self.clip, emitter=self.emitter,
                           position=tuple(float(part) for part in position),
                           gain=1.0, priority=1.0)


@dataclass
class Aim:
    """Where the cannon points and how hard it fires."""

    bearing: float = 0.0
    elevation: float = 20.0
    power: float = 10.0

    def adjust(self, bearing: float = 0.0, elevation: float = 0.0,
               power: float = 0.0) -> None:
        self.bearing = min(max(self.bearing + bearing, BEARING_LIMIT[0]), BEARING_LIMIT[1])
        self.elevation = min(max(self.elevation + elevation, ELEVATION_LIMIT[0]),
                             ELEVATION_LIMIT[1])
        self.power = min(max(self.power + power, POWER_LIMIT[0]), POWER_LIMIT[1])


class Cannon:
    """The cannon as scene nodes, each in the frame of the one above it.

    ``turn`` stands on the tower and is rotated about the vertical by the
    bearing.  ``tilt`` is inside it, rotated about the barrel's own side axis
    by the elevation.  The barrel runs along ``tilt``'s +x, and ``eye``, a
    `Viewpoint` behind and above it, is in the same frame, so the camera turns
    and tilts with the barrel.  Nothing is worked out from the angles: a point
    or a direction in the barrel's frame is carried to the world by the
    transform matrix of the path down to ``tilt``.
    """

    def __init__(self, position: tuple[float, float, float], look: dict[str, Any]) -> None:
        self.base = surfaces.shape(
            surfaces.block((1.4, 0.9, 1.4)), look['bronze'],
            translation=(position[0], position[1] - 0.45, position[2]))
        self.eye = Viewpoint(position=EYE, orientation=(0, 1, 0, -math.pi / 2),
                             description='Cannon')
        self.tilt = Transform(children=[
            surfaces.shape(barrel(), look['bronze'], translation=(BARREL / 2.0, 0, 0),
                           rotation=(0, 0, 1, -math.pi / 2)),
            self.eye,
        ])
        self.turn = Transform(translation=position, children=[self.tilt])
        #: The paths down to the barrel and to the eye.  A path keeps its matrix
        #: until a transform above it changes, so each is made once and kept.
        self.barrel_path = NodePath([self.turn, self.tilt])
        self.eye_path = NodePath([self.turn, self.tilt, self.eye])

    @property
    def nodes(self) -> list[Any]:
        return [self.base, self.turn]

    def aim(self, bearing: float, elevation: float) -> None:
        """Turn the cannon: bearing about the vertical, elevation inside that."""
        self.turn.rotation = (0, 1, 0, math.radians(bearing))
        self.tilt.rotation = (0, 0, 1, math.radians(elevation))

    def to_world(self, local: tuple[float, float, float], point: bool = True) -> Any:
        """A point (or, with ``point=False``, a direction) in the barrel's frame, in the world's."""
        matrix = self.barrel_path.transformMatrix()
        return numpy.dot([*local, 1.0 if point else 0.0], matrix)[:3]

    @property
    def muzzle(self) -> Any:
        """The centre of the mouth of the barrel, in the world."""
        return self.to_world((BARREL, 0.0, 0.0))

    @property
    def along(self) -> Any:
        """The unit vector the barrel points along, in the world."""
        return self.to_world((1.0, 0.0, 0.0), point=False)

    def look_through(self, context: Any) -> None:
        """Put the window's camera where the eye is, looking where it looks."""
        self.eye.moveTo(self.eye_path, context)


@dataclass
class Course:
    """The world the game is played in: scene nodes and where the towers are.

    Nothing here is physical.  It is geometry, drawn like any scene, and it is
    the same whether anything is going to collide with it or not.
    """

    cannon: Platform
    target: Platform
    #: What the ball collides with: the ground and the two towers.
    solids: list[Any]
    #: What is drawn and not collided with: the mark on the target, and the cannon.
    decor: list[Any]
    #: The slab round the target's top.  It is not drawn.
    pad: Any
    gun: Cannon

    @property
    def nodes(self) -> list[Any]:
        """Everything drawn."""
        return self.solids + self.decor

    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """``(minimum, maximum)``, the box round the towers and the sky over them."""
        high = max(self.cannon.top, self.target.top) + 25.0
        reach = max(self.cannon.half, self.target.half) + 6.0
        low_x = min(self.cannon.x, self.target.x) - reach
        high_x = max(self.cannon.x, self.target.x) + reach
        low_z = min(self.cannon.z, self.target.z) - reach
        high_z = max(self.cannon.z, self.target.z) + reach
        return ((low_x, 0.0, low_z), (high_x, high, high_z))


def build_course(rng: Any, look: dict[str, Any]) -> Course:
    """Two towers at random heights, distances and offsets across the line."""
    '''=The world=

    A tower is a `Transform` holding a box of brick or marble, and the ground
    is a wide, thin box of sand.  `surfaces.block` makes the geometry and
    `surfaces.shape` puts a material on it and places it.  The target has a
    red mark on its top and, round the top of the tower, a thin slab that is
    never drawn: it stands PAD_ABOVE over the top and reaches PAD_DEPTH down
    into the tower, and it is where the ball has to be.  The cannon is nodes too, one
    frame of reference inside another (see `Cannon`).  This is the whole
    world, and it has no physics in it yet.'''
    cannon = Platform(rng.uniform(-35, -20), rng.uniform(-10, 10),
                      rng.uniform(2.0, 5.0), CANNON_HALF)
    target = Platform(rng.uniform(20, 35), rng.uniform(-10, 10),
                      rng.uniform(1.0, 8.0), TARGET_HALF)
    ground = surfaces.shape(surfaces.block((400.0, 1.0, 400.0), repeat=4.0),
                            look['ground'], translation=(0, -0.5, 0))
    cannon_tower = surfaces.shape(
        surfaces.block((cannon.half * 2, cannon.top, cannon.half * 2), repeat=2.0),
        look['cannon'], translation=(cannon.x, cannon.top / 2.0, cannon.z))
    target_tower = surfaces.shape(
        surfaces.block((target.half * 2, target.top, target.half * 2), repeat=2.0),
        look['target'], translation=(target.x, target.top / 2.0, target.z))
    mark = surfaces.shape(
        surfaces.block((target.half * 1.6, 0.06, target.half * 1.6)), look['mark'],
        translation=(target.x, target.top + 0.03, target.z))
    pad = surfaces.shape(
        surfaces.block((target.half * 2, PAD_ABOVE + PAD_DEPTH, target.half * 2)),
        look['mark'],
        translation=(target.x, target.top + (PAD_ABOVE - PAD_DEPTH) / 2.0, target.z))
    gun = Cannon((cannon.x, cannon.top + 0.9, cannon.z), look)
    return Course(cannon, target, [ground, cannon_tower, target_tower], [mark, *gun.nodes], pad, gun)


class Game:
    """The rules, over a physics world: a course, the aim, and a ball in flight or not.

    ``state`` is ``aiming`` until the cannon fires, ``flying`` while the ball
    is in the air, then ``aiming`` again after a miss, ``won`` after a hit, or
    ``lost`` when the last of ``MAX_SHOTS`` has missed.  Firing from ``won`` or
    ``lost`` starts the next course.
    Nothing here draws or reads a clock: `tick` is given the seconds that have
    passed.

    The world's events decide the game.  ``on_success()`` is called when the
    physics reports the ball in the target, ``on_failure()`` when it reports the
    ball touching anything else, and ``on_game_over()`` after the failure that
    used the last shot.
    """

    def __init__(self, rng: Any = None,
                 on_success: Callable[[], None] | None = None,
                 on_failure: Callable[[], None] | None = None,
                 on_game_over: Callable[[], None] | None = None) -> None:
        self.rng = rng or entropy.randomizer('cannon')
        self.look = looks()
        self.on_success = on_success or (lambda: None)
        self.on_failure = on_failure or (lambda: None)
        self.on_game_over = on_game_over or (lambda: None)
        self.aim = Aim()
        self.new_course()

    def new_course(self) -> None:
        """Build a course, and a physics world for it, ready to go."""
        self.course = build_course(self.rng, self.look)
        self.state = 'aiming'
        self.shots = 0
        self.ball: PhysicsBody | None = None
        self.subscription: Any = None
        self.elapsed = 0.0
        self.point()
        self.wire_up_physics()

    def wire_up_physics(self) -> None:
        '''=Wiring up the physics=

        The world is built and the physics is told about it afterwards.  A
        `PhysicsManager` holds the simulation and writes each body's pose
        onto the `Transform` it is bound to.  Gravity is the OMI gravity
        model: 9.81 metres per second squared, downward.  Its default linear
        damping is a drag that settles scenes; a cannon-ball has none, so it
        is switched off.

        `attach` makes a node a physics body.  It cooks the collision shape
        from the geometry the node draws, binds the body to the node, and
        returns the `PhysicsBody`.  `strategy='primitive'` asks for the box or
        sphere the geometry fits, which the solver has exact tests for.  With
        no `motion` the body is static: everything else collides with it and
        it never moves.'''
        course = self.course
        self.manager = PhysicsManager(
            gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)),
            default_linear_damping=0.0, fixed_dt=STEP)
        self.world = self.manager.world
        for node in course.solids:
            self.manager.attach(node, material='wood', strategy='primitive')
        '''=A trigger=

        With `trigger=True` the geometry becomes a trigger instead: it stops
        nothing and reports what enters it.  The slab round the target's top is
        one, so a ball that lands on the target is inside it, and the game
        subscribes to its `enter` events.'''
        self.pad = self.manager.attach(course.pad, trigger=True, strategy='primitive')
        self.manager.events.subscribe(self._entered, body=self.pad,
                                      kinds=('trigger',), phases=('enter',))

    @property
    def cannon(self) -> Platform:
        return self.course.cannon

    @property
    def target(self) -> Platform:
        return self.course.target

    @property
    def muzzle(self) -> tuple[float, ...]:
        """The centre of the mouth of the barrel."""
        return tuple(float(part) for part in self.course.gun.muzzle)

    def point(self) -> None:
        """Turn the cannon's nodes to the aim."""
        self.course.gun.aim(self.aim.bearing, self.aim.elevation)

    @property
    def position(self) -> tuple[float, ...]:
        """Where the ball is: in the world, or in the mouth of the barrel."""
        if self.ball is None or self.ball.index is None:
            return self.muzzle
        return tuple(float(part) for part in self.world.position[self.ball.index])

    def adjust(self, **change: float) -> None:
        """Move the aim, unless a ball is in the air."""
        if self.state != 'flying':
            self.aim.adjust(**change)
            self.point()

    @property
    def shots_left(self) -> int:
        return MAX_SHOTS - self.shots

    def fire(self) -> None:
        """Send the ball; after a win or a loss, build a new course instead."""
        if self.state in ('won', 'lost'):
            self.new_course()
        elif self.state == 'aiming':
            self.release()
            '''=Go=

            The ball is a sphere of steel, a node like the towers, attached
            as a dynamic body at the mouth of the barrel, standing still.
            `apply_impulse` adds an impulse in newton seconds, and the body's
            velocity becomes impulse over mass: the mass times the power,
            along the barrel.  After that the script only advances the
            simulation.'''
            node = surfaces.shape(surfaces.sphere(BALL_RADIUS), self.look['steel'],
                                  translation=self.muzzle)
            self.ball = self.manager.attach(
                node, model.Motion(type=model.DYNAMIC, mass=BALL_MASS),
                material='metal', strategy='primitive')
            '''The impulse is the power along the barrel's own axis, carried
            into the world by the cannon's frame of reference.'''
            kick = BALL_MASS * self.aim.power * self.course.gun.along
            assert self.ball.index is not None
            self.world.apply_impulse(self.ball.index, tuple(float(part) for part in kick))
            '''=What the ball touched=

            A subscription to the ball's own contacts hears each time it
            touches another body.  The ground, a tower, or the side of the
            target are all a miss; the trigger over the target's top is the
            hit, and it is a different kind of event.'''
            self.subscription = self.manager.events.subscribe(
                self._touched, body=self.ball, phases=('begin',))
            self.state = 'flying'
            self.shots += 1
            self.elapsed = 0.0

    def release(self) -> None:
        """Take the last ball out of the world."""
        if self.subscription is not None:
            self.subscription.cancel()
            self.subscription = None
        if self.ball is not None:
            self.manager.remove(self.ball)
            self.ball = None

    def _entered(self, event: Any) -> None:
        """The physics reports the ball inside the trigger over the target: success."""
        if self.state == 'flying' and event.other is self.ball:
            self._finish(hit=True)

    def _touched(self, event: Any) -> None:
        """The physics reports the ball touching something solid: failure."""
        if self.state == 'flying':
            self._finish(hit=False)

    def _finish(self, hit: bool) -> None:
        if hit:
            self.state = 'won'
            self.on_success()
            return
        self.state = 'lost' if self.shots >= MAX_SHOTS else 'aiming'
        self.on_failure()
        if self.state == 'lost':
            self.on_game_over()

    def tick(self, seconds: float) -> None:
        """Run the world ``seconds`` further; the events arrive as it runs."""
        self.manager.advance(seconds)
        if self.state != 'flying':
            return
        self.elapsed += seconds
        if self.position[1] < FALLEN or self.elapsed > LONGEST:
            self._finish(hit=False)


class TestContext(BaseContext):
    def OnInit(self):
        '''The rules are a `Game`, which makes the nodes its bodies are bound
        to; the context puts them in the scene and keeps the scene in step.'''
        BaseContext.OnInit(self)
        steel = looks()['steel']
        '''=Bodies and their nodes=

        A body is bound to a `Transform` and the world writes its pose onto
        it, so what is drawn is whatever is under that transform.  The course
        is a group the game's static nodes go in, and the ball in flight goes
        in another.'''
        self.scenery = Transform()
        self.shot = Transform()
        self.loaded = surfaces.shape(surfaces.sphere(BALL_RADIUS), steel)
        self.waiting = list(self.loaded.children)
        self.trail = Coordinate(point=[(0, 0, 0), (0, 0, 0)])
        self.line = IndexedLineSet(coord=self.trail, coordIndex=[0, 1, -1])
        self.sg = sceneGraph(children=[
            sky_background(),
            DirectionalLight(direction=(-0.4, -0.8, -0.5)),
            self.scenery, self.loaded, self.shot,
            Shape(geometry=self.line, appearance=Appearance(
                material=Material(emissiveColor=(1.0, 0.8, 0.2), diffuseColor=(0, 0, 0)))),
        ])
        '''=A wash=

        A `ScreenWash` is a colour over the whole window, and its `strength`
        is how solid.  It is the first child of the layer so the text is drawn
        over it.  It is off at strength 0, and the success and game-over
        handlers set its colour and turn it up.'''
        self.wash = ScreenWash(strength=0.0)
        self.readout = TextBlock(anchor='bottom-right', align='right', lines=[])
        self.addHUDLayer(HUDLayer(children=[self.wash, self.readout]))
        '''=Sound=

        `engine_for` is the context's audio engine, opened on first ask, or
        None where the definition has audio switched off, and a `Report`
        played into None does nothing.'''
        self.engine = audioscene.engine_for(self)
        self.report = Report()
        self.message = 'Aim, then fire with the space bar.'
        self.game = Game(on_success=self.OnSuccess, on_failure=self.OnFailure,
                         on_game_over=self.OnGameOver)
        self.lay_out()
        for name in AIM_KEYS:
            self.addEventHandler('keypress', name=name, function=self.OnAim)
        self.addEventHandler('keypress', name=' ', function=self.OnFire)
        '''=The clock=

        The timer repeats, and `fraction` arrives every frame.  The world is
        advanced by the time since the last frame, from the engine's own
        clock, so a capture that steps the clock steps the ball with it.
        `advance` runs as many fixed steps as that time holds.'''
        self.timer = Timer(duration=1.0, repeating=1)
        self.timer.addEventHandler('fraction', self.OnFraction)
        self.timer.register(self)
        self.timer.start()
        self.last = systemtime.systemTime()
        self.update()
        print(__doc__)

    def lay_out(self):
        '''Put the course's nodes in the scene and the cannon on its tower.
        Runs for the first course and every one after it.'''
        game = self.game
        self.scenery.children = list(game.course.nodes)
        self.shot.children = []
        self.trail.point = [game.muzzle, game.muzzle]
        self.line.coordIndex = [0, 1, -1]
        self.update()

    def setupViews(self):
        '''A `MultiViewContext` shows the plan, the front and the left
        elevation in orthographic views and, in the fourth, what the window's
        camera sees, which here is a camera placed behind the barrel.  The
        three elevations are fitted to the box round the towers.'''
        self.startViews(arrangement='quad', bounds=lambda: self.game.course.bounds())

    def OnAim(self, event):
        self.game.adjust(**AIM_KEYS[event.name])
        self.message = ''
        self.update()

    def OnSuccess(self):
        '''The physics world reported the ball inside the target: green.'''
        self.message = 'Direct hit!  Space for a new course.'
        self.wash.colour = WIN_WASH
        self.wash.strength = WASH_STRENGTH

    def OnFailure(self):
        '''The physics world reported the ball touching anything else.'''
        self.message = 'Missed.'

    def OnGameOver(self):
        '''The last shot missed: red, until space starts the next course.'''
        self.message = 'Missed.  Out of shots.  Space for a new course.'
        self.wash.colour = LOSE_WASH
        self.wash.strength = WASH_STRENGTH

    def OnFire(self, event):
        was = self.game.state
        self.wash.strength = 0.0
        '''A new course makes its nodes and bodies afresh, so what is left is
        to put the new nodes in the scene.'''
        self.message = ''
        self.game.fire()
        if was in ('won', 'lost'):
            self.lay_out()
            self.frameViews()
        elif self.game.ball is not None:
            self.report.play(self.engine, self.game.muzzle)
            self.shot.children = [self.game.ball.transform]
            self.trail.point = [self.game.muzzle, self.game.muzzle]
        self.update()

    def OnFraction(self, event):
        now = systemtime.systemTime()
        self.game.tick(min(now - self.last, 0.05))
        self.last = now
        self.update()

    def update(self):
        '''Write what the game says into the scene.  The ball's `Transform` is
        moved by the physics manager, so what is left here is the camera, the
        path drawn behind the ball, and the text.'''
        game = self.game
        '''=The camera=

        The eye is a `Viewpoint` in the cannon's own frame, so it is wherever
        the barrel's frame puts it.  `look_through` moves the window's camera
        to it, which is done again each frame because the frame turns.'''
        game.course.gun.look_through(self)
        self.loaded.translation = game.muzzle
        if game.state == 'flying':
            path = list(self.trail.point)
            path.append(game.position)
            self.trail.point = path
            self.line.coordIndex = list(range(len(path))) + [-1]
        self.loaded.children = self.waiting if game.state != 'flying' else []
        self.readout.lines = [
            'q a  bearing    %5.1f deg' % game.aim.bearing,
            'w s  elevation  %5.1f deg' % game.aim.elevation,
            'e d  power      %5.1f m/s' % game.aim.power,
            'space  fire     %2d shots left' % game.shots_left,
            '',
            self.message,
        ]


def barrel():
    '''The barrel as a closed solid: a tube and a disc over each end.

    A cylinder is only its curved face, and from inside the barrel's mouth or
    behind its breech that face is culled, so the camera on the cannon would
    see through it.  The tube stands along y, centred, and the caller turns it
    along x.
    '''
    sides, radius = 20, 0.22
    half = BARREL / 2.0
    return surfaces.merge([
        surfaces.cylinder(radius, BARREL, sides=sides),
        surfaces.placed(surfaces.polygon(radius, sides), (0, half, 0), (1, 0, 0, -math.pi / 2)),
        surfaces.placed(surfaces.polygon(radius, sides), (0, -half, 0), (1, 0, 0, math.pi / 2)),
    ])


if __name__ == "__main__":
    TestContext.ContextMainLoop(definition={'renderer': 'pbr', 'size': SIZE})
