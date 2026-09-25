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

Walk onto the dark slate on the left to hear the cave, which echoes, and onto
the blue tiles on the right to hear the stream. Each is a zone: its sound fades
in over the last few metres, and the cave's reverb comes with it. Every sound
is generated at start-up, so the demo ships no audio files, and it runs
silently on a machine with no sound device. docs/audio.rst describes each of
these, and this file is the working code for them.
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from typing import Any, Optional

import numpy as np

from omi_audio import model, synth
from omi_audio.clip import DEFAULT_SAMPLE_RATE, Clip

from OpenGLContext.events.framestep import FrameStep
from OpenGLContext.physics.demo import DemoScene
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Appearance, AudioEmitter, AudioSource, Box, DirectionalLight, Shape, Sphere,
    Transform,
)
from OpenGLContext.scenegraph.zone import Zone, ZoneAudio, ZoneReverb

__all__ = ['AudioYard', 'Finishes', 'main']

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

#: The two areas: a zone each, the metres their sound fades over at the edge,
#: and the level it plays at inside.
CAVE_CENTRE = (-14.0, 1.0, -10.0)
STREAM_CENTRE = (14.0, 1.0, -10.0)
AREA_HALF_SIZE = (5.0, 4.0, 5.0)
AREA_MARGIN = 4.0
AREA_LEVEL = 0.6
#: The cave's reverb: how loud against the dry sound, and how long it rings,
#: in seconds.
CAVE_REVERB = 0.5
CAVE_DECAY = 2.5

#: How loud the whole demo plays. It runs at whatever volume the machine is at,
#: so it sits well below full scale; ``+`` and ``-`` move it.
MASTER_GAIN = 0.4


class Finishes:
    """The yard's materials, made once: stone, metals, slate and glazed tiles."""

    def __init__(self) -> None:
        self.floor = surfaces.pbr_material(surfaces.checkered_marble(512, tiles=8))
        self.balls = [
            surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.BRONZE, 0.3)),
            surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.STEEL, 0.2)),
        ]
        self.bell = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.GOLD, 0.2))
        self.rotor = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.STEEL, 0.35))
        self.post = surfaces.pbr_material(surfaces.sandstone(256))
        self.slate = surfaces.pbr_material(surfaces.sandstone(256, colour=(0.2, 0.21, 0.23)))
        self.water = surfaces.pbr_material(surfaces.tiles(256, count=6))


def _marker(material: Any, geometry: Any) -> Any:
    """A shape wearing ``material``."""
    return Shape(appearance=Appearance(material=material), geometry=geometry)


def _dress(body: Any, material: Any) -> Any:
    """Put ``material`` on a physics body's shape; return the body."""
    body.transform.children[0].appearance = Appearance(material=material)
    return body


def _bell_clip(sample_rate: int) -> Clip:
    """A struck bell: a bright tone that dies away over two seconds."""
    ringing = synth.tone(520.0, 2.0, sample_rate=sample_rate, amplitude=0.7,
                         harmonics=5)
    samples = np.asarray(ringing.samples, dtype=np.float32)
    decay = np.exp(-2.5 * np.arange(samples.size) / sample_rate).astype(np.float32)
    return Clip(samples * decay, sample_rate, name='bell')


class AudioYard:
    """The demo's world and its sounds, with no GL and no window.

    The context builds one, puts :meth:`scene` in front of the camera, takes
    each frame's time step from :attr:`frames`, calls :meth:`step` with it and
    forwards key presses to :meth:`drop`, :meth:`ring`, :meth:`fire`,
    :meth:`toggle_motor`, :meth:`toggle_muffle` and :meth:`change_volume`.
    Every method accepts a missing engine, which is what a machine with sound
    switched off has. The two areas are zones in :meth:`scene`, whose gains
    and reverb the render pass sets from where the camera is.
    """

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.finish = Finishes()
        #: The time step of each frame.
        self.frames = FrameStep(longest=0.1)
        self.physics = DemoScene(debug_flags=0)
        _dress(self.physics.add_box(size=(60.0, 1.0, 60.0), position=(0.0, -0.5, 0.0),
                                    dynamic=False), self.finish.floor)
        self.balls = [
            _dress(self.physics.add_sphere(radius=BALL_RADIUS,
                                           position=(x, BALL_RADIUS, z)),
                   self.finish.balls[number % len(self.finish.balls)])
            for number, (x, z) in enumerate(BALL_SPOTS)]
        #: Blows the balls took since the last frame, from every physics step
        #: of it. A pair of balls meeting is one entry, not two.
        self.blows: list[Any] = []
        self.physics.manager.events.subscribe(
            self.blows.append, body=self.balls, above=IMPACT_FLOOR)

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
            _marker(self.finish.rotor, Box(size=(2.4, 0.15, 0.3))),
        ])
        self.motor_on = False
        self.speed = 0.0
        self._angle = 0.0

        self.cave = AudioSource(loop=True, gain=AREA_LEVEL)
        self.cave.useClip(synth.rumble(2.0, sample_rate=sample_rate, decay=0.0,
                                       attack=0.0, cutoff=250.0, pitch=55.0,
                                       pitch_end=55.0, tone=0.4, seed=5))
        self.stream = AudioSource(loop=True, gain=AREA_LEVEL)
        self.stream.useClip(synth.noise(2.0, sample_rate=sample_rate,
                                        amplitude=0.3, seed=7, fade=0.0))
        #: The areas' sounds, one global emitter each, heard only inside
        #: their zones.
        self.cave_sound = AudioEmitter(type='global', sources=[self.cave])
        self.stream_sound = AudioEmitter(type='global', sources=[self.stream])

    def _area(self, centre: Sequence[float], material: Any,
              settings: Sequence[Any]) -> Any:
        """A pad on the ground and a zone over it, ``settings`` applying inside."""
        pad_height = 0.05
        size = tuple(2 * half for half in AREA_HALF_SIZE)
        return Transform(translation=tuple(centre), children=[
            Transform(translation=(0.0, pad_height - centre[1], 0.0), children=[
                _marker(material, Box(size=(size[0], 2 * pad_height, size[2])))]),
            Zone(size=size, blend=AREA_MARGIN, settings=list(settings)),
        ])

    def scene(self) -> Any:
        """The scenegraph: a light, the physics bodies, every sound's marker and the zones."""
        extra: list[Any] = [
            DirectionalLight(direction=(-0.3, -1.0, -0.5), intensity=0.9),
            Transform(translation=BELL_POSITION, children=[
                _marker(self.finish.bell, Sphere(radius=0.5)),
                AudioEmitter(refDistance=4.0, sources=[self.bell]),
            ]),
            Transform(translation=ROTOR_POSITION, children=[
                _marker(self.finish.post, Box(size=(0.4, 2.0, 0.4))),
                Transform(translation=(0.0, 1.1, 0.0), children=[self.rotor]),
                AudioEmitter(refDistance=3.0, sources=[self.motor]),
            ]),
            self._area(CAVE_CENTRE, self.finish.slate, [
                ZoneAudio(emitters=[self.cave_sound]),
                ZoneReverb(level=CAVE_REVERB, decay=CAVE_DECAY)]),
            self._area(STREAM_CENTRE, self.finish.water, [
                ZoneAudio(emitters=[self.stream_sound])]),
            self.cave_sound,
            self.stream_sound,
        ]
        return self.physics.scene_graph(extra=extra)

    def step(self, dt: float, engine: Any) -> int:
        """Advance the yard by ``dt`` seconds; return how many collision sounds it started."""
        started = self._collide(dt, engine)
        self._spin(dt)
        return started

    def _collide(self, dt: float, engine: Any) -> int:
        """Step the physics and thud for every blow a ball took."""
        self.physics.advance(dt)
        blows = self.blows[:]
        self.blows.clear()
        if engine is None:
            return 0
        started = 0
        for blow in blows:
            handle = engine.play(self.thud, emitter=self.placed, position=blow.point,
                                 gain=min(1.0, blow.approach / IMPACT_FULL),
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

    @staticmethod
    def toggle_muffle(engine: Any) -> float:
        """Muffle everything, as underwater, or stop; return the muffle now in force."""
        if engine is None:
            return 0.0
        engine.muffle = 0.0 if engine.muffle else 1.0
        return float(engine.muffle)

    @staticmethod
    def change_volume(audio: Any, delta: float) -> float:
        """Move the player's volume on ``audio`` by ``delta``, kept within 0 to 1; return it.

        ``audio`` is the context's audio settings (``contextDefinition.audio``),
        whose ``volume`` the F10 settings screen shows.
        """
        audio.volume = min(1.0, max(0.0, float(audio.volume) + delta))
        return float(audio.volume)


def main() -> int:                              # pragma: no cover - needs a window
    """Open the yard in a window."""
    argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0]).parse_args()
    from OpenGLContext import testingcontext
    from OpenGLContext.audio import scene as audioscene
    from OpenGLContext.contextdefinition import ContextDefinition
    from OpenGLContext.events import systemtime

    base: Any = testingcontext.getInteractive()

    class AudioDemoContext(base):
        """The yard in a window: keys in, the time step out."""

        #: The yard is dressed in metallic/roughness materials.
        renderer = 'pbr'

        initialPosition = (0, 1.6, 12)

        def OnInit(self) -> None:
            base.OnInit(self)
            self.yard = AudioYard()
            self.sg = self.yard.scene()
            engine = audioscene.engine_for(self)
            if engine is not None:
                engine.master_gain = MASTER_GAIN
            yard = self.yard
            for key, handler in (
                    ('b', yard.drop), ('g', yard.ring),
                    (' ', lambda: yard.fire(audioscene.existing_engine(self))),
                    ('r', yard.toggle_motor),
                    ('m', lambda: yard.toggle_muffle(audioscene.existing_engine(self))),
                    ('+', lambda: self.volume(0.1)), ('=', lambda: self.volume(0.1)),
                    ('-', lambda: self.volume(-0.1))):
                self.addEventHandler('keypress', name=key,
                                     function=lambda event, handler=handler: handler())
            yard.frames.step(systemtime.systemTime())
            print(__doc__, flush=True)
            print(audioscene.describe(self), flush=True)

        def OnIdle(self, *args: Any) -> int:
            dt = self.yard.frames.step(systemtime.systemTime())
            self.yard.step(dt, audioscene.existing_engine(self))
            self.triggerRedraw(1)
            return 1

        def volume(self, delta: float) -> None:
            level = self.yard.change_volume(self.contextDefinition.audio, delta)
            print('volume %.2f' % (level,), flush=True)

    AudioDemoContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext sound', size=(1024, 720)))
    return 0


if __name__ == '__main__':                      # pragma: no cover
    sys.exit(main())
