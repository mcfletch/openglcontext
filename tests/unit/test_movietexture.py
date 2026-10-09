"""MovieTexture: its url opened off the GL thread, its frame decoded on the GPU.

The timing is pyvrml97's (``vrml.x3d.media``); what is tested here is what the
engine adds: the url read in the background and reported to a LoadSensor,
``duration_changed`` from the movie, the frame for the node's media time in
each renderer, and the untextured draw with one logged reason where nothing
here decodes.

``tests/resources/colours.mp4`` is eight solid colours at four a second, 160 by
128, written by ``scripts/write_colours_movie.py`` with pyopengl-video's
encoder.
"""
import logging
import os
import subprocess
import sys
import textwrap

import numpy as np
import pytest
from vrml.x3d import loadsensor, media

from OpenGLContext.events import systemtime
from OpenGLContext.loaders import background
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, Material, MultiTexture, Shape, TextureProperties,
)
from OpenGLContext.scenegraph.movietexture import MovieTexture
from OpenGLContext.video import playback

COLOURS_MOVIE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'resources', 'colours.mp4')
#: The colour of each frame of the movie, a quarter of a second each.
COLOURS = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (0, 1, 1), (1, 0, 1), (1, 1, 1),
           (0, 0, 0)]

pyopengl_video = pytest.importorskip(
    'pyopengl_video', reason='MovieTexture reads movies through pyopengl-video')


class Clock:
    """The engine's time, held where a test puts it"""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    held = Clock(0.0)
    previous = systemtime.setTimeSource(held)
    yield held
    systemtime.setTimeSource(previous)


@pytest.fixture(autouse=True)
def fresh_reports():
    playback.forget_reports()
    yield
    playback.forget_reports()


def loaded(**fields):
    """A MovieTexture with its url read"""
    movie = MovieTexture(**fields)
    assert background.wait_for_idle(20.0)
    return movie


# ------------------------------------------------------------------ the node


def test_it_is_the_engines():
    assert prototypes()['MovieTexture'] is MovieTexture
    assert issubclass(MovieTexture, media.MovieTexture)


def test_its_url_is_read_in_the_background_and_reported(clock):
    movie = MovieTexture(url=[COLOURS_MOVIE])
    assert loadsensor.load_state(movie) in (loadsensor.LOADING, loadsensor.LOADED)
    assert background.wait_for_idle(20.0)
    assert loadsensor.load_state(movie) == loadsensor.LOADED
    assert movie.advance(clock.now)
    assert movie.duration_changed == pytest.approx(2.0)
    assert movie.cycle() == pytest.approx(2.0)


def test_the_first_entry_that_opens_is_the_movie(clock, tmp_path, caplog):
    notes = tmp_path / 'notes.txt'
    notes.write_text('not a movie')
    movie = loaded(url=[str(notes), COLOURS_MOVIE])
    movie.advance(clock.now)
    assert movie.duration_changed == pytest.approx(2.0)
    assert 'notes.txt' in caplog.text


def test_a_url_with_no_movie_fails(clock, tmp_path, caplog):
    other = tmp_path / 'film.avi'
    other.write_bytes(b'RIFF\x00\x10\x00\x00AVI LIST' + bytes(64))
    movie = loaded(url=[str(other)])
    assert loadsensor.load_state(movie) == loadsensor.FAILED
    movie.advance(clock.now)
    assert movie.duration_changed == -1
    assert 'AVI' in caplog.text
    assert movie.cached(None) is None


def test_a_document_reference_is_held_to_its_directory(clock, tmp_path):
    from OpenGLContext.loaders.loader import Loader
    document = tmp_path / 'scene.x3d'
    document.write_text(textwrap.dedent('''\
        <X3D profile="Full" version="4.0"><Scene>
          <Shape><Appearance><MovieTexture DEF="Film" url='"../outside.mp4" "film.mp4"'/>
          </Appearance><Box/></Shape>
        </Scene></X3D>'''))
    with open(COLOURS_MOVIE, 'rb') as source:
        data = source.read()
    (tmp_path / 'film.mp4').write_bytes(data)
    scene = Loader.load(str(document))
    assert background.wait_for_idle(20.0)
    movie = scene.getDEF('Film')
    assert loadsensor.load_state(movie) == loadsensor.LOADED
    movie.advance(clock.now)
    assert movie.duration_changed == pytest.approx(2.0)


def test_without_pyopengl_video_it_fails_with_one_reason(clock, monkeypatch, caplog):
    def missing(url, base):
        raise ImportError('No module named pyopengl_video')

    monkeypatch.setattr(playback, '_movie_class', missing)
    first = loaded(url=[COLOURS_MOVIE])
    second = loaded(url=[COLOURS_MOVIE])
    assert loadsensor.load_state(first) == loadsensor.FAILED
    assert loadsensor.load_state(second) == loadsensor.FAILED
    assert caplog.text.count('pyopengl-video') == 1


def test_it_shows_the_frame_for_its_media_time(clock):
    movie = loaded(url=[COLOURS_MOVIE], loop=True)
    clock.now = 0.6
    movie.advance(clock.now)
    assert movie.position() == pytest.approx(0.6)
    clock.now = 2.6
    movie.advance(clock.now)
    assert movie.position() == pytest.approx(0.6)


def test_before_it_starts_it_shows_the_first_frame_or_the_last_backwards(clock):
    forward = loaded(url=[COLOURS_MOVIE], startTime=100)
    backward = loaded(url=[COLOURS_MOVIE], startTime=100, speed=-1)
    forward.advance(clock.now)
    backward.advance(clock.now)
    assert forward.position() == 0.0
    assert backward.position() == pytest.approx(2.0)


def test_a_reversed_movie_runs_from_its_end(clock):
    movie = loaded(url=[COLOURS_MOVIE], loop=True, speed=-1)
    clock.now = 0.5
    movie.advance(clock.now)
    assert movie.position() == pytest.approx(1.5)


def test_it_holds_its_frame_while_paused_and_after_it_stops(clock):
    movie = loaded(url=[COLOURS_MOVIE], loop=True)
    clock.now = 0.5
    movie.advance(clock.now)
    movie.pauseTime = 0.5
    clock.now = 1.5
    movie.advance(clock.now)
    assert movie.isPaused
    assert movie.position() == pytest.approx(0.5)
    movie.stopTime = 1.6
    clock.now = 1.7
    movie.advance(clock.now)
    assert not movie.isActive
    assert movie.position() == pytest.approx(0.5)


def test_with_no_movie_it_binds_nothing():
    movie = MovieTexture()
    assert movie.cached(None) is None
    assert not movie.render(lit=1, mode=None)
    movie.renderPost(mode=None)
    assert not movie.hasAlpha()


def test_a_shape_it_textures_sorts_as_untextured_until_it_has_a_frame():
    appearance = Appearance(material=Material(), texture=MovieTexture())
    transparent, texture_token, _material = appearance.sortKey(None, np.identity(4))
    assert (transparent, texture_token) == (False, [])


# ------------------------------------------------------------------ playback


class FakePlayer:
    def __init__(self, fail_at=None):
        self.frame = None
        self.closed = False
        self.fail_at = fail_at

    def frame_at(self, seconds):
        if self.fail_at is not None and seconds >= self.fail_at:
            raise pyopengl_video.DecoderError('the slice data is corrupt')
        self.frame = int(seconds * 4)
        return 100 + self.frame

    def close(self):
        self.closed = True


class FakeTarget:
    def __init__(self, size, sampler):
        self.size = size
        self.sampler = sampler
        self.copied = []
        self.closed = False

    def copy_from(self, texture):
        self.copied.append(texture)

    def close(self):
        self.closed = True


class FakeMovie:
    size = (160, 128)


def made_playback(player):
    return playback.Playback(FakeMovie(), {'wrap_s': 'REPEAT'},
                             make_player=lambda movie: player, make_target=FakeTarget)


def test_a_frame_is_copied_once_however_often_it_is_asked_for():
    player = FakePlayer()
    shown = made_playback(player)
    target = shown.texture(0.3)
    assert shown.texture(0.4) is target
    shown.texture(0.6)
    assert target.copied == [101, 102]
    assert target.size == (160, 128)
    assert target.sampler == {'wrap_s': 'REPEAT'}


def test_no_decoder_is_no_texture_with_one_reason(caplog):
    def unavailable(movie):
        raise pyopengl_video.DecoderUnavailable('no decoder here can read 160x128 h264')

    first = playback.Playback(FakeMovie(), {}, make_player=unavailable, make_target=FakeTarget)
    second = playback.Playback(FakeMovie(), {}, make_player=unavailable, make_target=FakeTarget)
    with caplog.at_level(logging.WARNING):
        assert first.texture(0.0) is None
        assert first.texture(0.5) is None
        assert second.texture(0.0) is None
    assert caplog.text.count('no decoder here') == 1
    assert 'untextured' in caplog.text


def test_a_decoding_error_stops_the_movie_with_one_reason(caplog):
    player = FakePlayer(fail_at=1.0)
    shown = made_playback(player)
    target = shown.texture(0.5)
    assert target is not None
    with caplog.at_level(logging.WARNING):
        assert shown.texture(1.0) is None
        assert shown.texture(1.5) is None
    assert player.closed
    assert caplog.text.count('the slice data is corrupt') == 1


def test_closing_closes_the_player_and_the_target():
    player = FakePlayer()
    shown = made_playback(player)
    target = shown.texture(0.0)
    shown.close()
    assert player.closed and target.closed


# ------------------------------------------------------------------ drawn


def decoder_here():
    """Skip unless this GL context can decode H.264 through pyopengl-video"""
    from pyopengl_video import decoder as decoders
    reasons = decoders.explanations()
    if not list(decoders.available_backends()):
        pytest.skip('no video decoder for this GL context: %s' % ('; '.join(reasons) or 'none'))


def centre(children, environment=None, size=(32, 32)):
    from OpenGLContext.testing.scenes import drawn_image, scene_context
    with scene_context(children, size=size, environment=environment) as context:
        decoder_here()
        image = drawn_image(context)
    return image[size[1] // 2, size[0] // 2, :3].astype(float) / 255.0


class Mode:
    """What a texture node is drawn with: the context"""

    shader_mode = True

    def __init__(self, context):
        self.context = context


def screen(texture, material=None):
    return Shape(geometry=Box(size=(4, 4, 0.1)),
                 appearance=Appearance(material=material, texture=texture))


def assert_colour(found, expected):
    """The drawn colour has the frame's hue: the lit renderers shade it"""
    brightest = max(found)
    assert brightest > 0.3, found
    relative = found / brightest
    for channel, wanted in zip(relative, expected, strict=True):
        assert (channel > 0.7) if wanted else (channel < 0.5), (found, expected)


RENDERERS = [
    pytest.param({'OPENGLCONTEXT_RENDERER': 'pbr'}, id='pbr'),
    pytest.param({'OPENGLCONTEXT_RENDERER': 'vrml97'}, id='vrml97'),
    pytest.param({'OPENGLCONTEXT_PROFILE': 'compatibility',
                  'OPENGLCONTEXT_RENDERER': 'vrml97'}, id='compatibility'),
]


@pytest.mark.parametrize('environment', RENDERERS)
def test_its_frame_is_drawn_in_each_renderer(gl_context, clock, environment):
    clock.now = 0.6
    movie = loaded(url=[COLOURS_MOVIE], loop=True)
    assert_colour(centre([screen(movie)], environment), COLOURS[2])


@pytest.mark.parametrize('environment', RENDERERS)
def test_it_is_drawn_inside_a_multitexture(gl_context, clock, environment):
    clock.now = 0.5
    movie = loaded(url=[COLOURS_MOVIE], loop=True, speed=-1)
    layered = MultiTexture(texture=[movie], mode=['REPLACE'])
    assert_colour(centre([screen(layered)], environment), COLOURS[6])


def test_before_it_starts_the_first_frame_is_drawn(gl_context, clock):
    movie = loaded(url=[COLOURS_MOVIE], startTime=100)
    assert_colour(centre([screen(movie)]), COLOURS[0])


def test_its_sampler_follows_its_fields(gl_context, clock):
    from OpenGL import GL
    from OpenGLContext.testing.scenes import scene_context
    clamped = loaded(url=[COLOURS_MOVIE], repeatS=False, repeatT=False)
    nearest = loaded(url=[COLOURS_MOVIE], textureProperties=TextureProperties(
        boundaryModeS='MIRRORED_REPEAT', boundaryModeT='REPEAT',
        minificationFilter='NEAREST_PIXEL', magnificationFilter='NEAREST_PIXEL'))
    with scene_context([screen(clamped), screen(nearest)], size=(32, 32)) as context:
        decoder_here()
        mode = Mode(context)
        found = {}
        for node in (clamped, nearest):
            texture = node.cached(mode)
            GL.glBindTexture(GL.GL_TEXTURE_2D, texture.texture)
            found[node] = [int(GL.glGetTexParameteriv(GL.GL_TEXTURE_2D, name)) for name in (
                GL.GL_TEXTURE_WRAP_S, GL.GL_TEXTURE_WRAP_T, GL.GL_TEXTURE_MAG_FILTER)]
    assert found[clamped][:2] == [GL.GL_CLAMP_TO_EDGE, GL.GL_CLAMP_TO_EDGE]
    assert found[nearest] == [GL.GL_MIRRORED_REPEAT, GL.GL_REPEAT, GL.GL_NEAREST]


GLX_PROBE = textwrap.dedent('''\
    import logging, sys
    import glfw
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout)
    if not glfw.init():
        print('SKIP no X display'); sys.exit(0)
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_CREATION_API, glfw.NATIVE_CONTEXT_API)
    window = glfw.create_window(64, 64, 'glx', None, None)
    if not window:
        print('SKIP no GLX window'); sys.exit(0)
    glfw.make_context_current(window)
    from OpenGL import EGL
    if EGL.eglGetCurrentContext():
        print('SKIP the context is an EGL context'); sys.exit(0)
    from OpenGLContext.loaders import background
    from OpenGLContext.scenegraph.movietexture import MovieTexture

    class Mode:
        context = None
        shader_mode = True

    movie = MovieTexture(url=[sys.argv[1]], loop=True)
    background.wait_for_idle(20.0)
    print('FIRST', movie.cached(Mode()))
    print('SECOND', movie.cached(Mode()))
''')


def test_under_glx_it_is_drawn_untextured_with_one_reason(tmp_path):
    """The absent path on a GLX context: GLFW's X11 build, on an X display"""
    if not os.environ.get('DISPLAY'):
        pytest.skip('no X display to make a GLX context on')
    script = tmp_path / 'glx_probe.py'
    script.write_text(GLX_PROBE)
    environment = dict(os.environ, PYGLFW_LIBRARY_VARIANT='x11', XDG_SESSION_TYPE='x11')
    environment.pop('WAYLAND_DISPLAY', None)
    environment.pop('PYOPENGL_PLATFORM', None)
    result = subprocess.run([sys.executable, str(script), COLOURS_MOVIE], env=environment,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    if 'SKIP' in result.stdout:
        pytest.skip(result.stdout.split('SKIP', 1)[1].strip())
    assert 'FIRST None' in result.stdout and 'SECOND None' in result.stdout
    assert result.stdout.count('not an EGL context') == 1, result.stdout
