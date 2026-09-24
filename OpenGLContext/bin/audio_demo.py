#! /usr/bin/env python
"""Sound demonstration: collisions, events, areas and a sound that follows the simulation.

Walk around a yard with the arrow keys and press the keys it prints:

    oglc-audio-demo

    b      drop the balls; each bounce thuds, louder the harder it lands
    g      strike the bell, a sound that belongs to a node in the scene
    space  fire, a sound played through the engine with no place
    r      start or stop the motor; its pitch and level follow its speed
    m      muffle everything, as underwater
    + / -  the player's volume, the number the F10 settings screen shows

Walk into the dark pad on the left to hear the cave, and into the blue pad on
the right to hear the stream; each fades in over the last few metres. Every
sound is generated at start-up, so the demo ships no audio files, and it runs
silently on a machine with no sound device. docs/audio.rst describes each of
these, and this file is the working code for them.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from typing import Any, List, Optional, Sequence

import numpy as np

from omi_audio import model, synth
from omi_audio.clip import DEFAULT_SAMPLE_RATE, Clip

from OpenGLContext import testingcontext
from OpenGLContext.audio import scene as audioscene
from OpenGLContext.audio.areas import box_gain
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.physics.demo import DemoScene
from OpenGLContext.scenegraph.basenodes import (
    Appearance, AudioEmitter, AudioSource, Box, DirectionalLight, Material,
    Shape, Sphere, Transform,
)

BaseContext: Any = testingcontext.getInteractive()

#: Where the balls sit and are dropped from, in metres.
BALL_SPOTS = [(-2.0, 0.0), (-1.0, 0.6), (0.0, -0.4), (1.0, 0.5), (2.0, -0.2)]
BALL_RADIUS = 0.4
#: Heights the balls are dropped from, staggered so the thuds do not land
#: together.
DROP_HEIGHTS = [4.0, 5.0, 6.0, 7.0, 8.0]
#: Closing speed below which a contact is not a thud, and the one that is
#: full level, in metres per second.
IMPACT_FLOOR = 0.5
IMPACT_FULL = 10.0

BELL_POSITION = (-6.0, 2.0, 2.0)
ROTOR_POSITION = (6.0, 1.0, 2.0)
#: The motor's top speed in radians per second, and how quickly it gets there
#: and back, in radians per second per second.
MOTOR_TOP = 40.0
MOTOR_ACCELERATION = 15.0
MOTOR_LEVEL = 0.5

#: The two areas: a box each, the margin their sound fades over, and the level
#: it plays at inside.
CAVE_CENTRE = (-14.0, 1.0, -10.0)
STREAM_CENTRE = (14.0, 1.0, -10.0)
AREA_HALF_SIZE = (5.0, 4.0, 5.0)
AREA_MARGIN = 4.0
AREA_LEVEL = 0.6

#: How loud the whole demo plays. It runs at whatever volume the machine is at,
#: so it sits well below full scale; ``+`` and ``-`` move it.
MASTER_GAIN = 0.4


def _marker(colour: Sequence[float], geometry: Any) -> Any:
    """A lit shape in one colour."""
    return Shape(appearance=Appearance(material=Material(diffuseColor=colour)),
                 geometry=geometry)


def _bell_clip(sample_rate: int) -> Clip:
    """A struck bell: a bright tone that dies away over two seconds."""
    ringing = synth.tone(520.0, 2.0, sample_rate=sample_rate, amplitude=0.7,
                         harmonics=5)
    samples = np.asarray(ringing.samples, dtype=np.float32)
    decay = np.exp(-2.5 * np.arange(samples.size) / sample_rate).astype(np.float32)
    return Clip(samples * decay, sample_rate, name='bell')


class AudioYard:
    """The demo's world and its sounds, with no GL and no window.

    The context builds one, puts :meth:`scene` in front of the camera, calls
    :meth:`step` once a frame and forwards key presses to :meth:`drop`,
    :meth:`ring`, :meth:`fire` and :meth:`toggle_motor`. Every method accepts
    a missing engine, which is what a machine with sound switched off has.
    """

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.physics = DemoScene(debug_flags=0)
        self.physics.add_box(size=(60.0, 1.0, 60.0), position=(0.0, -0.5, 0.0),
                             dynamic=False, color=(0.45, 0.47, 0.4))
        self.balls = [
            self.physics.add_sphere(radius=BALL_RADIUS,
                                    position=(x, BALL_RADIUS, z),
                                    color=(0.9, 0.55, 0.2))
            for x, z in BALL_SPOTS]
        self._ball_indices = {ball.index for ball in self.balls}

        self.thud = synth.rumble(0.3, sample_rate=sample_rate, decay=16.0,
                                 cutoff=320.0, pitch=95.0, pitch_end=50.0,
                                 tone=0.5, drive=2.0, seed=3)
        self.shot = synth.rumble(0.45, sample_rate=sample_rate, decay=12.0,
                                 cutoff=1100.0, pitch=78.0, pitch_end=44.0,
                                 tone=0.26, drive=3.0, seed=11)
        #: Where a thud comes from: placed, and heard across the yard.
        self.placed = model.AudioEmitter(positional=model.PositionalProperties(
            refDistance=3.0, rolloffFactor=0.8))

        self.bell = AudioSource(autoplay=False, priority=0.6)
        self.bell.useClip(_bell_clip(sample_rate))

        self.motor = AudioSource(loop=True, gain=0.0)
        self.motor.useClip(synth.tone(110.0, 1.0, sample_rate=sample_rate,
                                      amplitude=0.5, fade=0.0, harmonics=7))
        self.rotor = Transform(rotation=(0.0, 1.0, 0.0, 0.0), children=[
            _marker((0.7, 0.7, 0.75), Box(size=(2.4, 0.15, 0.3))),
        ])
        self.motor_on = False
        self.speed = 0.0
        self._angle = 0.0

        self.cave = AudioSource(loop=True, gain=0.0)
        self.cave.useClip(synth.rumble(2.0, sample_rate=sample_rate, decay=0.0,
                                       attack=0.0, cutoff=250.0, pitch=55.0,
                                       pitch_end=55.0, tone=0.4, seed=5))
        self.stream = AudioSource(loop=True, gain=0.0)
        self.stream.useClip(synth.noise(2.0, sample_rate=sample_rate,
                                        amplitude=0.3, seed=7, fade=0.0))

    def scene(self) -> Any:
        """The scenegraph: a light, the physics bodies and every sound's marker."""
        pad_height = 0.05
        extra: List[Any] = [
            DirectionalLight(direction=(-0.3, -1.0, -0.5), intensity=0.9),
            Transform(translation=BELL_POSITION, children=[
                _marker((0.85, 0.75, 0.3), Sphere(radius=0.5)),
                AudioEmitter(refDistance=4.0, sources=[self.bell]),
            ]),
            Transform(translation=ROTOR_POSITION, children=[
                _marker((0.3, 0.3, 0.35), Box(size=(0.4, 2.0, 0.4))),
                Transform(translation=(0.0, 1.1, 0.0), children=[self.rotor]),
                AudioEmitter(refDistance=3.0, sources=[self.motor]),
            ]),
            Transform(translation=(CAVE_CENTRE[0], pad_height, CAVE_CENTRE[2]),
                      children=[_marker((0.2, 0.18, 0.22), Box(size=(
                          2 * AREA_HALF_SIZE[0], 2 * pad_height,
                          2 * AREA_HALF_SIZE[2])))]),
            Transform(translation=(STREAM_CENTRE[0], pad_height, STREAM_CENTRE[2]),
                      children=[_marker((0.25, 0.45, 0.8), Box(size=(
                          2 * AREA_HALF_SIZE[0], 2 * pad_height,
                          2 * AREA_HALF_SIZE[2])))]),
            AudioEmitter(type='global', sources=[self.cave, self.stream]),
        ]
        return self.physics.scene_graph(extra=extra)

    def step(self, dt: float, listener: Sequence[float], engine: Any) -> int:
        """Advance the yard by ``dt`` seconds with the listener at ``listener``.

        Returns how many collision sounds it started.
        """
        started = self._collide(dt, engine)
        self.cave.gain = AREA_LEVEL * box_gain(listener, CAVE_CENTRE,
                                               AREA_HALF_SIZE, AREA_MARGIN)
        self.stream.gain = AREA_LEVEL * box_gain(listener, STREAM_CENTRE,
                                                 AREA_HALF_SIZE, AREA_MARGIN)
        self._spin(dt)
        return started

    def _collide(self, dt: float, engine: Any) -> int:
        """Step the physics and thud for every ball that took a blow."""
        self.physics.advance(dt)
        if engine is None:
            return 0
        world = self.physics.world
        started = 0
        for ball in self.balls:
            struck = world.impact_on(ball.index, above=IMPACT_FLOOR)
            if struck is None:
                continue
            other, closing = struck
            # Two balls meeting is reported for both; one of them sounds it.
            if other in self._ball_indices and other < ball.index:
                continue
            handle = engine.play(self.thud, emitter=self.placed,
                                 position=world.position[ball.index],
                                 gain=min(1.0, closing / IMPACT_FULL),
                                 priority=0.3)
            started += handle is not None
        return started

    def _spin(self, dt: float) -> None:
        """Ease the motor towards its target speed; its sound follows."""
        target = MOTOR_TOP if self.motor_on else 0.0
        change = MOTOR_ACCELERATION * dt
        self.speed += max(-change, min(change, target - self.speed))
        self._angle = (self._angle + self.speed * dt) % (2.0 * math.pi)
        self.rotor.rotation = (0.0, 1.0, 0.0, self._angle)
        fraction = self.speed / MOTOR_TOP
        self.motor.gain = MOTOR_LEVEL * fraction
        self.motor.playbackRate = 0.6 + 1.4 * fraction

    def drop(self) -> None:
        """Lift every ball to its drop height and let go."""
        world = self.physics.world
        for ball, (x, z), height in zip(self.balls, BALL_SPOTS, DROP_HEIGHTS):
            world.place_body(ball.index, position=(x, height, z))
            world.linear_velocity[ball.index] = 0.0
            world.angular_velocity[ball.index] = 0.0
            world.wake(ball.index)

    def ring(self) -> None:
        """Strike the bell; it sounds on the next frame."""
        self.bell.play()

    def fire(self, engine: Any) -> Optional[Any]:
        """Fire the player's own weapon: centred, since it has no direction."""
        if engine is None:
            return None
        return engine.play(self.shot, gain=0.7, priority=0.7)

    def toggle_motor(self) -> None:
        """Start the motor, or let it run down."""
        self.motor_on = not self.motor_on


class AudioDemoContext(BaseContext):
    """The yard in a window: keys in, camera position and time step out."""

    initialPosition = (0, 1.6, 12)

    def OnInit(self) -> None:                   # pragma: no cover - needs a window
        BaseContext.OnInit(self)
        self.yard = AudioYard()
        self.sg = self.yard.scene()
        engine = audioscene.engine_for(self)
        if engine is not None:
            engine.master_gain = MASTER_GAIN
        for key, handler in (('b', self.OnDrop), ('g', self.OnRing),
                             (' ', self.OnFire), ('r', self.OnMotor),
                             ('m', self.OnMuffle), ('+', self.OnLouder),
                             ('=', self.OnLouder), ('-', self.OnQuieter)):
            self.addEventHandler('keypress', name=key, function=handler)
        self._last = time.time()
        print(__doc__, flush=True)
        print(audioscene.describe(self), flush=True)

    def OnIdle(self, *args: Any) -> int:        # pragma: no cover - needs a window
        now = time.time()
        dt, self._last = min(now - self._last, 0.1), now
        self.yard.step(dt, self.getViewPlatform().position,
                       audioscene.existing_engine(self))
        self.triggerRedraw(1)
        return 1

    def OnDrop(self, event: Any) -> None:       # pragma: no cover - needs a window
        self.yard.drop()

    def OnRing(self, event: Any) -> None:       # pragma: no cover - needs a window
        self.yard.ring()

    def OnFire(self, event: Any) -> None:       # pragma: no cover - needs a window
        self.yard.fire(audioscene.existing_engine(self))

    def OnMotor(self, event: Any) -> None:      # pragma: no cover - needs a window
        self.yard.toggle_motor()

    def OnMuffle(self, event: Any) -> None:     # pragma: no cover - needs a window
        engine = audioscene.existing_engine(self)
        if engine is not None:
            engine.muffle = 0.0 if engine.muffle else 1.0

    def OnLouder(self, event: Any) -> None:     # pragma: no cover - needs a window
        self._volume(0.1)

    def OnQuieter(self, event: Any) -> None:    # pragma: no cover - needs a window
        self._volume(-0.1)

    def _volume(self, delta: float) -> None:    # pragma: no cover - needs a window
        audio = self.contextDefinition.audio
        audio.volume = min(1.0, max(0.0, audio.volume + delta))
        print('volume %.2f' % (audio.volume,), flush=True)


def main() -> int:                              # pragma: no cover - needs a window
    argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0]).parse_args()
    AudioDemoContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext sound', size=(1024, 720)))
    return 0


if __name__ == '__main__':                      # pragma: no cover
    sys.exit(main())
