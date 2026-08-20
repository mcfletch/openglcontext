"""Unit tests for OpenGLContext.testing.event_injector.

These cover the socket/stdin receive path (EventInjector), the JSON dispatch
logic (EventInjectionMixin) and the EventSender wire format, using real
in-process sockets and a GL-free fake context. The only mocked edges are a
specific socket error and the GL framebuffer capture.
"""

import os
import socket
import sys
import tempfile
import time
from typing import Any

import pytest

from OpenGLContext.testing.event_injector import (
    EventInjectionMixin,
    EventInjector,
    EventSender,
)


def _sock_path() -> str:
    path = tempfile.mktemp(suffix='.sock')
    return path


def _drain(injector: EventInjector, expected: int, tries: int = 100) -> list:
    events: list = []
    for _ in range(tries):
        events.extend(injector.poll())
        if len(events) >= expected:
            break
        time.sleep(0.01)
    return events


# --------------------------------------------------------------------------
# EventInjector: socket receive path
# --------------------------------------------------------------------------


def test_injector_creates_and_listens_on_socket():
    """Constructing with a socket_path binds a listening unix socket file."""
    path = _sock_path()
    inj = EventInjector(context=object(), socket_path=path)
    try:
        assert os.path.exists(path)
        assert inj._socket is not None
    finally:
        inj.close()
    assert not os.path.exists(path)


def test_injector_replaces_stale_socket_file():
    """A leftover file at the socket path is unlinked before binding."""
    path = _sock_path()
    with open(path, 'w') as fh:
        fh.write('stale')
    inj = EventInjector(context=object(), socket_path=path)
    try:
        assert inj._socket is not None
    finally:
        inj.close()


def test_poll_returns_empty_before_client_connects():
    """With no client yet, accept raises BlockingIOError and poll yields []."""
    path = _sock_path()
    inj = EventInjector(context=object(), socket_path=path)
    try:
        assert inj.poll() == []
    finally:
        inj.close()


def test_poll_parses_events_sent_over_socket():
    """Events written by an EventSender are parsed back into dicts."""
    path = _sock_path()
    inj = EventInjector(context=object(), socket_path=path)
    sender = EventSender(path)
    try:
        assert sender.connect(timeout=2.0)
        inj.poll()  # accept the connection
        sender.send_keyboard('p')
        sender.send_mousebutton(10, 20, button=1, state=1)
        events = _drain(inj, expected=2)
        assert {'type': 'keyboard', 'key': 'p'}.items() <= events[0].items()
        assert events[1]['type'] == 'mousebutton'
        assert events[1]['x'] == 10 and events[1]['button'] == 1
    finally:
        sender.close()
        inj.close()


def test_poll_skips_invalid_json_lines():
    """A malformed JSON line is dropped; valid lines around it still parse."""
    path = _sock_path()
    inj = EventInjector(context=object(), socket_path=path)
    sender = EventSender(path)
    try:
        assert sender.connect(timeout=2.0)
        inj.poll()
        sender._socket.send(b'{not valid json}\n{"type": "exit"}\n')
        events = _drain(inj, expected=1)
        assert len(events) == 1
        assert events[0]['type'] == 'exit'
    finally:
        sender.close()
        inj.close()


def test_poll_detects_client_disconnect():
    """When the client closes, recv sees EOF and the connection is dropped."""
    path = _sock_path()
    inj = EventInjector(context=object(), socket_path=path)
    sender = EventSender(path)
    try:
        assert sender.connect(timeout=2.0)
        inj.poll()  # accept
        sender.close()
        _drain(inj, expected=1, tries=20)  # let recv observe EOF
        assert inj._conn is None
    finally:
        inj.close()


def test_read_from_socket_handles_connection_reset():
    """A ConnectionResetError on recv drops the connection without raising."""
    path = _sock_path()
    inj = EventInjector(context=object(), socket_path=path)

    class _ResettingConn:
        def recv(self, _n):
            raise ConnectionResetError('peer reset')

        def close(self):
            pass

    try:
        inj._conn = _ResettingConn()  # type: ignore[assignment]
        assert inj._read_from_socket() == ''
        assert inj._conn is None
    finally:
        inj.close()


# --------------------------------------------------------------------------
# EventInjector: stdin receive path
# --------------------------------------------------------------------------


def test_stdin_injection_reads_json_lines(monkeypatch):
    """With use_stdin, poll reads and parses JSON lines from stdin."""
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, 'r')
    monkeypatch.setattr(sys, 'stdin', reader)

    inj = EventInjector(context=object(), use_stdin=True)
    os.write(write_fd, b'{"type": "keyboard", "key": "x"}\n')
    events = _drain(inj, expected=1)
    os.close(write_fd)
    reader.close()

    assert events and events[0] == {'type': 'keyboard', 'key': 'x'}


def test_stdin_read_returns_empty_when_no_data(monkeypatch):
    """A stdin with nothing available yields no events (non-blocking read)."""
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, 'r')
    monkeypatch.setattr(sys, 'stdin', reader)
    inj = EventInjector(context=object(), use_stdin=True)
    try:
        assert inj.poll() == []
    finally:
        os.close(write_fd)
        reader.close()


def test_read_available_with_no_source_is_empty():
    """An injector with neither socket nor stdin reads nothing."""
    inj = EventInjector(context=object())
    assert inj._read_available() == ''
    assert inj.poll() == []


def test_stdin_read_swallows_blocking_error(monkeypatch):
    """A BlockingIOError from a non-blocking stdin read yields empty data."""
    read_fd, write_fd = os.pipe()
    reader = os.fdopen(read_fd, 'r')
    monkeypatch.setattr(sys, 'stdin', reader)
    inj = EventInjector(context=object(), use_stdin=True)

    class _Blocking:
        def read(self, _n):
            raise BlockingIOError('would block')

    monkeypatch.setattr(sys, 'stdin', _Blocking())
    try:
        assert inj._read_from_stdin() == ''
    finally:
        os.close(write_fd)
        reader.close()


def test_close_swallows_teardown_errors():
    """close() ignores failures from the connection, socket and unlink."""
    inj = EventInjector(context=object())

    class _Boom:
        def close(self):
            raise OSError('cannot close')

    inj._conn = _Boom()  # type: ignore[assignment]
    inj._socket = _Boom()  # type: ignore[assignment]
    inj.socket_path = '/no/such/dir/never.sock'  # unlink will raise OSError
    inj.close()  # must not propagate


# --------------------------------------------------------------------------
# EventInjectionMixin: dispatch + setup
# --------------------------------------------------------------------------


class _FakeManager:
    def __init__(self) -> None:
        self.events: list = []

    def ProcessEvent(self, event: Any) -> None:
        self.events.append(event)


def _fake_context() -> Any:
    class FakeContext(EventInjectionMixin):
        def __init__(self) -> None:
            self._managers = {
                t: _FakeManager()
                for t in ('mousebutton', 'mousemove', 'keyboard', 'keypress')
            }
            self.resized: list = []
            self.quit_called = False

        def getEventManager(self, event_type: str) -> Any:
            return self._managers.get(event_type)

        def ProcessEvent(self, event: Any) -> Any:
            # What the real EventHandlerMixin does: look the manager up by the
            # event's own type and hand it over.
            manager = self._managers.get(event.type)
            if manager is not None:
                manager.ProcessEvent(event)

        def OnResize(self, width: int, height: int) -> None:
            self.resized.append((width, height))

        def OnQuit(self) -> None:
            self.quit_called = True

    return FakeContext()


def test_dispatch_mousemove_reaches_manager():
    """A mousemove event is turned into a MouseMoveEvent and dispatched."""
    ctx = _fake_context()
    ctx._dispatch_injected_event(
        {'type': 'mousemove', 'x': 5, 'y': 7, 'buttons': [0]}
    )
    events = ctx._managers['mousemove'].events
    assert len(events) == 1
    assert events[0].pickPoint == (5.0, 7.0)


def test_dispatch_resize_calls_onresize():
    """A resize event invokes the context OnResize with the given size."""
    ctx = _fake_context()
    ctx._dispatch_injected_event({'type': 'resize', 'width': 800, 'height': 600})
    assert ctx.resized == [(800, 600)]


def test_dispatch_unknown_type_is_ignored():
    """An unknown event type dispatches to no manager and does not raise."""
    ctx = _fake_context()
    ctx._dispatch_injected_event({'type': 'nonsense'})
    assert all(not m.events for m in ctx._managers.values())


def test_dispatch_capture_records_framebuffer(monkeypatch):
    """A capture event stores pixel data under its name in the captures dict."""
    ctx = _fake_context()
    ctx._injection_captures = {}

    class _FakeCapture:
        width = 4
        height = 3

        def capture(self, exclude_hud=False):
            return [0, 1, 2, 3]

    monkeypatch.setattr(
        'OpenGLContext.testing.framebuffer_comparison.FramebufferCapture',
        _FakeCapture,
    )
    ctx._dispatch_injected_event({'type': 'capture', 'name': 'shot1'})

    captures = ctx.get_injection_captures()
    assert 'shot1' in captures
    assert captures['shot1']['width'] == 4
    assert captures['shot1']['height'] == 3
    assert captures['shot1']['pixels'] == [0, 1, 2, 3]


def test_dispatch_exit_prefers_onquit():
    """An exit event closes the injector and calls OnQuit when present."""
    ctx = _fake_context()

    class _FakeInjector:
        closed = False

        def close(self):
            self.closed = True

    fake = _FakeInjector()
    ctx._event_injector = fake  # type: ignore[assignment]
    ctx._dispatch_injected_event({'type': 'exit'})

    assert fake.closed is True
    assert ctx._event_injector is None
    assert ctx.quit_called is True


def test_dispatch_exit_falls_back_to_flush_and_exit(monkeypatch):
    """Without an OnQuit hook, exit hard-exits via flush_and_exit."""
    exited = {'code': None}
    monkeypatch.setattr(
        'OpenGLContext.testing.event_injector.flush_and_exit',
        lambda code: exited.__setitem__('code', code),
    )

    class Ctx(EventInjectionMixin):
        def getEventManager(self, event_type):
            return None

    ctx = Ctx()
    ctx._do_injection_exit()
    assert exited['code'] == 0


def test_setup_event_injection_from_args_builds_injector():
    """setup_event_injection wires an EventInjector from a socket argument."""
    ctx = _fake_context()
    path = _sock_path()
    import argparse

    args = argparse.Namespace(event_socket=path, event_stdin=False)
    try:
        ctx.setup_event_injection(args)
        assert isinstance(ctx._event_injector, EventInjector)
    finally:
        if ctx._event_injector:
            ctx._event_injector.close()


def test_setup_event_injection_noop_without_arguments():
    """No socket and no stdin means no injector is created."""
    ctx = _fake_context()
    args = __import__('argparse').Namespace(event_socket=None, event_stdin=False)
    ctx.setup_event_injection(args)
    assert ctx._event_injector is None


def test_setup_event_injection_parses_argv(monkeypatch):
    """With args=None the mixin parses --event-socket from the command line."""
    ctx = _fake_context()
    path = _sock_path()
    monkeypatch.setattr(sys, 'argv', ['prog', '--event-socket', path])
    try:
        ctx.setup_event_injection()
        assert isinstance(ctx._event_injector, EventInjector)
        assert ctx._event_injector.socket_path == path
    finally:
        if ctx._event_injector:
            ctx._event_injector.close()


def test_poll_injected_events_dispatches_each(monkeypatch):
    """poll_injected_events routes every polled event through dispatch."""
    ctx = _fake_context()

    class _StubInjector:
        def poll(self):
            return [
                {'type': 'keyboard', 'key': 'a', 'state': 1},
                {'type': 'mousemove', 'x': 1, 'y': 2},
            ]

    ctx._event_injector = _StubInjector()  # type: ignore[assignment]
    ctx.poll_injected_events()

    assert len(ctx._managers['keyboard'].events) == 1
    assert len(ctx._managers['mousemove'].events) == 1


def test_poll_injected_events_without_injector_is_noop():
    """With no injector, polling does nothing and does not raise."""
    ctx = _fake_context()
    ctx._event_injector = None
    ctx.poll_injected_events()
    assert all(not m.events for m in ctx._managers.values())


def test_add_event_injection_arguments_registers_flags():
    """The classmethod adds the --event-socket/--event-stdin options."""
    import argparse

    parser = argparse.ArgumentParser()
    EventInjectionMixin.add_event_injection_arguments(parser)
    ns = parser.parse_args(['--event-socket', '/tmp/x.sock', '--event-stdin'])
    assert ns.event_socket == '/tmp/x.sock'
    assert ns.event_stdin is True


# --------------------------------------------------------------------------
# EventSender wire format
# --------------------------------------------------------------------------


def test_send_event_requires_connection():
    """Sending before connect raises a clear RuntimeError."""
    sender = EventSender('/tmp/never.sock')
    with pytest.raises(RuntimeError, match='Not connected'):
        sender.send_event({'type': 'exit'})


def test_sender_encodes_all_event_kinds():
    """Every send_* helper serialises the documented JSON shape."""
    path = _sock_path()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    sender = EventSender(path)
    try:
        assert sender.connect(timeout=2.0)
        conn, _ = server.accept()

        sender.send_mousemove(3, 4, buttons=[0], modifiers=[1, 0, 0])
        sender.send_keyboard('q', state=0)
        sender.send_capture('frame')
        sender.send_resize(320, 240)
        sender.send_exit()
        sender.wait(0.0)

        import json

        lines = []
        conn.settimeout(2.0)
        buf = b''
        while len(lines) < 5:
            buf += conn.recv(4096)
            parts = buf.split(b'\n')
            buf = parts.pop()
            lines.extend(p for p in parts if p)
        parsed = [json.loads(line) for line in lines]

        by_type = {p['type']: p for p in parsed}
        assert by_type['mousemove']['buttons'] == [0]
        assert by_type['mousemove']['modifiers'] == [1, 0, 0]
        assert by_type['keyboard'] == {'type': 'keyboard', 'key': 'q',
                                       'state': 0, 'modifiers': [0, 0, 0]}
        assert by_type['capture']['name'] == 'frame'
        assert by_type['resize'] == {'type': 'resize', 'width': 320, 'height': 240}
        assert by_type['exit'] == {'type': 'exit'}

        conn.close()
    finally:
        sender.close()
        server.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def test_sender_close_swallows_socket_error():
    """A socket that raises on close does not break EventSender.close()."""
    sender = EventSender('/tmp/x.sock')

    class _Boom:
        def close(self):
            raise OSError('cannot close')

    sender._socket = _Boom()  # type: ignore[assignment]
    sender.close()
    assert sender._socket is None


def test_sender_close_is_idempotent():
    """close() clears the socket and a second call is harmless."""
    path = _sock_path()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    sender = EventSender(path)
    try:
        assert sender.connect(timeout=2.0)
        sender.close()
        assert sender._socket is None
        sender.close()
    finally:
        server.close()
        try:
            os.unlink(path)
        except OSError:
            pass
