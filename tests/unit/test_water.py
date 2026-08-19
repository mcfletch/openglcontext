"""The surface of a lake, and what it is made of.

A waterline that clamps the ground flat and paints it blue is a blue-grey floor:
it has no shoreline, because the shore is the line where the *ground* passes
through the water and a clamped ground has no such line, and it reflects
nothing. Water as its own surface fixes both -- the terrain dips under it and
the shore emerges from the geometry.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.water import (
    WATER_ROUGHNESS,
    water_material,
    water_surface,
)


def _basin(x, z):
    """Ground that dips below zero in the middle and rises past it outside."""
    x = np.asarray(x, dtype='d')
    z = np.asarray(z, dtype='d')
    return (x * x + z * z) / 400.0 - 25.0


class TestWhatWaterIsMadeOf:
    def test_it_is_smooth(self):
        """Which is what makes it reflect: a rough surface scatters."""
        assert water_material().roughness < 0.2

    def test_and_that_is_the_documented_roughness(self):
        assert water_material().roughness == pytest.approx(WATER_ROUGHNESS)

    def test_it_is_not_a_metal(self):
        assert water_material().metallic == pytest.approx(0.0)

    def test_you_can_see_into_it(self):
        assert water_material().transparency > 0.0

    def test_and_it_is_drawn_as_a_transparent_thing(self):
        assert water_material().alphaMode == 'BLEND'

    def test_it_bends_light_the_way_water_does(self):
        """1.33, which is water's own refractive index."""
        assert water_material().ior == pytest.approx(1.33, abs=0.02)

    def test_it_is_seen_from_underneath_as_well(self):
        """A car that has gone in is looking up at it."""
        assert water_material().doubleSided

    def test_it_is_a_dark_colour_rather_than_a_bright_one(self):
        """Water is dark and gets its brightness from what it reflects."""
        assert max(water_material().baseColor) < 0.35


class TestTheSurface:
    def _sheet(self, **named):
        return water_surface(-100.0, 100.0, -100.0, 100.0, level=0.0, **named)

    def test_it_produces_a_mesh(self):
        mesh = self._sheet()
        assert len(mesh.positions) and len(mesh.indices)

    def test_it_is_a_well_formed_indexed_triangle_mesh(self):
        mesh = self._sheet()
        assert len(mesh.indices) % 3 == 0
        assert int(mesh.indices.max()) < len(mesh.positions)
        assert len(mesh.normals) == len(mesh.positions)

    def test_it_lies_flat_at_the_waterline(self):
        mesh = water_surface(-50.0, 50.0, -50.0, 50.0, level=12.5)
        assert mesh.positions[:, 1] == pytest.approx(12.5)

    def test_it_covers_the_footprint_it_was_given(self):
        mesh = water_surface(-30.0, 70.0, -10.0, 90.0, level=0.0)
        assert (float(mesh.positions[:, 0].min()),
                float(mesh.positions[:, 0].max())) == pytest.approx((-30.0, 70.0))
        assert (float(mesh.positions[:, 2].min()),
                float(mesh.positions[:, 2].max())) == pytest.approx((-10.0, 90.0))

    def test_a_finer_sheet_has_more_of_it(self):
        assert len(self._sheet(resolution=9).positions) > \
            len(self._sheet(resolution=3).positions)

    def test_every_normal_points_broadly_upward(self):
        """It is a flat sheet: the ripple breaks the highlight, not the plane."""
        assert self._sheet(resolution=17).normals[:, 1].min() > 0.9

    def test_the_normals_are_not_all_the_same(self):
        """A perfectly flat mirror reads as glass; water has a moving surface,
        and a broken highlight is what says so in a still picture."""
        normals = self._sheet(resolution=17).normals
        assert float(np.ptp(normals[:, 0])) > 0.01

    def test_a_still_sheet_is_a_perfect_plane(self):
        normals = self._sheet(resolution=17, ripple=0.0).normals
        assert float(np.ptp(normals[:, 0])) == pytest.approx(0.0, abs=1e-6)

    def test_the_ripple_is_the_same_every_time_it_is_built(self):
        """A world baked twice is the same world."""
        assert self._sheet(resolution=9).normals == \
            pytest.approx(self._sheet(resolution=9).normals)

    def test_and_it_lines_up_between_two_sheets_that_meet(self):
        """The ripple is a function of where a point is in the world, so two
        tiles side by side agree along their seam rather than creasing."""
        left = water_surface(-100.0, 0.0, -50.0, 50.0, level=0.0, resolution=5)
        right = water_surface(0.0, 100.0, -50.0, 50.0, level=0.0, resolution=5)
        seam_left = left.normals[np.isclose(left.positions[:, 0], 0.0)]
        seam_right = right.normals[np.isclose(right.positions[:, 0], 0.0)]
        assert sorted(map(tuple, np.round(seam_left, 5))) == \
            sorted(map(tuple, np.round(seam_right, 5)))

    def test_it_is_made_of_the_water_material_unless_told_otherwise(self):
        assert self._sheet().material.roughness == pytest.approx(WATER_ROUGHNESS)

    def test_a_caller_may_give_it_its_own(self):
        from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
        mine = PBRMaterial(baseColor=(1.0, 0.0, 0.0))
        assert self._sheet(material=mine).material is mine


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
