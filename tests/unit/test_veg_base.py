"""Shared vegetation base-class preamble (no GL for the guarded paths).

:class:`InstancedVegBase` factors the render guard, the abstract stream/draw
contract, and the large bounding volume shared by the instanced vegetation
nodes. The guarded early-outs and the abstract stubs need no GL context.
"""
import types

import pytest

from OpenGLContext.scenegraph.fog import FOG_DENSITY, FOG_LINEAR, FOG_NONE, Fog
from OpenGLContext.scenegraph.instancedgl import DEFAULT_FOG, frame_fog
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
        _node()._stream()  # noqa: SLF001 the hooks a vegetation layer subclass implements


def test_draw_is_abstract():
    with pytest.raises(NotImplementedError):
        _node()._draw(None)  # noqa: SLF001 the hooks a vegetation layer subclass implements


def test_base_upload_constants_is_a_noop():
    assert _node()._upload_constants({}) is None  # noqa: SLF001 the hooks a vegetation layer subclass implements


class _Path:
    """A path to a Fog node, as a pass's ``currentFog`` answers one."""

    def __init__(self, fog, scale=1.0):
        self.fog, self.scale = fog, scale

    def __getitem__(self, index):
        return self.fog

    def transformMatrix(self):
        import numpy as np
        return np.diag([self.scale, self.scale, self.scale, 1.0])


def _pass_with(path):
    return types.SimpleNamespace(currentFog=lambda: path)


def test_a_mode_that_is_not_a_pass_is_fogged_by_the_default():
    assert frame_fog(types.SimpleNamespace()) == DEFAULT_FOG


def test_a_scene_with_no_fog_node_is_fogged_by_the_default():
    assert frame_fog(_pass_with(None)) == DEFAULT_FOG
    assert DEFAULT_FOG[0] == FOG_DENSITY


def test_the_bound_fog_node_is_the_frames_fog():
    fog = Fog(color=(0.2, 0.4, 0.6), visibilityRange=250.0)
    assert frame_fog(_pass_with(_Path(fog))) == (FOG_LINEAR, pytest.approx(1 / 250.0),
                                                 (pytest.approx(0.2), pytest.approx(0.4),
                                                  pytest.approx(0.6)))


def test_a_fog_placed_under_a_scale_carries_its_range_with_it():
    fog = Fog(visibilityRange=100.0)
    assert frame_fog(_pass_with(_Path(fog, scale=2.0)))[1] == pytest.approx(1 / 200.0)


def test_a_bound_fog_with_no_visible_range_is_no_fog_and_not_the_default():
    assert frame_fog(_pass_with(_Path(Fog())))[0] == FOG_NONE


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
