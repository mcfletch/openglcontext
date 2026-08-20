"""Water moved on the card: the same field the processor computes.

The point of putting the wave in the vertex shader is that the mesh is uploaded
once and only a handful of uniforms change. The danger is that the two copies
of the field drift, and a surface that floats a boat at one height and draws it
at another is worse than one that does neither -- so what is asserted hardest
here is that they are the same numbers.
"""
import re

import pytest

from OpenGLContext.passes import shadersource
from OpenGLContext.scenegraph.water.surface import (
    CHOPPY,
    RIPPLE_SCALE,
    _TRAINS,
)


def _source(name):
    """A shader as the compiler sees it: includes resolved."""
    import os
    return shadersource.preprocess_shader(
        os.path.join(shadersource.SHADER_DIR, name))


def _include(name):
    """An include's own text; it carries no #version to preprocess."""
    import os
    with open(os.path.join(shadersource.SHADER_DIR, name)) as handle:
        return handle.read()


class TestTheShaderHasIt:
    def test_the_pbr_program_moves_water(self) -> None:
        assert 'applyWave(position, normal)' in _source('pbr.vert')

    def test_the_depth_program_moves_it_too(self) -> None:
        """Or a wave casts the shadow of the plane it was meshed as."""
        assert 'applyWave(' in _source('shadow_depth.vert')

    def test_the_wave_runs_after_the_mesh_s_own_animation(self) -> None:
        """A surface deform belongs to what is painted on the mesh, so it comes
        after skinning, exactly as it does on the processor."""
        text = _source('pbr.vert')
        assert text.index('applySkin(') < text.index('applyWave(')

    def test_it_is_off_unless_something_turns_it_on(self) -> None:
        assert 'if (!waveEnabled)' in _include('_wave_inc.glsl')


class TestTheTwoFieldsAgree:
    """The numbers in the shader are the numbers in the module."""

    def _trains(self):
        text = _include('_wave_inc.glsl')
        block = text[text.index('WAVE_TRAINS'):text.index('WAVE_RIPPLE_SCALE')]
        return [tuple(float(n) for n in row)
                for row in re.findall(
                    r'vec3\(\s*(-?[\d.]+),\s*(-?[\d.]+),\s*(-?[\d.]+)\s*\)',
                    block)]

    def test_there_are_as_many_trains(self) -> None:
        assert len(self._trains()) == len(_TRAINS)

    def test_every_train_matches(self) -> None:
        for shader, module in zip(self._trains(), _TRAINS, strict=True):
            assert shader == pytest.approx(module, abs=1e-6)

    def test_the_ripple_repeats_over_the_same_distance(self) -> None:
        text = _include('_wave_inc.glsl')
        found = re.search(r'WAVE_RIPPLE_SCALE\s*=\s*([\d.]+)', text)
        assert found and float(found.group(1)) == pytest.approx(RIPPLE_SCALE)


class TestTurningItOn:
    class Program:
        """As much of the shader program as the wave asks anything of."""

        def __init__(self):
            self.set = {}

        def _set_uniform1i(self, name, value, program=None):
            self.set[name] = value

        def _set_uniform1f(self, name, value, program=None):
            self.set[name] = value

        def _set_uniform2f(self, name, value, program=None):
            self.set[name] = value

    def _program(self):
        from OpenGLContext.passes.pbrpass import PBRShaderProgram
        program = self.Program()
        program.program = 1
        program.set_wave = PBRShaderProgram.set_wave.__get__(program)
        return program

    def test_a_style_switches_it_on(self) -> None:
        program = self._program()
        program.set_wave(CHOPPY, 0.0)
        assert program.set['waveEnabled'] == 1

    def test_the_style_reaches_the_card(self) -> None:
        program = self._program()
        program.set_wave(CHOPPY, 2.5)
        assert program.set['waveAmplitude'] == pytest.approx(CHOPPY.amplitude)
        assert program.set['waveLength'] == pytest.approx(CHOPPY.wavelength)
        assert program.set['waveSpeed'] == pytest.approx(CHOPPY.speed)
        assert program.set['waveTime'] == pytest.approx(2.5)

    def test_nothing_switches_it_off(self) -> None:
        """Or the hillside after a lake ripples too."""
        program = self._program()
        program.set_wave(CHOPPY, 0.0)
        program.set_wave(None)
        assert program.set['waveEnabled'] == 0

    def test_only_the_flag_is_written_when_it_is_off(self) -> None:
        """A shape that is not water pays one uniform, not seven."""
        program = self._program()
        program.set_wave(None)
        assert set(program.set) == {'waveEnabled'}
