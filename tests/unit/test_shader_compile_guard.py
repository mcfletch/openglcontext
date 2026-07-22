"""A partial shader-program compile must not leave the object
half-populated. On any sub-program failure every handle is nulled and an `_ok`
flag stays False, and every `use*` entry point refuses to bind rather than
binding `None` and raising mid-frame far from the cause. These run without a GL
context by driving the failure-handling paths directly.
"""
import pytest

from OpenGLContext.passes.shaderpass import VRML97ShaderProgram


def _prog():
    return VRML97ShaderProgram()


class TestPartialCompileHandling:
    def test_fresh_program_is_not_ok(self):
        assert _prog()._ok is False

    def test_clear_programs_nulls_all_handles(self):
        p = _prog()
        p.program, p.unlit_program, p.depth_program = 1, 2, 3
        p.point_program, p.line_program, p.vertex_color_program = 4, 5, 6
        p._ok = True
        p._clear_programs()
        assert p.program is None and p.depth_program is None
        assert p.unlit_program is None and p.point_program is None
        assert p.line_program is None and p.vertex_color_program is None
        assert p._ok is False

    def test_use_returns_false_when_not_ok(self):
        p = _prog()
        p._compiled = True   # already attempted; don't trigger a real GL compile
        p._ok = False
        assert p.use(lit=True) is False
        assert p.use(lit=False) is False

    def test_use_depth_returns_none_when_not_ok(self):
        p = _prog()
        p._compiled = True
        p._ok = False
        assert p.use_depth() is None

    def test_use_point_and_line_false_when_not_ok(self):
        p = _prog()
        p._compiled = True
        p._ok = False
        assert p.use_point() is False
        assert p.use_line() is False


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
