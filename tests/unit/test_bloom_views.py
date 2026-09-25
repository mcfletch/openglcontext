"""Bloom over a frame of several views, and the frame it puts on screen.

The glow is a blur, and a blur samples its neighbours; with several views on
one window a neighbour can be another view. These render real frames with
bloom on and read them back where a screenshot would.
"""
import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.multiview.views import View, ViewLayout, ViewStyle
from tests.unit.glrender import base_env, frames_of
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

WIDTH, HEIGHT = 200, 100


def _glowing_box(x):
    material = PBRMaterial(baseColor=(0.0, 0.0, 0.0), emissiveColor=(1.0, 1.0, 1.0),
                           emissiveStrength=40.0, roughness=1.0, metallic=0.0)
    return basenodes.Transform(translation=(x, 0, 0), children=[
        basenodes.Shape(geometry=basenodes.Box(size=(1, 2, 1)),
                        appearance=basenodes.Appearance(material=material))])


def _camera(x, z=6.0):
    return ViewPlatform(position=(x, 0, z), orientation=(0, 1, 0, 0))


@pytest.fixture
def env(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999',
             OPENGLCONTEXT_BLOOM='1')


@pytest.mark.usefixtures('env')
def test_the_frame_presented_is_the_composited_one(render_scene):
    """Every frame read where a screenshot reads it already carries its glow."""
    frames = frames_of(render_scene, [_glowing_box(0.0)], frames=3,
                       size=(WIDTH, HEIGHT))
    for frame in frames:
        centre = frame[HEIGHT // 2, WIDTH // 2].astype(int)
        assert centre.min() > 200, centre


@pytest.mark.usefixtures('env')
def test_the_glow_stays_inside_its_view(render_scene):
    """A bright box at the edge of one view does not light the view beside it."""
    def layout(_context):
        # The box sits at the right-hand edge of the left view; the right view
        # looks at empty space.
        return ViewLayout.split(View(_camera(-2.4), name='glowing'),
                                View(_camera(40.0), name='empty'))

    frames = frames_of(render_scene, [_glowing_box(0.0)], frames=3,
                       size=(WIDTH, HEIGHT), layout=layout)
    frame = frames[-1].astype(int)
    left_edge = frame[:, WIDTH // 2 - 4:WIDTH // 2]
    right_edge = frame[:, WIDTH // 2:WIDTH // 2 + 6]
    assert left_edge.max() > 200, 'the glowing view shows no glow at its edge'
    assert right_edge.max() < 8, right_edge.max()


@pytest.mark.usefixtures('env')
def test_one_view_glows_as_it_always_has(render_scene):
    """A single view's glow reaches the edge of the window unclamped by tiles."""
    frames = frames_of(render_scene, [_glowing_box(0.0)], frames=3,
                       size=(WIDTH, HEIGHT))
    frame = frames[-1].astype(int)
    lit = np.flatnonzero(frame[HEIGHT // 2, :, 0] > 20)
    box = np.flatnonzero(frame[HEIGHT // 2, :, 0] > 240)
    # The glow extends past the box on both sides.
    assert lit[0] < box[0] - 2 and lit[-1] > box[-1] + 2


@pytest.mark.usefixtures('env')
def test_what_the_views_stop_covering_is_cleared(render_scene):
    """With bloom on, a band given up by the views keeps nothing of an earlier frame."""
    def layout(_context):
        drawn = []

        def arrangement(width, height):
            drawn.append(1)
            # The first frame fills the window; the rest leave a band.
            band = 0 if len(drawn) < 2 else 60
            half = (width - band) // 2
            return [(band, 0, half, height), (band + half, 0, width - band - half, height)]

        red = ViewStyle(background=(1.0, 0.0, 0.0))
        return ViewLayout([View(_camera(-2.0), name='left', style=red),
                           View(_camera(2.0), name='right', style=red)],
                          arrangement=arrangement)

    frames = frames_of(render_scene, [_glowing_box(0.0)], frames=3,
                       size=(WIDTH, HEIGHT), layout=layout)
    assert frames[0][:, :55, 0].min() > 100            # a view was here
    assert frames[-1][:, :55].max() < 40               # ...and is not now
