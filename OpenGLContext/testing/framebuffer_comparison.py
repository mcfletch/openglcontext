#! /usr/bin/env python
"""Framebuffer comparison utilities for automated rendering regression testing.

This module provides utilities for comparing rendered output between different
rendering paths (e.g., legacy vs shader-based, compatibility vs core profile).

Key features:
- Automated capture after configurable delay (no user interaction needed)
- Command-line flags for record vs test mode
- Excludes HUD/framerate display from comparisons
- Saves reference, result, and diff images using Pillow
- Supports automated testing by higher-level test runners

Usage:
    # Record a reference image (legacy/compatibility mode)
    python test_file.py --record --output-dir tests/reference_images

    # Test against reference (core mode)
    python test_file.py --test --reference tests/reference_images/test_name.png

    # Or use the RegressionTestRunner for automated legacy-vs-core testing
    from OpenGLContext.testing.framebuffer_comparison import RegressionTestRunner
    runner = RegressionTestRunner('teapot_test', TeapotContext)
    success = runner.run_comparison()
"""
import argparse
import logging
import os
import sys
import time
import numpy as np
from OpenGLContext.capture import ensure_pillow, read_back_buffer, save_png
from OpenGLContext.testing.process_exit import flush_and_exit

log = logging.getLogger(__name__)

# Default directory for reference images
DEFAULT_REFERENCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'tests', 'reference_images'
)

# Default capture delay in seconds (allow scene to stabilize). Overridable via
# the environment so a slow/headless CI runner can be more generous without
# editing source; the capture also waits for a minimum frame
# count, so this is a floor on wall-clock time, not the sole readiness signal.
DEFAULT_CAPTURE_DELAY = float(os.environ.get('OPENGLCONTEXT_CAPTURE_DELAY', '0.5'))

# Default region to exclude from bottom of frame (for any HUD elements)
# Set to 0 since we disable the frame counter for regression tests
DEFAULT_HUD_HEIGHT = 0


class ComparisonResult:
    """Results from comparing two framebuffer captures."""

    def __init__(self, pixels_a, pixels_b, threshold=0.02):
        """Calculate comparison statistics.

        Args:
            pixels_a: First image as numpy array (H, W, 3) with values 0-255
            pixels_b: Second image as numpy array (H, W, 3) with values 0-255
            threshold: Minimum difference to consider pixels different (0-255 scale)
        """
        self.shape_a = pixels_a.shape
        self.shape_b = pixels_b.shape
        self.shapes_match = pixels_a.shape == pixels_b.shape
        self.threshold = threshold

        if not self.shapes_match:
            self.max_diff = 255
            self.mean_diff = 255
            self.pixels_different = -1
            self.total_pixels = -1
            self.percent_different = 100.0
            self.diff_image = None
            return

        # Calculate differences (as float for precision)
        diff = np.abs(pixels_a.astype(np.float32) - pixels_b.astype(np.float32))

        self.max_diff = float(np.max(diff))
        self.mean_diff = float(np.mean(diff))

        # Create diff image (amplified for visibility)
        self.diff_image = np.clip(diff * 4, 0, 255).astype(np.uint8)

        # Count pixels that differ by more than threshold
        pixel_max_diff = np.max(diff, axis=2)  # Max diff across RGB channels
        self.pixels_different = int(np.sum(pixel_max_diff > threshold))
        self.total_pixels = pixels_a.shape[0] * pixels_a.shape[1]
        self.percent_different = 100.0 * self.pixels_different / self.total_pixels

    def is_match(self, max_diff_threshold=10, max_percent_different=1.0):
        """Check if images match within acceptable tolerances.

        Args:
            max_diff_threshold: Maximum allowed pixel difference (0-255)
            max_percent_different: Maximum percent of pixels that can differ

        Returns:
            bool: True if images match within tolerances
        """
        if not self.shapes_match:
            return False
        return (self.max_diff <= max_diff_threshold and
                self.percent_different <= max_percent_different)

    def __str__(self):
        if not self.shapes_match:
            return f"Shape mismatch: {self.shape_a} vs {self.shape_b}"
        return (
            f"Max diff: {self.max_diff:.1f}/255, "
            f"Mean diff: {self.mean_diff:.2f}, "
            f"Pixels different: {self.pixels_different}/{self.total_pixels} "
            f"({self.percent_different:.2f}%)"
        )


class FramebufferCapture:
    """Captures and stores framebuffer contents for comparison."""

    def __init__(self, reference_dir=None, hud_height=DEFAULT_HUD_HEIGHT):
        """Initialize capture.

        Args:
            reference_dir: Directory for saving/loading reference images
            hud_height: Height in pixels to exclude from top (for HUD)
        """
        self.reference_dir = reference_dir or DEFAULT_REFERENCE_DIR
        self.hud_height = hud_height
        self.pixels = None
        self.width = 0
        self.height = 0

    def capture(self, exclude_hud=True):
        """Capture current framebuffer contents.

        Args:
            exclude_hud: If True, exclude bottom portion of frame (HUD/FPS area)

        Returns:
            numpy array of shape (height, width, 3) with uint8 values 0-255
        """
        hud = self.hud_height if exclude_hud else 0
        self.pixels, self.width, self.height = read_back_buffer(hud)
        return self.pixels

    def save_image(self, filepath):
        """Save current capture as PNG image.

        Args:
            filepath: Path to save the image

        Returns:
            True if saved successfully, False otherwise
        """
        if self.pixels is None:
            log.error("No pixels captured - call capture() first")
            return False
        return save_png(filepath, self.pixels)

    def load_reference(self, filepath):
        """Load a reference image.

        Args:
            filepath: Path to the reference image

        Returns:
            numpy array of reference image, or None if not found
        """
        if not os.path.exists(filepath):
            return None

        Image = ensure_pillow()
        if Image is None:
            return None

        img = Image.open(filepath).convert('RGB')
        return np.array(img, dtype=np.uint8)

    def compare_with_reference(self, reference_path, threshold=5):
        """Compare current capture with saved reference.

        Args:
            reference_path: Path to reference image
            threshold: Minimum difference to consider pixels different

        Returns:
            ComparisonResult, or None if reference doesn't exist
        """
        if self.pixels is None:
            raise ValueError("No pixels captured - call capture() first")

        reference = self.load_reference(reference_path)
        if reference is None:
            return None

        return ComparisonResult(self.pixels, reference, threshold)


def compare_images(pixels_a, pixels_b, threshold=5):
    """Compare two pixel arrays.

    Args:
        pixels_a: First image as numpy array (uint8)
        pixels_b: Second image as numpy array (uint8)
        threshold: Minimum difference to consider pixels different

    Returns:
        ComparisonResult
    """
    return ComparisonResult(pixels_a, pixels_b, threshold)


def save_comparison_images(reference, result, diff, output_dir, test_name):
    """Save reference, result, and diff images.

    Args:
        reference: Reference image array (or path to load from)
        result: Result image array
        diff: Diff image array (amplified differences)
        output_dir: Directory to save images
        test_name: Base name for the images

    Returns:
        Tuple of (reference_path, result_path, diff_path)
    """
    Image = ensure_pillow()
    if Image is None:
        return None, None, None

    os.makedirs(output_dir, exist_ok=True)

    ref_path = os.path.join(output_dir, f"{test_name}_reference.png")
    result_path = os.path.join(output_dir, f"{test_name}_result.png")
    diff_path = os.path.join(output_dir, f"{test_name}_diff.png")

    # Save reference if it's an array
    if isinstance(reference, np.ndarray):
        Image.fromarray(reference, mode='RGB').save(ref_path)

    # Save result
    Image.fromarray(result, mode='RGB').save(result_path)

    # Save diff
    if diff is not None:
        Image.fromarray(diff, mode='RGB').save(diff_path)

    return ref_path, result_path, diff_path


class AutomatedRegressionContext:
    """Mixin for OpenGLContext that adds automated regression testing.

    Usage:
        class MyTestContext(AutomatedRegressionContext, BaseContext):
            test_name = "my_test"

            def OnInit(self):
                self.setup_regression_test()
                # ... set up scene ...

    Command-line arguments:
        --record: Save current render as reference image
        --test: Test current render against reference
        --reference PATH: Path to reference image for comparison
        --output-dir PATH: Directory for output images
        --capture-delay SECS: Delay before capture (default 0.5)
        --exit-after: Exit after capture/test completes
    """

    test_name = "unnamed_test"
    _regression_capture = None
    _regression_args = None
    _regression_start_time = None
    _regression_captured = False

    @classmethod
    def add_regression_arguments(cls, parser):
        """Add regression test arguments to an argument parser."""
        group = parser.add_argument_group('Regression Testing')
        group.add_argument('--record', action='store_true',
                          help='Record current render as reference image')
        group.add_argument('--test', action='store_true',
                          help='Test current render against reference')
        group.add_argument('--reference', type=str,
                          help='Path to reference image for comparison')
        group.add_argument('--output-dir', type=str,
                          default=DEFAULT_REFERENCE_DIR,
                          help='Directory for output images')
        group.add_argument('--capture-delay', type=float,
                          default=DEFAULT_CAPTURE_DELAY,
                          help='Delay in seconds before capture')
        group.add_argument('--hud-height', type=int,
                          default=DEFAULT_HUD_HEIGHT,
                          help='Height of HUD area to exclude from capture')
        group.add_argument('--exit-after', action='store_true',
                          help='Exit after capture/test completes')
        group.add_argument('--max-diff', type=int, default=255,
                          help='Maximum allowed pixel difference (0-255, default 255)')
        group.add_argument('--max-percent-different', type=float, default=2.0,
                          help='Maximum percent of pixels that can differ (default 2.0)')
        return parser

    @classmethod
    def parse_regression_arguments(cls):
        """Parse command-line arguments for regression testing."""
        parser = argparse.ArgumentParser()
        cls.add_regression_arguments(parser)
        # Parse known args to allow other arguments to pass through
        args, _ = parser.parse_known_args()
        return args

    def setup_regression_test(self, args=None):
        """Set up automated regression testing.

        Call this from OnInit() to enable automated capture/testing.

        Args:
            args: Parsed arguments, or None to parse from command line
        """
        if args is None:
            args = self.parse_regression_arguments()

        self._regression_args = args
        self._regression_capture = FramebufferCapture(
            reference_dir=args.output_dir,
            hud_height=args.hud_height
        )
        self._regression_start_time = time.time()
        self._regression_captured = False
        self._regression_frame_count = 0

        # Disable the frame counter display for regression tests
        # This prevents false positives from FPS variations
        self.frameCounter = None

        # We'll check for capture in OnPostRender which we hook

    def _check_regression_capture(self):
        """Check if it's time to capture and run regression test.

        Call this from Render() after rendering is complete.
        """
        if self._regression_captured:
            return
        if self._regression_args is None:
            return
        if not (self._regression_args.record or self._regression_args.test):
            return

        args = self._regression_args
        self._regression_frame_count += 1
        elapsed = time.time() - self._regression_start_time

        # Wait for both frame count and time delay
        if elapsed < args.capture_delay or self._regression_frame_count < 3:
            return

        self._regression_captured = True

        # Capture the framebuffer (scene is already rendered)
        self._regression_capture.capture(exclude_hud=True)

        if args.record:
            self._do_record()
        elif args.test:
            self._do_test()

        if args.exit_after:
            # Schedule exit
            self.OnQuit()

    def _do_record(self):
        """Record current render as reference image."""
        args = self._regression_args
        os.makedirs(args.output_dir, exist_ok=True)
        ref_path = os.path.join(args.output_dir, f"{self.test_name}.png")
        if self._regression_capture.save_image(ref_path):
            log.info("RECORD: Saved reference image to %s", ref_path)
        else:
            log.error("RECORD: Failed to save reference image")
            flush_and_exit(1)

    def _do_test(self):
        """Test current render against reference."""
        args = self._regression_args

        # Determine reference path
        if args.reference:
            ref_path = args.reference
        else:
            ref_path = os.path.join(args.output_dir, f"{self.test_name}.png")

        if not os.path.exists(ref_path):
            log.warning("TEST SKIP: Reference image not found: %s", ref_path)
            log.warning("Run with --record first to create reference image")
            flush_and_exit(2)

        # Compare with reference
        result = self._regression_capture.compare_with_reference(ref_path)
        if result is None:
            log.error("TEST FAIL: Could not load reference image: %s", ref_path)
            flush_and_exit(1)

        # Save comparison images
        ref_pixels = self._regression_capture.load_reference(ref_path)
        save_comparison_images(
            ref_pixels,
            self._regression_capture.pixels,
            result.diff_image,
            args.output_dir,
            self.test_name
        )

        log.info("Regression Test: %s", self.test_name)
        log.info("  Reference: %s", ref_path)
        log.info("  %s", result)

        # Allow for hardware rendering variations:
        # - max_diff_threshold: Individual pixel differences (0-255 scale)
        # - max_percent_different: Percentage of pixels that can differ
        # These tolerances account for anti-aliasing variations, timing differences,
        # and other hardware-specific rendering artifacts.
        max_diff = getattr(args, 'max_diff', 255)
        max_pct = getattr(args, 'max_percent_different', 2.0)
        if result.is_match(max_diff_threshold=max_diff, max_percent_different=max_pct):
            log.info("  PASS - Output matches reference")
            flush_and_exit(0)
        else:
            log.error("  FAIL - Output differs from reference")
            diff_path = os.path.join(args.output_dir, f"{self.test_name}_diff.png")
            log.error("  Diff image saved to: %s", diff_path)
            flush_and_exit(1)


class RegressionTestRunner:
    """Runs automated regression tests comparing legacy vs core rendering.

    Usage:
        from OpenGLContext.testing.framebuffer_comparison import RegressionTestRunner

        runner = RegressionTestRunner(
            test_name='teapot_test',
            context_class=TeapotTestContext,
            reference_dir='tests/reference_images'
        )

        # Run full comparison (legacy first, then core)
        success = runner.run_comparison()

        # Or run individual steps
        runner.record_reference(profile='compatibility')
        success = runner.test_against_reference(profile='core')
    """

    def __init__(self, test_name, context_class, reference_dir=None):
        """Initialize the test runner.

        Args:
            test_name: Name for this test (used for image filenames)
            context_class: The OpenGLContext class to test
            reference_dir: Directory for reference images
        """
        self.test_name = test_name
        self.context_class = context_class
        self.reference_dir = reference_dir or DEFAULT_REFERENCE_DIR

    def run_comparison(self, legacy_profile='compatibility', core_profile='core'):
        """Run full comparison: record with legacy, test with core.

        Args:
            legacy_profile: Profile for recording reference
            core_profile: Profile for testing

        Returns:
            True if test passed, False otherwise
        """
        import subprocess

        # Get the module file for the context class
        module_file = sys.modules[self.context_class.__module__].__file__

        # Record reference with legacy profile
        log.info("Recording reference with %s profile...", legacy_profile)
        env = os.environ.copy()
        env['OPENGLCONTEXT_PROFILE'] = legacy_profile

        record_cmd = [
            sys.executable, module_file,
            '--record',
            '--output-dir', self.reference_dir,
            '--exit-after'
        ]

        result = subprocess.run(record_cmd, env=env)
        if result.returncode != 0:
            log.error("Failed to record reference image")
            return False

        # Test with core profile
        log.info("Testing with %s profile...", core_profile)
        env['OPENGLCONTEXT_PROFILE'] = core_profile
        if core_profile == 'core':
            env['OPENGLCONTEXT_BACKEND'] = 'glfw'

        test_cmd = [
            sys.executable, module_file,
            '--test',
            '--output-dir', self.reference_dir,
            '--exit-after'
        ]

        result = subprocess.run(test_cmd, env=env)
        return result.returncode == 0


# Legacy compatibility - keep old class names working
RegressionTestMixin = AutomatedRegressionContext


class VisualRegressionTest:
    """Manages visual regression testing for a single test.

    This class provides a higher-level interface for visual regression testing,
    handling reference image management, comparison, and report data generation.

    Example:
        test = VisualRegressionTest('box_rendering', 'tests/reference_images')
        test.record_reference('compatibility')
        result = test.test_against_reference('core')
        report = test.generate_report_data()
    """

    def __init__(
        self,
        test_name: str,
        reference_dir: str,
        max_diff_threshold: int = 255,
        max_percent_different: float = 2.0,
    ):
        """Initialize the regression test.

        Args:
            test_name: Name for this test (used for image filenames)
            reference_dir: Directory for storing/loading reference images
            max_diff_threshold: Maximum allowed pixel difference (0-255)
            max_percent_different: Maximum percent of pixels that can differ
        """
        self.test_name = test_name
        self.reference_dir = reference_dir
        self.max_diff_threshold = max_diff_threshold
        self.max_percent_different = max_percent_different

        self._reference_path = os.path.join(reference_dir, f'{test_name}.png')
        self._result_path = os.path.join(reference_dir, f'{test_name}_result.png')
        self._diff_path = os.path.join(reference_dir, f'{test_name}_diff.png')

        self._reference_pixels = None
        self._result_pixels = None
        self._comparison_result = None
        self._status = 'pending'
        self._stdout = ''
        self._stderr = ''
        self._duration = 0.0

    @property
    def reference_path(self) -> str:
        """Path to reference image."""
        return self._reference_path

    @property
    def has_reference(self) -> bool:
        """Check if reference image exists."""
        return os.path.exists(self._reference_path)

    def load_reference(self) -> bool:
        """Load reference image from disk.

        Returns:
            True if loaded successfully, False otherwise
        """
        Image = ensure_pillow()
        if Image is None:
            return False

        if not os.path.exists(self._reference_path):
            return False

        try:
            img = Image.open(self._reference_path).convert('RGB')
            self._reference_pixels = np.array(img, dtype=np.uint8)
            return True
        except Exception as e:
            log.error("Failed to load reference: %s", e)
            return False

    def save_reference(self, pixels: np.ndarray) -> bool:
        """Save reference image to disk.

        Args:
            pixels: Image data as numpy array (H, W, 3) uint8

        Returns:
            True if saved successfully
        """
        Image = ensure_pillow()
        if Image is None:
            return False

        os.makedirs(self.reference_dir, exist_ok=True)

        try:
            img = Image.fromarray(pixels, mode='RGB')
            img.save(self._reference_path)
            self._reference_pixels = pixels.copy()
            return True
        except Exception as e:
            log.error("Failed to save reference: %s", e)
            return False

    def compare(self, result_pixels: np.ndarray) -> ComparisonResult:
        """Compare result against reference.

        Args:
            result_pixels: Image data to compare (H, W, 3) uint8

        Returns:
            ComparisonResult with comparison statistics
        """
        self._result_pixels = result_pixels

        if self._reference_pixels is None:
            if not self.load_reference():
                self._status = 'skip'
                return None

        self._comparison_result = ComparisonResult(
            self._reference_pixels,
            result_pixels,
            threshold=5,
        )

        # Save result and diff images
        self._save_result_images()

        # Determine pass/fail
        if self._comparison_result.is_match(
            max_diff_threshold=self.max_diff_threshold,
            max_percent_different=self.max_percent_different,
        ):
            self._status = 'pass'
        else:
            self._status = 'fail'

        return self._comparison_result

    def _save_result_images(self) -> None:
        """Save result and diff images."""
        Image = ensure_pillow()
        if Image is None:
            return

        os.makedirs(self.reference_dir, exist_ok=True)

        if self._result_pixels is not None:
            try:
                img = Image.fromarray(self._result_pixels, mode='RGB')
                img.save(self._result_path)
            except Exception:
                pass

        if self._comparison_result and self._comparison_result.diff_image is not None:
            try:
                img = Image.fromarray(self._comparison_result.diff_image, mode='RGB')
                img.save(self._diff_path)
            except Exception:
                pass

    def generate_report_data(self) -> dict:
        """Generate data for HTML report.

        Returns:
            Dict with test information for report generation
        """
        data = {
            'test_name': self.test_name,
            'status': self._status,
            'reference_image': self._reference_path if self.has_reference else None,
            'result_image': self._result_path if os.path.exists(self._result_path) else None,
            'diff_image': self._diff_path if os.path.exists(self._diff_path) else None,
            'stdout': self._stdout,
            'stderr': self._stderr,
            'duration': self._duration,
        }

        if self._comparison_result:
            data['comparison_stats'] = {
                'shapes_match': self._comparison_result.shapes_match,
                'max_diff': self._comparison_result.max_diff,
                'mean_diff': self._comparison_result.mean_diff,
                'pixels_different': self._comparison_result.pixels_different,
                'total_pixels': self._comparison_result.total_pixels,
                'percent_different': self._comparison_result.percent_different,
            }

        return data

    def set_output(self, stdout: str, stderr: str, duration: float = 0.0) -> None:
        """Set captured output from subprocess execution.

        Args:
            stdout: Standard output from test
            stderr: Standard error from test
            duration: Test execution duration
        """
        self._stdout = stdout
        self._stderr = stderr
        self._duration = duration


class ProfileComparisonTest:
    """Compare rendering between two OpenGL profiles.

    Runs the same test with two different profiles and compares the results.
    Useful for verifying core profile rendering matches compatibility profile.
    """

    def __init__(
        self,
        test_name: str,
        script_path: str,
        reference_dir: str,
        reference_profile: str = 'compatibility',
        test_profile: str = 'core',
    ):
        """Initialize the profile comparison test.

        Args:
            test_name: Name for this test
            script_path: Path to the test script
            reference_dir: Directory for reference images
            reference_profile: Profile for reference rendering
            test_profile: Profile to test against reference
        """
        self.test_name = test_name
        self.script_path = script_path
        self.reference_dir = reference_dir
        self.reference_profile = reference_profile
        self.test_profile = test_profile

        self._regression = VisualRegressionTest(
            test_name=test_name,
            reference_dir=reference_dir,
        )

    def run(self, timeout: float = 30.0) -> dict:
        """Run the full comparison test.

        Args:
            timeout: Timeout for each subprocess

        Returns:
            Report data dict
        """
        import subprocess

        # Record reference if needed
        if not self._regression.has_reference:
            record_result = self._run_subprocess(
                profile=self.reference_profile,
                mode='record',
                timeout=timeout,
            )
            if record_result.returncode != 0:
                self._regression._status = 'error'
                self._regression._stderr = record_result.stderr
                return self._regression.generate_report_data()

        # Run test
        test_result = self._run_subprocess(
            profile=self.test_profile,
            mode='test',
            timeout=timeout,
        )

        self._regression.set_output(
            stdout=test_result.stdout,
            stderr=test_result.stderr,
            duration=0.0,
        )

        if test_result.returncode == 0:
            self._regression._status = 'pass'
        elif test_result.returncode == 2:
            self._regression._status = 'skip'
        else:
            self._regression._status = 'fail'

        return self._regression.generate_report_data()

    def _run_subprocess(
        self,
        profile: str,
        mode: str,
        timeout: float,
    ) -> 'subprocess.CompletedProcess':
        """Run the test script in a subprocess.

        Args:
            profile: OpenGL profile to use
            mode: 'record' or 'test'
            timeout: Subprocess timeout

        Returns:
            subprocess.CompletedProcess result
        """
        import subprocess

        env = os.environ.copy()
        env['OPENGLCONTEXT_PROFILE'] = profile
        if profile == 'core':
            env['OPENGLCONTEXT_BACKEND'] = 'glfw'

        cmd = [
            sys.executable, self.script_path,
            f'--{mode}',
            '--output-dir', self.reference_dir,
            '--exit-after',
        ]

        return subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            timeout=timeout,
            text=True,
        )
