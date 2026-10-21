"""One frame's state, held for that frame and dropped when it ends.

The walk of the scene a frame makes is read by the views' culls, the shadow
pass's caster pool, the mirror views and the zone captures. It describes the
scene as it stood when it was walked, so it is kept on the pass's
``frameState`` for the frame and let go of as the frame ends, whatever else
the frame did.
"""
import numpy as np
import pytest

from OpenGLContext import frustum
from OpenGLContext.passes import _flat, flatcore, multiviewpass, pbrpass, renderpass, tonemapping
from OpenGLContext.scenegraph.instancedgl import DEFAULT_FOG, frame_fog
from OpenGLContext.scenegraph import basenodes


def _pass(count=3):
    moves = [basenodes.Transform(translation=(index * 3.0, 0, 0), children=[
        basenodes.Shape(geometry=basenodes.Box(size=(2, 2, 2)))])
        for index in range(count)]
    passing = flatcore.FlatPass.__new__(flatcore.FlatPass)
    _flat.SGObserver.__init__(passing, basenodes.sceneGraph(children=moves), [])
    passing.frustum = frustum.Frustum(planes=np.zeros((0, 4), 'f'))
    return passing


class TestTheFramesWalk:
    def test_within_a_frame_the_walk_is_made_once(self):
        passing = _pass()
        with passing.drawingFrame():
            walked = passing.gatherPaths()
            assert passing.frameGather() is walked
            assert passing.frameGather() is walked

    def test_the_walk_is_let_go_of_when_the_frame_ends(self):
        passing = _pass()
        with passing.drawingFrame():
            walked = passing.gatherPaths()
        assert passing.frameState is None
        assert passing.frameGather() is not walked

    def test_a_frame_that_raises_lets_it_go_as_well(self):
        passing = _pass()
        with pytest.raises(RuntimeError):
            with passing.drawingFrame():
                passing.gatherPaths()
                raise RuntimeError('a view failed')
        assert passing.frameState is None

    def test_outside_a_frame_every_asking_walks_the_scene(self):
        passing = _pass()
        assert passing.frameGather() is not passing.frameGather()

    def test_giving_the_views_back_leaves_the_walk_for_the_rest_of_the_frame(self, monkeypatch):
        """What the legacy pick path does part-way through a frame."""
        passing = _pass()
        # Patched where the calls are made: `finishViews` reads the names in
        # its own module, and a real `glDisable` with no context is a no-op on
        # one platform's GL and an invalid operation on another's.
        monkeypatch.setattr(multiviewpass, 'glDisable', lambda *_args: None)
        monkeypatch.setattr(multiviewpass, 'glViewport', lambda *_args: None)

        class _Context:
            def getViewPort(self):
                return (64, 48)

        passing.context = _Context()
        with passing.drawingFrame():
            walked = passing.gatherPaths()
            passing.finishViews()
            assert passing.frameGather() is walked


# -- in a window -------------------------------------------------------------

def test_a_frame_with_a_legacy_pick_still_draws_its_reflections(render_scene, monkeypatch):
    """The pick is drawn before the mirrors; they still find the frame's walk."""
    # glrender, and the mirror test module built on it, skip their importer
    # where glfw is missing; the tests above need no window.
    from tests.unit.glrender import base_env, frames_of  # noqa: PLC0415 skips without glfw
    from tests.unit.test_planar_mirror_gl import SIZE, _red, _room  # noqa: PLC0415 skips without glfw
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
    frames = frames_of(render_scene, _room(), frames=4, size=SIZE, mrt=False,
                       picks=lambda w, h: [(w // 2, h // 2)])
    # Frames 1 and 2 carry the pick.
    assert [_red(frame) > 300 for frame in frames[1:]] == [True, True, True]


def test_a_views_combined_matrix_is_of_the_projection_it_draws_with(render_scene, monkeypatch):
    """Trimming a view's projection to its depth trims the product with it."""
    from tests.unit.glrender import base_env  # noqa: PLC0415 skips without glfw
    from tests.unit.test_planar_mirror_gl import SIZE, _room  # noqa: PLC0415 skips without glfw
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0')
    render_scene(_room(), frames=2, size=SIZE)
    for frame in renderpass.current_pass().viewFrames:
        assert frame.maxDepth                     # the projection was trimmed
        assert np.allclose(frame.modelproj,
                           np.asarray(frame.modelView) @ np.asarray(frame.projection),
                           atol=1e-5)


def _fogged_pass(**named):
    fog = basenodes.Fog(color=(0.2, 0.4, 0.6), visibilityRange=100.0, **named)
    passing = pbrpass.PBRPass.__new__(pbrpass.PBRPass)
    _flat.SGObserver.__init__(passing, basenodes.sceneGraph(children=[
        fog, basenodes.Shape(geometry=basenodes.Box())]), [])
    passing.frustum = frustum.Frustum(planes=np.zeros((0, 4), 'f'))
    return passing, fog


class TestWhatEveryLayerOfAFrameAsksFor:
    """The vegetation, the terrain and every other layer that draws with its own program ask the
    pass for the frame's tone curve and fog, once each, and every node of them is told the same."""

    def test_within_a_frame_the_display_is_worked_out_once(self, monkeypatch):
        passing, _ = _fogged_pass()
        made = []
        real = tonemapping.display
        monkeypatch.setattr(tonemapping, 'display', lambda *a, **k: made.append(1) or real(*a, **k))
        with passing.drawingFrame():
            first = passing.frameDisplay()
            assert [passing.frameDisplay() for _ in range(5)] == [first] * 5
        assert len(made) == 1

    def test_the_next_frame_works_it_out_again(self, monkeypatch):
        passing, _ = _fogged_pass()
        made = []
        real = tonemapping.display
        monkeypatch.setattr(tonemapping, 'display', lambda *a, **k: made.append(1) or real(*a, **k))
        for _ in range(3):
            with passing.drawingFrame():
                passing.frameDisplay()
                passing.frameDisplay()
        assert len(made) == 3

    def test_outside_a_frame_every_asking_works_it_out(self, monkeypatch):
        passing, _ = _fogged_pass()
        made = []
        real = tonemapping.display
        monkeypatch.setattr(tonemapping, 'display', lambda *a, **k: made.append(1) or real(*a, **k))
        passing.frameDisplay()
        passing.frameDisplay()
        assert len(made) == 2

    def test_a_pass_that_does_not_tone_map_answers_the_engines_curve_whatever_the_frame_holds(self):
        passing, _ = _fogged_pass()
        with passing.drawingFrame():
            passing.frameDisplay()
            passing.toneMapped = False
            assert passing.frameDisplay() is tonemapping.ENGINE

    def test_within_a_frame_the_fog_is_worked_out_once(self, monkeypatch):
        passing, fog = _fogged_pass()
        asked = []
        real = fog.fogParameters
        monkeypatch.setattr(type(fog), 'fogParameters',
                            lambda self, matrix: asked.append(1) or real(matrix))
        with passing.drawingFrame():
            found = frame_fog(passing)
            assert [frame_fog(passing) for _ in range(5)] == [found] * 5
        assert len(asked) == 1
        assert found[2] == pytest.approx((0.2, 0.4, 0.6))

    def test_the_next_frame_has_the_fog_as_it_has_become(self):
        passing, fog = _fogged_pass()
        with passing.drawingFrame():
            before = frame_fog(passing)
        fog.color = (0.9, 0.1, 0.1)
        with passing.drawingFrame():
            after = frame_fog(passing)
        assert before[2] == pytest.approx((0.2, 0.4, 0.6))
        assert after[2] == pytest.approx((0.9, 0.1, 0.1))

    def test_a_scene_with_no_fog_has_the_default(self):
        passing = pbrpass.PBRPass.__new__(pbrpass.PBRPass)
        _flat.SGObserver.__init__(passing, basenodes.sceneGraph(children=[
            basenodes.Shape(geometry=basenodes.Box())]), [])
        with passing.drawingFrame():
            assert frame_fog(passing) == DEFAULT_FOG
