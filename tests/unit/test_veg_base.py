"""Shared vegetation base-class preamble (no GL for the guarded paths).

:class:`InstancedVegBase` factors the render guard, the abstract stream/draw
contract, and the large bounding volume shared by the instanced vegetation
nodes. The guarded early-outs and the abstract stubs need no GL context.
"""
import types

import pytest

from OpenGLContext.scenegraph.vegetation.base import InstancedVegBase


def _node(bounds=(2.0, 3.0, 4.0)):
    n = InstancedVegBase()
    n.bounds = bounds
    return n


def test_bounding_volume_uses_node_bounds():
    bv = _node((5.0, 6.0, 7.0)).boundingVolume(None)
    assert tuple(bv.size) == (5.0, 6.0, 7.0)


def test_render_is_a_noop_during_shadow_pass():
    # A shadow pass must return before any GL init (unlit impostors cast nothing).
    assert _node().render(types.SimpleNamespace(shadow_pass=True, visible=True)) == 1


def test_render_is_a_noop_when_not_visible():
    assert _node().render(types.SimpleNamespace(shadow_pass=False, visible=False)) == 1


def test_stream_is_abstract():
    with pytest.raises(NotImplementedError):
        _node()._stream()


def test_draw_is_abstract():
    with pytest.raises(NotImplementedError):
        _node()._draw(None)


def test_base_upload_constants_is_a_noop():
    assert _node()._upload_constants() is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
