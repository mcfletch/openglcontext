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
    'audio_spatial.py',  # An emitter orbits on a wall clock
    'particles_effects.py',  # Emitters run on a wall clock
    'particles_simple.py',  # Random particle positions
    'starfield.py',  # Random star positions
    'teapot_ceramic.py',  # Auto-rotates by wall clock; captured angle varies
    # The feature demos that move. Each is driven from the clock so that what
    # it demonstrates is visible without a key being held, which means the
    # frame a capture lands on is not the same one twice.
    'water_demo.py',  # Wave time advances every frame
    'hud_demo.py',  # Meters sweep and messages expire on a timer
    'crowd_demo.py',  # 150 figures walking, each at its own point in the stride
    'telemetry_demo.py',  # Bodies orbit on the clock
    'recording_demo.py',  # The carousel orbits and bobs on the clock
]

# Single source of truth for the visual-diff tolerance. The gate
# is percentage-based, not pixel-exact: cross-GPU rasterization, anti-aliasing
# and gamma differ, so a handful of edge pixels may legitimately vary while a
# black or wrong-colour frame differs across almost the whole image (finding
# 2.9 / 4.32). PIXEL_DIFF_THRESHOLD is the per-channel delta that counts a pixel
# as "different"; MAX_PERCENT_DIFFERENT is how many such pixels are tolerated.
PIXEL_DIFF_THRESHOLD = 5
MAX_PERCENT_DIFFERENT = 2.0


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


from OpenGLContext.testing.display import (
    OFFSCREEN_GL_PLATFORMS, display_available as _check_display_available,
)


def _check_wx_available():
    """Whether wxPython can be cleanly imported in this environment.

    Catches every failure, not just ImportError: wxPython's own package init can
    raise AttributeError from a circular import in some collection orders, and an
    availability probe must report "unavailable" rather than crash collection.
    """
    try:
        import wx
        return True
    except Exception:
        return False


def _check_pygame_available():
    """Whether pygame can be cleanly imported (any failure -> unavailable)."""
    try:
        import pygame
        return True
    except Exception:
        return False


def _check_glut_available():
    """Whether GLUT/freeglut can actually create a window in this environment.

    Importable is not enough: freeglut needs an X display and is completely broken
    under Wayland (it cannot open a display), so a Wayland session reports GLUT as
    unavailable and GLUT-only demos are skipped rather than failed.
    """
    if os.environ.get('WAYLAND_DISPLAY'):
        return False
    try:
        from OpenGL import GLUT
        return True
    except Exception:
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


# Rendering-configuration environment variables that other test modules set at
# their module scope to configure their own in-process GL contexts. pytest imports
# every test module during collection, so those assignments land in this process's
# environment and, left in place, would be inherited by the scripts launched here --
# switching the profile/renderer/shadows a script renders under (making captures
# non-deterministic) or, for the glut backend, breaking window creation entirely on
# Wayland. Drop them so each script runs in its default configuration, exactly as it
# does when this file is run on its own.
_LEAKED_RENDER_CONFIG_VARS = (
    'OPENGLCONTEXT_PROFILE',
    'OPENGLCONTEXT_BACKEND',
    'OPENGLCONTEXT_RENDERER',
    'OPENGLCONTEXT_SHADOWS',
    'OPENGLCONTEXT_SHADOW_CASCADES',
    'OPENGLCONTEXT_IBL',
    'OPENGLCONTEXT_IBL_INTENSITY',
    'OPENGLCONTEXT_INSTANCE_MIN',
    'OPENGLCONTEXT_TRANSMISSION',
)


def _subprocess_env(auto_exit_frames: int = AUTO_EXIT_FRAMES) -> dict:
    """Build the base environment for a launched script.

    Starts from the current environment with the leaked rendering-config vars
    removed (see _LEAKED_RENDER_CONFIG_VARS), then applies the deterministic
    settings the visual suite relies on.
    """
    env = os.environ.copy()
    for var in _LEAKED_RENDER_CONFIG_VARS:
        env.pop(var, None)
    # Enable auto-exit so interactive scripts will terminate
    env['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = str(auto_exit_frames)
    # Disable FPS display for clean screenshots
    env['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    # Disable distance-LOD so tessellation stays at full detail (stable references)
    env['OPENGLCONTEXT_LOD'] = '0'
    # No sound. A suite run launches every demo in turn, and a developer running
    # it should not have tones played at them for its duration -- nor should a
    # build machine contend for an audio device it may share. The audio nodes
    # and their scene traversal still run; only the device is not opened
    # (OpenGLContext.audio.scene), so the capture is of exactly the same frame.
    env['OPENGLCONTEXT_AUDIO'] = '0'
    return env


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

    env = _subprocess_env(auto_exit_frames)
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

    env = _subprocess_env(AUTO_EXIT_FRAMES)
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

                    # Update status based on visual comparison:
                    # a real pixel difference is a failure unless the script is
                    # flagged as producing expected (randomized) differences.
                    if status == 'pass':
                        if comparison_stats.get('is_match', False):
                            status = 'pass'
                        elif expect_visual_diff:
                            status = 'visual_diff_expected'
                        else:
                            status = 'visual_diff'
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

    # Delegate the pixel math to the single implementation in the shipped
    # package rather than keeping a second copy here.
    from OpenGLContext.testing.framebuffer_comparison import compare_images

    try:
        ref_array = np.array(Image.open(reference_path).convert('RGB'), dtype=np.uint8)
        result_array = np.array(Image.open(result_path).convert('RGB'), dtype=np.uint8)

        result = compare_images(ref_array, result_array, threshold=PIXEL_DIFF_THRESHOLD)

        if not result.shapes_match:
            return {
                'shapes_match': False,
                'reference_shape': ref_array.shape,
                'result_shape': result_array.shape,
                'is_match': False,
            }

        # Save an amplified diff image for the HTML report.
        diff_img = Image.fromarray(result.diff_image, mode='RGB')
        diff_path = result_path.parent / f"{result_path.stem}_diff.png"
        diff_img.save(diff_path)

        # Real gate: a differing frame must fail. The percentage
        # metric is the meaningful one; the old per-pixel ceiling was the maximum
        # possible value and so never rejected anything. max_diff is reported for
        # diagnostics only.
        is_match = result.percent_different <= MAX_PERCENT_DIFFERENT

        return {
            'shapes_match': True,
            'max_diff': result.max_diff,
            'mean_diff': result.mean_diff,
            'pixels_different': result.pixels_different,
            'total_pixels': result.total_pixels,
            'percent_different': result.percent_different,
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

    # Reference images by path rather than base64-embedding them; embedding
    # every reference/result/diff PNG balloons report.html to many MB (5.7).
    generator.save(str(output_path), embed_images=False)
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
    'diag_live.py',   # interactive perf monitor, driven by hand (never auto-run)
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
    '_gltf_toggle_driver.py',  # Subprocess driver for test_gltf_view_physics_toggle
    'frust_test_module.py',  # Helper module
    'profile_view.py',  # Interactive profiling tool
    'shader_intro.py',  # Tutorial introduction, not an actual test
]

# Demos of features that no longer exist in the library; skipped with a visible
# reason (rather than silently dropped) until they are rewritten or removed.
OBSOLETE_SCRIPTS = {
    'savepostscript.py': 'uses the removed gl2ps PostScript render pass',
    'shadow_1.py': 'uses the removed FlatPass.renderGeometry (old visitor pass API)',
    'shadow_2.py': 'uses the removed FlatPass.renderGeometry (old visitor pass API)',
}

# Scripts that produce no graphical output - test for functionality only
# These should NOT be included in visual regression tests
NON_VISUAL_SCRIPTS = [
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
    'teapot_comparison.py': SLOW_TIMEOUT,
    'test_shader_comprehensive.py': SLOW_TIMEOUT,
}

# Scripts that require GLUT specifically (the GLUT backend or GLUT draw helpers
# like glutSolidSphere, which need glutInit + an X display).
GLUT_SCRIPTS = [
    'glut_bitmap_font.py',
    'glut_font.py',
    'glut_fullscreen.py',
    'glutbitmapcharacter.py',
    'glutmousewheel.py',
    'glut_lineset.py',
    'test_glut_lineset.py',
    'redbook_alpha3D.py',
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


# Glob the test directory once: each parametrize decorator used to
# re-run the full directory walk at collection time. Visual vs non-visual is
# decided per-script in the runner (NON_VISUAL_SCRIPTS), so one list suffices.
_ALL_TEST_SCRIPTS = get_all_test_scripts()


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

    if script_name in OBSOLETE_SCRIPTS:
        return "obsolete demo: %s" % OBSOLETE_SCRIPTS[script_name]

    return None


# =============================================================================
# Test Categories -> a single table
#
# One data table replaces ~20 near-identical copy-paste classes. Each entry is
# {category: {"scripts": [...], "slow": bool}}. Platform categories reuse the
# module-level *_SCRIPTS constants and rely on should_skip_script() for skips.
# =============================================================================

SCRIPT_CATEGORIES = {
    'basic': {
        "slow": False,
        "scripts": [
            'addnodes.py',
            'backgroundobject.py',
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
        ],
    },
    'nehe': {
        "slow": False,
        "scripts": [
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
        ],
    },
    'shader': {
        "slow": False,
        "scripts": [
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
        ],
    },
    'glget': {
        "slow": False,
        "scripts": [
            'glgetlight.py',
            'glgetmaterial.py',
            'glgetpixelmap.py',
            'glgetpolygonstipple.py',
            'glugetstring.py',
        ],
    },
    'glget_comprehensive': {
        "slow": True,
        "scripts": [
            'glget.py',
            'glget_with_fonts.py',
        ],
    },
    'texture': {
        "slow": False,
        "scripts": [
            'getteximage.py',
            'gldrawpixels.py',
            'gldrawpixelssynth.py',
            'glhistogram.py',
            'multitexture_1.py',
            'pbodemo.py',
        ],
    },
    'nurbs': {
        "slow": False,
        "scripts": [
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
        ],
    },
    'selection': {
        "slow": False,
        "scripts": [
            'feedback_mode.py',
            'mouseover.py',
            'point_and_click.py',
            'selectrendermode.py',
        ],
    },
    'shadow': {
        "slow": False,
        "scripts": [
            'shadow_1.py',
            'shadow_2.py',
        ],
    },
    'animation': {
        "slow": False,
        "scripts": [
            'cubeback_rot.py',
            'particles_simple.py',
            'starfield.py',
            'timesensorobject.py',
            'transforms_1.py',
        ],
    },
    'transparency': {
        "slow": False,
        "scripts": [
            'redbook_alpha.py',
            'redbook_alpha3D.py',
            'transparentsorted.py',
        ],
    },
    'font': {
        "slow": False,
        "scripts": [
            'solid_font.py',
        ],
    },
    'arb': {
        "slow": False,
        "scripts": [
            'arbocclusionquery.py',
            'arbpointparameters.py',
            'arbsync.py',
            'arbwindowpos.py',
        ],
    },
    'instanced': {
        "slow": True,
        "scripts": [
            'shader_instanced.py',
            'shader_instanced_mapped.py',
            'shader_instanced_modern.py',
        ],
    },
    'misc': {
        "slow": False,
        "scripts": [
            'node_modify.py',
            'numpyfields.py',
            'readpixelsleak.py',
            'saveimage.py',
            'savepostscript.py',
            'selectrendermode_threads.py',
            'test_glut_lineset.py',
            'test_glvertex2fcrash.py',
            'test_selection_benchmark.py',
        ],
    },
    "glut": {"slow": False, "scripts": GLUT_SCRIPTS},
    "pygame": {"slow": False, "scripts": PYGAME_SCRIPTS},
    "wx": {"slow": False, "scripts": WX_SCRIPTS},
    "windows": {"slow": False, "scripts": WINDOWS_SCRIPTS},
}


# Scripts that get a slow marker: those with an explicit slow timeout, plus every
# script in a category flagged "slow" in SCRIPT_CATEGORIES.
_SLOW_SCRIPT_NAMES = set(SLOW_SCRIPTS) | {
    name
    for spec in SCRIPT_CATEGORIES.values() if spec.get("slow")
    for name in spec["scripts"]
}


def _all_script_params():
    """One parametrize list over every runnable script, slow-marked as needed."""
    params = []
    for path in _ALL_TEST_SCRIPTS:
        marks = [pytest.mark.slow] if path.name in _SLOW_SCRIPT_NAMES else []
        params.append(pytest.param(path, marks=marks, id=path.name))
    return params


_SCRIPT_PARAMS = _all_script_params()


@pytest.mark.visual
class TestScripts:
    """Run every test script once; capture + compare an image when it renders.

    This single runner supersedes the former TestScriptCategories / TestAllScripts
    / TestVisualRegression, which each independently subprocess-launched nearly the
    same script list 2-3x per session. Visual scripts (everything
    not in NON_VISUAL_SCRIPTS) go through the image-capturing regression path;
    non-visual scripts are just run and checked for tracebacks.

    Run with: pytest tests/test_all_scripts.py -v
    The HTML report is written to tests/report.html.
    """

    def test_count_scripts(self):
        """Sanity: a reasonable number of scripts was discovered."""
        assert len(_ALL_TEST_SCRIPTS) > 50, (
            f"Expected 50+ scripts, found {len(_ALL_TEST_SCRIPTS)}")

    @pytest.mark.parametrize('script_path', _SCRIPT_PARAMS)
    def test_script(self, script_path):
        """Run one script; visual scripts also capture and regress an image."""
        script_name = script_path.name

        skip_reason = should_skip_script(script_name)
        if skip_reason:
            pytest.skip(skip_reason)

        timeout = get_script_timeout(script_name)

        if script_name in NON_VISUAL_SCRIPTS:
            # No graphical output to capture; just run and check for tracebacks.
            _run_script(script_path, timeout=timeout)
            return

        result = _run_visual_test(
            script_path,
            timeout=timeout,
            expect_visual_diff=script_name in RANDOMIZED_SCRIPTS,
            capture_image=True,
        )
        if result.status == 'fail':
            if result.traceback:
                pytest.fail(f"Script produced traceback:\n{result.traceback}")
            pytest.fail(f"Script failed with return code {result.returncode}")
        elif result.status == 'error':
            pytest.fail(f"Script error: {result.stderr}")
        elif result.status == 'visual_diff':
            # A reference image existed and the render no longer matches it within
            # tolerance. This is a real regression.
            stats = result.comparison_stats or {}
            pytest.fail(
                f"Visual regression for {script_name}: "
                f"{stats.get('percent_different', '?')}% of pixels differ "
                f"(tolerance {MAX_PERCENT_DIFFERENT}%); see {result.diff_image}")



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
