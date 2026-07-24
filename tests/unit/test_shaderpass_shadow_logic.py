"""Headless tests for the per-slot shadow uniform binding (_ShadowUniformMixin).

The GL-touching helpers (_set_uniform*, _set_cascade_matrix, _bind_shadow_texture)
are stubbed to record their calls, so the pure per-light orchestration -- the
guard returns, the spot/CSM/point slot routing, the cube-array vs per-slot sampler
layout -- is exercised without a context. The end-to-end binding against a real
compiled program runs in test_passes_render_gl's shadowed scenes.
"""
from OpenGLContext.passes.shaderpass_shadow import _ShadowUniformMixin


class FakeProgram(_ShadowUniformMixin):
    def __init__(self, program=1, shadow_program=None, cube_array=False):
        self.program = program
        self._shadow_program = shadow_program
        self.vertex_color_program = None
        self._shadow_samplers_program = set()
        self.shadow_cube_array = cube_array
        self.MAX_SHADOW_LIGHTS = 4
        self.MAX_CASCADES = 4
        self.calls = []

    def _set_uniform1i(self, name, value, program):
        self.calls.append(('1i', name, value))

    def _set_uniform1f(self, name, value, program):
        self.calls.append(('1f', name, value))

    def _set_uniform3f(self, name, value, program):
        self.calls.append(('3f', name, value))

    def _set_cascade_matrix(self, slot, cascade, matrix):
        self.calls.append(('cascade', slot, cascade))

    def _bind_shadow_texture(self, unit, target, texture_id):
        self.calls.append(('bindtex', unit, texture_id))

    def _pcss_sampler_object(self):
        return 0


def _names(prog):
    return [c[1] for c in prog.calls if c[0] in ('1i', '1f', '3f')]


class TestSamplerLayout:
    def test_per_slot_cube_samplers_without_cube_array(self):
        p = FakeProgram(cube_array=False)
        p.init_shadow_samplers()
        names = _names(p)
        # one sampler per slot at the cube base, not a single array sampler
        assert 'shadowCubeArray' not in names
        assert 'shadowCube_0' in names and 'shadowCube_3' in names

    def test_single_array_sampler_with_cube_array(self):
        p = FakeProgram(cube_array=True)
        p.init_shadow_samplers()
        names = _names(p)
        assert 'shadowCubeArray' in names
        assert 'shadowCube_0' not in names

    def test_init_is_skipped_when_already_done(self):
        p = FakeProgram(cube_array=True)
        p.init_shadow_samplers()
        n = len(p.calls)
        p.init_shadow_samplers()          # same program already registered
        assert len(p.calls) == n


class TestGuardReturns:
    def test_bind_shadow_array_no_program_is_noop(self):
        p = FakeProgram(program=None, shadow_program=None)
        p.bind_shadow_array(7)
        assert p.calls == []

    def test_bind_shadow_array_no_texture_is_noop(self):
        p = FakeProgram()
        p.bind_shadow_array(0)            # falsy texture id
        assert p.calls == []

    def test_bind_cube_array_without_cube_array_is_noop(self):
        p = FakeProgram(cube_array=False)
        p.bind_cube_array(9)             # cube-array path disabled
        assert p.calls == []

    def test_bind_csm_slot_out_of_range_is_noop(self):
        p = FakeProgram()
        p.bind_csm_slot(99, 0, [], [])   # slot >= MAX_SHADOW_LIGHTS
        assert p.calls == []

    def test_bind_spot_slot_out_of_range_is_noop(self):
        p = FakeProgram()
        p.bind_spot_slot(99, 0, object())
        assert p.calls == []

    def test_bind_cube_slot_out_of_range_is_noop(self):
        p = FakeProgram()
        p.bind_cube_slot(99, 0, 5, (0, 0, 0), 0.1, 10.0)
        assert p.calls == []


class TestSlotBinding:
    def test_spot_slot_sets_index_kind_and_matrix(self):
        p = FakeProgram()
        p.bind_spot_slot(1, 2, object())
        names = _names(p)
        assert 'shadowLightIndex[1]' in names
        assert 'shadowKind[1]' in names
        assert ('cascade', 1, 0) in p.calls

    def test_csm_slot_binds_each_cascade_and_split(self):
        p = FakeProgram()
        mats = [object(), object()]
        p.bind_csm_slot(0, 3, mats, [0.2, 0.8])
        names = _names(p)
        assert 'cascadeCount[0]' in names
        assert ('cascade', 0, 0) in p.calls and ('cascade', 0, 1) in p.calls
        assert 'cascadeSplit[0]' in names and 'cascadeSplit[1]' in names

    def test_cube_slot_fallback_binds_per_slot_cube_texture(self):
        p = FakeProgram(cube_array=False)
        p.bind_cube_slot(2, 1, 42, (1.0, 2.0, 3.0), 0.1, 50.0)
        # fallback path binds the per-slot cube texture at SHADOW_CUBE_BASE + slot
        assert ('bindtex', p.SHADOW_CUBE_BASE + 2, 42) in p.calls
        names = _names(p)
        assert 'cubeLightPos[2]' in names
        assert 'cubeNear[2]' in names and 'cubeFar[2]' in names

    def test_cube_slot_with_cube_array_skips_per_slot_bind(self):
        p = FakeProgram(cube_array=True)
        p.bind_cube_slot(2, 1, 42, (1.0, 2.0, 3.0), 0.1, 50.0)
        # the shared cube-array is bound elsewhere; no per-slot texture bind here
        assert not any(c[0] == 'bindtex' for c in p.calls)
        assert 'cubeLightPos[2]' in _names(p)


if __name__ == '__main__':
    import sys
    import pytest
    sys.exit(pytest.main([__file__, '-v']))
