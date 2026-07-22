"""Unit tests for the testing infrastructure modules.

These tests verify the testing utilities work correctly without
requiring an OpenGL context.
"""

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import numpy as np


class TestSubprocessRunner:
    """Tests for subprocess_runner module."""

    def test_test_result_success(self):
        """TestResult correctly identifies success."""
        from OpenGLContext.testing.subprocess_runner import TestResult

        result = TestResult(
            script='test.py',
            returncode=0,
            stdout='output',
            stderr='',
            duration=1.0,
        )
        assert result.success
        assert not result.failed
        assert not result.skipped
        assert not result.timed_out

    def test_test_result_failure(self):
        """TestResult correctly identifies failure."""
        from OpenGLContext.testing.subprocess_runner import TestResult

        result = TestResult(
            script='test.py',
            returncode=1,
            stdout='',
            stderr='error',
            duration=1.0,
        )
        assert not result.success
        assert result.failed
        assert not result.skipped

    def test_test_result_skip(self):
        """TestResult correctly identifies skip."""
        from OpenGLContext.testing.subprocess_runner import TestResult

        result = TestResult(
            script='test.py',
            returncode=2,
            stdout='',
            stderr='',
            duration=1.0,
        )
        assert not result.success
        assert not result.failed
        assert result.skipped

    def test_test_result_timeout(self):
        """TestResult correctly identifies timeout."""
        from OpenGLContext.testing.subprocess_runner import TestResult

        result = TestResult(
            script='test.py',
            returncode=124,
            stdout='',
            stderr='',
            duration=30.0,
            timed_out=True,
        )
        assert not result.success
        assert not result.failed
        assert result.timed_out

    def test_build_command_without_coverage(self):
        """build_command creates basic command without coverage."""
        from OpenGLContext.testing.subprocess_runner import build_command

        cmd = build_command('/path/to/test.py', with_coverage=False)
        assert '/path/to/test.py' in cmd
        assert 'coverage' not in cmd

    def test_build_command_with_coverage(self):
        """build_command includes coverage arguments."""
        from OpenGLContext.testing.subprocess_runner import build_command

        cmd = build_command('/path/to/test.py', with_coverage=True)
        assert 'coverage' in cmd
        assert 'run' in cmd
        assert '--parallel-mode' in cmd

    def test_build_command_with_args(self):
        """build_command appends additional arguments."""
        from OpenGLContext.testing.subprocess_runner import build_command

        cmd = build_command('/path/to/test.py', args=['--arg1', '--arg2'], with_coverage=False)
        assert '--arg1' in cmd
        assert '--arg2' in cmd


class TestEventInjector:
    """Tests for event_injector module."""

    def test_event_sender_initialization(self):
        """EventSender initializes with socket path."""
        from OpenGLContext.testing.event_injector import EventSender

        sender = EventSender('/tmp/test.sock')
        assert sender.socket_path == '/tmp/test.sock'
        assert sender._socket is None

    def test_event_sender_connect_nonexistent(self):
        """EventSender.connect returns False for nonexistent socket."""
        from OpenGLContext.testing.event_injector import EventSender

        sender = EventSender('/tmp/nonexistent_socket_12345.sock')
        result = sender.connect(timeout=0.1)
        assert result is False

    def test_event_sender_socket_communication(self):
        """EventSender can send events over socket."""
        from OpenGLContext.testing.event_injector import EventSender

        # Create a server socket
        socket_path = tempfile.mktemp(suffix='.sock')
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(socket_path)
        server.listen(1)

        received_data = []

        def accept_and_read():
            conn, _ = server.accept()
            data = conn.recv(4096)
            received_data.append(data.decode())
            conn.close()

        # Start server thread
        thread = threading.Thread(target=accept_and_read)
        thread.start()

        try:
            sender = EventSender(socket_path)
            assert sender.connect(timeout=1.0)
            sender.send_event({'type': 'test', 'value': 42})
            sender.close()

            thread.join(timeout=2.0)

            assert len(received_data) == 1
            event = json.loads(received_data[0].strip())
            assert event['type'] == 'test'
            assert event['value'] == 42
        finally:
            server.close()
            try:
                os.unlink(socket_path)
            except OSError:
                pass

    def test_event_sender_send_mousebutton(self):
        """EventSender.send_mousebutton creates correct event."""
        from OpenGLContext.testing.event_injector import EventSender

        socket_path = tempfile.mktemp(suffix='.sock')
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(socket_path)
        server.listen(1)

        received = []

        def accept():
            conn, _ = server.accept()
            received.append(conn.recv(4096).decode())
            conn.close()

        thread = threading.Thread(target=accept)
        thread.start()

        try:
            sender = EventSender(socket_path)
            sender.connect(timeout=1.0)
            sender.send_mousebutton(100, 200, button=0, state=1)
            sender.close()

            thread.join(timeout=2.0)

            event = json.loads(received[0].strip())
            assert event['type'] == 'mousebutton'
            assert event['x'] == 100
            assert event['y'] == 200
            assert event['button'] == 0
            assert event['state'] == 1
        finally:
            server.close()
            try:
                os.unlink(socket_path)
            except OSError:
                pass


class TestVisualRegressionTest:
    """Tests for VisualRegressionTest class."""

    def test_initialization(self, tmp_path):
        """VisualRegressionTest initializes correctly."""
        from OpenGLContext.testing.framebuffer_comparison import VisualRegressionTest

        test = VisualRegressionTest('my_test', str(tmp_path))
        assert test.test_name == 'my_test'
        assert test.reference_dir == str(tmp_path)
        assert not test.has_reference

    def test_save_and_load_reference(self, tmp_path):
        """VisualRegressionTest can save and load reference images."""
        from OpenGLContext.testing.framebuffer_comparison import VisualRegressionTest

        test = VisualRegressionTest('my_test', str(tmp_path))

        # Create test image
        pixels = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)

        # Save reference
        assert test.save_reference(pixels)
        assert test.has_reference

        # Load reference
        assert test.load_reference()
        assert test._reference_pixels is not None
        np.testing.assert_array_equal(test._reference_pixels, pixels)

    def test_compare_identical_images(self, tmp_path):
        """VisualRegressionTest detects identical images."""
        from OpenGLContext.testing.framebuffer_comparison import VisualRegressionTest

        test = VisualRegressionTest('my_test', str(tmp_path))

        pixels = np.ones((100, 100, 3), dtype=np.uint8) * 128
        test.save_reference(pixels)

        result = test.compare(pixels)
        assert result is not None
        assert result.max_diff == 0.0
        assert test._status == 'pass'

    def test_compare_different_images(self, tmp_path):
        """VisualRegressionTest detects different images."""
        from OpenGLContext.testing.framebuffer_comparison import VisualRegressionTest

        test = VisualRegressionTest('my_test', str(tmp_path), max_diff_threshold=10)

        ref_pixels = np.zeros((100, 100, 3), dtype=np.uint8)
        result_pixels = np.ones((100, 100, 3), dtype=np.uint8) * 255

        test.save_reference(ref_pixels)
        result = test.compare(result_pixels)

        assert result is not None
        assert result.max_diff == 255.0
        assert test._status == 'fail'

    def test_generate_report_data(self, tmp_path):
        """VisualRegressionTest generates report data."""
        from OpenGLContext.testing.framebuffer_comparison import VisualRegressionTest

        test = VisualRegressionTest('my_test', str(tmp_path))

        pixels = np.ones((100, 100, 3), dtype=np.uint8) * 128
        test.save_reference(pixels)
        test.compare(pixels)
        test.set_output('stdout text', 'stderr text', 1.5)

        data = test.generate_report_data()

        assert data['test_name'] == 'my_test'
        assert data['status'] == 'pass'
        assert data['stdout'] == 'stdout text'
        assert data['stderr'] == 'stderr text'
        assert data['duration'] == 1.5
        assert 'comparison_stats' in data


class TestTestReportGenerator:
    """Tests for TestReportGenerator class."""

    def test_empty_report(self):
        """TestReportGenerator creates valid HTML for empty report."""
        from OpenGLContext.testing.report_generator import TestReportGenerator

        gen = TestReportGenerator("Empty Report")
        html = gen.generate_html()

        assert "Empty Report" in html
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html

    def test_add_test(self):
        """TestReportGenerator adds tests correctly."""
        from OpenGLContext.testing.report_generator import TestReportGenerator

        gen = TestReportGenerator()
        gen.add_test({'test_name': 'test1', 'status': 'pass'})
        gen.add_test({'test_name': 'test2', 'status': 'fail'})

        assert len(gen.tests) == 2

    def test_status_colors(self):
        """Status colors are assigned correctly."""
        from OpenGLContext.testing.report_generator import _status_color

        assert _status_color('pass') == '#28a745'  # Green
        assert _status_color('fail') == '#dc3545'  # Red
        assert _status_color('skip') == '#ffc107'  # Yellow

    def test_save_to_file(self, tmp_path):
        """TestReportGenerator saves to file correctly."""
        from OpenGLContext.testing.report_generator import TestReportGenerator

        gen = TestReportGenerator("Test Report")
        gen.add_test({'test_name': 'test', 'status': 'pass'})

        output_path = tmp_path / "report.html"
        gen.save(str(output_path))

        assert output_path.exists()
        content = output_path.read_text()
        assert "Test Report" in content
        assert "test" in content


class TestKillProcessTree:
    """Tests for process tree killing functionality."""

    def test_kill_nonexistent_process(self):
        """kill_process_tree handles nonexistent processes gracefully."""
        from OpenGLContext.testing.subprocess_runner import kill_process_tree

        # Should not raise exception
        kill_process_tree(999999999)


class TestEventInjectionMixin:
    """Tests for EventInjectionMixin functionality."""

    def test_mixin_attributes(self):
        """EventInjectionMixin has expected attributes."""
        from OpenGLContext.testing.event_injector import EventInjectionMixin

        assert hasattr(EventInjectionMixin, 'setup_event_injection')
        assert hasattr(EventInjectionMixin, 'poll_injected_events')
        assert hasattr(EventInjectionMixin, '_dispatch_injected_event')

    def _fake_context(self):
        """A minimal EventInjectionMixin host with recording event managers."""
        from OpenGLContext.testing.event_injector import EventInjectionMixin

        class FakeManager:
            def __init__(self):
                self.events = []

            def ProcessEvent(self, event):
                self.events.append(event)

        class FakeContext(EventInjectionMixin):
            def __init__(self):
                self._managers = {
                    t: FakeManager()
                    for t in ('mousebutton', 'mousemove', 'keyboard', 'keypress')
                }

            def getEventManager(self, event_type):
                return self._managers.get(event_type)

        return FakeContext()

    def test_inject_mousebutton_builds_valid_event(self):
        """Regression for 3.28: injectors must build real Event objects.

        The original code passed constructor kwargs the Event API rejects, so no
        injected event ever reached a handler. This checks the dispatched event
        is well-formed and keyed correctly, with no GL context required.
        """
        ctx = self._fake_context()
        ctx._dispatch_injected_event(
            {'type': 'mousebutton', 'x': 100, 'y': 120, 'button': 0, 'state': 1}
        )

        events = ctx._managers['mousebutton'].events
        assert len(events) == 1
        evt = events[0]
        assert evt.button == 0
        assert evt.state == 1
        assert evt.getKey() == (0, 1, (0, 0, 0))
        assert evt.getObjectPaths() == []  # anonymous dispatch, no pick pass

    def test_inject_keyboard_also_emits_keypress(self):
        """A pressed key drives both keyboard and keypress managers (3.28)."""
        ctx = self._fake_context()
        ctx._dispatch_injected_event({'type': 'keyboard', 'key': 'a', 'state': 1})

        assert len(ctx._managers['keyboard'].events) == 1
        press = ctx._managers['keypress'].events
        assert len(press) == 1
        assert press[0].name == 'a'


class TestConftest:
    """Tests for conftest.py fixtures."""

    def test_subprocess_result_properties(self):
        """conftest re-exports the package TestResult as its result type (3.27)."""
        # Import from conftest
        import sys
        from OpenGLContext.testing.paths import tests_root
        sys.path.insert(0, str(tests_root(__file__)))   # conftest lives in the tests root
        from conftest import SubprocessResult
        from OpenGLContext.testing.subprocess_runner import TestResult

        # conftest no longer keeps its own copy; it is the package's TestResult.
        assert SubprocessResult is TestResult

        result = SubprocessResult(
            script='demo.py',
            returncode=0,
            stdout='out',
            stderr='err',
            timed_out=False,
            duration=1.0,
        )
        assert result.success
        assert not result.skipped

        result2 = SubprocessResult(
            script='demo.py',
            returncode=2,
            stdout='',
            stderr='',
            timed_out=False,
            duration=1.0,
        )
        assert result2.skipped
