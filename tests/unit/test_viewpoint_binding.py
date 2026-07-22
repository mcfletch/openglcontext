"""Unit tests for Viewpoint near/far and the core-profile viewpoint bridge (no GL).

These use lightweight fakes for the platform/context/scenegraph so the binding
logic is exercised directly without a render context.
"""
import pytest

from OpenGLContext.scenegraph.basenodes import Viewpoint, sceneGraph
from OpenGLContext.passes import rendervisitor


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
                import numpy as np
                return np.identity(4)
            def quaternion(self):
                from OpenGLContext import quaternion
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
                import numpy as np
                return np.identity(4)
            def quaternion(self):
                from OpenGLContext import quaternion
                return quaternion.fromXYZR(0, 1, 0, 0)
        vp.moveTo(P(), ctx)
        _fov, _aspect, near, far = ctx.platform.frustum_calls[-1]
        assert near is None and far is None      # setFrustum leaves them unchanged


class TestCoreViewpointBridge:
    def _scene(self, n=3):
        vps = [Viewpoint(position=(i, 0, 0), description='cam%d' % i) for i in range(n)]
        sg = sceneGraph(children=list(vps))
        return sg, vps

    def test_binds_first_by_default(self, monkeypatch):
        sg, vps = self._scene()
        monkeypatch.setattr(rendervisitor.visitor, 'find',
                            lambda ctx, types: [_Path(vp) for vp in vps])
        ctx = FakeContext(sg)
        rendervisitor.bind_scene_viewpoint(ctx)
        assert sg.boundViewpoint is vps[0]
        assert ctx.platform.position == (0.0, 0.0, 0.0, 1.0)

    def test_binds_preselected_isbound(self, monkeypatch):
        sg, vps = self._scene()
        vps[2].isBound = True
        monkeypatch.setattr(rendervisitor.visitor, 'find',
                            lambda ctx, types: [_Path(vp) for vp in vps])
        ctx = FakeContext(sg)
        rendervisitor.bind_scene_viewpoint(ctx)
        assert sg.boundViewpoint is vps[2]
        assert ctx.platform.position == (2.0, 0.0, 0.0, 1.0)

    def test_cycles_to_next_when_unbound(self, monkeypatch):
        sg, vps = self._scene()
        monkeypatch.setattr(rendervisitor.visitor, 'find',
                            lambda ctx, types: [_Path(vp) for vp in vps])
        ctx = FakeContext(sg)
        rendervisitor.bind_scene_viewpoint(ctx)          # binds cam0
        # emulate OnNextViewpoint: unbind current
        sg.boundViewpoint.isBound = False
        rendervisitor.bind_scene_viewpoint(ctx)          # advances to cam1
        assert sg.boundViewpoint is vps[1]

    def test_no_viewpoints_is_noop(self, monkeypatch):
        sg = sceneGraph(children=[])
        monkeypatch.setattr(rendervisitor.visitor, 'find', lambda ctx, types: [])
        ctx = FakeContext(sg)
        rendervisitor.bind_scene_viewpoint(ctx)
        assert getattr(sg, 'boundViewpoint', None) in (None, [])
        assert ctx.platform.position is None             # platform untouched


class _Path:
    """Minimal nodepath: identity transform, single leaf viewpoint."""
    def __init__(self, node):
        self._node = node

    def __getitem__(self, i):
        return self._node

    def transformMatrix(self):
        import numpy as np
        return np.identity(4)

    def quaternion(self):
        from OpenGLContext import quaternion
        return quaternion.fromXYZR(0, 1, 0, 0)
