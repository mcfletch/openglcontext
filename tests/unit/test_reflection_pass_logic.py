"""The reflection pass's settings and per-shape choices, with no GL.

The budget a frame's reflections are held to comes from the context's
definition, or from the environment where nothing set the field; a shape too
small to see in a mirror is left out of it; and each shape drawn is told the
reflection it reads, once per change.
"""
import types
import numpy as np
import pytest
from tests.unit.test_reflection_planner import _frame, _mirror

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.passes import reflection
from OpenGLContext.passes.reflectionpass import ReflectionsMixin
from OpenGLContext.passes.reflectionatlas import FILL
from OpenGLContext.passes.reflectionplanner import (
    lookup_key, ReflectedView, ReflectionPlanner, SETTLE_FRAMES,
)
from OpenGLContext.scenegraph.boundingvolume import AABoundingBox
from OpenGLContext import renderoptions
from OpenGLContext.passes.reflectiontiles import Budget


class _Context:
    def __init__(self, definition=None, size=(400, 300)):
        self.contextDefinition = definition or ContextDefinition()
        self._size = size

    def getViewPort(self):
        return self._size


def _pass(strategy='vertex', **fields):
    effects = ReflectionsMixin()
    effects.context = _Context(ContextDefinition(**fields))
    effects.multiviewStrategy = strategy
    return effects


# --- the budget ---------------------------------------------------------------

def test_the_view_budget_follows_the_strategy():
    assert _pass('sequential').reflectionBudget().views == 2
    assert _pass('vertex').reflectionBudget().views >= 2


def test_the_definition_sets_the_budget():
    budget = _pass(reflectionViews=5, reflectionSeparateViews=1,
                   reflectionAtlas=0.25).reflectionBudget()
    assert (budget.views, budget.separate_views) == (5, 1)
    # A quarter of 400 x 300, rounded up, and the share of that the shelves pack.
    assert budget.texels == int(208 * 160 * FILL)


def test_the_environment_sets_what_the_definition_leaves(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_REFLECTION_VIEWS', '3')
    monkeypatch.setenv('OPENGLCONTEXT_REFLECTION_SEPARATE_VIEWS', '0')
    monkeypatch.setenv('OPENGLCONTEXT_REFLECTION_ATLAS', '1.0')
    budget = _pass().reflectionBudget()
    assert (budget.views, budget.separate_views) == (3, 0)
    assert budget.texels == int(400 * 304 * FILL)


def test_every_setting_is_a_rendering_one():
    for name in ('OPENGLCONTEXT_PLANAR_REFLECTIONS', 'OPENGLCONTEXT_REFLECTION_VIEWS',
                 'OPENGLCONTEXT_REFLECTION_SEPARATE_VIEWS', 'OPENGLCONTEXT_REFLECTION_ATLAS',
                 'OPENGLCONTEXT_REFLECTION_MS'):
        assert name in renderoptions.ENVIRONMENT


# --- what a mirror leaves out -------------------------------------------------

def _record(distance, size=1.0):
    placement = np.identity(4, 'f')
    placement[3, 2] = -distance
    volume = AABoundingBox(center=(0, 0, 0), size=(size, size, size))
    return ((False,), None, placement, volume, (), None)


def test_a_shape_covering_under_two_texels_is_too_small():
    # 1000 texels a radian: a unit box a thousand metres off covers under two.
    assert reflection.too_small(_record(1000.0), (0, 0, 0), 1000.0)
    assert not reflection.too_small(_record(10.0), (0, 0, 0), 1000.0)


def test_a_shape_with_no_box_is_never_too_small():
    record = ((False,), None, np.identity(4, 'f'), None, (), None)
    assert not reflection.too_small(record, (0, 0, 1000), 1.0)


def test_a_shape_around_the_eye_is_never_too_small():
    assert not reflection.too_small(_record(0.1, size=5.0), (0, 0, 0), 1.0)


# --- telling each shape what it reads -----------------------------------------

class _Shader:
    def __init__(self):
        self.given = []

    def set_planar_reflection(self, lookup, program=None):
        self.given.append(lookup)


def test_a_run_of_shapes_that_are_not_mirrors_sets_nothing():
    effects = ReflectionsMixin()
    effects.view = object()
    shader = _Shader()
    effects._reflection_lookups = {}
    for _ in range(3):
        effects.applyPlanarReflection(shader, ((False,), None, None, None, object(), None))
    assert shader.given == []


def test_a_mirror_reads_its_own_lookup_and_the_next_shape_none():
    effects = ReflectionsMixin()
    effects.view = view = object()
    mirror, plain = object(), object()
    lookup = object()
    effects._reflection_lookups = {lookup_key(view, mirror): lookup}
    shader = _Shader()
    effects.applyPlanarReflection(shader, ((False,), None, None, None, mirror, None))
    effects.applyPlanarReflection(shader, ((False,), None, None, None, mirror, None))
    effects.applyPlanarReflection(shader, ((False,), None, None, None, plain, None))
    assert shader.given == [lookup, None]


# --- switching reflections -------------------------------------------------------

def test_a_mirror_seen_in_a_mirror_falls_back_to_its_reflection_seen_directly():
    """Until its reflection for that mirror's view is drawn, a mirror seen in a
    mirror shows the one the viewer sees, not the probe."""
    effects, shader = ReflectionsMixin(), _Shader()
    main, mirror, inner = object(), object(), object()
    through = ReflectedView(main, 'key', np.zeros(3))
    direct = object()
    effects._reflection_lookups = {lookup_key(main, inner): direct}
    effects.view = through
    effects.applyPlanarReflection(shader, ((False,), None, None, None, inner, None))
    own = object()
    effects._reflection_lookups[lookup_key(through, inner)] = own
    effects.applyPlanarReflection(shader, ((False,), None, None, None, inner, None))
    effects.applyPlanarReflection(shader, ((False,), None, None, None, mirror, None))
    assert shader.given == [direct, own, None]


class _Program:
    planar_reflection_supported = True


def test_the_setting_is_read_every_frame():
    """A settings screen writes the field and the next frame follows it."""
    effects = _pass()
    effects.shader_program = _Program()
    effects._planar_reflections = None
    assert effects.planarReflectionsEnabled()
    effects.context.contextDefinition.planarReflections = False
    assert not effects.planarReflectionsEnabled()
    effects.context.contextDefinition.planarReflections = True
    assert effects.planarReflectionsEnabled()


def test_a_driver_without_the_texture_unit_never_reflects():
    effects = _pass(planarReflections=True)
    program = _Program()
    program.planar_reflection_supported = False
    effects.shader_program = program
    assert not effects.planarReflectionsEnabled()


# --- a failure in the reflection pass ---------------------------------------------

class _FailingPlanner:
    """A planner whose every plan raises, as a driver refusing the atlas does."""

    def __init__(self):
        self.allowed = None
        self.calls = 0
        self.schedule = None

    def plan(self, *args, **named):
        self.calls += 1
        raise RuntimeError('the reflection atlas is incomplete (0x8cd6)')


class _Gathered:
    """A frame's walk with one mirror in it."""

    paths = [object()]


def _failing_pass():
    effects = _pass()
    effects.shader_program = _Program()
    effects.frameGather = lambda: _Gathered()
    effects.sceneMirrors = lambda: np.array([0])
    effects.activeFrame = None
    effects.mirrorsZoned = lambda: False
    effects._reflection_planner = planner = _FailingPlanner()
    effects._reflection_lookups = {'stale': object()}
    return effects, planner


def test_a_failing_reflection_pass_switches_reflections_off_and_keeps_the_frame(caplog):
    """Every mirror reflects the probe from then on; the frame is drawn."""
    effects, planner = _failing_pass()
    with caplog.at_level('ERROR'):
        effects.renderReflections([], None)
        effects.renderReflections([], None)
    assert planner.calls == 1
    assert not effects.planarReflectionsEnabled()
    assert effects._reflection_lookups == {}
    failures = [r for r in caplog.records if 'reflection' in r.getMessage().lower()]
    assert len(failures) == 1
    assert failures[0].exc_info is not None


# --- the time target -------------------------------------------------------------

class _Timer:
    """A GPU timer's answer, as it stands between readings."""

    def __init__(self, milliseconds, tag, reading):
        self.milliseconds, self.tag, self.reading = milliseconds, tag, reading


def _timed_pass(timer):
    effects = _pass(reflectionMilliseconds=5.0)
    effects.shader_program = _Program()
    effects.frameGather = lambda: _Gathered()
    effects.sceneMirrors = lambda: np.array([0])
    effects.activeFrame = None
    effects.mirrorsZoned = lambda: False
    effects._reflection_planner = ReflectionPlanner()
    effects._reflection_timer = timer
    return effects


def test_a_reading_moves_the_time_scale_once_however_many_frames_it_stands():
    timer = _Timer(6.0, 1.0, 1)
    effects = _timed_pass(timer)
    schedule = effects._reflection_planner.schedule
    effects.renderReflections([], None)
    once = schedule.time_scale
    assert once < 1.0
    for _ in range(10):
        effects.renderReflections([], None)
    assert schedule.time_scale == once
    timer.reading = 2
    effects.renderReflections([], None)
    assert schedule.time_scale < once


def test_a_reading_is_weighed_by_the_scale_its_frame_was_drawn_at():
    """6 ms for a frame drawn at a time scale of a half says a full budget
    costs 12, whatever the scale has moved to since."""
    timer = _Timer(6.0, 0.5, 1)
    effects = _timed_pass(timer)
    schedule = effects._reflection_planner.schedule
    schedule.time_scale = 0.8
    effects.renderReflections([], None)
    wanted = 0.5 * 5.0 / 6.0
    assert schedule.time_scale == pytest.approx(0.8 + schedule.SMOOTHING * (wanted - 0.8))


# --- a frame's reflections, drawn with the GL left out ---------------------------

class _Atlas:
    """What the pass asks of the atlas, with nothing allocated."""

    def __init__(self, new=False):
        self.new, self.released, self.mipmapped = new, 0, False

    def ensure_size(self, width, height):
        return self.new

    def bind(self):
        pass

    def release(self):
        self.released += 1


class _Context(_Context):
    def __init__(self, *args, **named):
        super().__init__(*args, **named)
        self.redraws = 0

    def triggerRedraw(self, when=0):
        self.redraws += 1


class _LitProgram(_Program):
    def use(self, lit=True):
        pass

    def set_planar_levels(self, levels):
        pass


def _drawing_pass(records, **fields):
    """A pass whose scene is ``records``' mirrors, drawing nothing on the GPU."""
    effects = ReflectionsMixin()
    effects.context = _Context(ContextDefinition(**fields))
    effects.multiviewStrategy = 'vertex'
    effects.shader_program = _LitProgram()
    gathered = types.SimpleNamespace(paths=[record[4] for record in records])
    effects.frameGather = lambda: gathered
    effects.sceneMirrors = lambda: np.arange(len(records))
    effects.activeFrame = None
    effects.mirrorsZoned = lambda: False
    effects.mirrorsIn = lambda frame: []
    effects._separateShapes = lambda mirror: False
    effects.stats = types.SimpleNamespace()
    effects._reflection_planner = planner = ReflectionPlanner()
    planner.frame = SETTLE_FRAMES
    effects._reflection_atlas = _Atlas()
    effects.drawn = []

    def draw(plan, lighting, gathered, atlas):
        effects.drawn.append(plan)
        effects._incompleteMirrors = frozenset(draw.key for draw in plan.draws)

    effects._drawMirrorViews = draw
    return effects


def _mirror_frame():
    record = _mirror()
    return record, _frame([record])


def test_a_frame_asks_for_another_at_most_once():
    """Unfinished and left incomplete, it still asks for one frame."""
    record, frame = _mirror_frame()
    effects = _drawing_pass([record])
    effects._reflection_planner.frame = 0          # still settling: unfinished
    effects.renderReflections([frame], None)
    assert effects.drawn and effects.context.redraws == 1


def test_switching_reflections_off_gives_back_the_atlas_and_every_tile():
    record, frame = _mirror_frame()
    effects = _drawing_pass([record])
    atlas = effects._reflection_atlas
    effects.renderReflections([frame], None)
    assert effects._reflection_planner._held
    effects.context.contextDefinition.planarReflections = False
    effects.renderReflections([frame], None)
    assert atlas.released == 1 and effects._reflection_atlas is None
    assert not effects._reflection_planner._held
    assert not effects._reflection_planner.packer.tiles
    effects.renderReflections([frame], None)
    assert atlas.released == 1


def test_a_new_atlas_is_read_only_where_this_frame_drew():
    """Tiles kept from before hold nothing in an atlas made this frame."""
    kept, drawn = _mirror(-1.5), _mirror(1.5)
    effects = _drawing_pass([kept, drawn])
    planner = effects._reflection_planner
    planner.plan([_frame([kept])], effects.reflectionAtlasSize(), effects.reflectionBudget)
    effects._reflection_atlas = _Atlas(new=True)
    effects.reflectionBudget = lambda: Budget(views=1, separate_views=1, texels=10 ** 9)
    frame = _frame([kept, drawn])
    effects.renderReflections([frame], None)
    plan, = effects.drawn
    drew = {draw.key for draw in plan.draws}
    assert drew and set(effects._reflection_lookups) <= drew
    assert set(planner._held) == drew


def test_the_budget_is_worked_out_once_a_frame():
    record, frame = _mirror_frame()
    effects = _drawing_pass([record])
    asked = []
    real = effects.reflectionBudget
    effects.reflectionBudget = lambda: asked.append(1) or real()
    effects.renderReflections([frame], None)
    plan, = effects.drawn
    assert len(asked) == 1 and plan.budget is not None


# --- a shape too small to see in a mirror, for the whole walk at once -----------------

def test_the_whole_walk_is_measured_as_each_shape_would_be():
    rng = np.random.default_rng(7)
    records, matrices, points, bounded = [], [], [], []
    for index in range(40):
        placement = np.identity(4, 'f')
        placement[:3, :3] *= rng.uniform(0.2, 3.0)
        placement[3, :3] = rng.uniform(-400.0, 400.0, 3)
        size = rng.uniform(0.05, 4.0, 3)
        centre = rng.uniform(-1.0, 1.0, 3)
        volume = AABoundingBox(center=tuple(centre), size=tuple(size))
        has_box = index % 7 != 0
        records.append(((False,), None, placement, volume if has_box else None, (), None))
        matrices.append(placement)
        points.append(volume.getPoints())
        bounded.append(has_box)
    centres, radii = reflection.reach(np.array(matrices), np.array(points, 'f'),
                                      np.array(bounded))
    eye = np.array([3.0, 1.0, -2.0])
    small = reflection.too_small_mask(centres, radii, np.array(bounded), eye, 150.0)
    assert small.tolist() == [reflection.too_small(record, eye, 150.0) for record in records]
    assert small.any() and not small.all()
