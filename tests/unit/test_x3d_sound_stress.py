"""``oglc-x3d-sound-stress``: the document of many sounds, and what playing it costs."""
import os
import xml.etree.ElementTree as ElementTree

import pytest

from OpenGLContext.bin import x3d_sound_stress as stress
from OpenGLContext.loaders import background
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import x3dsound
from OpenGLContext.scenegraph.scenegraph import X3DScene
from OpenGLContext.testing.glcontext import profile_unavailable


@pytest.fixture(scope='module')
def shipped(tmp_path_factory):
    """The shipped document's path, written with its clips."""
    return stress.prepare(str(tmp_path_factory.mktemp('stress')))


@pytest.fixture(scope='module')
def scene(shipped):
    found = Loader.load(shipped)
    assert background.wait_for_idle(30.0)
    return found


@pytest.fixture(scope='module')
def sounds(scene):
    """Every sound node of the shipped document, and each oscillator's wave."""
    found, seen = [], set()
    stack = list(scene.children)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        if isinstance(current, x3dsound.SoundNode):
            found.append(current)
            stack.extend(current.audioInputs())
            if isinstance(current, x3dsound.OscillatorSource) and current.periodicWave:
                stack.append(current.periodicWave)
        stack.extend(getattr(current, 'children', ()) or ())
    return found


@pytest.fixture
def needs_gl():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


def of(sounds, kind):
    return [found for found in sounds if isinstance(found, kind)]


class TestDocument:
    def test_the_shipped_document_is_the_generated_one(self):
        with open(stress.DOCUMENT, encoding='utf-8') as handle:
            assert handle.read() == stress.document(stress.STATIONS)

    def test_it_reads_without_errors(self, scene):
        assert isinstance(scene, X3DScene)
        assert not [problem for problem in scene.problems if problem.severity == 'error']

    def test_it_uses_every_sound_node(self, sounds):
        assert {type(found).__name__ for found in sounds} == set(x3dsound.NODES)

    def test_every_station_is_a_placed_sound(self, sounds):
        assert len(of(sounds, x3dsound.Placed)) == stress.STATIONS

    def test_every_form_has_as_many_stations(self, sounds):
        each = stress.STATIONS // len(stress.FORMS)
        assert len(of(sounds, x3dsound.Sound)) == each
        assert len(of(sounds, x3dsound.Convolver)) == each
        assert len(of(sounds, x3dsound.ChannelSplitter)) == each
        assert len(of(sounds, x3dsound.WaveShaper)) == each

    def test_it_uses_every_mode(self, sounds):
        def values(kind, name):
            return {str(getattr(found, name)) for found in of(sounds, kind)}
        assert values(x3dsound.BiquadFilter, 'type') == set(stress._FILTERS)
        assert values(x3dsound.PeriodicWave, 'type') == set(stress._WAVES)
        assert values(x3dsound.WaveShaper, 'oversample') == set(stress._OVERSAMPLING)
        assert values(x3dsound.SpatialSound, 'distanceModel') == set(stress._MODELS)
        for name in ('dopplerEnabled', 'enableHRTF', 'spatialize'):
            assert values(x3dsound.SpatialSound, name) == {'True', 'False'}, name
        assert values(x3dsound.Sound, 'spatialize') == {'True', 'False'}
        assert values(x3dsound.BufferAudioSource, 'numberOfChannels') == {'1', '2'}

    def test_the_buffers_are_in_the_document(self, sounds):
        for found in of(sounds, x3dsound.BufferAudioSource):
            assert len(found.buffer) == found.numberOfChannels * stress.BUFFER_RATE // 10
        assert {len(found.buffer) for found in of(sounds, x3dsound.Convolver)} == {256}

    def test_the_rings_filters_and_gains_are_routed(self):
        root = ElementTree.fromstring(stress.document(32))
        routes = [(route.get('fromNode'), route.get('toField')) for route in root.iter('ROUTE')]
        assert routes.count(('Sweep', 'set_frequency')) == 4
        assert routes.count(('Swell', 'set_gain')) == 4
        assert routes.count(('Sunwise', 'set_rotation')) == 1
        assert routes.count(('Widdershins', 'set_rotation')) == 1
        assert routes.count(('Clock', 'set_fraction')) == 4

    @pytest.mark.parametrize('stations', [1, 8, 40])
    def test_any_number_of_stations_can_be_written(self, stations):
        root = ElementTree.fromstring(stress.document(stations))
        placed = list(root.iter('Sound')) + list(root.iter('SpatialSound'))
        assert len(placed) == stations
        assert len(list(root.iter('AcousticProperties'))) == 2

    def test_fewer_than_one_station_is_one(self):
        assert stress.document(0) == stress.document(1)


class TestPrepare:
    def test_the_clips_are_written_beside_the_document(self, shipped):
        assert {'x3d_sound_stress.x3d', 'bell.wav', 'drum.wav'} <= set(
            os.listdir(os.path.dirname(shipped)))

    def test_a_number_of_stations_writes_that_document(self, tmp_path):
        path = stress.prepare(str(tmp_path), stations=8)
        with open(path, encoding='utf-8') as handle:
            assert handle.read() == stress.document(8)

    def test_clips_already_there_are_kept_unless_forced(self, tmp_path):
        stress.prepare(str(tmp_path), stations=1)
        bell = tmp_path / 'bell.wav'
        written = bell.read_bytes()
        bell.write_bytes(b'kept')
        stress.prepare(str(tmp_path), stations=1)
        assert bell.read_bytes() == b'kept'
        stress.prepare(str(tmp_path), stations=1, force=True)
        assert bell.read_bytes() == written


def report(**named):
    values = dict(nodes=40, rendered=38, placed=10, voices=8, first_frame=30.0, frame=1.5,
                  frame_worst=2.5, block=2.0, block_worst=12.0, block_frames=441,
                  sample_rate=44100)
    values.update(named)
    return stress.Report(**values)


class TestReport:
    def test_a_block_plays_for_its_frames_over_the_rate(self):
        assert report().block_time == pytest.approx(10.0)

    def test_the_load_is_the_blocks_time_over_what_it_plays_for(self):
        assert report().load == pytest.approx(0.2)
        assert report().worst_load == pytest.approx(1.2)

    def test_it_prints_each_reading(self):
        text = str(report())
        assert '40 sound nodes, 38 rendered; 10 placed sounds, 8 voices' in text
        assert 'each frame        1.50 ms  (worst 2.50)' in text
        assert 'of 441 frames at 44100 Hz, which play for 10.00 ms' in text
        assert '20%   of real time (worst block 120%)' in text


class TestCommand:
    def test_write_puts_the_document_in_a_directory_and_names_it(self, tmp_path, capsys):
        assert stress.main(['--write', str(tmp_path), '--stations', '8']) == 0
        path = capsys.readouterr().out.strip()
        assert path == str(tmp_path / 'x3d_sound_stress.x3d')
        assert os.path.exists(path) and (tmp_path / 'drum.wav').exists()

    def test_it_prints_what_it_measured(self, needs_gl, tmp_path, monkeypatch, capsys):
        from OpenGLContext import userpaths
        monkeypatch.setattr(userpaths, 'cachedirectory', lambda: str(tmp_path))
        assert stress.main(['--stations', '8', '--seconds', '0.1', '--block', '256',
                            '--rate', '22050', '--voices', '4']) == 0
        text = capsys.readouterr().out
        assert '8 placed sounds, 4 voices' in text
        assert 'of 256 frames at 22050 Hz' in text


class TestMeasure:
    def test_only_what_is_heard_is_rendered(self, needs_gl, tmp_path):
        path = stress.prepare(str(tmp_path), stations=32)
        every = stress.measure(path, seconds=0.25)
        few = stress.measure(path, seconds=0.25, voices=4)
        assert every.rendered > 0.9 * every.nodes
        assert few.rendered < every.rendered / 2

    def test_it_reports_the_document_it_played(self, needs_gl, tmp_path):
        found = stress.measure(stress.prepare(str(tmp_path), stations=16), seconds=0.25)
        assert found.placed == 16 and found.voices == 16
        assert found.nodes > 4 * 16 and 0 < found.rendered <= found.nodes
        assert 0.0 < found.frame <= found.frame_worst
        assert 0.0 < found.block <= found.block_worst
        assert found.first_frame > 0.0
        assert (found.block_frames, found.sample_rate) == (1764, 44100)

    def test_the_voice_budget_given_is_the_one_heard(self, needs_gl, tmp_path):
        found = stress.measure(stress.prepare(str(tmp_path), stations=16), seconds=0.1, voices=5)
        assert found.voices == 5

    def test_a_document_with_no_sound_is_refused(self, needs_gl, tmp_path):
        path = tmp_path / 'quiet.x3d'
        path.write_text('<X3D profile="Full" version="4.0"><Scene>'
                        '<Shape><Box/></Shape></Scene></X3D>')
        with pytest.raises(ValueError, match='no X3D sound nodes'):
            stress.measure(str(path), seconds=0.1)

    def test_without_gl_it_says_so(self, tmp_path, monkeypatch):
        from OpenGLContext.testing import glcontext
        monkeypatch.setattr(glcontext, 'profile_unavailable', lambda profile: 'no display here')
        with pytest.raises(RuntimeError, match='no display here'):
            stress.measure(str(tmp_path / 'never-read.x3d'))


@pytest.fixture(scope='module')
def sized(tmp_path_factory):
    """``sized(n)`` is the path of the document with ``n`` stations."""
    def path(stations):
        return stress.prepare(str(tmp_path_factory.mktemp('sized')), stations=stations)
    return path


@pytest.mark.serial
class TestCost:
    """What the document costs, each reading taken with the machine to itself."""

    def test_a_frame_grows_with_the_stations(self, needs_gl, sized, check_scaling):
        def prepare(stations):
            path = sized(stations)
            return lambda: stress.measure(path, seconds=0.5).frame
        check_scaling(prepare, n=32, most=6.0, measure='count')

    def test_a_block_grows_with_the_stations(self, needs_gl, sized, check_scaling):
        def prepare(stations):
            path = sized(stations)
            return lambda: stress.measure(path, seconds=0.5, voices=stations).block
        check_scaling(prepare, n=32, most=6.0, measure='count')

    def test_a_voice_budget_of_stations_is_mixed_in_a_quarter_of_the_time_it_plays_for(
            self, needs_gl, sized):
        found = stress.measure(sized(32), seconds=1.0)
        assert found.voices == 32
        assert found.load < 0.25, str(found)

    def test_the_shipped_document_is_mixed_in_a_quarter_of_the_time_it_plays_for(
            self, needs_gl, shipped):
        found = stress.measure(shipped, seconds=1.0)
        assert found.load < 0.25, str(found)

    def test_the_shipped_document_is_kept_in_step_in_half_a_frame(self, needs_gl, shipped):
        found = stress.measure(shipped, seconds=1.0)
        assert found.frame < 1000.0 / 60 / 2, str(found)

    def test_every_station_heard_at_once_is_mixed_faster_than_it_plays(self, needs_gl, shipped):
        found = stress.measure(shipped, seconds=1.0, voices=stress.STATIONS)
        assert found.voices == stress.STATIONS
        assert found.load < 0.8 and found.worst_load < 1.0, str(found)
