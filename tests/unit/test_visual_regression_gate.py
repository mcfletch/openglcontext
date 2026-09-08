"""The visual-regression comparison must actually fail on pixel differences.

The old gate was ``max_diff <= 255 and percent_different <= 2.0``
-- the first clause is a tautology (255 is the max possible), and the mismatch
branch was a literal ``pass``, so a black or wrong-colour frame passed as long
as the process exited 0. These tests pin the gate to real behaviour.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PIL")
from PIL import Image

from OpenGLContext.testing.paths import tests_root

# test_all_scripts stays in the tests root (it runs the demo scripts there).
sys.path.insert(0, str(tests_root(__file__)))
import test_all_scripts as tas


def _write(path, rgb):
    arr = np.zeros((32, 32, 3), dtype=np.uint8)
    arr[:, :] = rgb
    Image.fromarray(arr, mode='RGB').save(path)


def test_identical_images_match(tmp_path):
    ref = tmp_path / "ref.png"
    res = tmp_path / "res.png"
    _write(ref, (10, 120, 240))
    _write(res, (10, 120, 240))

    stats = tas._compare_images(ref, res)
    assert stats['is_match'] is True
    assert stats['percent_different'] == 0.0


def test_black_frame_fails_against_reference(tmp_path):
    """The canonical 2.9 failure: a black frame must NOT match a real render."""
    ref = tmp_path / "ref.png"
    res = tmp_path / "res.png"
    _write(ref, (200, 200, 200))
    _write(res, (0, 0, 0))

    stats = tas._compare_images(ref, res)
    assert stats['is_match'] is False


def test_shape_mismatch_fails(tmp_path):
    ref = tmp_path / "ref.png"
    res = tmp_path / "res.png"
    Image.fromarray(np.zeros((16, 16, 3), np.uint8), 'RGB').save(ref)
    Image.fromarray(np.zeros((32, 32, 3), np.uint8), 'RGB').save(res)

    stats = tas._compare_images(ref, res)
    assert stats['is_match'] is False


def test_max_diff_bound_is_not_tautological():
    """The gate must not treat every image as a match via a 255 ceiling."""
    import inspect
    src = inspect.getsource(tas._compare_images)
    assert 'max_diff <= 255' not in src, "tautological bound still present (2.9)"


def test_thresholds_are_centralized():
    """A single named tolerance constant governs the gate."""
    assert hasattr(tas, 'MAX_PERCENT_DIFFERENT')
    assert hasattr(tas, 'PIXEL_DIFF_THRESHOLD')


class TestAFrameThatWasNeverCaptured:
    """A script asked for a capture that writes none has compared nothing.

    The auto-exit capture reports what went wrong and lets the script finish, so
    its exit code still says the run went well.  Reading the wrong colour buffer
    once was enough to make that happen to every script at once, and the gate
    below is what turns it into a failure rather than two hundred quiet passes.
    """

    def _script(self, tmp_path, body):
        path = tmp_path / 'never_draws.py'
        path.write_text(body)
        return path

    def test_no_capture_is_a_failure_not_a_pass(self, tmp_path):
        script = self._script(tmp_path, 'print("ran, drew nothing")\n')
        result = tas._run_visual_test(script, timeout=60)
        assert result.status == 'no_capture', (
            'a script that wrote no frame reported %r' % (result.status,))

    def test_a_script_that_fails_says_so_instead(self, tmp_path):
        """The exit code is the more useful answer where there is one.  Not
        ``REQUIRED_EXTENSION_MISSING``, which is the code a script says "there
        was nothing here to draw" with and is a skip rather than a failure."""
        script = self._script(tmp_path, 'raise SystemExit(1)\n')
        result = tas._run_visual_test(script, timeout=60)
        assert result.status == 'fail'

    def test_a_script_with_nothing_to_draw_is_still_a_skip(self, tmp_path):
        script = self._script(
            tmp_path, 'raise SystemExit(%d)\n' % tas.REQUIRED_EXTENSION_MISSING)
        result = tas._run_visual_test(script, timeout=60)
        assert result.status == 'skip'

    def test_last_runs_frame_is_not_this_runs_evidence(self, tmp_path):
        """The result directory is kept between runs, so a stale frame would
        otherwise stand in for the one this run failed to write."""
        script = self._script(tmp_path, 'print("ran, drew nothing")\n')
        stale = tas.RESULT_IMAGES_DIR / 'never_draws.png'
        tas.RESULT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        _write(stale, (10, 20, 30))
        try:
            result = tas._run_visual_test(script, timeout=60)
            assert result.status == 'no_capture'
            assert not stale.exists(), 'the stale frame was left to be compared'
        finally:
            stale.unlink(missing_ok=True)
