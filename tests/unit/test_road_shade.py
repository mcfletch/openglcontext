"""A road carries the shade it runs through.

A forest road drawn at full sun with everything beside it in deep shade reads
as a lit strip laid over a photograph of a wood. The tarmac is shaded the same
way the ground and the plants are -- the trees have been cleared out of the
corridor, so what falls across it is what the canopy either side leans over, and
the places the sun does reach are the ones where the trees open or the alignment
turns to face it.

It is written into the mesh's vertex colours rather than lit at runtime: the
trees do not move and neither does the sun.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.road import RoadProfile, road_mesh

PROFILE = RoadProfile(lane_width=3.6, lanes=2)


def _line(count=21, length=200.0):
    z = np.linspace(0.0, length, count)
    return np.stack([np.zeros(count), np.zeros(count), z], axis=-1)


class TestWhatIsWritten:
    def test_a_road_told_nothing_carries_no_colours(self) -> None:
        assert road_mesh(_line(), PROFILE).colors is None

    def test_a_shaded_road_carries_one_per_vertex(self) -> None:
        mesh = road_mesh(_line(), PROFILE, shade=np.full(21, 0.4))
        assert len(mesh.colors) == len(mesh.positions)

    def test_the_shade_is_what_it_was_given(self) -> None:
        mesh = road_mesh(_line(), PROFILE, shade=np.full(21, 0.4))
        assert np.allclose(mesh.colors[:, :3], 0.4)

    def test_it_is_opaque(self) -> None:
        mesh = road_mesh(_line(), PROFILE, shade=np.full(21, 0.4))
        assert np.allclose(mesh.colors[:, 3], 1.0)

    def test_it_follows_the_road_along_its_length(self) -> None:
        along = np.linspace(0.2, 1.0, 21)
        mesh = road_mesh(_line(), PROFILE, shade=along)
        far = mesh.positions[:, 2] > 150.0
        near = mesh.positions[:, 2] < 50.0
        assert float(mesh.colors[near, 0].mean()) \
            < float(mesh.colors[far, 0].mean())

    def test_the_whole_cut_at_one_point_shares_it(self) -> None:
        """A road four metres wide is one place as far as the canopy goes."""
        mesh = road_mesh(_line(count=3), PROFILE, shade=np.array([0.2, 0.5, 0.9]))
        ring = len(mesh.positions) // 3
        assert np.allclose(mesh.colors[:ring, 0], 0.2)

    def test_a_wrong_length_is_reported(self) -> None:
        with pytest.raises(ValueError):
            road_mesh(_line(), PROFILE, shade=np.ones(4))

    def test_it_survives_re_sampling(self) -> None:
        """The shade is given per written point, so it is applied after."""
        mesh = road_mesh(_line(), PROFILE, spacing=25.0,
                         shade=lambda points: np.full(len(points), 0.3))
        assert np.allclose(mesh.colors[:, :3], 0.3)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
