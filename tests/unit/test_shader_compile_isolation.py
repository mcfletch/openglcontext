"""Per-program shader-compile isolation.

`VRML97ShaderProgram.compile` wrapped all six program compiles in one try/except:
a break in any one shader ran `_clear_programs()` and nulled *every* already-linked
program, taking down the whole shader system instead of degrading one feature.
Each program now compiles in its own `_compile_one`; a `None` for one leaves the
others intact, and only a failed *lit* program makes the system report not-ok.

`_compile_one` is stubbed so no GL context is needed.
"""
import pytest

from OpenGLContext.passes import shaderpass
from OpenGLContext.passes.shaderpass import VRML97ShaderProgram


def _prepared(monkeypatch, failing_labels):
    sp = VRML97ShaderProgram.__new__(VRML97ShaderProgram)
    sp._compiled = False
    sp._ok = False
    monkeypatch.setattr(shaderpass, 'resolve_shadow_config', lambda: (0, False))
    monkeypatch.setattr(shaderpass, 'glUseProgram', lambda *a, **k: None, raising=False)
    sp.init_shadow_samplers = lambda: None

    def fake_compile_one(label, *a, **k):
        return None if label in failing_labels else 'prog_%s' % label
    sp._compile_one = fake_compile_one
    return sp


class TestCompileIsolation:
    def test_one_broken_feature_shader_keeps_the_rest(self, monkeypatch):
        sp = _prepared(monkeypatch, {'line'})
        ok = sp.compile()
        assert ok is True                        # lit compiled → system usable
        assert sp.program == 'prog_lit'
        assert sp.line_program is None           # only the broken one is dropped
        assert sp.unlit_program == 'prog_unlit'  # NOT nulled by the line failure
        assert sp.point_program == 'prog_point'
        assert sp.vertex_color_program == 'prog_vertex_color'

    def test_lit_failure_reports_not_ok_but_attempts_others(self, monkeypatch):
        sp = _prepared(monkeypatch, {'lit'})
        ok = sp.compile()
        assert ok is False                       # essential program missing
        assert sp.program is None
        # the others were still attempted, not skipped/nulled wholesale
        assert sp.unlit_program == 'prog_unlit'

    def test_all_ok(self, monkeypatch):
        sp = _prepared(monkeypatch, set())
        assert sp.compile() is True
        assert all(getattr(sp, n) is not None for n in (
            'program', 'unlit_program', 'vertex_color_program',
            'point_program', 'line_program', 'depth_program'))
