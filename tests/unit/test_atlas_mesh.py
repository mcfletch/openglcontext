"""Several pictures in one image, and several pieces of geometry in one mesh.

The point of both is the draw call. A world's warning signs say seven different
things and its start line is chequered in two colours; drawn as seven materials
and a paint job that is what the GPU is asked to switch between. Packed into one
picture and concatenated into one mesh, they are one draw.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.atlasmesh import (
    cell_centre,
    flat_patch,
    merged_mesh,
    pack_cells,
    srgb_bytes,
    textured_mesh,
)
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


def _material():
    return PBRMaterial(baseColor=(1.0, 1.0, 1.0))


def _quad(material, offset=0.0, uv=(0.0, 0.0)):
    points = np.array([(offset, 0.0, 0.0), (offset + 1.0, 0.0, 0.0),
                       (offset, 1.0, 0.0)], dtype='d')
    return textured_mesh(points, np.array([0, 1, 2], dtype=np.uint32),
                         material, np.tile(np.asarray(uv, 'f'), (3, 1)))


class TestPackingPictures:
    def test_every_patch_gets_a_corner(self) -> None:
        image, boxes = pack_cells({'a': flat_patch((1.0, 0.0, 0.0), 8),
                                   'b': flat_patch((0.0, 1.0, 0.0), 8)}, 8)
        assert set(boxes) == {'a', 'b'}
        assert image.size == (16, 8)

    def test_the_corners_do_not_overlap(self) -> None:
        _image, boxes = pack_cells(
            {name: flat_patch((0.5, 0.5, 0.5), 8) for name in 'abcd'}, 8)
        seen = set()
        for box in boxes.values():
            assert box not in seen
            seen.add(box)
        assert len(seen) == 4

    def test_a_box_is_the_fraction_of_the_image_it_covers(self) -> None:
        _image, boxes = pack_cells(
            {name: flat_patch((0.5, 0.5, 0.5), 8) for name in 'abcd'}, 8)
        assert boxes['a'] == (0.0, 0.0, 0.5, 0.5)
        assert boxes['d'] == (0.5, 0.5, 1.0, 1.0)

    def test_the_same_patches_pack_the_same_way(self) -> None:
        """A world re-bakes to itself, so the layout cannot wander."""
        first = pack_cells({'x': flat_patch((0.2, 0.2, 0.2), 8),
                            'y': flat_patch((0.8, 0.8, 0.8), 8)}, 8)[1]
        second = pack_cells({'x': flat_patch((0.2, 0.2, 0.2), 8),
                             'y': flat_patch((0.8, 0.8, 0.8), 8)}, 8)[1]
        assert first == second

    def test_it_takes_nothing_to_pack_nothing(self) -> None:
        image, boxes = pack_cells({}, 8)
        assert boxes == {}
        assert image.size == (8, 8)

    def test_the_centre_of_a_cell_is_inside_it(self) -> None:
        assert cell_centre((0.0, 0.25, 0.5, 0.75)) == (0.25, 0.5)


class TestColour:
    def test_black_stays_black_and_white_stays_white(self) -> None:
        assert srgb_bytes((0.0, 0.0, 0.0)) == (0, 0, 0, 255)
        assert srgb_bytes((1.0, 1.0, 1.0)) == (255, 255, 255, 255)

    def test_a_mid_albedo_encodes_brighter_than_it_is(self) -> None:
        """sRGB is not linear: half the light is well over half the byte."""
        red, _green, _blue, _alpha = srgb_bytes((0.5, 0.5, 0.5))
        assert 180 < red < 200

    def test_a_patch_is_that_colour_throughout(self) -> None:
        patch = flat_patch((0.25, 0.5, 0.75), 4)
        assert patch.size == (4, 4)
        assert patch.getpixel((0, 0)) == patch.getpixel((3, 3))
        assert patch.getpixel((0, 0)) == srgb_bytes((0.25, 0.5, 0.75))


class TestMergingGeometry:
    def test_the_points_of_both_are_in_it(self) -> None:
        material = _material()
        merged = merged_mesh([_quad(material), _quad(material, offset=5.0)],
                             material)
        assert len(merged.positions) == 6
        assert float(np.max(np.asarray(merged.positions)[:, 0])) == 6.0

    def test_the_second_mesh_keeps_its_own_triangles(self) -> None:
        """Indices are relative to each mesh, so the join has to renumber."""
        material = _material()
        merged = merged_mesh([_quad(material), _quad(material, offset=5.0)],
                             material)
        assert list(np.asarray(merged.indices)) == [0, 1, 2, 3, 4, 5]

    def test_each_keeps_the_corner_of_the_atlas_it_reads(self) -> None:
        material = _material()
        merged = merged_mesh([_quad(material, uv=(0.1, 0.1)),
                              _quad(material, offset=5.0, uv=(0.9, 0.9))],
                             material)
        uv = np.asarray(merged.texcoords)
        assert pytest.approx(0.1, abs=1e-6) == float(uv[0][0])
        assert pytest.approx(0.9, abs=1e-6) == float(uv[3][0])

    def test_it_wears_the_one_material(self) -> None:
        material = _material()
        merged = merged_mesh([_quad(material), _quad(material)], material)
        assert merged.material is material

    def test_merging_nothing_is_an_error_rather_than_an_empty_mesh(self) -> None:
        with pytest.raises(ValueError):
            merged_mesh([], _material())


class TestOneMesh:
    def test_it_has_normals_it_was_not_given(self) -> None:
        """Every caller here builds flat geometry, so estimating is the answer."""
        mesh = _quad(_material())
        assert len(mesh.normals) == len(mesh.positions)
        assert pytest.approx(1.0, abs=1e-5) == abs(float(mesh.normals[0][2]))

    def test_geometry_without_a_picture_carries_no_texcoords(self) -> None:
        points = np.array([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                          dtype='d')
        mesh = textured_mesh(points, np.array([0, 1, 2], dtype=np.uint32),
                             _material())
        assert mesh.texcoords is None


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
