"""The lit/PBR fragment sources stay within the fragment texture-unit budget.

The per-slot shadow sampler layout demanded up to 20 fragment
texture image units and failed to link on baseline GL 3.3 (16-unit) drivers.
These GL-free tests evaluate the source's preprocessor directives for a given
configuration and assert the *active* shadow samplers fit the packed budget.
"""
import re

import pytest

from OpenGLContext.passes import shaderpass


def _preprocess(src, defines):
    """Resolve the #if/#ifdef/#ifndef/#else/#endif the shadow sources use.

    Supports the exact directive set present: `#ifdef NAME`, `#ifndef NAME`,
    `#if MAX_SHADOW_LIGHTS > <int>`, `#else`, `#endif` (arbitrarily nested).
    """
    out, stack = [], []          # stack of (active_here,)
    active = lambda: all(s for s in stack)
    for line in src.split('\n'):
        s = line.strip()
        if s.startswith('#ifdef'):
            stack.append(active() and s.split()[1] in defines)
        elif s.startswith('#ifndef'):
            stack.append(active() and s.split()[1] not in defines)
        elif s.startswith('#if '):
            m = re.match(r'#if\s+(\w+)\s*>\s*(\d+)', s)
            cond = bool(m) and int(defines.get(m.group(1), 0)) > int(m.group(2))
            stack.append(active() and cond)
        elif s.startswith('#else'):
            top = stack.pop()
            stack.append((not top) and (active()))
        elif s.startswith('#endif'):
            stack.pop()
        elif active():
            out.append(line)
    return '\n'.join(out)


def _active_samplers(frag, n, cube_array):
    src = shaderpass.load_fragment_source(frag, n, cube_array)
    defines = {'MAX_SHADOW_LIGHTS': n, 'MAX_LIGHTS': 8, 'MAX_CASCADES': 4}
    if cube_array:
        defines['SHADOW_CUBE_ARRAY'] = 1
    resolved = _preprocess(src, defines)
    out = {}
    for m in re.finditer(r'uniform\s+(\w*sampler\w+)\s+([^;]+);', resolved):
        for name in m.group(2).split(','):
            out[name.strip()] = m.group(1)
    return out


def _shadow_units(samplers, n, cube_array):
    """Distinct fragment texture image units the packed lit shader spends."""
    material = 1                                   # diffuseTexture at unit 0
    fixed = 2                                      # shadowArray + shadowArrayRaw
    cube = 1 if cube_array else n                  # cube-array vs one per slot
    return material + fixed + cube


class TestFragmentSourcePacking:
    @pytest.mark.parametrize('frag', ['vrml97_lighting.frag', 'pbr.frag'])
    def test_no_per_slot_2d_or_array_shadow_samplers(self, frag):
        # The old shadow2D_N / shadowArr_N / shadow2Draw_N unrolled samplers are gone.
        src = shaderpass.load_fragment_source(frag, 4, cube_array=False)
        assert 'shadow2D_' not in src
        assert 'shadowArr_' not in src
        assert 'shadow2Draw_' not in src

    @pytest.mark.parametrize('frag', ['vrml97_lighting.frag', 'pbr.frag'])
    def test_spot_and_csm_share_one_array_sampler(self, frag):
        samplers = _active_samplers(frag, 4, cube_array=False)
        assert samplers.get('shadowArray') == 'sampler2DArrayShadow'
        assert samplers.get('shadowArrayRaw') == 'sampler2DArray'

    def test_fallback_declares_one_cube_per_slot(self):
        samplers = _active_samplers('vrml97_lighting.frag', 4, cube_array=False)
        cubes = sorted(n for n in samplers if n.startswith('shadowCube_'))
        assert cubes == ['shadowCube_0', 'shadowCube_1', 'shadowCube_2', 'shadowCube_3']
        assert 'shadowCubeArray' not in samplers

    def test_fallback_cube_count_follows_max_shadow_lights(self):
        samplers = _active_samplers('vrml97_lighting.frag', 2, cube_array=False)
        cubes = sorted(n for n in samplers if n.startswith('shadowCube_'))
        assert cubes == ['shadowCube_0', 'shadowCube_1']

    def test_cube_array_path_uses_single_sampler(self):
        samplers = _active_samplers('vrml97_lighting.frag', 4, cube_array=True)
        assert samplers.get('shadowCubeArray') == 'samplerCubeArrayShadow'
        assert not [n for n in samplers if n.startswith('shadowCube_')]

    def test_cube_array_injects_extension_and_define(self):
        src = shaderpass.load_fragment_source('vrml97_lighting.frag', 4, cube_array=True)
        assert '#extension GL_ARB_texture_cube_map_array : require' in src
        assert '#define SHADOW_CUBE_ARRAY' in src

    def test_max_shadow_lights_define_injected_after_version(self):
        src = shaderpass.load_fragment_source('vrml97_lighting.frag', 3, cube_array=False)
        lines = src.split('\n')
        vi = next(i for i, l in enumerate(lines) if l.lstrip().startswith('#version'))
        head = '\n'.join(lines[vi:vi + 6])
        assert '#define MAX_SHADOW_LIGHTS 3' in head
        assert '#define SHADOW_CUBE_ARRAY' not in src
        assert '#extension GL_ARB_texture_cube_map_array' not in src

    @pytest.mark.parametrize('n', [1, 2, 3, 4])
    @pytest.mark.parametrize('cube_array', [True, False])
    def test_worst_case_unit_budget_within_16(self, n, cube_array):
        samplers = _active_samplers('vrml97_lighting.frag', n, cube_array)
        # Every active shadow sampler maps to exactly one texture unit.
        shadow = [k for k in samplers if 'shadow' in k.lower()]
        assert len(shadow) == (3 if cube_array else 2 + n)
        assert _shadow_units(samplers, n, cube_array) <= 16

    def test_shadow_include_marker_expanded(self):
        src = shaderpass.load_fragment_source('vrml97_lighting.frag', 4, cube_array=False)
        assert shaderpass.SHADOW_INCLUDE_MARKER not in src
        assert 'void resolveShadows' in src


class TestPCFBounding:
    """3.24: PCF taps follow the filter radius (hard shadows do a cheap 3x3, not a
    fixed 5x5), and the spot + CSM paths share one radius function."""

    def _inc(self):
        with open(shaderpass.SHADOW_INCLUDE_PATH) as f:
            return f.read()

    def _fn_body(self, src, signature):
        body = src[src.index(signature):]
        return body[:body.index('\n}')]

    def test_pcf_loop_bound_is_dynamic_not_fixed_5x5(self):
        body = self._fn_body(self._inc(), 'float pcfArray(')
        # the tap loop must be bounded by the computed radius, not a literal -2..2
        assert 'x <= r' in body and 'y <= r' in body
        assert 'x <= 2' not in body and '/ 25.0' not in body
        assert 'clamp(ceil(radiusTexels' in body   # r derived from the radius

    def test_csm_reuses_pcf_array_no_inline_loop(self):
        body = self._fn_body(self._inc(), 'float csmFactor(')
        assert 'pcfArray(' in body              # unified onto the shared function
        assert 'for (int x' not in body         # no longer inlines its own 25-tap loop

    def test_spot_path_uses_pcf_array(self):
        body = self._fn_body(self._inc(), 'float spotFactor(')
        assert 'pcfArray(' in body


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
