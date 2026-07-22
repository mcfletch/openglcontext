"""Visual regression tests for OpenGLContext rendering.

These tests run rendering scripts in subprocesses and compare output
against saved reference images. Tests are parametrized to run with
both compatibility and core profiles.

Note: Most existing test scripts don't support the --exit-after flag needed
for automated testing. This module tests the scripts that have been updated
to support automated regression testing (using AutomatedRegressionContext mixin).

The tests collect coverage from subprocess runs using --parallel-mode,
which is automatically combined by conftest.py after the test session.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROFILES = ['compatibility', 'core']

# Test directory paths
from OpenGLContext.testing.paths import tests_root
TESTS_DIR = tests_root(__file__)
PROJECT_ROOT = TESTS_DIR.parent
REFERENCE_IMAGES_DIR = TESTS_DIR / 'reference_images'

# Scripts that have been updated to support automated testing with --exit-after
# These scripts use the AutomatedRegressionContext mixin.
AUTOMATED_TEST_SCRIPTS = [
    'teapot_comparison.py',
]

# Default timeout for subprocess tests
DEFAULT_TIMEOUT = 60


class TestModuleImports:
    """Test that all testing modules can be imported."""

    def test_import_framebuffer_comparison(self):
        """Test framebuffer_comparison module imports."""
        from OpenGLContext.testing import framebuffer_comparison
        assert framebuffer_comparison.FramebufferCapture is not None
        assert framebuffer_comparison.ComparisonResult is not None

    def test_import_subprocess_runner(self):
        """Test subprocess_runner module imports."""
        from OpenGLContext.testing import subprocess_runner
        assert subprocess_runner.TestRunner is not None
        assert subprocess_runner.run_test is not None

    def test_import_event_injector(self):
        """Test event_injector module imports."""
        from OpenGLContext.testing import event_injector
        assert event_injector.EventInjector is not None
        assert event_injector.EventSender is not None

    def test_import_report_generator(self):
        """Test report_generator module imports."""
        from OpenGLContext.testing import report_generator
        assert report_generator.TestReportGenerator is not None
        assert report_generator.generate_report is not None


class TestBespokeFrameworkRetired:
    """6a: the bespoke rendering_regression.py -- a fourth parallel run/capture/
    diff/report framework -- is retired in favour of the shared
    OpenGLContext.testing helpers, and its 5 itemized + 1 full-suite driver tests
    (a redundant re-render of scenes the visual suite already covers) are gone.
    This guards against the duplication creeping back.
    """

    def test_rendering_regression_script_removed(self):
        assert not (TESTS_DIR / 'rendering_regression.py').exists(), (
            'rendering_regression.py is back -- reuse OpenGLContext.testing '
            '(framebuffer_comparison / report_generator) instead of a 4th framework')

    def test_no_driver_classes_for_the_bespoke_framework(self):
        assert 'TestRenderingRegression' not in globals()
        assert 'TestFullRegressionSuite' not in globals()

    def test_shared_framework_is_the_path(self):
        from OpenGLContext.testing import framebuffer_comparison, report_generator
        assert framebuffer_comparison.ComparisonResult is not None
        assert report_generator.TestReportGenerator is not None


class TestComparisonResult:
    """Test ComparisonResult calculations."""

    def test_identical_images_match(self):
        """Identical images should have zero difference."""
        import numpy as np
        from OpenGLContext.testing.framebuffer_comparison import ComparisonResult

        img = np.ones((100, 100, 3), dtype=np.uint8) * 128
        result = ComparisonResult(img, img)

        assert result.shapes_match
        assert result.max_diff == 0.0
        assert result.mean_diff == 0.0
        assert result.pixels_different == 0
        assert result.is_match()

    def test_different_images_detected(self):
        """Different images should be detected."""
        import numpy as np
        from OpenGLContext.testing.framebuffer_comparison import ComparisonResult

        img1 = np.zeros((100, 100, 3), dtype=np.uint8)
        img2 = np.ones((100, 100, 3), dtype=np.uint8) * 255
        result = ComparisonResult(img1, img2)

        assert result.shapes_match
        assert result.max_diff == 255.0
        assert result.pixels_different > 0
        assert not result.is_match(max_diff_threshold=10)

    def test_shape_mismatch_detected(self):
        """Shape mismatches should be detected."""
        import numpy as np
        from OpenGLContext.testing.framebuffer_comparison import ComparisonResult

        img1 = np.zeros((100, 100, 3), dtype=np.uint8)
        img2 = np.zeros((50, 50, 3), dtype=np.uint8)
        result = ComparisonResult(img1, img2)

        assert not result.shapes_match
        assert not result.is_match()


# TestReportGenerator unit tests live in test_testing_infrastructure.py
# (TestTestReportGenerator) -- the single home for OpenGLContext.testing coverage
#. The duplicate copy that was here has been removed.


def _check_coverage_available():
    """Check if coverage module is available."""
    try:
        import coverage
        return hasattr(coverage, 'Coverage')
    except ImportError:
        return False


def _check_display_available():
    """Check if OpenGL rendering is possible (windowed or offscreen EGL/OSMesa).

    Delegates to the shared helper so this copy can't drift back to a
    windowed-only check that false-skips the visual suite on headless CI.
    """
    from OpenGLContext.testing.display import display_available
    return display_available()


def _build_coverage_command(script_path, args=None, with_coverage=True):
    """Build command to run script with optional coverage collection."""
    if with_coverage and _check_coverage_available():
        cmd = [
            sys.executable, '-m', 'coverage', 'run',
            '--parallel-mode',
            '--source=OpenGLContext',
            str(script_path)
        ]
    else:
        cmd = [sys.executable, str(script_path)]

    if args:
        cmd.extend(args)
    return cmd


@pytest.mark.visual
class TestTeapotRegression:
    """Subprocess tests for teapot rendering regression.

    These tests run the teapot_comparison.py script in subprocesses
    and verify the rendering works correctly. Coverage is collected
    from subprocess runs.
    """

    @pytest.fixture
    def output_dir(self, tmp_path):
        """Create a temporary output directory for test images."""
        output = tmp_path / 'teapot_output'
        output.mkdir()
        return output

    @pytest.mark.skipif(not _check_display_available(), reason="No display available")
    def test_teapot_compatibility_record(self, output_dir):
        """Test teapot rendering in compatibility mode (record)."""
        script_path = TESTS_DIR / 'teapot_comparison.py'
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_path}")

        env = os.environ.copy()
        env['OPENGLCONTEXT_PROFILE'] = 'compatibility'

        cmd = _build_coverage_command(
            script_path,
            args=['--record', '--output-dir', str(output_dir), '--exit-after'],
        )

        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            cwd=str(PROJECT_ROOT),
        )

        # Check subprocess completed
        assert result.returncode == 0, f"Teapot compat failed:\n{result.stderr}"

        # Check output image was created
        output_files = list(output_dir.glob('*.png'))
        assert len(output_files) > 0, "No output image created"

    @pytest.mark.skipif(not _check_display_available(), reason="No display available")
    def test_teapot_core_record(self, output_dir):
        """Test teapot rendering in core profile mode (record)."""
        script_path = TESTS_DIR / 'teapot_comparison.py'
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_path}")

        env = os.environ.copy()
        env['OPENGLCONTEXT_PROFILE'] = 'core'
        env['OPENGLCONTEXT_BACKEND'] = 'glfw'

        cmd = _build_coverage_command(
            script_path,
            args=['--record', '--output-dir', str(output_dir), '--exit-after'],
        )

        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT,
            cwd=str(PROJECT_ROOT),
        )

        # Check subprocess completed
        assert result.returncode == 0, f"Teapot core failed:\n{result.stderr}"

        # Check output image was created
        output_files = list(output_dir.glob('*.png'))
        assert len(output_files) > 0, "No output image created"
