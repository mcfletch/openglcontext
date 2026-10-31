"""Triangles cooked into collision shapes: hulls, convex pieces and their volumes."""
from __future__ import annotations

import numpy as np
import pytest

from OpenGLContext.physics import cooking
from OpenGLContext.physics.proxy import Proxy

CUBE = np.array([(x, y, z) for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)])
#: An L of two 10 m bars: its hull leaves half its bounds empty.
ELL = np.concatenate([CUBE * (10.0, 1.0, 1.0), CUBE * (1.0, 10.0, 1.0)])


def test_a_cubes_hull_is_its_corners_with_twelve_outward_triangles() -> None:
    vertices, faces = cooking.convex_hull(np.concatenate([CUBE, [(0.5, 0.5, 0.5)]]))
    assert len(vertices) == 8 and len(faces) == 12
    centre = vertices.mean(axis=0)
    for face in faces:
        a, b, c = vertices[face]
        assert np.dot(np.cross(b - a, c - a), a - centre) > 0.0
    assert cooking.hull_volume(vertices, faces) == pytest.approx(1.0)


@pytest.mark.parametrize('points', [CUBE[:3], np.zeros((5, 3)), CUBE[[0, 2, 4, 6]]])
def test_points_with_no_volume_have_no_hull(points: np.ndarray) -> None:
    vertices, faces = cooking.convex_hull(points)
    assert len(faces) == 0
    assert cooking.concavity(points) == 0.0


def test_a_hulls_volume_or_the_bounds_of_flat_points() -> None:
    assert cooking.points_hull_volume(CUBE * 2.0) == pytest.approx(8.0)
    assert cooking.points_hull_volume(CUBE[[0, 2, 4, 6]]) == pytest.approx(1e-6)
    assert cooking.hull_volume(CUBE, np.zeros((0, 3), dtype='i')) == 0.0


def test_concavity_is_the_share_of_the_bounds_the_hull_leaves_empty() -> None:
    assert cooking.concavity(CUBE) == pytest.approx(0.0, abs=1e-9)
    assert cooking.concavity(ELL) > 0.4


def test_a_concave_cloud_splits_into_convex_pieces() -> None:
    pieces = cooking.approximate_convex_decomposition(ELL)
    assert 2 <= len(pieces) <= 8
    assert sum(len(piece) for piece in pieces) == len(ELL)
    assert len(cooking.approximate_convex_decomposition(CUBE)) == 1


def test_cooking_by_strategy() -> None:
    triangles = cooking.convex_hull(CUBE)[1]
    assert cooking.cook(CUBE, triangles, 'auto', dynamic=False).kind == 'trimesh'
    assert cooking.cook(CUBE, None, 'auto', dynamic=False).kind == 'convex'
    assert cooking.cook(CUBE, triangles, 'convex', dynamic=False).kind == 'convex'
    concave = cooking.cook(ELL, None, 'auto', dynamic=True)
    assert concave.kind == 'compound'
    assert all(part.kind == 'convex' for part, _position, _turn in concave.params['parts'])
    flat = cooking.cook(CUBE[[0, 2, 4, 6]], None, 'convex', dynamic=True)
    assert len(flat.params['points']) == 4


def test_a_proxy_of_a_convex_mesh_weighs_its_hull() -> None:
    proxy = Proxy.from_mesh(ELL, None, 'convex', dynamic=True)
    assert proxy.volume() == pytest.approx(cooking.points_hull_volume(ELL))


@pytest.mark.parametrize('points', [CUBE, ELL, np.random.default_rng(3).normal(size=(40, 3))])
@pytest.mark.parametrize('dynamic', [True, False])
def test_the_same_pieces_as_omi_physics(points: np.ndarray, dynamic: bool) -> None:
    """omi_physics cooks a mesh into the same shapes, while it is installed."""
    cookery = pytest.importorskip('omi_physics.cookery', reason='omi_physics is the reference')
    ours = cooking.cook(points, None, 'auto', dynamic)
    theirs = cookery.cook_shape(np.array(points), None, 'auto', dynamic)
    if ours.kind == 'compound':
        assert isinstance(theirs, list)
        assert len(ours.params['parts']) == len(theirs)
        pairs = [(part.params['points'], shape.points)
                 for (part, _p, _t), shape in zip(ours.params['parts'], theirs, strict=True)]
    else:
        assert ours.kind == theirs.type
        pairs = [(ours.params['points'], theirs.points)]
    for mine, omi in pairs:
        assert np.allclose(np.sort(mine, axis=0), np.sort(omi, axis=0))
