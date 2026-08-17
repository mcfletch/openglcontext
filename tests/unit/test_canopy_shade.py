"""How dark it is under the trees, and who else gets to read that.

The shade a wood casts on its own floor is baked once into the terrain rather
than traced per frame: the trees do not move and neither does the sun. What
makes it read as a wood is *depth* -- the floor under a closed canopy is a
fraction as bright as the clearing beside it, and the places the sun does reach
are the ones the canopy happens to leave open.

A tree shades the ground its crown covers, not the pixel its trunk stands in, so
the density is spread over the crown before it darkens anything. Everything else
standing on that ground -- the grass, the cover, whatever a game adds -- reads
the same figure through :meth:`SplatTerrain.shade`.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain.heightfield import HeightField
from OpenGLContext.scenegraph.terrain.splat import SplatTerrain

EXTENT = 512.0
SUN = (-0.5, -0.72, -0.48)


def _field(res=129):
    return HeightField(np.zeros((res, res)), EXTENT, 1.0)


def _stand(count=900, radius=60.0, seed=3):
    """A dense round stand of trees at the origin."""
    rng = np.random.default_rng(seed)
    angle = rng.random(count) * 2.0 * np.pi
    at = np.sqrt(rng.random(count)) * radius
    return np.stack([np.cos(angle) * at, np.zeros(count),
                     np.sin(angle) * at], axis=-1)


class TestHowDeepItGoes:
    def _lit(self, **named):
        field = _field()
        return field.canopy_shadow(np.ones((129, 129), 'f4'), _stand(),
                                   SUN, **named)

    def test_the_floor_of_a_stand_is_deep_in_shade(self) -> None:
        lit = self._lit(crown=8.0, darken=1.15, cap=0.74)
        assert float(lit[64, 64]) < 0.4

    def test_the_open_ground_beside_it_is_not(self) -> None:
        lit = self._lit(crown=8.0)
        assert float(lit[4, 4]) > 0.9

    def test_a_wider_crown_shades_more_ground(self) -> None:
        narrow = self._lit(crown=3.0)
        wide = self._lit(crown=12.0)
        assert float((wide < 0.8).sum()) > float((narrow < 0.8).sum())

    def test_it_never_goes_past_the_cap(self) -> None:
        lit = self._lit(crown=10.0, darken=4.0, cap=0.6)
        assert float(lit.min()) == pytest.approx(0.4, abs=0.01)

    def test_a_wood_of_no_trees_shades_nothing(self) -> None:
        lit = _field().canopy_shadow(np.ones((129, 129), 'f4'),
                                     np.zeros((0, 3)), SUN, crown=8.0)
        assert float(lit.min()) == 1.0

    def test_the_shade_falls_away_from_the_sun(self) -> None:
        """A tree shades along the light, not straight down."""
        one = np.zeros((1, 3))
        lit = _field().canopy_shadow(np.ones((129, 129), 'f4'), one, SUN,
                                     crown=6.0, spread=40.0)
        assert int(np.argmin(lit)) != 64 * 129 + 64


class TestWhoElseCanReadIt:
    def _terrain(self):
        return SplatTerrain(_field(), ['grass'], control=None,
                            canopy=_stand(), sun=SUN,
                            material_fn=lambda name, res: {'color': name})

    def test_a_terrain_says_how_lit_each_place_is(self) -> None:
        assert self._terrain().shading.shape == (129, 129)

    def test_it_is_asked_by_world_position(self) -> None:
        terrain = self._terrain()
        under = terrain.shade(np.array([0.0]), np.array([0.0]))
        beside = terrain.shade(np.array([-240.0]), np.array([-240.0]))
        assert float(under[0]) < float(beside[0])

    def test_it_is_in_range(self) -> None:
        found = self._terrain().shade(np.linspace(-250.0, 250.0, 40),
                                      np.zeros(40))
        assert float(found.min()) >= 0.0 and float(found.max()) <= 1.0

    def test_it_is_worked_out_once(self) -> None:
        terrain = self._terrain()
        assert terrain.shading is terrain.shading

    def test_a_terrain_with_no_trees_is_lit_by_the_land_alone(self) -> None:
        bare = SplatTerrain(_field(), ['grass'], control=None, sun=SUN,
                            material_fn=lambda name, res: {'color': name})
        assert float(bare.shading.min()) > 0.99


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
