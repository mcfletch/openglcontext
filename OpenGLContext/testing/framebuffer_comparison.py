#! /usr/bin/env python
"""Framebuffer comparison utilities for rendering regression testing

This module provides reusable utilities for comparing rendered output:
- Side-by-side comparison (two different rendering paths)
- Regression testing (current vs saved reference images)

Usage:
    from OpenGLContext.testing.framebuffer_comparison import FramebufferCapture, compare_images

    # Capture current framebuffer
    capture = FramebufferCapture()
    capture.capture()

    # Compare with reference
    result = capture.compare_with_reference('test_name')

    # Or compare two captures
    result = compare_images(capture1.pixels, capture2.pixels)
"""
from __future__ import print_function
import os
import numpy as np
from OpenGL.GL import (
    glReadPixels, glReadBuffer, glGetIntegerv,
    GL_VIEWPORT, GL_BACK, GL_RGB, GL_FLOAT
)

# Default directory for reference images
DEFAULT_REFERENCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'tests', 'reference_images'
)


class ComparisonResult:
    """Results from comparing two framebuffer captures"""

    def __init__(self, pixels_a, pixels_b, threshold=0.01):
        """Calculate comparison statistics

        Args:
            pixels_a: First image as numpy array (H, W, 3)
            pixels_b: Second image as numpy array (H, W, 3)
            threshold: Minimum difference to consider pixels different (0-1)
        """
        self.shape_a = pixels_a.shape
        self.shape_b = pixels_b.shape
        self.shapes_match = pixels_a.shape == pixels_b.shape

        if not self.shapes_match:
            self.max_diff = 1.0
            self.mean_diff = 1.0
            self.pixels_different = -1
            self.total_pixels = -1
            self.percent_different = 100.0
            self.diff_image = None
            return

        # Calculate differences
        diff = np.abs(pixels_a.astype(np.float32) - pixels_b.astype(np.float32))

        self.max_diff = float(np.max(diff))
        self.mean_diff = float(np.mean(diff))
        self.diff_image = diff

        # Count pixels that differ by more than threshold
        flat_a = pixels_a.reshape(-1, 3)
        flat_b = pixels_b.reshape(-1, 3)
        diff_flat = np.abs(flat_a - flat_b)
        self.pixels_different = int(np.sum(np.any(diff_flat > threshold, axis=1)))
        self.total_pixels = flat_a.shape[0]
        self.percent_different = 100.0 * self.pixels_different / self.total_pixels if self.total_pixels > 0 else 0.0

    def is_match(self, max_diff_threshold=0.05, max_percent_different=1.0):
        """Check if images match within acceptable tolerances

        Args:
            max_diff_threshold: Maximum allowed pixel difference (0-1)
            max_percent_different: Maximum percent of pixels that can differ

        Returns:
            bool: True if images match within tolerances
        """
        if not self.shapes_match:
            return False
        return self.max_diff <= max_diff_threshold and self.percent_different <= max_percent_different

    def __str__(self):
        if not self.shapes_match:
            return f"Shape mismatch: {self.shape_a} vs {self.shape_b}"
        return (
            f"Max diff: {self.max_diff:.4f}, "
            f"Mean diff: {self.mean_diff:.6f}, "
            f"Pixels different: {self.pixels_different}/{self.total_pixels} "
            f"({self.percent_different:.2f}%)"
        )


class FramebufferCapture:
    """Captures and stores framebuffer contents for comparison"""

    def __init__(self, reference_dir=None):
        """Initialize capture

        Args:
            reference_dir: Directory for saving/loading reference images
        """
        self.reference_dir = reference_dir or DEFAULT_REFERENCE_DIR
        self.pixels = None
        self.width = 0
        self.height = 0

    def capture(self, x=None, y=None, width=None, height=None):
        """Capture current framebuffer contents

        Args:
            x, y: Lower-left corner of region (default: 0, 0)
            width, height: Size of region (default: full viewport)

        Returns:
            numpy array of shape (height, width, 3) with float values 0-1
        """
        viewport = glGetIntegerv(GL_VIEWPORT)
        vp_x, vp_y, vp_width, vp_height = viewport

        x = x if x is not None else 0
        y = y if y is not None else 0
        width = width if width is not None else vp_width
        height = height if height is not None else vp_height

        glReadBuffer(GL_BACK)
        pixels = glReadPixels(x, y, width, height, GL_RGB, GL_FLOAT)

        # Reshape to (height, width, 3)
        self.pixels = np.array(pixels, dtype=np.float32).reshape(height, width, 3)
        self.width = width
        self.height = height

        return self.pixels

    def capture_left_half(self):
        """Capture the left half of the viewport"""
        viewport = glGetIntegerv(GL_VIEWPORT)
        width, height = viewport[2], viewport[3]
        half_width = width // 2
        return self.capture(0, 0, half_width, height)

    def capture_right_half(self):
        """Capture the right half of the viewport"""
        viewport = glGetIntegerv(GL_VIEWPORT)
        width, height = viewport[2], viewport[3]
        half_width = width // 2
        return self.capture(half_width, 0, half_width, height)

    def save_reference(self, name):
        """Save current capture as reference image

        Args:
            name: Name for the reference (used as filename base)

        Returns:
            Path to saved file
        """
        if self.pixels is None:
            raise ValueError("No pixels captured - call capture() first")

        os.makedirs(self.reference_dir, exist_ok=True)
        path = os.path.join(self.reference_dir, f"{name}.npy")
        np.save(path, self.pixels)
        return path

    def load_reference(self, name):
        """Load a reference image

        Args:
            name: Name of the reference to load

        Returns:
            numpy array of reference image, or None if not found
        """
        path = os.path.join(self.reference_dir, f"{name}.npy")
        if os.path.exists(path):
            return np.load(path)
        return None

    def compare_with_reference(self, name, threshold=0.01):
        """Compare current capture with saved reference

        Args:
            name: Name of reference to compare with
            threshold: Minimum difference to consider pixels different

        Returns:
            ComparisonResult, or None if reference doesn't exist
        """
        if self.pixels is None:
            raise ValueError("No pixels captured - call capture() first")

        reference = self.load_reference(name)
        if reference is None:
            return None

        return ComparisonResult(self.pixels, reference, threshold)

    def has_reference(self, name):
        """Check if a reference image exists"""
        path = os.path.join(self.reference_dir, f"{name}.npy")
        return os.path.exists(path)


def compare_images(pixels_a, pixels_b, threshold=0.01):
    """Compare two pixel arrays

    Args:
        pixels_a: First image as numpy array
        pixels_b: Second image as numpy array
        threshold: Minimum difference to consider pixels different

    Returns:
        ComparisonResult
    """
    return ComparisonResult(pixels_a, pixels_b, threshold)


def compare_side_by_side():
    """Compare left and right halves of current framebuffer

    Returns:
        ComparisonResult comparing left half vs right half
    """
    capture = FramebufferCapture()
    left = capture.capture_left_half()

    capture2 = FramebufferCapture()
    right = capture2.capture_right_half()

    return compare_images(left, right)


class RegressionTestMixin:
    """Mixin for OpenGLContext test contexts that adds regression testing

    Usage:
        class MyTestContext(RegressionTestMixin, BaseContext):
            test_name = "my_rendering_test"

            def Render(self, mode):
                # ... render scene ...
                pass

    Press 'r' to save current render as reference
    Press 't' to test current render against reference
    """

    test_name = "unnamed_test"
    _capture = None

    def OnInit_regression(self):
        """Call this from OnInit to set up regression test handlers"""
        self._capture = FramebufferCapture()
        self.addEventHandler('keyboard', name='r', function=self._save_reference)
        self.addEventHandler('keyboard', name='t', function=self._test_against_reference)

    def _save_reference(self, event):
        """Save current framebuffer as reference"""
        self._capture.capture()
        path = self._capture.save_reference(self.test_name)
        print(f"Saved reference to: {path}")

    def _test_against_reference(self, event):
        """Test current framebuffer against reference"""
        self._capture.capture()

        if not self._capture.has_reference(self.test_name):
            print(f"No reference found for '{self.test_name}'. Press 'r' to save one.")
            return

        result = self._capture.compare_with_reference(self.test_name)
        print(f"\nRegression test result for '{self.test_name}':")
        print(f"  {result}")

        if result.is_match():
            print("  PASS - Output matches reference")
        else:
            print("  FAIL - Output differs from reference")


class AutomatedRegressionTest:
    """Automated regression test runner for headless testing

    Usage:
        from OpenGLContext.testing.framebuffer_comparison import AutomatedRegressionTest

        def setup_scene(context):
            # Configure the scene
            pass

        def render_scene(context, mode):
            # Render the scene
            pass

        test = AutomatedRegressionTest(
            test_name="my_test",
            setup_func=setup_scene,
            render_func=render_scene,
        )
        result = test.run()
        assert result.is_match(), f"Regression: {result}"
    """

    def __init__(self, test_name, setup_func=None, render_func=None, reference_dir=None):
        """Initialize automated test

        Args:
            test_name: Name for this test (used for reference images)
            setup_func: Function(context) to set up the scene
            render_func: Function(context, mode) to render the scene
            reference_dir: Directory for reference images
        """
        self.test_name = test_name
        self.setup_func = setup_func
        self.render_func = render_func
        self.capture = FramebufferCapture(reference_dir)
        self.result = None

    def run(self, update_reference=False):
        """Run the regression test

        Args:
            update_reference: If True, save as new reference instead of comparing

        Returns:
            ComparisonResult if comparing, or path to saved reference if updating
        """
        # This would need integration with a headless rendering context
        # For now, this is a placeholder for the API
        raise NotImplementedError(
            "AutomatedRegressionTest.run() requires headless context support. "
            "Use RegressionTestMixin for interactive testing."
        )
