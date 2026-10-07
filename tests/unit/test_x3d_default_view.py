"""How a document is seen: X3D's field of view and its default viewpoint.

A Viewpoint's ``fieldOfView`` spans the smaller of the window's width and
height (ISO/IEC 19775-1, 23.4.6; VRML97 6.53), so in a portrait window it is
the horizontal angle. A document that binds no viewpoint is seen through the
default one: from (0, 0, 10) looking down -z, ``fieldOfView`` pi/4. The
engine's own camera keeps its vertical field of view for a scene built in
code.
"""
from math import atan, degrees, pi, tan

import numpy as np
import pytest

from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.passes import viewpointbinding
from OpenGLContext.scenegraph.basenodes import Transform, Viewpoint, sceneGraph
from OpenGLContext.scenegraph.scenegraph import X3DScene


def vertical(fov, aspect):
    """The vertical angle, in degrees, that spans `fov` across the narrower width"""
    return degrees(2 * atan(tan(fov / 2) / aspect))


class TestTheSmallerDimension:
    def test_a_landscape_view_spans_its_height(self):
        platform = ViewPlatform(aspect=2.0)
        platform.setFrustum(pi / 4, across='smaller')
        assert platform.frustum[0] == pytest.approx(45.0)

    def test_a_portrait_view_spans_its_width(self):
        platform = ViewPlatform(aspect=0.5)
        platform.setFrustum(pi / 4, across='smaller')
        assert platform.frustum[0] == pytest.approx(vertical(pi / 4, 0.5))

    def test_a_resize_keeps_the_rule(self):
        platform = ViewPlatform(aspect=2.0)
        platform.setFrustum(pi / 4, across='smaller')
        platform.setViewport(300, 600)
        assert platform.frustum[0] == pytest.approx(vertical(pi / 4, 0.5))
        platform.setViewport(600, 300)
        assert platform.frustum[0] == pytest.approx(45.0)

    def test_the_engines_camera_spans_its_height(self):
        platform = ViewPlatform(aspect=0.5)
        platform.setFrustum(pi / 3)
        assert platform.frustum[0] == pytest.approx(60.0)
        platform.setViewport(600, 300)
        assert platform.frustum[0] == pytest.approx(60.0)

    def test_the_projection_matrix_follows(self):
        platform = ViewPlatform(aspect=0.5)
        platform.setFrustum(pi / 4, across='smaller')
        matrix = np.asarray(platform.viewMatrix())
        # Column-major focal terms: x scale is 1/tan(horizontal half-angle).
        assert matrix[0, 0] == pytest.approx(1.0 / tan(pi / 8), rel=1e-5)

    def test_a_viewpoint_spans_the_smaller_dimension(self):
        platform = ViewPlatform(aspect=0.5)
        Viewpoint(fieldOfView=pi / 4).project(platform)
        assert platform.frustum[0] == pytest.approx(vertical(pi / 4, 0.5))


class FakeContext:
    def __init__(self, scene, aspect=2.0):
        self.scene = scene
        self.platform = ViewPlatform(position=(0, 0, 10), aspect=aspect)

    def getSceneGraph(self):
        return self.scene

    def getViewPlatform(self):
        return self.platform


class _Path(tuple):
    def transformMatrix(self):
        return np.identity(4)

    def quaternion(self):
        from OpenGLContext import quaternion  # noqa: PLC0415 kept with its use
        return quaternion.fromXYZR(0, 1, 0, 0)


class TestTheDefaultViewpoint:
    def test_a_document_without_one_is_seen_through_x3ds(self):
        context = FakeContext(X3DScene(children=[Transform()]))
        viewpointbinding.bind_scene_viewpoint(context)
        assert context.scene.boundViewpoint is viewpointbinding.default_viewpoint(context.scene)
        # The declared default is 0.7854, pi/4 to four places.
        assert context.platform.frustum[0] == pytest.approx(degrees(0.7854))
        assert tuple(context.platform.position[:3]) == pytest.approx((0, 0, 10))

    def test_a_scene_built_in_code_keeps_the_engines_camera(self):
        context = FakeContext(sceneGraph(children=[Transform()]))
        before = context.platform.frustum
        viewpointbinding.bind_scene_viewpoint(context)
        assert context.platform.frustum == before

    def test_a_viewpoint_arriving_later_is_jumped_to(self):
        scene = X3DScene(children=[Transform()])
        context = FakeContext(scene)
        viewpointbinding.bind_scene_viewpoint(context)
        arrived = Viewpoint(position=(5, 0, 0), fieldOfView=pi / 2)
        scene.viewpointPaths = (_Path((scene, arrived)),)
        viewpointbinding.bind_scene_viewpoint(context)
        assert tuple(context.platform.position[:3]) == pytest.approx((5, 0, 0))
        assert context.platform.frustum[0] == pytest.approx(90.0)
