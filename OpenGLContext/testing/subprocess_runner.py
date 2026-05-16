"""Subprocess-based test execution with coverage collection and timeout handling.

This module provides utilities for running OpenGLContext tests in isolated
subprocesses with proper timeout handling, coverage collection, and
process tree cleanup.
"""

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


# Default timeout for test execution
DEFAULT_TIMEOUT = 30

# Extended timeout for slow tests
SLOW_TEST_TIMEOUT = 120


@dataclass
class TestResult:
    """Result from running a test in a subprocess."""

    script: str
    returncode: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    profile: str = ''
    captured_images: Dict[str, Path] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Return True if test passed."""
        return self.returncode == 0 and not self.timed_out

    @property
    def skipped(self) -> bool:
        """Return True if test was skipped (exit code 2)."""
        return self.returncode == 2

    @property
    def failed(self) -> bool:
        """Return True if test failed."""
        return self.returncode != 0 and self.returncode != 2 and not self.timed_out

    def __str__(self) -> str:
        if self.timed_out:
            status = "TIMEOUT"
        elif self.success:
            status = "PASS"
        elif self.skipped:
            status = "SKIP"
        else:
            status = "FAIL"
        return f"{status}: {self.script} ({self.duration:.2f}s)"


def kill_process_tree(pid: int) -> None:
    """Kill a process and all its children.

    Uses psutil if available for reliable tree killing, otherwise
    falls back to basic signal-based killing.

    Args:
        pid: Process ID to kill
    """
    try:
        import psutil
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            # Kill children first
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            # Then kill parent
            try:
                parent.kill()
            except psutil.NoSuchProcess:
                pass
        except psutil.NoSuchProcess:
            pass
    except ImportError:
        # Fallback: just try to kill the process directly
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass


def build_command(
    script_path: Union[str, Path],
    args: Optional[List[str]] = None,
    with_coverage: bool = True,
    coverage_source: str = 'OpenGLContext',
) -> List[str]:
    """Build command to run a test script.

    Args:
        script_path: Path to the test script
        args: Additional command-line arguments
        with_coverage: Whether to wrap with coverage collection
        coverage_source: Source directory for coverage

    Returns:
        List of command arguments
    """
    script_path = str(script_path)

    if with_coverage:
        cmd = [
            sys.executable, '-m', 'coverage', 'run',
            '--parallel-mode',
            f'--source={coverage_source}',
            script_path,
        ]
    else:
        cmd = [sys.executable, script_path]

    if args:
        cmd.extend(args)

    return cmd


def run_test(
    script_path: Union[str, Path],
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    with_coverage: bool = True,
    cwd: Optional[Union[str, Path]] = None,
) -> TestResult:
    """Run a test script in a subprocess.

    Args:
        script_path: Path to the test script
        args: Additional command-line arguments
        env: Environment variable overrides (merged with os.environ)
        timeout: Maximum execution time in seconds
        with_coverage: Whether to collect coverage data
        cwd: Working directory for the subprocess

    Returns:
        TestResult with execution details
    """
    script_path = Path(script_path)
    script_name = script_path.name

    cmd = build_command(script_path, args, with_coverage)
    full_env = {**os.environ, **(env or {})}

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            env=full_env,
            capture_output=True,
            timeout=timeout,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
        duration = time.time() - start_time

        return TestResult(
            script=script_name,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration=duration,
            timed_out=False,
            profile=full_env.get('OPENGLCONTEXT_PROFILE', ''),
        )

    except subprocess.TimeoutExpired as e:
        duration = time.time() - start_time

        # Attempt to kill the process tree
        # The subprocess module doesn't give us the PID directly in TimeoutExpired,
        # but we can work around this by using Popen instead of run for critical cases

        stdout = ''
        stderr = f'Test timed out after {timeout}s'

        if e.stdout:
            stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout
        if e.stderr:
            stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr

        return TestResult(
            script=script_name,
            returncode=124,  # Standard timeout exit code
            stdout=stdout,
            stderr=stderr,
            duration=duration,
            timed_out=True,
            profile=full_env.get('OPENGLCONTEXT_PROFILE', ''),
        )


def run_test_with_popen(
    script_path: Union[str, Path],
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    with_coverage: bool = True,
    cwd: Optional[Union[str, Path]] = None,
) -> TestResult:
    """Run a test script using Popen for better timeout handling.

    This version uses Popen instead of run() to get access to the PID
    for proper process tree cleanup on timeout.

    Args:
        script_path: Path to the test script
        args: Additional command-line arguments
        env: Environment variable overrides
        timeout: Maximum execution time in seconds
        with_coverage: Whether to collect coverage data
        cwd: Working directory for the subprocess

    Returns:
        TestResult with execution details
    """
    script_path = Path(script_path)
    script_name = script_path.name

    cmd = build_command(script_path, args, with_coverage)
    full_env = {**os.environ, **(env or {})}

    start_time = time.time()

    proc = subprocess.Popen(
        cmd,
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
    )

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        duration = time.time() - start_time

        return TestResult(
            script=script_name,
            returncode=proc.returncode,
            stdout=stdout.decode() if stdout else '',
            stderr=stderr.decode() if stderr else '',
            duration=duration,
            timed_out=False,
            profile=full_env.get('OPENGLCONTEXT_PROFILE', ''),
        )

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time

        # Kill the process tree
        kill_process_tree(proc.pid)

        # Try to get any output that was produced
        try:
            stdout, stderr = proc.communicate(timeout=1)
            stdout_str = stdout.decode() if stdout else ''
            stderr_str = stderr.decode() if stderr else ''
        except Exception:
            stdout_str = ''
            stderr_str = ''

        return TestResult(
            script=script_name,
            returncode=124,
            stdout=stdout_str,
            stderr=stderr_str + f'\nTest timed out after {timeout}s',
            duration=duration,
            timed_out=True,
            profile=full_env.get('OPENGLCONTEXT_PROFILE', ''),
        )


class TestRunner:
    """Runs multiple tests with configurable settings."""

    def __init__(
        self,
        test_dir: Optional[Union[str, Path]] = None,
        reference_dir: Optional[Union[str, Path]] = None,
        with_coverage: bool = True,
        default_timeout: float = DEFAULT_TIMEOUT,
    ):
        """Initialize the test runner.

        Args:
            test_dir: Directory containing test scripts
            reference_dir: Directory for reference images
            with_coverage: Whether to collect coverage data
            default_timeout: Default timeout for tests
        """
        if test_dir is None:
            # Default to tests/ relative to project root
            test_dir = Path(__file__).parent.parent.parent / 'tests'
        self.test_dir = Path(test_dir)
        self.reference_dir = Path(reference_dir) if reference_dir else self.test_dir / 'reference_images'
        self.with_coverage = with_coverage
        self.default_timeout = default_timeout
        self.results: List[TestResult] = []

    def run(
        self,
        script: Union[str, Path],
        args: Optional[List[str]] = None,
        profile: str = 'compatibility',
        backend: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> TestResult:
        """Run a single test script.

        Args:
            script: Script name or path
            args: Additional arguments
            profile: OpenGL profile to use
            backend: Backend to use (auto-selected for core if not specified)
            timeout: Override default timeout

        Returns:
            TestResult from the execution
        """
        script_path = Path(script)
        if not script_path.is_absolute():
            script_path = self.test_dir / script

        env = {'OPENGLCONTEXT_PROFILE': profile}
        if backend:
            env['OPENGLCONTEXT_BACKEND'] = backend
        elif profile == 'core':
            env['OPENGLCONTEXT_BACKEND'] = 'glfw'

        result = run_test_with_popen(
            script_path,
            args=args,
            env=env,
            timeout=timeout or self.default_timeout,
            with_coverage=self.with_coverage,
        )

        self.results.append(result)
        return result

    def run_regression(
        self,
        script: Union[str, Path],
        test_name: str,
        record_profile: str = 'compatibility',
        test_profile: str = 'core',
        timeout: Optional[float] = None,
        max_diff: int = 255,
        max_percent_different: float = 2.0,
    ) -> TestResult:
        """Run a visual regression test.

        First records reference with record_profile (if needed),
        then tests against it with test_profile.

        Args:
            script: Script name or path
            test_name: Name for reference images
            record_profile: Profile for recording reference
            test_profile: Profile for testing
            timeout: Override default timeout
            max_diff: Maximum allowed pixel difference
            max_percent_different: Maximum percent of different pixels

        Returns:
            TestResult from the test run
        """
        script_path = Path(script)
        if not script_path.is_absolute():
            script_path = self.test_dir / script

        timeout = timeout or self.default_timeout
        ref_path = self.reference_dir / f"{test_name}.png"

        # Record reference if needed
        if not ref_path.exists():
            record_result = self.run(
                script_path,
                args=['--record', '--output-dir', str(self.reference_dir), '--exit-after'],
                profile=record_profile,
                timeout=timeout,
            )
            if not record_result.success:
                return record_result

        # Test against reference
        return self.run(
            script_path,
            args=[
                '--test',
                '--output-dir', str(self.reference_dir),
                '--exit-after',
                '--max-diff', str(max_diff),
                '--max-percent-different', str(max_percent_different),
            ],
            profile=test_profile,
            timeout=timeout,
        )

    def summary(self) -> Dict[str, Any]:
        """Get summary of all test results.

        Returns:
            Dict with counts and lists of passed/failed/skipped tests
        """
        passed = [r for r in self.results if r.success]
        failed = [r for r in self.results if r.failed]
        skipped = [r for r in self.results if r.skipped]
        timed_out = [r for r in self.results if r.timed_out]

        return {
            'total': len(self.results),
            'passed': len(passed),
            'failed': len(failed),
            'skipped': len(skipped),
            'timed_out': len(timed_out),
            'passed_tests': [r.script for r in passed],
            'failed_tests': [r.script for r in failed],
            'skipped_tests': [r.script for r in skipped],
            'timed_out_tests': [r.script for r in timed_out],
        }

    def print_summary(self) -> None:
        """Print a summary of test results."""
        summary = self.summary()
        print(f"\nTest Results: {summary['passed']}/{summary['total']} passed")
        if summary['failed']:
            print(f"  Failed: {', '.join(summary['failed_tests'])}")
        if summary['timed_out']:
            print(f"  Timed out: {', '.join(summary['timed_out_tests'])}")
        if summary['skipped']:
            print(f"  Skipped: {', '.join(summary['skipped_tests'])}")
