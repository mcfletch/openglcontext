"""Reading relief off a plan view: a cartographic hillshade.

Pure arithmetic on normals, so none of it needs a window.
"""
import numpy as np
import pytest

from OpenGLContext.edit.relief import (
    DEFAULT_ALTITUDE,
    DEFAULT_AZIMUTH,
    DEFAULT_EXAGGERATION,
    hillshade,
    light_vector,
    shade_colors,
    steepen,
)


def _normals(*vectors):
    return np.asarray(vectors, dtype='f')


UP = (0.0, 1.0, 0.0)


class TestWhereTheSunIs:
    def test_the_default_sun_is_in_the_north_west(self) -> None:
        """The cartographic convention: relief read any other way inverts."""
        direction = light_vector(DEFAULT_AZIMUTH, DEFAULT_ALTITUDE)
        assert direction[0] < 0.0        # west
        assert direction[2] < 0.0        # north, which is -z in the world
        assert direction[1] > 0.0        # above the ground

    def test_it_is_a_unit_vector(self) -> None:
        assert np.linalg.norm(light_vector(120.0, 30.0)) == pytest.approx(1.0)

    def test_a_sun_overhead_is_straight_up(self) -> None:
        assert np.allclose(light_vector(0.0, 90.0), (0.0, 1.0, 0.0), atol=1e-6)

    def test_east_is_plus_x(self) -> None:
        assert light_vector(90.0, 0.0)[0] == pytest.approx(1.0)


class TestTheShading:
    def test_flat_ground_takes_the_sun_at_its_altitude(self) -> None:
        value = hillshade(_normals(UP), azimuth=315.0, altitude=45.0)
        assert value[0] == pytest.approx(np.sin(np.radians(45.0)), abs=1e-6)

    def test_a_slope_facing_the_sun_is_brighter_than_one_facing_away(self) -> None:
        toward = (-0.6, 0.5, -0.6)
        away = (0.6, 0.5, 0.6)
        lit = hillshade(_normals(toward, away))
        assert lit[0] > lit[1]

    def test_a_slope_in_shadow_is_dark_but_never_negative(self) -> None:
        value = hillshade(_normals((0.9, 0.1, 0.4)), azimuth=315.0, altitude=20.0)
        assert 0.0 <= value[0] < 0.2

    def test_it_answers_one_number_per_normal(self) -> None:
        assert hillshade(_normals(UP, UP, UP)).shape == (3,)

    def test_a_normal_that_is_not_unit_length_is_still_read_right(self) -> None:
        scaled = hillshade(_normals((0.0, 4.0, 0.0)))
        assert scaled[0] == pytest.approx(hillshade(_normals(UP))[0], abs=1e-6)


class TestShadingAGround:
    def _colors(self, count=3):
        return np.tile(np.asarray([[0.4, 0.6, 0.3]], 'f'), (count, 1))

    def test_a_sunlit_face_keeps_more_of_its_colour_than_a_shaded_one(self) -> None:
        colors = self._colors(2)
        normals = _normals((-0.6, 0.5, -0.6), (0.6, 0.5, 0.6))
        shaded = shade_colors(colors, normals)
        assert shaded[0].sum() > shaded[1].sum()

    def test_nothing_goes_black(self) -> None:
        """A map is read, and a valley floor nobody can see is not a map."""
        colors = self._colors(1)
        shaded = shade_colors(colors, _normals((0.7, 0.1, 0.7)))
        assert shaded.min() > 0.0

    def test_nothing_blows_out(self) -> None:
        colors = np.ones((1, 3), 'f')
        shaded = shade_colors(colors, _normals((-0.7, 0.5, -0.5)))
        assert shaded.max() <= 1.0

    def test_the_shape_and_type_are_what_a_mesh_wants(self) -> None:
        shaded = shade_colors(self._colors(5), np.tile(_normals(UP), (5, 1)))
        assert shaded.shape == (5, 3)
        assert shaded.dtype == np.dtype('f')

    def test_colours_with_an_alpha_keep_it(self) -> None:
        colors = np.ones((2, 4), 'f')
        shaded = shade_colors(colors, np.tile(_normals(UP), (2, 1)))
        assert shaded.shape == (2, 4)
        assert np.all(shaded[:, 3] == 1.0)

    def test_more_relief_makes_a_bigger_difference(self) -> None:
        colors = self._colors(2)
        normals = _normals((-0.6, 0.5, -0.6), (0.6, 0.5, 0.6))
        gentle = shade_colors(colors, normals, ambient=0.8)
        strong = shade_colors(colors, normals, ambient=0.1)
        assert (strong[0] - strong[1]).sum() > (gentle[0] - gentle[1]).sum()


class TestExaggeratingTheRelief:
    """Gentle country shaded honestly is a flat green sheet.

    Every printed relief map of lowland steepens the land before it lights it,
    because the eye reads shading as shape and there is nothing to read at a
    one-in-fifty gradient. The exaggeration is in the shading only: the ground
    is drawn at the height it really is.
    """

    def test_it_leans_a_gentle_slope_further_over(self) -> None:
        gentle = _normals((0.05, 1.0, 0.0))
        steeper = steepen(gentle, 4.0)
        assert steeper[0][0] / steeper[0][1] > gentle[0][0] / gentle[0][1]

    def test_flat_ground_stays_flat(self) -> None:
        assert np.allclose(steepen(_normals(UP), 5.0), [[0.0, 1.0, 0.0]],
                           atol=1e-6)

    def test_one_leaves_the_land_as_it_is(self) -> None:
        normals = _normals((0.3, 0.9, -0.2))
        assert np.allclose(steepen(normals, 1.0),
                           normals[0] / np.linalg.norm(normals[0]), atol=1e-6)

    def test_the_result_is_still_unit_length(self) -> None:
        lengths = np.linalg.norm(steepen(_normals((0.2, 0.9, 0.3)), 3.0), axis=1)
        assert np.allclose(lengths, 1.0)

    def test_shading_a_gentle_land_shows_more_of_it(self) -> None:
        colors = np.tile(np.asarray([[0.4, 0.6, 0.3]], 'f'), (2, 1))
        gentle = _normals((-0.04, 1.0, -0.04), (0.04, 1.0, 0.04))
        honest = shade_colors(colors, gentle, exaggeration=1.0)
        leaned = shade_colors(colors, gentle, exaggeration=6.0)
        assert (leaned[0] - leaned[1]).sum() > (honest[0] - honest[1]).sum()

    def test_the_default_shows_relief_in_country_a_road_can_climb(self) -> None:
        """A one-in-twenty slope has to be visible, or the map is a green sheet."""
        colors = np.tile(np.asarray([[0.5, 0.5, 0.5]], 'f'), (2, 1))
        gentle = _normals((-0.05, 1.0, -0.05), (0.05, 1.0, 0.05))
        shaded = shade_colors(colors, gentle)
        assert DEFAULT_EXAGGERATION > 1.0
        assert (shaded[0] - shaded[1])[0] > 0.02
