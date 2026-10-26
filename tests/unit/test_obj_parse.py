"""The OBJ parser: statements into triangle arrays, with no scenegraph and no GL.

Each test names one statement or one rule of the format (Wavefront's
specification, in the form Paul Bourke's description of it gives) and states what
the arrays hold afterwards.
"""
from __future__ import annotations

import numpy as np
import pytest

from OpenGLContext.loaders.objfile import ObjFile, ObjMesh, parse_obj


def parse(text: str | bytes) -> ObjFile:
    return parse_obj(text.encode() if isinstance(text, str) else text, 'test.obj')


def only_mesh(model: ObjFile) -> ObjMesh:
    assert len(model.parts) == 1 and len(model.parts[0].meshes) == 1, model.parts
    return model.parts[0].meshes[0]


def triangles(mesh: ObjMesh) -> np.ndarray:
    """The mesh's triangles as an (n, 3, 3) array of corner positions."""
    return mesh.positions[mesh.indices.reshape(-1, 3)]


def all_counter_clockwise(mesh: ObjMesh) -> bool:
    """Whether every triangle of a mesh in the z = 0 plane faces +Z, as its polygon did"""
    corners = triangles(mesh)
    cross = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    return bool((cross[:, 2] > 0).all())


def area(mesh: ObjMesh) -> float:
    corners = triangles(mesh)
    cross = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    return float(np.linalg.norm(cross, axis=1).sum() / 2)


SQUARE = """\
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
"""


class TestFaces:
    def test_triangle(self) -> None:
        mesh = only_mesh(parse('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n'))
        assert mesh.kind == 'triangles'
        assert mesh.indices.dtype == np.uint32
        assert mesh.positions.dtype == np.float32
        assert triangles(mesh).shape == (1, 3, 3)
        assert area(mesh) == pytest.approx(0.5)

    def test_quad_is_two_triangles_covering_it(self) -> None:
        mesh = only_mesh(parse(SQUARE + 'f 1 2 3 4\n'))
        assert len(mesh.indices) == 6
        assert area(mesh) == pytest.approx(1.0)

    def test_concave_quad_stays_inside_its_outline(self) -> None:
        # A dart with its reflex corner second: fanned from the first corner
        # the triangles cover 0.7, outside the polygon's 0.3.
        text = 'v 0 0 0\nv 0.5 0.4 0\nv 1 0 0\nv 0.5 1 0\nf 1 2 3 4\n'
        mesh = only_mesh(parse(text))
        assert area(mesh) == pytest.approx(0.3)
        assert all_counter_clockwise(mesh)

    @pytest.mark.parametrize('outline, expected', [
        # an L: six corners, one reflex
        ([(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)], 3.0),
        # a convex pentagon
        ([(0, 0), (2, 0), (3, 1.5), (1, 3), (-1, 1.5)], 7.5),
        # a comb with three reflex corners
        ([(0, 0), (6, 0), (6, 3), (5, 3), (5, 1), (4, 1), (4, 3), (2, 3), (2, 1),
          (1, 1), (1, 3), (0, 3)], 14.0),
    ])
    def test_polygon_triangles_cover_exactly_its_area(self, outline, expected) -> None:
        text = ''.join('v %g %g 0\n' % corner for corner in outline)
        text += 'f ' + ' '.join(str(i + 1) for i in range(len(outline))) + '\n'
        mesh = only_mesh(parse(text))
        assert len(mesh.indices) == 3 * (len(outline) - 2)
        assert area(mesh) == pytest.approx(expected)
        assert all_counter_clockwise(mesh)

    def test_convex_and_concave_polygons_of_one_size_in_one_file(self) -> None:
        # Two hexagons: a regular one (area 6 * sqrt(3) / 4 * 1.5) and an L (area 3).
        hexagon = [(np.cos(a), np.sin(a)) for a in np.linspace(0, 2 * np.pi, 7)[:-1]]
        outline = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
        text = ''.join('v %.9f %.9f 0\n' % corner for corner in hexagon + outline)
        text += 'f 1 2 3 4 5 6\nf 7 8 9 10 11 12\n'
        mesh = only_mesh(parse(text))
        assert len(mesh.indices) == 3 * 8
        assert area(mesh) == pytest.approx(6 * np.sqrt(3) / 4 + 3.0, rel=1e-5)
        assert all_counter_clockwise(mesh)

    def test_polygon_in_a_tilted_plane_is_triangulated_in_that_plane(self) -> None:
        # The L from above, stood on edge and turned; the plane is not z = 0.
        outline = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
        rows = ['v %g %g %g\n' % (x, y * 0.6, y * 0.8) for x, y in outline]
        text = ''.join(rows) + 'f 1 2 3 4 5 6\n'
        assert area(only_mesh(parse(text))) == pytest.approx(3.0)

    def test_a_face_with_fewer_than_three_corners_draws_nothing(self) -> None:
        model = parse(SQUARE + 'f 1 2\nf 3\n')
        assert model.parts == []
        assert model.ignored['f (fewer than three corners)'] == 2

    @pytest.mark.parametrize('corner', ['{v}', '{v}/{t}', '{v}//{n}', '{v}/{t}/{n}'])
    def test_every_corner_form_reads(self, corner: str) -> None:
        text = SQUARE + 'vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\n'
        text += 'f ' + ' '.join(corner.format(v=i, t=i, n=1) for i in (1, 2, 3, 4)) + '\n'
        assert area(only_mesh(parse(text))) == pytest.approx(1.0)

    def test_relative_indices_count_back_from_the_last_vertex_read(self) -> None:
        text = SQUARE + 'f -4 -3 -2 -1\nv 5 5 5\nf -1 -2 -3\n'
        mesh = only_mesh(parse(text))
        assert mesh.indices.max() < len(mesh.positions)
        corners = triangles(mesh)
        # the second face is the three newest vertices: (5,5,5), (0,1,0), (1,1,0)
        assert np.allclose(corners[-1, 0], (5, 5, 5))
        assert np.allclose(corners[-1, 1], (0, 1, 0))
        assert np.allclose(corners[-1, 2], (1, 1, 0))

    def test_relative_indices_apply_to_texture_coordinates_and_normals_too(self) -> None:
        text = SQUARE + 'vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nvn 0 0 1\nvn 0 0 -1\n'
        text += 'f -4/-4/-2 -3/-3/-2 -2/-2/-2 -1/-1/-2\n'
        mesh = only_mesh(parse(text))
        assert np.allclose(mesh.normals, (0, 0, 1))
        assert np.allclose(mesh.texcoords[np.argmax(mesh.positions[:, 0] + mesh.positions[:, 1])],
                           (1, 1))

    def test_a_corner_shared_by_two_normals_becomes_two_vertices(self) -> None:
        text = ('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n'
                'vn 0 0 -1\nvn 0 -1 0\n'
                'f 1//1 2//1 3//1\nf 1//2 2//2 4//2\n')
        mesh = only_mesh(parse(text))
        assert len(mesh.positions) == 6
        assert len(mesh.normals) == 6

    def test_identical_corners_share_one_vertex(self) -> None:
        mesh = only_mesh(parse(SQUARE + 'f 1 2 3\nf 1 3 4\n'))
        assert len(mesh.positions) == 4

    def test_texture_coordinates_keep_two_components(self) -> None:
        text = SQUARE + 'vt 0 0 0\nvt 1 0 0.5\nvt 1\nvt 0 1\nf 1/1 2/2 3/3 4/4\n'
        mesh = only_mesh(parse(text))
        assert mesh.texcoords.shape[1] == 2
        assert np.allclose(sorted(map(tuple, mesh.texcoords.round(3))),
                           [(0, 0), (0, 1), (1, 0), (1, 0)])

    def test_a_vertex_weight_is_not_a_colour(self) -> None:
        text = 'v 0 0 0 1\nv 1 0 0 1\nv 0 1 0 1\nf 1 2 3\n'
        assert only_mesh(parse(text)).colors is None

    def test_numbers_in_every_spelling(self) -> None:
        text = 'v +1.5 -.5 1e-3\nv 2E2 0 0\nv 0 0 +0.\nf 1 2 3\n'
        corners = triangles(only_mesh(parse(text)))
        assert np.allclose(corners[0, 0], (1.5, -0.5, 0.001))
        assert np.allclose(corners[0, 1], (200, 0, 0))


class TestNormals:
    def test_vn_is_used_where_the_face_names_it(self) -> None:
        text = SQUARE + 'vn 0 0 -1\nf 1//1 2//1 3//1 4//1\n'
        assert np.allclose(only_mesh(parse(text)).normals, (0, 0, -1))

    def test_a_face_with_no_normal_is_flat_by_default(self) -> None:
        # Two faces meeting at 90 degrees, no `s` statement: each keeps its own.
        text = 'v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3\nf 1 4 2\n'
        mesh = only_mesh(parse(text))
        assert len(mesh.positions) == 6
        assert sorted({tuple(n) for n in mesh.normals.round(3)}) == [(0, 0, 1), (0, 1, 0)]

    def test_normals_are_unit_length_and_face_the_winding(self) -> None:
        text = SQUARE + 'f 1 2 3 4\n'
        mesh = only_mesh(parse(text))
        assert np.allclose(np.linalg.norm(mesh.normals, axis=1), 1.0)
        assert np.allclose(mesh.normals, (0, 0, 1))

    def test_a_smoothing_group_shares_normals_across_its_edge(self) -> None:
        text = ('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n'
                's 1\nf 1 2 3\nf 1 4 2\n')
        mesh = only_mesh(parse(text))
        assert len(mesh.positions) == 4
        shared = mesh.normals[np.isclose(mesh.positions[:, 0], 0)
                              & np.isclose(mesh.positions[:, 1], 0)
                              & np.isclose(mesh.positions[:, 2], 0)][0]
        assert np.allclose(shared, np.array((0, 1, 1)) / np.sqrt(2), atol=1e-5)

    def test_two_smoothing_groups_do_not_share(self) -> None:
        text = ('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n'
                's 1\nf 1 2 3\ns 2\nf 1 4 2\n')
        assert len(only_mesh(parse(text)).positions) == 6

    @pytest.mark.parametrize('off', ['off', '0'])
    def test_smoothing_off_splits_the_faces_again(self, off: str) -> None:
        text = ('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n'
                's 1\nf 1 2 3\ns %s\nf 1 4 2\n' % off)
        assert len(only_mesh(parse(text)).positions) == 6

    def test_a_smoothed_vertex_weights_each_face_by_its_angle(self) -> None:
        # A fan of one tiny and one huge triangle at the origin: the huge face's
        # area would drown the small one's under an area weighting, and the
        # normal tilts by the angle each face subtends instead.
        text = ('v 0 0 0\nv 100 0 0\nv 0 100 0\nv 0.01 0 0.01\n'
                's 1\nf 1 2 3\nf 1 4 2\n')
        mesh = only_mesh(parse(text))
        origin = np.isclose(np.abs(mesh.positions).sum(axis=1), 0)
        normal = mesh.normals[origin][0]
        assert np.allclose(np.linalg.norm(normal), 1.0)
        # the flat face subtends 90 degrees at the origin and the tilted one 45,
        # so the normal leans a half as far to +Y as it points to +Z
        assert np.allclose(normal, (0, 0.4472136, 0.8944272), atol=1e-5)

    def test_degenerate_triangles_give_finite_normals(self) -> None:
        text = 'v 0 0 0\nv 1 0 0\nv 2 0 0\nf 1 2 3\n'
        assert np.isfinite(only_mesh(parse(text)).normals).all()


class TestColours:
    def test_v_with_six_numbers_carries_a_colour(self) -> None:
        text = 'v 0 0 0 1 0 0\nv 1 0 0 0 1 0\nv 0 1 0 0 0 1\nf 1 2 3\n'
        mesh = only_mesh(parse(text))
        assert mesh.colors.shape == (3, 4)
        red = mesh.colors[np.isclose(mesh.positions[:, 0], 0) & np.isclose(mesh.positions[:, 1], 0)][0]
        assert np.allclose(red, (1, 0, 0, 1))

    def test_a_colour_written_as_bytes_is_scaled(self) -> None:
        text = 'v 0 0 0 255 0 0\nv 1 0 0 0 255 0\nv 0 1 0 0 0 51\nf 1 2 3\n'
        mesh = only_mesh(parse(text))
        assert mesh.colors.max() == pytest.approx(1.0)
        assert np.isclose(mesh.colors, 0.2).any()

    def test_vertices_without_a_colour_among_coloured_ones_are_white(self) -> None:
        text = 'v 0 0 0 1 0 0\nv 1 0 0\nv 0 1 0 0 0 1\nf 1 2 3\n'
        mesh = only_mesh(parse(text))
        plain = mesh.colors[np.isclose(mesh.positions[:, 0], 1)][0]
        assert np.allclose(plain, (1, 1, 1, 1))


class TestParts:
    def test_faces_before_any_name_are_one_unnamed_part(self) -> None:
        model = parse(SQUARE + 'f 1 2 3 4\n')
        assert [part.name for part in model.parts] == ['']

    def test_o_names_a_part(self) -> None:
        model = parse(SQUARE + 'o Wall\nf 1 2 3 4\no Roof\nf 1 2 3\n')
        assert [part.name for part in model.parts] == ['Wall', 'Roof']

    def test_g_names_a_part_when_there_is_no_object(self) -> None:
        model = parse(SQUARE + 'g Wall\nf 1 2 3 4\n')
        assert [part.name for part in model.parts] == ['Wall']

    def test_a_group_inside_an_object_names_both(self) -> None:
        model = parse(SQUARE + 'o House\ng Wall\nf 1 2 3 4\ng Roof\nf 1 2 3\n')
        assert [part.name for part in model.parts] == ['House_Wall', 'House_Roof']

    def test_a_group_naming_several_groups_joins_them(self) -> None:
        model = parse(SQUARE + 'g left arm\nf 1 2 3 4\n')
        assert [part.name for part in model.parts] == ['left_arm']

    def test_returning_to_a_group_continues_it(self) -> None:
        model = parse(SQUARE + 'g A\nf 1 2 3\ng B\nf 1 3 4\ng A\nf 1 2 4\n')
        assert [part.name for part in model.parts] == ['A', 'B']
        assert len(model.parts[0].meshes[0].indices) == 6

    def test_g_default_is_the_unnamed_group(self) -> None:
        model = parse(SQUARE + 'g A\nf 1 2 3\ng default\nf 1 3 4\n')
        assert [part.name for part in model.parts] == ['A', '']

    def test_a_part_with_no_faces_is_not_made(self) -> None:
        model = parse(SQUARE + 'o Empty\no Full\nf 1 2 3\n')
        assert [part.name for part in model.parts] == ['Full']


class TestMaterials:
    def test_usemtl_names_the_material_of_the_faces_after_it(self) -> None:
        model = parse(SQUARE + 'usemtl red\nf 1 2 3\nusemtl blue\nf 1 3 4\n')
        assert [mesh.material for mesh in model.parts[0].meshes] == ['red', 'blue']

    def test_runs_of_one_material_in_a_part_are_one_mesh(self) -> None:
        model = parse(SQUARE + 'usemtl red\nf 1 2 3\nusemtl blue\nf 1 3 4\n'
                      'usemtl red\nf 1 2 4\n')
        meshes = model.parts[0].meshes
        assert [mesh.material for mesh in meshes] == ['red', 'blue']
        assert len(meshes[0].indices) == 6

    def test_faces_before_usemtl_have_no_material(self) -> None:
        assert only_mesh(parse(SQUARE + 'f 1 2 3\n')).material == ''

    def test_material_names_may_hold_spaces(self) -> None:
        mesh = only_mesh(parse(SQUARE + 'usemtl dark red\nf 1 2 3\n'))
        assert mesh.material == 'dark red'

    def test_usemtl_after_a_new_group_still_applies(self) -> None:
        model = parse(SQUARE + 'usemtl red\ng A\nf 1 2 3\ng B\nf 1 3 4\n')
        assert [part.meshes[0].material for part in model.parts] == ['red', 'red']

    def test_mtllib_lists_every_library_in_order(self) -> None:
        model = parse('mtllib a.mtl b.mtl\nmtllib c.mtl\n' + SQUARE + 'f 1 2 3\n')
        assert model.libraries == ['a.mtl b.mtl', 'c.mtl']


class TestLinesAndPoints:
    def test_l_makes_segments(self) -> None:
        model = parse(SQUARE + 'l 1 2 3\nl 3 4\n')
        mesh = only_mesh(model)
        assert mesh.kind == 'lines'
        assert len(mesh.indices) == 6
        assert np.allclose(mesh.positions[mesh.indices[:2]], [(0, 0, 0), (1, 0, 0)])

    def test_l_accepts_texture_indices(self) -> None:
        model = parse(SQUARE + 'vt 0 0\nvt 1 0\nl 1/1 2/2\n')
        assert only_mesh(model).kind == 'lines'

    def test_p_makes_points(self) -> None:
        mesh = only_mesh(parse(SQUARE + 'p 1 2 3\n'))
        assert mesh.kind == 'points'
        assert len(mesh.indices) == 3

    def test_faces_lines_and_points_in_one_part_are_separate_meshes(self) -> None:
        model = parse(SQUARE + 'f 1 2 3\nl 1 3\np 4\n')
        assert sorted(mesh.kind for mesh in model.parts[0].meshes) == ['lines', 'points', 'triangles']


class TestSyntax:
    def test_comments_blank_lines_and_trailing_comments(self) -> None:
        text = '# header\n\nv 0 0 0 # origin\nv 1 0 0\n\tv 0 1 0\n\nf 1 2 3 # one\n'
        assert area(only_mesh(parse(text))) == pytest.approx(0.5)

    def test_windows_line_ends(self) -> None:
        text = 'v 0 0 0\r\nv 1 0 0\r\nv 0 1 0\r\nf 1 2 3\r\n'
        assert area(only_mesh(parse(text))) == pytest.approx(0.5)

    def test_old_mac_line_ends(self) -> None:
        text = 'v 0 0 0\rv 1 0 0\rv 0 1 0\rf 1 2 3\r'
        assert area(only_mesh(parse(text))) == pytest.approx(0.5)

    def test_backslash_continues_a_line(self) -> None:
        text = SQUARE + 'f 1 2 \\\n 3 4\n'
        assert len(only_mesh(parse(text)).indices) == 6

    def test_tabs_and_runs_of_spaces_separate_fields(self) -> None:
        text = 'v\t0   0\t0\nv 1\t0 0\nv 0 1 0\nf  1\t 2  3\n'
        assert area(only_mesh(parse(text))) == pytest.approx(0.5)

    def test_utf8_byte_order_mark(self) -> None:
        assert len(parse(b'\xef\xbb\xbf' + (SQUARE + 'f 1 2 3\n').encode()).parts) == 1

    def test_latin_1_names_decode(self) -> None:
        model = parse(SQUARE.encode() + b'o caf\xe9\nf 1 2 3\n')
        assert model.parts[0].name == 'caf\xe9'

    def test_a_file_with_no_final_newline(self) -> None:
        assert len(only_mesh(parse(SQUARE + 'f 1 2 3')).indices) == 3

    def test_empty_file_has_no_parts(self) -> None:
        assert parse('').parts == []
        assert parse('# nothing here\n').parts == []

    def test_keywords_this_reader_does_not_draw_are_counted_not_failed(self) -> None:
        text = SQUARE + 'vp 0.5\ncstype bspline\ndeg 3\ncurv 0 1 1 2 3\nend\nf 1 2 3\n'
        model = parse(text)
        assert len(model.parts) == 1
        assert model.ignored['curv'] == 1
        assert model.ignored['cstype'] == 1

    def test_unknown_keywords_are_counted(self) -> None:
        model = parse(SQUARE + 'frobnicate 1 2\nf 1 2 3\n')
        assert model.ignored['frobnicate'] == 1


class TestMalformed:
    def test_an_unreadable_number_names_its_line(self) -> None:
        with pytest.raises(ValueError, match=r'test\.obj:3.*abc'):
            parse('v 0 0 0\nv 1 0 0\nv 0 abc 0\n')

    @pytest.mark.parametrize('number', ['nan', 'inf', '-inf', '1e999'])
    def test_a_coordinate_that_is_not_finite_is_refused(self, number: str) -> None:
        with pytest.raises(ValueError, match=r'test\.obj'):
            parse('v 0 0 0\nv %s 0 0\nv 0 1 0\nf 1 2 3\n' % number)

    def test_a_vertex_with_too_few_numbers_names_its_line(self) -> None:
        with pytest.raises(ValueError, match=r'test\.obj:2'):
            parse('v 0 0 0\nv 1 0\n')

    def test_an_index_past_the_end_names_its_line(self) -> None:
        with pytest.raises(ValueError, match=r'test\.obj:4.*vertex'):
            parse('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 4\n')

    def test_a_relative_index_before_the_start_names_its_line(self) -> None:
        with pytest.raises(ValueError, match=r'test\.obj:2.*vertex'):
            parse('v 0 0 0\nf -1 -2 -3\n')

    def test_index_zero_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r'test\.obj:4.*vertex'):
            parse('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 0 1 2\n')

    def test_a_texture_index_with_no_texture_coordinates_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r'texture'):
            parse('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1/1 2/1 3/1\n')

    def test_a_normal_index_with_no_normals_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r'normal'):
            parse('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1//1 2//1 3//1\n')

    def test_a_corner_that_is_not_an_index_names_its_line(self) -> None:
        with pytest.raises(ValueError, match=r'test\.obj:4'):
            parse('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 x\n')

    def test_a_corner_of_four_parts_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r'test\.obj:4'):
            parse('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1/1/1/1 2 3\n')


class TestForwardReferences:
    def test_a_face_may_name_vertices_defined_after_it(self) -> None:
        mesh = only_mesh(parse('f 1 2 3\nv 0 0 0\nv 1 0 0\nv 0 1 0\n'))
        assert area(mesh) == pytest.approx(0.5)
