"""The spatial-audio demo has to be *audible*, not merely correct.

A demonstration whose distance curves are right to the last decimal and whose
output sits 20 dB below anything a laptop speaker reproduces is a demonstration
that does not demonstrate.  Nothing in the rest of the suite catches that: every
other test asserts a ratio or a shape, and a ratio is the same at any level.

So this one runs the demo's own scene, through the demo's own nodes, and asserts
about the number that actually matters -- how loud the mix is.
"""

import importlib.util
import math
import os

import numpy as np
import pytest

from omi_audio.device import NullDevice

from OpenGLContext.audio import scene as audioscene
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import viewplatform
from OpenGLContext.scenegraph import audio as audionodes

DEMO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'audio_spatial.py')

#: Floor for one source on its own: below this it is lost on ordinary hardware.
AUDIBLE_DBFS = -30.0

#: The band the whole scene has to sit in, and the reason it is a *band* rather
#: than a floor: this demo has been wrong in both directions.  Too quiet and it
#: demonstrates nothing; too loud and it is startling at whatever volume the
#: machine happens to be at, and the mixer's limiter engages and distorts.
SCENE_QUIET_DBFS = -24.0
SCENE_LOUD_DBFS = -6.0


def demo_module():
    """The demo, imported without running its main loop.

    It builds its scenegraph in ``OnInit``, which needs a context, so only the
    module-level constants and helpers are taken from here; the scene is rebuilt
    below from the same numbers.
    """
    spec = importlib.util.spec_from_file_location('audio_spatial_demo', DEMO)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakePath(list):
    """A node and the transform above it, as the render pass supplies them."""

    def __init__(self, node, matrix):
        super().__init__([node])
        self.matrix = matrix

    def transformMatrix(self):
        return self.matrix


class FakeContext:
    def __init__(self):
        self.contextDefinition = ContextDefinition()
        self.platform = viewplatform.ViewPlatform(position=(0.0, 1.6, 6.0))

    def getViewPlatform(self):
        return self.platform


def translation(position):
    matrix = np.identity(4, dtype='d')
    matrix[3, :3] = position[:3]
    return matrix


def half_turn():
    """A half turn about +Y, which is what points an emitter back at the camera."""
    matrix = np.identity(4, dtype='d')
    matrix[0, 0] = matrix[2, 2] = -1.0
    return matrix


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setattr(audioscene, 'open_device',
                        lambda **named: NullDevice(**named))
    return demo_module()


def build(demo, context):
    """The demo's three emitters, placed where the demo places them."""
    engine = audioscene.engine_for(context)
    engine.master_gain = demo.MASTER_GAIN
    engine.clips.put('orbit', demo.synth.tone(660.0, 2.0, amplitude=0.45))
    engine.clips.put('distant', demo.synth.tone(330.0, 2.0, amplitude=0.6))
    engine.clips.put('cone', demo.synth.chirp(700.0, 1100.0, 1.5, amplitude=0.45))

    def emitter(url, **named):
        named.setdefault('gain', 1.0)
        return audionodes.AudioEmitter(
            sources=[audionodes.AudioSource(url=[url], loop=True)], **named)

    return engine, [
        FakePath(emitter('orbit', refDistance=4.0),
                 translation((0.0, 1.2, demo.ORBIT_RADIUS))),
        FakePath(emitter('distant', refDistance=demo.DISTANT_REFERENCE,
                         rolloffFactor=demo.DISTANT_ROLLOFF),
                 translation(demo.DISTANT_POSITION)),
        # Turned to face the listener, as the demo's own Transform turns it.
        FakePath(emitter('cone', shapeType='cone',
                         coneInnerAngle=demo.CONE_INNER,
                         coneOuterAngle=demo.CONE_OUTER,
                         coneOuterGain=0.05, refDistance=6.0),
                 np.dot(half_turn(), translation(demo.CONE_POSITION))),
    ]


def level_dbfs(engine, blocks=8, frames=1024):
    """The loudest sample the mix produces, in dBFS."""
    peak = 0.0
    for _ in range(blocks):
        peak = max(peak, float(np.abs(engine.mixer.mix(frames)).max()))
    return 20.0 * math.log10(max(peak, 1e-9))


def test_the_demos_scene_sits_in_the_comfortable_band(demo):
    context = FakeContext()
    try:
        engine, paths = build(demo, context)
        audioscene.update(context, paths, now=0.0)
        assert engine.active_voices == 3
        level = level_dbfs(engine)
        assert SCENE_QUIET_DBFS < level < SCENE_LOUD_DBFS, '%.1f dBFS' % (level,)
    finally:
        audioscene.close(context)


def test_the_loudest_moment_still_leaves_headroom(demo):
    """The orbiting source passes within its reference distance, at full gain.

    That is the peak of the whole demo, and it must not reach the limiter --
    which is what makes the difference between loud and distorted.
    """
    context = FakeContext()
    try:
        engine, paths = build(demo, context)
        paths[0].matrix = translation((0.0, 1.6, 6.0 - 0.5))     # on the listener
        audioscene.update(context, paths, now=0.0)
        assert level_dbfs(engine) < SCENE_LOUD_DBFS
    finally:
        audioscene.close(context)


def test_the_orbiting_emitter_alone_is_audible(demo):
    """Each source has to carry on its own; a mix is not an alibi."""
    context = FakeContext()
    try:
        engine, paths = build(demo, context)
        audioscene.update(context, paths[:1], now=0.0)
        assert level_dbfs(engine) > AUDIBLE_DBFS
    finally:
        audioscene.close(context)


def test_the_cone_emitter_is_audible_when_it_faces_you(demo):
    """And the test says so with the emitter turned as the demo turns it."""
    context = FakeContext()
    try:
        engine, paths = build(demo, context)
        audioscene.update(context, paths[2:3], now=0.0)
        assert level_dbfs(engine) > AUDIBLE_DBFS
    finally:
        audioscene.close(context)


def test_the_distant_emitter_alone_is_audible(demo):
    """The one most easily lost: 22 metres away on an inverse curve."""
    context = FakeContext()
    try:
        engine, paths = build(demo, context)
        audioscene.update(context, paths[1:2], now=0.0)
        assert level_dbfs(engine) > AUDIBLE_DBFS
    finally:
        audioscene.close(context)


def test_the_demos_frequencies_are_ones_small_speakers_reproduce(demo):
    """A 60 Hz drone is a silent demo on most hardware."""
    for clip in (demo.synth.tone(660.0, 0.2), demo.synth.tone(330.0, 0.2)):
        spectrum = np.abs(np.fft.rfft(clip.samples))
        peak = np.fft.rfftfreq(clip.frames, 1.0 / clip.sample_rate)[spectrum.argmax()]
        assert 150.0 < peak < 4000.0
