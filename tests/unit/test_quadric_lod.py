"""Distance-LOD for quadric geometry (Sphere/Cone/Cylinder).

Level 0 reproduces the pre-LOD tessellation; coarser levels use a larger angular
step (fewer slices) and are cached separately per level. No GL context.
"""
import types

import numpy as np
import pytest
from vrml.cache import Cache

from OpenGLContext.scenegraph import quadrics
from OpenGLContext.scenegraph.quadrics import Sphere, Cone, Cylinder, lod_phi


PI = np.pi


class TestLodPhi:
    def test_coarser_levels_have_fewer_or_equal_slices(self):
        steps = [round(PI / lod_phi(PI / 12, l, PI)) for l in range(4)]
        assert steps == sorted(steps, reverse=True)
        assert steps[0] > steps[-1]                   # genuinely coarsens

    def test_never_below_the_round_floor(self):
        # coarsest level must stay a recognizable round solid (no tetrahedron)
        for l in range(4):
            assert round(PI / lod_phi(PI / 12, l, PI)) >= quadrics.LOD_MIN_STEPS


class TestClosure:
    """The LOD tessellation must close -- no missing pole cap or seam wedge. The
    exact guarantee is that phi divides its angular period into whole steps, so
    ``arange(0, period, phi)`` lands on the period. This is the precise guard the
    render-based gap test can't give for the cone/cylinder seam (their far wall
    backfills it on screen)."""

    def test_phi_divides_period_evenly(self):
        for period in (PI, 2 * PI):
            for lvl in range(4):
                n = period / lod_phi(PI / 12, lvl, period)
                assert abs(n - round(n)) < 1e-9, (period, lvl, n)

    def test_sphere_latitude_reaches_the_pole(self):
        for lvl in range(4):
            phi = lod_phi(Sphere(radius=1.0).phi, lvl, PI)
            lat = np.arange(0, PI + 3e-6, phi)
            assert np.isclose(lat[-1], PI)            # south pole included

    def test_cone_ring_reaches_2pi(self):
        for lvl in range(4):
            phi = lod_phi(Cone._BASE_PHI, lvl, 2 * PI)
            lon = np.arange(0, 2 * PI + 3e-6, phi)
            assert np.isclose(lon[-1], 2 * PI)        # ring closes

    def test_sphere_mesh_spans_both_poles(self):
        # the built mesh must reach y=+-radius; a missing cap would fall short
        for lvl in range(4):
            coords, _ = Sphere(radius=1.0).compileArrays(lvl)
            assert np.isclose(coords[:, 1].min(), -1.0, atol=1e-4)
            assert np.isclose(coords[:, 1].max(), 1.0, atol=1e-4)


class TestSphereLevels:
    def test_vertex_count_non_increasing_with_level(self):
        s = Sphere(radius=1.0)
        counts = [len(s.compileArrays(l)[1]) for l in range(4)]
        assert counts == sorted(counts, reverse=True)
        assert counts[0] > counts[-1]                 # far sphere is genuinely coarser

    def test_level0_matches_base_tessellation(self):
        s = Sphere(radius=1.0)
        base = s.sphere(s.phi)                         # pre-LOD call
        c0, i0 = s.compileArrays(0)
        assert len(i0) == len(base[1])

    def test_bounding_radius_tracks_radius(self):
        assert Sphere(radius=3.0)._lod_bounding_radius() == 3.0


class TestConeCylinderRadius:
    def test_cone_radius_is_max_extent(self):
        assert Cone(bottomRadius=2.0, height=10.0)._lod_bounding_radius() == 5.0
        assert Cone(bottomRadius=4.0, height=2.0)._lod_bounding_radius() == 4.0

    def test_cylinder_radius_is_max_extent(self):
        assert Cylinder(radius=1.0, height=8.0)._lod_bounding_radius() == 4.0


class TestPerLevelCaching:
    def _mode(self, dz):
        m = np.eye(4); m[3, 2] = dz
        return types.SimpleNamespace(cache=Cache(), matrix=m)

    def test_distance_selects_level_and_caches(self, monkeypatch):
        calls = []

        def fake_compile(self, mode=None, level=0, key=''):
            calls.append(level)
            vbos = ('coords', 'indices', level)
            mode.cache.holder(self, vbos, key=key)
            return vbos

        monkeypatch.setattr(Sphere, 'compile', fake_compile)
        s = Sphere(radius=1.0)

        near = self._mode(-3.0)                        # ~3 radii -> level 0
        assert s._lod_vbos(near)[2] == 0
        s._lod_vbos(near)                              # cached: no recompile
        assert calls == [0]

        far = self._mode(-500.0)                       # coarsest level
        lvl = s._lod_vbos(far)[2]
        assert lvl == quadrics.tessellationlod.COARSEST_LEVEL
        assert calls == [0, lvl]                       # a second, distinct level built

    def test_lod_off_forces_level0(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_LOD', 'off')
        seen = []
        monkeypatch.setattr(Sphere, 'compile',
                            lambda self, mode=None, level=0, key='': seen.append(level) or ('c', 'i', level))
        s = Sphere(radius=1.0)
        s._lod_vbos(self._mode(-500.0))                # far, but LOD disabled
        assert seen == [0]


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
