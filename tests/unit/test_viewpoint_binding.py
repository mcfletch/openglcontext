"""Unit tests for Viewpoint near/far and the core-profile viewpoint bridge (no GL).

These use lightweight fakes for the platform/context/scenegraph so the binding
logic is exercised directly without a render context.
"""
import pytest
import numpy as np

from OpenGLContext.scenegraph.basenodes import sceneGraph, Transform, Viewpoint
from OpenGLContext.passes import viewpointbinding
from OpenGLContext import quaternion
from OpenGLContext.passes.flatcore import FlatPass


class FakePlatform:
    def __init__(self):
        self.frustum_calls = []
        self.position = None
        self.orientation = None

    def setPosition(self, p):
        self.position = tuple(p)

    def setOrientation(self, o):
        self.orientation = tuple(o)

    def setFrustum(self, fov, aspect=None, near=None, far=None):
        self.frustum_calls.append((fov, aspect, near, far))


class FakeContext:
    def __init__(self, sg=None):
        self.platform = FakePlatform()
        self._sg = sg

    def getViewPlatform(self):
        return self.platform

    def getSceneGraph(self):
        return self._sg


class TestViewpointMoveTo:
    def test_applies_near_far_when_present(self):
        vp = Viewpoint(position=(1, 2, 3), fieldOfView=0.7)
        vp.near, vp.far = 0.25, 400.0
        ctx = FakeContext()

        class P:                       # a one-element path whose leaf is vp
            def __getitem__(self, i):
                return vp
            def transformMatrix(self):
                return np.identity(4)
            def quaternion(self):
                return quaternion.fromXYZR(0, 1, 0, 0)
        vp.moveTo(P(), ctx)
        fov, aspect, near, far = ctx.platform.frustum_calls[-1]
        assert (near, far) == (0.25, 400.0)
        assert round(fov, 2) == 0.7

    def test_near_far_default_none(self):
        vp = Viewpoint(position=(0, 0, 0), fieldOfView=0.9)
        ctx = FakeContext()

        class P:
            def __getitem__(self, i):
                return vp
            def transformMatrix(self):
                return np.identity(4)
            def quaternion(self):
                return quaternion.fromXYZR(0, 1, 0, 0)
        vp.moveTo(P(), ctx)
        _fov, _aspect, near, far = ctx.platform.frustum_calls[-1]
        assert near is None and far is None      # setFrustum leaves them unchanged


class TestCoreViewpointBridge:
    def _scene(self, n=3):
        vps = [Viewpoint(position=(i, 0, 0), description='cam%d' % i) for i in range(n)]
        sg = sceneGraph(children=list(vps))
        return sg, vps

    def test_binds_first_by_default(self):
        sg, vps = self._scene()
        sg.viewpointPaths = tuple(_Path(vp) for vp in vps)
        ctx = FakeContext(sg)
        viewpointbinding.bind_scene_viewpoint(ctx)
        assert sg.boundViewpoint is vps[0]
        assert ctx.platform.position == (0.0, 0.0, 0.0, 1.0)

    def test_binds_preselected_isbound(self):
        sg, vps = self._scene()
        vps[2].isBound = True
        sg.viewpointPaths = tuple(_Path(vp) for vp in vps)
        ctx = FakeContext(sg)
        viewpointbinding.bind_scene_viewpoint(ctx)
        assert sg.boundViewpoint is vps[2]
        assert ctx.platform.position == (2.0, 0.0, 0.0, 1.0)

    def test_cycles_to_next_when_unbound(self):
        sg, vps = self._scene()
        sg.viewpointPaths = tuple(_Path(vp) for vp in vps)
        ctx = FakeContext(sg)
        viewpointbinding.bind_scene_viewpoint(ctx)          # binds cam0
        # emulate OnNextViewpoint: unbind current
        sg.boundViewpoint.isBound = False
        viewpointbinding.bind_scene_viewpoint(ctx)          # advances to cam1
        assert sg.boundViewpoint is vps[1]

    def test_no_viewpoints_is_noop(self):
        sg = sceneGraph(children=[])
        ctx = FakeContext(sg)
        viewpointbinding.bind_scene_viewpoint(ctx)
        # `boundViewpoint` is an SFNode, so what it holds when it holds
        # nothing is the NULL node -- which is falsy, and is what the callers
        # in `context.py` and `sceneviewer.py` test it for.
        assert not getattr(sg, 'boundViewpoint', None)
        assert ctx.platform.position is None             # platform untouched


class TestTheRenderPassesPaths:
    """Binding reads what the render pass found, as it goes on finding it."""

    def test_a_viewpoint_nested_in_a_transform_is_bound_where_it_stands(self):
        inner = Viewpoint(position=(0, 0, 1), description='inner')
        sg = sceneGraph(children=[Transform(translation=(4, 0, 0),
                                            children=[inner])])
        ctx = FakeContext(sg)
        viewpointbinding.publish_viewpoints(ctx, FlatPass(sg, []))
        viewpointbinding.bind_scene_viewpoint(ctx)
        assert sg.boundViewpoint is inner
        assert tuple(round(v, 5) for v in ctx.platform.position) == (4, 0, 1, 1)

    def test_one_that_arrives_after_the_first_frame_can_be_bound(self):
        sg = sceneGraph(children=[])
        found = FlatPass(sg, [])
        ctx = FakeContext(sg)
        viewpointbinding.publish_viewpoints(ctx, found)
        viewpointbinding.bind_scene_viewpoint(ctx)
        late = Viewpoint(position=(0, 3, 0), description='late')
        sg.children.append(late)
        viewpointbinding.publish_viewpoints(ctx, found)
        viewpointbinding.bind_scene_viewpoint(ctx)
        assert sg.boundViewpoint is late


class _Path:
    """Minimal nodepath: identity transform, single leaf viewpoint."""
    def __init__(self, node):
        self._node = node

    def __getitem__(self, i):
        return self._node

    def transformMatrix(self):
        return np.identity(4)

    def quaternion(self):
        return quaternion.fromXYZR(0, 1, 0, 0)
