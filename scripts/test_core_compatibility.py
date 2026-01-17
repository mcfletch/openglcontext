#!/usr/bin/env python
"""Test runner to check OpenGLContext tests in core vs compatibility mode.

This script runs tests from the tests/ directory and reports which ones
fail in core profile mode. It helps identify tests that rely on
deprecated OpenGL features.

Usage:
    python scripts/test_core_compatibility.py [--timeout SECONDS] [--output FILE]

Environment variables used:
    OPENGLCONTEXT_PROFILE - Set to "core" or "compatibility"
    OPENGLCONTEXT_BACKEND - Set to backend name (e.g., "glfw" for core profile)
"""

import argparse
import glob
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class TestResult:
    """Result of running a single test."""
    name: str
    profile: str
    success: bool
    exit_code: int
    error_output: str
    timeout: bool
    duration: float
    used_core_renderer: bool = False  # True if we saw the core renderer log message
    used_compat_renderer: bool = False  # True if we saw FLATCOMPAT_USED error


def find_test_scripts(test_dir: str) -> List[str]:
    """Find all Python test scripts in the test directory."""
    patterns = [
        os.path.join(test_dir, '*.py'),
    ]

    scripts = []
    for pattern in patterns:
        scripts.extend(glob.glob(pattern))

    # Filter out __init__.py and non-runnable files
    scripts = [s for s in scripts if not s.endswith('__init__.py')]
    scripts = [s for s in scripts if not s.endswith('_helper.py')]

    return sorted(scripts)


def run_test(script_path: str, profile: str, timeout: int = 10) -> TestResult:
    """Run a single test script with the specified profile.

    Args:
        script_path: Path to the test script
        profile: "core" or "compatibility"
        timeout: Maximum seconds to run before killing

    Returns:
        TestResult with details of the run
    """
    name = os.path.basename(script_path)

    env = os.environ.copy()
    env['OPENGLCONTEXT_PROFILE'] = profile

    # For core profile, we need a backend that supports it
    if profile == 'core':
        env['OPENGLCONTEXT_BACKEND'] = 'glfw'

    start_time = time.time()
    timed_out = False

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=os.path.dirname(os.path.dirname(script_path)),
        )
        exit_code = result.returncode
        # Combine stdout and stderr for error analysis
        output = result.stdout + result.stderr

    except subprocess.TimeoutExpired as e:
        # Timeout is actually success for interactive tests
        timed_out = True
        exit_code = 0  # Treat timeout as success (test ran without crashing)
        # Handle bytes or string output
        stdout_raw = e.stdout if e.stdout else b''
        stderr_raw = e.stderr if e.stderr else b''
        stdout_str = stdout_raw.decode('utf-8', errors='replace') if isinstance(stdout_raw, bytes) else str(stdout_raw)
        stderr_str = stderr_raw.decode('utf-8', errors='replace') if isinstance(stderr_raw, bytes) else str(stderr_raw)
        output = stdout_str + stderr_str

    except Exception as e:
        exit_code = -1
        output = str(e)

    duration = time.time() - start_time

    # Check if core renderer was used (look for the flatcore log message)
    used_core_renderer = '[flatcore] Render mode: SHADER' in output

    # Check if compatibility renderer was used (look for FLATCOMPAT_USED error)
    used_compat_renderer = 'FLATCOMPAT_USED' in output

    # Check for error indicators in output
    error_keywords = ['Error', 'Exception', 'Traceback', 'GLError', 'FAILED']
    has_errors = any(kw in output for kw in error_keywords)

    # Success if: no crash (exit_code 0 or timeout) and no error output
    # For interactive tests, timeout means it ran successfully
    success = (exit_code == 0 or timed_out) and not has_errors

    return TestResult(
        name=name,
        profile=profile,
        success=success,
        exit_code=exit_code,
        error_output=output if not success else output,  # Always capture output for renderer detection
        timeout=timed_out,
        duration=duration,
        used_core_renderer=used_core_renderer,
        used_compat_renderer=used_compat_renderer,
    )


def extract_error_summary(output: str, max_lines: int = 20) -> str:
    """Extract relevant error information from test output."""
    lines = output.split('\n')

    # Find error-related lines
    error_lines = []
    in_traceback = False

    for line in lines:
        if 'Traceback' in line:
            in_traceback = True
        if in_traceback or any(kw in line for kw in ['Error', 'Exception', 'GLError', 'FAILED']):
            error_lines.append(line)
            if len(error_lines) >= max_lines:
                error_lines.append('... (truncated)')
                break
        if in_traceback and line.strip() and not line.startswith(' '):
            in_traceback = False

    return '\n'.join(error_lines)


def categorize_error(output: str) -> str:
    """Categorize the type of error based on output."""
    output_lower = output.lower()

    # Check for compatibility renderer being used instead of core
    if 'flatcompat_used' in output_lower:
        return 'Using compatibility renderer (not core profile)'

    if 'glpushattrib' in output_lower or 'glpopattrib' in output_lower:
        return 'glPushAttrib/glPopAttrib (deprecated state management)'
    if 'glenableclientstate' in output_lower or 'gldisableclientstate' in output_lower:
        return 'glEnableClientState (deprecated vertex arrays)'
    if 'glvertexpointer' in output_lower or 'glnormalpointer' in output_lower:
        return 'glVertexPointer/etc (deprecated vertex specification)'
    if 'glbegin' in output_lower or 'glend' in output_lower or 'glvertex' in output_lower:
        return 'glBegin/glEnd (immediate mode)'
    if 'gllightf' in output_lower or 'glmaterial' in output_lower:
        return 'glLightf/glMaterial (fixed-function lighting)'
    if 'gltexenv' in output_lower:
        return 'glTexEnv (fixed-function texturing)'
    if 'gldrawpixels' in output_lower or 'glrasterpos' in output_lower:
        return 'glDrawPixels/glRasterPos (raster operations)'
    if 'gllist' in output_lower or 'glcalllist' in output_lower or 'glnewlist' in output_lower:
        return 'Display lists (deprecated)'
    if 'glutbitmap' in output_lower or 'glutstroke' in output_lower:
        return 'GLUT bitmap/stroke fonts'
    if 'invalid operation' in output_lower:
        return 'Invalid GL operation (likely deprecated function)'
    if 'invalid enum' in output_lower:
        return 'Invalid GL enum (deprecated constant)'
    if 'attribute' in output_lower and 'not found' in output_lower:
        return 'Shader attribute not found'
    if 'uniform' in output_lower and 'not found' in output_lower:
        return 'Shader uniform not found'
    if 'importerror' in output_lower or 'modulenotfounderror' in output_lower:
        return 'Import error'
    if 'filenotfounderror' in output_lower:
        return 'File not found'

    return 'Other/Unknown'


def generate_report(
    results: List[TestResult],
    output_path: Optional[str] = None
) -> str:
    """Generate a markdown report of test results."""

    # Separate by profile
    core_results = [r for r in results if r.profile == 'core']
    compat_results = [r for r in results if r.profile == 'compatibility']

    # Find tests that fail in core but pass in compatibility
    core_only_failures = []
    for core_r in core_results:
        compat_r = next((r for r in compat_results if r.name == core_r.name), None)
        if not core_r.success and (compat_r is None or compat_r.success):
            core_only_failures.append(core_r)

    # Categorize failures
    categories = {}
    for result in core_only_failures:
        category = categorize_error(result.error_output)
        if category not in categories:
            categories[category] = []
        categories[category].append(result)

    # Count renderer usage for core profile tests
    core_used_core_renderer = [r for r in core_results if r.used_core_renderer]
    core_used_compat_renderer = [r for r in core_results if r.used_compat_renderer]
    core_neither_renderer = [r for r in core_results if not r.used_core_renderer and not r.used_compat_renderer]

    # Generate report
    lines = [
        '# OpenGLContext Core Profile Compatibility Report',
        '',
        f'Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        '',
        '## Summary',
        '',
        f'- Total tests: {len(set(r.name for r in results))}',
        f'- Tests passing in compatibility mode: {sum(1 for r in compat_results if r.success)}',
        f'- Tests passing in core mode: {sum(1 for r in core_results if r.success)}',
        f'- Tests failing only in core mode: {len(core_only_failures)}',
        '',
        '## Renderer Usage (Core Profile Tests)',
        '',
        f'- Tests using core renderer (flatcore): {len(core_used_core_renderer)}',
        f'- Tests using compatibility renderer (flatcompat): {len(core_used_compat_renderer)}',
        f'- Tests with unknown renderer: {len(core_neither_renderer)}',
        '',
    ]

    if core_used_compat_renderer:
        lines.append('### Tests Using Compatibility Renderer (should be using core)')
        lines.append('')
        for r in sorted(core_used_compat_renderer, key=lambda x: x.name):
            lines.append(f'- `{r.name}`')
        lines.append('')

    if core_neither_renderer:
        lines.append('### Tests With Unknown Renderer')
        lines.append('')
        lines.append('These tests did not produce renderer detection output (may have crashed early):')
        lines.append('')
        for r in sorted(core_neither_renderer, key=lambda x: x.name):
            lines.append(f'- `{r.name}`')
        lines.append('')

    lines.extend([
        '## Tests Failing in Core Profile',
        '',
        'These tests pass in compatibility mode but fail in core profile,',
        'indicating they use deprecated OpenGL features.',
        '',
    ])

    if not core_only_failures:
        lines.append('*No tests fail exclusively in core mode.*')
    else:
        # Group by category
        lines.append('### By Error Category')
        lines.append('')

        for category, cat_results in sorted(categories.items(), key=lambda x: -len(x[1])):
            lines.append(f'#### {category} ({len(cat_results)} tests)')
            lines.append('')
            for r in sorted(cat_results, key=lambda x: x.name):
                lines.append(f'- `{r.name}`')
            lines.append('')

        lines.append('### Detailed Error Output')
        lines.append('')

        for result in sorted(core_only_failures, key=lambda x: x.name):
            lines.append(f'#### {result.name}')
            lines.append('')
            lines.append(f'**Category:** {categorize_error(result.error_output)}')
            lines.append('')
            if result.error_output:
                summary = extract_error_summary(result.error_output)
                lines.append('```')
                lines.append(summary[:2000] if len(summary) > 2000 else summary)
                lines.append('```')
            lines.append('')

    # Tests that pass in both modes
    lines.append('## Tests Passing in Both Modes')
    lines.append('')
    both_pass = []
    for core_r in core_results:
        compat_r = next((r for r in compat_results if r.name == core_r.name), None)
        if core_r.success and compat_r and compat_r.success:
            both_pass.append(core_r.name)

    if both_pass:
        for name in sorted(both_pass):
            lines.append(f'- `{name}`')
    else:
        lines.append('*None*')

    lines.append('')

    # Tests that fail in both modes
    lines.append('## Tests Failing in Both Modes')
    lines.append('')
    lines.append('These tests have issues unrelated to core/compatibility profile.')
    lines.append('')
    both_fail = []
    for core_r in core_results:
        compat_r = next((r for r in compat_results if r.name == core_r.name), None)
        if not core_r.success and compat_r and not compat_r.success:
            both_fail.append(core_r.name)

    if both_fail:
        for name in sorted(both_fail):
            lines.append(f'- `{name}`')
    else:
        lines.append('*None*')

    report = '\n'.join(lines)

    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(report)
        print(f'Report written to: {output_path}')

    return report


def main():
    parser = argparse.ArgumentParser(
        description='Test OpenGLContext scripts in core vs compatibility mode'
    )
    parser.add_argument(
        '--timeout', type=int, default=8,
        help='Timeout in seconds for each test (default: 8)'
    )
    parser.add_argument(
        '--output', '-o', type=str,
        default='plans/core_compatibility_report.md',
        help='Output file for the report'
    )
    parser.add_argument(
        '--test-dir', type=str, default='tests',
        help='Directory containing test scripts'
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Print progress as tests run'
    )

    args = parser.parse_args()

    # Find test scripts
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_dir = os.path.join(script_dir, args.test_dir)

    scripts = find_test_scripts(test_dir)
    print(f'Found {len(scripts)} test scripts in {test_dir}')

    results = []

    # Run each test in both modes
    for i, script in enumerate(scripts):
        name = os.path.basename(script)

        for profile in ['compatibility', 'core']:
            if args.verbose:
                backend = 'glfw' if profile == 'core' else 'default'
                print(f'[{i+1}/{len(scripts)}] {name} [{profile}/{backend}]...', end=' ', flush=True)

            result = run_test(script, profile, timeout=args.timeout)
            results.append(result)

            if args.verbose:
                status = 'PASS' if result.success else 'FAIL'
                if result.timeout:
                    status += ' (timeout)'
                # Show renderer info for core profile
                if profile == 'core':
                    if result.used_core_renderer:
                        status += ' [CORE]'
                    elif result.used_compat_renderer:
                        status += ' [COMPAT!]'
                    else:
                        status += ' [?]'
                print(status)

    # Generate report
    print()
    report = generate_report(results, args.output)

    # Print summary
    core_failures = sum(1 for r in results if r.profile == 'core' and not r.success)
    compat_failures = sum(1 for r in results if r.profile == 'compatibility' and not r.success)
    print(f'\nSummary:')
    print(f'  Compatibility mode failures: {compat_failures}/{len(scripts)}')
    print(f'  Core mode failures: {core_failures}/{len(scripts)}')


if __name__ == '__main__':
    main()
