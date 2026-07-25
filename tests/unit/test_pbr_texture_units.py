"""The PBR fragment program must keep every shadow /
material / IBL / transmission sampler within the baseline GL 3.3 fragment
texture-unit budget (GL_MAX_TEXTURE_IMAGE_UNITS is only guaranteed >= 16, i.e.
valid unit indices are 0..15). No GL context required -- these are the static
unit assignments the program uploads with glUniform1i."""
import pytest

from OpenGLContext.passes.pbrpass import PBR_UNITS
from OpenGLContext.passes.ibl import IBL_UNITS
from OpenGLContext.passes.transmission import TRANSMISSION_UNIT
from OpenGLContext.passes.shaderpass import VRML97ShaderProgram as V

BASELINE_UNITS = 16


def _shadow_units():
    units = {V.SHADOW_ARRAY_UNIT, V.SHADOW_ARRAY_RAW_UNIT}
    # the cube-array packed path uses one unit at SHADOW_CUBE_BASE; the per-slot
    # fallback uses SHADOW_CUBE_BASE .. +MAX_SHADOW_LIGHTS-1 -- cover both.
    for s in range(V.MAX_SHADOW_LIGHTS):
        units.add(V.SHADOW_CUBE_BASE + s)
    return units


def _pbr_units():
    units = set(PBR_UNITS.values()) | set(IBL_UNITS.values())
    units.add(TRANSMISSION_UNIT)
    return units


def test_all_sampler_units_within_baseline_budget():
    every = _pbr_units() | _shadow_units()
    assert max(every) < BASELINE_UNITS, (
        "max texture unit %d exceeds the 16-unit GL 3.3 budget" % max(every))


def test_pbr_units_do_not_collide_with_shadow_units():
    assert _pbr_units().isdisjoint(_shadow_units())


def test_pbr_sampler_units_are_unique():
    values = list(PBR_UNITS.values()) + list(IBL_UNITS.values()) + [TRANSMISSION_UNIT]
    assert len(values) == len(set(values))


def test_only_the_lightmap_uses_scratch_unit_zero():
    # Unit 0 is the conventional scratch/bind unit, so the semantic PBR maps stay
    # off it. The lightmap is the one exception: units 1-15 are fully allocated
    # and baked lighting has to work inside the guaranteed-16 budget.
    on_zero = {name for name, unit in PBR_UNITS.items() if unit == 0}
    assert on_zero == {'lightmap'}
    assert 0 not in set(IBL_UNITS.values()) | {TRANSMISSION_UNIT}


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
