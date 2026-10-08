"""Unit tests for Viewpoint near/far and the core-profile viewpoint bridge (no GL).

These use lightweight fakes for the platform/context/scenegraph so the binding
logic is exercised directly without a render context.
"""
import pytest
import numpy as np

from OpenGLContext.scenegraph.basenodes import NavigationInfo, sceneGraph, Transform, Viewpoint
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

    def setFrustum(self, fov, aspect=None, near=None, far=None, across="height"):
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
        # Jumping between viewpoints, so each binding moves the platform at once.
        jump = NavigationInfo(transitionType=['TELEPORT'])
        sg = sceneGraph(children=[jump] + list(vps))
        jump.set_bind = True
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
        vps[2].set_bind = True
        sg.viewpointPaths = tuple(_Path(vp) for vp in vps)
        ctx = FakeContext(sg)
        viewpointbinding.bind_scene_viewpoint(ctx)
        assert sg.boundViewpoint is vps[2]
        assert ctx.platform.position == (2.0, 0.0, 0.0, 1.0)

    def test_cycles_to_the_next(self):
        sg, vps = self._scene()
        sg.viewpointPaths = tuple(_Path(vp) for vp in vps)
        ctx = FakeContext(sg)
        viewpointbinding.bind_scene_viewpoint(ctx)          # binds cam0
        viewpointbinding.next_viewpoint(ctx)
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


class _Path(tuple):
    """Minimal nodepath: identity transform, single leaf viewpoint."""
    def __new__(cls, node):
        return super().__new__(cls, (node,))

    def transformMatrix(self):
        return np.identity(4)

    def quaternion(self):
        return quaternion.fromXYZR(0, 1, 0, 0)


class TestAViewpointUnderATransform:
    """The Viewpoint's position and orientation are both taken through the
    transforms above it (X3D 19775-1, 23.4.7)"""

    def place(self, *transforms):
        from OpenGLContext.scenegraph.nodepath import NodePath  # noqa: PLC0415 kept with its use
        view = Viewpoint(position=(0, 0, 10), orientation=(1, 0, 0, -0.5))
        graph = sceneGraph()
        path = NodePath([]) + graph
        for transform in transforms:
            path = path + transform
        path = path + view
        context = FakeContext(graph)
        Viewpoint.moveTo(view, path, context)
        return context.platform

    def looking(self, platform):
        turned = quaternion.fromXYZR(*platform.orientation)
        return np.asarray(turned * [0.0, 0.0, -1.0, 0.0])[:3]

    def test_a_rotation_turns_where_it_looks(self, gl_context):
        """A Viewpoint 10 out along +Z, turned a quarter about Y with its
        Transform, stands on +X and looks back at the box at the origin"""
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
        scene = Loader.loads(
            b'<X3D version="3.3"><Scene><Transform rotation="0 1 0 1.5708">'
            b'<Viewpoint position="0 0 10"/></Transform><Shape><Appearance>'
            b'<Material diffuseColor="0 0 0" emissiveColor="1 0 0"/></Appearance><Box/>'
            b'</Shape></Scene></X3D>', 'a.x3d')
        with scene_context(scene, size=(32, 32)) as context:
            drawn_image(context)
            centre = drawn_image(context)[16, 16].astype(int)
            assert context.platform.position[:3] == pytest.approx((10, 0, 0), abs=1e-4)
        assert centre[0] > 200 and centre[1] < 40, centre

    def test_a_scale_does_not_change_where_it_looks(self):
        plain = self.place(Transform(rotation=(0, 1, 0, 0.7)))
        scaled = self.place(Transform(rotation=(0, 1, 0, 0.7), scale=(2, 3, 2)))
        assert self.looking(scaled) == pytest.approx(self.looking(plain), abs=1e-5)

    def test_nested_rotations_compose(self):
        platform = self.place(Transform(rotation=(0, 1, 0, 0.4)), Transform(rotation=(0, 1, 0, 0.3)))
        alone = self.place(Transform(rotation=(0, 1, 0, 0.7)))
        assert self.looking(platform) == pytest.approx(self.looking(alone), abs=1e-5)
