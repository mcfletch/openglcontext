"""How long the GPU spent on a stretch of a frame, without waiting for it.

A ``GL_TIME_ELAPSED`` query's answer is ready only once the GPU has finished
the work it brackets, and asking for it sooner stalls the CPU until then.
:class:`GpuTimer` keeps a ring of queries: each frame's is issued into the next
slot, and the answer read is the newest one the driver reports ready, which is
normally the one issued :data:`DEPTH` - 1 frames ago. Nothing waits on the GPU.

GL allows one ``GL_TIME_ELAPSED`` query at a time, so timers do not nest.
"""
from __future__ import annotations

from typing import List, Optional

__all__ = ['DEPTH', 'GpuTimer']

#: Queries in the ring: an answer is read this many frames, less one, after
#: the work it measures was issued.
DEPTH = 3


class GpuTimer:
    """Milliseconds of GPU time for a bracketed stretch, a frame or two late."""

    def __init__(self, depth: int = DEPTH) -> None:
        self.depth = int(depth)
        self._queries: List[int] = []
        self._issued: List[bool] = [False] * self.depth
        self._next = 0
        self._open = False
        #: The newest measurement read back, in milliseconds, or None.
        self.milliseconds: Optional[float] = None

    def begin(self) -> None:
        """Start timing; everything issued until :meth:`end` is measured."""
        from OpenGL import GL as gl
        if not self._queries:
            self._queries = [int(name) for name in gl.glGenQueries(self.depth)]
        self._collect()
        gl.glBeginQuery(gl.GL_TIME_ELAPSED, self._queries[self._next])
        self._open = True

    def end(self) -> None:
        """Stop timing what :meth:`begin` started."""
        from OpenGL import GL as gl
        if not self._open:
            return
        gl.glEndQuery(gl.GL_TIME_ELAPSED)
        self._open = False
        self._issued[self._next] = True
        self._next = (self._next + 1) % self.depth

    def _collect(self) -> None:
        """Read every finished query, oldest first, keeping the newest answer."""
        from OpenGL import GL as gl
        for step in range(self.depth):
            slot = (self._next + step) % self.depth
            if not self._issued[slot]:
                continue
            query = self._queries[slot]
            ready = gl.glGetQueryObjectuiv(query, gl.GL_QUERY_RESULT_AVAILABLE)
            if not int(ready):
                continue
            nanoseconds = gl.glGetQueryObjectui64v(query, gl.GL_QUERY_RESULT)
            self.milliseconds = int(nanoseconds) / 1.0e6
            self._issued[slot] = False

    def release(self) -> None:
        """Give back the queries."""
        from OpenGL import GL as gl
        if self._queries:
            gl.glDeleteQueries(self.depth, self._queries)
        self._queries = []
        self._issued = [False] * self.depth
        self._open = False
