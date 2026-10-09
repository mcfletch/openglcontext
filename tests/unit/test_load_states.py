"""The engine's url nodes record their load state, and a LoadSensor watches it.

An Inline or ImageTexture records ``loading`` when it starts to read its url,
``loaded`` when it has read one, and ``failed`` when none read
(``vrml.x3d.loadsensor``). The engine's LoadSensor is polled by each context
it is bound to, as a TimeSensor is.
"""
import io

import pytest
from PIL import Image
from vrml.x3d import loadsensor
from vrml.x3d.loadsensor import FAILED, LOADED, LOADING

from OpenGLContext.events.timeeventgeneratormanager import TimeEventGeneratorManager
from OpenGLContext.loaders import background
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import x3druntime
from OpenGLContext.scenegraph.imagetexture import ImageTexture
from OpenGLContext.scenegraph.inline import Inline


@pytest.fixture
def held(monkeypatch):
    """Background loads recorded rather than started"""
    started = []
    monkeypatch.setattr(background, 'load_in_background',
                        lambda key, function, *arguments, **named: started.append(
                            (function, arguments)))
    return started


def png(path):
    Image.new('RGB', (2, 2), (0, 255, 0)).save(path)
    return str(path)


def test_an_image_texture_loading_and_loaded(held, tmp_path):
    texture = ImageTexture()
    texture.url = [png(tmp_path / 'green.png')]
    assert loadsensor.load_state(texture) == LOADING
    function, arguments = held[-1]
    function(*arguments)
    assert loadsensor.load_state(texture) == LOADED


def test_an_image_texture_that_reads_nothing_failed(held, tmp_path):
    texture = ImageTexture()
    texture.url = [str(tmp_path / 'missing.png')]
    function, arguments = held[-1]
    function(*arguments)
    assert loadsensor.load_state(texture) == FAILED


def test_an_image_from_data_is_loaded():
    data = io.BytesIO()
    Image.new('RGB', (2, 2)).save(data, format='PNG')
    texture = ImageTexture()
    texture.loadFromData(data.getvalue())
    assert loadsensor.load_state(texture) == LOADED


def test_an_inline_loading_loaded_and_failed(held, tmp_path):
    good = tmp_path / 'good.x3d'
    good.write_text('<X3D version="4.0"><Scene><Group/></Scene></X3D>')
    inline = Inline()
    inline.url = [str(good)]
    assert loadsensor.load_state(inline) == LOADING
    function, arguments = held[-1]
    function(*arguments)
    assert loadsensor.load_state(inline) == LOADED
    inline.url = [str(tmp_path / 'missing.x3d')]
    function, arguments = held[-1]
    function(*arguments)
    assert loadsensor.load_state(inline) == FAILED


def test_an_inline_not_loading_records_nothing(held):
    inline = Inline(load=False)
    inline.url = ['anything.x3d']
    assert loadsensor.load_state(inline) is None


def test_the_load_sensor_is_the_engines_and_polled():
    sensor_class = prototypes()['LoadSensor']
    assert sensor_class is x3druntime.LoadSensor
    texture = ImageTexture()
    loadsensor.set_load_state(texture, LOADED)
    sensor = sensor_class(children=[texture])

    class Timing:
        manager = TimeEventGeneratorManager()

        def getTimeManager(self):
            return self.manager

    context = Timing()
    sensor.bind(context)
    assert context.manager(context) == 1
    assert sensor.isLoaded is True


def test_a_documents_load_sensor_sees_its_texture_load(gl_context, tmp_path):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    png(tmp_path / 'green.png')
    document = tmp_path / 'scene.x3d'
    document.write_text('''<X3D version="4.0"><Scene>
      <Shape><Appearance><ImageTexture DEF="TEX" url='"green.png"'/></Appearance><Box/></Shape>
      <LoadSensor DEF="L"><ImageTexture USE="TEX" containerField="children"/></LoadSensor>
    </Scene></X3D>''')
    scene = Loader.load(str(document))
    with scene_context(scene) as context:
        # Bound as the first frame walks the scene; polled from the next.
        context.OnDraw(force=1)
        background.wait_for_idle(10.0)
        context.OnDraw(force=1)
    assert scene.getDEF('L').isLoaded is True


@pytest.fixture
def audio_engine():
    from omi_audio import synth  # noqa: PLC0415 kept with its use
    from omi_audio.device import NullDevice  # noqa: PLC0415 kept with its use
    from omi_audio.engine import AudioEngine  # noqa: PLC0415 kept with its use
    made = AudioEngine(device=NullDevice(sample_rate=8000), voices=4)
    made.clips.put('beep', synth.tone(440.0, 0.25, sample_rate=8000))
    yield made
    made.close()


@pytest.mark.parametrize('name', ['AudioClip', 'BufferAudioSource'])
def test_a_sound_file_read_is_loaded_or_failed(audio_engine, name):
    node_class = prototypes()[name]
    found = node_class(url=['beep'])
    assert loadsensor.load_state(found) is None
    found.playedSamples(audio_engine)
    assert loadsensor.load_state(found) == LOADED
    missing = node_class(url=['nowhere.wav'])
    missing.playedSamples(audio_engine)
    assert loadsensor.load_state(missing) == FAILED


def test_samples_in_the_buffer_read_no_url(audio_engine):
    source = prototypes()['BufferAudioSource'](buffer=[0.0, 0.5], numberOfChannels=1)
    source.playedSamples(audio_engine)
    assert loadsensor.load_state(source) is None


def test_a_movie_with_a_url_failed():
    movie_class = prototypes()['MovieTexture']
    assert loadsensor.load_state(movie_class(url=['film.mp4'])) == FAILED
    assert loadsensor.load_state(movie_class()) is None


def test_an_anchor_is_loaded():
    assert loadsensor.load_state(prototypes()['Anchor'](url=['#there'])) == LOADED
