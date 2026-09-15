"""How closed the canopy is, as a thing the ground can be asked (no GL).

The shading a wood casts on its own floor is *clamped* -- past a certain density
more trees cannot take more light, which is right for lighting and useless for
deciding what grows. A shrub does not care how dark it is so much as how much
room there is: a stand with gaps has shrubs in it and a closed one does not, and
both are at the bottom of the shading's range.

So the closure itself is readable, unclamped: 0 is open ground and 1 is one
tree's crown over every square metre.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain import (
    HeightField,
    LayerRule,
    SplatTerrain,
    control_map,
)


def _ground(res=129, extent=512.0):
    return HeightField(np.zeros((res, res)), extent, 1.0)


def _stand(centre, count, spread, seed=3):
    """A clump of trunks about ``centre``."""
    rng = np.random.default_rng(seed)
    x, z = centre
    return np.stack([
        rng.normal(x, spread, count),
        np.zeros(count),
        rng.normal(z, spread, count)], 1)


def _terrain(trees=None, **named):
    field = _ground()
    named.setdefault('canopy_crown', 8.0)
    control = control_map(field, [LayerRule()], size=32)
    return SplatTerrain(field, ['grass'], control, canopy=trees, **named)


class TestReadingHowClosedTheCanopyIs:
    def test_open_ground_has_none(self) -> None:
        terrain = _terrain(_stand((-200.0, -200.0), 200, 6.0))
        assert float(terrain.canopy_cover(np.array([180.0]),
                                          np.array([180.0]))[0]) < 0.05

    def test_under_a_stand_there_is_some(self) -> None:
        terrain = _terrain(_stand((0.0, 0.0), 200, 6.0))
        assert float(terrain.canopy_cover(np.array([0.0]),
                                          np.array([0.0]))[0]) > 0.5

    def test_a_denser_stand_reads_denser(self) -> None:
        """Which the shading cannot say: both are at the bottom of its range."""
        thin = _terrain(_stand((0.0, 0.0), 60, 9.0))
        thick = _terrain(_stand((0.0, 0.0), 600, 9.0))
        at = (np.array([0.0]), np.array([0.0]))
        assert float(thick.canopy_cover(*at)[0]) \
            > 3 * float(thin.canopy_cover(*at)[0])

    def test_the_shading_cannot_tell_them_apart(self) -> None:
        """The reason this exists at all: past the cap, more trees take no more
        light, so a sparse stand and a thicket shade the floor the same."""
        thin = _terrain(_stand((0.0, 0.0), 200, 9.0))
        thick = _terrain(_stand((0.0, 0.0), 900, 9.0))
        at = (np.array([0.0]), np.array([0.0]))
        assert float(thin.shade(*at)[0]) \
            == pytest.approx(float(thick.shade(*at)[0]), abs=0.02)

    def test_it_falls_away_from_a_stand(self) -> None:
        terrain = _terrain(_stand((0.0, 0.0), 400, 10.0))
        across = np.array([0.0, 20.0, 60.0, 150.0])
        cover = terrain.canopy_cover(across, np.zeros(4))
        assert list(cover) == sorted(cover, reverse=True)

    def test_a_wood_with_no_trees_is_open_everywhere(self) -> None:
        terrain = _terrain(None)
        assert not float(terrain.canopy_cover(np.array([0.0]),
                                              np.array([0.0]))[0])

    def test_it_reads_by_world_position_like_the_shading_does(self) -> None:
        terrain = _terrain(_stand((120.0, -80.0), 300, 7.0))
        here = float(terrain.canopy_cover(np.array([120.0]),
                                          np.array([-80.0]))[0])
        there = float(terrain.canopy_cover(np.array([-120.0]),
                                           np.array([80.0]))[0])
        assert here > 0.4 > there


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
