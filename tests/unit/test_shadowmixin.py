"""Unit tests for ShadowMapMixin logic that does not require a GL context."""
import types

import numpy as np
import pytest

from OpenGLContext.passes.shadowmixin import ShadowMapMixin
from OpenGLContext.passes.shadowcaps import ShadowCapabilities
from OpenGLContext.passes import shadowmath
from OpenGLContext.scenegraph.light import SpotLight, PointLight, DirectionalLight


CAPS = ShadowCapabilities.from_features(set(), (3, 3))       # cube supported
CAPS_NO_CUBE = ShadowCapabilities.from_features(set(), (2, 1))  # no cube


class FakeVolume:
    def __init__(self, points):
        self._points = np.asarray(points, dtype='f')

    def getPoints(self):
        return self._points


def _record(tmatrix, volume):
    return (None, None, np.asarray(tmatrix, dtype='d'), volume, None)


class TestCastsShadow:
    def setup_method(self):
        self.mixin = ShadowMapMixin()

    def test_spotlight_casts(self):
        s = SpotLight(location=(0, 5, 0), direction=(0, -1, 0), cutOffAngle=0.5)
        assert self.mixin._castsShadow(s, CAPS) is True

    def test_directional_casts(self):
        d = DirectionalLight(direction=(0, -1, 0))
        assert self.mixin._castsShadow(d, CAPS) is True

    def test_point_casts_when_cube_supported(self):
        assert self.mixin._castsShadow(PointLight(), CAPS) is True

    def test_point_skipped_without_cube(self):
        assert self.mixin._castsShadow(PointLight(), CAPS_NO_CUBE) is False

    def test_castshadows_false_disables(self):
        s = SpotLight(location=(0, 5, 0), direction=(0, -1, 0), cutOffAngle=0.5)
        s.castShadows = False
        assert self.mixin._castsShadow(s, CAPS) is False


class TestOccluderPoints:
    def setup_method(self):
        self.mixin = ShadowMapMixin()

    def test_transforms_points_to_world(self):
        local = [(x, y, z, 1) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        tmat = np.eye(4)
        tmat[3, 0] = 10.0
        pts = self.mixin._occluderPoints([_record(tmat, FakeVolume(local))])
        assert pts.shape == (8, 3)
        assert np.isclose(pts[:, 0].min(), 9.0) and np.isclose(pts[:, 0].max(), 11.0)

    def test_no_volumes_returns_none(self):
        assert self.mixin._occluderPoints([_record(np.eye(4), None)]) is None


class TestWorldHelpers:
    def setup_method(self):
        self.mixin = ShadowMapMixin()

    def test_world_point_translation(self):
        tmat = np.eye(4)
        tmat[3, 1] = 5.0
        out = self.mixin._world_point((0, 0, 0), tmat)
        assert np.allclose(out, [0, 5, 0])

    def test_world_dir_rotation(self):
        tmat = np.eye(4)
        out = self.mixin._world_dir((0, -1, 0), tmat)
        assert np.allclose(out, [0, -1, 0])

    def test_world_dir_zero_returns_none(self):
        assert self.mixin._world_dir((0, 0, 0), np.zeros((4, 4))) is None


class TestDepthHelpers:
    def setup_method(self):
        self.mixin = ShadowMapMixin()

    def test_depth01_monotonic(self):
        proj = shadowmath.perspective_matrix(np.pi / 3, 1.0, 1.0, 100.0)
        near = self.mixin._depth01(proj, 2.0)
        far = self.mixin._depth01(proj, 50.0)
        assert 0.0 <= near < far <= 1.0

    def test_scene_depth_range(self):
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        # points 6..10 units in front of the camera
        occ = np.array([[0, 0, 0], [0, 0, 4], [0, 0, 2]], dtype='d')
        near, far = self.mixin._scene_depth_range(view, occ)
        assert near >= 0.1 and far > near
        assert near <= 6.0 and far >= 10.0


class FakeFrustum:
    # inward-pointing planes of the box [-10,10]^3 (distance >= 0 means inside)
    planes = np.array([
        (1, 0, 0, 10), (-1, 0, 0, 10),
        (0, 1, 0, 10), (0, -1, 0, 10),
        (0, 0, 1, 10), (0, 0, -1, 10),
    ], dtype='d')


class TestLightInView:
    def setup_method(self):
        self.mixin = ShadowMapMixin()
        self.mixin.frustum = FakeFrustum()

    def test_point_inside_frustum_kept(self):
        light = PointLight(attenuation=(0, 0, 1), intensity=1.0)  # finite range
        assert self.mixin._lightInView((0, 0, 0), light) is True

    def test_point_far_outside_culled(self):
        light = PointLight(attenuation=(0, 0, 1), intensity=1.0)
        assert self.mixin._lightInView((100, 0, 0), light) is False

    def test_directional_always_in_view(self):
        light = DirectionalLight(direction=(0, -1, 0))
        # directional has unbounded range -> never culled, even far away
        assert self.mixin._lightInView((100, 100, 100), light) is True

    def test_unbounded_point_range_not_culled(self):
        light = PointLight(attenuation=(1, 0, 0), intensity=1.0)  # constant -> unbounded
        assert self.mixin._lightInView((100, 0, 0), light) is True

    def test_no_frustum_keeps_light(self):
        m = ShadowMapMixin()
        light = PointLight(attenuation=(0, 0, 1))
        assert m._lightInView((100, 0, 0), light) is True


class TestCullOccluders:
    def setup_method(self):
        self.mixin = ShadowMapMixin()

    def test_none_bvolume_passes_through(self):
        view = shadowmath.look_at_matrix((0, 5, 0), (0, -1, 0))
        proj = shadowmath.perspective_matrix(1.0, 1.0, 0.5, 20.0)
        recs = [_record(np.eye(4), None)]
        assert self.mixin._cullOccluders(recs, view, proj) == recs

    def test_empty_input_returns_input(self):
        view = shadowmath.look_at_matrix((0, 5, 0), (0, -1, 0))
        proj = shadowmath.perspective_matrix(1.0, 1.0, 0.5, 20.0)
        assert self.mixin._cullOccluders([], view, proj) == []


class TestSpotViewProjection:
    """4.15: the spot depth pass reuses shadowmath.spot_light_view_projection
    rather than re-deriving the frustum inline."""

    def setup_method(self):
        self.mixin = ShadowMapMixin()

    def test_matches_shared_shadowmath_helper(self):
        pos = (0.0, 5.0, 0.0)
        direction = (0.0, -1.0, 0.0)
        cutoff = 0.5
        occ = np.array([[1, 0, 1], [-1, 0, -1], [0, 0, 0]], dtype='d')
        view, proj = self.mixin._spotViewProjection(pos, direction, cutoff, occ)
        # near/far derived from the same occluder set through the shared math
        v0 = shadowmath.look_at_matrix(pos, direction)
        near, far = shadowmath.near_far_from_points(v0, occ)
        exp_view, exp_proj = shadowmath.spot_light_view_projection(
            pos, direction, cutoff, near, far)
        assert np.allclose(view, exp_view, atol=1e-5)
        assert np.allclose(proj, exp_proj, atol=1e-5)


class TestSpotUsesCasterPool:
    """3d: _renderSpot fits near/far to the full caster pool (self._caster_points),
    not the camera-culled occluder set, so the shadow doesn't pop as the camera
    moves and a caster leaves/enters the camera frustum."""

    def _mixin(self):
        m = ShadowMapMixin()
        m.shader_program = types.SimpleNamespace(MAX_CASCADES=4, MAX_SHADOW_LIGHTS=4)
        m.shadow_resolution = 512
        m._toRender_cache = []
        m._lightInView = lambda pos, node: True
        m._array_layers = lambda: 4
        m._cullOccluders = lambda tr, v, p: []
        m._renderDepth = lambda occ, v, p: None
        m._shared_map = lambda: types.SimpleNamespace(
            texture=1, bind_layer=lambda *a: True, unbind=lambda: None)
        return m

    def test_spot_near_far_derived_from_caster_points(self):
        m = self._mixin()
        pool = np.array([[3, 0, 3], [-3, 0, -3], [0, -8, 0]], dtype='d')
        m._caster_points = pool
        captured = {}
        real = m._spotViewProjection

        def spy(pos, direction, cutoff, points):
            captured['points'] = points
            return real(pos, direction, cutoff, points)

        m._spotViewProjection = spy
        light = SpotLight(location=(0, 5, 0), direction=(0, -1, 0), cutOffAngle=0.5)
        binding = m._renderSpot(_FakePath(np.eye(4)), light, 0, 0, np.eye(4))
        assert binding is not None
        # The near/far fit saw the whole caster pool, not a camera-culled subset.
        assert captured['points'] is pool


class TestBiasConstants:
    """4.17: acne controls live in named module constants, not magic literals,
    and front-face culling is no longer stacked on top of the offsets (3.14)."""

    def test_bias_uses_named_constant(self):
        from OpenGLContext.passes import shadowmixin
        m = ShadowMapMixin()
        assert m._shadowBias() == shadowmixin.SHADOW_DEPTH_BIAS
        assert m._normalOffset() == shadowmixin.SHADOW_NORMAL_OFFSET

    def test_polygon_offset_constants_present(self):
        from OpenGLContext.passes import shadowmixin
        assert hasattr(shadowmixin, 'SHADOW_POLYGON_OFFSET_FACTOR')
        assert hasattr(shadowmixin, 'SHADOW_POLYGON_OFFSET_UNITS')


class TestLightDirectionConsistency:
    """4.18: the shadow light direction must transform the same way as the lit
    shader's light direction (upper-3x3 + normalize, a direction of travel), so
    a light inside a non-uniformly scaled Transform shines and shadows the same
    way. Inverse-transpose would desynchronise the two."""

    def test_matches_lighting_path_under_nonuniform_scale(self):
        import numpy as np
        # rotation about Z composed with a non-uniform scale (shear in the 3x3)
        theta = 0.6
        c, s = np.cos(theta), np.sin(theta)
        rot = np.array([[c, s, 0, 0], [-s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], 'd')
        scale = np.diag([2.0, 0.5, 3.0, 1.0])
        mv = scale @ rot                       # row-vector modelview
        local_dir = (1.0, 0.0, 0.0)

        shadow_dir = ShadowMapMixin._world_dir(local_dir, mv)
        shadow_dir = shadow_dir / np.linalg.norm(shadow_dir)

        # reproduce the lighting path's transform_direction (upper-3x3 + normalize)
        d = np.array(local_dir, dtype=np.float32) @ mv[:3, :3].astype(np.float32)
        light_dir = d / np.linalg.norm(d)
        assert np.allclose(shadow_dir, light_dir, atol=1e-5)


class TestFrustumPlanesNormalized:
    """4.19: _lightInView treats plane*point as a signed distance, which is only
    valid when the frustum planes are normalized. Lock the builder default."""

    def test_frustum_builder_normalizes_planes(self):
        from OpenGLContext import frustum as frustum_module
        proj = shadowmath.perspective_matrix(np.pi / 3, 1.0, 1.0, 100.0)
        view = shadowmath.look_at_matrix((0, 0, 10), (0, 0, -1))
        mp = (view.astype('d') @ proj.astype('d')).astype('f')
        fr = frustum_module.Frustum.fromViewingMatrix(mp)   # default normalize=1
        for plane in fr.planes:
            n = np.linalg.norm(np.asarray(plane, dtype='d')[:3])
            assert abs(n - 1.0) < 1e-4


class _FakeCubeMap:
    def __init__(self):
        self.faces_bound = []
        self.texture = 42

    def bind_face(self, face, size=None):
        self.faces_bound.append(face)
        return True

    def unbind(self):
        pass


class _FakePath(list):
    def __init__(self, tmatrix):
        super().__init__([PointLight()])
        self._t = np.asarray(tmatrix, dtype='d')

    def transformMatrix(self):
        return self._t


class TestCubeFaceClearing:
    """2.5: every cube face must be bound + cleared each frame even when it holds
    no caster, or it keeps undefined (first frame) / stale (caster left the
    frustum) depth and casts phantom shadows. Only the *draw* is skipped."""

    def _mixin(self, cull_result):
        m = ShadowMapMixin()
        m.frustum = None
        m.shader_program = types.SimpleNamespace(
            shadow_cube_array=False, MAX_CASCADES=4, MAX_SHADOW_LIGHTS=4)
        m.shadow_cube_resolution = 512
        m._toRender_cache = []
        self.smap = _FakeCubeMap()
        m._map_cube = lambda slot: self.smap
        self.draws = []
        m._renderDepth = lambda occ, v, p: self.draws.append(occ)
        m._cullOccluders = lambda tr, v, p: cull_result
        return m

    def _render(self, m):
        light = PointLight(location=(0, 5, 0), attenuation=(1, 0, 0), intensity=1.0)
        # near/far now come from the full caster pool cached on the mixin
        #, not a per-call occluder argument.
        m._caster_points = np.array([[0, 0, 0], [1, 1, 1]], dtype='d')
        return m._renderPoint(_FakePath(np.eye(4)), light, 0, 0, np.eye(4), CAPS)

    def test_all_six_faces_bound_without_occluders(self):
        m = self._mixin(cull_result=[])           # no caster in any face
        binding = self._render(m)
        assert sorted(self.smap.faces_bound) == [0, 1, 2, 3, 4, 5]  # all cleared
        assert self.draws == []                    # but nothing drawn
        assert binding is not None

    def test_all_six_faces_bound_and_drawn_with_occluders(self):
        m = self._mixin(cull_result=['occ'])       # a caster in every face
        self._render(m)
        assert sorted(self.smap.faces_bound) == [0, 1, 2, 3, 4, 5]
        assert len(self.draws) == 6                 # drawn into each cleared face


class TestEffectiveCascadesEnvOverride:
    """3.16: OPENGLCONTEXT_SHADOW_CASCADES pins the rendered cascade count,
    bypassing the nondeterministic fps probe so shadow output is reproducible."""

    def _mixin(self):
        m = ShadowMapMixin()
        m.shader_program = types.SimpleNamespace(MAX_CASCADES=4)
        return m

    def test_env_pins_exact_count(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_SHADOW_CASCADES', '2')
        assert self._mixin()._effectiveCascades() == 2

    def test_env_clamped_to_max_cascades(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_SHADOW_CASCADES', '99')
        assert self._mixin()._effectiveCascades() == 4

    def test_invalid_env_ignored_falls_back(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_SHADOW_CASCADES', 'nope')
        n = self._mixin()._effectiveCascades()      # falls through to adaptive path
        assert isinstance(n, int) and n >= 1


class TestDisposeShadowMaps:
    """3.15: disposeShadowMaps releases every allocated pool so a scenegraph swap
    / context loss doesn't leak the FBOs + depth textures."""

    class _Pool:
        def __init__(self):
            self.cleaned = 0

        def cleanup(self):
            self.cleaned += 1

    def test_all_pools_cleaned_and_nulled(self):
        m = ShadowMapMixin()
        arr, cube_arr, cube = self._Pool(), self._Pool(), self._Pool()
        m._shared_array = arr
        m._shared_cube_array = cube_arr
        m._maps_cube = {0: cube}
        m._shadow_bindings = [{'kind': 'spot'}]
        m._depth_map_cache = {123: ('key',)}
        m._depth_grouping_cache = {('sig', ()): ([], [])}
        m.disposeShadowMaps()
        assert arr.cleaned == cube_arr.cleaned == cube.cleaned == 1
        assert m._shared_array is None
        assert m._shared_cube_array is None
        assert m._maps_cube is None
        assert m._shadow_bindings is None
        assert m._depth_map_cache is None
        assert m._depth_grouping_cache is None

    def test_idempotent(self):
        m = ShadowMapMixin()
        m.disposeShadowMaps()
        m.disposeShadowMaps()   # nothing allocated -> no crash


class TestRenderShadowMapsGuards:
    """The cheap early-outs of renderShadowMaps (no GL needed to reach them)."""

    def _node(self, casts=True):
        return types.SimpleNamespace(castsShadow=casts)

    def _record(self, node):
        return (None, None, np.identity(4, 'd'), None, [node])

    def test_disabled_shadows_clears_bindings_and_returns(self):
        m = ShadowMapMixin()
        m.use_shadows = False
        m.renderShadowMaps([self._record(self._node())])
        assert m._shadow_bindings == []

    def test_empty_render_set_returns(self):
        m = ShadowMapMixin()
        m.use_shadows = True
        m.renderShadowMaps([])
        assert m._shadow_bindings == []

    def test_all_casters_opted_out_returns(self):
        m = ShadowMapMixin()
        m.use_shadows = True
        # every record's node opts out of casting -> filtered set is empty
        m.renderShadowMaps([self._record(self._node(casts=False))])
        assert m._shadow_bindings == []

    def test_no_shader_program_returns(self):
        m = ShadowMapMixin()
        m.use_shadows = True
        m.shader_program = None
        m.renderShadowMaps([self._record(self._node(casts=True))])
        assert m._shadow_bindings == []

    def test_no_compiled_program_returns(self):
        m = ShadowMapMixin()
        m.use_shadows = True
        m.shader_program = types.SimpleNamespace(program=None)
        m.renderShadowMaps([self._record(self._node(casts=True))])
        assert m._shadow_bindings == []


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
