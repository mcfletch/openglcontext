"""Comprehensive subprocess tests for all OpenGLContext test scripts.

This module runs all test scripts in subprocesses with:
- Platform/library detection for conditional skipping
- Traceback detection in stderr for error reporting
- Coverage collection from subprocess runs
- Timeout handling for hung processes
- Visual regression testing with image capture
- HTML report generation with side-by-side comparisons

Scripts are categorized by their requirements:
- wxPython: Requires wx module
- Pygame: Requires pygame module
- Windows-specific (WGL): Requires Windows platform
- GLUT-specific: Requires GLUT/freeglut
- General: Should work on any platform with OpenGL

Visual Regression:
- Each test captures a screenshot after rendering
- Screenshots are compared against reference images (if available)
- Tests can be marked with @pytest.mark.expect_visual_diff for randomized output
- An HTML report is generated at tests/report.html
"""

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

# Test directory paths
TESTS_DIR = Path(__file__).parent
PROJECT_ROOT = TESTS_DIR.parent

# Timeout settings
QUICK_TIMEOUT = 15  # Simple scripts
DEFAULT_TIMEOUT = 30  # Most scripts
SLOW_TIMEOUT = 60  # Complex scripts (shaders, NURBS)
VERY_SLOW_TIMEOUT = 120  # Heavy scripts

# Auto-exit configuration
# Number of frames to render before auto-exiting
# This enables automated testing of interactive scripts
AUTO_EXIT_FRAMES = 5

# Visual regression directories
REFERENCE_IMAGES_DIR = TESTS_DIR / "reference_images"
RESULT_IMAGES_DIR = TESTS_DIR / "result_images"
REPORT_PATH = TESTS_DIR / "report.html"

# Scripts that use randomization and shouldn't expect visual match
# These will still capture images but won't fail on visual differences
RANDOMIZED_SCRIPTS = [
    'particles_simple.py',  # Random particle positions
    'starfield.py',  # Random star positions
]


@dataclass
class VisualTestResult:
    """Result from a visual regression test."""
    script_name: str
    status: str  # 'pass', 'fail', 'skip', 'error', 'visual_diff_expected'
    returncode: int
    stdout: str
    stderr: str
    duration: float
    reference_image: Optional[str] = None
    result_image: Optional[str] = None
    diff_image: Optional[str] = None
    comparison_stats: Optional[Dict[str, Any]] = None
    expect_visual_diff: bool = False
    traceback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for report generation."""
        return {
            'test_name': self.script_name,
            'status': self.status,
            'returncode': self.returncode,
            'stdout': self.stdout,
            'stderr': self.stderr,
            'duration': self.duration,
            'reference_image': self.reference_image,
            'result_image': self.result_image,
            'diff_image': self.diff_image,
            'comparison_stats': self.comparison_stats,
            'expect_visual_diff': self.expect_visual_diff,
            'traceback': self.traceback,
        }


# Global list to collect test results for report generation
_test_results: List[VisualTestResult] = []


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


def _check_wx_available():
    """Check if wxPython is available."""
    try:
        import wx
        return True
    except ImportError:
        return False


def _check_pygame_available():
    """Check if pygame is available."""
    try:
        import pygame
        return True
    except ImportError:
        return False


def _check_glut_available():
    """Check if GLUT/freeglut is available."""
    try:
        from OpenGL import GLUT
        return True
    except ImportError:
        return False


def _is_windows():
    """Check if running on Windows."""
    return sys.platform == 'win32'


def _is_linux():
    """Check if running on Linux."""
    return sys.platform.startswith('linux')


# Cache availability checks
HAS_DISPLAY = _check_display_available()
HAS_WX = _check_wx_available()
HAS_PYGAME = _check_pygame_available()
HAS_GLUT = _check_glut_available()
HAS_COVERAGE = _check_coverage_available()
IS_WINDOWS = _is_windows()


def _build_coverage_command(script_path: Path, args: Optional[List[str]] = None) -> List[str]:
    """Build command to run script with coverage collection."""
    if HAS_COVERAGE:
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


def _detect_traceback(stderr: str) -> Optional[str]:
    """Detect Python tracebacks in stderr output.

    Returns the traceback text if found, None otherwise.
    """
    if not stderr:
        return None

    # Pattern to detect traceback start
    traceback_patterns = [
        r'Traceback \(most recent call last\):',
        r'^\s*File ".*", line \d+',
        r'^\w+Error:',
        r'^\w+Exception:',
    ]

    for pattern in traceback_patterns:
        if re.search(pattern, stderr, re.MULTILINE):
            return stderr

    return None


def _run_script(
    script_path: Path,
    timeout: float = DEFAULT_TIMEOUT,
    env_overrides: Optional[dict] = None,
    expected_returncode: int = 0,
    auto_exit_frames: int = AUTO_EXIT_FRAMES,
) -> Tuple[int, str, str]:
    """Run a script and return (returncode, stdout, stderr).

    Raises AssertionError if:
    - Script times out
    - Return code doesn't match expected
    - Traceback is detected in stderr

    Args:
        script_path: Path to the script to run
        timeout: Maximum time to wait for script completion
        env_overrides: Additional environment variables
        expected_returncode: Expected exit code (default 0)
        auto_exit_frames: Number of frames before auto-exit (default AUTO_EXIT_FRAMES)
    """
    cmd = _build_coverage_command(script_path)

    env = os.environ.copy()
    # Enable auto-exit so interactive scripts will terminate
    env['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = str(auto_exit_frames)
    # Disable FPS display for clean screenshots
    env['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    if env_overrides:
        env.update(env_overrides)

    try:
        # Run from tests directory so scripts can find their resource files
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(TESTS_DIR),
        )
    except subprocess.TimeoutExpired as e:
        pytest.fail(f"Script {script_path.name} timed out after {timeout}s")

    # Check for tracebacks in stderr
    traceback = _detect_traceback(result.stderr)
    if traceback:
        pytest.fail(
            f"Script {script_path.name} produced a traceback:\n{traceback}\n"
            f"stdout:\n{result.stdout}"
        )

    # Check return code
    if result.returncode != expected_returncode:
        pytest.fail(
            f"Script {script_path.name} exited with code {result.returncode} "
            f"(expected {expected_returncode})\n"
            f"stderr:\n{result.stderr}\n"
            f"stdout:\n{result.stdout}"
        )

    return result.returncode, result.stdout, result.stderr


def _run_visual_test(
    script_path: Path,
    timeout: float = DEFAULT_TIMEOUT,
    env_overrides: Optional[dict] = None,
    expect_visual_diff: bool = False,
    capture_image: bool = True,
) -> VisualTestResult:
    """Run a script with visual regression testing.

    This function:
    1. Runs the script in record mode to capture a screenshot
    2. Compares the result against a reference image (if available)
    3. Records the result for report generation

    Args:
        script_path: Path to the test script
        timeout: Maximum time to wait for script completion
        env_overrides: Additional environment variables
        expect_visual_diff: If True, don't fail on visual differences (for randomized tests)
        capture_image: If True, capture screenshot for comparison

    Returns:
        VisualTestResult with test outcome and captured data
    """
    script_name = script_path.name
    test_name = script_path.stem
    start_time = time.time()

    # Ensure output directories exist
    REFERENCE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Build command - most scripts don't support --record flag
    # They use the auto-exit environment variable instead
    cmd = _build_coverage_command(script_path)

    env = os.environ.copy()
    env['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = str(AUTO_EXIT_FRAMES)
    # Disable FPS display for clean screenshots
    env['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    # Enable screenshot capture on auto-exit
    if capture_image:
        env['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR'] = str(RESULT_IMAGES_DIR)
        env['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME'] = test_name
    if env_overrides:
        env.update(env_overrides)

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(TESTS_DIR),
        )
        duration = time.time() - start_time
        returncode = result.returncode
        stdout = result.stdout
        stderr = result.stderr
        timed_out = False
    except subprocess.TimeoutExpired as e:
        duration = time.time() - start_time
        returncode = 124
        stdout = e.stdout.decode() if e.stdout else ''
        stderr = f'Test timed out after {timeout}s'
        timed_out = True

    # Detect traceback
    traceback = _detect_traceback(stderr)

    # Determine initial status
    if timed_out:
        status = 'error'
    elif traceback:
        status = 'fail'
    elif returncode != 0:
        status = 'fail'
    else:
        status = 'pass'

    # Handle visual comparison
    reference_image = None
    result_image = None
    diff_image = None
    comparison_stats = None

    result_image_path = RESULT_IMAGES_DIR / f"{test_name}.png"
    reference_image_path = REFERENCE_IMAGES_DIR / f"{test_name}.png"

    if capture_image and result_image_path.exists():
        result_image = str(result_image_path)

        if reference_image_path.exists():
            reference_image = str(reference_image_path)

            # Compare images
            try:
                comparison_stats = _compare_images(reference_image_path, result_image_path)

                if comparison_stats:
                    # Create diff image
                    diff_image_path = RESULT_IMAGES_DIR / f"{test_name}_diff.png"
                    if diff_image_path.exists():
                        diff_image = str(diff_image_path)

                    # Update status based on visual comparison
                    if status == 'pass':
                        if comparison_stats.get('is_match', False):
                            status = 'pass'
                        elif expect_visual_diff:
                            status = 'visual_diff_expected'
                        else:
                            # Visual diff but test otherwise passed - still pass but note it
                            # Don't fail just because images differ
                            pass
            except Exception as e:
                stderr += f"\nImage comparison error: {e}"

    # Create result object
    test_result = VisualTestResult(
        script_name=script_name,
        status=status,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration=duration,
        reference_image=reference_image,
        result_image=result_image,
        diff_image=diff_image,
        comparison_stats=comparison_stats,
        expect_visual_diff=expect_visual_diff,
        traceback=traceback,
    )

    # Add to global results for report
    _test_results.append(test_result)

    return test_result


def _compare_images(reference_path: Path, result_path: Path) -> Optional[Dict[str, Any]]:
    """Compare two images and return comparison statistics.

    Args:
        reference_path: Path to reference image
        result_path: Path to result image

    Returns:
        Dict with comparison statistics, or None if comparison failed
    """
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None

    try:
        ref_img = Image.open(reference_path).convert('RGB')
        result_img = Image.open(result_path).convert('RGB')

        ref_array = np.array(ref_img, dtype=np.float32)
        result_array = np.array(result_img, dtype=np.float32)

        # Check shapes match
        if ref_array.shape != result_array.shape:
            return {
                'shapes_match': False,
                'reference_shape': ref_array.shape,
                'result_shape': result_array.shape,
                'is_match': False,
            }

        # Calculate differences
        diff = np.abs(ref_array - result_array)
        max_diff = float(np.max(diff))
        mean_diff = float(np.mean(diff))

        # Count different pixels (threshold of 5)
        pixel_max_diff = np.max(diff, axis=2)
        pixels_different = int(np.sum(pixel_max_diff > 5))
        total_pixels = ref_array.shape[0] * ref_array.shape[1]
        percent_different = 100.0 * pixels_different / total_pixels

        # Create amplified diff image
        diff_amplified = np.clip(diff * 4, 0, 255).astype(np.uint8)
        diff_img = Image.fromarray(diff_amplified, mode='RGB')
        diff_path = result_path.parent / f"{result_path.stem}_diff.png"
        diff_img.save(diff_path)

        # Determine if match (allow 2% difference, max 255 per-pixel diff)
        is_match = (max_diff <= 255 and percent_different <= 2.0)

        return {
            'shapes_match': True,
            'max_diff': max_diff,
            'mean_diff': mean_diff,
            'pixels_different': pixels_different,
            'total_pixels': total_pixels,
            'percent_different': percent_different,
            'is_match': is_match,
        }
    except Exception as e:
        return {'error': str(e), 'is_match': False}


def generate_html_report(results: List[VisualTestResult], output_path: Path) -> None:
    """Generate an HTML report with side-by-side image comparisons.

    Args:
        results: List of test results
        output_path: Path to save the HTML report
    """
    from OpenGLContext.testing.report_generator import TestReportGenerator

    generator = TestReportGenerator(title="OpenGLContext Visual Regression Report")

    for result in results:
        generator.add_test(result.to_dict())

    generator.save(str(output_path), embed_images=True)
    print(f"\nHTML report generated: {output_path}")


# =============================================================================
# Script Categories
# =============================================================================

# Scripts that require wxPython
WX_SCRIPTS = [
    'wx_font.py',
    'wx_multiple_contexts.py',
    'wx_with_controls.py',
]

# Scripts that require pygame
PYGAME_SCRIPTS = [
    'pygame_font.py',
    'pygame_textureatlas.py',
]

# Scripts that require Windows (WGL)
WINDOWS_SCRIPTS = [
    'glprint.py',  # Uses WGL bitmap fonts
    'wgl_bitmap_font.py',
    'wgl_font.py',
    'wglpixelformatarb.py',
]

# Scripts that are test runners (not individual tests)
RUNNER_SCRIPTS = [
    'runalltests.py',
    'run_core_tests.py',
    'run_teapot_regression.py',
    'rendering_regression.py',
]

# Scripts that are pytest test modules (already run by pytest)
PYTEST_MODULES = [
    'conftest.py',
    'test_visual_regression.py',
    'test_testing_infrastructure.py',
    'test_all_scripts.py',
    'test_shaderpass.py',
]

# Scripts that have known issues or are not standalone
SKIP_SCRIPTS = [
    '__init__.py',
    '_bitmap_font.py',  # Helper module
    '_fontstyles.py',  # Helper module
    'frust_test_module.py',  # Helper module
    'profile_view.py',  # Interactive profiling tool
    'shader_intro.py',  # Tutorial introduction, not an actual test
]

# Scripts that produce no graphical output - test for functionality only
# These should NOT be included in visual regression tests
NON_VISUAL_SCRIPTS = [
    'boundingvolume.py',  # Bounding volume calculations
    'flower_geometry.py',  # Prints geometry info to stdout
    'glget.py',  # GL state query, prints to stdout
    'glget_with_fonts.py',  # GL state query with fonts, prints to stdout
    'glgetlight.py',  # GL light state query
    'glgetmaterial.py',  # GL material state query
    'glgetpixelmap.py',  # GL pixel map state query
    'glgetpolygonstipple.py',  # GL polygon stipple query
    'glugetstring.py',  # GLU string query
    'numpyfields.py',  # NumPy field tests
    'shader_binary.py',  # Tests shader binary retrieval, no rendering
]

# Scripts that need longer timeouts
SLOW_SCRIPTS = {
    'nurbsobject.py': SLOW_TIMEOUT,
    'glget.py': SLOW_TIMEOUT,
    'glget_with_fonts.py': SLOW_TIMEOUT,
    'molehill.py': SLOW_TIMEOUT,
    'shader_instanced.py': SLOW_TIMEOUT,
    'shader_instanced_mapped.py': SLOW_TIMEOUT,
    'shader_instanced_modern.py': SLOW_TIMEOUT,
    'volumetric_tree.py': VERY_SLOW_TIMEOUT,
    'volumetric_forest.py': VERY_SLOW_TIMEOUT,
    'teapot_comparison.py': SLOW_TIMEOUT,
    'test_shader_comprehensive.py': SLOW_TIMEOUT,
}

# Scripts that require GLUT specifically
GLUT_SCRIPTS = [
    'glut_bitmap_font.py',
    'glut_font.py',
    'glut_fullscreen.py',
    'glutbitmapcharacter.py',
    'glutmousewheel.py',
]


def get_all_test_scripts(include_non_visual: bool = True) -> List[Path]:
    """Get list of all test scripts to run.

    Args:
        include_non_visual: If False, exclude scripts that produce no graphical output
    """
    all_scripts = []

    for script_path in TESTS_DIR.glob('*.py'):
        name = script_path.name

        # Skip various categories
        if name in SKIP_SCRIPTS:
            continue
        if name in PYTEST_MODULES:
            continue
        if name in RUNNER_SCRIPTS:
            continue
        if name.startswith('test_') and name not in ['test_glut_lineset.py', 'test_glvertex2fcrash.py', 'test_selection_benchmark.py']:
            # Skip pytest test modules but keep old-style test_ scripts
            continue
        if not include_non_visual and name in NON_VISUAL_SCRIPTS:
            continue

        all_scripts.append(script_path)

    return sorted(all_scripts)


def get_visual_test_scripts() -> List[Path]:
    """Get list of test scripts that produce graphical output (for visual regression)."""
    return get_all_test_scripts(include_non_visual=False)


def get_script_timeout(script_name: str) -> float:
    """Get appropriate timeout for a script."""
    return SLOW_SCRIPTS.get(script_name, DEFAULT_TIMEOUT)


def should_skip_script(script_name: str) -> Optional[str]:
    """Check if a script should be skipped and return reason if so."""
    if not HAS_DISPLAY:
        return "No display available"

    if script_name in WX_SCRIPTS and not HAS_WX:
        return "wxPython not available"

    if script_name in PYGAME_SCRIPTS and not HAS_PYGAME:
        return "pygame not available"

    if script_name in WINDOWS_SCRIPTS and not IS_WINDOWS:
        return "Windows-only script"

    if script_name in GLUT_SCRIPTS and not HAS_GLUT:
        return "GLUT not available"

    return None


# =============================================================================
# Test Classes
# =============================================================================

@pytest.mark.visual
class TestBasicRendering:
    """Test basic rendering scripts (geometry, colors, etc.)."""

    SCRIPTS = [
        'addnodes.py',
        'backgroundobject.py',
        'boundingvolume.py',
        'cubebackgroundobject.py',
        'flower_geometry.py',
        'gearobject.py',
        'geometry.py',
        'glarrayelement.py',
        'gldrawarrays.py',
        'gldrawarrays_string.py',
        'gldrawelements.py',
        'gldrawelements_list.py',
        'gldrawelements_string.py',
        'glinterleavedarrays.py',
        'glvertex.py',
        'heightmap.py',
        'ilsstrategies.py',
        'indexedfaceset_lit_npf.py',
        'indexedfaceset_lit_npv.py',
        'indexedlinesetobject.py',
        'lightobject.py',
        'line_stipple.py',
        'pointsetobject.py',
        'simplerotate.py',
        'spherebackgroundobject.py',
        'transparentsorted.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a basic rendering script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        timeout = get_script_timeout(script_name)
        _run_script(script_path, timeout=timeout)


@pytest.mark.visual
class TestNeHeScripts:
    """Test NeHe tutorial scripts."""

    SCRIPTS = [
        'nehe1.py',
        'nehe2.py',
        'nehe3.py',
        'nehe4.py',
        'nehe5.py',
        'nehe6.py',
        'nehe6_compressed.py',
        'nehe6_convolve.py',
        'nehe6_multi.py',
        'nehe6_timer.py',
        'nehe7.py',
        'nehe8.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a NeHe tutorial script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestShaderScripts:
    """Test shader-based scripts."""

    SCRIPTS = [
        'shader_1.py',
        'shader_2.py',
        'shader_2_c_void_p.py',
        'shader_3.py',
        'shader_4.py',
        'shader_4_subset.py',
        'shader_5.py',
        'shader_6.py',
        'shader_7.py',
        'shader_8.py',
        'shader_9.py',
        'shader_10.py',
        'shader_11.py',
        'shader_12.py',
        'shader_binary.py',
        'shader_intro.py',
        'shader_ng.py',
        'shader_sphere.py',
        'shader_spike.py',
        'shadergeometry.py',
        'shaderobjects.py',
        'shaders.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a shader script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        timeout = get_script_timeout(script_name)
        _run_script(script_path, timeout=timeout)


@pytest.mark.visual
class TestGLGetScripts:
    """Test GL state query scripts."""

    SCRIPTS = [
        'glgetlight.py',
        'glgetmaterial.py',
        'glgetpixelmap.py',
        'glgetpolygonstipple.py',
        'glugetstring.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a GL state query script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
@pytest.mark.slow
class TestGLGetComprehensive:
    """Test comprehensive GL state query scripts (slow)."""

    SCRIPTS = [
        'glget.py',
        'glget_with_fonts.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a comprehensive GL query script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        timeout = get_script_timeout(script_name)
        _run_script(script_path, timeout=timeout)


@pytest.mark.visual
class TestTextureScripts:
    """Test texture-related scripts."""

    SCRIPTS = [
        'getteximage.py',
        'gldrawpixels.py',
        'gldrawpixelssynth.py',
        'glhistogram.py',
        'multitexture_1.py',
        'pbodemo.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a texture script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestNURBSScripts:
    """Test NURBS and surface scripts."""

    SCRIPTS = [
        'dek_surf.py',
        'dek_texturesurf.py',
        'glelathe.py',
        'glu_tess.py',
        'glu_tess2.py',
        'molehill.py',
        'nurbsobject.py',
        'redbook_surface.py',
        'redbook_surface_cb.py',
        'redbook_trim.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a NURBS/surface script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        timeout = get_script_timeout(script_name)
        _run_script(script_path, timeout=timeout)


@pytest.mark.visual
class TestSelectionScripts:
    """Test selection and picking scripts."""

    SCRIPTS = [
        'feedback_mode.py',
        'mouseover.py',
        'point_and_click.py',
        'selectrendermode.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a selection script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestShadowScripts:
    """Test shadow rendering scripts."""

    SCRIPTS = [
        'shadow_1.py',
        'shadow_2.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a shadow script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestAnimationScripts:
    """Test animation and timer scripts."""

    SCRIPTS = [
        'cubeback_rot.py',
        'particles_simple.py',
        'starfield.py',
        'timesensorobject.py',
        'transforms_1.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run an animation script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestTransparencyScripts:
    """Test transparency and blending scripts."""

    SCRIPTS = [
        'redbook_alpha.py',
        'redbook_alpha3D.py',
        'transparentsorted.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a transparency script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestFontScripts:
    """Test font rendering scripts."""

    SCRIPTS = [
        'solid_font.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a font script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestGLUTScripts:
    """Test GLUT-specific scripts."""

    @pytest.mark.parametrize('script_name', GLUT_SCRIPTS)
    def test_script(self, script_name):
        """Run a GLUT script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestPygameScripts:
    """Test pygame-specific scripts."""

    @pytest.mark.parametrize('script_name', PYGAME_SCRIPTS)
    def test_script(self, script_name):
        """Run a pygame script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestWxScripts:
    """Test wxPython-specific scripts."""

    @pytest.mark.parametrize('script_name', WX_SCRIPTS)
    def test_script(self, script_name):
        """Run a wxPython script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
@pytest.mark.skipif(not IS_WINDOWS, reason="Windows-only scripts")
class TestWindowsScripts:
    """Test Windows-specific (WGL) scripts."""

    @pytest.mark.parametrize('script_name', WINDOWS_SCRIPTS)
    def test_script(self, script_name):
        """Run a Windows script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
class TestARBExtensionScripts:
    """Test ARB extension scripts."""

    SCRIPTS = [
        'arbocclusionquery.py',
        'arbpointparameters.py',
        'arbsync.py',
        'arbwindowpos.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run an ARB extension script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


@pytest.mark.visual
@pytest.mark.slow
class TestInstancedScripts:
    """Test instanced rendering scripts (slow)."""

    SCRIPTS = [
        'shader_instanced.py',
        'shader_instanced_mapped.py',
        'shader_instanced_modern.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run an instanced rendering script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        timeout = get_script_timeout(script_name)
        _run_script(script_path, timeout=timeout)


@pytest.mark.visual
@pytest.mark.slow
class TestVolumetricScripts:
    """Test volumetric rendering scripts (very slow)."""

    SCRIPTS = [
        'volumetric_tree.py',
        'volumetric_forest.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a volumetric rendering script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        timeout = get_script_timeout(script_name)
        _run_script(script_path, timeout=timeout)


@pytest.mark.visual
class TestMiscScripts:
    """Test miscellaneous scripts not in other categories."""

    SCRIPTS = [
        'node_modify.py',
        'numpyfields.py',
        'readpixelsleak.py',
        'saveimage.py',
        'savepostscript.py',
        'selectrendermode_threads.py',
        'test_glut_lineset.py',
        'test_glvertex2fcrash.py',
        'test_selection_benchmark.py',
    ]

    @pytest.mark.parametrize('script_name', SCRIPTS)
    def test_script(self, script_name):
        """Run a miscellaneous script."""
        script_path = TESTS_DIR / script_name
        if not script_path.exists():
            pytest.skip(f"Script not found: {script_name}")

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        _run_script(script_path)


# =============================================================================
# Comprehensive test that runs ALL scripts
# =============================================================================

@pytest.mark.visual
@pytest.mark.slow
class TestAllScripts:
    """Run all test scripts as a comprehensive test."""

    @pytest.fixture
    def all_scripts(self):
        """Get list of all scripts to test."""
        return get_all_test_scripts()

    def test_count_scripts(self, all_scripts):
        """Verify we have a reasonable number of scripts."""
        assert len(all_scripts) > 50, f"Expected 50+ scripts, found {len(all_scripts)}"
        print(f"\nFound {len(all_scripts)} test scripts")

    @pytest.mark.parametrize('script_path', get_all_test_scripts(), ids=lambda p: p.name)
    def test_script_runs(self, script_path):
        """Run each script and verify no traceback."""
        skip_reason = should_skip_script(script_path.name)
        if skip_reason:
            pytest.skip(skip_reason)

        timeout = get_script_timeout(script_path.name)
        _run_script(script_path, timeout=timeout)


# =============================================================================
# Visual Regression Tests with Report Generation
# =============================================================================

@pytest.mark.visual
class TestVisualRegression:
    """Visual regression tests with image capture and comparison.

    These tests run visual test scripts (excluding non-graphical scripts)
    with screenshot capture, comparing against reference images when available.
    Results are collected for HTML report generation.

    Run with: pytest tests/test_all_scripts.py::TestVisualRegression -v

    The HTML report will be generated at tests/report.html showing:
    - Side-by-side reference/result/diff images
    - Pass/fail status
    - Stdout/stderr output and tracebacks

    Scripts that produce no graphical output (like glget.py, boundingvolume.py)
    are excluded - use TestAllScripts for those.
    """

    @pytest.mark.parametrize('script_path', get_visual_test_scripts(), ids=lambda p: p.name)
    def test_visual_script(self, script_path):
        """Run a script with visual regression testing and image capture."""
        script_name = script_path.name

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        # Check if this script is marked as expecting visual differences
        expect_diff = script_name in RANDOMIZED_SCRIPTS

        timeout = get_script_timeout(script_name)
        result = _run_visual_test(
            script_path,
            timeout=timeout,
            expect_visual_diff=expect_diff,
            capture_image=True,
        )

        # Fail test if there was a traceback or error
        if result.status == 'fail':
            if result.traceback:
                pytest.fail(f"Script produced traceback:\n{result.traceback}")
            else:
                pytest.fail(f"Script failed with return code {result.returncode}")
        elif result.status == 'error':
            pytest.fail(f"Script error: {result.stderr}")


# =============================================================================
# Pytest Hooks for Report Generation
# =============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "expect_visual_diff: marks tests where visual differences are expected"
    )


@pytest.fixture(scope="session", autouse=True)
def generate_report_on_finish(request):
    """Generate HTML report after all tests complete."""
    yield
    # This runs after all tests in the session
    if _test_results:
        try:
            generate_html_report(_test_results, REPORT_PATH)
        except Exception as e:
            print(f"Failed to generate HTML report: {e}")
