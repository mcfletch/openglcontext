"""A ground cover's scatter, made in a child process.

The scatter is numpy over a hash of each cell. It runs on threads of the process
that renders, and every thread of a process shares one interpreter lock: a scatter
that takes a few milliseconds of its own makes the render thread wait for it, a
few milliseconds a frame at the speed a vehicle covers new ground. A child process
runs the same scatter with no lock to share.

:class:`CoverProcess` is the parent's end. A cover given one
(:meth:`GroundCover.use_process
<OpenGLContext.scenegraph.vegetation.cover.GroundCover.use_process>`) asks it for each
disc and for the ground to make ahead, and receives the arrays. :class:`CoverScatterMaker` is
the child's end: built by the factory the process names, from a cover of the same
ground, species, mask, shade and canopy as the parent's, it answers each request with the
cover's own scatter, so what it makes is what the cover makes in line. The child keeps the
blocks it has made as the cover does, and ground the parent asked for ahead is there when
the disc that reaches it is asked for.

The child starts in the background and the cover asks it only once it is ready
(:attr:`CoverProcess.ready`); until then, and after the child stops, the cover scatters in
line.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING, Any

from OpenGLContext.loaders.tiles3d.tileprocess import TileProcesses, TileProcessError

if TYPE_CHECKING:
    from OpenGLContext.scenegraph.vegetation.cover import GroundCover

log = logging.getLogger(__name__)

__all__ = ['CoverProcess', 'CoverProcessError', 'CoverScatterMaker']

#: A request the child could not answer, or a child that stopped.
CoverProcessError = TileProcessError


class CoverProcess:
    """One child process that scatters a ground cover, and the connection to it.

    ``factory`` is ``"package.module:function"``, called in the child with ``args`` to build
    a :class:`CoverScatterMaker`. With ``start`` the child is started in the background
    now; without, it starts at the first request.
    """

    def __init__(self, factory: str, args: tuple[Any, ...] = (), start: bool = True) -> None:
        self._processes = TileProcesses(factory, args, count=1)
        self._ready = threading.Event()
        self._failed = False
        self._closed = False
        #: How many requests the child has been sent.
        self.requests = 0
        if start:
            self.start()

    def start(self) -> None:
        """Start the child, on a thread of its own; :attr:`ready` says when it is up."""
        threading.Thread(target=self._start, name='ground-cover-process', daemon=True).start()

    def _start(self) -> None:
        try:
            self._processes.make(('process',))
        except CoverProcessError as err:
            self._failed = True
            log.warning('the ground cover process did not start: %s', err)
            return
        self._ready.set()

    @property
    def ready(self) -> bool:
        """Whether the child is up and can be asked."""
        return self._ready.is_set() and not self._failed and not self._closed

    @property
    def closed(self) -> bool:
        """Whether :meth:`close` has been called."""
        return self._closed

    def wait_until_ready(self, timeout: float | None = None) -> bool:
        """Wait for the child to be up; whether it is."""
        self._ready.wait(timeout)
        return self.ready

    def disc(self, rung: int, role: str, x: float, z: float, radius: float,
             density: float, height: float) -> tuple:
        """The plants of species ``rung`` for ``role`` within ``radius`` of ``(x, z)``, as the arrays
        :meth:`GroundCover._scatter <OpenGLContext.scenegraph.vegetation.cover.GroundCover>` makes."""
        return self._request(('disc', rung, role, x, z, radius, density, height))  # type: ignore[no-any-return]  # a pickled tuple of arrays

    def warm(self, rung: int, role: str, x: float, z: float, radius: float,
             density: float, height: float) -> None:
        """Make the blocks the disc about ``(x, z)`` will reach, so asking for it finds them made."""
        self._request(('warm', rung, role, x, z, radius, density, height))

    def scattered(self) -> int:
        """How many blocks of ground the child has scattered."""
        return int(self._request(('built',)))

    def process_id(self) -> int:
        """The child's process id."""
        return int(self._request(('process',)))

    def _request(self, key: tuple) -> Any:
        self.requests += 1
        return self._processes.make(key)

    def close(self) -> None:
        """Stop the child. Calls after this raise :class:`CoverProcessError`."""
        self._closed = True
        self._processes.close()


class CoverScatterMaker:
    """The child's end: answers a :class:`CoverProcess`'s requests from ``cover``'s own scatter.

    ``cover`` is built from the same ground and rules as the parent's, with no draw nodes
    needed: only its scatter is used.
    """

    def __init__(self, cover: GroundCover) -> None:
        self.cover = cover

    def make(self, key: tuple) -> Any:
        kind = key[0]
        if kind == 'disc':
            _, rung, role, x, z, radius, density, height = key
            return self.cover._scatter_here(self.cover.rungs[rung], role, x, z, radius, density, height)  # noqa: SLF001 the scatter this process exists to run
        if kind == 'warm':
            _, rung, role, x, z, radius, density, height = key
            self.cover._warm_here(rung, role, x, z, radius, density, height)  # noqa: SLF001 the scatter this process exists to run
            return None
        if kind == 'built':
            return self.cover.scattered
        if kind == 'process':
            return os.getpid()
        raise ValueError('no request called %r' % (kind,))
