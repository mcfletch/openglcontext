"""Unit tests for the shadow-pass frame-to-frame caching (R1/R2/R3).

These exercise the camera-independent caster-data cache (R1), the per-light depth
map reuse (R2), and the once-per-light occluder cull (R3) without a GL context, by
driving the mixin methods with controlled fake records/lights.
"""
import types

import numpy as np
import pytest

from OpenGLContext.passes.shadowmixin import ShadowMapMixin
from OpenGLContext.passes.shadowcaps import ShadowCapabilities
from OpenGLContext.passes import shadowmath
from OpenGLContext.scenegraph.light import SpotLight, PointLight, DirectionalLight


CAPS = ShadowCapabilities.from_features(set(), (3, 3))


class FakeVolume:
    def __init__(self, points):
        self._points = np.asarray(points, dtype='f')

    def getPoints(self):
        return self._points


def _unit_box(scale=1.0):
    return [(x, y, z, 1) for x in (-scale, scale)
            for y in (-scale, scale) for z in (-scale, scale)]


def _record(tmatrix, volume):
    return (None, None, np.asarray(tmatrix, dtype='d'), volume, None)


class TestCasterDataCache:
    """R1: _worldPointsFromRecords / _casterWorldAABBCorners are camera-independent
    and must be reused across frames while no caster has moved, then recomputed
    when a caster's transform (or bounding volume) changes."""

    def _mixin(self, records):
        m = ShadowMapMixin()
        m._shadowCasterRecords = lambda: list(records)
        self.calls = {'points': 0, 'aabb': 0}
        real_points = m._worldPointsFromRecords
        real_aabb = m._casterWorldAABBCorners

        def points(recs):
            self.calls['points'] += 1
            return real_points(recs)

        def aabb(recs):
            self.calls['aabb'] += 1
            return real_aabb(recs)

        m._worldPointsFromRecords = points
        m._casterWorldAABBCorners = aabb
        return m

    def test_static_scene_computes_world_geometry_once(self):
        recs = [_record(np.eye(4), FakeVolume(_unit_box()))]
        m = self._mixin(recs)
        m._refreshCasterData()
        m._refreshCasterData()
        m._refreshCasterData()
        assert self.calls['points'] == 1
        assert self.calls['aabb'] == 1

    def test_cached_values_are_exposed(self):
        recs = [_record(np.eye(4), FakeVolume(_unit_box()))]
        m = self._mixin(recs)
        m._refreshCasterData()
        assert m._caster_points is not None and m._caster_points.shape[1] == 3
        assert m._caster_aabb is not None and m._caster_aabb.shape[1:] == (8, 3)

    def test_moving_a_caster_recomputes(self):
        vol = FakeVolume(_unit_box())
        rec = _record(np.eye(4), vol)
        records = [rec]
        m = self._mixin(records)
        m._refreshCasterData()
        # Simulate a transform change: a fresh matrix object (as the dependency
        # cache would hand back after a rotation field changed).
        moved = np.eye(4)
        moved[3, 0] = 5.0
        records[0] = _record(moved, vol)
        m._refreshCasterData()
        assert self.calls['points'] == 2
        assert self.calls['aabb'] == 2

    def test_adding_a_caster_recomputes(self):
        vol = FakeVolume(_unit_box())
        records = [_record(np.eye(4), vol)]
        m = self._mixin(records)
        m._refreshCasterData()
        records.append(_record(np.eye(4), FakeVolume(_unit_box(2.0))))
        m._refreshCasterData()
        assert self.calls['points'] == 2

    def test_cached_points_match_fresh_computation(self):
        recs = [_record(np.eye(4), FakeVolume(_unit_box())),
                _record(np.eye(4), FakeVolume(_unit_box(3.0)))]
        m = self._mixin(recs)
        m._refreshCasterData()
        cached = m._caster_points
        fresh = ShadowMapMixin._worldPointsFromRecords(recs)
        assert np.allclose(np.sort(cached, axis=0), np.sort(fresh, axis=0))


class _FakeDirPath(list):
    def __init__(self, tmatrix):
        super().__init__([DirectionalLight(direction=(0, -1, 0))])
        self._t = np.asarray(tmatrix, dtype='d')

    def transformMatrix(self):
        return self._t


class TestDirectionalCullsOncePerLight:
    """R3: a directional light's occluder cull runs once per light, not once per
    cascade. The shared occluder set is rendered into every cascade layer."""

    def _mixin(self, cascades=3):
        m = ShadowMapMixin()
        m.shader_program = types.SimpleNamespace(MAX_CASCADES=4, MAX_SHADOW_LIGHTS=4)
        m.shadow_resolution = 512
        m._effectiveCascades = lambda: cascades
        m._array_layers = lambda: 4
        m._toRender_cache = [_record(np.eye(4), FakeVolume(_unit_box()))]
        m._caster_aabb = ShadowMapMixin._casterWorldAABBCorners(m._toRender_cache)
        self.cull_calls = 0
        self.depth_calls = 0
        self.cull_frusta = []

        def cull(tr, view, proj):
            self.cull_calls += 1
            self.cull_frusta.append((np.asarray(view), np.asarray(proj)))
            return list(tr)

        def depth(occ, view, proj, grouping=None):
            self.depth_calls += 1

        m._cullOccluders = cull
        m._renderDepth = depth
        m._shared_map = lambda: types.SimpleNamespace(
            bind_layer=lambda *a: True, unbind=lambda: None)
        return m

    def _render(self, m):
        camera_view = shadowmath.look_at_matrix((0, 3, 12), (0, -0.2, -1))
        camera_proj = shadowmath.perspective_matrix(np.pi / 3, 4 / 3, 0.5, 60.0)
        return m._renderDirectional(
            _FakeDirPath(np.eye(4)), DirectionalLight(direction=(0, -1, 0)),
            0, 0, camera_view, camera_proj,
            occluder_points=np.array([[0, 0, 0], [2, 0, 2], [-2, 0, -2]], dtype='d'))

    def test_cull_runs_once_regardless_of_cascade_count(self):
        m = self._mixin(cascades=3)
        binding = self._render(m)
        assert binding is not None
        assert self.cull_calls == 1                 # not 3
        assert self.depth_calls == 3                # still one depth pass per cascade

    def test_single_cascade_still_one_cull(self):
        m = self._mixin(cascades=1)
        self._render(m)
        assert self.cull_calls == 1
        assert self.depth_calls == 1


class TestDirectionalGroupsOncePerLight:
    """R4: the instance-group partition depends only on the caster set, so a
    directional light builds it once and every cascade reuses it, instead of
    rebuilding it inside each cascade's depth pass."""

    def _mixin(self, cascades=3):
        m = ShadowMapMixin()
        m.shader_program = types.SimpleNamespace(MAX_CASCADES=4, MAX_SHADOW_LIGHTS=4)
        m.shadow_resolution = 512
        m._effectiveCascades = lambda: cascades
        m._array_layers = lambda: 4
        m._toRender_cache = [_record(np.eye(4), FakeVolume(_unit_box()))]
        m._caster_aabb = ShadowMapMixin._casterWorldAABBCorners(m._toRender_cache)
        m._cullOccluders = lambda tr, v, p: list(tr)
        self.group_calls = 0
        self.groupings_seen = []

        sentinel = ([], list(m._toRender_cache))

        def grouping(records):
            self.group_calls += 1
            return sentinel

        def depth(occ, view, proj, grouping=None):
            self.groupings_seen.append(grouping)

        m._depthGrouping = grouping
        m._renderDepth = depth
        m._shared_map = lambda: types.SimpleNamespace(
            bind_layer=lambda *a: True, unbind=lambda: None)
        self.sentinel = sentinel
        return m

    def _render(self, m):
        camera_view = shadowmath.look_at_matrix((0, 3, 12), (0, -0.2, -1))
        camera_proj = shadowmath.perspective_matrix(np.pi / 3, 4 / 3, 0.5, 60.0)
        return m._renderDirectional(
            _FakeDirPath(np.eye(4)), DirectionalLight(direction=(0, -1, 0)),
            0, 0, camera_view, camera_proj,
            occluder_points=np.array([[0, 0, 0], [2, 0, 2], [-2, 0, -2]], dtype='d'))

    def test_grouping_built_once_and_shared(self):
        m = self._mixin(cascades=3)
        self._render(m)
        assert self.group_calls == 1                       # not 3
        assert len(self.groupings_seen) == 3               # one per cascade
        # every cascade drew from the same precomputed grouping
        assert all(g is self.sentinel for g in self.groupings_seen)


class TestDepthGroupingCache:
    """R5: the instance-group partition is invariant while the caster set is
    unchanged, so it is cached across frames (and reused by both directional
    lights when they share an occluder set) instead of rebuilt every frame."""

    def _mixin(self):
        m = ShadowMapMixin()
        m.instancing_enabled = True
        m.INSTANCE_MIN = 2
        m._instanceKey = lambda path: 'geo'
        m._instanceable = lambda path: True
        m._caster_sig = ('sceneA',)
        return m

    def _records(self, n=3):
        # records whose path identity is stable (what the cache keys on)
        return [(_shared_path(i)) for i in range(n)]

    def setup_method(self):
        import OpenGLContext.passes.instancing as inst
        self._real = inst.build_instance_groups
        self.calls = 0

        def counting(records, **kw):
            self.calls += 1
            return self._real(records, **kw)

        inst.build_instance_groups = counting
        self._inst = inst

    def teardown_method(self):
        self._inst.build_instance_groups = self._real

    def test_repeated_same_set_builds_once(self):
        m = self._mixin()
        recs = self._records()
        a = m._depthGrouping(recs)
        b = m._depthGrouping(recs)
        assert self.calls == 1
        assert a is b

    def test_changed_caster_signature_rebuilds(self):
        m = self._mixin()
        recs = self._records()
        m._depthGrouping(recs)
        m._caster_sig = ('sceneB',)     # a caster moved
        m._depthGrouping(recs)
        assert self.calls == 2

    def test_changed_visible_set_rebuilds(self):
        m = self._mixin()
        m._depthGrouping(self._records(3))
        m._depthGrouping(self._records(2))   # a caster left the light frustum
        assert self.calls == 2

    def test_two_lights_same_set_share_one_build(self):
        m = self._mixin()
        recs = self._records()
        # both directional lights cull to the same occluder set this frame
        m._depthGrouping(recs)
        m._depthGrouping(recs)
        assert self.calls == 1

    def test_instancing_disabled_returns_singles(self):
        m = self._mixin()
        m.instancing_enabled = False
        recs = self._records()
        groups, singles = m._depthGrouping(recs)
        assert groups == [] and singles == recs
        assert self.calls == 0


class _Shape:
    geometry = object()
    appearance = None


_SHARED_PATHS = {}


def _shared_path(i):
    """A stable (sortKey, mv, tmatrix, bvolume, path) record; path identity is
    reused per index so the cache key is stable across calls."""
    if i not in _SHARED_PATHS:
        _SHARED_PATHS[i] = [_Shape()]
    return (None, np.eye(4), np.eye(4), None, _SHARED_PATHS[i])


class TestLightSpaceModelviews:
    """R4: a group's per-instance light-space modelviews are built with one
    batched matmul, not a Python loop of per-member dots."""

    def test_matches_per_member_dot(self):
        from OpenGLContext.arrays import dot
        light_view = shadowmath.look_at_matrix((0, 8, 0), (0, -1, 0)).astype('f')
        members = [_record(np.diag([1, 1, 1, 1]).astype('f'), None),
                   _record((np.eye(4) + np.arange(16).reshape(4, 4) * 0.01).astype('f'), None),
                   _record(shadowmath.look_at_matrix((1, 2, 3), (0, 0, -1)).astype('f'), None)]
        out = ShadowMapMixin._lightSpaceModelviews(members, light_view)
        assert out.shape == (3, 4, 4)
        for i, rec in enumerate(members):
            expected = dot(rec[2], light_view).astype('f')
            assert np.allclose(out[i], expected, atol=1e-5)


class _StableSpotPath(list):
    """A path whose transformMatrix() returns the SAME object until explicitly
    moved -- mirroring the real dependency-cached transform."""

    def __init__(self, tmatrix):
        super().__init__([SpotLight(location=(0, 5, 0), direction=(0, -1, 0),
                                    cutOffAngle=0.5)])
        self._t = np.asarray(tmatrix, dtype='f')

    def transformMatrix(self):
        return self._t

    def move(self, tmatrix):
        self._t = np.asarray(tmatrix, dtype='f')


class TestSpotMapReuse:
    """R2: a spot light's depth map is camera-independent. When neither the light
    nor any caster has moved, the previous frame's depth map is reused and the
    depth pass (bind_layer + _renderDepth) is skipped entirely -- but a binding is
    still returned each frame (its matrix folds in the moving camera)."""

    def _mixin(self):
        m = ShadowMapMixin()
        m.shader_program = types.SimpleNamespace(MAX_CASCADES=4, MAX_SHADOW_LIGHTS=4)
        m.shadow_resolution = 512
        m._toRender_cache = [_record(np.eye(4), FakeVolume(_unit_box()))]
        m._caster_points = np.array([[0, 0, 0], [2, 2, 2], [-2, -2, -2]], dtype='d')
        m._caster_sig = ('sceneA',)
        m._lightInView = lambda pos, node: True
        m._array_layers = lambda: 4
        m._cullOccluders = lambda tr, v, p: list(tr)
        self.binds = 0
        self.depths = 0

        def bind_layer(*a):
            self.binds += 1
            return True

        def render_depth(occ, v, p):
            self.depths += 1

        m._renderDepth = render_depth
        m._shared_map = lambda: types.SimpleNamespace(
            texture=7, bind_layer=bind_layer, unbind=lambda: None)
        return m

    def test_first_frame_renders(self):
        m = self._mixin()
        path = _StableSpotPath(np.eye(4))
        b = m._renderSpot(path, path[0], 0, 0, np.eye(4))
        assert b is not None
        assert self.depths == 1 and self.binds == 1

    def test_static_scene_reuses_map(self):
        m = self._mixin()
        path = _StableSpotPath(np.eye(4))
        for _ in range(5):
            b = m._renderSpot(path, path[0], 0, 0, np.eye(4))
            assert b is not None            # binding returned every frame
        assert self.depths == 1             # depth pass ran only once
        assert self.binds == 1

    def test_moving_light_rerenders(self):
        m = self._mixin()
        path = _StableSpotPath(np.eye(4))
        m._renderSpot(path, path[0], 0, 0, np.eye(4))
        moved = np.eye(4); moved[3, 0] = 3.0
        path.move(moved)
        m._renderSpot(path, path[0], 0, 0, np.eye(4))
        assert self.depths == 2

    def test_moving_a_caster_rerenders(self):
        m = self._mixin()
        path = _StableSpotPath(np.eye(4))
        m._renderSpot(path, path[0], 0, 0, np.eye(4))
        m._caster_sig = ('sceneB',)         # a caster moved this frame
        m._renderSpot(path, path[0], 0, 0, np.eye(4))
        assert self.depths == 2

    def test_reallocated_texture_rerenders(self):
        m = self._mixin()
        path = _StableSpotPath(np.eye(4))
        m._renderSpot(path, path[0], 0, 0, np.eye(4))
        # Simulate the depth array being reallocated (new GL texture id).
        m._shared_map = lambda: types.SimpleNamespace(
            texture=99, bind_layer=lambda *a: (setattr(self, 'binds', self.binds+1) or True),
            unbind=lambda: None)
        m._renderSpot(path, path[0], 0, 0, np.eye(4))
        assert self.depths == 2


class _StablePointPath(list):
    def __init__(self, tmatrix):
        super().__init__([PointLight(location=(0, 5, 0), attenuation=(1, 0, 0),
                                     intensity=1.0)])
        self._t = np.asarray(tmatrix, dtype='f')

    def transformMatrix(self):
        return self._t


class TestPointMapReuse:
    """R2 for point lights: the whole cube map is camera-independent, so an
    unchanged light + caster set reuses every face."""

    def _mixin(self):
        m = ShadowMapMixin()
        m.frustum = None
        m.shader_program = types.SimpleNamespace(
            shadow_cube_array=False, MAX_CASCADES=4, MAX_SHADOW_LIGHTS=4)
        m.shadow_cube_resolution = 256
        m._toRender_cache = [_record(np.eye(4), FakeVolume(_unit_box()))]
        m._caster_points = np.array([[0, 0, 0], [1, 1, 1]], dtype='d')
        m._caster_sig = ('sceneA',)
        m._lightInView = lambda pos, node: True
        m._cullOccluders = lambda tr, v, p: list(tr)
        self.faces = 0
        self.depths = 0

        def bind_face(face, size=None):
            self.faces += 1
            return True

        m._renderDepth = lambda occ, v, p: setattr(self, 'depths', self.depths + 1)
        m._map_cube = lambda slot: types.SimpleNamespace(
            texture=5, bind_face=bind_face, unbind=lambda: None)
        return m

    def test_static_scene_reuses_cube(self):
        m = self._mixin()
        path = _StablePointPath(np.eye(4))
        for _ in range(4):
            b = m._renderPoint(path, path[0], 0, 0, np.eye(4), CAPS)
            assert b is not None
        assert self.faces == 6      # bound once, on the first frame only
        assert self.depths == 6


class TestSpotSlotOwnership:
    """Finding 2: the depth-map cache is keyed by the physical layer, not the
    light. A light that leaves the view frees its slot to another light; when it
    returns and reclaims that layer it must re-render, not sample the depth the
    other light wrote there."""

    def _mixin(self):
        m = ShadowMapMixin()
        m.shader_program = types.SimpleNamespace(MAX_CASCADES=4, MAX_SHADOW_LIGHTS=4)
        m.shadow_resolution = 512
        m._toRender_cache = [_record(np.eye(4), FakeVolume(_unit_box()))]
        m._caster_points = np.array([[0, 0, 0], [2, 2, 2], [-2, -2, -2]], dtype='d')
        m._caster_sig = ('sceneA',)
        m._lightInView = lambda pos, node: True
        m._array_layers = lambda: 4
        m._cullOccluders = lambda tr, v, p: list(tr)
        self.depths = 0
        m._renderDepth = lambda occ, v, p: setattr(self, 'depths', self.depths + 1)
        m._shared_map = lambda: types.SimpleNamespace(
            texture=7, bind_layer=lambda *a: True, unbind=lambda: None)
        return m

    def test_returning_light_reclaiming_layer_rerenders(self):
        m = self._mixin()
        a = _StableSpotPath(np.eye(4))
        b = _StableSpotPath(np.eye(4))
        m._renderSpot(a, a[0], 0, 0, np.eye(4))    # A -> slot0/layer0
        assert self.depths == 1
        m._renderSpot(b, b[0], 0, 1, np.eye(4))    # B reclaims slot0/layer0 (A left view)
        assert self.depths == 2
        m._renderSpot(a, a[0], 0, 0, np.eye(4))    # A returns to slot0/layer0
        assert self.depths == 3                    # must re-render, not reuse B's depth


class TestDepthCacheCommit:
    """Finding 3: a slot is recorded as rendered only AFTER the depth pass
    succeeds, so a failed bind/render does not leave the slot marked fresh and
    skipped forever."""

    def _mixin(self, bind_ok):
        m = ShadowMapMixin()
        m.shader_program = types.SimpleNamespace(MAX_CASCADES=4, MAX_SHADOW_LIGHTS=4)
        m.shadow_resolution = 512
        m._toRender_cache = [_record(np.eye(4), FakeVolume(_unit_box()))]
        m._caster_points = np.array([[0, 0, 0], [2, 2, 2]], dtype='d')
        m._caster_sig = ('sceneA',)
        m._lightInView = lambda pos, node: True
        m._array_layers = lambda: 4
        m._cullOccluders = lambda tr, v, p: list(tr)
        self.depths = 0
        m._renderDepth = lambda occ, v, p: setattr(self, 'depths', self.depths + 1)
        m._shared_map = lambda: types.SimpleNamespace(
            texture=7, bind_layer=lambda *a: bind_ok[0], unbind=lambda: None)
        return m

    def test_failed_bind_does_not_mark_fresh(self):
        bind_ok = [False]
        m = self._mixin(bind_ok)
        path = _StableSpotPath(np.eye(4))
        b = m._renderSpot(path, path[0], 0, 0, np.eye(4))
        assert b is None                    # bind failed, light skipped this frame
        assert self.depths == 0
        bind_ok[0] = True                   # allocation succeeds next frame
        b = m._renderSpot(path, path[0], 0, 0, np.eye(4))
        assert b is not None
        assert self.depths == 1             # re-attempted, not wrongly skipped


def _real_transform_shape_path():
    """A REAL scenegraph node path: Transform -> Shape(Box), plus the Transform.

    Returns ``(transform, path)`` where ``path.transformMatrix()`` and
    ``path[-1].boundingVolume(mode)`` are backed by the vrml dependency cache --
    the identity contract _casterSignature relies on. Skips the test cleanly if a
    scenegraph can't be constructed in this environment (import/build failure).
    """
    try:
        from vrml.vrml97 import nodepath
        from OpenGLContext.scenegraph import basenodes
    except Exception as err:                                    # pragma: no cover
        pytest.skip("scenegraph unavailable: %s" % (err,))
    try:
        shape = basenodes.Shape(geometry=basenodes.Box(size=(2, 2, 2)))
        transform = basenodes.Transform(translation=(0, 0, 0), children=[shape])
        path = nodepath.NodePath([transform, shape])
    except Exception as err:                                    # pragma: no cover
        pytest.skip("could not build scenegraph headless: %s" % (err,))
    return transform, path


class TestCasterSignatureIdentityContract:
    """S2: the caster signature is keyed on ``id()`` of the dependency-cached
    ``transformMatrix()`` / ``boundingVolume()`` objects. The other cache tests
    fake that contract with hand-built stubs; this one drives a REAL scenegraph
    node so a regression in the actual dependency cache (a matrix reused in place,
    or a fresh wrapper per call) would be caught.

    The signature MUST stay stable across reads while nothing moves, and MUST
    change when the Transform's translation/rotation field is mutated -- otherwise
    the R1/R2/R5 shadow caches either freeze on stale geometry or never reuse.
    """

    def _mixin_with_path(self, path):
        from vrml.vrml97 import nodetypes
        m = ShadowMapMixin()
        # _shadowCasterRecords reads self.paths[Rendering]; hand it the real path
        # so _casterSignature runs on real transformMatrix()/boundingVolume() ids.
        m.paths = {nodetypes.Rendering: [path]}
        return m

    def test_real_node_signature_is_stable_while_unmoved(self):
        transform, path = _real_transform_shape_path()
        m = self._mixin_with_path(path)
        sig1 = ShadowMapMixin._casterSignature(m._shadowCasterRecords())
        sig2 = ShadowMapMixin._casterSignature(m._shadowCasterRecords())
        assert sig1 == sig2                 # same cached objects -> same ids
        assert len(sig1) == 1               # one caster in the pool

    def test_real_node_translation_change_moves_signature(self):
        transform, path = _real_transform_shape_path()
        m = self._mixin_with_path(path)
        # Hold the pre-move records: the signature keys on id() of their cached
        # matrix/volume objects, so those objects must stay alive or a freed
        # address could be reused by the post-move matrix and alias the old id.
        before_recs = m._shadowCasterRecords()
        before = ShadowMapMixin._casterSignature(before_recs)
        transform.translation = (5.0, 0.0, 0.0)
        after = ShadowMapMixin._casterSignature(m._shadowCasterRecords())
        assert after != before              # fresh transformMatrix object -> new id
        assert before_recs                  # keep alive until after the compare

    def test_real_node_rotation_change_moves_signature(self):
        transform, path = _real_transform_shape_path()
        m = self._mixin_with_path(path)
        before_recs = m._shadowCasterRecords()
        before = ShadowMapMixin._casterSignature(before_recs)
        transform.rotation = (0.0, 1.0, 0.0, 1.0)
        after = ShadowMapMixin._casterSignature(m._shadowCasterRecords())
        assert after != before
        assert before_recs                  # keep alive until after the compare

    def test_refresh_reuses_then_recomputes_on_real_move(self):
        """Drive the full R1 path (_refreshCasterData) on the real node: a static
        node recomputes world geometry once, a moved node recomputes again."""
        transform, path = _real_transform_shape_path()
        m = self._mixin_with_path(path)
        calls = {'n': 0}
        real_points = m._worldPointsFromRecords

        def counting(recs):
            calls['n'] += 1
            return real_points(recs)

        m._worldPointsFromRecords = counting
        m._refreshCasterData()
        m._refreshCasterData()
        assert calls['n'] == 1              # unmoved -> world geometry cached
        transform.translation = (3.0, 0.0, 0.0)
        m._refreshCasterData()
        assert calls['n'] == 2              # moved -> recomputed


class TestFarCascadeCullCompleteness:
    """S4: R3 culls the caster pool ONCE against an ortho fitted to the UNION of
    every cascade's receiver corners, then draws the survivors into each cascade
    layer. The claim (asserted in _renderDirectional, never tested) is that this
    union-cull is a superset of every per-cascade frustum, so a caster that
    shadows ONLY the far cascade still survives the single cull.

    This builds near/far cascade corner sets where a caster lies OUTSIDE the near
    cascade's frustum but INSIDE the far one, runs the same union-cull path the
    mixin uses (``shadowmath.directional_cascade`` over the concatenated corners +
    ``_cullOccluders``), and asserts the far-only caster is retained.
    """

    LIGHT_DIR = (0.0, -1.0, 0.0)

    def _cascade_corners(self):
        """Near + far cascade receiver corners from a real camera split, the way
        _renderDirectional derives them (frustum_corners_world over depth slices)."""
        camera_view = shadowmath.look_at_matrix((0, 3, 0), (0, -0.15, -1))
        camera_proj = shadowmath.perspective_matrix(np.pi / 3, 4 / 3, 0.5, 120.0)
        near, far = 0.5, 120.0
        splits = shadowmath.cascade_splits(near, far, 3)

        def depth01(dist):
            clip = np.array([0, 0, -dist, 1.0]) @ np.asarray(camera_proj, dtype='d')
            return float(np.clip(0.5 * (clip[2] / clip[3]) + 0.5, 0.0, 1.0))

        near_corners = shadowmath.frustum_corners_world(
            camera_view, camera_proj, depth01(near), depth01(splits[0]))
        far_corners = shadowmath.frustum_corners_world(
            camera_view, camera_proj, depth01(splits[1]), depth01(splits[2]))
        return near_corners, far_corners

    @staticmethod
    def _ground_caster(corners, label):
        """An AABoundingBox caster centred on the ground under a corner set."""
        from OpenGLContext.scenegraph.boundingvolume import AABoundingBox
        c = corners.mean(axis=0)
        bv = AABoundingBox(center=(float(c[0]), 0.0, float(c[2])), size=(2, 2, 2))
        return (None, None, np.eye(4), bv, label)

    def _labels(self, records):
        return {r[4] for r in records}

    def test_far_only_caster_survives_union_cull(self):
        near_corners, far_corners = self._cascade_corners()
        # A control caster in the near cascade keeps _cullOccluders' non-empty
        # result honest: with a single record, its "fall back to full list if
        # nothing survives" would mask a genuine exclusion.
        control = self._ground_caster(near_corners, 'near_control')
        far_caster = self._ground_caster(far_corners, 'far_only')
        records = [control, far_caster]
        m = ShadowMapMixin()

        # Per-cascade near cull: the far caster is genuinely outside it (the
        # control survives, so this is a real cull, not the empty-set fallback).
        near_view, near_proj = shadowmath.directional_cascade(
            self.LIGHT_DIR, near_corners, texel_snap=0)
        near_survivors = self._labels(m._cullOccluders(records, near_view, near_proj))
        assert 'near_control' in near_survivors
        assert 'far_only' not in near_survivors     # only shadows the far cascade

        # Single union cull over the concatenated corners, exactly as R3 does.
        union_view, union_proj = shadowmath.directional_cascade(
            self.LIGHT_DIR, np.concatenate([near_corners, far_corners], axis=0),
            texel_snap=0)
        union_survivors = self._labels(
            m._cullOccluders(records, union_view, union_proj))
        # The far-only caster survives the union cull -> it is drawn into the
        # depth pass and can still shadow the far cascade.
        assert 'far_only' in union_survivors
        assert 'near_control' in union_survivors     # union is a superset of near
