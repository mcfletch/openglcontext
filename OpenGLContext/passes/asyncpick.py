"""Non-blocking (asynchronous) pick readback for :class:`SelectionMixin`.

A synchronous ``glReadPixels`` under a pick sample stalls the CPU on the GPU. This
mixin instead reads each sample's object-id and depth into a pooled Pixel Pack
Buffer, fences it, and dispatches the resolved events a frame later once the fence
has signalled. :class:`SelectionMixin` inherits it, so ``self`` is the pass. The
pick *policy* lives in :mod:`selection`; this module holds the PBO/fence plumbing.

Also home to :meth:`_AsyncPickMixin._dispatchPickEvent`, the one place the
``setObjectPaths``/``viewCoordinate``/matrix event-population sequence lives — the
sync MRT path, the legacy per-pick path and the async resolve path all funnel
through it so the three cannot drift.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import ctypes

import numpy as np

from OpenGL.GL import (
    GL_ALREADY_SIGNALED, GL_COLOR_ATTACHMENT1, GL_CONDITION_SATISFIED,
    GL_DEPTH_COMPONENT, GL_FLOAT, GL_MAP_READ_BIT, GL_PIXEL_PACK_BUFFER,
    GL_READ_FRAMEBUFFER, GL_READ_FRAMEBUFFER_BINDING, GL_RGBA, GL_STREAM_READ,
    GL_SYNC_FLUSH_COMMANDS_BIT, GL_SYNC_GPU_COMMANDS_COMPLETE, GL_UNSIGNED_BYTE,
    glBindBuffer, glBindFramebuffer, glBufferData, glClientWaitSync, glDeleteSync,
    glFenceSync, glGenBuffers, glGetIntegerv, glMapBufferRange, glReadBuffer,
    glReadPixels, glUnmapBuffer,
)
# frombuffer is numpy.frombuffer re-exported through vrml.arrays' star import,
# which mypy cannot trace across.
from OpenGLContext.arrays import frombuffer  # type: ignore[attr-defined]
import logging

if TYPE_CHECKING:
    from OpenGLContext.passes.selectionbuffers import SelectionBufferFBO

log = logging.getLogger(__name__)


class _AsyncPickMixin:
    """Async PBO-fenced pick readback + the shared pick-event dispatch helper."""

    use_async_pick: bool = True
    _async_batches: Optional[List] = None
    _pbo_free: Optional[List] = None
    _ASYNC_MAX_INFLIGHT = 4

    if TYPE_CHECKING:
        matrix: Any
        projection: Any
        viewport: Any

        def _getSelectionBuffer(self) -> "SelectionBufferFBO": ...

    @staticmethod
    def _dispatchPickEvent(mode: Any, event: Any, object_paths: List,
                           x: float, y: float, depth: float,
                           matrix: Any, projection: Any, viewport: Any) -> None:
        """Populate a pick event and hand it to the context.

        ``object_paths`` is the already-formed list passed to
        ``event.setObjectPaths`` (the callers differ on how they wrap a hit path,
        so they form it and this only sets it), keeping the three pick paths in
        lock-step for every other field.
        """
        event.setObjectPaths(object_paths)
        event.viewCoordinate = x, y, depth
        event.modelViewMatrix = matrix
        event.projectionMatrix = projection
        event.viewport = viewport
        if hasattr(mode.context, 'ProcessEvent'):
            mode.context.ProcessEvent(event)

    def _acquirePBO(self, nbytes: int) -> tuple[int, int]:
        """Get a pooled Pixel Pack Buffer of at least nbytes (id, capacity)."""
        pool = self._pbo_free
        if pool is None:
            pool = self._pbo_free = []
        for i, (pid, cap) in enumerate(pool):
            if cap >= nbytes:
                pool.pop(i)
                return pid, cap
        pid = int(glGenBuffers(1))
        cap = max(nbytes, 256)
        glBindBuffer(GL_PIXEL_PACK_BUFFER, pid)
        glBufferData(GL_PIXEL_PACK_BUFFER, cap, None, GL_STREAM_READ)
        glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)
        return pid, cap

    def _releasePBO(self, pid: int, cap: int) -> None:
        if self._pbo_free is None:
            self._pbo_free = []
        self._pbo_free.append((pid, cap))

    def submitAsyncPicks(self, mode: Any, events: Dict, id_map: Dict) -> None:
        """Issue async reads of object-id + depth under each pick sample.

        Reads from the MRT selection FBO (which now holds this frame's render)
        into pooled PBOs and records a fence; the batch is resolved by
        drainAsyncPicks on a later frame. Must run after the selection buffer
        has been rendered this frame.
        """
        if not events:
            return
        sb = self._getSelectionBuffer()
        if not sb._initialized:
            return

        samples, evs, inb = [], [], []
        for e in events.values():
            x, y = e.getPickPoint()
            x, y = int(x), int(y)
            samples.append((x, y))
            evs.append(e)
            inb.append(0 <= x < sb.width and 0 <= y < sb.height)
        n = len(samples)

        id_pid, id_cap = self._acquirePBO(n * 4)
        dz_pid, dz_cap = self._acquirePBO(n * 4)

        prev = int(glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING))
        glBindFramebuffer(GL_READ_FRAMEBUFFER, sb.fbo)
        try:
            glReadBuffer(GL_COLOR_ATTACHMENT1)
            glBindBuffer(GL_PIXEL_PACK_BUFFER, id_pid)
            for i, (x, y) in enumerate(samples):
                if inb[i]:
                    glReadPixels(x, y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE,
                                 ctypes.c_void_p(i * 4))
            glBindBuffer(GL_PIXEL_PACK_BUFFER, dz_pid)
            for i, (x, y) in enumerate(samples):
                if inb[i]:
                    glReadPixels(x, y, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT,
                                 ctypes.c_void_p(i * 4))
            glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)
        finally:
            glBindFramebuffer(GL_READ_FRAMEBUFFER, prev)

        fence = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0)
        if self._async_batches is None:
            self._async_batches = []
        self._async_batches.append({
            'events': evs, 'samples': samples, 'inb': inb, 'n': n,
            'id_pid': id_pid, 'id_cap': id_cap,
            'dz_pid': dz_pid, 'dz_cap': dz_cap,
            'fence': fence, 'id_map': id_map,
            'matrix': self.matrix, 'projection': self.projection,
            'viewport': self.viewport,
        })
        # Keep the in-flight queue bounded: if the GPU falls behind, block on the
        # oldest so events still get delivered and PBOs are recycled.
        while len(self._async_batches) > self._ASYNC_MAX_INFLIGHT:
            self._resolveBatch(mode, self._async_batches.pop(0), block=True)

    def drainAsyncPicks(self, mode: Any) -> None:
        """Dispatch any batches whose fence has signalled (non-blocking)."""
        batches = self._async_batches
        if not batches:
            return
        remaining = []
        for b in batches:
            status = glClientWaitSync(b['fence'], GL_SYNC_FLUSH_COMMANDS_BIT, 0)
            if status in (GL_ALREADY_SIGNALED, GL_CONDITION_SATISFIED):
                self._resolveBatch(mode, b, block=False)
            else:
                remaining.append(b)
        self._async_batches = remaining

    def _readPBO(self, pid: int, n: int) -> np.ndarray:
        """Copy n*4 bytes out of a Pixel Pack Buffer as a uint8 array."""
        glBindBuffer(GL_PIXEL_PACK_BUFFER, pid)
        ptr = glMapBufferRange(GL_PIXEL_PACK_BUFFER, 0, n * 4, GL_MAP_READ_BIT)
        try:
            raw = (ctypes.c_ubyte * (n * 4)).from_address(int(ptr))
            data = frombuffer(bytes(raw), dtype='B').copy()
        finally:
            glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
            glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)
        return data

    def _resolveBatch(self, mode: Any, b: Dict, block: bool = False) -> None:
        """Read a batch's PBOs back to the CPU and dispatch its pick events."""
        if block:
            # Honour the wait status: on TIMEOUT_EXPIRED / WAIT_FAILED
            # the GPU write hasn't landed, so reading the PBO would dispatch stale
            # (or zero) ids as if the pick completed. Skip the batch instead.
            status = glClientWaitSync(b['fence'], GL_SYNC_FLUSH_COMMANDS_BIT, 1_000_000_000)
            if status not in (GL_ALREADY_SIGNALED, GL_CONDITION_SATISFIED):
                log.warning(
                    "pick fence did not signal (status=%s); dropping batch of %d "
                    "event(s) rather than dispatch stale ids", status, b['n'])
                return
        n = b['n']
        # Read the PBOs by mapping them; glGetBufferSubData returns zeroes with
        # this PyOpenGL build, whereas glMapBufferRange gives the real bytes.
        ids = self._readPBO(b['id_pid'], n).view('<u4')
        dz = self._readPBO(b['dz_pid'], n).view('<f4')

        id_map = b['id_map'] or {}
        for i, event in enumerate(b['events']):
            if b['inb'][i]:
                obj_id = int(ids[i])       # RGBA8 little-endian == 32-bit id
                depth = float(dz[i])
            else:
                obj_id, depth = 0, 1.0
            path = id_map.get(obj_id, [])
            x, y = b['samples'][i]
            self._dispatchPickEvent(
                mode, event, [path] if path else [[]], x, y, depth,
                b['matrix'], b['projection'], b['viewport'])

        glDeleteSync(b['fence'])
        self._releasePBO(b['id_pid'], b['id_cap'])
        self._releasePBO(b['dz_pid'], b['dz_cap'])
