#! /usr/bin/env python
"""X3D sound under load: a document of many sounds, and what playing it costs.

    oglc-x3d-sound-stress [--stations N] [--seconds S] [--block FRAMES]
                          [--rate HZ] [--voices N] [--write DIR]

The document is ``x3d_sound_stress.x3d``, shipped with this module:
:data:`STATIONS` sounding stations on rings that turn about the listener,
between walls and over a floor with AcousticProperties. The stations take
eight forms in turn (:data:`FORMS`), which between them use every node of
X3D's Sound component and each of its modes: the three distance models,
cones, Doppler, HRTF panning, the eight filter types, the five wave types,
the three oversampling rates, clips and buffers read from files and held in
the document, and channels split, selected and merged. An AudioDestination
and a StreamAudioDestination carry a bus of unplaced sounds. Interpolators
turn the rings, sweep the filters and swell the gains, so every frame places
every sound again and redesigns every swept filter.

:func:`document` writes the same scene with any number of stations, and
:func:`measure` plays one with a silent device and times the two costs a
scene's sound has: the frame's (:class:`~OpenGLContext.audio.x3dgraph.SoundGraph`
kept in step, on the thread that draws) and the block's (the mixer, on the
audio thread, which renders only the nodes something is heard through). The command prints what :func:`measure` found; ``--write``
puts the document and the clips it names in a directory instead, to open
with ``oglc-view``. docs/audio.rst describes the report.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

__all__ = ['DOCUMENT', 'FORMS', 'STATIONS', 'Report', 'document', 'main', 'measure', 'prepare']

#: The X3D document shipped with this module: :func:`document` at :data:`STATIONS`.
DOCUMENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_sound_stress.x3d')
#: How many stations the shipped document has.
STATIONS = 128
#: What each form of station plays, in the order the stations take them.
FORMS = (
    'a Sound between two ellipsoids playing an AudioClip',
    'a SpatialSound with Doppler: an oscillator through a swept BiquadFilter and a Gain',
    'a SpatialSound with a cone and HRTF panning: an oscillator through a WaveShaper',
    'a SpatialSound playing a BufferAudioSource through a Delay',
    'a SpatialSound playing an AudioClip through a Convolver and a DynamicsCompressor',
    'a SpatialSound playing two channels split, selected and merged',
    'a SpatialSound with Doppler and HRTF panning: two oscillators through a Gain and an Analyser',
    'a SpatialSound not spatialised: an audio input and an oscillator through a Gain',
)
#: How many stations a ring holds.
RING = 16
#: The sample rate of the buffers the document holds, in hertz.
BUFFER_RATE = 4000

_FILTERS = ('LOWPASS', 'HIGHPASS', 'BANDPASS', 'LOWSHELF', 'HIGHSHELF', 'PEAKING', 'NOTCH',
            'ALLPASS')
_WAVES = ('SINE', 'SQUARE', 'SAWTOOTH', 'TRIANGLE', 'CUSTOM')
_OVERSAMPLING = ('NONE', '2X', '4X')
_MODELS = ('INVERSE', 'LINEAR', 'EXPONENTIAL')


def _numbers(values: Any) -> str:
    return ' '.join('%.3g' % (value,) for value in np.asarray(values, dtype='d').reshape(-1))


def _burst(index: int, channels: int = 1) -> str:
    """A tenth of a second of a decaying tone, each channel's samples after the last's"""
    times = np.arange(BUFFER_RATE // 10) / float(BUFFER_RATE)
    rows = [np.exp(-18.0 * times) * np.sin(2.0 * math.pi * (220.0 + 40.0 * (index % 9) + 110.0 * row)
                                           * times) for row in range(channels)]
    return _numbers(np.stack(rows))


def _room(index: int) -> str:
    """A short impulse response: the direct sound, then noise dying away"""
    response = np.random.default_rng(index).uniform(-1.0, 1.0, 256) * np.exp(
        -np.arange(256) / 48.0) * 0.3
    response[0] = 1.0
    return _numbers(response)


def _oscillator(index: int, frequency: float, indent: str) -> str:
    wave = _WAVES[index % len(_WAVES)]
    custom = ' optionsReal="0 0.6 0 0.25 0 0.1" optionsImag="0 0.5 0.3 0 0.15 0"' \
        if wave == 'CUSTOM' else ''
    return ('%s<OscillatorSource frequency="%g" detune="%d">\n'
            '%s  <PeriodicWave type="%s"%s/>\n'
            '%s</OscillatorSource>\n'
            % (indent, frequency, (index % 5) * 7, indent, wave, custom, indent))


def _station(index: int, routes: list[str]) -> str:
    """Station ``index``'s sound, as the X3D inside its Transform"""
    form, turn = index % len(FORMS), index // len(FORMS)
    pad = ' ' * 10
    tone = 110.0 * 2.0 ** ((index % 24) / 12.0)
    model = _MODELS[turn % len(_MODELS)]
    placed = 'priority="%.2f" referenceDistance="2" maxDistance="60" distanceModel="%s"' % (
        (index % 10) / 10.0, model)
    if form == 0:
        return ('%s<Sound spatialize="%s" priority="%.2f" intensity="0.5" direction="1 0 0" '
                'minFront="2" minBack="1" maxFront="40" maxBack="20">\n'
                '%s  <AudioClip url=\'"bell.wav"\' loop="true" pitch="%g"/>\n'
                '%s</Sound>\n'
                % (pad, 'false' if turn % 4 == 3 else 'true', (index % 10) / 10.0,
                   pad, 0.5 + 0.25 * (turn % 5), pad))
    if form == 1:
        name = 'Swept%d' % (index,)
        routes.append('    <ROUTE fromNode="Sweep" fromField="value_changed" toNode="%s" '
                      'toField="set_frequency"/>\n' % (name,))
        return ('%s<SpatialSound dopplerEnabled="true" %s>\n'
                '%s  <Gain gain="0.2">\n'
                '%s    <BiquadFilter DEF="%s" type="%s" frequency="900" qualityFactor="%g" '
                'gain="6">\n%s'
                '%s    </BiquadFilter>\n'
                '%s  </Gain>\n'
                '%s</SpatialSound>\n'
                % (pad, placed, pad, pad, name, _FILTERS[turn % len(_FILTERS)], 1.0 + turn % 4,
                   _oscillator(turn, tone, pad + '      '), pad, pad, pad))
    if form == 2:
        return ('%s<SpatialSound enableHRTF="true" coneInnerAngle="1.2" coneOuterAngle="3" '
                'coneOuterGain="0.2" direction="0 0 1" %s>\n'
                '%s  <WaveShaper gain="0.2" oversample="%s" curve="-0.8 -0.7 -0.45 0 0.45 0.7 0.8">\n%s'
                '%s  </WaveShaper>\n'
                '%s</SpatialSound>\n'
                % (pad, placed, pad, _OVERSAMPLING[turn % len(_OVERSAMPLING)],
                   _oscillator(turn + 1, tone, pad + '    '), pad, pad))
    if form == 3:
        return ('%s<SpatialSound %s>\n'
                '%s  <Delay gain="0.3" delayTime="%g" maxDelayTime="1">\n'
                '%s    <BufferAudioSource loop="true" numberOfChannels="1" sampleRate="%d" '
                'playbackRate="%g" detune="%d" loopStart="0.01" loopEnd="0.09"\n'
                '%s        buffer="%s"/>\n'
                '%s  </Delay>\n'
                '%s</SpatialSound>\n'
                % (pad, placed, pad, 0.05 + 0.05 * (turn % 8), pad, BUFFER_RATE,
                   0.75 + 0.25 * (turn % 4), (turn % 3) * 100, pad, _burst(index), pad, pad))
    if form == 4:
        return ('%s<SpatialSound %s>\n'
                '%s  <DynamicsCompressor threshold="-24" knee="20" ratio="%d" attack="0.004" '
                'release="0.2">\n'
                '%s    <Convolver gain="0.3" normalize="true"\n'
                '%s        buffer="%s">\n'
                '%s      <AudioClip url=\'"drum.wav"\' loop="true" pitch="%g"/>\n'
                '%s    </Convolver>\n'
                '%s  </DynamicsCompressor>\n'
                '%s</SpatialSound>\n'
                % (pad, placed, pad, 2 + turn % 10, pad, pad, _room(index), pad,
                   0.8 + 0.1 * (turn % 5), pad, pad, pad))
    if form == 5:
        name = 'Split%d' % (index,)
        return ('%s<SpatialSound %s>\n'
                '%s  <ChannelMerger gain="0.3">\n'
                '%s    <ChannelSelector channelSelection="1">\n'
                '%s      <ChannelSplitter DEF="%s">\n'
                '%s        <BufferAudioSource loop="true" numberOfChannels="2" sampleRate="%d"\n'
                '%s            buffer="%s"/>\n'
                '%s      </ChannelSplitter>\n'
                '%s    </ChannelSelector>\n'
                '%s    <ChannelSelector channelSelection="0">\n'
                '%s      <ChannelSplitter USE="%s"/>\n'
                '%s    </ChannelSelector>\n'
                '%s  </ChannelMerger>\n'
                '%s</SpatialSound>\n'
                % (pad, placed, pad, pad, pad, name, pad, BUFFER_RATE, pad, _burst(index, 2),
                   pad, pad, pad, pad, name, pad, pad, pad))
    if form == 6:
        name = 'Swell%d' % (index,)
        routes.append('    <ROUTE fromNode="Swell" fromField="value_changed" toNode="%s" '
                      'toField="set_gain"/>\n' % (name,))
        return ('%s<SpatialSound dopplerEnabled="true" enableHRTF="true" %s>\n'
                '%s  <Analyser fftSize="%d" smoothingTimeConstant="0.7">\n'
                '%s    <Gain DEF="%s" gain="0.15">\n%s%s'
                '%s    </Gain>\n'
                '%s  </Analyser>\n'
                '%s</SpatialSound>\n'
                % (pad, placed, pad, 256 << (turn % 4), pad, name,
                   _oscillator(0, tone, pad + '      '),
                   _oscillator(turn + 2, tone * 1.5, pad + '      '), pad, pad, pad))
    source = ('<MicrophoneSource description="The default input"/>' if turn % 2 == 0
              else '<StreamAudioSource description="The default input"/>')
    return ('%s<SpatialSound spatialize="false" %s>\n'
            '%s  <Gain gain="0.1">\n'
            '%s    %s\n%s'
            '%s  </Gain>\n'
            '%s</SpatialSound>\n'
            % (pad, placed, pad, pad, source, _oscillator(turn + 3, tone, pad + '    '), pad, pad))


def _bus(beds: int) -> str:
    """The destinations: ``beds`` unplaced tones under a compressor and an analyser"""
    pad = ' ' * 12
    tones = ''.join(
        '%s<BiquadFilter type="%s" frequency="%d" qualityFactor="2">\n%s%s</BiquadFilter>\n'
        % (pad, _FILTERS[bed % len(_FILTERS)], 300 + 150 * bed,
           _oscillator(bed, 55.0 * (1 + bed % 6), pad + '  '), pad)
        for bed in range(beds))
    return ('    <AudioDestination DEF="Speakers" maxChannelCount="2">\n'
            '      <DynamicsCompressor threshold="-18" ratio="6" attack="0.005" release="0.2">\n'
            '        <Analyser DEF="Meter" fftSize="512">\n'
            '          <Gain DEF="Bus" gain="0.05">\n%s'
            '          </Gain>\n'
            '        </Analyser>\n'
            '      </DynamicsCompressor>\n'
            '    </AudioDestination>\n'
            '    <StreamAudioDestination DEF="Stream" channelCountMode="EXPLICIT" '
            'channelInterpretation="DISCRETE">\n'
            '      <Gain gain="0.05">\n'
            '        <Delay delayTime="0.25" maxDelayTime="1">\n%s'
            '        </Delay>\n'
            '      </Gain>\n'
            '    </StreamAudioDestination>\n'
            % (tones, _oscillator(1, 82.5, pad)))


def document(stations: int = STATIONS) -> str:
    """The stress scene with ``stations`` stations, as X3D's XML encoding"""
    stations = max(1, int(stations))
    rings = (stations + RING - 1) // RING
    routes: list[str] = []
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<X3D profile="Full" version="4.0">\n'
        '  <head>\n'
        '    <component name="Sound" level="2"/>\n'
        '    <meta name="title" content="X3D sound under load"/>\n'
        '    <meta name="creator" content="OpenGLContext"/>\n'
        '    <meta name="license" content="BSD-3-Clause"/>\n'
        '    <meta name="generator" content="OpenGLContext.bin.x3d_sound_stress.document(%d)"/>\n'
        '    <meta name="description" content="%d sounding stations on turning rings, using every '
        'node and mode of the Sound component; oglc-x3d-sound-stress measures what playing it '
        'costs."/>\n'
        '  </head>\n'
        '  <Scene>\n'
        '    <WorldInfo title="X3D sound under load"/>\n'
        '    <NavigationInfo type=\'"EXAMINE" "ANY"\'/>\n'
        '    <Background skyColor="0.1 0.12 0.2 0.4 0.42 0.5" skyAngle="1.45" '
        'groundColor="0.2 0.18 0.16"/>\n'
        '    <Viewpoint description="Among the rings" position="0 %g %g" '
        'orientation="1 0 0 -0.5"/>\n'
        '    <DirectionalLight global="true" direction="-0.4 -0.8 -0.5" intensity="1.4"/>\n'
        '    <ListenerPointSource DEF="Ear" trackCurrentView="true"/>\n'
        '    <TimeSensor DEF="Clock" cycleInterval="12" loop="true"/>\n'
        '    <ScalarInterpolator DEF="Sweep" key="0 0.5 1" keyValue="300 4000 300"/>\n'
        '    <ScalarInterpolator DEF="Swell" key="0 0.25 0.5 0.75 1" '
        'keyValue="0.05 0.2 0.05 0.2 0.05"/>\n'
        '    <OrientationInterpolator DEF="Sunwise" key="0 0.5 1" '
        'keyValue="0 1 0 0  0 1 0 3.14159  0 1 0 6.28318"/>\n'
        '    <OrientationInterpolator DEF="Widdershins" key="0 0.5 1" '
        'keyValue="0 1 0 6.28318  0 1 0 3.14159  0 1 0 0"/>\n'
        % (stations, stations, 4.0 + 2.0 * rings, 6.0 + 3.0 * rings),
        '    <!-- A stone floor and four brass walls: each sound is heard at the share\n'
        '         of it the surfaces between it and the listener pass. -->\n'
        '    <Shape>\n'
        '      <Appearance>\n'
        '        <AcousticProperties absorption="0.05" diffuse="0.25" specular="0.7"/>\n'
        '        <PhysicalMaterial baseColor="0.55 0.5 0.45" metallic="0" roughness="0.9"/>\n'
        '      </Appearance>\n'
        '      <IndexedFaceSet coordIndex="0 1 2 3 -1" solid="false">\n'
        '        <Coordinate point="-%(far)g 0 %(far)g  %(far)g 0 %(far)g  %(far)g 0 -%(far)g  '
        '-%(far)g 0 -%(far)g"/>\n'
        '      </IndexedFaceSet>\n'
        '    </Shape>\n' % {'far': 6.0 + 2.0 * rings},
    ]
    for wall in range(4):
        angle = wall * math.pi / 2.0
        parts.append(
            '    <Transform translation="%g 1 %g" rotation="0 1 0 %g">\n'
            '      <Shape%s\n'
            '    </Transform>\n'
            % (3.0 * math.sin(angle), 3.0 * math.cos(angle), angle,
               ' USE="Wall"/>' if wall else
               ' DEF="Wall">\n'
               '        <Appearance>\n'
               '          <AcousticProperties absorption="0.3" diffuse="0.2" specular="0.3"/>\n'
               '          <PhysicalMaterial baseColor="0.9 0.7 0.35" metallic="1" roughness="0.4"/>\n'
               '        </Appearance>\n'
               '        <Box size="2.5 2 0.2"/>\n'
               '      </Shape>'))
    for ring in range(rings):
        members = range(ring * RING, min(stations, (ring + 1) * RING))
        radius = 4.0 + 2.0 * ring
        parts.append('    <Transform DEF="Ring%d">\n' % (ring,))
        for index in members:
            angle = 2.0 * math.pi * (index - ring * RING) / len(members)
            parts.append(
                '      <Transform translation="%.3f %g %.3f">\n'
                '        <Shape%s\n'
                '        <Group>\n%s'
                '        </Group>\n'
                '      </Transform>\n'
                % (radius * math.sin(angle), 1.0 + 0.5 * (index % 3), radius * math.cos(angle),
                   ' USE="Marker"/>' if index else
                   ' DEF="Marker">\n'
                   '          <Appearance>\n'
                   '            <PhysicalMaterial baseColor="0.95 0.6 0.4" metallic="1" '
                   'roughness="0.35"/>\n'
                   '          </Appearance>\n'
                   '          <Sphere radius="0.25"/>\n'
                   '        </Shape>',
                   _station(index, routes)))
        parts.append('    </Transform>\n')
        routes.append('    <ROUTE fromNode="%s" fromField="value_changed" toNode="Ring%d" '
                      'toField="set_rotation"/>\n'
                      % ('Widdershins' if ring % 2 else 'Sunwise', ring))
    parts.append(_bus(max(1, stations // len(FORMS))))
    for name in ('Sweep', 'Swell', 'Sunwise', 'Widdershins'):
        parts.append('    <ROUTE fromNode="Clock" fromField="fraction_changed" toNode="%s" '
                     'toField="set_fraction"/>\n' % (name,))
    parts.extend(routes)
    parts.append('  </Scene>\n</X3D>\n')
    return ''.join(parts)


def prepare(directory: str, stations: Optional[int] = None, force: bool = False) -> str:
    """The document written to ``directory`` with the clips it names; its path

    The shipped document where ``stations`` is None, :func:`document` at
    that size otherwise. Clips already there are kept unless ``force``.
    """
    from OpenGLContext.atomicfiles import copy_file, staged_file  # noqa: PLC0415 kept with its use
    from OpenGLContext.bin import x3d_sound  # noqa: PLC0415 the clips are that scene's
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(DOCUMENT))
    if stations is None:
        copy_file(DOCUMENT, target)
    else:
        with staged_file(target) as handle:
            handle.write(document(stations).encode('utf-8'))
    for name, made in (('bell.wav', x3d_sound.bell), ('drum.wav', x3d_sound.drum)):
        path = os.path.join(directory, name)
        if force or not os.path.exists(path):
            with staged_file(path) as handle:
                handle.write(made().wav_bytes())
    return target


@dataclass(frozen=True)
class Report:
    """What playing a document cost, from :func:`measure`

    Times are in milliseconds. ``frame`` is one frame's
    :meth:`~OpenGLContext.audio.x3dgraph.SoundGraph.update` on the drawing
    thread, ``block`` one :meth:`~omi_audio.mixer.Mixer.mix` of
    ``block_frames`` frames on the audio thread, each as the median and the
    worst of the run. ``block_time`` is how long a block plays for: a block
    that takes longer than that to mix is heard as a gap.
    """

    #: X3D sound nodes driven each frame, and the graph nodes the last block
    #: rendered: those something was heard through.
    nodes: int
    rendered: int
    #: Sound and SpatialSound nodes, and how many of them the voice budget hears.
    placed: int
    voices: int
    #: The first frame, which makes every graph node and reads every clip.
    first_frame: float
    frame: float
    frame_worst: float
    block: float
    block_worst: float
    block_frames: int
    sample_rate: int

    @property
    def block_time(self) -> float:
        """How long one block plays for, in milliseconds"""
        return 1000.0 * self.block_frames / self.sample_rate

    @property
    def load(self) -> float:
        """The share of real time the audio thread spends mixing: 1.0 is all of it"""
        return self.block / self.block_time

    @property
    def worst_load(self) -> float:
        """:attr:`load` for the slowest block; past 1.0 that block was late"""
        return self.block_worst / self.block_time

    def __str__(self) -> str:
        return ('%d sound nodes, %d rendered; %d placed sounds, %d voices\n'
                'first frame   %8.2f ms\n'
                'each frame    %8.2f ms  (worst %.2f)\n'
                'each block    %8.2f ms  (worst %.2f) of %d frames at %d Hz, which play for %.2f ms\n'
                'audio thread  %7.0f%%   of real time (worst block %.0f%%)'
                % (self.nodes, self.rendered, self.placed, self.voices, self.first_frame,
                   self.frame, self.frame_worst, self.block, self.block_worst,
                   self.block_frames, self.sample_rate, self.block_time,
                   100.0 * self.load, 100.0 * self.worst_load))


def measure(path: str, seconds: float = 2.0, block: Optional[int] = None, rate: int = 44100,
            voices: Optional[int] = None, fps: int = 60) -> Report:
    """Play the document at ``path`` for ``seconds`` of scene time and time it

    The scene is drawn in a hidden window on a clock stepped ``fps`` times a
    second, so its sensors and interpolators run as they do in a viewer, and
    is heard through a silent device at ``rate``. After each frame the mixer
    is asked for the ``block``-frame blocks that frame's time plays; where
    ``block`` is None it is the block a playback device asks for, omi_audio's
    ``DEFAULT_BUFFER_MSEC`` at ``rate``. ``voices`` is the voice budget
    (AudioSettings' where None).

    Raises:
        RuntimeError: where no core-profile GL context can be made.
        ValueError: where the document has no X3D sound nodes.
    """
    from omi_audio.device import DEFAULT_BUFFER_MSEC, NullDevice  # noqa: PLC0415 sound only when measured
    from omi_audio.engine import AudioEngine  # noqa: PLC0415 sound only when measured

    from OpenGLContext.audio import scene as audioscene  # noqa: PLC0415 kept with its use
    from OpenGLContext.audio.settings import settings_for  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders import background  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import x3dsound  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.glcontext import profile_unavailable  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 kept with its use
    from OpenGLContext.video.clock import FixedStepClock  # noqa: PLC0415 kept with its use
    refused = profile_unavailable('core')
    if refused:
        raise RuntimeError(refused)
    if block is None:
        block = rate * DEFAULT_BUFFER_MSEC // 1000
    scene = Loader.load(path)
    background.wait_for_idle(30.0)
    engine = AudioEngine(device=NullDevice(sample_rate=rate))
    frames: list[float] = []
    blocks: list[float] = []
    driven: tuple[Any, ...] = ()
    owed = 0.0
    with FixedStepClock(fps, start=1000.0) as clock, scene_context(
            scene, size=(96, 54), environment={'OPENGLCONTEXT_RENDERER': 'pbr'}) as context:
        audioscene.attach(context, engine)
        if voices is not None:
            settings_for(context).voices = int(voices)
        try:
            for _ in range(max(2, round(seconds * fps))):
                clock.advance()
                context.renderQueue.run()
                context.OnDraw(force=1)
                graph = audioscene.sound_graph(context)
                if graph is None:
                    raise ValueError('%s has no X3D sound nodes' % (path,))
                frames.append(graph.seconds)
                driven = graph.nodes
                owed += rate / float(fps)
                while owed >= block:
                    owed -= block
                    started = time.perf_counter()
                    engine.mixer.mix(block)
                    blocks.append(time.perf_counter() - started)
            placed = [found for found in driven if isinstance(found, x3dsound.Placed)]
            report = Report(
                nodes=len(driven), rendered=engine.graph.rendered, placed=len(placed),
                voices=min(len(placed), int(settings_for(context).voices)),
                first_frame=1000.0 * frames[0],
                frame=1000.0 * float(np.median(frames[1:])),
                frame_worst=1000.0 * max(frames[1:]),
                block=1000.0 * float(np.median(blocks)), block_worst=1000.0 * max(blocks),
                block_frames=block, sample_rate=rate)
        finally:
            audioscene.close(context)
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Measure the document, or write it"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-sound-stress', description=__doc__.split('\n')[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stations', type=int,
                        help='how many stations (default: the shipped document, %d)' % STATIONS)
    parser.add_argument('--seconds', type=float, default=2.0,
                        help='scene time to play (default: 2)')
    parser.add_argument('--block', type=int,
                        help='frames mixed at a time (default: what a playback device '
                             'asks for, 40 ms of them)')
    parser.add_argument('--rate', type=int, default=44100,
                        help='sample rate in hertz (default: 44100)')
    parser.add_argument('--voices', type=int,
                        help='the voice budget (default: the audio settings\')')
    parser.add_argument('--write', metavar='DIR',
                        help='write the document and its clips to DIR and measure nothing')
    options = parser.parse_args(argv)
    from OpenGLContext import userpaths  # noqa: PLC0415 only for main
    directory = options.write or os.path.join(userpaths.cachedirectory(), 'x3d-sound-stress')
    path = prepare(directory, options.stations)
    if options.write:
        print(path)
        return 0
    print(measure(path, seconds=options.seconds, block=options.block, rate=options.rate,
                  voices=options.voices))
    return 0


if __name__ == '__main__':
    sys.exit(main())
