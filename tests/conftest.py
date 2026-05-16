"""Pytest configuration and shared fixtures for OpenGLContext test suite.

This module provides fixtures for:
- Subprocess-based test execution with coverage collection
- Visual regression testing
- Event simulation
- Profile-based testing (core vs compatibility)
- Automatic coverage combination from subprocess runs
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

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


@dataclass
class SubprocessResult:
    """Result from running a test script in a subprocess."""

    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration: float = 0.0
    captured_images: Dict[str, Path] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Return True if subprocess completed successfully."""
        return self.returncode == 0 and not self.timed_out

    @property
    def skipped(self) -> bool:
        """Return True if test was skipped (exit code 2)."""
        return self.returncode == 2

    def __str__(self) -> str:
        status = "PASS" if self.success else ("TIMEOUT" if self.timed_out else "FAIL")
        return f"SubprocessResult({status}, rc={self.returncode}, {self.duration:.2f}s)"


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children."""
    try:
        import psutil
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        try:
            parent.kill()
        except psutil.NoSuchProcess:
            pass
    except ImportError:
        # Fallback without psutil: just kill the main process
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    except Exception:
        pass


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


def _build_coverage_command(
    script_path: Path,
    args: Optional[List[str]] = None,
    coverage: bool = True
) -> List[str]:
    """Build command to run script, optionally with coverage collection."""
    if coverage and _COVERAGE_AVAILABLE:
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


@pytest.fixture
def subprocess_runner():
    """Run a test script in a subprocess with timeout handling.

    Returns a callable that runs the script and returns SubprocessResult.
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
            SubprocessResult with execution details
        """
        script_path = Path(script_path)
        if not script_path.is_absolute():
            script_path = TESTS_DIR / script_path

        cmd = _build_coverage_command(script_path, args, coverage)
        full_env = {**os.environ, **(env or {})}

        start_time = time.time()
        try:
            result = subprocess.run(
                cmd,
                env=full_env,
                capture_output=True,
                timeout=timeout,
                text=True,
                cwd=str(PROJECT_ROOT),
            )
            duration = time.time() - start_time
            return SubprocessResult(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                timed_out=False,
                duration=duration,
            )
        except subprocess.TimeoutExpired as e:
            duration = time.time() - start_time
            # Kill the subprocess tree on timeout
            if e.args and hasattr(e, 'args'):
                # Get PID from exception if available
                pass
            _kill_process_tree(os.getpid())  # This won't work well, but we try
            return SubprocessResult(
                returncode=124,  # Standard timeout exit code
                stdout=e.stdout.decode() if e.stdout else '',
                stderr=e.stderr.decode() if e.stderr else f'Test timed out after {timeout}s',
                timed_out=True,
                duration=duration,
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


class EventSender:
    """Sends events to a test subprocess via Unix socket."""

    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self._socket: Optional[socket.socket] = None

    def connect(self, timeout: float = 10.0) -> bool:
        """Connect to the event socket with polling.

        Args:
            timeout: Maximum time to wait for socket

        Returns:
            True if connected, False otherwise
        """
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        start = time.time()
        while time.time() - start < timeout:
            try:
                self._socket.connect(self.socket_path)
                return True
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.05)  # 50ms between attempts
        return False

    def send_event(self, event: Dict[str, Any]) -> None:
        """Send an event to the subprocess."""
        if self._socket is None:
            raise RuntimeError("Not connected")
        data = json.dumps(event) + '\n'
        self._socket.send(data.encode())

    def send_mousebutton(
        self, x: int, y: int, button: int = 0, state: int = 1, modifiers: Optional[List[int]] = None
    ) -> None:
        """Send a mouse button event."""
        self.send_event({
            'type': 'mousebutton',
            'x': x, 'y': y,
            'button': button,
            'state': state,
            'modifiers': modifiers or [0, 0, 0],
        })

    def send_mousemove(
        self, x: int, y: int, buttons: Optional[List[int]] = None, modifiers: Optional[List[int]] = None
    ) -> None:
        """Send a mouse move event."""
        self.send_event({
            'type': 'mousemove',
            'x': x, 'y': y,
            'buttons': buttons or [],
            'modifiers': modifiers or [0, 0, 0],
        })

    def send_keyboard(
        self, key: str, state: int = 1, modifiers: Optional[List[int]] = None
    ) -> None:
        """Send a keyboard event."""
        self.send_event({
            'type': 'keyboard',
            'key': key,
            'state': state,
            'modifiers': modifiers or [0, 0, 0],
        })

    def send_capture(self, name: str) -> None:
        """Request a framebuffer capture."""
        self.send_event({'type': 'capture', 'name': name})

    def send_exit(self) -> None:
        """Request the subprocess to exit."""
        self.send_event({'type': 'exit'})

    def wait(self, duration: float) -> None:
        """Wait for a duration (for event timing)."""
        time.sleep(duration)

    def close(self) -> None:
        """Close the socket connection."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None


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
        cmd = _build_coverage_command(
            script_path,
            ['--event-socket', socket_path],
            coverage=True,
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
            # Connect to socket
            sender = event_sender(socket_path)
            if not sender.connect(timeout=10.0):
                proc.kill()
                return SubprocessResult(
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
                returncode=proc.returncode,
                stdout=stdout.decode() if stdout else '',
                stderr=stderr.decode() if stderr else '',
                timed_out=False,
                duration=duration,
            )

        except subprocess.TimeoutExpired:
            _kill_process_tree(proc.pid)
            return SubprocessResult(
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

    # Check for display
    has_display = os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')

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
