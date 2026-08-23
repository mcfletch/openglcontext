"""Road geometry: a centreline and a cross-section become a drivable surface.

The road is generated from a polyline and a profile, so what these assert is
the shape that comes out -- where the carriageway edges land, which way the
camber falls, that the surface is continuous around a bend, and that the
texture runs along the road rather than across it.

No GL: a road is arrays until something draws it.
"""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import road as road_module
from OpenGLContext.scenegraph.road import (
    RoadProfile, resample_polyline, road_mesh, road_surface, road_texture,
    tarmac_material,
)


def _straight(length=100.0, count=11, height=0.0):
    z = np.linspace(0.0, -length, count)
    return np.stack([np.zeros(count), np.full(count, height), z], axis=-1)


def _bend(radius=50.0, count=17):
    angle = np.linspace(0.0, math.pi / 2, count)
    return np.stack([radius * np.cos(angle), np.zeros(count),
                     -radius * np.sin(angle)], axis=-1)


class TestTheCrossSection:
    def test_the_carriageway_is_the_lanes_it_has(self) -> None:
        profile = RoadProfile(lane_width=3.5, lanes=2)
        assert profile.carriageway_width == pytest.approx(7.0)

    def test_the_section_runs_left_to_right(self) -> None:
        section = RoadProfile().section()
        assert np.all(np.diff(section[:, 0]) > 0)

    def test_the_section_is_symmetric(self) -> None:
        section = RoadProfile().section()
        assert np.allclose(section[:, 0], -section[::-1, 0])
        assert np.allclose(section[:, 1], section[::-1, 1])

    def test_the_crown_is_the_highest_point(self) -> None:
        """Water runs off a road because the middle is higher than the edges."""
        section = RoadProfile(crossfall=0.03).section()
        assert section[:, 1].argmax() == len(section) // 2
        assert section[:, 1].max() == 0.0

    def test_the_carriageway_edge_falls_by_the_crossfall(self) -> None:
        profile = RoadProfile(lane_width=4.0, lanes=2, crossfall=0.025)
        section = profile.section()
        edge = section[np.isclose(section[:, 0], 4.0)][0]
        assert edge[1] == pytest.approx(-0.1)         # 2.5% over 4 m

    def test_the_shoulder_drops_below_the_carriageway(self) -> None:
        profile = RoadProfile(shoulder_drop=0.2)
        section = profile.section()
        half = profile.carriageway_width / 2.0
        carriageway = section[np.isclose(section[:, 0], half)][0]
        shoulder = section[np.isclose(section[:, 0], half + profile.shoulder_width)][0]
        assert shoulder[1] < carriageway[1] - 0.19

    def test_the_verge_falls_away_to_the_ground(self) -> None:
        profile = RoadProfile(verge_drop=1.5)
        assert profile.section()[0, 1] < -1.4

    def test_the_full_width_covers_every_part(self) -> None:
        profile = RoadProfile()
        assert profile.total_width == pytest.approx(
            profile.section()[-1, 0] - profile.section()[0, 0])

    def test_a_road_can_be_a_bare_carriageway(self) -> None:
        profile = RoadProfile(shoulder_width=0.0, verge_width=0.0)
        assert len(profile.section()) == 3           # left edge, crown, right edge

    def test_texture_coordinates_span_the_section(self) -> None:
        u = RoadProfile().section_u()
        assert u[0] == pytest.approx(0.0) and u[-1] == pytest.approx(1.0)
        assert np.all(np.diff(u) > 0)


class TestResamplingACentreline:
    def test_it_spaces_points_evenly(self) -> None:
        points = resample_polyline(_straight(100.0, 3), spacing=10.0)
        steps = np.linalg.norm(np.diff(points, axis=0), axis=1)
        assert np.allclose(steps, steps[0], atol=1e-6)

    def test_it_keeps_the_ends(self) -> None:
        source = _straight(100.0, 3)
        points = resample_polyline(source, spacing=7.0)
        assert np.allclose(points[0], source[0])
        assert np.allclose(points[-1], source[-1], atol=1e-6)

    def test_a_coarser_spacing_gives_fewer_points(self) -> None:
        fine = resample_polyline(_bend(), spacing=2.0)
        coarse = resample_polyline(_bend(), spacing=20.0)
        assert len(coarse) < len(fine)

    def test_it_follows_a_bend_rather_than_cutting_it(self) -> None:
        points = resample_polyline(_bend(radius=50.0), spacing=5.0)
        radii = np.linalg.norm(points[:, [0, 2]], axis=1)
        assert np.allclose(radii, 50.0, atol=0.5)

    def test_two_points_are_enough(self) -> None:
        points = resample_polyline(np.array([(0, 0, 0), (0, 0, -10.0)]), spacing=3.0)
        assert len(points) >= 4

    def test_a_single_point_is_refused(self) -> None:
        with pytest.raises(ValueError, match='two points'):
            resample_polyline(np.array([(0, 0, 0.0)]), spacing=1.0)


class TestTheSurfaceItGenerates:
    def _surface(self, points=None, **kwargs):
        return road_surface(points if points is not None else _straight(),
                            RoadProfile(**kwargs))

    def test_a_vertex_ring_per_centreline_point(self) -> None:
        points = _straight(count=11)
        positions, _, _, _ = self._surface(points)
        assert len(positions) == 11 * len(RoadProfile().section())

    def test_the_road_is_as_wide_as_its_profile(self) -> None:
        profile = RoadProfile()
        positions, _, _, _ = self._surface()
        width = positions[:, 0].max() - positions[:, 0].min()
        assert width == pytest.approx(profile.total_width, abs=1e-4)

    def test_it_lies_along_the_centreline(self) -> None:
        positions, _, _, _ = self._surface(_straight(length=80.0))
        assert positions[:, 2].min() == pytest.approx(-80.0, abs=1e-4)
        assert positions[:, 2].max() == pytest.approx(0.0, abs=1e-4)

    def test_it_sits_at_the_height_of_the_centreline(self) -> None:
        positions, _, _, _ = self._surface(_straight(height=12.0))
        crown = positions[:, 1].max()
        assert crown == pytest.approx(12.0, abs=1e-4)

    def test_the_surface_normals_point_up(self) -> None:
        _, normals, _, _ = self._surface()
        assert normals[:, 1].min() > 0.5

    def test_the_triangles_are_wound_consistently(self) -> None:
        """A road wound both ways shows its underside through the surface."""
        positions, _, _, indices = self._surface()
        tris = indices.reshape(-1, 3)
        a, b, c = positions[tris[:, 0]], positions[tris[:, 1]], positions[tris[:, 2]]
        facing = np.cross(b - a, c - a)[:, 1]
        assert np.all(facing > 0) or np.all(facing < 0)

    def test_a_bend_stays_the_same_width_all_the_way_round(self) -> None:
        profile = RoadProfile()
        positions, _, _, _ = road_surface(_bend(radius=60.0), profile)
        ring = len(profile.section())
        widths = [np.linalg.norm(positions[i * ring] - positions[i * ring + ring - 1])
                  for i in range(len(positions) // ring)]
        assert np.allclose(widths, profile.total_width, atol=1e-3)

    def test_the_texture_runs_along_the_road(self) -> None:
        _, _, texcoords, _ = self._surface(_straight(length=100.0))
        assert texcoords[:, 1].max() > texcoords[:, 0].max()

    def test_the_texture_repeats_at_the_length_it_is_given(self) -> None:
        profile = RoadProfile(texture_length=25.0)
        _, _, texcoords, _ = road_surface(_straight(length=100.0), profile)
        assert texcoords[:, 1].max() == pytest.approx(4.0, abs=1e-3)

    def test_a_rising_road_tilts_with_the_grade(self) -> None:
        points = np.array([(0, 0, 0), (0, 10.0, -100.0)])
        positions, normals, _, _ = road_surface(resample_polyline(points, 10.0),
                                                RoadProfile())
        assert positions[:, 1].max() == pytest.approx(10.0, abs=0.01)
        assert normals[:, 2].mean() > 0.02        # leaning back into the climb


class TestTheMeshItGenerates:
    def test_it_is_a_pbr_mesh_with_a_material(self) -> None:
        mesh = road_mesh(_straight(), RoadProfile())
        assert mesh.positions is not None and mesh.indices is not None
        assert mesh.material is not None
        assert mesh.texcoords is not None

    def test_the_material_can_be_supplied(self) -> None:
        material = tarmac_material()
        assert road_mesh(_straight(), RoadProfile(), material=material).material is material

    def test_tangents_come_with_it_for_the_normal_map(self) -> None:
        mesh = road_mesh(_straight(), RoadProfile())
        assert mesh.tangents is not None and mesh.tangents.shape[1] == 4

    def test_a_spacing_sets_how_finely_it_is_built(self) -> None:
        """Re-sampling the centreline is the whole of a road's level of detail,
        so the caller that wants a coarse one says so here."""
        profile = RoadProfile()
        ring = len(profile.section())
        route = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)]
        fine = road_mesh(route, profile, spacing=5.0)
        coarse = road_mesh(route, profile, spacing=25.0)
        assert len(fine.positions) == 21 * ring
        assert len(coarse.positions) == 5 * ring

    def test_without_one_the_points_given_are_the_points_used(self) -> None:
        profile = RoadProfile()
        route = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)]
        mesh = road_mesh(route, profile)
        assert len(mesh.positions) == 2 * len(profile.section())


class TestTheRoadMaterial:
    def test_dry_tarmac_is_rough(self) -> None:
        assert 0.4 < tarmac_material().roughness < 1.0

    def test_the_colour_comes_from_the_texture(self) -> None:
        """One image spans tarmac, gravel and grass, so no factor describes it."""
        assert min(tarmac_material().baseColor) == pytest.approx(1.0)

    def test_wet_tarmac_is_smoother_and_darker(self) -> None:
        dry, wet = tarmac_material(), tarmac_material(wetness=1.0)
        assert wet.roughness < dry.roughness
        assert max(wet.baseColor) < max(dry.baseColor)

    def test_it_carries_the_road_surface_texture(self) -> None:
        assert 'baseColor' in tarmac_material().textures

    def test_the_road_is_not_double_sided(self) -> None:
        """Nothing drives under it, and back faces cost fill."""
        assert bool(tarmac_material().doubleSided) is False


class TestTheRoadTexture:
    def test_it_is_an_image_of_the_full_section(self) -> None:
        image = road_texture(size=64)
        assert image.size == (64, 64)

    def test_the_carriageway_is_darker_than_the_verge(self) -> None:
        """Asphalt is one of the darkest surfaces outdoors; grass is not."""
        pixels = np.asarray(road_texture(size=128).convert('RGB'), dtype='d')
        carriageway = pixels[:, 45:58].mean()      # tarmac, clear of the markings
        verge = pixels[:, :8].mean()
        assert carriageway < verge * 0.6

    def test_there_is_a_line_down_the_middle(self) -> None:
        pixels = np.asarray(road_texture(size=128).convert('RGB'), dtype='d')
        centre_column = pixels[:, 64].mean(axis=1)
        assert centre_column.max() > 150        # the dashes
        assert centre_column.min() < 90         # the gaps between them

    def test_it_is_deterministic(self) -> None:
        first = np.asarray(road_texture(size=64, seed=3))
        second = np.asarray(road_texture(size=64, seed=3))
        assert np.array_equal(first, second)


class TestSharedGeometryHelpers:
    def test_normals_are_estimated_from_the_triangles(self) -> None:
        """The helper the loader uses for a mesh with no normals, made public."""
        positions = np.array([(0, 0, 0), (1, 0, 0), (0, 0, -1)], 'f')
        indices = np.array([0, 1, 2], np.uint32)
        normals = road_module.estimate_normals(positions, indices)
        assert np.allclose(np.abs(normals[0]), (0, 1, 0), atol=1e-5)


class TestASectionThatChangesAlongTheRoad:
    """A road does not keep one cut from end to end: the verge flattens where
    it runs onto a bridge deck and the shoulder narrows into a bore. The sweep
    takes a section per point so the change is a taper rather than a step."""

    def _line(self, count=21, spacing=10.0):
        x = np.arange(count) * spacing
        return np.stack([x, np.zeros(count), np.zeros(count)], axis=-1)

    def test_a_road_with_one_section_is_unchanged(self) -> None:
        from OpenGLContext.scenegraph.road import morphed_sections, road_surface
        line = self._line()
        profile = RoadProfile()
        plain = road_surface(line, profile)[0]
        held = road_surface(line, profile, sections=morphed_sections(
            profile, profile, np.zeros(len(line))))[0]
        assert np.allclose(plain, held)

    def test_a_full_blend_gives_the_other_section(self) -> None:
        from OpenGLContext.scenegraph.road import morphed_sections, road_surface
        line = self._line()
        profile = RoadProfile()
        deck = profile.on_structure()
        blended = road_surface(line, profile, sections=morphed_sections(
            profile, deck, np.ones(len(line))))[0]
        assert np.allclose(blended, road_surface(line, deck)[0])

    def test_a_taper_runs_between_the_two(self) -> None:
        from OpenGLContext.scenegraph.road import morphed_sections, road_surface
        line = self._line()
        profile = RoadProfile()
        blend = np.linspace(0.0, 1.0, len(line))
        positions = road_surface(line, profile, sections=morphed_sections(
            profile, profile.on_structure(), blend))[0]
        ring = len(profile.section())
        verge = positions.reshape(len(line), ring, 3)[:, 0, 1]
        assert verge[0] < verge[-1]
        assert np.all(np.diff(verge) >= -1e-6)

    def test_the_road_is_still_one_surface(self) -> None:
        from OpenGLContext.scenegraph.road import morphed_sections, road_surface
        line = self._line()
        profile = RoadProfile()
        blend = np.concatenate([np.zeros(8), np.linspace(0, 1, 5), np.ones(8)])
        _positions, _normals, _uv, indices = road_surface(
            line, profile, sections=morphed_sections(
                profile, profile.on_structure(), blend))
        ring = len(profile.section())
        assert len(indices) == (len(line) - 1) * (ring - 1) * 6

    def test_a_section_per_point_is_required(self) -> None:
        from OpenGLContext.scenegraph.road import morphed_sections, road_surface
        line = self._line()
        profile = RoadProfile()
        with pytest.raises(ValueError):
            road_surface(line, profile, sections=morphed_sections(
                profile, profile, np.zeros(3)))

    def test_a_mesh_takes_them_too(self) -> None:
        from OpenGLContext.scenegraph.road import morphed_sections, road_mesh
        line = self._line()
        profile = RoadProfile()
        mesh = road_mesh(line, profile, sections=morphed_sections(
            profile, profile.on_structure(), np.linspace(0, 1, len(line))))
        assert len(mesh.positions) == len(line) * len(profile.section())

    def test_two_profiles_of_different_shape_cannot_be_blended(self) -> None:
        from OpenGLContext.scenegraph.road import morphed_sections
        with pytest.raises(ValueError):
            morphed_sections(RoadProfile(), RoadProfile(verge_width=0.0),
                             np.zeros(4))


class TestTheCutOverAStructure:
    """A deck and a bore have no ground beside them for a verge to fall to, and
    a grass verge inside a tunnel is grass inside a tunnel."""

    def test_the_verge_does_not_fall(self) -> None:
        assert RoadProfile().on_structure().verge_drop == 0.0

    def test_it_is_an_edge_beam_rather_than_a_verge(self) -> None:
        profile = RoadProfile()
        assert profile.on_structure().verge_width < profile.verge_width / 2.0

    def test_the_carriageway_is_untouched(self) -> None:
        profile = RoadProfile()
        assert profile.on_structure().carriageway_width \
            == profile.carriageway_width

    def test_the_road_narrows_onto_it(self) -> None:
        profile = RoadProfile()
        assert profile.on_structure().total_width < profile.total_width

    def test_the_two_sections_have_the_same_points(self) -> None:
        """Or they cannot be blended, and the change is a step."""
        profile = RoadProfile()
        assert profile.section().shape == profile.on_structure().section().shape

    def test_a_road_with_no_verge_still_has_one_on_a_structure(self) -> None:
        profile = RoadProfile(verge_width=0.0)
        assert profile.section().shape \
            == profile.on_structure().section().shape

    def test_blending_the_two_narrows_the_road(self) -> None:
        from OpenGLContext.scenegraph.road import morphed_sections
        profile = RoadProfile()
        blend = morphed_sections(profile, profile.on_structure(),
                                 np.array([0.0, 1.0]))
        assert abs(blend[1, 0, 0]) < abs(blend[0, 0, 0])


class TestThePaintIsWhereTheRoadIs:
    """A road's markings are painted into the surface texture across its whole
    section, so where the bands fall has to come from the *profile* rather than
    from a set of fractions. Painted to fractions of a section they do not
    belong to, the carriageway comes out narrower than it is built: the lane a
    driver sees is not the lane the car is on, and a car half a lane wide looks
    like a car that fills one.
    """

    @staticmethod
    def _bands(profile, size=512):
        """Where the tarmac starts and stops across the painted image."""
        import numpy as np
        from OpenGLContext.scenegraph.road import TARMAC_ALBEDO, road_texture
        found = np.asarray(road_texture(size, profile=profile), dtype='d') / 255.0
        row = found[0]
        dark = row.max(axis=-1) < max(TARMAC_ALBEDO) * 2.5
        columns = np.nonzero(dark)[0]
        return columns.min() / size, (columns.max() + 1) / size

    def test_the_tarmac_is_as_wide_as_the_carriageway(self) -> None:
        from OpenGLContext.scenegraph.road import RoadProfile
        profile = RoadProfile(lane_width=3.6, lanes=2)
        first, last = self._bands(profile)
        painted = (last - first) * profile.total_width
        assert painted == pytest.approx(profile.carriageway_width, abs=0.25)

    def test_a_wider_road_paints_a_wider_carriageway(self) -> None:
        from OpenGLContext.scenegraph.road import RoadProfile
        narrow = self._bands(RoadProfile(lane_width=3.0, lanes=2))
        wide = self._bands(RoadProfile(lane_width=3.6, lanes=4))
        assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])

    def test_the_edge_lines_are_at_the_edge_of_the_carriageway(self) -> None:
        import numpy as np
        from OpenGLContext.scenegraph.road import (
            LINE_ALBEDO,
            RoadProfile,
            road_texture,
        )
        profile = RoadProfile(lane_width=3.6, lanes=2)
        size = 512
        found = np.asarray(road_texture(size, profile=profile), dtype='d') / 255.0
        row = found[0]
        paint = np.nonzero(row.min(axis=-1) > min(LINE_ALBEDO) * 0.9)[0]
        assert len(paint)
        edge = 0.5 - (profile.carriageway_width / 2.0) / profile.total_width
        assert paint.min() / size == pytest.approx(edge, abs=0.03)

    def test_and_the_dashes_run_down_the_crown(self) -> None:
        import numpy as np
        from OpenGLContext.scenegraph.road import (
            LINE_ALBEDO,
            RoadProfile,
            road_texture,
        )
        found = np.asarray(road_texture(512, profile=RoadProfile()),
                           dtype='d') / 255.0
        middle = found[:, 256]
        assert (middle.min(axis=-1) > min(LINE_ALBEDO) * 0.9).any()


class TestHowFastABankedCornerAllows:
    def test_a_flat_corner_is_the_grip_it_has(self) -> None:
        from OpenGLContext.scenegraph.road import corner_speed
        assert corner_speed(100.0, grip=1.0) == pytest.approx(math.sqrt(9.81 * 100.0))

    def test_banking_a_corner_makes_it_faster(self) -> None:
        from OpenGLContext.scenegraph.road import corner_speed
        assert corner_speed(315.0, bank=0.3) > corner_speed(315.0, bank=0.0)

    def test_the_bank_is_the_sign_free_part_of_it(self) -> None:
        """Left or right, a corner leans into itself and gains the same."""
        from OpenGLContext.scenegraph.road import corner_speed
        assert corner_speed(200.0, bank=-0.25) == pytest.approx(
            corner_speed(200.0, bank=0.25))

    def test_a_bank_steep_enough_needs_no_tyre_at_all(self) -> None:
        """Past ``grip * bank == 1`` the road holds a car of any speed."""
        from OpenGLContext.scenegraph.road import corner_speed
        assert not math.isfinite(corner_speed(100.0, grip=1.0, bank=1.5))

    def test_a_banked_corner_may_be_tighter_for_the_same_speed(self) -> None:
        from OpenGLContext.scenegraph.road import cornering_radius
        speed = 200.0 / 3.6
        assert cornering_radius(speed, bank=0.3) < cornering_radius(speed) * 0.7

    def test_the_radius_and_the_speed_are_each_other(self) -> None:
        from OpenGLContext.scenegraph.road import corner_speed, cornering_radius
        speed = 180.0 / 3.6
        found = cornering_radius(speed, grip=0.9, bank=0.2)
        assert corner_speed(found, grip=0.9, bank=0.2) == pytest.approx(speed)


class TestTheBankACornerAsks:
    def test_it_balances_a_car_at_the_speed_it_is_given(self) -> None:
        """No sideways grip is needed at the speed the bank is chosen for."""
        from OpenGLContext.scenegraph.road import superelevation
        radius, speed = 400.0, 40.0
        found = float(superelevation(radius, speed, maximum=10.0))
        assert found == pytest.approx(speed * speed / (9.81 * radius))

    def test_a_straight_asks_for_none(self) -> None:
        from OpenGLContext.scenegraph.road import superelevation
        assert float(superelevation(1e9, 55.0)) == pytest.approx(0.0, abs=1e-6)

    def test_it_never_leans_further_than_it_is_allowed(self) -> None:
        from OpenGLContext.scenegraph.road import superelevation
        assert float(superelevation(20.0, 55.0, maximum=0.3)) == pytest.approx(0.3)

    def test_it_answers_an_array_of_corners_at_once(self) -> None:
        from OpenGLContext.scenegraph.road import superelevation
        found = superelevation(np.array([1e9, 4000.0, 1200.0]), 55.0, maximum=0.3)
        assert found.shape == (3,)
        assert found[0] < found[1] < found[2]


class TestTheCurvatureOfAPlan:
    def test_a_straight_has_none(self) -> None:
        from OpenGLContext.scenegraph.road import plan_curvature
        found = plan_curvature(resample_polyline(_straight(length=200.0), 5.0))
        assert np.allclose(found, 0.0, atol=1e-6)

    def test_a_circle_is_one_over_its_radius(self) -> None:
        from OpenGLContext.scenegraph.road import plan_curvature
        line = resample_polyline(_bend(radius=120.0, count=257), 4.0)
        found = plan_curvature(line, baseline=30.0)
        assert np.allclose(np.abs(found[6:-6]), 1.0 / 120.0, rtol=0.02)

    def test_it_is_positive_where_the_road_turns_right(self) -> None:
        """``_bend`` runs anticlockwise seen from above, which is a left turn."""
        from OpenGLContext.scenegraph.road import plan_curvature
        line = resample_polyline(_bend(radius=120.0, count=257), 4.0)
        assert plan_curvature(line)[10] < 0.0
        assert plan_curvature(line[::-1])[10] > 0.0


class TestTheBankAlongARoad:
    def _circuit(self, radius=200.0, straight=400.0, spacing=5.0):
        """A straight, a quarter circle to the right, and a straight."""
        run = np.stack([np.zeros(2), np.zeros(2),
                        np.array([0.0, -straight])], axis=-1)
        angle = np.linspace(0.0, math.pi / 2, 65)
        arc = np.stack([radius - radius * np.cos(angle), np.zeros(65),
                        -straight - radius * np.sin(angle)], axis=-1)
        out = np.stack([np.array([radius, radius + 300.0]), np.zeros(2),
                        np.full(2, -straight - radius)], axis=-1)
        return resample_polyline(np.vstack([run, arc[1:], out[1:]]), spacing)

    def test_a_straight_road_is_not_banked(self) -> None:
        from OpenGLContext.scenegraph.road import bank_profile
        found = bank_profile(resample_polyline(_straight(length=400.0), 5.0),
                             speed=55.0)
        assert np.allclose(found, 0.0, atol=1e-6)

    def test_a_corner_leans_into_itself(self) -> None:
        from OpenGLContext.scenegraph.road import bank_profile
        line = self._circuit()
        found = bank_profile(line, speed=55.0)
        # A right-hand bend banks positive: the right side of the road, which
        # is the inside of the turn, is the low one.
        assert found.max() > 0.05
        assert found.min() > -1e-6

    def test_it_never_exceeds_what_it_is_allowed(self) -> None:
        from OpenGLContext.scenegraph.road import bank_profile
        found = bank_profile(self._circuit(radius=60.0), speed=55.0,
                             maximum=0.25)
        assert found.max() <= 0.25 + 1e-9

    def test_it_is_taken_up_gradually_rather_than_at_a_vertex(self) -> None:
        from OpenGLContext.scenegraph.road import bank_profile
        profile = RoadProfile()
        line = self._circuit()
        found = bank_profile(line, speed=55.0, profile=profile, gradient=0.01)
        steps = np.linalg.norm(np.diff(line, axis=0), axis=1)
        rate = np.abs(np.diff(found)) / np.maximum(steps, 1e-9)
        allowed = 0.01 / (profile.carriageway_width / 2.0)
        assert rate.max() <= allowed * 1.0001

    def test_the_lean_is_taken_up_before_the_corner_starts(self) -> None:
        """A runoff straddles the entry: the road is already leaning when it
        gets there, rather than rolling once it is in the bend."""
        from OpenGLContext.scenegraph.road import bank_profile
        line = self._circuit(straight=400.0)
        found = bank_profile(line, speed=55.0)
        entry = int(np.searchsorted(
            np.concatenate([[0.0], np.cumsum(
                np.linalg.norm(np.diff(line, axis=0), axis=1))]), 400.0))
        assert found[entry] > 0.02

    def test_a_quicker_transition_starts_closer_to_the_corner(self) -> None:
        from OpenGLContext.scenegraph.road import bank_profile
        line = self._circuit()

        def onset(found):
            return int(np.argmax(found >= found.max() * 0.5))
        gentle = bank_profile(line, speed=55.0, gradient=0.004)
        quick = bank_profile(line, speed=55.0, gradient=0.02)
        assert onset(quick) > onset(gentle)

    def test_a_road_that_cannot_reach_the_bank_takes_what_it_can(self) -> None:
        """A corner shorter than its own runoff is banked less, not stepped."""
        from OpenGLContext.scenegraph.road import bank_profile
        line = self._circuit(radius=60.0, straight=200.0)
        found = bank_profile(line, speed=55.0, gradient=0.001, maximum=0.3)
        assert 0.0 < found.max() < 0.3


class TestABankedSurface:
    def _banked(self, bank, profile=None, points=None):
        from OpenGLContext.scenegraph.road import banked_sections, road_surface
        profile = profile or RoadProfile()
        line = points if points is not None else _straight(length=100.0)
        lean = np.full(len(line), bank)
        sections = banked_sections(
            np.tile(profile.section(), (len(line), 1, 1)), lean, profile)
        return road_surface(line, profile, sections=sections, bank=lean)

    def test_an_unbanked_road_is_the_road_it_always_was(self) -> None:
        from OpenGLContext.scenegraph.road import road_surface
        plain = road_surface(_straight(), RoadProfile())[0]
        assert np.allclose(self._banked(0.0)[0], plain)

    def test_the_outside_of_the_bank_is_the_high_side(self) -> None:
        """A road running south, banked right-side-down: +x is the low side."""
        positions = self._banked(0.25)[0]
        left = positions[positions[:, 0] < -1.0][:, 1].mean()
        right = positions[positions[:, 0] > 1.0][:, 1].mean()
        assert left > right

    def test_the_carriageway_is_one_plane_once_it_is_banked(self) -> None:
        """Past the crossfall the crown is gone and the whole cut is flat."""
        profile = RoadProfile(crossfall=0.02, lane_width=3.7, lanes=2)
        positions = self._banked(0.20, profile)[0]
        ring = len(profile.section())
        cut = positions[3 * ring:4 * ring][2:5]          # the carriageway
        fit = np.polyfit(cut[:, 0], cut[:, 1], 1)
        assert fit[0] == pytest.approx(-0.20, abs=1e-6)
        assert np.allclose(np.polyval(fit, cut[:, 0]), cut[:, 1], atol=1e-9)

    def test_the_crown_survives_a_bank_shallower_than_the_crossfall(self) -> None:
        """Half way through the change the outer half is level and the inner
        half still falls at the crossfall."""
        profile = RoadProfile(crossfall=0.02)
        positions = self._banked(0.01, profile)[0]
        ring = len(profile.section())
        # 2, 3, 4 of the ring are the left carriageway edge, the crown and the
        # right one -- the road runs south, so the right edge is the low side.
        high, crown, low = positions[3 * ring + 2:3 * ring + 5][:, 1]
        # The camber left is measured across the pavement, which is leaning, so
        # what is left of it in plan is the cosine of the lean shallower.
        half = profile.carriageway_width / 2.0 * math.cos(math.atan(0.01))
        assert high == pytest.approx(crown, abs=1e-6)
        assert low == pytest.approx(crown - 0.02 * half, abs=1e-6)

    def test_it_keeps_the_width_it_is_told(self) -> None:
        """The pavement turns about the crown; it does not stretch."""
        profile = RoadProfile()
        positions = self._banked(0.3, profile)[0]
        ring = len(profile.section())
        cut = positions[3 * ring:4 * ring]
        assert np.linalg.norm(cut[-1] - cut[0]) == pytest.approx(
            profile.total_width, abs=1e-6)

    def test_the_surface_normal_leans_with_the_bank(self) -> None:
        _positions, normals, _uv, _indices = self._banked(0.3)
        assert normals[:, 0].mean() > 0.1       # tilted towards +x, the low side

    def test_the_section_offset_follows_the_crown_being_taken_out(self) -> None:
        profile = RoadProfile(crossfall=0.02)
        half = profile.carriageway_width / 2.0
        assert profile.section_offset(half, bank=0.2) == pytest.approx(0.0)
        assert profile.section_offset(half, bank=0.005) == pytest.approx(
            -0.015 * half)


class TestALineWithNoLengthInASegment:
    """A centreline may arrive with a point written twice.

    A segment of no length has no direction, and the frame built from one is
    not a frame: :func:`sweep_frames` falls into its vertical-tangent guard,
    the up vector comes out zero, and every vertex of that ring collapses onto
    the centreline.  What a car meets there is a hole in the road.
    """

    def _doubled(self, at):
        """A straight with the point at ``at`` written twice."""
        line = _straight(length=100.0, count=11)
        return np.insert(line, at, line[at], axis=0)

    def test_the_doubled_point_keeps_an_up_vector(self) -> None:
        from OpenGLContext.scenegraph.road import sweep_frames
        _right, up = sweep_frames(self._doubled(5))
        assert np.linalg.norm(up[5]) == pytest.approx(1.0, abs=1e-9), (
            "the ring there has no up vector: %r" % (up[5],))

    def test_it_gets_the_frame_the_road_has_there(self) -> None:
        from OpenGLContext.scenegraph.road import sweep_frames
        right, up = sweep_frames(self._doubled(5))
        assert np.allclose(right[5], right[4], atol=1e-9)
        assert np.allclose(up[5], up[4], atol=1e-9)

    def test_a_doubled_point_at_the_end_keeps_its_frame(self) -> None:
        """Where a caller closes a loop by repeating the first point onto a
        line that already ended with it."""
        from OpenGLContext.scenegraph.road import sweep_frames
        line = _straight(length=100.0, count=11)
        line = np.vstack([line, line[-1:]])
        _right, up = sweep_frames(line)
        assert np.linalg.norm(up[-1]) == pytest.approx(1.0, abs=1e-9)

    def test_the_surface_does_not_collapse_there(self) -> None:
        profile = RoadProfile()
        positions = road_surface(self._doubled(5), profile)[0]
        ring = len(profile.section())
        cut = positions[5 * ring:6 * ring]
        assert np.linalg.norm(cut[-1] - cut[0]) == pytest.approx(
            profile.total_width, rel=1e-3), (
                "the ring is %.3f m wide, not %.3f"
                % (float(np.linalg.norm(cut[-1] - cut[0])),
                   profile.total_width))


class TestASweepThatComesBackToItsStart:
    """A circuit has no first point: the ring before the first is the last.

    Swept as though it were an open road, the two ends get a one-sided tangent
    and the cut at the seam is rolled away from the road either side of it.
    """

    def _loop(self, radius=60.0, count=24, repeat=False):
        angle = np.linspace(0.0, 2 * math.pi, count, endpoint=False)
        ring = np.stack([radius * np.cos(angle), np.zeros(count),
                         radius * np.sin(angle)], axis=-1)
        return np.vstack([ring, ring[:1]]) if repeat else ring

    def test_an_open_sweep_is_unchanged(self) -> None:
        from OpenGLContext.scenegraph.road import sweep_frames
        line = self._loop()
        assert np.allclose(sweep_frames(line)[0],
                           sweep_frames(line, closed=False)[0])

    def test_the_seam_gets_the_frame_its_neighbours_have(self) -> None:
        """Round a circle every across vector is radial, the seam included."""
        from OpenGLContext.scenegraph.road import sweep_frames
        line = self._loop()
        right, _up = sweep_frames(line, closed=True)
        radial = line / np.linalg.norm(line, axis=1, keepdims=True)
        assert np.allclose(np.abs((right * radial).sum(axis=1)), 1.0,
                           atol=1e-9)

    def test_a_line_that_already_repeats_its_first_point(self) -> None:
        """The shape a baked circuit arrives in: the closing ring is the
        opening one, so the two cuts have to coincide."""
        from OpenGLContext.scenegraph.road import banked_sections
        profile = RoadProfile()
        line = self._loop(repeat=True)
        lean = np.full(len(line), 0.10)
        sections = banked_sections(
            np.tile(profile.section(), (len(line), 1, 1)), lean, profile)
        positions = road_surface(line, profile, sections=sections, bank=lean,
                                 closed=True)[0]
        ring = len(profile.section())
        assert np.allclose(positions[-ring:], positions[:ring], atol=1e-5), (
            "the closing ring is %.3f m from the opening one"
            % float(np.abs(positions[-ring:] - positions[:ring]).max()))

    def test_frames_can_be_supplied_for_a_stretch_of_a_longer_road(self) -> None:
        """A chunk of a road cannot be swept on its own: the frame at its ends
        depends on the points either side, which the chunk does not have."""
        from OpenGLContext.scenegraph.road import sweep_frames
        profile = RoadProfile()
        line = self._loop(count=48)
        right, up = sweep_frames(line, closed=True)
        whole = road_surface(line, profile, closed=True)[0]
        ring = len(profile.section())
        part = road_surface(line[10:20], profile,
                            frames=(right[10:20], up[10:20]))[0]
        assert np.allclose(part, whole[10 * ring:20 * ring], atol=1e-5)
