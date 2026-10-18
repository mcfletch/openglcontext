"""``oglc-x3d-movie``: the room of screens, its film, and its keys."""
import os
import subprocess

import numpy as np
import pytest
from vrml.x3d import loadsensor

from OpenGLContext.bin import x3d_movie
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph.movietexture import MovieTexture
from OpenGLContext.scenegraph.scenegraph import X3DScene

COLOURS_MOVIE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'resources', 'colours.mp4')

pytest.importorskip('pyopengl_video', reason='the screens read their film through pyopengl-video')


@pytest.fixture
def demo(tmp_path):
    found = x3d_movie.MovieScene(str(tmp_path), COLOURS_MOVIE)
    assert background.wait_for_idle(20.0)
    return found


def test_it_reads_without_errors(demo):
    assert isinstance(demo.scene, X3DScene)
    assert not [problem for problem in demo.scene.problems if problem.severity == 'error']


def test_the_maps_the_vignette_and_the_film_are_written_beside_it(demo):
    names = set(os.listdir(demo.directory))
    assert {'x3d_movie.x3d', 'vignette.png', 'film.mp4'} <= names
    for material in x3d_movie.MATERIALS:
        assert {'%s_base.png' % material, '%s_mr.png' % material,
                '%s_normal.png' % material} <= names


def test_three_screens_play_the_film(demo):
    looping, reversed_, keyed = (demo.node(name) for name in ('Looping', 'Reversed', 'Keyed'))
    for movie in (looping, reversed_, keyed):
        assert isinstance(movie, MovieTexture)
        assert loadsensor.load_state(movie) == loadsensor.LOADED
    assert looping.loop and float(looping.speed) == 1
    assert reversed_.loop and float(reversed_.speed) == -1
    assert reversed_.textureProperties is not None
    assert not keyed.loop and not keyed.repeatS and not keyed.repeatT


def test_the_keyed_screen_waits_on_its_first_frame_until_s_starts_it(demo):
    keyed = demo.node('Keyed')
    keyed.advance(10.0)
    assert not keyed.running()
    assert keyed.position() == 0.0
    assert demo.press('s', 10.0) == 'right-hand film started'
    keyed.advance(10.5)
    assert keyed.isActive
    assert keyed.position() == pytest.approx(0.5)
    assert demo.press('s', 10.6) == 'the right-hand film is already playing'


def test_p_pauses_and_resumes_the_looping_screen(demo):
    looping = demo.node('Looping')
    looping.advance(1.0)
    assert demo.press('p', 1.0) == 'left-hand film paused'
    looping.advance(1.5)
    assert looping.isPaused
    assert demo.press('p', 1.5) == 'left-hand film resumed'
    looping.advance(2.0)
    assert not looping.isPaused
    assert demo.press('x', 2.0) == ''


def test_the_help_names_each_key():
    assert all(key in x3d_movie.MovieScene.help() for key in x3d_movie.MovieScene.KEYS)


def test_the_vignette_is_white_in_the_middle_and_darker_at_the_edges():
    picture = x3d_movie.vignette(64)
    assert picture.shape == (64, 64, 3) and picture.dtype == np.uint8
    assert picture[32, 32, 0] == 255
    assert picture[0, 0, 0] < 128
    assert (picture[:, :, 0] == picture[:, :, 2]).all()


def test_a_film_already_made_is_kept(tmp_path, monkeypatch):
    film = tmp_path / 'film.mp4'
    film.write_bytes(b'made')
    monkeypatch.setattr(subprocess, 'run', lambda *args, **named: pytest.fail('made again'))
    assert x3d_movie.make_film(str(film)) == str(film)


def test_the_film_is_made_in_a_directory_that_is_not_there_yet(tmp_path, monkeypatch):
    film = tmp_path / 'cache' / 'x3d-movie' / 'film.mp4'

    def records(command, **named):
        with open(command[-1], 'wb') as handle:
            handle.write(b'film')
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(subprocess, 'run', records)
    assert x3d_movie.make_film(str(film)) == str(film)
    assert film.read_bytes() == b'film'


def test_a_film_that_cannot_be_made_says_why(tmp_path, monkeypatch):
    def refused(command, **named):
        assert 'OPENGLCONTEXT_AUTO_EXIT_FRAMES' not in named['env']
        return subprocess.CompletedProcess(command, x3d_movie.NO_ENCODER,
                                           'no encoder: none here\n', '')

    monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '5')
    monkeypatch.setattr(subprocess, 'run', refused)
    with pytest.raises(x3d_movie.FilmUnavailable, match='no encoder: none here'):
        x3d_movie.make_film(str(tmp_path / 'film.mp4'))


def test_a_film_process_that_hangs_is_given_up_on(tmp_path, monkeypatch):
    def hangs(command, **named):
        raise subprocess.TimeoutExpired(command, named['timeout'])

    monkeypatch.setattr(subprocess, 'run', hangs)
    with pytest.raises(x3d_movie.FilmUnavailable, match='over 5 seconds'):
        x3d_movie.make_film(str(tmp_path / 'film.mp4'), timeout=5)


def test_the_film_is_recorded_by_the_hardware_encoder(tmp_path):
    import pyopengl_video
    from pyopengl_video.playback import Movie
    if not pyopengl_video.encoders():
        pytest.skip('no video encoder here: %s' % (
            '; '.join(pyopengl_video.encoder.explanations()) or 'none'))
    path = x3d_movie.make_film(str(tmp_path / 'film.mp4'))
    with Movie.open(path) as film:
        assert film.size == x3d_movie.FILM_SIZE
        assert film.frames == x3d_movie.FILM_FPS * x3d_movie.FILM_SECONDS
        assert film.duration == pytest.approx(x3d_movie.FILM_SECONDS)


def test_main_reports_a_film_it_cannot_make(tmp_path, monkeypatch, capsys):
    def refused(path, force=False):
        raise x3d_movie.FilmUnavailable('no encoder: none here')

    monkeypatch.setattr(x3d_movie, 'make_film', refused)
    assert x3d_movie.main(['--directory', str(tmp_path)]) == 1
    assert 'no encoder: none here' in capsys.readouterr().out


def test_a_named_movie_is_shown_from_a_directory_of_its_own(tmp_path):
    made = tmp_path / 'film.mp4'
    made.write_bytes(b'made')
    directory, film = x3d_movie.chosen_film(str(tmp_path), COLOURS_MOVIE)
    assert film == COLOURS_MOVIE
    assert directory == str(tmp_path / x3d_movie.NAMED)
    shown = x3d_movie.MovieScene(directory, film)
    assert background.wait_for_idle(20.0)
    assert loadsensor.load_state(shown.node('Looping')) == loadsensor.LOADED
    with open(COLOURS_MOVIE, 'rb') as handle:
        assert (tmp_path / x3d_movie.NAMED / 'film.mp4').read_bytes() == handle.read()
    assert made.read_bytes() == b'made'


def test_with_no_movie_named_the_film_is_the_one_made_here(tmp_path, monkeypatch):
    asked = []

    def made(path, force=False):
        asked.append((path, force))
        return path

    monkeypatch.setattr(x3d_movie, 'make_film', made)
    film = str(tmp_path / 'film.mp4')
    assert x3d_movie.chosen_film(str(tmp_path), remake=True) == (str(tmp_path), film)
    assert asked == [(film, True)]


def test_a_named_movie_that_is_not_a_file_is_refused(tmp_path):
    with pytest.raises(x3d_movie.FilmUnavailable, match='absent.mp4 is not a file'):
        x3d_movie.chosen_film(str(tmp_path), str(tmp_path / 'absent.mp4'))


def test_main_reports_a_named_movie_that_is_not_there(tmp_path, capsys):
    assert x3d_movie.main(['--directory', str(tmp_path), str(tmp_path / 'absent.mp4')]) == 1
    assert 'absent.mp4 is not a file' in capsys.readouterr().out


def test_remake_is_refused_with_a_named_movie(tmp_path, capsys):
    with pytest.raises(SystemExit):
        x3d_movie.main(['--remake', COLOURS_MOVIE])
    assert '--remake' in capsys.readouterr().err

