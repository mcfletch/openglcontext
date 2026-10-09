#! /usr/bin/env python
"""X3D sound: X3D's Sound component read from a document and heard.

    oglc-x3d-sound [--directory DIR] [--microphone]

    b      the bell paused and resumed
    d      the organ pipe's distortion on and off
    f      the organ pipe's filter stepped: 300, 1200, 4000 Hz
    e      the drum's echo off and on
    s      the chimes swapped between the ears
    l      heard from the camera, or from the centre of the orbit

The document is ``x3d_sound.x3d``, shipped with this module: a bronze bell
playing an AudioClip through a Sound, a copper organ pipe circling the
centre on a SpatialSound with Doppler, its sawtooth OscillatorSource shaped
by a WaveShaper and low-passed by a BiquadFilter, and a steel drum heard
through an AudioDestination, with a Delay for its echo, a Convolver for its
room, a DynamicsCompressor over the mix and an Analyser whose levels raise a
meter of eight bars. Two pings, one to each ear, are split by a
ChannelSplitter and put back by two ChannelSelectors into a ChannelMerger.
A MicrophoneSource is heard only with ``--microphone``. :func:`prepare`
writes the clips and the maps the document names beside a copy of it.
docs/audio.rst describes the nodes.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

import numpy as np

__all__ = ['DOCUMENT', 'RATE', 'SoundScene', 'bell', 'drum', 'main', 'pings', 'prepare', 'room']

#: The X3D document the scene is read from.
DOCUMENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_sound.x3d')
#: The sample rate the clips are written at, in hertz.
RATE = 22050
#: The organ pipe's filter frequencies, in hertz, as ``f`` steps through them.
FILTER_STEPS = (300.0, 1200.0, 4000.0)


def bell(rate: int = RATE, seconds: float = 3.0) -> Any:
    """A struck bell: five partials of 220 Hz, each dying away at its own rate"""
    from omi_audio.clip import Clip  # noqa: PLC0415 sound only when made
    times = np.arange(int(rate * seconds)) / float(rate)
    samples = np.zeros(times.shape[0])
    for ratio, level, decay in ((1.0, 0.5, 1.2), (2.0, 0.25, 1.8), (2.4, 0.2, 2.5),
                                (3.0, 0.12, 3.0), (4.5, 0.08, 4.0)):
        samples += level * np.exp(-decay * times) * np.sin(2.0 * math.pi * 220.0 * ratio * times)
    samples *= np.minimum(1.0, times / 0.004)
    return Clip(samples.astype(np.float32), rate, name='bell')


def drum(rate: int = RATE, seconds: float = 2.0) -> Any:
    """Two bars of drum at 120 beats a minute: a kick on the beat, a snare between"""
    from omi_audio.clip import Clip  # noqa: PLC0415 sound only when made
    frames = int(rate * seconds)
    samples = np.zeros(frames)
    hit = np.arange(int(rate * 0.25)) / float(rate)
    kick = 0.9 * np.exp(-14.0 * hit) * np.sin(2.0 * math.pi * (110.0 * hit - 60.0 * hit * hit))
    noise = np.random.default_rng(7).uniform(-1.0, 1.0, hit.shape[0])
    snare = 0.45 * np.exp(-22.0 * hit) * noise
    for beat in range(int(seconds * 2)):
        start = int(beat * rate / 2)
        part = kick if beat % 2 == 0 else snare
        end = min(frames, start + part.shape[0])
        samples[start:end] += part[:end - start]
    return Clip(samples.astype(np.float32), rate, name='drum')


def pings(rate: int = RATE, seconds: float = 1.5) -> np.ndarray:
    """Two channels: a high ping on the left, a lower one on the right half a loop later"""
    times = np.arange(int(rate * seconds)) / float(rate)
    later = (times - seconds / 2.0) % seconds
    left = 0.6 * np.exp(-6.0 * times) * np.sin(2.0 * math.pi * 1320.0 * times)
    right = 0.6 * np.exp(-6.0 * later) * np.sin(2.0 * math.pi * 990.0 * later)
    return np.stack([left, right]).astype(np.float32)


def room(rate: int, seconds: float = 0.35) -> np.ndarray:
    """A small room's impulse response at ``rate``: noise dying away, the direct sound first"""
    frames = int(rate * seconds)
    times = np.arange(frames) / float(rate)
    response = np.random.default_rng(11).uniform(-1.0, 1.0, frames) * np.exp(-12.0 * times)
    response[0] = 1.0
    return response.astype(np.float32)


def _surface(name: str) -> Any:
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    if name == 'marble':
        return surfaces.checkered_marble(256, tiles=2)
    if name == 'steel':
        return surfaces.brushed_metal(256)
    return surfaces.sandstone(256)


def prepare(directory: str, force: bool = False) -> str:
    """The document, copied to `directory` with the clips and images it names

    Files already there are kept unless `force`. Returns the copy's path.
    """
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import copy_file, staged_file  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 only when written
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(DOCUMENT))
    copy_file(DOCUMENT, target)
    for name in ('marble', 'sandstone', 'steel'):
        paths = [os.path.join(directory, '%s_%s.png' % (name, part))
                 for part in ('base', 'mr', 'normal')]
        if force or not all(os.path.exists(path) for path in paths):
            for path, pixels in zip(paths, surfaces.images(_surface(name)), strict=True):
                with staged_file(path) as handle:
                    Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    for name, made in (('bell.wav', bell), ('drum.wav', drum)):
        path = os.path.join(directory, name)
        if force or not os.path.exists(path):
            with staged_file(path) as handle:
                handle.write(made().wav_bytes())
    return target


class SoundScene:
    """The scene with no window: what the demo and its tests share

    ``scene`` is the document read by the engine's loader, with the two
    buffers a document cannot hold compactly set from code: the pings'
    samples and the room's impulse response.
    """

    KEYS: ClassVar[dict[str, str]] = {
        'b': 'the bell paused and resumed',
        'd': "the organ pipe's distortion on and off",
        'f': "the organ pipe's filter stepped: 300, 1200, 4000 Hz",
        'e': "the drum's echo off and on",
        's': 'the chimes swapped between the ears',
        'l': 'heard from the camera, or from the centre of the orbit',
    }

    #: How many bars the meter has.
    BARS = 8

    def __init__(self, directory: str, room_rate: int = 44100) -> None:
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        self.scene = Loader.load(self.path)
        found = self.scene.getDEF('Pings')
        found.buffer = pings().reshape(-1)
        found.sampleRate = float(RATE)
        self.scene.getDEF('Room').buffer = room(room_rate)

    def node(self, name: str) -> Any:
        """The node the document names `name`"""
        return self.scene.getDEF(name)

    def press(self, key: str, now: float = 0.0) -> str:
        """Answer a key at engine time `now`; what it did, for the console"""
        if key == 'b':
            clip = self.node('BellClip')
            if clip.paused():
                clip.resumeTime = now
                return 'bell resumed'
            clip.pauseTime = now
            return 'bell paused'
        if key == 'd':
            shaper = self.node('Distortion')
            shaper.enabled = not shaper.enabled
            return 'distortion %s' % ('on' if shaper.enabled else 'off')
        if key == 'f':
            pipe = self.node('PipeFilter')
            steps = FILTER_STEPS
            at = min(range(len(steps)), key=lambda index: abs(steps[index] - pipe.frequency))
            pipe.frequency = steps[(at + 1) % len(steps)]
            return 'filter %g Hz' % (pipe.frequency,)
        if key == 'e':
            echo = self.node('EchoLevel')
            echo.gain = 0.0 if echo.gain else 0.4
            return 'echo %s' % ('on' if echo.gain else 'off')
        if key == 's':
            left, right = self.node('LeftEar'), self.node('RightEar')
            left.channelSelection, right.channelSelection = (
                right.channelSelection, left.channelSelection)
            return 'chimes %s' % ('swapped' if left.channelSelection else 'as recorded')
        if key == 'l':
            ear = self.node('Ear')
            ear.trackCurrentView = not ear.trackCurrentView
            return 'heard from %s' % ('the camera' if ear.trackCurrentView else 'the orbit')
        return ''

    def levels(self) -> np.ndarray:
        """The meter's eight levels from 0 to 1: the Analyser's bins, grouped"""
        found = self.node('Meter').byteFrequencyData()
        if found.shape[0] < self.BARS:
            return np.zeros(self.BARS)
        groups = np.array_split(found.astype(np.float64) / 255.0, self.BARS)
        return np.array([group.max() for group in groups])

    def showLevels(self) -> np.ndarray:
        """Raise the meter's bars to :meth:`levels`; the levels shown"""
        shown = self.levels()
        for index, level in enumerate(shown):
            height = 0.05 + 1.2 * float(level)
            bar = self.node('Bar%d' % (index,))
            bar.scale = (1.0, height, 1.0)
            bar.translation = (bar.translation[0], height / 2.0, bar.translation[2])
        return shown

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the scene in a window"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-sound', description=__doc__.split('\n')[0],
        epilog=SoundScene.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', help='where the document, its clips and images are '
                        'written (default: the user cache directory)')
    parser.add_argument('--microphone', action='store_true',
                        help='let the MicrophoneSource open the default input')
    options = parser.parse_args(argv)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.audio.settings import AudioSettings  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    from OpenGLContext.events import systemtime  # noqa: PLC0415 a window only for main
    from OpenGLContext.events.renderqueue import DEFER  # noqa: PLC0415 a window only for main
    directory = options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-sound')
    base: Any = testingcontext.getInteractive()

    class SoundContext(base):                   # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.sound = SoundScene(directory)
            self.sg = self.sound.scene
            for key in SoundScene.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            self.renderQueue.call(self.meter)
            print(SoundScene.help())

        def meter(self) -> Any:
            self.sound.showLevels()
            self.triggerRedraw(1)
            return DEFER

        def OnKey(self, event: Any) -> None:
            said = self.sound.press(event.name, systemtime.systemTime())
            if said:
                print(said)
                self.triggerRedraw(1)

    definition = ContextDefinition(title='OpenGLContext X3D sound', size=(1280, 720),
                                   renderer='pbr')
    definition.audio = AudioSettings(microphone=options.microphone)
    SoundContext.ContextMainLoop(definition=definition)
    return 0


if __name__ == '__main__':
    sys.exit(main())
