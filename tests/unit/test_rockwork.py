"""Rock cut into a mesh: refinement that leaves no cracks, and scrapes that only go into the rock."""
import numpy as np
import pytest

from OpenGLContext.scenegraph import rockwork as rw


def grid(n=12, size=6.0):
    """A square of ``n`` by ``n`` quads in the XY plane, facing +Z (the open side), as triangles."""
    xs = np.linspace(0.0, size, n + 1)
    x, y = np.meshgrid(xs, xs)
    points = np.stack([x.ravel(), y.ravel(), np.zeros(x.size)], axis=1)
    j, i = np.meshgrid(np.arange(n), np.arange(n), indexing='ij')
    a = (j * (n + 1) + i).ravel()
    b, below = a + 1, a + n + 1
    return points, np.stack([a, b, below, b, below + 1, below], axis=1).reshape(-1, 3)


def area(points, triangles):
    c = points[triangles]
    return 0.5 * np.linalg.norm(np.cross(c[:, 1] - c[:, 0], c[:, 2] - c[:, 0]), axis=1)


def edge_use(triangles):
    edges = np.sort(np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]),
                    axis=1)
    keys, counts = np.unique(edges, axis=0, return_counts=True)
    return dict(zip(map(tuple, keys), counts, strict=True))


class TestSplittingEdges:
    @pytest.mark.parametrize('rule', [
        lambda a, b: np.ones(len(a), bool),
        lambda a, b: (a[:, 0] + b[:, 0]) / 2 < 3.0,
        lambda a, b: np.arange(len(a)) % 5 == 0,
        lambda a, b: np.arange(len(a)) % 2 == 0,
    ], ids=['all', 'a half of the square', 'one in five', 'alternate'])
    def test_the_surface_stays_whole_and_no_edge_is_cracked(self, rule):
        points, triangles = grid()
        before = area(points, triangles).sum()
        new_points, new_triangles, parents = rw.split_edges(points, triangles, rule)
        assert area(new_points, new_triangles).sum() == pytest.approx(before)
        assert len(new_points) == len(points) + len(parents)
        use = edge_use(new_triangles)
        assert set(use.values()) <= {1, 2}
        boundary = sum(1 for v in use.values() if v == 1)
        assert boundary == 4 * 12 + (len(parents) and sum(
            1 for p in parents if _on_the_border(points[p[0]], points[p[1]])))

    def test_edges_between_fixed_vertices_and_protected_edges_are_not_split(self):
        points, triangles = grid(4, 4.0)
        fixed = points[:, 1] == 0.0
        every = lambda a, b: np.ones(len(a), bool)  # noqa: E731 a rule that chooses every edge
        _p, new, parents = rw.split_edges(points, triangles, every, fixed=fixed)
        edges = {tuple(sorted(e)) for tri in new for e in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0]))}
        top = [i for i in range(len(points)) if fixed[i]]
        assert all((a, b) in edges for a, b in zip(top[:-1], top[1:], strict=True))
        assert not any(set(p) <= set(top) for p in parents.tolist())
        _p, new, parents = rw.split_edges(points, triangles, every, protected=np.array([[0, 1]]))
        assert not any(sorted(p) == [0, 1] for p in parents.tolist())

    def test_windings_are_kept(self):
        points, triangles = grid()
        _p, new_triangles, _parents = rw.split_edges(
            points, triangles, lambda a, b: np.arange(len(a)) % 3 == 0)
        assert np.all(rw.face_normals(_p, new_triangles)[:, 2] > 0.99)

    def test_nothing_chosen_changes_nothing(self):
        points, triangles = grid()
        new_points, new_triangles, parents = rw.split_edges(
            points, triangles, lambda a, b: np.zeros(len(a), bool))
        assert len(parents) == 0 and np.array_equal(new_triangles, triangles)
        assert np.array_equal(new_points, points)

    def test_every_edge_split_gives_four_triangles_for_one(self):
        points, triangles = grid(3)
        _p, new_triangles, _parents = rw.split_edges(
            points, triangles, lambda a, b: np.ones(len(a), bool))
        assert len(new_triangles) == 4 * len(triangles)

    def test_new_points_are_the_middles_of_their_parents(self):
        points, triangles = grid()
        new_points, _t, parents = rw.split_edges(points, triangles,
                                                 lambda a, b: np.arange(len(a)) % 4 == 0)
        middles = (points[parents[:, 0]] + points[parents[:, 1]]) / 2.0
        assert np.allclose(new_points[len(points):], middles)
        values = np.arange(len(points), dtype=float)[:, None]
        got = rw.interpolated(values, parents)
        assert np.allclose(got[len(points):, 0], (parents[:, 0] + parents[:, 1]) / 2.0)


def _on_the_border(a, b):
    edge = 6.0
    return (a[0] == b[0] and a[0] in (0.0, edge)) or (a[1] == b[1] and a[1] in (0.0, edge))


class TestScraping:
    PASSES = (rw.Pass((1.2, 2.0), (0.2, 0.5), 0.12), rw.Pass((0.4, 0.8), (0.15, 0.4), 0.5))

    def scraped(self, seed=1, **named):
        points, triangles = grid(24, 12.0)
        return points, triangles, rw.scrape(points, triangles, np.random.default_rng(seed),
                                            self.PASSES, **named)

    def test_every_cut_goes_into_the_rock_and_none_toward_the_open(self):
        _p, _t, (points, _tri, _pin) = self.scraped()
        assert points[:, 2].max() <= 1e-9
        assert points[:, 2].min() < -0.15

    def test_the_surface_is_cut_in_facets_with_steps_at_their_rims(self):
        _p, _t, (points, triangles, _pin) = self.scraped()
        floor = points[:, 2][np.abs(points[:, 2]) > 0.1]
        assert len(floor) > 50
        assert len(points) > 25 * 25      # refined about the rims

    def test_the_mesh_stays_whole(self):
        _p, _t, (points, triangles, _pin) = self.scraped()
        use = edge_use(triangles)
        assert set(use.values()) <= {1, 2}
        assert sum(1 for v in use.values() if v == 1) <= 4 * 24 * 2 ** rw.MAX_SPLITS * len(self.PASSES)

    def test_pinned_points_do_not_move_and_the_cut_comes_in_gradually(self):
        points, triangles = grid(24, 12.0)
        pinned = np.zeros(len(points), bool)
        pinned[points[:, 0] < 0.01] = True
        new, _tri, pin = rw.scrape(points, triangles, np.random.default_rng(2), self.PASSES,
                                   pinned=pinned, ramp=1.0)
        first = new[: len(points)]
        assert np.array_equal(first[pinned], points[pinned])
        assert pin[: len(points)][pinned].all()
        near = (new[:, 0] > 0.01) & (new[:, 0] < 0.15)
        assert np.abs(new[near, 2]).max() < 0.2

    def test_nothing_is_cut_near_a_place_kept_clear(self):
        keep = np.array([[6.0, 6.0, 0.0]])
        _p, _t, (points, _tri, _pin) = self.scraped(keep_clear=keep)
        near = np.linalg.norm(points - keep[0], axis=1) < 0.4
        assert near.any() and np.abs(points[near, 2]).max() < 0.05

    def test_the_same_generator_cuts_the_same_rock(self):
        a = self.scraped(seed=7)[2]
        b = self.scraped(seed=7)[2]
        c = self.scraped(seed=8)[2]
        assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])
        assert a[0].shape != c[0].shape or not np.allclose(a[0], c[0])

    def test_a_pit_is_deeper_than_a_facet(self):
        points, triangles = grid(24, 12.0)
        pits = (rw.Pass((0.3, 0.5), (0.8, 1.0), 0.3),)
        new, _tri, _pin = rw.scrape(points, triangles, np.random.default_rng(3), pits)
        assert new[:, 2].min() < -0.7


def test_grain_never_brings_the_surface_nearer_the_open():
    points, triangles = grid(10, 6.0)
    rough = rw.grain(points, triangles, np.random.default_rng(1), 0.1,
                     lambda rng, p: rng.random(len(p)))
    assert rough[:, 2].max() <= 1e-9 and rough[:, 2].min() < -0.02
    assert np.allclose(rough[:, :2], points[:, :2])
