"""Loading an image-based environment cubemap for the IBL probe (no GL).

The IBL probe normally builds its environment from a procedural studio cube; this
lets a real cubemap (6 face images) be the source instead, so metals reflect a
genuine environment (SpecularTest / EnvironmentTest / any reflective demo). Tests
the pure face-loading + sRGB->linear step; the GL upload/convolve is covered by a
render test.
"""
import os

import numpy as np
import pytest

PIL = pytest.importorskip("PIL")

from OpenGLContext.passes import ibl

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))
ENV_PREFIX = os.path.join(TESTS_DIR, 'pimbackground_')   # _RT/_LF/_UP/_DN/_FR/_BK.jpg


class TestCubemapFaceLoading:
    def test_loads_six_faces_at_requested_size(self):
        faces = ibl.load_cubemap_faces(ENV_PREFIX, size=64)
        assert set(faces.keys()) == {0, 1, 2, 3, 4, 5}      # 6 GL face offsets
        for arr in faces.values():
            assert arr.shape == (64, 64, 3)
            assert arr.dtype == np.float32

    def test_values_are_linearised(self):
        # a mid-gray sRGB pixel (~0.5) must decode to ~0.21 linear, not 0.5
        faces = ibl.load_cubemap_faces(ENV_PREFIX, size=32)
        allv = np.concatenate([f.reshape(-1, 3) for f in faces.values()])
        assert allv.max() <= 1.0 + 1e-5 and allv.min() >= 0.0
        # sky faces are bright; linearisation keeps them in range but darkens midtones
        assert allv.mean() < 0.6

    def test_missing_prefix_returns_none(self):
        assert ibl.load_cubemap_faces(os.path.join(TESTS_DIR, 'no_such_env_'),
                                      size=32) is None

    def test_env_prefix_from_environment(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_ENV_CUBEMAP', ENV_PREFIX)
        assert ibl.environment_cubemap_prefix() == ENV_PREFIX
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        assert ibl.environment_cubemap_prefix() is None
