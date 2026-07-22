"""Distance-LOD for NURBS surfaces.

The shared distance metric drives a coarser GLU sampling step for far surfaces;
level 0 keeps the node's own sampling so close-up appearance is unchanged. GL-free.
"""
import types

import numpy as np
import pytest

from OpenGLContext.scenegraph import nurbs


_KNOT = [0, 0, 0, 0, 1, 1, 1, 1]


def _surface(scale=1.0):
    cps = [[x * scale, y * scale, 0] for y in range(4) for x in range(4)]
    return nurbs.NurbsSurface(
        controlPoint=cps, uDimension=4, vDimension=4, uKnot=_KNOT, vKnot=_KNOT)


def _mode(dz):
    m = np.eye(4); m[3, 2] = dz
    return types.SimpleNamespace(matrix=m)


class TestLodSteps:
    def test_level0_keeps_node_sampling(self):
        assert nurbs.nurbs_lod_steps(0) is None      # None -> use the node's sampling

    def test_coarser_levels_fewer_steps(self):
        steps = [nurbs.nurbs_lod_steps(l) for l in range(1, 4)]
        assert steps == sorted(steps, reverse=True)
        assert all(s is not None for s in steps)

    def test_clamps_past_last(self):
        assert nurbs.nurbs_lod_steps(99) == nurbs.nurbs_lod_steps(3)


class TestControlPointSphere:
    def test_center_and_radius_from_extents(self):
        center, radius = _surface()._lod_bounding_sphere()
        assert np.allclose(center, (1.5, 1.5, 0.0))
        assert radius > 0

    def test_none_without_surface_on_trimmed(self):
        t = nurbs.TrimmedSurface()          # no inner surface
        assert t._lod_bounding_sphere() is None


class TestLodLevel:
    def test_near_is_finest(self):
        assert _surface()._lod_level(_mode(-2.0)) == 0

    def test_far_is_coarser(self):
        s = _surface()
        assert s._lod_level(_mode(-300.0)) > s._lod_level(_mode(-2.0))

    def test_scale_invariant(self):
        # a small and a large surface at proportional distances get the same level
        small = _surface(scale=1.0)._lod_level(_mode(-40.0))
        big = _surface(scale=10.0)._lod_level(_mode(-400.0))
        assert small == big

    def test_lod_off_forces_level0(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_LOD', 'off')
        assert _surface()._lod_level(_mode(-300.0)) == 0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
