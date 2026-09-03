"""Event injection for automated interactive testing.

This module provides IPC-based event injection for testing interactive
OpenGLContext applications. Events are sent as JSON messages over a socket or
stdin.

Both ends name one path -- ``--event-socket`` on the application, the same
string to :class:`EventSender` -- and the transport underneath it is whichever
the platform has. Where there are Unix domain sockets the path is the socket;
where there are not, the listener takes a loopback TCP port and writes the
number into a file at that path for the sender to read. The stdin transport
needs ``fcntl`` and so is POSIX-only.

The loopback port reaches no further than the machine, but it carries no
filesystem permissions the way a Unix socket does: while an application is
listening, any process on the same machine can drive it. This is test
machinery, and what it drives is a program under test.

Usage in test scripts:
    class MyTestContext(EventInjectionMixin, BaseContext):
        def OnInit(self):
            self.setup_event_injection()
            # ... setup scene ...

    if __name__ == '__main__':
        MyTestContext.ContextMainLoop()

From test code:
    proc = subprocess.Popen(['python', 'test.py', '--event-socket', '/tmp/test.sock'])
    sender = EventSender('/tmp/test.sock')
    sender.connect()
    sender.send_keyboard('p')
    sender.send_mousebutton(100, 200, button=0, state=1)
    sender.send_exit()
"""

import argparse
import json
import logging
import os
import socket
import sys
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from OpenGLContext.events import synthetic
from OpenGLContext.testing.process_exit import flush_and_exit

try:
    import fcntl
except ImportError:
    # POSIX-only, and wanted by one method: making stdin non-blocking.  The
    # socket transport does not need it, and neither does importing this
    # module -- which the pytest plugin does, so letting the ImportError out
    # would take every test on the platform with it.
    fcntl = None

#: Unix domain sockets carry the event stream where there are any.  Windows has
#: had them since 1803, but CPython does not expose AF_UNIX there, so on that
#: platform the stream goes over a loopback TCP connection instead.
HAVE_UNIX_SOCKETS = hasattr(socket, 'AF_UNIX')

#: The loopback transport's rendezvous: the listener binds port 0, lets the
#: kernel choose, and writes the number it got into the file the caller named.
#: The caller therefore still names one path and nothing above here has to know
#: which transport it got.
LOOPBACK_HOST = '127.0.0.1'


def _stream_socket() -> socket.socket:
    """A stream socket of whichever family carries events on this platform."""
    family = socket.AF_UNIX if HAVE_UNIX_SOCKETS else socket.AF_INET
    return socket.socket(family, socket.SOCK_STREAM)


def _bind_listener(sock: socket.socket, path: str) -> None:
    """Bind *sock* so that a sender naming *path* can reach it."""
    if HAVE_UNIX_SOCKETS:
        sock.bind(path)
        return
    sock.bind((LOOPBACK_HOST, 0))
    port = sock.getsockname()[1]
    # Written whole and moved into place, so a sender that finds the file never
    # reads half a number: it polls for the file's existence to know we are up.
    temporary = path + '.partial'
    with open(temporary, 'w', encoding='ascii') as handle:
        handle.write('%d\n' % (port,))
    os.replace(temporary, path)


def _sender_address(path: str):
    """Where a sender should connect to reach the listener named by *path*.

    Raises :class:`FileNotFoundError` while the listener has yet to publish
    itself, which is the same signal an unbound Unix socket path gives and is
    what the connect loop already waits on.
    """
    if HAVE_UNIX_SOCKETS:
        return path
    with open(path, encoding='ascii') as handle:
        return (LOOPBACK_HOST, int(handle.read().strip()))


log = logging.getLogger(__name__)


class EventInjector:
    """Receives JSON events from socket or stdin and dispatches them."""

    def __init__(
        self,
        context: Any,
        socket_path: Optional[str] = None,
        use_stdin: bool = False,
    ):
        """Initialize the event injector.

        Args:
            context: The OpenGLContext instance to dispatch events to
            socket_path: Rendezvous path for the socket transport (mutually
                exclusive with use_stdin)
            use_stdin: Read events from stdin instead of socket
        """
        self.context = context
        self.socket_path = socket_path
        self.use_stdin = use_stdin
        self._buffer = ''
        self._socket: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None
        self._captures: Dict[str, Any] = {}

        if socket_path:
            self._setup_socket(socket_path)
        elif use_stdin:
            self._setup_stdin()

    def _setup_socket(self, path: str) -> None:
        """Set up the listener a sender naming *path* can reach."""
        # Remove whatever a previous run left at the path -- a socket node, or
        # the published port of a listener that is gone.
        try:
            os.unlink(path)
        except OSError:
            pass

        self._socket = _stream_socket()
        _bind_listener(self._socket, path)
        self._socket.listen(1)
        self._socket.setblocking(False)
        self._conn = None

    def _setup_stdin(self) -> None:
        """Set up non-blocking stdin reading."""
        if fcntl is None:
            raise RuntimeError(
                'stdin event injection needs fcntl, which this platform does '
                'not have; give --event-socket a path to use the socket '
                'transport instead'
            )
        # Make stdin non-blocking
        fd = sys.stdin.fileno()
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def poll(self) -> List[Dict[str, Any]]:
        """Poll for and return available events.

        Returns:
            List of parsed JSON event dictionaries
        """
        events = []

        # Read available data
        data = self._read_available()
        if data:
            self._buffer += data

        # Parse complete JSON lines
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            line = line.strip()
            if line:
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError as e:
                    log.warning("EventInjector: Invalid JSON: %s... (%s)", line[:50], e)

        return events

    def _read_available(self) -> str:
        """Read available data from socket or stdin."""
        if self._socket is not None:
            return self._read_from_socket()
        elif self.use_stdin:
            return self._read_from_stdin()
        return ''

    def _read_from_socket(self) -> str:
        """Read available data from socket."""
        assert self._socket is not None  # reached only while the listener exists
        data = ''

        # Accept new connection if needed
        if self._conn is None:
            try:
                self._conn, _ = self._socket.accept()
                self._conn.setblocking(False)
            except BlockingIOError:
                return ''

        # Read from connection
        try:
            chunk = self._conn.recv(4096)
            if chunk:
                data = chunk.decode('utf-8')
            else:
                # Connection closed
                self._conn.close()
                self._conn = None
        except BlockingIOError:
            pass
        except ConnectionResetError:
            if self._conn is not None:
                self._conn.close()
            self._conn = None

        return data

    def _read_from_stdin(self) -> str:
        """Read available data from stdin."""
        try:
            data = sys.stdin.read(4096)
            return data if data else ''
        except (BlockingIOError, IOError):
            return ''

    def close(self) -> None:
        """Clean up resources."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            if self.socket_path:
                try:
                    os.unlink(self.socket_path)
                except OSError:
                    pass


class EventInjectionMixin:
    """Mixin to add event injection support to OpenGLContext classes.

    Add this mixin to your context class and call setup_event_injection()
    in OnInit() to enable event injection from external test code.

    Example:
        class MyTestContext(EventInjectionMixin, BaseContext):
            def OnInit(self):
                self.setup_event_injection()
                # ... rest of initialization ...
    """

    _event_injector: Optional[EventInjector] = None
    _injection_captures: Dict[str, Any] = {}

    if TYPE_CHECKING:
        # Provided by the concrete Context this mixin is composed into
        # (OpenGLContext.events.eventhandlermixin.EventHandlerMixin and
        # OpenGLContext.context.Context).
        def getEventManager(self, eventType: str) -> Any: ...
        def addPickEvent(self, event: Any) -> None: ...
        def triggerPick(self) -> None: ...
        def ProcessEvent(self, event: Any) -> Any: ...
        def OnResize(self, width: int, height: int) -> None: ...

    @classmethod
    def add_event_injection_arguments(cls, parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        """Add event injection arguments to an argument parser."""
        group = parser.add_argument_group('Event Injection')
        group.add_argument(
            '--event-socket',
            type=str,
            help='Unix socket path for event injection',
        )
        group.add_argument(
            '--event-stdin',
            action='store_true',
            help='Read events from stdin (JSON lines)',
        )
        return parser

    @classmethod
    def parse_event_injection_arguments(cls) -> argparse.Namespace:
        """Parse command-line arguments for event injection."""
        parser = argparse.ArgumentParser()
        cls.add_event_injection_arguments(parser)
        args, _ = parser.parse_known_args()
        return args

    def setup_event_injection(self, args: Optional[argparse.Namespace] = None) -> None:
        """Set up event injection from socket or stdin.

        Call this from OnInit() to enable event injection.

        Args:
            args: Parsed arguments, or None to parse from command line
        """
        if args is None:
            args = self.parse_event_injection_arguments()

        socket_path = getattr(args, 'event_socket', None)
        use_stdin = getattr(args, 'event_stdin', False)

        if socket_path or use_stdin:
            self._event_injector = EventInjector(
                context=self,
                socket_path=socket_path,
                use_stdin=use_stdin,
            )
            self._injection_captures = {}

    def poll_injected_events(self) -> None:
        """Poll for and process injected events.

        Call this from your render loop or use OnPostRender hook.
        """
        if self._event_injector is None:
            return

        for event in self._event_injector.poll():
            self._dispatch_injected_event(event)

    def _dispatch_injected_event(self, event: Dict[str, Any]) -> None:
        """Convert JSON event to OpenGLContext event and dispatch.

        The input vocabulary is :mod:`OpenGLContext.events.synthetic`, shared
        with the session recorder and its replay, so a script written for this
        is understood by them and a recorded session can be replayed by a test.

        Args:
            event: Parsed JSON event dictionary
        """
        event_type = event.get('type')

        if event_type == 'capture':
            self._do_injection_capture(event.get('name', 'capture'))
        elif event_type == 'exit':
            self._do_injection_exit()
        elif event_type == 'keyboard':
            self._inject_keyboard(event)
        elif event_type in synthetic.KINDS:
            synthetic.dispatch(self, event)
        else:
            log.warning("EventInjector: Unknown event type: %s", event_type)

    def _inject_keyboard(self, event: Dict[str, Any]) -> None:
        """Inject a raw key, and the character a press of it also produces.

        A key generates a low-level ``keyboard`` event, and on press a
        ``keypress`` as well -- the latter is what most application handlers
        bind to through ``addEventHandler("keypress", ...)``.  A script says
        "the player pressed this key" once and gets both, because that is what
        pressing a key on a keyboard does.
        """
        synthetic.dispatch(self, event)
        if event.get('state', 1):
            synthetic.dispatch(self, {
                'type': 'keypress',
                'key': event.get('key', ''),
                'modifiers': event.get('modifiers', [0, 0, 0]),
            })

    def _do_injection_capture(self, name: str) -> None:
        """Capture framebuffer for test verification.

        Args:
            name: Name for the capture (used as key in captures dict)
        """
        from OpenGLContext.testing.framebuffer_comparison import FramebufferCapture

        capture = FramebufferCapture()
        pixels = capture.capture(exclude_hud=True)
        self._injection_captures[name] = {
            'pixels': pixels,
            'width': capture.width,
            'height': capture.height,
            'timestamp': time.time(),
        }
        log.info("CAPTURE: %s (%dx%d)", name, capture.width, capture.height)

    def _do_injection_exit(self) -> None:
        """Handle exit request from test code."""
        # Clean up injector
        if self._event_injector:
            self._event_injector.close()
            self._event_injector = None

        # Exit the context
        if hasattr(self, 'OnQuit'):
            self.OnQuit()
        else:
            flush_and_exit(0)

    def get_injection_captures(self) -> Dict[str, Any]:
        """Get all captured framebuffers.

        Returns:
            Dict mapping capture names to capture data
        """
        return self._injection_captures


class EventSender:
    """Sends events to a test subprocess over the injection socket.

    Use this class from test code to send events to a running
    OpenGLContext application. The path given here is the one the application
    was started with; which transport carries it is settled per platform.

    Example:
        sender = EventSender('/tmp/test.sock')
        sender.connect()
        sender.send_keyboard('p')
        sender.send_mousebutton(100, 200, button=0)
        sender.send_exit()
        sender.close()
    """

    def __init__(self, socket_path: str):
        """Initialize the sender.

        Args:
            socket_path: The path the application was given as --event-socket
        """
        self.socket_path = socket_path
        self._socket: Optional[socket.socket] = None

    def connect(self, timeout: float = 10.0) -> bool:
        """Connect to the event socket with polling.

        Args:
            timeout: Maximum time to wait for socket

        Returns:
            True if connected, False otherwise
        """
        start = time.time()

        while time.time() - start < timeout:
            # A fresh socket per attempt: a stream socket whose connect() was
            # refused cannot be connected again, so retrying on the same one
            # would fail for a reason that has nothing to do with the listener.
            attempt = _stream_socket()
            try:
                attempt.connect(_sender_address(self.socket_path))
            except (OSError, ValueError):
                # OSError: the listener has not published itself yet, or has
                # published and is not yet accepting.  ValueError: the port file
                # was caught mid-write.  Both mean "not up yet, try again".
                attempt.close()
                time.sleep(0.05)  # 50ms between attempts
            else:
                self._socket = attempt
                return True

        return False

    def send_event(self, event: Dict[str, Any]) -> None:
        """Send a raw event dictionary.

        Args:
            event: Event dictionary to send
        """
        if self._socket is None:
            raise RuntimeError("Not connected - call connect() first")
        data = json.dumps(event) + '\n'
        self._socket.send(data.encode('utf-8'))

    def send_mousebutton(
        self,
        x: int,
        y: int,
        button: int = 0,
        state: int = 1,
        modifiers: Optional[List[int]] = None,
        pick: bool = False,
    ) -> None:
        """Send a mouse button event.

        Args:
            x: X coordinate
            y: Y coordinate
            button: Button number (0=left, 1=middle, 2=right)
            state: 1 for press, 0 for release
            modifiers: [shift, ctrl, alt] states
            pick: route it through the selection pass, as a window does, so the
                event carries the nodes under the cursor and is delivered when
                the pick resolves
        """
        self.send_event({
            'type': 'mousebutton',
            'x': x,
            'y': y,
            'button': button,
            'state': state,
            'modifiers': modifiers or [0, 0, 0],
            'pick': bool(pick),
        })

    def send_mousemove(
        self,
        x: int,
        y: int,
        buttons: Optional[List[int]] = None,
        modifiers: Optional[List[int]] = None,
        pick: bool = False,
    ) -> None:
        """Send a mouse move event.

        Args:
            x: X coordinate
            y: Y coordinate
            buttons: List of pressed button numbers
            modifiers: [shift, ctrl, alt] states
            pick: route it through the selection pass, as a window does
        """
        self.send_event({
            'type': 'mousemove',
            'x': x,
            'y': y,
            'buttons': buttons or [],
            'modifiers': modifiers or [0, 0, 0],
            'pick': bool(pick),
        })

    def send_keyboard(
        self,
        key: str,
        state: int = 1,
        modifiers: Optional[List[int]] = None,
    ) -> None:
        """Send a keyboard event.

        Args:
            key: Key name (e.g., 'a', 'Enter', 'Escape')
            state: 1 for press, 0 for release
            modifiers: [shift, ctrl, alt] states
        """
        self.send_event({
            'type': 'keyboard',
            'key': key,
            'state': state,
            'modifiers': modifiers or [0, 0, 0],
        })

    def send_capture(self, name: str) -> None:
        """Request a framebuffer capture.

        Args:
            name: Name for the capture
        """
        self.send_event({'type': 'capture', 'name': name})

    def send_resize(self, width: int, height: int) -> None:
        """Send a resize event.

        Args:
            width: New width in pixels
            height: New height in pixels
        """
        self.send_event({'type': 'resize', 'width': width, 'height': height})

    def send_exit(self) -> None:
        """Request the subprocess to exit."""
        self.send_event({'type': 'exit'})

    def wait(self, duration: float) -> None:
        """Wait for a duration (for event timing).

        Args:
            duration: Time to wait in seconds
        """
        time.sleep(duration)

    def close(self) -> None:
        """Close the socket connection."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
