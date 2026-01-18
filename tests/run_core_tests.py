#!/usr/bin/env python
"""Run tests with core profile context and report failures.

This script runs tests with OPENGLCONTEXT_PROFILE=core and OPENGLCONTEXT_BACKEND=glfw
to check which tests fail in core context mode (as opposed to compatibility mode).
"""
import os
import sys
import subprocess
import signal
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
TEST_RUNNER = 'oglc-test'
TIMEOUT = 8  # seconds per test - needs to be long enough to actually render

# Tests known to not work / not relevant
SKIP_SET = {
    'runalltests.py',
    'run_core_tests.py',  # this script
    'frust_test_module.py',
    'numpyfields.py',
    'wx_multiple_contexts.py',
    'wx_with_controls.py',
    'wx_font.py',
    'nehe6_convolve.py',  # modern drivers don't include the functionality
    'profile_view.py',
    'pygame_font.py',
    'pygame_textureatlas.py',
    'savepostscript.py',  # removed functionality
    '__init__.py',
    # Different testing models that don't work with oglc-test
    'rendering_regression.py',
    'run_teapot_regression.py',
    'test_shader_comparison.py',
    'test_shader_comprehensive.py',
    'test_shaderpass.py',
}

# Platform-specific skips
if sys.platform != 'win32':
    SKIP_SET.update({
        'wgl_font.py',
        'wgl_bitmap_font.py',
        'wglpixelformatarb.py',
        'glprint.py',
    })


def run_test(script_path, timeout=TIMEOUT):
    """Run a single test with timeout. Returns (success, output)."""
    env = os.environ.copy()
    env['OPENGLCONTEXT_PROFILE'] = 'core'
    env['OPENGLCONTEXT_BACKEND'] = 'glfw'

    try:
        result = subprocess.run(
            [TEST_RUNNER, script_path],
            cwd=os.path.dirname(script_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (result.returncode == 0, result.stdout + result.stderr)
    except subprocess.TimeoutExpired:
        return (False, "TIMEOUT after %d seconds" % timeout)
    except Exception as e:
        return (False, "Exception: %s" % str(e))


def main():
    scripts = sorted([
        os.path.join(HERE, f) for f in os.listdir(HERE)
        if f.endswith('.py') and not f.startswith('_') and f not in SKIP_SET
    ])

    if len(sys.argv) > 1:
        # Run specific tests
        scripts = [os.path.join(HERE, s) for s in sys.argv[1:]]

    passed = []
    failed = []

    for script in scripts:
        name = os.path.basename(script)
        print("Testing %s..." % name, end=' ', flush=True)
        success, output = run_test(script)
        if success:
            passed.append(name)
            print("PASS")
        else:
            failed.append((name, output))
            print("FAIL")

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print("Passed: %d" % len(passed))
    print("Failed: %d" % len(failed))

    if failed:
        print("\nFailed tests and their errors:")
        print("-"*60)
        for name, output in failed:
            print("\n%s:" % name)
            # Show first 20 lines of error
            lines = output.strip().split('\n')
            for line in lines[-20:]:
                print("  ", line)

    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
