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
from OpenGLContext.passes import _flat, flatcore, renderpass
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
        monkeypatch.setattr(_flat, 'glDisable', lambda *a: None)
        monkeypatch.setattr(_flat, 'glViewport', lambda *a: None)

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
