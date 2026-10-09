"""``oglc-x3d-sound``: the X3D sound scene, with no window and with a silent device."""
import os

import numpy as np
import pytest

from omi_audio.device import NullDevice
from omi_audio.engine import AudioEngine

from OpenGLContext.audio import scene as audioscene
from OpenGLContext.bin import x3d_sound
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph import x3dsound
from OpenGLContext.scenegraph.scenegraph import X3DScene
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context


@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    found = x3d_sound.SoundScene(str(tmp_path_factory.mktemp('sound')))
    assert background.wait_for_idle(20.0)
    return found


def test_it_reads_without_errors(demo):
    assert isinstance(demo.scene, X3DScene)
    assert not [problem for problem in demo.scene.problems if problem.severity == 'error']


def test_the_clips_and_images_it_names_are_written_beside_it(demo):
    assert {'x3d_sound.x3d', 'bell.wav', 'drum.wav', 'marble_base.png', 'steel_normal.png',
            'sandstone_mr.png'} <= set(os.listdir(demo.directory))


def test_the_clips_are_what_they_say():
    bell = x3d_sound.bell(8000)
    assert bell.sample_rate == 8000 and bell.frames == 24000
    assert np.abs(bell.samples[:800]).max() > 10 * np.abs(bell.samples[-800:]).max()
    drum = x3d_sound.drum(8000)
    assert drum.frames == 16000
    assert np.abs(drum.samples[:400]).max() > 0.5
    pings = x3d_sound.pings(8000)
    assert pings.shape == (2, 12000)
    assert np.abs(pings[0, :400]).max() > 0.3 and np.abs(pings[1, :400]).max() < 0.01
    room = x3d_sound.room(8000)
    assert room[0] == 1.0 and np.abs(room[-100:]).max() < 0.05


def test_it_uses_every_sound_node(demo):
    used = set()
    stack = list(demo.scene.children)
    while stack:
        found = stack.pop()
        if isinstance(found, x3dsound.SoundNode):
            used.add(type(found).__name__)
            stack.extend(found.audioInputs())
            if isinstance(found, x3dsound.OscillatorSource) and found.periodicWave:
                used.add(type(found.periodicWave).__name__)
        stack.extend(getattr(found, 'children', ()) or ())
    assert used >= {
        'Sound', 'AudioClip', 'SpatialSound', 'Gain', 'BiquadFilter', 'WaveShaper',
        'OscillatorSource', 'PeriodicWave', 'AudioDestination', 'DynamicsCompressor',
        'Analyser', 'BufferAudioSource', 'Delay', 'Convolver', 'ChannelMerger',
        'ChannelSelector', 'ChannelSplitter', 'MicrophoneSource', 'ListenerPointSource'}


def test_the_buffers_the_document_does_not_hold_are_set(demo):
    assert len(demo.node('Pings').buffer) == 2 * x3d_sound.RATE * 3 // 2
    assert len(demo.node('Room').buffer) > 1000


def test_the_keys_change_what_is_heard(demo):
    assert demo.press('d') == 'distortion on'
    assert demo.press('d') == 'distortion off'
    assert demo.press('f') == 'filter 4000 Hz'
    assert demo.press('f') == 'filter 300 Hz'
    assert demo.press('f') == 'filter 1200 Hz'
    assert demo.press('e') == 'echo off'
    assert demo.press('e') == 'echo on'
    assert demo.press('s') == 'chimes swapped'
    assert demo.press('s') == 'chimes as recorded'
    assert demo.press('l') == 'heard from the orbit'
    assert demo.press('l') == 'heard from the camera'
    assert demo.press('x') == ''


def test_the_bell_pauses_and_resumes(demo):
    clip = demo.node('BellClip')
    clip.setDuration(3.0)
    clip.advance(10.0)
    assert demo.press('b', 11.0) == 'bell paused'
    clip.advance(12.0)
    assert demo.press('b', 13.0) == 'bell resumed'
    clip.advance(14.0)
    assert clip.paused() is False


def test_a_meter_with_nothing_analysed_is_at_rest(tmp_path):
    scene = x3d_sound.SoundScene(str(tmp_path))
    assert np.array_equal(scene.showLevels(), np.zeros(x3d_sound.SoundScene.BARS))
    assert scene.node('Bar0').scale[1] == pytest.approx(0.05)


def test_it_is_heard_and_the_meter_rises(demo):
    """Drawn with a silent device: the pass drives the graph, the mix is pulled here."""
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    from OpenGLContext.video.clock import FixedStepClock
    engine = AudioEngine(device=NullDevice(sample_rate=44100))
    with FixedStepClock(30, start=1000.0) as clock, scene_context(
            demo.scene, size=(160, 90), environment={'OPENGLCONTEXT_RENDERER': 'pbr'}) as context:
        audioscene.attach(context, engine)
        for _ in range(10):
            clock.advance()
            context.renderQueue.run()
            context.OnDraw(force=1)
            engine.mixer.mix(1470)
            levels = demo.showLevels()
        graph = audioscene.sound_graph(context)
        heard = {type(found).__name__ for found in graph.heard}
        image = drawn_image(context)
        audioscene.close(context)
    assert heard == {'Sound', 'SpatialSound', 'AudioDestination'}
    assert demo.node('BellClip').isActive is True
    assert levels.max() > 0.3
    assert demo.node('Bar0').scale[1] > 0.05
    assert image.astype(int).sum(axis=2).max() > 300
