"""A navigation mesh built from a collision mesh, and paths across it.

**Generated rather than baked.** The original engines shipped pre-computed
navigation data beside their maps; we have something better at load time — the
collision mesh itself, in memory — so the mesh is built from the geometry a
character actually walks on. That gives navigation for maps nobody ever baked,
regeneration when geometry changes, and no dependence on content we may not
read.

Everything here is data: triangles in, cells and a path out. So a whole
navmesh can be built and searched against a floor written in five lines, which
is what makes this testable at all — a navmesh debugged by watching a bot walk
into a wall is a navmesh debugged very slowly.
"""
import math

import numpy as np
import pytest

from OpenGLContext.nav import navmesh


def grid(size=6, spacing=1.0, height=0.0, hole=()):
    """A flat floor of ``size``x``size`` quads, optionally with squares missing."""
    points, triangles = [], []
    index = {}
    for row in range(size + 1):
        for col in range(size + 1):
            index[(row, col)] = len(points)
            points.append((col * spacing, height, row * spacing))
    for row in range(size):
        for col in range(size):
            if (row, col) in hole:
                continue
            a = index[(row, col)]
            b = index[(row, col + 1)]
            c = index[(row + 1, col + 1)]
            d = index[(row + 1, col)]
            # Wound so the normal points *up*: a floor, not a ceiling.
            triangles.append((a, c, b))
            triangles.append((a, d, c))
    return (np.array(points, dtype='d'), np.array(triangles, dtype='i'))


def ramp(size=6, spacing=1.0, rise=0.3):
    """A floor that climbs steadily along +z."""
    points, triangles = [], []
    index = {}
    for row in range(size + 1):
        for col in range(size + 1):
            index[(row, col)] = len(points)
            points.append((col * spacing, row * rise, row * spacing))
    for row in range(size):
        for col in range(size):
            a, b = index[(row, col)], index[(row, col + 1)]
            c, d = index[(row + 1, col + 1)], index[(row + 1, col)]
            triangles.extend([(a, c, b), (a, d, c)])
    return (np.array(points, dtype='d'), np.array(triangles, dtype='i'))


def wall(x=3.0, height=3.0, span=6.0):
    """A vertical face across the floor: not walkable, and a barrier."""
    points = np.array([(x, 0.0, 0.0), (x, height, 0.0),
                       (x, height, span), (x, 0.0, span)], dtype='d')
    return (points, np.array([(0, 1, 2), (0, 2, 3)], dtype='i'))


def joined(*meshes):
    """Several ``(points, triangles)`` as one."""
    points, triangles, offset = [], [], 0
    for part_points, part_triangles in meshes:
        points.append(part_points)
        triangles.append(np.asarray(part_triangles) + offset)
        offset += len(part_points)
    return (np.vstack(points), np.vstack(triangles))


class TestWhatCountsAsWalkable:

    def test_a_flat_floor_is_all_walkable(self):
        mesh = navmesh.build(*grid())
        assert len(mesh) == 72                  # two triangles per quad

    def test_a_wall_is_not(self):
        """The test that decides whether a bot tries to walk up the scenery."""
        mesh = navmesh.build(*wall())
        assert len(mesh) == 0

    def test_a_gentle_ramp_is(self):
        assert len(navmesh.build(*ramp(rise=0.2))) > 0

    def test_a_ramp_steeper_than_the_limit_is_not(self):
        assert len(navmesh.build(*ramp(rise=4.0))) == 0

    def test_the_slope_limit_is_the_characters_own(self):
        """A mesh built for one body is wrong for another; it is a parameter."""
        points, triangles = ramp(rise=1.2)      # about 50 degrees
        assert len(navmesh.build(points, triangles, max_slope=60.0)) > 0
        assert len(navmesh.build(points, triangles, max_slope=30.0)) == 0

    def test_a_ceiling_is_not_walkable_however_flat(self):
        """A downward-facing surface is a ceiling, and nobody walks on one."""
        points, triangles = grid(size=2)
        flipped = triangles[:, ::-1].copy()     # wound the other way
        assert len(navmesh.build(points, flipped)) == 0

    def test_a_mesh_with_no_triangles_builds_an_empty_navmesh(self):
        empty = navmesh.build(np.zeros((0, 3)), np.zeros((0, 3), dtype='i'))
        assert len(empty) == 0


class TestWhereYouAre:

    def test_a_point_over_the_floor_finds_its_cell(self):
        mesh = navmesh.build(*grid())
        assert mesh.cell_at((2.5, 0.0, 2.5)) is not None

    def test_a_point_off_the_floor_finds_none(self):
        mesh = navmesh.build(*grid())
        assert mesh.cell_at((99.0, 0.0, 99.0)) is None

    def test_the_cell_found_is_the_one_underneath(self):
        """Height decides between two floors stacked over each other."""
        lower = grid(size=4, height=0.0)
        upper = grid(size=4, height=4.0)
        mesh = navmesh.build(*joined(lower, upper))
        low = mesh.cell_at((1.5, 0.1, 1.5))
        high = mesh.cell_at((1.5, 4.1, 1.5))
        assert low is not None and high is not None
        assert low != high

    def test_a_point_far_above_everything_finds_nothing(self):
        mesh = navmesh.build(*grid())
        assert mesh.cell_at((2.5, 50.0, 2.5)) is None


class TestFindingAPath:

    def test_a_path_across_open_floor_is_found(self):
        mesh = navmesh.build(*grid())
        path = mesh.path((0.5, 0.0, 0.5), (5.5, 0.0, 5.5))
        assert path

    def test_the_path_starts_and_ends_where_it_was_asked_to(self):
        mesh = navmesh.build(*grid())
        path = mesh.path((0.5, 0.0, 0.5), (5.5, 0.0, 5.5))
        assert np.allclose(path[0][::2], (0.5, 0.5), atol=1e-6)
        assert np.allclose(path[-1][::2], (5.5, 5.5), atol=1e-6)

    def test_an_open_floor_gives_a_straight_line(self):
        """String-pulled: a path that followed cell centres would zigzag.

        A bot walking the staircase of triangle centres across an empty room
        looks drunk, and every corner it rounds is a corner it did not need.
        """
        mesh = navmesh.build(*grid())
        path = mesh.path((0.5, 0.0, 0.5), (5.5, 0.0, 5.5))
        assert len(path) == 2

    def test_a_path_round_an_obstacle_bends_round_it(self):
        """The test that says a wall is a wall.

        A wall contributes no walkable triangles of its own, so without the
        headroom test the floor either side of it is joined straight through
        and a bot walks into the scenery.  The gap is two cells wide, because
        the cells immediately against a wall are removed too — a body has a
        radius and cannot stand there.
        """
        floor = grid(size=6)
        blocked = joined(floor, wall(x=3.0, span=4.0))
        # The headroom test is off by default -- it is too blunt for a real
        # level, see DEFAULT_CLEARANCE -- so this asks for it explicitly.
        mesh = navmesh.build(*blocked, clearance=1.8)
        assert len(mesh) < len(navmesh.build(*floor, clearance=1.8))
        path = mesh.path((1.0, 0.0, 1.0), (5.0, 0.0, 1.0))
        assert path
        assert len(path) > 2                    # it had to go round
        assert max(float(point[2]) for point in path) > 4.0   # via the gap

    def test_a_path_to_somewhere_unreachable_is_no_path(self):
        left = grid(size=2, spacing=1.0)
        right = (np.array([(50.0, 0.0, 0.0), (52.0, 0.0, 0.0),
                           (52.0, 0.0, 2.0), (50.0, 0.0, 2.0)], dtype='d'),
                 np.array([(0, 2, 1), (0, 3, 2)], dtype='i'))
        mesh = navmesh.build(*joined(left, right))
        assert mesh.path((0.5, 0.0, 0.5), (51.0, 0.0, 1.0)) == []

    def test_a_path_from_off_the_mesh_is_no_path(self):
        mesh = navmesh.build(*grid())
        assert mesh.path((99.0, 0.0, 99.0), (1.0, 0.0, 1.0)) == []

    def test_a_path_to_where_you_already_are_is_that_point(self):
        mesh = navmesh.build(*grid())
        path = mesh.path((2.5, 0.0, 2.5), (2.5, 0.0, 2.5))
        assert len(path) == 1

    def test_a_path_climbs_a_ramp(self):
        mesh = navmesh.build(*ramp(rise=0.25))
        path = mesh.path((2.5, 0.0, 0.5), (2.5, 1.25, 5.5))
        assert path
        assert path[-1][1] > path[0][1]

    def test_the_path_is_no_longer_than_it_has_to_be(self):
        """A* rather than a flood fill: the route across a room is the room."""
        mesh = navmesh.build(*grid(size=10))
        path = mesh.path((0.5, 0.0, 0.5), (9.5, 0.0, 9.5))
        length = sum(float(np.linalg.norm(np.asarray(b) - np.asarray(a)))
                     for a, b in zip(path, path[1:], strict=False))
        straight = math.hypot(9.0, 9.0)
        assert length == pytest.approx(straight, rel=0.05)


class TestSomewhereToGo:

    def test_a_random_point_is_on_the_mesh(self):
        """What a bot with nothing better to do walks toward."""
        mesh = navmesh.build(*grid())
        for seed in range(10):
            point = mesh.random_point(seed=seed)
            assert mesh.cell_at(point) is not None

    def test_an_empty_mesh_has_nowhere_to_go(self):
        mesh = navmesh.build(np.zeros((0, 3)), np.zeros((0, 3), dtype='i'))
        assert mesh.random_point(seed=1) is None

    def test_the_same_seed_gives_the_same_point(self):
        mesh = navmesh.build(*grid())
        assert mesh.random_point(seed=3) == mesh.random_point(seed=3)


class TestBuildingItFromAWorld:
    """The seam a game actually uses: a physics world in, a navmesh out."""

    def test_a_world_with_a_floor_gives_a_navmesh(self):
        from omi_physics import model
        from omi_physics.world import PhysicsWorld

        world = PhysicsWorld(gravity=model.Gravity(gravity=9.81,
                                                   direction=(0, -1, 0)))
        points, triangles = grid()
        shape = world.add_shape(model.Shape.trimesh(points, triangles))
        world.add_body(model.Motion(type=model.STATIC),
                       collider=model.Collider(shape=shape), position=(0, 0, 0))
        assert len(navmesh.from_world(world)) > 0

    def test_a_world_with_nothing_static_gives_an_empty_one(self):
        from omi_physics import model
        from omi_physics.world import PhysicsWorld

        world = PhysicsWorld(gravity=model.Gravity(gravity=9.81,
                                                   direction=(0, -1, 0)))
        assert len(navmesh.from_world(world)) == 0
