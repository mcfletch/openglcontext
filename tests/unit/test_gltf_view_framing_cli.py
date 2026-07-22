"""The viewer's auto-fit framing is parametrized by --margin/--elevation/--tilt so
a per-scene metadata entry can pull the camera in on a model that under-fills the
frame. These exercise the parsing and the _frame() arithmetic without a GL context."""
import os
import sys

import pytest

_orig = dict(os.environ)
try:
    from OpenGLContext.bin import gltf_view
finally:
    for k in list(os.environ):
        if k not in _orig:
            del os.environ[k]
    os.environ.update(_orig)


class TestFramingArgs:
    def test_defaults_are_none_so_frame_uses_builtins(self):
        a = gltf_view.parse_args(['m.glb'])
        assert a.margin is None and a.elevation is None and a.tilt is None

    def test_values_parse(self):
        a = gltf_view.parse_args(['m.glb', '--margin', '0.8', '--elevation', '0.4',
                                  '--tilt', '-0.2'])
        assert a.margin == 0.8 and a.elevation == 0.4 and a.tilt == -0.2


class _Recorder:
    """Stand-in platform capturing what _frame would set."""
    def __init__(self):
        self.frustum = self.position = self.orientation = None

    def setFrustum(self, *a):
        self.frustum = a

    def setPosition(self, p):
        self.position = p

    def setOrientation(self, o):
        self.orientation = o


def _frame_with(margin=None, elevation=None, tilt=None, radius=10.0):
    import argparse
    stub = gltf_view.TestContext.__new__(gltf_view.TestContext)
    stub.config = argparse.Namespace(margin=margin, elevation=elevation, tilt=tilt)
    stub.platform = _Recorder()
    gltf_view.TestContext._frame(stub, radius)
    return stub.platform


class TestFrameArithmetic:
    def test_defaults_reproduce_builtin_framing(self):
        p = _frame_with()                       # all None -> built-in constants
        assert p.position[1] == pytest.approx(10.0 * 0.22)     # elevation 0.22
        assert p.orientation == (1, 0, 0, 0.10)                # tilt 0.10

    def test_smaller_margin_pulls_camera_in(self):
        far = _frame_with(margin=1.15).position[2]
        near = _frame_with(margin=0.8).position[2]
        assert near < far                        # tighter framing => closer camera

    def test_elevation_and_tilt_are_applied(self):
        p = _frame_with(elevation=0.5, tilt=-0.3)
        assert p.position[1] == pytest.approx(10.0 * 0.5)
        assert p.orientation == (1, 0, 0, -0.3)
