"""Tile content made in worker processes, so a busy render thread does not slow it.

A tile is built from numpy arrays by Python code, and every thread of a process shares one
interpreter lock: while the render thread is running Python, the threads of a
:class:`~OpenGLContext.loaders.tiles3d.loadmanager.LoadManager` get a small share of the time
and a tile that takes 0.3 s on its own takes several seconds. :class:`TileProcesses` runs a
*maker* in child processes instead. The maker is built in each child from a factory named
``"package.module:function"`` and called with the arguments given::

    maker = factory(*args)
    payload = maker.make(key)

``make(key)`` returns the tile's content as plain data -- arrays, tuples, dataclasses -- that
pickles; it builds no scenegraph node that must share an identity with the parent's (a
material, a texture) and makes no GL call. The parent turns the payload into nodes
(:meth:`GeneratedTileset.loader
<OpenGLContext.loaders.tiles3d.generated.GeneratedTileset.loader>` calls the generator's
``assemble(key, payload)``).

Each child is a fresh interpreter started with ``python -m``, not a fork of a process that
holds a GL context, and the parent's main module is not run again in it. The two ends talk over a
loopback socket that only a process holding the token the parent made for it can use; a payload
travels as one pickled message. A child ends when the socket closes, so it does not outlive the
parent.
"""
import atexit
import pickle
import queue
import secrets
import socket
import struct
import subprocess
import sys
import threading
import traceback
import weakref
from collections.abc import Callable
from importlib import import_module
from typing import Any

__all__ = ['TileProcesses', 'TileProcessError', 'TileProcessInterrupted']

#: Seconds a child has to start, import its factory and connect.
START_TIMEOUT = 60.0
#: Seconds a child whose connection broke is given to be seen ending.
EXIT_GRACE = 0.5
#: The status a child ends with when an interrupt stopped it: 128 and SIGINT's number.
INTERRUPTED = 130
_LENGTH = struct.Struct('!Q')


class TileProcessError(RuntimeError):
    """A tile could not be made by a child process: the maker raised (the message is its
    traceback), or the child stopped."""


class TileProcessInterrupted(TileProcessError):
    """A child ended on an interrupt. A terminal's Ctrl-C reaches every process of its group, so
    the application is ending too, and this is not a fault in the child."""


def _send(sock: socket.socket, message: Any) -> None:
    data = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
    sock.sendall(_LENGTH.pack(len(data)))
    sock.sendall(data)


def _receive_exactly(sock: socket.socket, count: int) -> bytearray:
    buffer = bytearray(count)
    view, got = memoryview(buffer), 0
    while got < count:
        n = sock.recv_into(view[got:])
        if not n:
            raise EOFError('the other end of the tile socket closed')
        got += n
    return buffer


def _receive(sock: socket.socket) -> Any:
    (length,) = _LENGTH.unpack(_receive_exactly(sock, _LENGTH.size))
    return pickle.loads(_receive_exactly(sock, length))


def _factory(path: str) -> Callable[..., Any]:
    module, _, name = path.partition(':')
    return getattr(import_module(module), name)  # type: ignore[no-any-return]  # a factory is any callable


class _Child:
    """One child process and the socket to it."""

    def __init__(self, listener: socket.socket, token: str, factory: str, args: tuple[Any, ...]):
        host, port = listener.getsockname()
        # The address and token go down the child's standard input, not its command line, which
        # other users of the machine can read.
        self.process = subprocess.Popen([sys.executable, '-m', __name__], stdin=subprocess.PIPE)
        try:
            assert self.process.stdin is not None
            self.process.stdin.write(('%s %d %s\n' % (host, port, token)).encode())
            self.process.stdin.close()
            self.sock = self._accept(listener, token)
            _send(self.sock, (list(sys.path), factory, args))
            answer = _receive(self.sock)
        except BaseException:
            self.kill()
            raise
        if answer is not None:
            self.kill()
            raise TileProcessError('the tile maker could not be built:\n%s' % answer)

    def _accept(self, listener: socket.socket, token: str) -> socket.socket:
        listener.settimeout(1.0)
        waited = 0.0
        while True:
            try:
                sock, _ = listener.accept()
            except TimeoutError:
                waited += 1.0
                if self.process.poll() is not None:
                    raise TileProcessError('the tile process stopped before it connected') from None
                if waited >= START_TIMEOUT:
                    raise TileProcessError('the tile process did not connect in %d s' % START_TIMEOUT) from None
                continue
            sock.settimeout(START_TIMEOUT)
            try:
                shown = _receive(sock)
            except (OSError, EOFError, pickle.UnpicklingError):
                sock.close()
                continue
            if isinstance(shown, str) and secrets.compare_digest(shown, token):
                sock.settimeout(None)
                return sock
            sock.close()

    def make(self, key: Any) -> Any:
        _send(self.sock, key)
        ok, result = _receive(self.sock)
        if not ok:
            raise TileProcessError(result)
        return result

    def interrupted(self) -> bool:
        """Whether the child ended on an interrupt."""
        try:
            return self.process.wait(timeout=EXIT_GRACE) == INTERRUPTED
        except subprocess.TimeoutExpired:
            return False

    def kill(self) -> None:
        sock = getattr(self, 'sock', None)
        if sock is not None:
            sock.close()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()

    def close(self) -> None:
        try:
            _send(self.sock, None)
        except OSError:
            pass
        self.sock.close()
        try:
            self.process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


class TileProcesses:
    """``count`` child processes that each hold a maker built by ``factory(*args)``.

    :meth:`make` may be called from as many threads at once as there are processes; a call
    waits its turn when they are all busy. Children start on the first call that needs one.
    """

    def __init__(self, factory: str, args: tuple[Any, ...] = (), count: int = 2) -> None:
        if count < 1:
            raise ValueError('count must be at least 1, not %r' % (count,))
        self.factory, self.args, self.count = factory, tuple(args), count
        self._token = secrets.token_hex(16)
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(('127.0.0.1', 0))
        self._listener.listen(count)
        self._idle: "queue.Queue[_Child | None]" = queue.Queue()
        for _ in range(count):
            self._idle.put(None)
        self._starting = threading.Lock()
        self._children: "list[_Child]" = []
        self._closed = False
        atexit.register(_close_weakly, weakref.ref(self))

    def __enter__(self) -> "TileProcesses":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def make(self, key: Any) -> Any:
        """The payload the maker makes for ``key``, made in a child process."""
        if self._closed:
            raise TileProcessError('the tile processes are closed')
        child = self._idle.get()
        try:
            if child is None:
                with self._starting:
                    child = _Child(self._listener, self._token, self.factory, self.args)
                self._children.append(child)
            return child.make(key)
        except (OSError, EOFError) as err:
            interrupted = child is not None and child.interrupted()
            if child is not None:
                self._forget(child)
                child = None
            if interrupted:
                raise TileProcessInterrupted('a tile process was interrupted while making %r' % (key,)) from err
            raise TileProcessError('a tile process stopped while making %r: %s' % (key, err)) from err
        except TileProcessError:
            raise
        finally:
            self._idle.put(child)

    def _forget(self, child: _Child) -> None:
        child.kill()
        if child in self._children:
            self._children.remove(child)

    def close(self) -> None:
        """Stop the children and the socket. Calls after this raise :class:`TileProcessError`."""
        self._closed = True
        for child in list(self._children):
            child.close()
        self._children.clear()
        self._listener.close()


def _close_weakly(ref: "weakref.ref[TileProcesses]") -> None:
    processes = ref()
    if processes is not None:
        processes.close()


def _serve() -> int:
    """The child's end: connect, build the maker, and make a payload for each key until the
    socket closes. The exit status: :data:`INTERRUPTED` when an interrupt stopped it, else 0.

    The parent closing the socket, or ending, is how a child is told to stop, so a connection
    that fails is an ending and prints nothing.
    """
    try:
        _converse()
    except KeyboardInterrupt:
        return INTERRUPTED
    except (EOFError, OSError):
        pass
    return 0


def _converse() -> None:
    host, port, token = sys.stdin.readline().split()
    sock = socket.create_connection((host, int(port)))
    _send(sock, token)
    paths, factory, args = _receive(sock)
    sys.path.extend(p for p in paths if p not in sys.path)
    try:
        maker = _factory(factory)(*args)
    except Exception:
        _send(sock, traceback.format_exc())
        return
    _send(sock, None)
    while True:
        key = _receive(sock)
        if key is None:
            return
        try:
            reply: tuple[bool, Any] = (True, maker.make(key))
        except Exception:
            reply = (False, traceback.format_exc())
        _send(sock, reply)


if __name__ == '__main__':  # pragma: no cover - runs in the child
    sys.exit(_serve())
