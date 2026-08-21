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
