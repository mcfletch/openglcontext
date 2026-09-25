"""The reflection pass's settings and per-shape choices, with no GL.

The budget a frame's reflections are held to comes from the context's
definition, or from the environment where nothing set the field; a shape too
small to see in a mirror is left out of it; and each shape drawn is told the
reflection it reads, once per change.
"""
import numpy as np
import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.passes import reflection
from OpenGLContext.passes.flateffects import _FlatEffectsMixin
from OpenGLContext.passes.reflectionatlas import FILL
from OpenGLContext.scenegraph.boundingvolume import AABoundingBox


class _Context:
    def __init__(self, definition=None, size=(400, 300)):
        self.contextDefinition = definition or ContextDefinition()
        self._size = size

    def getViewPort(self):
        return self._size


def _pass(strategy='vertex', **fields):
    effects = _FlatEffectsMixin()
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
    from OpenGLContext import renderoptions
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
    effects = _FlatEffectsMixin()
    effects.view = object()
    shader = _Shader()
    effects._reflection_lookups = {}
    for _ in range(3):
        effects.applyPlanarReflection(shader, ((False,), None, None, None, object(), None))
    assert shader.given == []


def test_a_mirror_reads_its_own_lookup_and_the_next_shape_none():
    effects = _FlatEffectsMixin()
    effects.view = view = object()
    mirror, plain = object(), object()
    lookup = object()
    effects._reflection_lookups = {(id(view), id(mirror)): lookup}
    shader = _Shader()
    effects.applyPlanarReflection(shader, ((False,), None, None, None, mirror, None))
    effects.applyPlanarReflection(shader, ((False,), None, None, None, mirror, None))
    effects.applyPlanarReflection(shader, ((False,), None, None, None, plain, None))
    assert shader.given == [lookup, None]


# --- switching reflections -------------------------------------------------------

def test_a_mirror_seen_in_a_mirror_falls_back_to_its_reflection_seen_directly():
    """Until its reflection for that mirror's view is drawn, a mirror seen in a
    mirror shows the one the viewer sees, not the probe."""
    from OpenGLContext.passes.reflectionplanner import ReflectedView
    effects, shader = _FlatEffectsMixin(), _Shader()
    main, mirror, inner = object(), object(), object()
    through = ReflectedView(main, 'key', np.zeros(3))
    direct = object()
    effects._reflection_lookups = {(id(main), id(inner)): direct}
    effects.view = through
    effects.applyPlanarReflection(shader, ((False,), None, None, None, inner, None))
    own = object()
    effects._reflection_lookups[(id(through), id(inner))] = own
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
