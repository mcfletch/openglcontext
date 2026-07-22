"""The regression runner's non-GL logic: diffing a new render against a baseline,
deciding what counts as a regression, selecting scenes, and blessing."""
import os
import shutil

import numpy as np
import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image

from OpenGLContext.bin import gltf_regression as R


def _png(path, color, size=(16, 16)):
    Image.new('RGB', size, color).save(path)


class TestCompare:
    def test_identical_images_are_not_a_regression(self, tmp_path):
        a = str(tmp_path / 'a.png'); b = str(tmp_path / 'b.png')
        _png(a, (120, 130, 140)); _png(b, (120, 130, 140))
        result, stats = R.compare(a, b, str(tmp_path / 'd.png'), R.DIFF_THRESHOLD)
        assert stats['percent_different'] == 0.0
        assert R.is_regression(result, R.DEFAULT_TOLERANCE) is False

    def test_changed_image_is_a_regression_and_writes_a_diff(self, tmp_path):
        a = str(tmp_path / 'a.png'); b = str(tmp_path / 'b.png')
        diff = str(tmp_path / 'd.png')
        _png(a, (10, 10, 10)); _png(b, (200, 200, 200))
        result, stats = R.compare(a, b, diff, R.DIFF_THRESHOLD)
        assert stats['percent_different'] > R.DEFAULT_TOLERANCE
        assert R.is_regression(result, R.DEFAULT_TOLERANCE) is True
        assert os.path.exists(diff)          # a heatmap was saved

    def test_shape_mismatch_is_a_regression(self, tmp_path):
        a = str(tmp_path / 'a.png'); b = str(tmp_path / 'b.png')
        _png(a, (0, 0, 0), size=(16, 16)); _png(b, (0, 0, 0), size=(8, 8))
        result, _ = R.compare(a, b, str(tmp_path / 'd.png'), R.DIFF_THRESHOLD)
        assert result.shapes_match is False
        assert R.is_regression(result, R.DEFAULT_TOLERANCE) is True


class TestSelectAndBless:
    def test_only_filters_scenes(self):
        picked = [s.name for s in R.select_scenes(['Duck', 'MetalRoughSpheres'])]
        assert set(picked) == {'Duck', 'MetalRoughSpheres'}

    def test_no_filter_returns_full_roster(self):
        assert len(R.select_scenes(None)) == len(R.select_scenes([])) > 5

    def test_bless_flag_semantics(self):
        # absent -> None (no bless); bare --bless -> [] (bless all); named -> list
        assert R.build_parser().parse_args([]).bless is None
        assert R.build_parser().parse_args(['--bless']).bless == []
        assert R.build_parser().parse_args(['--bless', 'Duck']).bless == ['Duck']

    def test_baseline_root_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv('OPENGLCONTEXT_GLTF_BASELINE', str(tmp_path))
        assert R.default_baseline_root() == str(tmp_path)


class TestReportLocation:
    def test_default_report_lands_under_tests_subdir(self):
        # not inside a virtualenv/site-packages -- a subdirectory of the source
        # tree's tests/ (the report must never write into .venv)
        path = R.default_report_path().replace(os.sep, '/')
        assert '/tests/gltf_regression/' in path
        assert 'site-packages' not in path and '.venv' not in path

    def test_source_root_has_tests_and_package(self):
        root = R._source_root()
        assert root is not None
        assert os.path.isdir(os.path.join(root, 'tests'))
        assert os.path.isfile(os.path.join(root, 'OpenGLContext', '__init__.py'))
