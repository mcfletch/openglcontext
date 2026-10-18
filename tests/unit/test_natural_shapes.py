"""Stones and timber: closed, outward-facing, varied, and the same for the same generator."""
import numpy as np
import pytest

from OpenGLContext.scenegraph import natural as n


def rng(seed=1):
    return np.random.default_rng(seed)


def valid(geometry):
    count = len(geometry.positions)
    assert geometry.positions.shape == (count, 3) and geometry.normals.shape == (count, 3)
    assert geometry.texcoords.shape == (count, 2) and geometry.tangents.shape == (count, 4)
    assert np.isfinite(geometry.positions).all() and np.isfinite(geometry.texcoords).all()
    assert geometry.indices.max() < count and len(geometry.indices) % 3 == 0
    assert np.allclose(np.linalg.norm(geometry.normals, axis=1), 1.0, atol=1e-3)
    assert np.allclose(np.linalg.norm(geometry.tangents[:, :3], axis=1), 1.0, atol=1e-3)
    assert set(np.unique(geometry.tangents[:, 3])) <= {-1.0, 1.0}


def outward(geometry, centre):
    """The share of triangles that wind counter-clockwise seen from outside."""
    p = geometry.positions[geometry.indices.reshape(-1, 3)].astype(float)
    face = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    away = p.mean(axis=1) - centre
    keep = np.linalg.norm(face, axis=1) > 1e-10
    return float((np.einsum('ij,ij->i', face[keep], away[keep]) > 0).mean())


# -- stone ------------------------------------------------------------------------

@pytest.mark.parametrize('divisions', [1, 2, 3])
def test_a_stone_is_a_valid_mesh_facing_outward(divisions):
    rock = n.stone(rng(), (0.5, 0.35, 0.4), divisions)
    valid(rock)
    assert outward(rock, rock.positions.mean(axis=0)) > 0.97


def test_a_finer_stone_has_more_triangles():
    counts = [len(n.stone(rng(), (1, 1, 1), d).indices) for d in (1, 2, 3)]
    assert counts[0] < counts[1] < counts[2]


def test_a_stone_is_about_the_size_asked_for():
    rock = n.stone(rng(), (0.8, 0.3, 0.5), 3)
    size = np.ptp(rock.positions, axis=0)
    assert 0.6 < size[0] / 1.6 < 1.3 and 0.6 < size[1] / 0.6 < 1.3 and 0.6 < size[2] / 1.0 < 1.3


def test_a_stone_is_the_same_for_the_same_generator_and_different_for_another():
    a, b, other = n.stone(rng(4), (1, 1, 1)), n.stone(rng(4), (1, 1, 1)), n.stone(rng(5), (1, 1, 1))
    assert np.array_equal(a.positions, b.positions)
    assert not np.array_equal(a.positions, other.positions)


def test_stones_are_not_all_the_same_ball():
    radii = []
    for seed in range(6):
        rock = n.stone(rng(seed), (1, 1, 1), 3)
        r = np.linalg.norm(rock.positions - rock.positions.mean(axis=0), axis=1)
        radii.append(r.std() / r.mean())
    assert min(radii) > 0.04


def test_scraping_flattens_some_of_a_sphere_and_leaves_the_rest():
    unit, _ = n._icosphere(3)
    shape = n.scrape(rng(2), unit, 6)
    reach = np.linalg.norm(shape, axis=1)
    assert reach.max() <= 1.0 + 1e-9
    moved = float((reach < 1.0 - 1e-6).mean())
    assert 0.2 < moved < 0.9


def test_each_scrape_leaves_a_flat_face():
    unit, _ = n._icosphere(3)
    one = n.scrape(rng(2), unit, 1)
    moved = np.linalg.norm(one, axis=1) < 1.0 - 1e-6
    direction = (unit[moved] - one[moved])[np.argmax(np.linalg.norm(unit[moved] - one[moved], axis=1))]
    direction /= np.linalg.norm(direction)
    height = one[moved] @ direction
    assert moved.sum() > 20 and np.ptp(height) < 1e-6


def test_the_texture_of_a_stone_keeps_its_scale_on_every_face():
    rock = n.stone(rng(3), (1.0, 1.0, 1.0), 2, repeat=0.5)
    p = rock.positions.astype(float).reshape(-1, 3, 3)
    t = rock.texcoords.astype(float).reshape(-1, 3, 2)
    metres = np.linalg.norm(p[:, 1] - p[:, 0], axis=1)
    repeats = np.linalg.norm(t[:, 1] - t[:, 0], axis=1)
    keep = metres > 0.02
    ratio = repeats[keep] / metres[keep]
    # Projection along an axis shortens an edge by at most the cosine of 55 degrees.
    assert ratio.min() > 0.55 / 0.5 and ratio.max() < 1.01 / 0.5


# -- timber -----------------------------------------------------------------------

def test_a_trunk_is_valid_bark_and_two_ends():
    bark, ends = n.timber(rng(), 2.0, 0.25)
    valid(bark)
    valid(ends)


def test_bark_winds_outward_from_the_axis():
    bark, _ = n.timber(rng(), 2.0, 0.25)
    p = bark.positions[bark.indices.reshape(-1, 3)].astype(float)
    face = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    away = p.mean(axis=1) * np.array([0.0, 1.0, 1.0])
    keep = np.linalg.norm(face, axis=1) > 1e-10
    assert (np.einsum('ij,ij->i', face[keep], away[keep]) > 0).mean() > 0.97


def test_the_ends_face_away_from_the_trunk():
    _, ends = n.timber(rng(), 2.0, 0.25)
    p = ends.positions[ends.indices.reshape(-1, 3)].astype(float)
    face = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    side = np.sign(p.mean(axis=1)[:, 0])
    assert (np.sign(face[:, 0]) == side).all()


def test_a_trunk_lies_along_x_and_is_as_long_and_as_thick_as_asked():
    bark, _ = n.timber(rng(), 2.0, 0.25)
    size = np.ptp(bark.positions, axis=0)
    assert size[0] == pytest.approx(2.0, abs=0.01)
    assert 0.4 < size[2] < 0.7


def test_a_trunk_is_not_a_cylinder():
    bark, _ = n.timber(rng(), 2.0, 0.25)
    p = bark.positions.astype(float)
    spread = np.hypot(p[:, 1] - np.median(p[:, 1]), p[:, 2] - np.median(p[:, 2]))
    assert spread.std() / spread.mean() > 0.05


def test_a_trunk_is_the_same_for_the_same_generator():
    a, b = n.timber(rng(8), 1.5, 0.2), n.timber(rng(8), 1.5, 0.2)
    assert np.array_equal(a[0].positions, b[0].positions)
    assert np.array_equal(a[1].positions, b[1].positions)


def test_bark_is_textured_at_the_scale_asked_for_and_the_ends_with_one_picture():
    bark, ends = n.timber(rng(), 2.0, 0.25, repeat=0.5)
    assert np.ptp(bark.texcoords[:, 1]) == pytest.approx(2.0 / 0.5, rel=0.02)
    assert np.ptp(bark.texcoords[:, 0]) == pytest.approx(2 * np.pi * 0.25 / 0.5, rel=0.02)
    assert ends.texcoords.min() >= -0.01 and ends.texcoords.max() <= 1.01


# -- rubble wall ---------------------------------------------------------------------

def wall_line(count=60, length=15.0):
    z = -np.linspace(0.0, length, count)
    return np.stack([np.zeros(count), 0.05 * np.sin(z), z], axis=1)


def test_a_rubble_wall_is_valid_and_faces_outward_from_its_axis():
    line = wall_line()
    wall = n.rubble(rng(), line, 0.14, 0.7)
    valid(wall)
    p = wall.positions[wall.indices.reshape(-1, 3)].astype(float)
    face = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    centre = p.mean(axis=1)
    axis = centre.copy()
    axis[:, 0] = 0.0
    axis[:, 1] = 0.05 * np.sin(centre[:, 2]) + 0.175
    keep = np.linalg.norm(face, axis=1) > 1e-10
    assert (np.einsum('ij,ij->i', face[keep], (centre - axis)[keep]) > 0).mean() > 0.95


def test_a_rubble_wall_runs_the_length_of_its_line_as_high_and_as_wide_as_asked():
    wall = n.rubble(rng(), wall_line(), 0.14, 0.7)
    z = wall.positions[:, 2]
    assert (z.min(), z.max()) == pytest.approx((-15.0, 0.0), abs=1e-4)
    assert 0.6 < wall.positions[:, 1].max() < 0.95
    assert np.ptp(wall.positions[:, 0]) < 0.35
    assert wall.positions[:, 1].min() < -0.2


def test_the_two_faces_of_a_rubble_wall_are_not_flat_or_alike():
    wall = n.rubble(rng(), wall_line(), 0.14, 0.7)
    p = wall.positions.astype(float).reshape(60, 11, 3)
    left, right = p[:, 2, 0], p[:, 8, 0]
    assert left.std() > 0.01 and right.std() > 0.01
    assert not np.allclose(left, -right, atol=0.01)


def test_a_rubble_wall_ends_closed():
    wall = n.rubble(rng(), wall_line(), 0.14, 0.7)
    p = wall.positions.astype(float).reshape(60, 11, 3)
    assert np.ptp(p[0, :, 0]) < 0.02 and np.ptp(p[-1, :, 0]) < 0.02
