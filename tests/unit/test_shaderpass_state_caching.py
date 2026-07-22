"""Redundant per-frame GL is elided in the shader program.

Three costs the review flagged:
  * ``init_shadow_samplers`` re-uploaded the (static) sampler->unit mapping 2-3x
    per frame; it is now idempotent per program.
  * ``set_matrices``/``set_object_id`` did a ``glGetIntegerv(GL_CURRENT_PROGRAM)``
    driver round-trip on their default path, once per shape per frame; they now
    read the program the class last bound.
  * ``use*()`` re-issued ``glUseProgram`` for the already-bound program every
    shape; it now skips the redundant bind (reset each frame via ``begin_frame``).

GL entry points are stubbed so no context is needed.
"""
import pytest

from OpenGLContext.passes import shaderpass
from OpenGLContext.passes.shaderpass import VRML97ShaderProgram


def _prog(monkeypatch, uses=()):
    """A compiled-looking program with GL calls counted, not executed."""
    sp = VRML97ShaderProgram.__new__(VRML97ShaderProgram)
    sp._compiled = True
    sp._ok = True
    sp.program = 11
    sp.unlit_program = 12
    sp.vertex_color_program = 13
    sp.point_program = 14
    sp.line_program = 15
    sp.depth_program = 16
    sp._pick_active = False
    sp._current_object_id = 0
    sp._active_program = None
    sp._shadow_samplers_program = set()
    sp._shadow_program = None
    sp.MAX_SHADOW_LIGHTS = 2
    sp.shadow_cube_array = False
    sp.SHADOW_ARRAY_UNIT = 4
    sp.SHADOW_ARRAY_RAW_UNIT = 5
    sp.SHADOW_CUBE_BASE = 6
    counts = {'use': 0, 'sampler': 0, 'getint': 0}
    monkeypatch.setattr(shaderpass, 'glUseProgram',
                        lambda p: counts.__setitem__('use', counts['use'] + 1),
                        raising=False)
    monkeypatch.setattr(shaderpass, 'glGetIntegerv',
                        lambda *a: counts.__setitem__('getint', counts['getint'] + 1) or 999,
                        raising=False)
    sp._set_uniform1i = lambda *a, **k: counts.__setitem__('sampler', counts['sampler'] + 1)
    if hasattr(sp, 'begin_frame'):
        sp.begin_frame()
    return sp, counts


class TestInitShadowSamplersIdempotent:
    def test_applied_once_per_program(self, monkeypatch):
        sp, counts = _prog(monkeypatch)
        sp.init_shadow_samplers()
        first = counts['sampler']
        assert first > 0
        sp.init_shadow_samplers()
        sp.init_shadow_samplers()
        assert counts['sampler'] == first, "re-uploaded static sampler units"

    def test_reapplied_after_program_change(self, monkeypatch):
        sp, counts = _prog(monkeypatch)
        sp.init_shadow_samplers()
        first = counts['sampler']
        sp.program = 99                      # recompiled -> new program handle
        sp.init_shadow_samplers()
        assert counts['sampler'] > first


class TestActiveProgramTracking:
    def test_use_tracks_active_program(self, monkeypatch):
        sp, counts = _prog(monkeypatch)
        sp.use(lit=True)
        assert sp._active_program == sp.program

    def test_use_switches_track_active_program(self, monkeypatch):
        # The bind always issues glUseProgram (other passes bind their own program
        # mid-frame, so a skip-cache would go stale) but always records the program
        # so the default-arg lookups need no GL round-trip.
        sp, counts = _prog(monkeypatch)
        sp.use(lit=True)
        assert sp._active_program == sp.program
        sp.use(lit=False)
        assert sp._active_program == sp.unlit_program

    def test_default_program_uses_tracked_not_glGetIntegerv(self, monkeypatch):
        # set_matrices/set_object_id resolve their default program through
        # _program_for_default, which must not touch GL.
        monkeypatch.setattr(shaderpass, 'glGetIntegerv',
                            lambda *a: (_ for _ in ()).throw(
                                AssertionError("must not round-trip GL for the program")),
                            raising=False)
        sp, counts = _prog(monkeypatch)
        assert sp._program_for_default() == sp.program   # nothing bound -> lit
        sp.use(lit=False)
        assert sp._program_for_default() == sp.unlit_program
        assert counts['getint'] == 0

    def test_begin_frame_resets_active_program(self, monkeypatch):
        sp, counts = _prog(monkeypatch)
        sp.use(lit=True)
        assert sp._active_program is not None
        sp.begin_frame()
        assert sp._active_program is None
