"""What the visual regression machinery is, and where it lives.

Comparing a rendered frame with a reference image is
``OpenGLContext.testing.framebuffer_comparison``, and reporting on a run is
``OpenGLContext.testing.report_generator``; ``tests/test_all_scripts.py`` is
what drives the scripts through them. These hold that arrangement to one
implementation -- the shared helpers -- and cover the comparison arithmetic
those helpers do.
"""

import pytest

# Test directory paths
from OpenGLContext.testing.paths import tests_root
TESTS_DIR = tests_root(__file__)
PROJECT_ROOT = TESTS_DIR.parent
REFERENCE_IMAGES_DIR = TESTS_DIR / 'reference_images'


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



# Teapot rendering is compared against a reference image by the visual suite,
# which drives `run_teapot_regression.py`, `teapot_ceramic.py` and
# `teapot_nurbs.py` through `tests/test_all_scripts.py`; the two profiles are
# swept by `scripts/profile_sweep.py`.
