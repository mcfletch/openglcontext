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
TESTS_DIR = Path(__file__).parent
PROJECT_ROOT = TESTS_DIR.parent
REFERENCE_IMAGES_DIR = TESTS_DIR / 'reference_images'

# Scripts that have been updated to support automated testing with --exit-after
# These scripts use the AutomatedRegressionContext mixin
AUTOMATED_TEST_SCRIPTS = [
    'teapot_comparison.py',
    'rendering_regression.py',
]

# Default timeout for subprocess tests
DEFAULT_TIMEOUT = 60
SLOW_TEST_TIMEOUT = 180


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


class TestReportGenerator:
    """Test HTML report generation."""

    def test_generate_empty_report(self, tmp_path):
        """Test generating an empty report."""
        from OpenGLContext.testing.report_generator import TestReportGenerator

        generator = TestReportGenerator("Test Report")
        html = generator.generate_html()

        assert "Test Report" in html
        assert "0" in html  # Total count
        assert "Passed" in html

    def test_generate_report_with_tests(self, tmp_path):
        """Test generating a report with test results."""
        from OpenGLContext.testing.report_generator import TestReportGenerator

        generator = TestReportGenerator("Test Report")
        generator.add_test({
            'test_name': 'test_one',
            'status': 'pass',
            'duration': 1.5,
        })
        generator.add_test({
            'test_name': 'test_two',
            'status': 'fail',
            'duration': 0.5,
            'stderr': 'Error message',
        })

        html = generator.generate_html()

        assert "test_one" in html
        assert "test_two" in html
        assert "Error message" in html

    def test_save_report(self, tmp_path):
        """Test saving report to file."""
        from OpenGLContext.testing.report_generator import generate_report

        output_path = tmp_path / "report.html"
        generate_report(
            [{'test_name': 'test', 'status': 'pass'}],
            str(output_path),
        )

        assert output_path.exists()
        content = output_path.read_text()
        assert "test" in content


def _check_coverage_available():
    """Check if coverage module is available."""
    try:
        import coverage
        return hasattr(coverage, 'Coverage')
    except ImportError:
        return False


def _check_display_available():
    """Check if a display is available for OpenGL rendering."""
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))


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


@pytest.mark.visual
@pytest.mark.slow
class TestRenderingRegression:
    """Subprocess tests for comprehensive rendering regression suite.

    These tests run the rendering_regression.py script which tests
    multiple rendering scenarios (geometry, lighting, textures, etc).
    Coverage is collected from all subprocess runs.
    """

    @pytest.fixture
    def output_dir(self, tmp_path):
        """Create a temporary output directory for test images."""
        output = tmp_path / 'regression_output'
        output.mkdir()
        return output

    @pytest.mark.skipif(not _check_display_available(), reason="No display available")
    def test_basic_geometry(self, output_dir):
        """Test basic geometry rendering (Box, Sphere, Cone)."""
        script_path = TESTS_DIR / 'rendering_regression.py'
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_path}")

        cmd = _build_coverage_command(
            script_path,
            args=['--output-dir', str(output_dir), '--tests', 'basic_geometry'],
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SLOW_TEST_TIMEOUT,
            cwd=str(PROJECT_ROOT),
        )

        # Check subprocess completed
        assert result.returncode == 0, f"basic_geometry failed:\n{result.stderr}\n{result.stdout}"

    @pytest.mark.skipif(not _check_display_available(), reason="No display available")
    def test_teapot_lighting(self, output_dir):
        """Test teapot with directional lighting."""
        script_path = TESTS_DIR / 'rendering_regression.py'
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_path}")

        cmd = _build_coverage_command(
            script_path,
            args=['--output-dir', str(output_dir), '--tests', 'teapot_lighting'],
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SLOW_TEST_TIMEOUT,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 0, f"teapot_lighting failed:\n{result.stderr}\n{result.stdout}"

    @pytest.mark.skipif(not _check_display_available(), reason="No display available")
    def test_material_properties(self, output_dir):
        """Test material properties (ambient, specular, emissive)."""
        script_path = TESTS_DIR / 'rendering_regression.py'
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_path}")

        cmd = _build_coverage_command(
            script_path,
            args=['--output-dir', str(output_dir), '--tests', 'material_properties'],
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SLOW_TEST_TIMEOUT,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 0, f"material_properties failed:\n{result.stderr}\n{result.stdout}"

    @pytest.mark.skipif(not _check_display_available(), reason="No display available")
    def test_transparency(self, output_dir):
        """Test transparent objects with alpha blending."""
        script_path = TESTS_DIR / 'rendering_regression.py'
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_path}")

        cmd = _build_coverage_command(
            script_path,
            args=['--output-dir', str(output_dir), '--tests', 'transparency'],
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SLOW_TEST_TIMEOUT,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 0, f"transparency failed:\n{result.stderr}\n{result.stdout}"

    @pytest.mark.skipif(not _check_display_available(), reason="No display available")
    def test_indexed_lineset(self, output_dir):
        """Test IndexedLineSet with per-vertex colors."""
        script_path = TESTS_DIR / 'rendering_regression.py'
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_path}")

        cmd = _build_coverage_command(
            script_path,
            args=['--output-dir', str(output_dir), '--tests', 'indexed_lineset'],
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SLOW_TEST_TIMEOUT,
            cwd=str(PROJECT_ROOT),
        )

        assert result.returncode == 0, f"indexed_lineset failed:\n{result.stderr}\n{result.stdout}"


@pytest.mark.visual
@pytest.mark.slow
class TestFullRegressionSuite:
    """Run the full rendering regression suite.

    This is a comprehensive test that runs all rendering scenarios.
    It's marked as slow because it runs many subprocesses.
    """

    @pytest.fixture
    def output_dir(self, tmp_path):
        """Create a temporary output directory for test images."""
        output = tmp_path / 'full_regression'
        output.mkdir()
        return output

    @pytest.mark.skipif(not _check_display_available(), reason="No display available")
    def test_full_regression_suite(self, output_dir):
        """Run all rendering regression tests."""
        script_path = TESTS_DIR / 'rendering_regression.py'
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_path}")

        cmd = _build_coverage_command(
            script_path,
            args=['--output-dir', str(output_dir)],
        )

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SLOW_TEST_TIMEOUT * 2,  # Full suite takes longer
            cwd=str(PROJECT_ROOT),
        )

        # Print output for debugging
        if result.stdout:
            print("\n--- Regression Suite Output ---")
            print(result.stdout)

        # Check report was generated
        report_path = output_dir / 'regression_report.md'
        if report_path.exists():
            print("\n--- Regression Report ---")
            print(report_path.read_text()[:2000])  # First 2000 chars

        assert result.returncode == 0, f"Full regression suite failed:\n{result.stderr}"
