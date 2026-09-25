"""Transmissive / BLEND fragments write the packed object id into
MRT attachment 1. With alpha blending enabled for the colour attachment, the same
blend would average the id against whatever opaque id sits behind the glass, so a
pick there returns garbage. The transparent passes must disable blending on the
object-id attachment (indexed blend enable) whenever MRT picking is active.
"""
import inspect
import logging

import pytest

from OpenGLContext.passes import _flat


class TestDisableObjectIdBlendHelper:
    def test_targets_attachment_one(self, monkeypatch):
        calls = []
        monkeypatch.setattr(_flat, 'glDisablei', lambda cap, i: calls.append((cap, i)))
        _flat.disable_object_id_blend()
        assert calls == [(_flat.GL_BLEND, _flat.OBJECT_ID_ATTACHMENT)]
        assert _flat.OBJECT_ID_ATTACHMENT == 1

    def test_swallows_driver_error(self, monkeypatch, caplog):
        """A driver without indexed enables keeps its blend state; the
        failure is logged rather than raised into the pass."""
        def boom(cap, i):
            raise RuntimeError("no indexed blend")
        monkeypatch.setattr(_flat, 'glDisablei', boom)
        caplog.set_level(logging.DEBUG, logger=_flat.log.name)
        assert _flat.disable_object_id_blend() is None
        assert [r.getMessage() for r in caplog.records] == [
            'indexed blend disable unavailable: no indexed blend']


class TestTransparentPassesGuardObjectId:
    def test_shader_transparent_disables_id_blend(self):
        src = inspect.getsource(_flat.FlatPass.shaderRenderTransparent)
        assert 'disable_object_id_blend()' in src

    def test_transmissive_pass_disables_id_blend(self):
        src = inspect.getsource(_flat.FlatPass.shaderRenderTransmissive)
        assert 'disable_object_id_blend()' in src


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
