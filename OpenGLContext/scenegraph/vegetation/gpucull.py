"""Instanced rows culled on the GPU, drawn from an indirect command.

:class:`~OpenGLContext.scenegraph.vegetation.viewcull.CulledRows` cuts a set
into clusters and uploads the rows of the clusters in view, from the processor,
every time the view moves far enough to need others. :class:`GPUCulledRows` does
the same job where the driver has compute shaders: the whole set is uploaded
once, when it is staged, and each draw runs a compute pass over it that keeps
the instances whose box reaches into the view and the disc. The pass packs them
at the front of the buffer the draw reads its per-instance attributes from and
counts them in an indirect draw command, so nothing is read back and the
processor does no work per instance.

Both cullers answer :meth:`show`, :meth:`draw_arrays` and :meth:`draw_elements`;
:func:`rows_culler` makes the one the driver can run. ``OPENGLCONTEXT_GPU_CULL=0``
keeps the processor's.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional, Protocol

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BUFFER_UPDATE_BARRIER_BIT, GL_COMMAND_BARRIER_BIT, GL_COMPUTE_SHADER,
    GL_CURRENT_PROGRAM, GL_DRAW_INDIRECT_BUFFER, GL_DYNAMIC_COPY, GL_EXTENSIONS,
    GL_MAJOR_VERSION, GL_NUM_EXTENSIONS, GL_SHADER_STORAGE_BUFFER, GL_STATIC_DRAW, GL_TRIANGLES,
    GL_UNSIGNED_INT, GL_VERTEX_ATTRIB_ARRAY_BARRIER_BIT, glBindBuffer, glBindBufferBase,
    glBufferData, glBufferSubData, glDeleteBuffers, glDeleteProgram, glDispatchCompute,
    glDrawArraysIndirect, glDrawElementsIndirect, glGenBuffers, glGetBufferSubData,
    glGetIntegerv, glGetStringi, glGetUniformLocation, glMemoryBarrier, glUniform1i,
    glUniform1ui, glUniform3f, glUniform4fv, glUseProgram,
)
from OpenGL.GL import shaders as GL_shaders

from OpenGLContext import contextresources, renderoptions
from OpenGLContext.scenegraph.instancedgl import INSTANCE_FLOATS, InstanceBuffer
from OpenGLContext.scenegraph.vegetation.viewcull import CulledRows, Disc

log = logging.getLogger(__name__)

__all__ = ['GPUCulledRows', 'RowCuller', 'gpu_cull_is_available', 'gpu_cull_is_enabled', 'rows_culler',
           'reset_capability_cache']

#: Threads per work group; matches ``local_size_x`` in ``veg_cull.comp``.
GROUP = 64
#: The most frustum planes the shader tests; a frustum has six.
MAX_PLANES = 8
#: Bytes of an indirect draw command: five 32-bit words, of which an arrays draw
#: reads four.
COMMAND_BYTES = 20
#: How much larger than the set the buffer it is drawn from is made, so that a set
#: that grows by a scatter does not make a new store every time.
HEADROOM = 1.5

class RowCuller(Protocol):
    """What a layer asks of the culler that streams or counts its instances."""

    enabled: bool
    reach: float

    def stage(self, rows: np.ndarray) -> None: ...

    def show(self, mode: Any, disc: Optional[Disc] = None) -> int: ...

    def draw_arrays(self, copies: int = 1) -> None: ...

    def draw_elements(self, copies: int = 1) -> None: ...

    def release(self) -> None: ...


_UNIFORMS = ('uPlanes', 'uPlaneCount', 'uDisc', 'uExtent', 'uCount', 'uCopies')
_AVAILABLE: Optional[bool] = None
#: Each context's culling program and its uniforms' locations.
_PROGRAMS: dict[Any, tuple[int, dict[str, int]]] = {}


def gpu_cull_is_enabled() -> bool:
    """Whether the GPU is to cull where it can (``OPENGLCONTEXT_GPU_CULL``, on by default)."""
    return renderoptions.env_flag_once('OPENGLCONTEXT_GPU_CULL', True)


def gpu_cull_is_available() -> bool:
    """Whether culling is on and this context can run the compute pass and an indirect draw.

    Compute shaders and shader storage buffers are GL 4.3, and a driver may offer them to
    an older context as extensions; indirect draws are GL 4.0. Asked once and kept.
    """
    if not gpu_cull_is_enabled():
        return False
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            names = {glGetStringi(GL_EXTENSIONS, i).decode()
                     for i in range(int(glGetIntegerv(GL_NUM_EXTENSIONS)))}
            _AVAILABLE = ('GL_ARB_compute_shader' in names
                          and 'GL_ARB_shader_storage_buffer_object' in names
                          and (int(glGetIntegerv(GL_MAJOR_VERSION)) >= 4
                               or 'GL_ARB_draw_indirect' in names))
        except Exception as err:        # pragma: no cover - needs a driver that refuses
            log.info('compute-shader detection failed (%s); vegetation is culled on the CPU',
                     err)
            _AVAILABLE = False
    return _AVAILABLE


def reset_capability_cache() -> None:
    """Forget the detected capability, so the next ask reaches the driver."""
    global _AVAILABLE
    _AVAILABLE = None


def _compile() -> int:
    from OpenGLContext.passes.shadersource import SHADER_DIR
    with open(os.path.join(SHADER_DIR, 'veg_cull.comp')) as source:
        text = source.read()
    return int(GL_shaders.compileProgram(GL_shaders.compileShader(text, GL_COMPUTE_SHADER),
                                         validate=False))


def _program() -> tuple[int, dict[str, int]]:
    """This context's culling program and its uniforms, made on first use."""
    key = contextresources.context_key()
    held = _PROGRAMS.get(key)
    if held is None:
        program = _compile()
        held = (program, {name: glGetUniformLocation(program, name) for name in _UNIFORMS})
        _PROGRAMS[key] = held
    return held


def _forget_programs() -> None:
    """Drop the program of the context going away, deleting it where that context is current."""
    held = _PROGRAMS.pop(contextresources.context_key(), None)
    if held is not None and contextresources.deletable():
        glDeleteProgram(held[0])


contextresources.on_context_lost(_forget_programs)


class GPUCulledRows:
    """A staged set of instance rows, kept on the GPU and culled there for each view.

    Takes what :class:`~OpenGLContext.scenegraph.vegetation.viewcull.CulledRows` does: the
    ``buffer`` the draw reads its instance attributes from, how far an instance reaches
    sideways, above and below its base point (``reach``, ``rise`` and ``drop``, each for a
    scale of one), and how many ``triangles`` one instance draws. Each instance is tested
    by its own box rather than a cluster's.

    :meth:`stage` takes the set, and :meth:`show` runs the pass for the view of ``mode`` and
    the ``disc``. :meth:`draw_arrays` and :meth:`draw_elements` then issue the draw from the
    command the pass counted into, with the node's program and vertex array bound. A pass
    with no frustum, a shared draw of several views (which sends each instance to each view)
    and ``enabled`` False send every instance, within the disc if there is one and
    ``enabled`` is True.
    """

    def __init__(self, buffer: InstanceBuffer, reach: float, rise: float,
                 drop: float = 0.0, enabled: bool = True, triangles: int = 1) -> None:
        self.buffer = buffer
        self.reach = float(reach)
        self.rise = float(rise)
        self.drop = float(drop)
        self.enabled = bool(enabled)
        self.triangles = int(triangles)
        self._rows = np.zeros((0, INSTANCE_FLOATS), np.float32)
        self._dirty = False
        self._count = 0
        self._copies = 1
        self._source = 0
        self._command = 0
        self._fresh = np.array([3 * self.triangles, 0, 0, 0, 0], np.uint32)

    # -- the set ---------------------------------------------------------------
    def stage(self, rows: np.ndarray) -> None:
        """Take a new set; the next :meth:`show` uploads it."""
        self._rows = rows
        self._dirty = True

    def _upload(self) -> None:
        """Put the staged set on the GPU, with room in the draw's buffer for all of it."""
        rows = np.ascontiguousarray(self._rows, np.float32).reshape(-1, INSTANCE_FLOATS)
        self._dirty = False
        self._count = len(rows)
        self.buffer.count = 0
        if not self._source:
            self._source, self._command = (int(name) for name in glGenBuffers(2))
            glBindBuffer(GL_SHADER_STORAGE_BUFFER, self._command)
            glBufferData(GL_SHADER_STORAGE_BUFFER, COMMAND_BYTES, self._fresh, GL_DYNAMIC_COPY)
        if not self._count:
            return
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self._source)
        glBufferData(GL_SHADER_STORAGE_BUFFER, rows.nbytes, rows, GL_STATIC_DRAW)
        if rows.nbytes > self.buffer.capacity:
            self.buffer.capacity = int(rows.nbytes * HEADROOM)
            glBindBuffer(GL_ARRAY_BUFFER, self.buffer.id)
            glBufferData(GL_ARRAY_BUFFER, self.buffer.capacity, None, GL_DYNAMIC_COPY)

    # -- the pass --------------------------------------------------------------
    def show(self, mode: Any, disc: Optional[Disc] = None) -> int:
        """Cull the set for the view of ``mode``, within ``disc``; the number of rows staged.

        The number kept is the GPU's to count and is not known here: :meth:`visible_count`
        reads it back, which waits for the pass, so a draw does not ask.
        """
        if self._dirty:
            self._upload()
        if not self._count:
            return 0
        self._copies = max(1, int(getattr(mode, 'viewCopies', 0) or 0))
        planes = self._planes(mode) if self.enabled and self._copies == 1 else None
        self._cull(planes, disc if self.enabled else None)
        return self._count

    def _planes(self, mode: Any) -> Optional[np.ndarray]:
        held = getattr(mode, 'frustum', None)
        if held is None:
            return None
        planes = np.asarray(held.planes, np.float32).reshape(-1, 4)[:MAX_PLANES]
        return planes if len(planes) else None

    def _cull(self, planes: Optional[np.ndarray], disc: Optional[Disc]) -> None:
        program, U = _program()
        current = int(glGetIntegerv(GL_CURRENT_PROGRAM))
        glUseProgram(program)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self._command)
        glBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, COMMAND_BYTES, self._fresh)
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 0, self._source)
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 1, self.buffer.id)
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, 2, self._command)
        if planes is None:
            glUniform1i(U['uPlaneCount'], 0)
        else:
            glUniform4fv(U['uPlanes'], len(planes), planes)
            glUniform1i(U['uPlaneCount'], len(planes))
        glUniform3f(U['uDisc'], *(disc if disc is not None else (0.0, 0.0, -1.0)))
        glUniform3f(U['uExtent'], self.reach, self.rise, self.drop)
        glUniform1i(U['uCount'], self._count)
        glUniform1ui(U['uCopies'], self._copies)
        glDispatchCompute((self._count + GROUP - 1) // GROUP, 1, 1)
        glMemoryBarrier(GL_VERTEX_ATTRIB_ARRAY_BARRIER_BIT | GL_COMMAND_BARRIER_BIT)
        glUseProgram(current)

    # -- drawing ---------------------------------------------------------------
    def draw_arrays(self, copies: int = 1) -> None:  # noqa: ARG002 the command holds the copies
        """Draw the instances kept as triangles read in order, from the vertex array bound."""
        glBindBuffer(GL_DRAW_INDIRECT_BUFFER, self._command)
        glDrawArraysIndirect(GL_TRIANGLES, None)
        glBindBuffer(GL_DRAW_INDIRECT_BUFFER, 0)

    def draw_elements(self, copies: int = 1) -> None:  # noqa: ARG002 the command holds the copies
        """Draw the instances kept as indexed triangles, from the vertex array bound."""
        glBindBuffer(GL_DRAW_INDIRECT_BUFFER, self._command)
        glDrawElementsIndirect(GL_TRIANGLES, GL_UNSIGNED_INT, None)
        glBindBuffer(GL_DRAW_INDIRECT_BUFFER, 0)

    # -- reading back, for a test or a debugging aid -----------------------------
    def visible_count(self) -> int:
        """The instance count the draw is issued with: instances kept, times the views each goes to.

        Reads the command back, which waits for the GPU.
        """
        if self._dirty:
            self._upload()
        if not self._command:
            return 0
        glMemoryBarrier(GL_BUFFER_UPDATE_BARRIER_BIT)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self._command)
        data = glGetBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, COMMAND_BYTES)
        return int(np.frombuffer(data, np.uint32)[1])

    def visible_rows(self) -> np.ndarray:
        """The rows kept, in the order the pass packed them. Waits for the GPU."""
        kept = self.visible_count() // self._copies
        if not kept:
            return np.zeros((0, INSTANCE_FLOATS), np.float32)
        glBindBuffer(GL_ARRAY_BUFFER, self.buffer.id)
        data = glGetBufferSubData(GL_ARRAY_BUFFER, 0, kept * INSTANCE_FLOATS * 4)
        return np.frombuffer(data, np.float32).reshape(kept, INSTANCE_FLOATS).copy()

    def release(self) -> None:
        """Delete the buffers this holds. GL thread; the draw's own buffer is its owner's."""
        names = [name for name in (self._source, self._command) if name]
        if names:
            glDeleteBuffers(len(names), np.array(names, dtype=np.uint32))
        self._source = self._command = 0


def rows_culler(buffer: Any, reach: float, rise: float, drop: float = 0.0,
                enabled: bool = True, triangles: int = 1) -> RowCuller:
    """The culler for a layer drawing into ``buffer``: on the GPU where it can, else the processor's.

    A layer with culling turned off (``enabled`` False) is given the processor's, which sends
    it every row without a pass over them. Needs the context the layer draws in current.
    """
    if enabled and gpu_cull_is_available():
        return GPUCulledRows(buffer, reach, rise, drop, enabled, triangles)
    return CulledRows(buffer, reach, rise, drop, enabled, triangles)
