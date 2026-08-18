"""The start/finish gantry: a beam over the road and a line painted under it.

A circuit's lap has to be visible from the driving seat. The timing already
knows where the line is; what is here is the thing a driver sees coming and
recognises -- a chequered banner on a beam spanning the carriageway, with a
chequered line across the tarmac beneath it.

Built at the origin with the road running along -Z and the beam spanning X, so
a world places one by turning and moving it, the same way it places a sign.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.gantry import (
    CHEQUER_DARK,
    CHEQUER_LIGHT,
    GantryProfile,
    chequer_texture,
    gantry_atlas,
    gantry_legs,
    gantry_material,
    gantry_mesh,
    start_line_mesh,
)
from OpenGLContext.scenegraph.atlasmesh import cell_centre, srgb_bytes

SPAN = 9.0
WIDTH = 7.4


def _points(mesh):
    return np.asarray(mesh.positions, dtype='d')


class TestTheChequer:
    def test_it_is_the_two_colours_and_nothing_else(self) -> None:
        image = chequer_texture(size=64, columns=4, rows=2)
        found = {image.getpixel((x, y)) for x in range(64) for y in range(64)}
        assert found == {srgb_bytes(CHEQUER_DARK), srgb_bytes(CHEQUER_LIGHT)}

    def test_neighbouring_squares_differ(self) -> None:
        image = chequer_texture(size=64, columns=4, rows=2)
        assert image.getpixel((8, 8)) != image.getpixel((24, 8))
        assert image.getpixel((8, 8)) != image.getpixel((8, 40))

    def test_the_light_squares_are_not_white(self) -> None:
        """A white board in sunlight is the brightest object in the scene."""
        assert max(CHEQUER_LIGHT) < 0.85


class TestTheAtlas:
    def test_it_holds_the_steel_the_banner_and_the_two_paints(self) -> None:
        _image, cells = gantry_atlas(cell=32)
        assert set(cells) == {'steel', 'banner', 'paint-light', 'paint-dark'}

    def test_the_steel_cell_is_the_colour_the_material_would_be(self) -> None:
        from OpenGLContext.scenegraph.gantry import GANTRY_STEEL
        image, cells = gantry_atlas(cell=32)
        u0, v0, _u1, _v1 = cells['steel']
        at = (int(u0 * image.width) + 4, int(v0 * image.height) + 4)
        assert image.getpixel(at) == srgb_bytes(GANTRY_STEEL)

    def test_the_same_atlas_comes_out_every_time(self) -> None:
        assert gantry_atlas(cell=32)[1] == gantry_atlas(cell=32)[1]

    def test_a_gantry_wears_one_material(self) -> None:
        material = gantry_material()
        beam = gantry_mesh(SPAN, material=material,
                           cells=gantry_atlas(cell=32)[1])
        line = start_line_mesh(WIDTH, material=material,
                               cells=gantry_atlas(cell=32)[1])
        assert beam.material is line.material is material

    def test_the_material_is_opaque(self) -> None:
        """Nothing here is glass; a sorted pass for a steel beam is waste."""
        from OpenGLContext.scenegraph.pbrmaterial import material_is_transparent
        assert not material_is_transparent(gantry_material())


class TestTheGantry:
    def test_nothing_hangs_into_the_road(self) -> None:
        """Everything below the beam is out at the legs, clear of the tarmac."""
        profile = GantryProfile()
        points = _points(gantry_mesh(SPAN, profile))
        low = points[points[:, 1] < profile.clearance - 1e-6]
        assert float(np.abs(low[:, 0]).min()) >= SPAN / 2.0 - profile.leg_radius - 1e-6

    def test_its_legs_stand_at_the_ends_of_the_span(self) -> None:
        points = _points(gantry_mesh(SPAN))
        feet = points[points[:, 1] < 0.01]
        assert pytest.approx(SPAN / 2.0, abs=0.2) == float(np.max(feet[:, 0]))
        assert pytest.approx(-SPAN / 2.0, abs=0.2) == float(np.min(feet[:, 0]))

    def test_it_is_tall_enough_to_drive_a_lorry_under(self) -> None:
        assert GantryProfile().clearance >= 5.0

    def test_the_banner_sits_above_the_beam(self) -> None:
        profile = GantryProfile()
        points = _points(gantry_mesh(SPAN, profile))
        top = profile.clearance + profile.beam_depth + profile.banner_height
        assert pytest.approx(top, abs=1e-5) == float(points[:, 1].max())

    def test_the_banner_is_a_wide_thin_board(self) -> None:
        profile = GantryProfile()
        board = _points(gantry_mesh(SPAN, profile))
        board = board[board[:, 1] > profile.clearance + profile.beam_depth + 1e-6]
        assert float(np.ptp(board[:, 0])) > 5.0 * float(np.ptp(board[:, 2]))
        assert pytest.approx(profile.banner_depth,
                             abs=1e-6) == float(np.ptp(board[:, 2]))

    def test_the_banner_faces_up_and_down_the_road(self) -> None:
        """Its large faces look at the traffic, not across it."""
        profile = GantryProfile()
        mesh = gantry_mesh(SPAN, profile)
        high = _points(mesh)[:, 1] > profile.clearance + profile.beam_depth + 1e-6
        normals = np.asarray(mesh.normals, dtype='d')[high]
        assert float(np.abs(normals[:, 2]).max()) > 0.99

    def test_a_leg_reaches_ground_that_is_lower_than_the_road(self) -> None:
        points = _points(gantry_mesh(SPAN, drops=(0.0, 2.5)))
        left = points[points[:, 0] < 0]
        right = points[points[:, 0] > 0]
        assert pytest.approx(0.0, abs=1e-6) == float(left[:, 1].min())
        assert pytest.approx(-2.5, abs=1e-6) == float(right[:, 1].min())

    def test_it_is_one_mesh(self) -> None:
        mesh = gantry_mesh(SPAN)
        assert len(np.asarray(mesh.indices)) % 3 == 0
        assert len(mesh.texcoords) == len(mesh.positions)

    def test_every_point_reads_somewhere_in_the_atlas(self) -> None:
        uv = np.asarray(gantry_mesh(SPAN).texcoords, dtype='d')
        assert float(uv.min()) >= 0.0 and float(uv.max()) <= 1.0

    def test_a_span_narrower_than_its_own_legs_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            gantry_mesh(0.1)


class TestTheLegsAsObstacles:
    def test_there_are_two_of_them(self) -> None:
        assert len(gantry_legs(SPAN)) == 2

    def test_they_stand_where_the_geometry_puts_them(self) -> None:
        assert [leg.offset for leg in gantry_legs(SPAN)] == [-SPAN / 2.0,
                                                             SPAN / 2.0]

    def test_a_leg_is_as_tall_as_the_gantry_it_holds_up(self) -> None:
        profile = GantryProfile()
        legs = gantry_legs(SPAN, profile)
        assert pytest.approx(profile.clearance + profile.beam_depth,
                             abs=1e-6) == legs[0].height

    def test_a_leg_on_low_ground_is_that_much_taller(self) -> None:
        legs = gantry_legs(SPAN, drops=(0.0, 2.5))
        assert pytest.approx(legs[0].height + 2.5, abs=1e-6) == legs[1].height

    def test_a_leg_is_as_wide_as_it_is_drawn(self) -> None:
        profile = GantryProfile()
        assert gantry_legs(SPAN, profile)[0].radius == profile.leg_radius


class TestThePaintedLine:
    def test_it_lies_across_the_carriageway(self) -> None:
        points = _points(start_line_mesh(WIDTH))
        assert pytest.approx(WIDTH, abs=1e-6) == float(np.ptp(points[:, 0]))

    def test_it_is_narrow_along_the_road(self) -> None:
        profile = GantryProfile()
        points = _points(start_line_mesh(WIDTH, profile))
        assert pytest.approx(profile.line_width,
                             abs=1e-6) == float(np.ptp(points[:, 2]))

    def test_it_lies_just_above_the_tarmac(self) -> None:
        """In the surface it z-fights; far above it it is a plank."""
        profile = GantryProfile()
        points = _points(start_line_mesh(WIDTH, profile))
        assert 0.0 < float(points[:, 1].max()) < 0.1
        assert pytest.approx(profile.line_lift,
                             abs=1e-6) == float(points[:, 1].max())

    def test_it_follows_the_camber(self) -> None:
        """A flat quad on a cambered road sinks into it at the edges."""
        points = _points(start_line_mesh(WIDTH, crossfall=0.02))
        edge = points[np.abs(points[:, 0]) > WIDTH / 2.0 - 1e-6]
        assert float(edge[:, 1].max()) < float(points[:, 1].max())
        assert pytest.approx(0.02 * WIDTH / 2.0, abs=1e-6) == (
            float(points[:, 1].max()) - float(edge[:, 1].max()))

    def test_it_faces_the_sky(self) -> None:
        normals = np.asarray(start_line_mesh(WIDTH).normals, dtype='d')
        assert float(normals[:, 1].min()) > 0.9

    def test_it_is_chequered_in_geometry_rather_than_in_a_picture(self) -> None:
        """Seen from a driving seat the line is nearly edge-on, and a texture
        stretched nine times wider than it is deep loses its pattern to the
        mip level the grazing angle asks for. Each square is its own quad
        reading a flat colour, so it is a chequer at any angle."""
        cells = gantry_atlas(cell=32)[1]
        uv = np.asarray(start_line_mesh(WIDTH, cells=cells).texcoords,
                        dtype='d')
        read = {tuple(round(float(v), 6) for v in one) for one in uv}
        assert read == {cell_centre(cells['paint-light']),
                        cell_centre(cells['paint-dark'])}

    def test_its_squares_alternate(self) -> None:
        mesh = start_line_mesh(WIDTH)
        points = _points(mesh)
        uv = np.asarray(mesh.texcoords, dtype='d')
        near = [(float(points[i][0]), tuple(uv[i]))
                for i in range(0, len(points), 4)
                if points[i][2] < 0.0]
        near.sort()
        colours = [one[1] for one in near]
        assert len(set(colours)) == 2
        assert all(a != b for a, b in zip(colours, colours[1:], strict=False))

    def test_a_square_is_about_as_wide_as_it_is_deep(self) -> None:
        profile = GantryProfile()
        points = _points(start_line_mesh(WIDTH, profile))
        across = sorted({round(float(v), 6) for v in points[:, 0]})
        step = across[1] - across[0]
        assert pytest.approx(profile.line_width / 2.0, abs=0.12) == step

    def test_the_crown_of_the_road_falls_on_a_square_edge(self) -> None:
        """An odd number of squares would put a joint off-centre and the two
        halves of the line would not mirror each other."""
        points = _points(start_line_mesh(WIDTH))
        assert 0.0 in {round(float(v), 6) for v in points[:, 0]}


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
