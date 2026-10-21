"""``shadowFarInterval``: the cascades beyond the nearest are drawn every few frames.

The nearest cascade holds what moves and is seen closely, so it is drawn every frame. Each of
the others is fitted with room to spare, drawn in its turn, and used again until the slice of
the view it serves leaves it, the light changes or the shadow map is made again. Every test
here draws the same scene with the setting at 1, which draws every cascade every frame, and
with it above 1.
"""
import numpy as np
import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.passes import shadowmixin
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.scenes import drawn_image, scene_context

CASCADES = 3


def test_the_definition_has_the_field_and_it_draws_every_cascade_every_frame():
    assert ContextDefinition().shadowFarInterval == 1


def _slab(centre, size):
    return basenodes.Transform(translation=centre, children=[basenodes.Shape(
        geometry=basenodes.Box(size=size),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(1, 1, 1))))])


class _Frames:
    """A long floor with slabs over it, drawn by a camera that can be moved between frames."""

    def __init__(self, interval, monkeypatch, environment=None):
        self.depth_draws = 0
        real = shadowmixin.ShadowMapMixin._renderDepth

        def counting(owner, *arguments, **named):
            self.depth_draws += 1
            return real(owner, *arguments, **named)
        monkeypatch.setattr(shadowmixin.ShadowMapMixin, '_renderDepth', counting)
        floor = _slab((0, -1, -120), (60, 0.1, 300))
        slabs = [_slab((0, 1, -z), (2, 0.2, 2)) for z in range(10, 190, 12)]
        self.sun = basenodes.DirectionalLight(direction=(1, -1, 0), intensity=1.0, shadows=True)
        self.eye = basenodes.Viewpoint(position=(-4, 6, 0), orientation=(1, 0, 0, -0.35))
        self.scene = scene_context(
            [self.eye, basenodes.NavigationInfo(headlight=False), self.sun, floor, *slabs],
            size=(96, 96), shadowCascades=CASCADES, environment=environment,
            **({} if interval is None else {'shadowFarInterval': interval}))

    def __enter__(self):
        self.context = self.scene.__enter__()
        return self

    def __exit__(self, *exc):
        return self.scene.__exit__(*exc)

    def move_to(self, z):
        self.context.platform.setPosition((-4.0, 6.0, float(z)))

    def frame(self):
        return drawn_image(self.context).astype(float).mean(axis=2)


def _difference(first, second):
    return float(np.abs(first - second).mean())


@pytest.mark.usefixtures('gl_context')
class TestWhatIsDrawn:
    def test_a_still_view_draws_fewer_cascades_with_the_interval_than_without(self, monkeypatch):
        draws = {}
        for interval in (1, 3):
            with _Frames(interval, monkeypatch) as frames:
                for _ in range(2):
                    frames.frame()
                frames.depth_draws = 0
                for _ in range(12):
                    frames.frame()
                draws[interval] = frames.depth_draws
        assert draws[1] == CASCADES * 12
        assert draws[3] < 0.8 * draws[1]
        assert draws[3] >= 12

    def test_the_environment_variable_sets_it_for_a_definition_that_leaves_it_alone(
            self, monkeypatch):
        with _Frames(None, monkeypatch, {'OPENGLCONTEXT_SHADOW_FAR_INTERVAL': '3'}) as frames:
            for _ in range(2):
                frames.frame()
            frames.depth_draws = 0
            for _ in range(12):
                frames.frame()
            assert frames.depth_draws < 0.8 * CASCADES * 12

    def test_a_definition_that_sets_it_outranks_the_environment_variable(self, monkeypatch):
        with _Frames(1, monkeypatch, {'OPENGLCONTEXT_SHADOW_FAR_INTERVAL': '3'}) as frames:
            for _ in range(2):
                frames.frame()
            frames.depth_draws = 0
            for _ in range(12):
                frames.frame()
            assert frames.depth_draws == CASCADES * 12

    def test_a_still_view_has_the_shadows_it_has_without_the_interval(self, monkeypatch):
        images = {}
        for interval in (1, 3):
            with _Frames(interval, monkeypatch) as frames:
                for _ in range(7):
                    image = frames.frame()
                images[interval] = image
        assert _difference(images[1], images[3]) < 0.25

    def test_a_view_that_moved_out_of_every_cascade_draws_every_cascade_again(self, monkeypatch):
        with _Frames(3, monkeypatch) as frames:
            for _ in range(7):
                frames.frame()
            frames.move_to(-900.0)
            frames.depth_draws = 0
            frames.frame()
            assert frames.depth_draws == CASCADES

    def test_a_view_that_moved_a_long_way_has_the_shadows_it_has_without_the_interval(
            self, monkeypatch):
        images = {}
        for interval in (1, 3):
            with _Frames(interval, monkeypatch) as frames:
                for _ in range(4):
                    frames.frame()
                frames.move_to(-90.0)
                images[interval] = frames.frame()
        assert _difference(images[1], images[3]) < 0.25

    def test_a_light_that_turned_draws_every_cascade_again(self, monkeypatch):
        with _Frames(3, monkeypatch) as frames:
            for _ in range(7):
                frames.frame()
            frames.sun.direction = (-1.0, -1.0, 0.3)
            frames.depth_draws = 0
            frames.frame()
            assert frames.depth_draws == CASCADES

    def test_a_light_that_turned_has_the_shadows_it_has_without_the_interval(self, monkeypatch):
        images = {}
        for interval in (1, 3):
            with _Frames(interval, monkeypatch) as frames:
                for _ in range(4):
                    frames.frame()
                frames.sun.direction = (-1.0, -1.0, 0.3)
                images[interval] = frames.frame()
        assert _difference(images[1], images[3]) < 0.25

    def test_a_view_that_moves_a_little_each_frame_stays_close_to_the_shadows_without_it(
            self, monkeypatch):
        images, draws = {}, {}
        for interval in (1, 3):
            with _Frames(interval, monkeypatch) as frames:
                for step in range(16):
                    frames.move_to(-0.4 * step)
                    image = frames.frame()
                images[interval], draws[interval] = image, frames.depth_draws
        assert _difference(images[1], images[3]) < 0.6
        assert draws[3] < draws[1]
