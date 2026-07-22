"""Pytest configuration and shared fixtures for OpenGLContext test suite.

This module provides fixtures for:
- Subprocess-based test execution with coverage collection
- Visual regression testing
- Event simulation
- Profile-based testing (core vs compatibility)
- Automatic coverage combination from subprocess runs
"""

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

# Single source of truth for the subprocess/runner/event machinery lives in the
# shipped OpenGLContext.testing package; conftest imports it rather than keeping
# a second, drifting copy.
from OpenGLContext.testing.subprocess_runner import (
    TestResult as SubprocessResult,
    build_command as _build_command,
    kill_process_tree as _kill_process_tree,
    run_test_with_popen as _run_test_with_popen,
)
from OpenGLContext.testing.event_injector import EventSender

# Disable vsync for the whole test run (inherited by GL subprocess tests via the
# environment). On Wayland a vsync swap blocks on a compositor frame callback,
# which a leaked GL context from an abnormally-terminated earlier test can wedge,
# hanging every later swap. Off, swaps never block on the compositor, so one
# flaky/killed GL test cannot stall the rest of the suite. Respected by
# glfwcontext; harmless on other backends.
os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')

# Timeout settings
DEFAULT_TIMEOUT = 30  # Most tests
SLOW_TEST_TIMEOUT = 120  # Heavy initialization (NURBS, large scenes)

# Test directories
TESTS_DIR = Path(__file__).parent
PROJECT_ROOT = TESTS_DIR.parent
REFERENCE_IMAGES_DIR = TESTS_DIR / "reference_images"

# Files to ignore during pytest collection (legacy resources with Python 2/3 issues)
collect_ignore = [
    "resources/test_context_set_txt.py",
    "resources/test_vrml_set_txt.py",
]

# OpenGL profiles for parametrized tests
PROFILES = ['compatibility', 'core']


def _check_coverage_available() -> bool:
    """Check if coverage module is available and can run."""
    try:
        import coverage
        # Verify coverage.run works
        return hasattr(coverage, 'Coverage')
    except ImportError:
        return False


# Cache coverage availability check
_COVERAGE_AVAILABLE = _check_coverage_available()


@pytest.fixture
def subprocess_runner():
    """Run a test script in a subprocess with timeout handling.

    Returns a callable that runs the script and returns a TestResult. Execution
    goes through the shared Popen-based runner, which knows the child PID and so
    reaps the whole process tree on timeout -- unlike the old inline path, which
    called ``_kill_process_tree(os.getpid())`` and would SIGKILL pytest itself
   .
    """
    def run(
        script_path: Path,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        coverage: bool = True,
    ) -> SubprocessResult:
        """Run a test script in a subprocess.

        Args:
            script_path: Path to the test script
            args: Additional command-line arguments
            env: Environment variable overrides
            timeout: Maximum execution time in seconds
            coverage: Whether to collect coverage data

        Returns:
            TestResult with execution details
        """
        script_path = Path(script_path)
        if not script_path.is_absolute():
            script_path = TESTS_DIR / script_path

        return _run_test_with_popen(
            script_path,
            args=args,
            env=env,
            timeout=timeout,
            with_coverage=coverage and _COVERAGE_AVAILABLE,
            cwd=PROJECT_ROOT,
        )

    return run


@pytest.fixture
def reference_image_dir() -> Path:
    """Path to reference images directory."""
    REFERENCE_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    return REFERENCE_IMAGES_DIR


@pytest.fixture
def opengl_env():
    """Environment variables for OpenGL context creation.

    Returns a callable that generates env dict for a given profile.
    """
    def get_env(profile: str = 'compatibility', backend: Optional[str] = None) -> Dict[str, str]:
        """Get environment variables for the given profile.

        Args:
            profile: OpenGL profile ('core' or 'compatibility')
            backend: Backend to use (auto-selected for core if not specified)

        Returns:
            Dict of environment variables
        """
        env = {'OPENGLCONTEXT_PROFILE': profile}
        if backend:
            env['OPENGLCONTEXT_BACKEND'] = backend
        elif profile == 'core':
            # Core profile requires GLFW for proper context creation
            env['OPENGLCONTEXT_BACKEND'] = 'glfw'
        return env

    return get_env


@pytest.fixture
def visual_regression_runner(subprocess_runner, reference_image_dir, opengl_env):
    """Run visual regression tests against reference images.

    Returns a callable that:
    1. Records reference with compatibility profile (if needed)
    2. Tests against reference with specified profile
    """
    def run(
        script_path: Path,
        test_name: str,
        profile: str = 'core',
        record_profile: str = 'compatibility',
        timeout: float = DEFAULT_TIMEOUT,
        max_diff: int = 255,
        max_percent_different: float = 2.0,
        force_record: bool = False,
    ) -> SubprocessResult:
        """Run a visual regression test.

        Args:
            script_path: Path to the test script
            test_name: Name for reference images
            profile: Profile to test with
            record_profile: Profile to record reference with
            timeout: Maximum execution time
            max_diff: Maximum allowed pixel difference
            max_percent_different: Maximum percent of different pixels
            force_record: Force re-recording of reference image

        Returns:
            SubprocessResult from the test run
        """
        script_path = Path(script_path)
        if not script_path.is_absolute():
            script_path = TESTS_DIR / script_path

        ref_path = reference_image_dir / f"{test_name}.png"

        # Record reference if needed
        if force_record or not ref_path.exists():
            record_args = [
                '--record',
                '--output-dir', str(reference_image_dir),
                '--exit-after',
            ]
            record_result = subprocess_runner(
                script_path,
                args=record_args,
                env=opengl_env(record_profile),
                timeout=timeout,
            )
            if not record_result.success:
                return record_result

        # Test against reference
        test_args = [
            '--test',
            '--output-dir', str(reference_image_dir),
            '--exit-after',
            '--max-diff', str(max_diff),
            '--max-percent-different', str(max_percent_different),
        ]

        return subprocess_runner(
            script_path,
            args=test_args,
            env=opengl_env(profile),
            timeout=timeout,
        )

    return run


@pytest.fixture
def event_sender():
    """Create an EventSender for interactive testing.

    Returns a factory that creates EventSender instances.
    """
    senders: List[EventSender] = []

    def create(socket_path: Optional[str] = None) -> EventSender:
        if socket_path is None:
            socket_path = tempfile.mktemp(suffix='.sock')
        sender = EventSender(socket_path)
        senders.append(sender)
        return sender

    yield create

    # Cleanup
    for sender in senders:
        sender.close()


@pytest.fixture
def interactive_runner(subprocess_runner, event_sender):
    """Run an interactive test with event injection.

    Returns a callable that spawns a subprocess and provides an event sender.
    """
    def run(
        script_path: Path,
        events: List[Dict[str, Any]],
        env: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> SubprocessResult:
        """Run an interactive test with events.

        Args:
            script_path: Path to the test script
            events: List of events to send (include 'wait' events for timing)
            env: Environment variables
            timeout: Maximum execution time

        Returns:
            SubprocessResult from the test run
        """
        script_path = Path(script_path)
        if not script_path.is_absolute():
            script_path = TESTS_DIR / script_path

        # Create socket path
        socket_path = tempfile.mktemp(suffix='.sock')

        # Start subprocess
        cmd = _build_command(
            script_path,
            ['--event-socket', socket_path],
            with_coverage=_COVERAGE_AVAILABLE,
        )
        full_env = {**os.environ, **(env or {})}

        start_time = time.time()
        proc = subprocess.Popen(
            cmd,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
        )

        try:
            # Connect to socket. Launching a coverage-wrapped GL app can take a
            # while to reach OnInit (where the socket is bound), especially on a
            # loaded CI box, so scale the connect window with the run budget
            # rather than a fixed 10s.
            sender = event_sender(socket_path)
            if not sender.connect(timeout=min(timeout, 30.0)):
                _kill_process_tree(proc.pid)
                return SubprocessResult(
                    script=script_path.name,
                    returncode=1,
                    stdout='',
                    stderr=f'Failed to connect to event socket: {socket_path}',
                    timed_out=False,
                    duration=time.time() - start_time,
                )

            # Send events
            for event in events:
                if event.get('type') == 'wait':
                    sender.wait(event.get('duration', 0.5))
                else:
                    sender.send_event(event)

            # Send exit and wait
            sender.send_exit()
            stdout, stderr = proc.communicate(timeout=timeout)
            duration = time.time() - start_time

            return SubprocessResult(
                script=script_path.name,
                returncode=proc.returncode,
                stdout=stdout.decode() if stdout else '',
                stderr=stderr.decode() if stderr else '',
                timed_out=False,
                duration=duration,
            )

        except subprocess.TimeoutExpired:
            _kill_process_tree(proc.pid)
            return SubprocessResult(
                script=script_path.name,
                returncode=124,
                stdout='',
                stderr=f'Test timed out after {timeout}s',
                timed_out=True,
                duration=time.time() - start_time,
            )
        finally:
            # Cleanup socket
            try:
                os.unlink(socket_path)
            except OSError:
                pass

    return run


# Pytest markers for test categorization
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "visual: marks tests as visual regression tests"
    )
    config.addinivalue_line(
        "markers", "interactive: marks tests that use event simulation"
    )
    config.addinivalue_line(
        "markers", "core_profile: marks tests that require core profile"
    )
    config.addinivalue_line(
        "markers", "compatibility_profile: marks tests for compatibility profile"
    )


# Skip tests based on available backends
def pytest_collection_modifyitems(config, items):
    """Modify test collection based on available backends."""
    # Check for GLFW availability
    try:
        import glfw
        has_glfw = True
    except ImportError:
        has_glfw = False

    # A windowed display OR an offscreen GL platform (EGL/OSMesa) can render;
    # only skip visual tests when neither is present, so a headless CI runner
    # configured with PYOPENGL_PLATFORM actually runs them.
    from OpenGLContext.testing.display import display_available
    has_display = display_available()

    for item in items:
        # Skip core profile tests if GLFW not available
        if 'core_profile' in item.keywords and not has_glfw:
            item.add_marker(pytest.mark.skip(reason='GLFW not available for core profile'))

        # Skip visual tests if no display
        if 'visual' in item.keywords and not has_display:
            item.add_marker(pytest.mark.skip(reason='No display available'))


# Coverage combination hooks
def pytest_sessionstart(session):
    """Clean up old coverage data files before running tests."""
    if _COVERAGE_AVAILABLE:
        # Remove old parallel coverage files
        project_root = Path(__file__).parent.parent
        for coverage_file in project_root.glob('.coverage.*'):
            try:
                coverage_file.unlink()
            except OSError:
                pass


def pytest_sessionfinish(session, exitstatus):
    """Combine coverage data from all subprocess runs after tests complete."""
    if not _COVERAGE_AVAILABLE:
        return

    project_root = Path(__file__).parent.parent

    # Check if there are any parallel coverage files to combine
    coverage_files = list(project_root.glob('.coverage.*'))
    if not coverage_files:
        return

    print(f"\n\nCombining coverage from {len(coverage_files)} subprocess runs...")

    try:
        # Run coverage combine
        result = subprocess.run(
            [sys.executable, '-m', 'coverage', 'combine'],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print("Coverage data combined successfully.")

            # Generate coverage report
            result = subprocess.run(
                [sys.executable, '-m', 'coverage', 'report', '--show-missing'],
                cwd=str(project_root),
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print("\n--- Subprocess Coverage Report ---")
                print(result.stdout)
            else:
                print(f"Coverage report failed: {result.stderr}")
        else:
            print(f"Coverage combine failed: {result.stderr}")
    except Exception as e:
        print(f"Coverage combination error: {e}")
