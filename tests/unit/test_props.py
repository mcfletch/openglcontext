"""Things standing in a world that a car can hit.

A world has more in it than ground, road and trees: boulders on the verge, a
car that broke down, whatever a game puts in the way. What they have in common
is that they are *placed* -- a mesh and a body at one spot, neither of which
moves -- and that is the thing an engine can own. What each one looks like is
art, and the only kind generated here is the one a landscape supplies for free.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.props import (
    Prop,
    RockProfile,
    rock_material,
    rock_mesh,
)


class TestARock:
    def test_it_is_a_closed_solid(self) -> None:
        mesh = rock_mesh()
        assert len(mesh.positions) and len(mesh.indices) % 3 == 0
        assert len(mesh.normals) == len(mesh.positions)

    def test_it_sits_on_the_ground(self) -> None:
        assert float(rock_mesh().positions[:, 1].min()) \
            == pytest.approx(0.0, abs=1e-5)

    def test_it_is_the_size_it_was_asked_for(self) -> None:
        mesh = rock_mesh(radius=2.0)
        assert 3.0 < float(np.ptp(mesh.positions[:, 0])) < 5.0

    def test_it_is_wider_than_it_is_tall(self) -> None:
        """A boulder that has been lying there is settled into the ground."""
        mesh = rock_mesh()
        assert float(mesh.positions[:, 1].max()) \
            < float(np.ptp(mesh.positions[:, 0]))

    def test_two_seeds_are_two_rocks(self) -> None:
        assert not np.allclose(rock_mesh(seed=1).positions,
                               rock_mesh(seed=2).positions)

    def test_the_same_seed_is_the_same_rock(self) -> None:
        assert np.allclose(rock_mesh(seed=3).positions,
                           rock_mesh(seed=3).positions)

    def test_it_is_not_a_sphere(self) -> None:
        mesh = rock_mesh(radius=1.0, seed=4)
        centre = np.array([0.0, float(mesh.positions[:, 1].max()) / 2.0, 0.0])
        reach = np.linalg.norm(mesh.positions - centre, axis=1)
        assert float(reach.std()) > 0.05

    def test_a_smoother_profile_is_rounder(self) -> None:
        def lumpiness(profile):
            mesh = rock_mesh(seed=5, profile=profile)
            reach = np.linalg.norm(mesh.positions, axis=1)
            return float(reach.std())
        assert lumpiness(RockProfile(roughness=0.05)) \
            < lumpiness(RockProfile(roughness=0.5))

    def test_it_is_stone_rather_than_a_mirror(self) -> None:
        assert rock_material().metallic == 0.0


class TestWhatAPropCarries:
    def test_it_knows_where_it_is_and_which_way(self) -> None:
        one = Prop(kind='rock', position=(3.0, 1.0, -4.0), yaw=0.5, scale=1.5)
        assert tuple(one.position) == (3.0, 1.0, -4.0)
        assert one.yaw == 0.5 and one.scale == 1.5

    def test_it_survives_a_round_trip_through_json(self) -> None:
        import json
        one = Prop(kind='rock', position=(1.0, 2.0, 3.0), yaw=0.25, scale=0.8,
                   radius=1.2, height=1.6)
        assert Prop.from_json(json.loads(json.dumps(one.to_json()))) == one

    def test_it_reads_as_what_it_is(self) -> None:
        assert 'rock' in repr(Prop(kind='rock', position=(0.0, 0.0, 0.0)))

    def test_a_prop_measures_itself_from_its_mesh(self) -> None:
        one = Prop.of(rock_mesh(radius=1.5), kind='rock',
                      position=(0.0, 0.0, 0.0))
        assert 1.0 < one.radius < 2.5
        assert 0.4 < one.height < 3.0

    def test_scaling_it_scales_what_it_takes_up(self) -> None:
        mesh = rock_mesh(radius=1.0)
        plain = Prop.of(mesh, kind='rock', position=(0.0, 0.0, 0.0))
        big = Prop.of(mesh, kind='rock', position=(0.0, 0.0, 0.0), scale=3.0)
        assert float(big.radius) == pytest.approx(plain.radius * 3.0, rel=1e-6)
        assert float(big.height) == pytest.approx(plain.height * 3.0, rel=1e-6)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
