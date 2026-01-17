#!/usr/bin/env python
"""Runner script for teapot regression tests.

Usage:
    # Record reference with compatibility mode
    python tests/run_teapot_regression.py record

    # Test core profile against reference
    python tests/run_teapot_regression.py test

    # Run full comparison (record compatibility, test core)
    python tests/run_teapot_regression.py compare

    # Record with core profile (for debugging)
    python tests/run_teapot_regression.py record-core
"""
import os
import subprocess
import sys

# Test parameters
TEST_SCRIPT = os.path.join(os.path.dirname(__file__), 'teapot_comparison.py')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'reference_images')
CAPTURE_DELAY = '0.5'
TIMEOUT = 15

# Tolerance for comparison tests
# These account for known differences between legacy (GLUT) and shader-based rendering:
# - Different teapot geometry (GLUT vs embedded OBJ mesh)
# - Per-vertex (Gouraud) vs per-fragment (Phong) lighting
# - Hardware-specific rendering variations
MAX_DIFF = 255  # Max allowed pixel difference (0-255)
MAX_PERCENT_DIFFERENT = 10.0  # Max percent of pixels that can differ


def run_test(mode, profile='compatibility', backend=None, with_tolerance=False):
    """Run the teapot test with specified parameters.

    Args:
        mode: 'record' or 'test'
        profile: 'compatibility' or 'core'
        backend: None for default, or 'glfw' for core profile
        with_tolerance: If True, add tolerance args for test mode

    Returns:
        exit code from subprocess
    """
    env = os.environ.copy()
    env['OPENGLCONTEXT_PROFILE'] = profile
    if backend:
        env['OPENGLCONTEXT_BACKEND'] = backend

    cmd = [
        sys.executable, '-u', TEST_SCRIPT,
        f'--{mode}',
        '--exit-after',
        '--capture-delay', CAPTURE_DELAY,
        '--output-dir', OUTPUT_DIR,
    ]

    # Add tolerance for test mode when comparing different rendering modes
    if with_tolerance and mode == 'test':
        cmd.extend(['--max-diff', str(MAX_DIFF)])
        cmd.extend(['--max-percent-different', str(MAX_PERCENT_DIFFERENT)])

    print(f"\n{'='*60}")
    print(f"Running: {mode} with profile={profile}, backend={backend or 'default'}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    try:
        result = subprocess.run(
            cmd,
            env=env,
            timeout=TIMEOUT,
        )
        return result.returncode
    except subprocess.TimeoutExpired:
        print(f"ERROR: Test timed out after {TIMEOUT} seconds")
        return 1


def record_compatibility():
    """Record reference image using compatibility profile."""
    return run_test('record', profile='compatibility')


def record_core():
    """Record reference image using core profile (for debugging)."""
    return run_test('record', profile='core', backend='glfw')


def test_core(with_tolerance=True):
    """Test core profile against reference.

    Args:
        with_tolerance: Use relaxed tolerances for comparing different rendering modes
    """
    return run_test('test', profile='core', backend='glfw', with_tolerance=with_tolerance)


def test_compatibility():
    """Test compatibility profile against reference (self-test)."""
    return run_test('test', profile='compatibility')


def full_comparison():
    """Run full comparison: record with compatibility, test with core."""
    print("Step 1: Recording reference with compatibility profile...")
    rc = record_compatibility()
    if rc != 0:
        print(f"Recording failed with exit code {rc}")
        return rc

    print("\nStep 2: Testing core profile against reference...")
    rc = test_core()
    return rc


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nAvailable commands:")
        print("  record      - Record reference with compatibility profile")
        print("  record-core - Record reference with core profile (debug)")
        print("  test        - Test core profile against reference")
        print("  test-compat - Test compatibility against reference (self-test)")
        print("  compare     - Full comparison (record compat, test core)")
        sys.exit(1)

    command = sys.argv[1]

    if command == 'record':
        sys.exit(record_compatibility())
    elif command == 'record-core':
        sys.exit(record_core())
    elif command == 'test':
        sys.exit(test_core())
    elif command == 'test-compat':
        sys.exit(test_compatibility())
    elif command == 'compare':
        sys.exit(full_comparison())
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == '__main__':
    main()
