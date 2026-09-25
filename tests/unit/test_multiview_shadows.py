"""Shadows seen from every view of a frame.

The shadow maps are rendered once a frame and read by every view. A spot or
point map depends only on its light, but a directional light's cascades are
fitted to one camera -- the layout's active view -- and every other view reads
the same cascades. These render one scene through two views and compare what
a view shows when the cascades were fitted to it with what it shows when they
were fitted to the other.
"""
import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.multiview.views import View, ViewLayout
from tests.unit.glrender import base_env, frames_of
from OpenGLContext.move.followcam import look_at_orientation
from OpenGLContext.move.viewplatform import ViewPlatform

WIDTH, HEIGHT = 240, 120


def _scene():
    white = basenodes.Appearance(material=basenodes.Material(diffuseColor=(1, 1, 1)))
    return [
        basenodes.Background(skyColor=[(0.0, 0.0, 1.0)]),
        basenodes.Transform(translation=(0, -1.05, 0), children=[
            basenodes.Shape(geometry=basenodes.Box(size=(12, 0.1, 12)),
                            appearance=white)]),
        basenodes.Transform(translation=(0, 0.5, 0), children=[
            basenodes.Shape(geometry=basenodes.Box(size=(2, 0.2, 2)),
                            appearance=white)]),
        # Almost straight down, so a cascade covers the ground beneath the
        # slice of the view it was fitted to and none of the rest.
        basenodes.DirectionalLight(direction=(0.05, -1.0, 0.0), intensity=1.0),
    ]


def _looking(eye, target=(0.0, -1.0, 0.0)):
    return ViewPlatform(position=eye, orientation=look_at_orientation(eye, target))


def _cameras():
    # Far and level: its cascades are split sixty units out, and the first
    # holds the ground nearest it, well in front of the box. Close and from the
    # side: everything it sees is nearer than that first split, so choosing by
    # its own depth would read the first cascade, which does not hold the
    # ground under the box.
    return _looking((0.0, 0.0, 60.0), (0.0, 0.0, 0.0)), _looking((6.0, 4.0, 1.0))


def _layout(fitted):
    def build(context):
        far, near = _cameras()
        layout = ViewLayout.split(View(far, name='far'), View(near, name='near'))
        layout.activate(layout.views[1 if fitted == 'near' else 0])
        return layout
    return build


def _differing(one, other):
    """How many pixels of two tiles differ by more than a rounding error."""
    return int((abs(one.astype(int) - other.astype(int)).max(axis=-1) > 24).sum())


@pytest.fixture
def env(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='1', OPENGLCONTEXT_SHADOW_CASCADES='4',
             OPENGLCONTEXT_INSTANCE_MIN='999')


def _near_tile(render_scene, fitted, shadows=True):
    frames = frames_of(render_scene, _scene(), frames=3, shadows=shadows,
                       size=(WIDTH, HEIGHT), layout=_layout(fitted))
    return frames[-1][:, WIDTH // 2:]


def test_the_close_view_has_a_shadow_to_compare(render_scene, env):
    lit = _near_tile(render_scene, 'near', shadows=False)
    shadowed = _near_tile(render_scene, 'near')
    assert _differing(lit, shadowed) > 400


def test_a_view_the_cascades_were_not_fitted_to_still_shows_the_shadow(
        render_scene, env):
    own = _near_tile(render_scene, 'near')
    borrowed = _near_tile(render_scene, 'far')
    # The borrowed cascades cover the ground at a different resolution, so the
    # edge of the shadow moves by a texel or two; its area does not go missing.
    assert _differing(own, borrowed) < 60


def _looking_away_layout(context):
    """The active view looks up at the empty sky; the other sees the shadow."""
    _far, near = _cameras()
    away = _looking((0.0, 0.0, 60.0), (0.0, 100.0, 70.0))
    layout = ViewLayout.split(View(away, name='away'), View(near, name='near'))
    layout.activate(layout.views[0])
    return layout


def test_an_active_view_with_nothing_in_it_leaves_the_others_their_shadows(
        render_scene, env):
    lit = _near_tile(render_scene, 'near', shadows=False)
    frames = frames_of(render_scene, _scene(), frames=3, shadows=True,
                       size=(WIDTH, HEIGHT), layout=_looking_away_layout)
    assert _differing(lit, frames[-1][:, WIDTH // 2:]) > 400
