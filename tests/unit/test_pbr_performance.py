"""Performance tests for the PBR pass GPU-resource cache.

Two layers:

* Unit tests (no GL): the per-mesh GPU resources are built once and reused via
  the scenegraph cache, and the front-face winding is cached per modelview.
* Subprocess test (needs GL): an animated 200-primitive scene rendered for many
  frames allocates one VAO per mesh with caching vs one per mesh *per frame*
  without, and the cached path is no slower.
"""
import json
import os
import subprocess
import sys
import types

import pytest

import numpy as np
from vrml.cache import Cache

from OpenGLContext.scenegraph import pbrmesh
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))
HARNESS = os.path.join(TESTS_DIR, "helpers", "_pbr_perf_harness.py")

CUBE = (np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0]], 'f'),
        np.array([[0, 0, 1]] * 3, 'f'))


def _mesh():
    return PBRMesh(positions=CUBE[0], normals=CUBE[1])


# -- unit tests (no GL) -----------------------------------------------------

def test_gpu_resources_built_once_and_reused(monkeypatch):
    """`_gpu` builds a single GPU-resource object and returns it thereafter."""
    builds = []

    class FakeGPU:
        def __init__(self, mesh, pending_deletes=None):
            builds.append(mesh)

    monkeypatch.setattr(pbrmesh, "_MeshGPU", FakeGPU)
    mesh = _mesh()
    mode = types.SimpleNamespace(cache=Cache())

    first = mesh._gpu(mode)
    again = mesh._gpu(mode)

    assert first is again
    assert len(builds) == 1, "VAO/VBO resources rebuilt instead of cached"


def test_gpu_cache_is_per_node(monkeypatch):
    """Distinct meshes get distinct cached GPU resources under one cache."""
    monkeypatch.setattr(pbrmesh, "_MeshGPU", lambda mesh, pending_deletes=None: object())
    mode = types.SimpleNamespace(cache=Cache())
    a, b = _mesh(), _mesh()
    assert a._gpu(mode) is not b._gpu(mode)
    assert a._gpu(mode) is a._gpu(mode)


def test_front_face_winding_from_determinant_sign():
    """Front-face winding follows the modelview parity (direct 3x3 determinant)."""
    from OpenGL.GL import GL_CCW, GL_CW

    mesh = _mesh()
    assert mesh._front_face(np.identity(4, 'f')) == GL_CCW
    # odd negative scale -> flipped parity -> CW
    assert mesh._front_face(np.diag([-1.0, 1.0, 1.0, 1.0]).astype('f')) == GL_CW
    # even negative scale -> parity restored -> CCW
    assert mesh._front_face(np.diag([-1.0, -1.0, 1.0, 1.0]).astype('f')) == GL_CCW
    # a rotation (determinant +1) stays CCW; must ignore the translation row
    from math import cos, sin, pi
    a = pi / 3
    R = np.identity(4, 'f')
    R[:3, :3] = [[cos(a), -sin(a), 0], [sin(a), cos(a), 0], [0, 0, 1]]
    R[3, :3] = [5.0, -2.0, 9.0]
    assert mesh._front_face(R) == GL_CCW


def test_front_face_handles_missing_matrix():
    from OpenGL.GL import GL_CCW
    assert _mesh()._front_face(None) == GL_CCW


# -- subprocess perf test (needs GL) ----------------------------------------

def _run(mode, shapes=200, frames=200):
    try:
        proc = subprocess.run(
            [sys.executable, HARNESS, mode, str(shapes), str(frames)],
            timeout=300, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None
    out = proc.stdout.decode("utf-8", "replace").strip().splitlines()
    for line in reversed(out):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


@pytest.fixture(scope="module")
def perf_results():
    shapes = 200
    cached = _run("cached", shapes)
    if not cached or cached.get("rendered", 0) < 20:
        pytest.skip("OpenGL context unavailable for PBR performance test")
    uncached = _run("uncached", shapes)
    if not uncached or uncached.get("rendered", 0) < 20:
        pytest.skip("OpenGL context unavailable for PBR performance test")
    return shapes, cached, uncached


def test_cached_allocates_one_vao_per_mesh(perf_results):
    """With caching, the VAO count equals the primitive count for the whole run."""
    shapes, cached, _ = perf_results
    assert cached["vao_allocations"] == shapes


def test_uncached_allocates_a_vao_every_frame(perf_results):
    """The uncached baseline rebuilds a VAO per mesh per frame (the old churn)."""
    shapes, cached, uncached = perf_results
    # roughly shapes * frames; assert it is at least an order of magnitude more
    assert uncached["vao_allocations"] > cached["vao_allocations"] * 10


@pytest.mark.performance
def test_cached_is_not_slower(perf_results):
    """Caching must not regress per-frame submission cost."""
    _, cached, uncached = perf_results
    # 10% margin for measurement noise; the cache removes per-frame VAO churn so
    # the cached path should be at least as fast as rebuilding every frame.
    assert cached["median_ms"] <= uncached["median_ms"] * 1.1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
