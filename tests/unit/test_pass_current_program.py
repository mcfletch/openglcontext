"""``FlatPass.current_program()``: the bound-program accessor raw-GL nodes restore to.

The vegetation, terrain and particle nodes bind their own program to draw and then
restore the pass's via this accessor, instead of a
``glGetIntegerv(GL_CURRENT_PROGRAM)`` round-trip. It reads the program the pass
tracks on its ``shader_program`` (a VRML97 or PBR shader program), so it needs no GL
context.
"""
import types

from OpenGLContext.passes._flat import FlatPass


def _pass(shader_program):
    p = FlatPass.__new__(FlatPass)
    p._shader_program_instance = shader_program
    return p


def test_zero_when_no_shader_program():
    assert _pass(None).current_program() == 0


def test_uses_the_active_program():
    sp = types.SimpleNamespace(_active_program=42, program=7)
    assert _pass(sp).current_program() == 42


def test_falls_back_to_program_when_none_active():
    sp = types.SimpleNamespace(_active_program=None, program=7)
    assert _pass(sp).current_program() == 7


def test_zero_when_nothing_is_bound():
    sp = types.SimpleNamespace(_active_program=None, program=0)
    assert _pass(sp).current_program() == 0
