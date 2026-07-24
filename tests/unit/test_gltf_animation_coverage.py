"""Coverage tests for glTF animation edge paths.

Sampler construction/evaluation corner cases, cubic-spline single-key and rotation
normalization, the KHR_animation_pointer setter resolver (node-visibility, material
factors, emissive strength, texture transform), the JSON-pointer walker's
list/attr/None results, and the ``_build_animations`` channel-skip guards. All pure
Python/numpy -- reads go through a fake resolver exposing a decoded-buffer cache.
"""
import types

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")
from pygltflib import GLTF2, Node, Accessor, BufferView, Buffer  # noqa: E402

from OpenGLContext.loaders.gltf import animation as ga  # noqa: E402


class _R:
    def __init__(self, data):
        self._buffers = {0: data}


class TestQuatSlerpParallel:
    def test_near_parallel_uses_normalized_lerp(self):
        q0 = np.array([0.0, 0.0, 0.0, 1.0])
        q1 = np.array([0.0, 0.0, 0.001, 0.9999995])
        out = ga.quat_slerp(q0, q1, 0.5)
        assert abs(np.linalg.norm(out) - 1.0) < 1e-9


class TestSamplerConstruction:
    def test_one_dimensional_values_reshaped_to_column(self):
        s = ga.Sampler(times=np.array([0.0, 1.0]), values=np.array([3.0, 7.0]))
        assert s.values.shape == (2, 1)

    def test_unknown_interpolation_falls_back_to_linear(self):
        s = ga.Sampler(times=np.array([0.0, 1.0]),
                       values=np.array([[0.0], [1.0]]), interpolation='NOPE')
        assert s.interpolation == 'LINEAR'

    def test_empty_sampler_evaluates_to_zero_vector(self):
        s = ga.Sampler(times=np.array([]), values=np.zeros((0, 3)))
        assert np.allclose(s.evaluate(0.5), [0, 0, 0])


class TestCubicSplineHelpers:
    def test_key_accessor_uses_value_row_for_cubic_layout(self):
        keys = np.array([[0.], [5.], [0.], [0.], [9.], [0.]])
        s = ga.Sampler(times=np.array([0.0, 1.0]), values=keys,
                       interpolation='CUBICSPLINE')
        assert s._key(0)[0] == 5.0 and s._key(1)[0] == 9.0

    def test_single_key_cubic_returns_its_value(self):
        keys = np.array([[0.], [7.], [0.]])
        s = ga.Sampler(times=np.array([2.0]), values=keys,
                       interpolation='CUBICSPLINE')
        assert s.evaluate(2.0)[0] == 7.0
        assert s.evaluate(-3.0)[0] == 7.0

    def test_cubic_rotation_is_renormalized(self):
        a = np.sin(np.radians(22.5)), np.cos(np.radians(22.5))
        keys = np.array([
            [0, 0, 0, 0], [0, 0, 0, 1], [0, 0, 0, 0],
            [0, 0, 0, 0], [0, a[0], 0, a[1]], [0, 0, 0, 0]], dtype=float)
        s = ga.Sampler(times=np.array([0.0, 1.0]), values=keys,
                       interpolation='CUBICSPLINE', is_rotation=True)
        out = s.evaluate(0.5)
        assert abs(np.linalg.norm(out) - 1.0) < 1e-9


class TestComputeWorldMatricesBaked:
    def test_baked_forward_matrix_used_directly(self):
        baked = np.eye(4)
        baked[3, 0] = 2.0
        node = types.SimpleNamespace(_forward=baked)
        worlds = ga.compute_world_matrices([0], {}, {0: node})
        assert worlds[0][3, 0] == 2.0


class TestPlayerPointerException:
    def test_failing_setter_is_swallowed(self):
        s = ga.Sampler(np.array([0.0, 1.0]), np.array([[0.0], [1.0]]))

        def boom(_value):
            raise RuntimeError("setter blew up")

        anim = ga.Animation('a', [], [ga.PointerChannel(s, boom)])
        ga.Player(anim, {}).evaluate(0.0)      # must not propagate


class TestSamplerValuesValidation:
    def test_indivisible_output_raises(self):
        vals = np.array([1.0, 2.0, 3.0], dtype=np.float32)   # 3 scalars, 2 keyframes
        g = GLTF2()
        g.accessors = [Accessor(bufferView=0, componentType=5126, count=3, type='SCALAR')]
        g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=vals.nbytes)]
        g.buffers = [Buffer(byteLength=vals.nbytes)]
        samp = types.SimpleNamespace(input=0, output=0, interpolation='LINEAR')
        with pytest.raises(ValueError, match='keyframe rows'):
            ga._sampler_values(g, samp, 2, 'LINEAR', _R(vals.tobytes()))


class TestPointerSetter:
    def _g(self):
        g = GLTF2()
        g.nodes = [Node()]
        return g

    def test_node_visibility_toggles_light_intensity(self):
        light = types.SimpleNamespace(intensity=2.0)
        setter = ga._pointer_setter(
            self._g(), '/nodes/0/extensions/KHR_node_visibility/visible',
            {}, {0: light}, {})
        setter([1.0])
        assert light.intensity == 2.0
        setter([0.0])
        assert light.intensity == 0.0

    def test_node_non_visibility_pointer_is_unsupported(self):
        assert ga._pointer_setter(
            self._g(), '/nodes/0/translation', {}, {}, {}) is None

    def test_unknown_material_is_unsupported(self):
        assert ga._pointer_setter(
            self._g(), '/materials/9/pbrMetallicRoughness/metallicFactor',
            {}, {}, {}) is None

    def test_scalar_factor_setter(self):
        m = types.SimpleNamespace()
        setter = ga._pointer_setter(
            self._g(), '/materials/0/pbrMetallicRoughness/metallicFactor',
            {}, {}, {0: m})
        setter([0.3])
        assert abs(m.metallic - 0.3) < 1e-6

    def test_emissive_strength_setter(self):
        m = types.SimpleNamespace()
        setter = ga._pointer_setter(
            self._g(),
            '/materials/0/extensions/KHR_materials_emissive_strength/emissiveStrength',
            {}, {}, {0: m})
        setter([4.0])
        assert abs(m.emissiveStrength - 4.0) < 1e-6

    def test_unknown_material_property_is_unsupported(self):
        # A valid material but an unrecognised factor falls through to no setter.
        m = types.SimpleNamespace()
        assert ga._pointer_setter(
            self._g(), '/materials/0/pbrMetallicRoughness/unknownFactor',
            {}, {}, {0: m}) is None

    def test_malformed_material_pointer_is_swallowed(self):
        # A non-integer material index raises inside and resolves to no setter.
        m = types.SimpleNamespace()
        assert ga._pointer_setter(
            self._g(), '/materials/notanindex/metallicFactor',
            {}, {}, {0: m}) is None

    def test_texture_transform_offset_rotation_scale(self):
        for comp, value, check in (
            ('offset', [0.5, 0.25], lambda m: m._uv_params['offset'] == [0.5, 0.25]),
            ('rotation', [1.2], lambda m: abs(m._uv_params['rotation'] - 1.2) < 1e-6),
            ('scale', [2.0, 3.0], lambda m: m._uv_params['scale'] == [2.0, 3.0]),
        ):
            m = types.SimpleNamespace()
            ptr = '/materials/0/extensions/KHR_texture_transform/%s' % comp
            setter = ga._pointer_setter(self._g(), ptr, {}, {}, {0: m})
            setter(value)
            assert check(m)
            assert m.uv_transform is not None


class TestResolveJsonPointer:
    def test_list_container_result(self):
        g = GLTF2()
        g.nodes = [Node()]
        parent, last, kind = ga._resolve_json_pointer(g, ['nodes', '0'])
        assert kind == 'list' and last == '0' and parent is g.nodes

    def test_attribute_container_result(self):
        g = GLTF2()
        parent, last, kind = ga._resolve_json_pointer(g, ['scene'])
        assert kind == 'attr' and last == 'scene' and parent is g

    def test_none_midway_returns_none(self):
        g = GLTF2()
        g.nodes = [Node()]        # node has no mesh
        assert ga._resolve_json_pointer(g, ['nodes', '0', 'mesh', 'x']) is None


class TestReadInverseBind:
    def test_absent_matrices_default_to_identity_stack(self):
        sd = types.SimpleNamespace(inverseBindMatrices=None)
        out = ga._read_inverse_bind(GLTF2(), sd, 3, None)
        assert out.shape == (3, 4, 4)
        assert np.allclose(out[0], np.eye(4))


class TestRegisterSkinGuards:
    def test_out_of_range_skin_index_skipped(self):
        node = types.SimpleNamespace(skin=5)
        g = types.SimpleNamespace(skins=[object()])
        skins = []
        ga._register_skin(node, 0, [], g, None, skins)
        assert skins == []

    def test_no_skinned_meshes_skipped(self):
        node = types.SimpleNamespace(skin=0)
        sd = types.SimpleNamespace(joints=[0], inverseBindMatrices=None)
        g = types.SimpleNamespace(skins=[sd])
        shape = types.SimpleNamespace(geometry=types.SimpleNamespace(skin_joints=None))
        skins = []
        ga._register_skin(node, 0, [(shape, None)], g, None, skins)
        assert skins == []


class TestBuildAnimationsGuards:
    def test_malformed_channels_are_all_skipped(self, caplog):
        times = np.array([0.0, 1.0], dtype=np.float32)
        vals = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32)
        data = times.tobytes() + vals.tobytes()
        g = GLTF2()
        g.accessors = [
            Accessor(bufferView=0, componentType=5126, count=2, type='SCALAR'),
            Accessor(bufferView=1, componentType=5126, count=2, type='VEC3'),
        ]
        g.bufferViews = [
            BufferView(buffer=0, byteOffset=0, byteLength=times.nbytes),
            BufferView(buffer=0, byteOffset=times.nbytes, byteLength=vals.nbytes),
        ]
        g.buffers = [Buffer(byteLength=len(data))]
        good = types.SimpleNamespace(input=0, output=1, interpolation='LINEAR')
        broken = types.SimpleNamespace(input=99, output=1, interpolation='LINEAR')
        ns = types.SimpleNamespace
        g.animations = [ns(name='a', samplers=[good, broken], channels=[
            ns(target=None, sampler=0),                                   # no target
            ns(target=ns(node=0, path='translation'), sampler=99),        # bad sampler
            ns(target=ns(node=0, path='weird'), sampler=0),               # bad path
            ns(target=ns(node=None, path='translation'), sampler=0),      # no node
            ns(target=ns(node=0, path='translation'), sampler=1),         # read error
        ])]
        with caplog.at_level('WARNING'):
            out = ga._build_animations(g, _R(data))
        assert out == []          # every channel skipped -> no Animation emitted
        assert any('skipping animation channel' in r.getMessage()
                   for r in caplog.records)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
