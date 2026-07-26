"""Headless tests for the FlatPass effects mixin logic that needs no GL.

Transmissive-record selection, the cluster-cull env gate, the per-object and
cluster-accelerated frustum visibility filters (driven with a REAL frustum and
real axis-aligned bounding volumes), and the once-resolved transmission mode.
"""
import numpy as np

from OpenGLContext.passes.flateffects import _FlatEffectsMixin
from OpenGLContext.frustum import Frustum
from OpenGLContext.scenegraph.boundingvolume import AABoundingBox


def make_frustum():
    """A frustum from a simple perspective * lookdown-Z view (eye at +Z)."""
    # Perspective projection (fov 60, aspect 1, near 0.1, far 100), row-major.
    f = 1.0 / np.tan(np.radians(30.0))
    n, fa = 0.1, 100.0
    proj = np.array([
        [f, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (fa + n) / (n - fa), -1],
        [0, 0, (2 * fa * n) / (n - fa), 0],
    ], 'f')
    # Model-view: translate the world -10 along z so the camera looks at origin.
    model = np.identity(4, 'f')
    model[3][2] = -10.0
    return Frustum.fromViewingMatrix(np.dot(model, proj), normalize=1)


def bbox(size=(1.0, 1.0, 1.0)):
    return AABoundingBox(center=(0, 0, 0), size=size)


def transform(tx=0.0, ty=0.0, tz=0.0, scale=1.0):
    m = np.identity(4, 'f') * 1.0
    m[0][0] = m[1][1] = m[2][2] = scale
    m[3][3] = 1.0
    m[3][0], m[3][1], m[3][2] = tx, ty, tz
    return m


def record(tx=0.0, ty=0.0, tz=0.0, bv=None, key0=False, material=None,
           scale=1.0):
    tm = transform(tx, ty, tz, scale)
    shape = type('S', (), {})()
    shape.appearance = type('A', (), {'material': material})()
    path = [shape]
    return ((key0, [], 0.0), tm, tm, bv, path)


def pass_with_frustum():
    p = _FlatEffectsMixin()
    p.frustum = make_frustum()
    return p


class Material:
    def __init__(self, transmission=0.0):
        self.transmission = transmission


class TestTransmissiveRecords:
    def test_selects_only_transmissive_opaque_records(self):
        p = _FlatEffectsMixin()
        records = [
            record(material=Material(0.0)),        # opaque, no transmission
            record(material=Material(0.7)),        # transmissive -> index 1
            record(material=None),                 # no material
            record(material=Material(0.5), key0=True),  # already routed to blend
        ]
        assert p.transmissiveRecords(records) == {1}

    def test_empty_when_nothing_transmissive(self):
        p = _FlatEffectsMixin()
        assert p.transmissiveRecords([record(material=Material(0.0))]) == set()


class TestClusterCullGate:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_INSTANCE_CLUSTER_CULL', raising=False)
        assert _FlatEffectsMixin()._cluster_cull_enabled() is False

    def test_enabled_by_env(self, monkeypatch):
        for val in ('1', 'true', 'YES', 'on'):
            monkeypatch.setenv('OPENGLCONTEXT_INSTANCE_CLUSTER_CULL', val)
            assert _FlatEffectsMixin()._cluster_cull_enabled() is True


class TestFrustumVisibilityFilter:
    def test_keeps_in_view_and_drops_far_offscreen(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_INSTANCE_CLUSTER_CULL', raising=False)
        p = pass_with_frustum()
        inside = record(tx=0.0, bv=bbox())
        # Far to the side and behind the far plane -> outside the frustum.
        outside = record(tx=0.0, ty=0.0, tz=500.0, bv=bbox())
        kept = p.frustumVisibilityFilter([inside, outside])
        # Records hold numpy arrays, so compare by identity (``x in kept`` would
        # do element-wise array equality and raise on the truth-value ambiguity).
        assert any(r is inside for r in kept)
        assert not any(r is outside for r in kept)

    def test_record_without_bounding_volume_is_always_kept(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_INSTANCE_CLUSTER_CULL', raising=False)
        p = pass_with_frustum()
        forced = record(tz=500.0, bv=None)      # would be culled if it had a bv
        assert forced in p.frustumVisibilityFilter([forced])

    def test_cluster_path_matches_per_object_result(self, monkeypatch):
        # With cluster cull ON and >= CLUSTER_CULL_MIN records, the result must
        # equal the plain per-object filter.
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCE_CLUSTER_CULL', '1')
        p = pass_with_frustum()
        rng = np.random.RandomState(0)
        records = []
        for _ in range(_FlatEffectsMixin.CLUSTER_CULL_MIN + 40):
            # Mix near (in view) and far (out of view) instances.
            far = rng.rand() < 0.5
            tz = 800.0 if far else 0.0
            tx = float(rng.uniform(-2, 2))
            records.append(record(tx=tx, tz=tz, bv=bbox()))
        clustered = p.frustumVisibilityFilter(records)

        p2 = pass_with_frustum()      # same frustum, cluster path forced off
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCE_CLUSTER_CULL', '')
        per_object = p2.frustumVisibilityFilter(records)
        assert clustered == per_object
        # It actually culled something (the far half) and kept something.
        assert 0 < len(clustered) < len(records)

    def test_cluster_filter_all_forced_returns_all(self):
        p = pass_with_frustum()
        records = [record(bv=None) for _ in range(5)]
        assert p._clusterFrustumFilter(records) == records

    def test_cluster_fallback_on_error_uses_per_object(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCE_CLUSTER_CULL', '1')
        p = pass_with_frustum()
        records = [record(tx=0.0, bv=bbox())
                   for _ in range(_FlatEffectsMixin.CLUSTER_CULL_MIN)]

        def boom(_records):
            raise RuntimeError("cluster failure")
        p._clusterFrustumFilter = boom
        # Falls back to the per-object path without raising; in-view kept.
        kept = p.frustumVisibilityFilter(records)
        assert len(kept) == len(records)


class TestTransmissionMode:
    def test_off_when_program_lacks_transmission(self):
        p = _FlatEffectsMixin()
        p.shader_program = type('P', (), {})()   # no set_transmission
        p._gl_renderer = 'whatever'
        assert p.transmissionMode() == 'off'
        assert p._transmission_mode == 'off'

    def test_resolves_and_caches_from_renderer(self):
        from OpenGLContext.passes import transmission
        p = _FlatEffectsMixin()
        p.shader_program = type('P', (), {'set_transmission': lambda *a: None})()
        p._gl_renderer = 'NVIDIA GeForce RTX'
        mode = p.transmissionMode()
        assert mode == transmission.resolve_mode('NVIDIA GeForce RTX')
        # Cached: a second call returns the stored value without re-resolving.
        p.shader_program = None
        assert p.transmissionMode() == mode


class TestBloomWrapDefensive:
    """The bloom-wrap begin/end guard + failure branches (no GL needed)."""

    def test_begin_bloom_disabled_returns_false(self, monkeypatch):
        from OpenGLContext.passes import bloom
        monkeypatch.setattr(bloom, 'bloom_enabled', lambda source=None: False)
        p = _FlatEffectsMixin()
        p.viewport = (0, 0, 64, 64)
        assert p._begin_bloom() is False
        assert p._bloom_active is False

    def test_begin_bloom_zero_viewport_returns_false(self, monkeypatch):
        from OpenGLContext.passes import bloom
        monkeypatch.setattr(bloom, 'bloom_enabled', lambda source=None: True)
        p = _FlatEffectsMixin()
        p.viewport = (0, 0, 0, 0)
        assert p._begin_bloom() is False
        assert p._bloom_active is False

    def test_begin_bloom_swallows_setup_failure(self, monkeypatch):
        from OpenGLContext.passes import bloom

        class _BoomPass:
            def begin(self, w, h):
                raise RuntimeError("simulated bloom setup failure")

        monkeypatch.setattr(bloom, 'bloom_enabled', lambda source=None: True)
        monkeypatch.setattr(bloom, 'BloomPass', _BoomPass)
        p = _FlatEffectsMixin()
        p.viewport = (0, 0, 64, 64)
        p._bloom_pass = None
        assert p._begin_bloom() is False
        assert p._bloom_active is False

    def test_end_bloom_swallows_composite_failure(self):
        class _BoomPass:
            def composite(self):
                raise RuntimeError("simulated composite failure")

        p = _FlatEffectsMixin()
        p._bloom_pass = _BoomPass()
        p._bloom_active = True
        p._end_bloom()                # must not raise
        assert p._bloom_active is False
