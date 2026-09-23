"""The cameras a scene carries, and a view looking through one.

A VRML97 world's ``Viewpoint`` nodes and a glTF file's cameras (which the
loader builds as ``Viewpoint`` nodes) are the same thing to a view. The render
pass keeps a path to each; these tests build that pass over a scenegraph with
no GL, publish its paths the way a frame does, and read the cameras back.
"""
import math

import numpy as np
import pytest

from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform, view_kind
from OpenGLContext.multiview.viewpoints import (
    SceneCamera,
    first_camera,
    look_through,
    scene_cameras,
)
from OpenGLContext.multiview.views import View
from OpenGLContext.passes import viewpointbinding
from OpenGLContext.passes.flatcore import FlatPass
from OpenGLContext.scenegraph.basenodes import Transform, Viewpoint, sceneGraph


def _published(*children):
    """A scenegraph whose Viewpoint paths a pass has found and published."""
    graph = sceneGraph(children=list(children))
    found = FlatPass(graph, [])
    viewpointbinding.publish_viewpoints(_Context(graph), found)
    return graph, found


class _Context:
    def __init__(self, graph):
        self.graph = graph
        self.told = []

    def getSceneGraph(self):
        return self.graph

    def OnViewpointsChanged(self, paths):
        self.told.append(tuple(path[-1] for path in paths))


class TestFindingThem:
    def test_every_viewpoint_is_a_camera(self):
        graph, _pass = _published(Viewpoint(description='door'),
                                  Viewpoint(description='roof'))
        assert [camera.name for camera in scene_cameras(graph)] == ['door', 'roof']

    def test_a_scene_with_none_has_no_cameras(self):
        graph, _pass = _published(Transform())
        assert scene_cameras(graph) == []

    def test_nothing_is_found_before_a_pass_has_looked(self):
        assert scene_cameras(sceneGraph(children=[Viewpoint()])) == []

    def test_no_scene_has_no_cameras(self):
        assert scene_cameras(None) == []

    def test_an_unnamed_one_is_named_by_its_def_or_its_place(self):
        graph, _pass = _published(Viewpoint(), Viewpoint(DEF='Porch'))
        assert [camera.name for camera in scene_cameras(graph)] == ['Camera 1', 'Porch']

    def test_one_added_later_is_found_on_the_next_frame(self):
        graph, found = _published(Viewpoint(description='first'))
        graph.children.append(Viewpoint(description='second'))
        viewpointbinding.publish_viewpoints(_Context(graph), found)
        assert [camera.name for camera in scene_cameras(graph)] == ['first', 'second']

    def test_the_context_is_told_when_the_set_changes_and_only_then(self):
        graph = sceneGraph(children=[Viewpoint(description='first')])
        found = FlatPass(graph, [])
        context = _Context(graph)
        viewpointbinding.publish_viewpoints(context, found)
        viewpointbinding.publish_viewpoints(context, found)
        assert len(context.told) == 1
        graph.children.append(Viewpoint(description='second'))
        viewpointbinding.publish_viewpoints(context, found)
        assert len(context.told) == 2 and len(context.told[-1]) == 2


class TestWhereEachStands:
    def test_the_default_viewpoint_looks_down_minus_z(self):
        graph, _pass = _published(Viewpoint(position=(0.0, 1.0, 10.0)))
        camera = scene_cameras(graph)[0]
        assert camera.position == pytest.approx((0.0, 1.0, 10.0))
        assert camera.forward == pytest.approx((0.0, 0.0, -1.0))
        assert camera.up == pytest.approx((0.0, 1.0, 0.0))

    def test_its_orientation_turns_where_it_looks(self):
        graph, _pass = _published(
            Viewpoint(orientation=(0.0, 1.0, 0.0, math.pi / 2.0)))
        camera = scene_cameras(graph)[0]
        assert camera.forward == pytest.approx((-1.0, 0.0, 0.0), abs=1e-6)

    def test_one_inside_a_transform_is_where_the_transform_puts_it(self):
        graph, _pass = _published(Transform(
            translation=(5.0, 0.0, 0.0),
            rotation=(0.0, 1.0, 0.0, math.pi),
            children=[Viewpoint(position=(0.0, 2.0, 3.0), description='in')]))
        camera = scene_cameras(graph)[0]
        assert camera.position == pytest.approx((5.0, 2.0, -3.0), abs=1e-5)
        assert camera.forward == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)

    def test_its_lens_is_the_viewpoints(self):
        graph, _pass = _published(Viewpoint(fieldOfView=0.5))
        assert scene_cameras(graph)[0].fov == pytest.approx(0.5)

    def test_it_knows_the_node_it_came_from(self):
        viewpoint = Viewpoint()
        graph, _pass = _published(viewpoint)
        assert scene_cameras(graph)[0].viewpoint is viewpoint


class TestTheFirstOne:
    def test_it_is_the_first_the_scene_declares(self):
        graph, _pass = _published(Viewpoint(description='a'), Viewpoint(description='b'))
        assert first_camera(scene_cameras(graph)).name == 'a'

    def test_with_none_there_is_none(self):
        assert first_camera([]) is None


def _camera(position=(0.0, 2.0, 10.0), forward=(0.0, 0.0, -1.0), fov=0.6, **named):
    return SceneCamera(name='cam', position=position, forward=forward,
                       up=(0.0, 1.0, 0.0), fov=fov, **named)


def _clip(view, point, viewport=(400, 300)):
    view.camera.setViewport(*viewport)
    clip = np.append(np.asarray(point, 'd'), 1.0) @ view.camera.matrix()
    return clip[:3] / clip[3]


class TestLookingThroughOne:
    def test_an_orbiting_view_is_moved_to_the_camera(self):
        orbit = OrbitView(nearest=0.01)
        view = View(OrbitViewPlatform(orbit))
        assert look_through(view, _camera(), distance=8.0)
        assert view.camera.view is orbit
        assert orbit.position() == pytest.approx((0.0, 2.0, 10.0))
        assert orbit.fov == pytest.approx(math.degrees(0.6))

    def test_what_the_camera_looks_at_is_in_the_middle(self):
        view = View(OrbitViewPlatform(OrbitView(nearest=0.01, lowest=-89.0)))
        look_through(view, _camera(), distance=8.0)
        assert _clip(view, (0.0, 2.0, 0.0))[:2] == pytest.approx((0.0, 0.0), abs=1e-6)

    def test_an_orthographic_view_is_given_a_perspective_camera(self):
        view = View(OrthoViewPlatform(OrthoView('front')))
        assert look_through(view, _camera(), distance=8.0)
        assert view_kind(view) == 'perspective'
        assert view.camera.view.position() == pytest.approx((0.0, 2.0, 10.0))

    def test_without_a_distance_it_keeps_the_one_it_had(self):
        orbit = OrbitView(distance=40.0)
        view = View(OrbitViewPlatform(orbit))
        look_through(view, _camera())
        assert orbit.distance == pytest.approx(40.0)
        assert orbit.position() == pytest.approx((0.0, 2.0, 10.0))

    def test_a_view_drawn_through_the_window_binds_the_viewpoint(self):
        first, second = Viewpoint(description='a'), Viewpoint(description='b')
        graph, _pass = _published(first, second)
        first.isBound = True
        graph.boundViewpoint = first
        view = View()
        assert look_through(view, scene_cameras(graph)[1])
        assert second.isBound and not first.isBound

    def test_a_view_drawn_through_the_window_needs_a_viewpoint_to_bind(self):
        assert not look_through(View(), _camera())
