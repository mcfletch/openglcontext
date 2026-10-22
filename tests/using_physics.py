#! /usr/bin/env python
'''=Creating a Game with the Physics Engine=

[using_physics.py-screen-0001.png Screenshot]

This tutorial walks through the process of creating a game using the
OpenGLContext renderer and the omi_physics engine for simulating a
physical environment. We use convenience methods to create the geometry
for the world with reasonable textures.

As with any game, the first question is what we're going to build.
To keep it simple, we'll use a classic game that's been available
on computers since the early 80s. It's a cannon game where you try
to land a ball on a target by controlling your cannon's bearing,
elevation and power. The physics engine makes the things that older
versions of the game left out cheap to add, so this one has them:

* three kinds of ball: steel is the all-rounder, rubber is light and
  bounces, lead is heavy and does not
* six courses, each a new arrangement of walls, a crate stack on the
  target, a target that slides, a gate that rises and falls, and wind
* a springboard that throws a rubber ball high, for ricochet shots
* a score that rewards the balls you did not need

The rules are approximately these:

* two random platforms are created, one with a cannon, one with a target
* the player picks a ball with the `1`, `2` and `3` keys, and adjusts the
  bearing, elevation and power of the cannon, with the keys or by dragging
  three thumb-wheels on the screen
* the player hits space to fire the cannon
* a ball that lands on the red mark clears the course; the player is paid
  for each ball left over, each crate knocked off its place and a ricochet
* a ball that comes to rest, falls away or flies too long is a miss, and a
  course is lost when the last ball has missed
* space after a clear starts the next course, and after a loss starts again

The `v` key steps between the four views and the cannon's own view.

'''
from __future__ import annotations

import dataclasses
import functools
import itertools
import math
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy
from omi_audio import model as audiomodel
from omi_audio import synth
from omi_audio.clip import Clip
from omi_physics import model
from omi_physics.kinematic import KinematicAnimator
from pydispatch import dispatcher

''':py:mod:`OpenGLContext.entropy` provides a random number generator that shares
the world's seed, that allows test suites to test the random value
by using the same seed on each test run.'''
from OpenGLContext import entropy
'''The audio scene will let us play the cannon's report when it fires, and a thud
where a ball or a crate strikes something'''
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
from OpenGLContext.scenegraph import particles, surfaces
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Coordinate, DirectionalLight, Group, IndexedLineSet, LayerSet,
    Layout, LayoutLayer, Material, NavigationInfo, PlaneSensor,
    ScreenFontStyle, ScreenGroup, Shape, Text, Transform, Viewpoint, sceneGraph,
)
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.nodepath import NodePath
from OpenGLContext.scenegraph.physicsbody import PhysicsBody
from OpenGLContext.ui.hudwidgets import HUDLayer, ScreenWash, TextBlock
from OpenGLContext.viewer.environment import sky_background

'''A 4-tile layout view means that the on-screen items are about 1/4 of normal
size, so we'll make the window larger than we normally do for a demo.'''
#: The window is larger than most of these scripts', since it holds four views.
SIZE = (1200, 760)

'''Game parameters are just regular python variables. We have a lot of knobs
we can tweak to change the gameplay or the presentation of the game.'''
#: Radius (metres) of every ball, and the distance from the barrel's pivot to
#: its mouth.
BALL_RADIUS = 0.3
BARREL = 2.0

#: Half the width of each tower, in metres.  The target is small: at forty
#: metres it is under two degrees across.
CANNON_HALF, TARGET_HALF = 2.0, 1.25

#: Seconds the world advances in one step.  A ball at full power crosses
#: less than  its own radius in a step, so it cannot pass through a surface.
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

#: The longest a shot is followed, in seconds, and how far below the ground
#: a ball may fall before the shot is over.
LONGEST = 40.0
FALLEN = -10.0

#: How far outside the box round the course a ball may go, in metres, before
#: the shot is over.
FAR = 40.0

#: A shot is over when the ball has moved slower than SETTLED_SPEED metres a
#: second for SETTLED_TIME seconds.
SETTLED_SPEED, SETTLED_TIME = 0.5, 0.75

#: The hazards, in metres: a wall's thickness and width, a crate's side and
#: how far the world must move it before it counts as knocked off its place,
#: and the springboard's length, thickness and width and how far in front of
#: the target it lies.  The crate's mass is in kilograms.
WALL_THICK, WALL_WIDTH = 1.5, 12.0
CRATE, CRATE_MASS, TOPPLED = 1.1, 20.0, 1.0
SPRINGBOARD, SPRINGBOARD_GAP = (4.0, 0.25, 7.0), 7.0

#: The seconds a sliding target takes to go to one side and back, and a gate
#: to close, open and close again.
SLIDE_PERIOD, GATE_PERIOD = 9.0, 9.0

#: The wind that streams the pennant at full length, in newtons, and the
#: height of its pole in metres.
WIND_FULL, POLE = 4.0, 7.0

#: What a cleared course pays: for clearing it, each ball left over, each
#: crate knocked off its place and a ricochet.
CLEAR_BONUS, PER_BALL, PER_CRATE, RICOCHET_BONUS = 500, 50, 25, 250

#: The width, in characters, the message under the status is wrapped to.
MESSAGE_WIDTH = 22

#: What counts as an impact: the closing speed in metres a second that a ball
#: makes noise and sparks at, and a crate makes a crash at.
IMPACT_SPEED, CRASH_SPEED = 3.0, 4.0

#: What one key press changes: degrees of bearing and elevation, and metres per
#: second of power.
TURN, RAISE, PUSH = 0.2, 0.2, 0.2

#: How far the aim may be moved: bearing either side of straight ahead and the
#: elevation, in degrees, and the power in metres per second.
BEARING_LIMIT = (-60.0, 60.0)
ELEVATION_LIMIT = (-10.0, 85.0)
POWER_LIMIT = (5.0, 40.0)

#: How loud the report is at the least and the most power: a gentle shot is
#: plainly audible, a hard one is at full volume, and the 14 dB between them is
#: heard as a clear change rather than a nudge.
REPORT_GAIN = (0.2, 1.0)

#: How far a thumb-wheel is dragged for one whole turn, in pixels: most of the
#: window's height.
TRAVEL = 0.8 * SIZE[1]

#: A thumb-wheel, in pixels: the opening its drum shows through (across, up),
#: the drum's radius and the width of its face, how far behind the panel its
#: axis is, the thickness of the bars round the opening, and the length of
#: knurling one copy of the texture covers, which goes six times round.
SLOT, DRUM, FACE, AXLE, BAR = (52.0, 124.0), 84.0, 46.0, 52.0, 10.0
KNURL = 2.0 * math.pi * DRUM / 6.0

#: The distance between two wheels' centres, how far the panel they are on
#: stands in from the left of its view, and how far above the panel's middle
#: the wheels are, which leaves room under them for what they read.
PITCH, INSET, RISE = 96.0, 10.0, 26.0

#: The colours of the screen wash for a win and for a lost game, and how solid
#: it is: the world still shows through.
WIN_WASH, LOSE_WASH, WASH_STRENGTH = (0.1, 0.8, 0.2), (0.85, 0.1, 0.1), 0.4

'''Defines our control scheme. Here we use the three left-most columns of the
US keyboard layout's alphabetic keys, each column being an up/down pair for
a particular field, and the number keys to choose a ball.'''

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
        'wall': surfaces.pbr_material(surfaces.plaster(256, colour=(0.78, 0.74, 0.66))),
        'gate': surfaces.pbr_material(surfaces.wood(256, colour=(0.30, 0.17, 0.08))),
        'crate': surfaces.pbr_material(surfaces.wood(256, colour=(0.60, 0.42, 0.22))),
        'springboard': surfaces.pbr_material(surfaces.tiles(256, count=4)),
        'mark': PhysicalMaterial(baseColor=(0.8, 0.08, 0.06), metallic=0.0, roughness=0.5),
        'pennant': PhysicalMaterial(baseColor=(0.95, 0.75, 0.1), metallic=0.0, roughness=0.8),
        'steel': PhysicalMaterial(baseColor=surfaces.STEEL, metallic=1.0, roughness=0.25),
        'rubber': PhysicalMaterial(baseColor=(0.9, 0.35, 0.05), metallic=0.0, roughness=0.9),
        'lead': PhysicalMaterial(baseColor=(0.22, 0.23, 0.27), metallic=1.0, roughness=0.55),
        'bronze': PhysicalMaterial(baseColor=surfaces.BRONZE, metallic=1.0, roughness=0.35),
        'panel': surfaces.pbr_material(
            surfaces.brushed_metal(128, colour=(0.35, 0.36, 0.37), roughness=0.6)),
        'knurl': surfaces.pbr_material(surfaces.knurled(256, count=8), relief=6.0,
                                       baseColor=(0.8, 0.8, 0.8)),
        'chrome': PhysicalMaterial(baseColor=surfaces.STEEL, metallic=1.0, roughness=0.3),
        'recess': PhysicalMaterial(baseColor=(0.02, 0.02, 0.02), metallic=0.0, roughness=0.9),
        'paint': Material(diffuseColor=(0.02, 0.02, 0.02)),
    }

'''=The balls=

A ball is a mass and a physics material.  The material is the OMI model's
friction and restitution: `restitution` is the fraction of the closing speed a
contact throws back, so steel (0.1) lands with a clank, rubber (0.8) hops, and
lead is given none and stays where it lands.  `MATERIAL_PRESETS` has steel and
rubber ready made; lead is described here.  Every kind leaves the barrel at
the same speed, so the mass decides how hard it hits, and how far the wind
moves it.'''
@dataclass(frozen=True)
class Ammo:
    """A kind of ball: its mass, what it is made of, how it looks and how it sounds."""

    name: str
    #: Kilograms.
    mass: float
    material: model.Material
    #: Which of `looks` it is drawn in.
    look: str
    #: How high its impact sounds, as a multiple of the recording's pitch.
    pitch: float
    #: Whether it throws sparks where it strikes.
    sparks: bool


AMMO = (
    Ammo('steel', 5.0, model.MATERIAL_PRESETS['metal'], 'steel', 1.0, True),
    Ammo('rubber', 2.0, model.MATERIAL_PRESETS['rubber'], 'rubber', 1.6, False),
    Ammo('lead', 12.0, model.Material(staticFriction=0.5, dynamicFriction=0.4,
                                      restitution=0.0), 'lead', 0.65, True),
)
AMMO_BY_NAME = {ammo.name: ammo for ammo in AMMO}

#: The number key that loads each kind of ball.
SELECT_KEYS = {str(number): ammo.name for number, ammo in enumerate(AMMO, 1)}

#: The kinds of piece that make a ball's hit a ricochet when it goes on to land
#: on the mark.
RICOCHETS = ('springboard', 'wall', 'gate')

'''Model a single platform as to where it is and how large it is.'''
@dataclass(frozen=True)
class Platform:
    """A square tower: centre on the ground plane, height and half its width."""

    x: float
    z: float
    top: float
    half: float


def report_gain(power: float) -> float:
    """The report's gain at ``power``: audible at the least, full at the most."""
    low, high = POWER_LIMIT
    fraction = (min(max(power, low), high) - low) / (high - low)
    return REPORT_GAIN[0] + (REPORT_GAIN[1] - REPORT_GAIN[0]) * fraction


class Sounds:
    """What the game sounds like, made from arithmetic.

    '''=The sounds=

    `omi_audio.synth` makes sounds with no files: `rumble` is noise with the
    top taken off over a falling tone, which is what a detonation is, and
    `reverberated` puts the tail of an open field behind it.  `impact` is a
    burst of noise with a sharp decay, a crack, and a rising run of `tone`s
    is the fanfare.  Each clip is made once and played from where it
    happened through an emitter, so it is placed in the stereo field and
    falls off with the distance from the camera.  The report's gain rises with
    the shot's power, so a gentle shot is audible and a hard one is at full
    volume.  `play` takes a `rate`, and the same thud at a higher rate is a
    lighter ball.'''
    """

    def __init__(self, sample_rate: int | None = None) -> None:
        options = {} if sample_rate is None else {'sample_rate': sample_rate}
        boom = synth.rumble(0.9, decay=7.0, cutoff=600.0, tilt=-6.0, pitch=90.0,
                            pitch_end=40.0, tone=0.2, drive=3.0, seed=21, **options)
        notes = [synth.tone(frequency, 0.16, harmonics=4, **options)
                 for frequency in (523.25, 659.25, 783.99, 1046.5)]
        self.clips: dict[str, Clip] = {
            'report': synth.reverberated(boom, seconds=0.9, level=0.35, seed=5),
            'thud': synth.rumble(0.3, decay=16.0, cutoff=320.0, pitch=95.0, pitch_end=50.0,
                                 tone=0.5, drive=2.0, seed=3, **options),
            'crash': synth.impact(0.4, decay=9.0, seed=11, **options),
            'fanfare': Clip(numpy.concatenate([note.samples for note in notes]),
                            notes[0].sample_rate, name='fanfare'),
        }
        self.emitter = audiomodel.AudioEmitter(positional=audiomodel.PositionalProperties(
            refDistance=3.0, rolloffFactor=0.8))

    def play(self, engine: Any, name: str, position: Any, gain: float = 1.0,
             rate: float = 1.0) -> Any:
        """Start clip ``name`` at ``position``; None where there is no engine to play it."""
        if engine is None:
            return None
        return engine.play(self.clips[name], emitter=self.emitter,
                           position=tuple(float(part) for part in position),
                           gain=gain, priority=1.0, rate=rate)

    def fire(self, engine: Any, position: Any, power: float) -> Any:
        """Start the report at ``position``, as loud as ``power`` asks."""
        return self.play(engine, 'report', position, report_gain(power))


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


@dataclass(frozen=True)
class Scale:
    """One field of the aim as a thumb-wheel sets it.

    The field's limits are one whole turn of the wheel apart, and TRAVEL
    pixels of drag.  ``keys`` are the keys that step the field up and down.
    """

    name: str
    unit: str
    limits: tuple[float, float]
    keys: tuple[str, str]
    #: Whether the wheel also reads the value as a percentage of its scale.
    fraction: bool = False

    def turn(self, value: float) -> float:
        """How far round the wheel is at ``value``: 0 at the lower limit, 1 at the upper."""
        low, high = self.limits
        return (value - low) / (high - low)

    def value(self, travel: float) -> float:
        """The value ``travel`` pixels of drag up from the lower limit, within the limits."""
        low, high = self.limits
        return min(max(low + travel / TRAVEL * (high - low), low), high)


#: The three wheels, in the order they stand on the panel.  The power wheel
#: reads as a percentage of its scale as well as in metres per second.
SCALES = (
    Scale('bearing', 'deg', BEARING_LIMIT, ('q', 'a')),
    Scale('elevation', 'deg', ELEVATION_LIMIT, ('w', 's')),
    Scale('power', 'm/s', POWER_LIMIT, ('e', 'd'), fraction=True),
)


class Wheel:
    """A thumb-wheel on the screen that sets one field of the aim, labelled with its value.

    '''=A drag sensor=

    A thumb-wheel is turned by dragging its face up or down, and a long drag
    is a small turn, which is what makes it a fine control.  X3D has three
    sensors that follow a drag: a `CylinderSensor` and a `SphereSensor` turn
    with the pointer as though it held their surface, and a `PlaneSensor`
    measures how far the pointer has gone.  The wheel uses a `PlaneSensor`,
    since its turn is the length of the drag and not the angle the pointer
    has reached round it.

    The sensor sends `translation_changed`, here in pixels.  `minPosition`
    and `maxPosition` hold it to no movement across and to TRAVEL pixels up,
    which is the wheel's whole scale.

    The sensor and the drum share a `Group`: a sensor senses its siblings,
    and a drag that starts on the drum carries on wherever the pointer goes.

    Each drag starts from the sensor's `offset`.  `show` writes the place of
    the value there, so a drag carries on from wherever the keys left the
    aim, and it leaves the offset alone while a drag is under way.'''

    '''=The wheel=

    The drum is a cylinder lying across the panel, knurled, and it is turned
    about its own axis, so the knurling moves up and down its face as a real
    wheel's does.  Its axis is behind the panel and a frame of four chrome
    bars stands in front of its top and bottom, so what shows is the part
    of the drum that stands out through the frame.'''
    """

    def __init__(self, scale: Scale, look: dict[str, Any],
                 on_turn: Callable[[str, float], None]) -> None:
        self.scale = scale
        self.on_turn = on_turn
        #: The value the drum and the label were last written for.
        self.shown: float | None = None
        self.sensor = PlaneSensor(description=scale.name, minPosition=(0, 0),
                                  maxPosition=(0, TRAVEL))
        self.drum = Transform(translation=(0, 0, -AXLE), children=[
            surfaces.shape(surfaces.cylinder(DRUM, FACE, sides=64, repeat=KNURL),
                           look['knurl'], rotation=(0, 0, 1, math.pi / 2))])
        self.label = Text(string=['', ''], fontStyle=ScreenFontStyle(
            pointSize=10, spacing=1.3, family=['SANS'], justify=['MIDDLE', 'BEGIN']))
        width, height = SLOT
        '''A `Layout` sets the size of its children's unit across and up the
        screen and leaves depth alone, so a drum drawn straight into the
        panel would be far deeper than it is tall.  A `ScreenGroup`'s unit is
        one pixel in all three directions, and the wheel's parts go in one.'''
        self.node = Transform(children=[ScreenGroup(children=[
            surfaces.shape(surfaces.panel(width, height), look['recess'],
                           translation=(0, 0, 0.5)),
            Group(children=[self.drum, self.sensor]),
            *frame(width, height, look['chrome']),
            Transform(translation=(0, -height / 2 - BAR - 18, 1), children=[
                Shape(geometry=self.label, appearance=Appearance(material=look['paint']))]),
        ])])
        '''A field of a node sends a `set` signal when it is written, which is
        how a ROUTE hears a sensor.  The wheel listens for the sensor's
        `translation_changed` the same way.'''
        dispatcher.connect(self.turned, sender=self.sensor,
                           signal=('set', PlaneSensor.translation_changed))

    def turned(self, value: Any) -> None:
        """Report the value at ``value``, the sensor's translation."""
        self.on_turn(self.scale.name, self.scale.value(float(value[1])))

    def show(self, value: float) -> None:
        """Turn the drum to ``value`` and write it underneath."""
        turn = self.scale.turn(value)
        if value != self.shown:
            self.shown = value
            self.drum.rotation = (1, 0, 0, -2.0 * math.pi * turn)
            reading = '%.1f %s' % (value, self.scale.unit)
            if self.scale.fraction:
                reading += '  %d%%' % round(100.0 * turn)
            self.label.string = ['%s  %s %s' % (self.scale.name, *self.scale.keys),
                                 reading]
        if not self.sensor.active():
            self.sensor.offset = (0, turn * TRAVEL, 0)


def frame(width: float, height: float, material: Any) -> list[Any]:
    """Four half-round bars round a ``width`` by ``height`` opening, their flat backs on z = 0."""
    upright = surfaces.cylinder(BAR / 2.0, height + 2 * BAR, arc=math.pi)
    level = surfaces.cylinder(BAR / 2.0, width + 2 * BAR, arc=math.pi)
    across, up = (width + BAR) / 2.0, (height + BAR) / 2.0
    return [
        surfaces.shape(upright, material, translation=(-across, 0, 0)),
        surfaces.shape(upright, material, translation=(across, 0, 0)),
        surfaces.shape(level, material, translation=(0, up, 0), rotation=(0, 0, 1, math.pi / 2)),
        surfaces.shape(level, material, translation=(0, -up, 0), rotation=(0, 0, 1, math.pi / 2)),
    ]


class Wheels:
    """The three wheels on a panel at the left of the view, drawn over the scene.

    '''=On the screen=

    A `LayerSet` draws layers over the scene's own children, which are layer
    0.  A `LayoutLayer` is a layer whose `Layout` places it on the screen:
    this one is a rectangle of pixels against the left of the view, half
    way up, and `scaleMode` PIXEL makes its children's unit one pixel too.
    A layer has its own lights, and its `NavigationInfo` gives it a
    headlight.  A pick is resolved through the topmost layer under the
    pointer, so the wheels take the pointer and the world behind them does
    not.'''
    """

    def __init__(self, on_turn: Callable[[str, float], None]) -> None:
        look = looks()
        self.wheels = [Wheel(scale, look, on_turn) for scale in SCALES]
        #: The panel's width and height, in pixels.
        self.size = (PITCH * len(self.wheels), SLOT[1] + 2 * BAR + 84.0)
        width, height = self.size
        for index, wheel in enumerate(self.wheels):
            wheel.node.translation = ((index - (len(self.wheels) - 1) / 2.0) * PITCH, RISE, 0)
        self.layer = LayoutLayer(
            layout=Layout(size=self.size, sizeUnits=['PIXEL', 'PIXEL'],
                          align=['LEFT', 'CENTER'], offset=(INSET, 0),
                          offsetUnits=['PIXEL', 'PIXEL'], scaleMode=['PIXEL', 'PIXEL']),
            children=[
                NavigationInfo(),
                surfaces.shape(surfaces.panel(width, height, repeat=height), look['panel']),
                *(wheel.node for wheel in self.wheels),
            ])
        self.layers = LayerSet(order=[0, 1], layers=[self.layer])

    def show(self, aim: Aim) -> None:
        """Turn each wheel to its field of ``aim``."""
        for wheel in self.wheels:
            wheel.show(getattr(aim, wheel.scale.name))


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



@dataclass(frozen=True)
class Level:
    """One course: what stands between the cannon and the target, and the balls it allows.

    ``ammo`` is how many steel, rubber and lead balls the player has.  The
    rest are the hazards: the height in metres of a wall or of a sliding
    gate, the crates stacked on the target (columns each way, rows high), the metres the
    target slides to either side, the wind in newtons, and whether a
    springboard lies in front of the target.  Zero or false leaves one out.
    """

    name: str
    hint: str
    ammo: tuple[int, int, int]
    wall: float = 0.0
    crates: tuple[int, int] = (0, 0)
    gate: float = 0.0
    slide: float = 0.0
    wind: float = 0.0
    springboard: bool = False


'''=The courses=

A course is data.  Each `Level` names the hazards it has and how many of each
ball the player is given, and `build_course` makes the scene from it, so a new
course is a new line here.'''
LEVELS = (
    Level('Open Ground', 'Hit the red mark.', (6, 0, 0)),
    Level('The Wall', 'Over the wall, or off the springboard.',
          (4, 3, 0), wall=10.0, springboard=True),
    Level('Crate Stack', 'Clear the crates.  Lead hits hard.',
          (3, 0, 4), crates=(2, 2)),
    Level('Crosswind', 'Read the pennant.  Light balls drift.',
          (4, 3, 2), wall=7.0, wind=3.0),
    Level('The Ferry', 'The target slides.  Time the shot.',
          (5, 3, 1), slide=7.0, springboard=True),
    Level('Portcullis', 'Time the gate, or lob over it.',
          (4, 3, 3), gate=22.0, crates=(2, 1), wind=2.0),
)


def swing(home: tuple[float, float, float], reach: float) -> Callable[[float], Any]:
    """A pose function: the position ``home`` moved ``reach`` metres either way along z."""
    def pose(time: float) -> Any:
        return (home[0], home[1], home[2] + reach * math.sin(2.0 * math.pi * time / SLIDE_PERIOD))
    return pose


def gate_open(time: float) -> float:
    """How far open the gate is at ``time``: 0 closed, 1 open, a third of the period at each."""
    phase = 0.5 + 0.5 * math.cos(2.0 * math.pi * time / GATE_PERIOD)
    return min(max((0.75 - phase) / 0.5, 0.0), 1.0)


def drop(home: tuple[float, float, float], depth: float) -> Callable[[float], Any]:
    """A pose function: ``home`` lowered ``depth`` metres as the gate opens."""
    def pose(time: float) -> Any:
        return (home[0], home[1] - depth * gate_open(time), home[2])
    return pose


@dataclass
class Piece:
    """A node of the course, and how the physics world is to treat it.

    ``motion`` is None for something that stands still, a `model.Motion` for
    something that moves.  ``pose`` drives a kinematic piece: a function from
    the seconds it has run to where it should be.  ``kind`` names what it is
    to the rules.
    """

    node: Any
    kind: str
    material: str = 'wood'
    motion: model.Motion | None = None
    pose: Callable[[float], Any] | None = None
    trigger: bool = False


@dataclass
class Course:
    """The world a level is played in: its pieces, the cannon and the wind.

    Nothing here is physical.  It is geometry, drawn like any scene, and it is
    the same whether anything is going to collide with it or not.
    """

    level: Level
    cannon: Platform
    target: Platform
    pieces: list[Piece]
    gun: Cannon
    #: Newtons along +z, which is to the right of a barrel pointing along +x.
    wind: float = 0.0
    #: The pole and pennant that show the wind, or None where it is calm.
    flag: Any = None

    @property
    def nodes(self) -> list[Any]:
        """Everything drawn."""
        found = [piece.node for piece in self.pieces] + self.gun.nodes
        return found + [self.flag] if self.flag is not None else found

    def kind(self, kind: str) -> list[Piece]:
        """The pieces of one kind."""
        return [piece for piece in self.pieces if piece.kind == kind]

    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """``(minimum, maximum)``, the box round the towers and the sky over them."""
        level = self.level
        high = max(self.cannon.top, self.target.top, level.wall, level.gate) + 25.0
        reach = max(self.cannon.half, self.target.half, WALL_WIDTH / 2.0) + 6.0
        low_x = min(self.cannon.x, self.target.x) - reach
        high_x = max(self.cannon.x, self.target.x) + reach
        low_z = min(self.cannon.z, self.target.z) - reach - level.slide
        high_z = max(self.cannon.z, self.target.z) + reach + level.slide
        return ((low_x, 0.0, low_z), (high_x, high, high_z))

    def beyond(self, point: tuple[float, ...]) -> bool:
        """Whether ``point`` is more than FAR metres outside the course's box, across the ground."""
        low, high = self.bounds()
        return bool(point[0] < low[0] - FAR or point[0] > high[0] + FAR
                    or point[2] < low[2] - FAR or point[2] > high[2] + FAR)


def build_course(level: Level, rng: Any, look: dict[str, Any]) -> Course:
    """Two towers at random heights, distances and offsets across the line, and the level's hazards."""
    '''=The world=

    A tower is a `Transform` holding a box of brick or marble, and the ground
    is a wide, thin box of sand.  `surfaces.block` makes the geometry and
    `surfaces.shape` puts a material on it and places it.  Each node goes in a
    `Piece` with a word for what it is, and what the physics world should do
    with it is added later.

    The red mark on the target is a slab that stands PAD_ABOVE over the top of
    the tower and reaches PAD_DEPTH down into it.  It is drawn, and it is also
    the place the ball has to be: the game makes it a trigger.  A ball that
    passes higher over the target than PAD_ABOVE plus its own width is a miss.'''
    cannon = Platform(rng.uniform(-35, -20), rng.uniform(-10, 10),
                      rng.uniform(2.0, 5.0), CANNON_HALF)
    target = Platform(rng.uniform(20, 35), rng.uniform(-10, 10),
                      rng.uniform(1.0, 5.0 if level.slide else 8.0), TARGET_HALF)
    wind = level.wind * rng.choice((-1.0, 1.0))
    middle = ((cannon.x + target.x) / 2.0, (cannon.z + target.z) / 2.0)

    ground = surfaces.shape(surfaces.block((400.0, 1.0, 400.0), repeat=4.0),
                            look['ground'], translation=(0, -0.5, 0))
    cannon_tower = surfaces.shape(
        surfaces.block((cannon.half * 2, cannon.top, cannon.half * 2), repeat=2.0),
        look['cannon'], translation=(cannon.x, cannon.top / 2.0, cannon.z))
    target_home = (target.x, target.top / 2.0, target.z)
    target_tower = surfaces.shape(
        surfaces.block((target.half * 2, target.top, target.half * 2), repeat=2.0),
        look['target'], translation=target_home)
    pad_home = (target.x, target.top + (PAD_ABOVE - PAD_DEPTH) / 2.0, target.z)
    pad = surfaces.shape(
        surfaces.block((target.half * 1.8, PAD_ABOVE + PAD_DEPTH, target.half * 1.8)),
        look['mark'], translation=pad_home)
    pieces = [Piece(ground, 'ground'), Piece(cannon_tower, 'tower')]
    '''=A moving platform=

    A target that slides is two pieces that move together, the tower and the
    mark on it.  A piece with a `pose` is a kinematic body: gravity and
    collisions never move it, and each frame the game steers it along the pose
    function.  Whatever rests on it is carried, because the steering is a
    real velocity.'''
    if level.slide:
        kinematic = model.Motion(type=model.KINEMATIC)
        pieces.append(Piece(target_tower, 'tower', motion=kinematic,
                            pose=swing(target_home, level.slide)))
        pieces.append(Piece(pad, 'pad', motion=kinematic, trigger=True,
                            pose=swing(pad_home, level.slide)))
    else:
        pieces.append(Piece(target_tower, 'tower'))
        pieces.append(Piece(pad, 'pad', trigger=True))
    if level.wall:
        wall = surfaces.shape(surfaces.block((WALL_THICK, level.wall, WALL_WIDTH), repeat=2.0),
                              look['wall'], translation=(middle[0], level.wall / 2.0, middle[1]))
        pieces.append(Piece(wall, 'wall'))
    if level.gate:
        home = (middle[0], level.gate / 2.0, middle[1])
        gate = surfaces.shape(surfaces.block((WALL_THICK, level.gate, WALL_WIDTH), repeat=2.0),
                              look['gate'], translation=home)
        pieces.append(Piece(gate, 'gate', motion=model.Motion(type=model.KINEMATIC),
                            pose=drop(home, level.gate + 1.0)))
    if level.springboard:
        board = surfaces.shape(surfaces.block((SPRINGBOARD[0], SPRINGBOARD[1], SPRINGBOARD[2])),
                               look['springboard'],
                               translation=(target.x - SPRINGBOARD_GAP, SPRINGBOARD[1] / 2.0,
                                            target.z))
        pieces.append(Piece(board, 'springboard', material='rubber'))
    across, high = level.crates
    for row, column, depth in itertools.product(range(high), range(across), range(across)):
        crate = surfaces.shape(
            surfaces.block((CRATE,) * 3, repeat=1.0), look['crate'],
            translation=(target.x + CRATE * (depth - (across - 1) / 2.0),
                         target.top + CRATE * (row + 0.5),
                         target.z + CRATE * (column - (across - 1) / 2.0)))
        pieces.append(Piece(crate, 'crate', motion=model.Motion(
            type=model.DYNAMIC, mass=CRATE_MASS)))
    gun = Cannon((cannon.x, cannon.top + 0.9, cannon.z), look)
    return Course(level, cannon, target, pieces, gun, wind, flag(target, wind, look))


def flag(target: Platform, wind: float, look: dict[str, Any]) -> Any:
    """A pole beside the target with a pennant streaming downwind, or None where there is none."""
    if not wind:
        return None
    side = 1.0 if wind > 0 else -1.0
    length = 0.6 + 1.4 * min(abs(wind) / WIND_FULL, 1.0)
    x, z = target.x + target.half + 1.5, target.z
    return Transform(children=[
        surfaces.shape(surfaces.cylinder(0.06, POLE), look['steel'],
                       translation=(x, POLE / 2.0, z)),
        surfaces.shape(surfaces.block((0.04, 0.6, length)), look['pennant'],
                       translation=(x, POLE - 0.4, z + side * length / 2.0)),
    ])


class Game:
    """The rules, over a physics world: a course, the aim, the balls and the score.

    ``state`` is ``aiming`` until the cannon fires, ``flying`` while the ball
    is in the air, then ``aiming`` again after a miss, ``cleared`` after a hit,
    ``lost`` when the last ball has missed and ``finished`` when the last
    course is cleared.  Firing from any of the last three starts the next
    course, or the first again.
    Nothing here draws or reads a clock: `tick` is given the seconds that have
    passed.

    The world's events decide the game.  A ball in the target's slab is a hit,
    and a ball that stops, falls away or flies too long is a miss.  What the
    ball touches along the way is reported to ``on_event(kind, detail)``, which
    is how the window plays sounds and throws sparks without the rules knowing
    either exists.  The kinds are ``fire``, ``impact``, ``crash``, ``hit``,
    ``miss`` and ``lost``.
    """

    def __init__(self, rng: Any = None, on_event: Callable[[str, Any], None] | None = None,
                 level: int = 0) -> None:
        self.rng = rng or entropy.randomizer('cannon')
        self.look = looks()
        self.on_event = on_event or (lambda kind, detail=None: None)
        self.aim = Aim()
        self.score = 0
        self.start_level(level)

    def start_level(self, index: int) -> None:
        """Build course ``index`` and a physics world for it, ready to go."""
        self.index = index
        self.level = LEVELS[index]
        self.course = build_course(self.level, self.rng, self.look)
        self.stock = {ammo.name: count for ammo, count in zip(AMMO, self.level.ammo, strict=True)}
        self.chosen = next(name for name, count in self.stock.items() if count)
        self.state = 'aiming'
        self.message = self.level.hint
        self.ball: PhysicsBody | None = None
        self.flying: Ammo | None = None
        self.subscription: Any = None
        self.elapsed = self.slow = 0.0
        self.ricochet = False
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
        it never moves.  A `Motion` of type DYNAMIC has a mass and falls; one
        of type KINEMATIC is moved by the game and pushes whatever is in its
        way.

        `material` names how a surface behaves: its friction and its
        restitution, the fraction of the closing speed a contact gives back.
        When two surfaces meet the world averages the two, so a rubber ball
        rebounds far on the rubber springboard, less from the wood of the
        ground, and a lead ball hardly at all.'''
        course = self.course
        self.manager = PhysicsManager(
            gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)),
            default_linear_damping=0.0, fixed_dt=STEP)
        self.world = self.manager.world
        self.materials = {ammo.name: self.world.add_material(ammo.material) for ammo in AMMO}
        self.bodies: dict[PhysicsBody, Piece] = {}
        self.animators: list[KinematicAnimator] = []
        for piece in course.pieces:
            body = self.manager.attach(piece.node, piece.motion, material=piece.material,
                                       strategy='primitive', trigger=piece.trigger)
            self.bodies[body] = piece
            if piece.pose is not None:
                self.animators.append(KinematicAnimator(self.world, body.index, piece.pose))
        self.pad = self.body_of('pad')
        self.crates = [body for body, piece in self.bodies.items() if piece.kind == 'crate']
        self.homes = numpy.array([self.world.position[body.index] for body in self.crates])
        '''=A trigger=

        With `trigger=True` the geometry becomes a trigger instead: it stops
        nothing and reports what enters it.  The red mark is one, so a ball
        that lands on the target is inside it, and the game subscribes to its
        `enter` events.  Crates resting on the mark are inside it too, which
        is why the handler asks who came in.'''
        self.manager.events.subscribe(self._entered, body=self.pad,
                                      kinds=('trigger',), phases=('enter',))
        if self.crates:
            self.manager.events.subscribe(self._crashed, body=self.crates, above=CRASH_SPEED)

    def body_of(self, kind: str) -> PhysicsBody:
        """The body of the one piece of ``kind``."""
        return next(body for body, piece in self.bodies.items() if piece.kind == kind)

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
        """Move the aim and turn the cannon to it; a ball already in the air keeps its course."""
        self.aim.adjust(**change)
        self.point()

    def set_aim(self, name: str, value: float) -> None:
        """Move one field of the aim to ``value``, as far as `adjust` allows."""
        self.adjust(**{name: value - getattr(self.aim, name)})

    def select(self, name: str) -> None:
        """Load ball ``name``, if this course allows it."""
        if name in self.stock and AMMO_BY_NAME[name] in self.carried:
            self.chosen = name

    @property
    def carried(self) -> list[Ammo]:
        """The kinds of ball this course gives the player, spent or not."""
        return [ammo for ammo, count in zip(AMMO, self.level.ammo, strict=True) if count]

    @property
    def shots_left(self) -> int:
        return sum(self.stock.values())

    @property
    def toppled(self) -> int:
        """How many crates have been knocked more than TOPPLED metres from where they stood."""
        if not self.crates:
            return 0
        now = self.world.position[[body.index for body in self.crates]]
        return int((numpy.linalg.norm(now - self.homes, axis=1) > TOPPLED).sum())

    def fire(self) -> bool:
        """Send the ball; after a course is over, build the next one instead.

        True where a ball was sent or a course started.  False while a ball is
        in the air, which has to settle or leave the area first, and where the
        loaded kind of ball has run out.
        """
        if self.state == 'cleared':
            self.start_level(self.index + 1)
            return True
        if self.state in ('lost', 'finished'):
            self.score = 0
            self.start_level(0)
            return True
        if self.state == 'flying':
            self.message = 'Wait for the ball to land.'
            return False
        if not self.stock[self.chosen]:
            self.message = 'No %s balls left.  Choose another.' % self.chosen
            return False
        self.release()
        ammo = AMMO_BY_NAME[self.chosen]
        '''=Go=

        The ball is a sphere, a node like the towers, attached as a
        dynamic body at the mouth of the barrel, standing still.  The
        kinds of ball differ in the mass and the material they are given.
        `apply_impulse` adds an impulse in newton seconds, and the body's
        velocity becomes impulse over mass: the mass times the power,
        along the barrel, so every ball leaves the barrel at the same
        speed and the heavy ones carry more punch.  `set_force` pushes a
        body with a steady force until it is changed, which is the wind:
        the same force moves a light ball further than a heavy one.  A
        sphere resting on the ground rolls under any push, so the force is
        taken away at the ball's first touch.'''
        node = surfaces.shape(surfaces.sphere(BALL_RADIUS), self.look[ammo.look],
                              translation=self.muzzle)
        self.ball = self.manager.attach(
            node, model.Motion(type=model.DYNAMIC, mass=ammo.mass),
            material=self.materials[ammo.name], strategy='primitive')
        '''The impulse is the power along the barrel's own axis, carried
        into the world by the cannon's frame of reference.'''
        kick = ammo.mass * self.aim.power * self.course.gun.along
        assert self.ball.index is not None
        self.world.apply_impulse(self.ball.index, tuple(float(part) for part in kick))
        if self.course.wind:
            self.world.set_force(self.ball.index, (0.0, 0.0, self.course.wind))
        '''=What the ball touched=

        A subscription to the ball's own contacts hears each time it
        touches another body.  Touching the ground or a tower does not end
        the shot, because a rubber ball keeps going.  The game looks at
        what was touched: a bounce off the springboard or a wall that
        ends in a hit is a ricochet, and scores extra.'''
        self.subscription = self.manager.events.subscribe(
            self._touched, body=self.ball, phases=('begin',))
        self.stock[ammo.name] -= 1
        if not self.stock[ammo.name]:
            self.chosen = next((name for name, count in self.stock.items() if count),
                               ammo.name)
        self.flying = ammo
        self.state = 'flying'
        self.elapsed = self.slow = 0.0
        self.ricochet = False
        self.message = ''
        self.on_event('fire', ammo)
        return True

    def release(self) -> None:
        """Take the last ball out of the world."""
        if self.subscription is not None:
            self.subscription.cancel()
            self.subscription = None
        if self.ball is not None:
            self.manager.remove(self.ball)
            self.ball = None

    def _entered(self, event: Any) -> None:
        """The physics reports something inside the trigger over the target."""
        if self.state == 'flying' and event.other is self.ball:
            self._hit()

    def _touched(self, event: Any) -> None:
        """The physics reports the ball touching something."""
        if self.state != 'flying':
            return
        piece = self.bodies.get(event.other)
        if piece is not None and piece.kind in RICOCHETS:
            self.ricochet = True
        if self.course.wind and self.ball is not None and self.ball.index is not None:
            self.world.set_force(self.ball.index, (0.0, 0.0, 0.0))
        self.on_event('impact', event)

    def _crashed(self, event: Any) -> None:
        """The physics reports a crate meeting something hard."""
        self.on_event('crash', event)

    def _hit(self) -> None:
        gain = (CLEAR_BONUS + PER_BALL * self.shots_left + PER_CRATE * self.toppled
                + (RICOCHET_BONUS if self.ricochet else 0))
        self.score += gain
        last = self.index + 1 >= len(LEVELS)
        self.state = 'finished' if last else 'cleared'
        self.message = '%sDirect hit!  +%d.  %s' % (
            'Ricochet!  ' if self.ricochet else '', gain,
            'Every course is cleared.  Space to play again.' if last
            else 'Space for the next course.')
        self.on_event('hit', gain)

    def _miss(self) -> None:
        if self.shots_left:
            self.state = 'aiming'
            self.message = 'Missed.'
            self.on_event('miss', None)
        else:
            self.state = 'lost'
            self.message = 'Missed.  Out of balls.  Space to start again.'
            self.on_event('lost', None)

    def tick(self, seconds: float) -> None:
        '''=Moving things=

        A kinematic body is steered by an animator: given the seconds that
        have passed it sets the velocity that carries the body to where its
        pose says it will be.  That is done before the world advances, which
        runs the fixed steps the seconds hold and delivers the events.'''
        for animator in self.animators:
            animator.update(seconds)
        self.manager.advance(seconds)
        if self.state != 'flying' or self.ball is None or self.ball.index is None:
            return
        self.elapsed += seconds
        speed = float(numpy.linalg.norm(self.world.linear_velocity[self.ball.index]))
        self.slow = self.slow + seconds if speed < SETTLED_SPEED else 0.0
        if (self.position[1] < FALLEN or self.course.beyond(self.position)
                or self.slow >= SETTLED_TIME or self.elapsed > LONGEST):
            self._miss()

    def status(self) -> list[str]:
        """The lines the window shows: course, score, wind, the balls, the keys and the message."""
        lines = ['course %d/%d %s' % (self.index + 1, len(LEVELS), self.level.name),
                 'score %d' % self.score]
        if self.course.wind:
            lines.append('wind %.1f N to the %s' % (
                abs(self.course.wind), 'right' if self.course.wind > 0 else 'left'))
        lines.extend('%s%d %s x%d' % ('>' if ammo.name == self.chosen else ' ', number,
                                      ammo.name, self.stock[ammo.name])
                     for number, ammo in enumerate(AMMO, 1) if ammo in self.carried)
        lines.append('space fire  v views')
        return lines + textwrap.wrap(self.message, MESSAGE_WIDTH)


class TestContext(BaseContext):
    def OnInit(self):
        '''The rules are a `Game`, which makes the nodes its bodies are bound
        to; the context puts them in the scene and keeps the scene in step.'''
        BaseContext.OnInit(self)
        look = looks()
        '''=Bodies and their nodes=

        A body is bound to a `Transform` and the world writes its pose onto
        it, so what is drawn is whatever is under that transform.  The course
        is a group the game's static nodes go in, and the ball in flight goes
        in another.'''
        self.scenery = Transform()
        self.shot = Transform()
        self.loaded = Transform()
        self.waiting = {ammo.name: surfaces.shape(surfaces.sphere(BALL_RADIUS), look[ammo.look])
                        for ammo in AMMO}
        self.trail = Coordinate(point=[(0, 0, 0), (0, 0, 0)])
        self.line = IndexedLineSet(coord=self.trail, coordIndex=[0, 1, -1])
        self.ghost = Coordinate(point=[(0, 0, 0), (0, 0, 0)])
        self.ghost_line = IndexedLineSet(coord=self.ghost, coordIndex=[0, 1, -1])
        '''=Sparks=

        One particle emitter serves every impact: `burst_at` throws a burst
        wherever the ball struck, along the surface's normal.  A second
        emitter is the fireworks for a hit.'''
        self.sparks = particles.preset('sparks', burstOnStart=False, worldSpace=True)
        self.fireworks = particles.preset('explosion', burstOnStart=False, worldSpace=True)
        '''=The wheels=

        The wheels' `LayerSet` goes in the scene with everything else.  Each
        wheel calls `OnWheel` with the name of its field and the value it was
        turned to.'''
        self.wheels = Wheels(self.OnWheel)
        self.sg = sceneGraph(children=[
            sky_background(),
            DirectionalLight(direction=(-0.4, -0.8, -0.5)),
            self.scenery, self.loaded, self.shot,
            Shape(geometry=self.ghost_line, appearance=Appearance(
                material=Material(emissiveColor=(0.4, 0.5, 0.7), diffuseColor=(0, 0, 0)))),
            Shape(geometry=self.line, appearance=Appearance(
                material=Material(emissiveColor=(1.0, 0.8, 0.2), diffuseColor=(0, 0, 0)))),
            self.sparks, self.fireworks,
            self.wheels.layers,
        ])
        '''=A wash=

        A `ScreenWash` is a colour over the whole window, and its `strength`
        is how solid.  It is the first child of the layer so the text is drawn
        over it.  It is off at strength 0, and a cleared or lost course sets
        its colour and turns it up.'''
        self.wash = ScreenWash(strength=0.0)
        self.readout = TextBlock(anchor='bottom-right', align='right', lines=[])
        self.addHUDLayer(HUDLayer(children=[self.wash, self.readout]))
        '''=Sound=

        `engine_for` is the context's audio engine, opened on first ask, or
        None where the definition has audio switched off, and a `Sounds`
        played into None does nothing.'''
        self.engine = audioscene.engine_for(self)
        self.sounds = Sounds()
        self.game = Game(on_event=self.OnGame)
        self.lay_out()
        for name in AIM_KEYS:
            self.addEventHandler('keypress', name=name, function=self.OnAim)
        for key in SELECT_KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnSelect)
        self.addEventHandler('keypress', name=' ', function=self.OnFire)
        self.addEventHandler('keypress', name='v', function=self.OnView)
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
        three elevations are fitted to the box round the course.  The plan
        shows wind and crossing targets best, and the `v` key steps between
        the four views and the cannon's view alone.

        Each view draws the scene's whole layer stack unless its style says
        otherwise, which would put a panel of wheels in all four.  The three
        elevations are styled without layers, so the wheels are in the
        cannon's view alone.'''
        views = self.startViews(arrangement='quad', bounds=lambda: self.game.course.bounds())
        for view in views.views:
            if not view.windowView:
                view.style = dataclasses.replace(view.style, layers=False)

    def OnView(self, event):
        self.toggleViews()

    def OnAim(self, event):
        self.game.adjust(**AIM_KEYS[event.name])
        self.update()

    def OnSelect(self, event):
        self.game.select(SELECT_KEYS[event.name])
        self.update()

    def OnWheel(self, name, value):
        '''A wheel sets the field a pair of keys steps, through the same
        `adjust`, so either can set up the next shot while a ball is in the air.'''
        self.game.set_aim(name, value)
        self.update()

    def OnGame(self, kind, detail):
        '''The game reports what happened; this is where it is seen and heard.
        The sparks and sounds come from the physics events, so they are where
        the ball really struck and as hard as it really struck.'''
        game = self.game
        if kind == 'fire':
            self.sounds.fire(self.engine, game.muzzle, game.aim.power)
        elif kind == 'impact' and detail.approach > IMPACT_SPEED:
            self.sounds.play(self.engine, 'thud', detail.point,
                             min(detail.approach / 20.0, 1.0), game.flying.pitch)
            if game.flying.sparks:
                self.sparks.burst_at(tuple(float(p) for p in detail.point),
                                     direction=tuple(float(n) for n in detail.normal))
        elif kind == 'crash':
            self.sounds.play(self.engine, 'crash', detail.point, min(detail.approach / 10.0, 1.0))
        elif kind == 'hit':
            self.sounds.play(self.engine, 'fanfare', game.position)
            self.fireworks.burst_at(game.position)
            self.wash.colour = WIN_WASH
            self.wash.strength = WASH_STRENGTH
        elif kind == 'lost':
            self.wash.colour = LOSE_WASH
            self.wash.strength = WASH_STRENGTH

    def OnFire(self, event):
        was = self.game.state
        '''A ball in the air has to settle or leave the area before the next
        is fired, and `fire` says whether it sent one.  A new course makes its
        nodes and bodies afresh, so what is left is to put the new nodes in the
        scene.  The path of the last shot stays on screen in blue to aim the
        next one by.'''
        if not self.game.fire():
            self.update()
            return
        self.wash.strength = 0.0
        if was in ('cleared', 'lost', 'finished'):
            self.ghost.point = [self.game.muzzle, self.game.muzzle]
            self.ghost_line.coordIndex = [0, 1, -1]
            self.lay_out()
            self.frameViews()
        else:
            self.ghost.point = list(self.trail.point)
            self.ghost_line.coordIndex = list(range(len(self.trail.point))) + [-1]
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
        '''The sounds are played directly rather than through a scene `Sound`,
        so nothing else moves the engine's listener.  The camera is the
        listener, and it has just moved, so the ears follow it here.'''
        if self.engine is not None:
            self.engine.listen(self.getViewPlatform())
        self.loaded.translation = game.muzzle
        if game.state == 'flying':
            path = list(self.trail.point)
            path.append(game.position)
            self.trail.point = path
            self.line.coordIndex = list(range(len(path))) + [-1]
        wanted = [] if game.state == 'flying' else [self.waiting[game.chosen]]
        if wanted != list(self.loaded.children):
            self.loaded.children = wanted
        self.wheels.show(game.aim)
        self.readout.lines = game.status()




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
