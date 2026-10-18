"""oglc-mirrors: the hall of mirrors the reflections page shows off.

:class:`MirrorHall` is the demo without a window: the scene and what each key
does. The hall is held to what the page says is in it, and drawn once for
real.
"""
import tomllib
from pathlib import Path
import numpy as np
import pytest

from OpenGLContext.bin.mirrors_demo import BOUNCES, BUDGETS, INTERVALS, MirrorHall
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.passes import reflection, renderpass
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.bin import mirrors_demo


def _placed(node, matrix=None, out=None):
    """Every shape under ``node`` with its world matrix, as draw records."""
    out = [] if out is None else out
    matrix = np.identity(4) if matrix is None else matrix
    local = getattr(node, 'localMatrices', None)
    if local is not None:
        forward = local().data[0]
        if forward is not None:
            matrix = np.asarray(forward, 'd') @ matrix
    if isinstance(node, Shape):
        out.append(((False,), None, matrix, None, (), node))
    for child in getattr(node, 'children', None) or []:
        _placed(child, matrix, out)
    return out


@pytest.fixture(scope='module')
def hall():
    return MirrorHall()


@pytest.fixture(scope='module')
def records(hall):
    found = []
    for child in hall.children:
        _placed(child, out=found)
    return found


def _using(records, reflector):
    return [record for record in records if reflection.reflector_for(record) is reflector]


def test_the_hall_holds_each_kind_of_mirror(hall, records):
    assert len(_using(records, hall.mirror)) == 1
    assert len(_using(records, hall.corridor)) == 10
    assert len(_using(records, hall.floor)) == 2          # the tiled field and its border
    assert len(_using(records, hall.window)) == 1
    assert hall.window.replace
    assert any(reflection.is_water(record) for record in records)


def test_every_mirror_is_flat_and_faces_into_the_hall(records):
    middle = np.array([0.0, 1.7, 0.0])
    mirrors = [record for record in records if reflection.is_reflector(record)]
    # The far mirror, ten in the corridor, the window, the floor's field and
    # its border, and the pool.
    assert len(mirrors) == 15
    for record in mirrors:
        point, normal = reflection.surface_plane(record)
        assert float(np.dot(middle - point, normal)) > 0.0


def test_r_switches_reflections():
    hall, definition = MirrorHall(), ContextDefinition()
    assert hall.press('r', definition) == 'reflections off'
    assert definition.planarReflections is False or not definition.planarReflections
    assert hall.press('r', definition) == 'reflections on'


def test_b_steps_through_the_budgets():
    hall, definition = MirrorHall(), ContextDefinition(reflectionViews=0)
    seen = [hall.press('b', definition) and definition.reflectionViews
            for _ in BUDGETS]
    assert seen == list(BUDGETS[1:]) + [BUDGETS[0]]


def test_m_steps_through_the_bounces():
    hall, definition = MirrorHall(), ContextDefinition(reflectionBounces=2)
    seen = [hall.press('m', definition) and definition.reflectionBounces
            for _ in BOUNCES]
    assert seen == list(BOUNCES[1:]) + [BOUNCES[0]]


def test_i_steps_the_corridor_through_its_intervals():
    hall = MirrorHall()
    seen = [hall.press('i', ContextDefinition()) and hall.corridor.interval
            for _ in INTERVALS]
    assert seen == list(INTERVALS[1:]) + [INTERVALS[0]]


def test_o_turns_the_window_to_glass_and_back():
    hall = MirrorHall()
    assert hall.press('o', ContextDefinition()) == 'window: shaded glass'
    assert not hall.window.replace
    assert hall.press('o', ContextDefinition()) == 'window: only its reflection'


def test_the_pool_ripples_as_time_passes():
    """Small moving ripples tell water from glass."""
    hall = MirrorHall()
    style = hall.pool.waveStyle
    assert style.moving() and 0.0 < style.amplitude < 0.01
    assert hall.tick(2.5) and hall.pool.wave_time == pytest.approx(2.5)


def test_a_key_the_hall_does_not_use_says_nothing():
    assert MirrorHall().press('q', ContextDefinition()) == ''


def test_the_help_names_every_key():
    assert all(key in MirrorHall.help() for key in MirrorHall.KEYS)


def test_the_command_is_installed():
    project = tomllib.loads((Path(__file__).resolve().parents[2]
                             / 'pyproject.toml').read_text(encoding='utf-8'))
    assert project['project']['scripts']['oglc-mirrors'] == \
        'OpenGLContext.bin.mirrors_demo:main'


def test_the_hall_draws_its_mirrors(render_scene, monkeypatch):
    pytest.importorskip('glfw')
    from tests.unit.glrender import base_env  # noqa: PLC0415 glrender skips its importer without glfw, and the rest of this module needs none
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_REFLECTION_VIEWS='3')
    render_scene(MirrorHall().children, frames=3, size=(320, 180))
    stats = renderpass.FLAT.stats
    assert stats.mirrorViews == 3
    assert stats.mirrorTexels > 0


def test_help_prints_usage_and_opens_no_window(capsys):
    """``oglc-mirrors --help`` answers on the console and exits."""
    with pytest.raises(SystemExit) as stopped:
        mirrors_demo.main(['--help'])
    assert stopped.value.code == 0
    said = capsys.readouterr().out
    assert 'usage' in said
    assert 'reflections on and off' in said.lower()


COLOURS_MOVIE = str(Path(__file__).resolve().parents[1] / 'resources' / 'colours.mp4')


def _movies(hall):
    from OpenGLContext.scenegraph.movietexture import MovieTexture  # noqa: PLC0415 kept with its use
    found = []
    for child in hall.children:
        for record in _placed(child):
            texture = getattr(record[-1].appearance, 'texture', None)
            if isinstance(texture, MovieTexture):
                found.append((texture, record))
    return found


def test_the_hall_has_no_screen_unless_a_movie_is_named(hall):
    assert hall.screen is None
    assert _movies(hall) == []


def test_a_named_movie_plays_looped_on_a_screen_facing_the_far_mirror():
    hall = MirrorHall(movie=COLOURS_MOVIE)
    (texture, record), = _movies(hall)
    assert texture is hall.screen
    assert list(texture.url) == [COLOURS_MOVIE] and texture.loop
    point, normal = reflection.surface_plane(record)
    assert point[2] > 11.0 and normal[2] == pytest.approx(-1.0)
    mesh = record[-1].geometry
    low, high = np.min(mesh.texcoords, axis=0), np.max(mesh.texcoords, axis=0)
    assert tuple(low) == (0.0, 0.0) and tuple(high) == (1.0, 1.0)
    width, tall = np.ptp(np.asarray(mesh.positions)[:, :2], axis=0)
    assert width / tall == pytest.approx(16 / 9)


def test_the_screen_adds_no_mirror():
    found = []
    for child in MirrorHall(movie=COLOURS_MOVIE).children:
        _placed(child, out=found)
    assert len([record for record in found if reflection.is_reflector(record)]) == 15


def test_the_named_movie_is_opened_by_the_loader():
    pytest.importorskip('pyopengl_video', reason='the screen reads its movie through pyopengl-video')
    from vrml.x3d import loadsensor  # noqa: PLC0415 kept with its use

    from OpenGLContext.loaders import background  # noqa: PLC0415 kept with its use
    hall = MirrorHall(movie=COLOURS_MOVIE)
    assert background.wait_for_idle(20.0)
    assert loadsensor.load_state(hall.screen) == loadsensor.LOADED


def test_movie_url_is_read_from_the_command_line():
    assert mirrors_demo.arguments([]).movie_url is None
    assert mirrors_demo.arguments(['--movie-url', 'https://example.org/film.mp4']).movie_url \
        == 'https://example.org/film.mp4'


def test_the_hall_draws_with_a_screen(render_scene, monkeypatch):
    pytest.importorskip('glfw')
    pytest.importorskip('pyopengl_video', reason='the screen reads its movie through pyopengl-video')
    from tests.unit.glrender import base_env  # noqa: PLC0415 glrender skips its importer without glfw, and the rest of this module needs none

    from OpenGLContext.loaders import background  # noqa: PLC0415 kept with its use
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_REFLECTION_VIEWS='3')
    hall = MirrorHall(movie=COLOURS_MOVIE)
    assert background.wait_for_idle(20.0)
    render_scene(hall.children, frames=3, size=(320, 180))
    assert hall.screen.movie() is not None
    assert renderpass.FLAT.stats.mirrorViews == 3
