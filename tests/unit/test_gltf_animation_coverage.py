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
from pygltflib import GLTF2, Node, Accessor, BufferView, Buffer

from OpenGLContext.loaders.gltf import animation as ga


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
    def test_a_failing_setter_costs_only_its_own_property(self):
        s = ga.Sampler(np.array([0.0, 1.0]), np.array([[0.0], [1.0]]))
        written = []

        def boom(_value):
            raise RuntimeError("setter blew up")

        anim = ga.Animation('a', [], [ga.PointerChannel(s, boom),
                                      ga.PointerChannel(s, written.append)])
        ga.Player(anim, {}).evaluate(0.5)
        assert len(written) == 1
        assert np.allclose(written[0], [0.5])

    def test_it_is_reported_once_and_then_left_undriven(self, caplog):
        s = ga.Sampler(np.array([0.0, 1.0]), np.array([[0.0], [1.0]]))
        calls = []

        def boom(_value):
            calls.append(_value)
            raise RuntimeError("setter blew up")

        anim = ga.Animation('a', [], [
            ga.PointerChannel(s, boom, '/materials/0/emissiveFactor')])
        player = ga.Player(anim, {})
        with caplog.at_level('ERROR', logger=ga.__name__):
            for t in (0.25, 0.5, 0.75):
                player.evaluate(t)
        assert len(calls) == 1
        [record] = caplog.records
        assert '/materials/0/emissiveFactor' in record.getMessage()
        assert record.exc_info is not None


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

    def _targets(self, **named):
        return ga.PointerTargets(self._g(), **named)

    def test_node_visibility_sets_the_transforms_visible(self):
        transform = types.SimpleNamespace(visible=True)
        setter = self._targets(node_transforms={0: transform}).setter(
            '/nodes/0/extensions/KHR_node_visibility/visible')
        setter([0.0])
        assert transform.visible is False
        setter([1.0])
        assert transform.visible is True

    def test_a_node_with_no_transform_is_unsupported(self):
        assert self._targets().setter('/nodes/0/translation') is None

    def test_unknown_material_is_unsupported(self):
        assert self._targets().setter(
            '/materials/9/pbrMetallicRoughness/metallicFactor') is None

    def test_scalar_factor_setter(self):
        m = types.SimpleNamespace(metallic=1.0)
        setter = self._targets(appearances={0: types.SimpleNamespace(material=m)}).setter(
            '/materials/0/pbrMetallicRoughness/metallicFactor')
        setter([0.3])
        assert abs(m.metallic - 0.3) < 1e-6

    def test_emissive_strength_setter(self):
        m = types.SimpleNamespace(emissiveStrength=1.0)
        setter = self._targets(appearances={0: types.SimpleNamespace(material=m)}).setter(
            '/materials/0/extensions/KHR_materials_emissive_strength/emissiveStrength')
        setter([4.0])
        assert abs(m.emissiveStrength - 4.0) < 1e-6

    def test_unknown_material_property_is_unsupported(self):
        # A valid material but an unrecognised factor falls through to no setter.
        m = types.SimpleNamespace()
        assert self._targets(appearances={0: types.SimpleNamespace(material=m)}).setter(
            '/materials/0/pbrMetallicRoughness/unknownFactor') is None

    def test_malformed_material_pointer_is_swallowed(self):
        # A non-integer material index resolves to no setter.
        m = types.SimpleNamespace()
        assert self._targets(appearances={0: types.SimpleNamespace(material=m)}).setter(
            '/materials/notanindex/metallicFactor') is None

    def _transformed(self):
        """An appearance whose base colour map is moved by a matrix transform."""
        from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
        from OpenGLContext.loaders.gltf.materials import khr_transform_matrix  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.appearance import Appearance  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.imagedata import ImageDataTexture  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial  # noqa: PLC0415 kept with its use
        transform = x3d.TextureTransformMatrix3D(
            mapping='TEXCOORD_0:0', matrix=khr_transform_matrix(scale=(2.0, 2.0)))
        material = PhysicalMaterial(baseTexture=ImageDataTexture(),
                                    baseTextureMapping='TEXCOORD_0:0')
        appearance = Appearance(material=material, textureTransform=x3d.MultiTextureTransform(
            textureTransform=[transform]))
        return appearance, transform

    def test_texture_transform_offset_rotation_scale(self):
        from OpenGLContext.loaders.gltf.materials import khr_transform_params  # noqa: PLC0415 kept with its use
        for comp, value, check in (
            ('offset', [0.5, 0.25], lambda p: p['offset'] == pytest.approx([0.5, 0.25])
             and p['scale'] == pytest.approx([2.0, 2.0])),
            ('rotation', [1.2], lambda p: p['rotation'] == pytest.approx(1.2)
             and p['scale'] == pytest.approx([2.0, 2.0])),
            ('scale', [2.0, 3.0], lambda p: p['scale'] == pytest.approx([2.0, 3.0])),
        ):
            appearance, transform = self._transformed()
            ptr = ('/materials/0/pbrMetallicRoughness/baseColorTexture/extensions/'
                   'KHR_texture_transform/%s' % comp)
            setter = self._targets(appearances={0: appearance}).setter(ptr)
            setter(value)
            assert check(khr_transform_params(transform.matrix)), comp

    def test_a_texture_without_a_transform_cannot_be_animated(self):
        appearance, _transform = self._transformed()
        ptr = '/materials/0/normalTexture/extensions/KHR_texture_transform/offset'
        assert self._targets(appearances={0: appearance}).setter(ptr) is None


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
