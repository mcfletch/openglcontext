"""oglc-mirrors: the hall of mirrors the reflections page shows off.

:class:`MirrorHall` is the demo without a window: the scene and what each key
does. The hall is held to what the page says is in it, and drawn once for
real.
"""
import numpy as np
import pytest

from OpenGLContext.bin.mirrors_demo import BOUNCES, BUDGETS, INTERVALS, MirrorHall
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.passes import reflection
from OpenGLContext.scenegraph.shape import Shape


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
    import tomllib
    from pathlib import Path
    project = tomllib.loads((Path(__file__).resolve().parents[2]
                             / 'pyproject.toml').read_text(encoding='utf-8'))
    assert project['project']['scripts']['oglc-mirrors'] == \
        'OpenGLContext.bin.mirrors_demo:main'


def test_the_hall_draws_its_mirrors(render_scene, monkeypatch):
    pytest.importorskip('glfw')
    from tests.unit.glrender import base_env
    from OpenGLContext.passes import renderpass
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_REFLECTION_VIEWS='3')
    render_scene(MirrorHall().children, frames=3, size=(320, 180))
    stats = renderpass.FLAT.stats
    assert stats.mirrorViews == 3
    assert stats.mirrorTexels > 0
