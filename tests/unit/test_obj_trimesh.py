"""The OBJ reader against trimesh's, an independent reader of the same format.

trimesh (MIT) reads the corpus files and random polygon meshes written in every
corner form, and the two readers agree on triangle count, surface area,
area-weighted normal and bounds. The module is skipped where trimesh is not
installed, and ``trimesh`` is in the project's ``dev`` extra.

The corpus manifest marks the two files trimesh reads differently from the
format's rules, with the reason each time.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from OpenGLContext.loaders.objfile import parse_obj
from tests.unit.objcorpus import (
    CORPUS, MANIFEST, NAMES, check_consistent, corner_positions, crosses, random_obj,
    read, surface_area,
)

trimesh = pytest.importorskip('trimesh')


def trimesh_triangles(path: Path) -> np.ndarray:
    scene = trimesh.load(str(path), force='scene', process=False)
    found = [np.asarray(geometry.vertices)[np.asarray(geometry.faces)] for geometry in scene.dump()
             if hasattr(geometry, 'faces') and len(geometry.faces)]
    return np.concatenate(found) if found else np.zeros((0, 3, 3))


def agree(ours: np.ndarray, theirs: np.ndarray) -> None:
    assert len(ours) == len(theirs)
    if not len(ours):
        return
    assert surface_area(ours) == pytest.approx(surface_area(theirs), rel=1e-5, abs=1e-6)
    assert crosses(ours).sum(axis=0) == pytest.approx(crosses(theirs).sum(axis=0), rel=1e-4, abs=1e-5)
    assert np.allclose(ours.reshape(-1, 3).min(axis=0), theirs.reshape(-1, 3).min(axis=0), atol=1e-5)
    assert np.allclose(ours.reshape(-1, 3).max(axis=0), theirs.reshape(-1, 3).max(axis=0), atol=1e-5)


@pytest.mark.parametrize('name', [name for name in NAMES if MANIFEST[name]['trimesh']])
def test_trimesh_reads_the_file_to_the_same_surface(name: str) -> None:
    agree(corner_positions(read(name)), trimesh_triangles(CORPUS / name))


@pytest.mark.parametrize('name', [name for name in NAMES if not MANIFEST[name]['trimesh']])
def test_each_file_trimesh_reads_differently_says_why_in_the_manifest(name: str) -> None:
    assert MANIFEST[name]['note']


@pytest.mark.parametrize('seed', range(60))
def test_random_polygon_files_agree_with_trimesh(seed: int, tmp_path: Path) -> None:
    path = tmp_path / 'random.obj'
    path.write_bytes(random_obj(seed).encode())
    model = parse_obj(path.read_bytes(), 'random.obj')
    check_consistent(model)
    agree(corner_positions(model), trimesh_triangles(path))
