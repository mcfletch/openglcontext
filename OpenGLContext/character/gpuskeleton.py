"""Composing a crowd's skeletons and joint palettes on the GPU.

Once skinning itself runs in the vertex shader, what a figure still costs the
CPU each frame is the arithmetic *behind* the pose: composing a local matrix
per joint, walking those into world space, and turning each skin's joints into
the palette the shader reads. It is the same short calculation for every joint
of every body -- which is the shape of work a GPU is for, and the shape a CPU
is worst at, because on a few dozen rows almost all of what a numpy call costs
is setting the call up.

:class:`GPUSkeleton` moves that half across. Per frame the only thing that
crosses the bus is the **pose** -- translation, rotation and scale per joint,
forty-eight bytes a joint -- and two compute dispatches turn it into palettes
written straight into the buffer the skinning shader already reads. Nothing
comes back: a read-back would cost more than the work saved.

**It is not always available, and never required.** Compute shaders are
``ARB_compute_shader`` (GL 4.3, exposed by many GL 3.3 drivers); where the
driver has neither, :class:`~OpenGLContext.character.crowd.Crowd` does the same
arithmetic in numpy and the two agree to single precision -- which is what the
palette is stored in either way. The CPU path stays the reference, and the test
for this one is that it matches it.

Matrices keep the renderer's row-vector convention (``p * M``, ``world = local
* parent``). A GLSL ``mat4`` holds the transpose of such a matrix -- its
columns are the row-vector matrix's rows -- which is both why the shaders
multiply right to left and why a palette entry can be written to the buffer
without rearranging anything.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

log = logging.getLogger(__name__)

__all__ = ['GPUSkeleton', 'compute_is_available', 'compute_skeleton_is_enabled']

#: Where each buffer binds, matching the ``layout(binding = N)`` in the shaders.
POSE_BINDING = 0
HIERARCHY_BINDING = 1
WORLD_BINDING = 2
JOINTS_BINDING = 3
INVERSE_BIND_BINDING = 4
TARGETS_BINDING = 5
MESH_SLOTS_BINDING = 6
PALETTE_BINDING = 7

#: Threads per work group; matches ``local_size_x`` in both shaders.
GROUP = 64

_AVAILABLE: Optional[bool] = None


def compute_skeleton_is_enabled() -> bool:
    """Whether to compose skeletons on the GPU (``OPENGLCONTEXT_GPU_SKELETON``).

    On by default where the driver has compute. Off keeps the numpy path, which
    is the reference the GPU one is measured against.
    """
    from OpenGLContext import renderoptions
    return renderoptions.env_flag('OPENGLCONTEXT_GPU_SKELETON', True)


def compute_is_available() -> bool:
    """Whether this context can run a compute shader, asked once and kept.

    ``ARB_compute_shader`` and ``ARB_shader_storage_buffer_object`` are GL 4.3
    features, and a driver may expose both to a 3.3 context; asking for the
    extensions rather than the version is what lets it.
    """
    global _AVAILABLE
    if _AVAILABLE is not None:
        return _AVAILABLE
    try:
        from OpenGL.GL import (
            GL_EXTENSIONS, GL_NUM_EXTENSIONS, glGetIntegerv, glGetStringi,
        )
        count = int(glGetIntegerv(GL_NUM_EXTENSIONS))
        names = {glGetStringi(GL_EXTENSIONS, i).decode() for i in range(count)}
        _AVAILABLE = ('GL_ARB_compute_shader' in names
                      and 'GL_ARB_shader_storage_buffer_object' in names)
    except Exception as err:      # pragma: no cover - needs a driver that refuses
        log.info('compute-shader detection failed (%s); skeletons stay on the CPU',
                 err)
        _AVAILABLE = False
    return _AVAILABLE


def reset_capability_cache() -> None:
    """Forget the detected capability, so the next ask reaches the driver."""
    global _AVAILABLE
    _AVAILABLE = None


class _Buffer:
    """One shader-storage buffer, grown rather than reallocated per frame."""

    __slots__ = ('name', 'capacity', 'binding')

    def __init__(self, binding: int) -> None:
        from OpenGL.GL import glGenBuffers
        self.name = int(glGenBuffers(1))
        self.capacity = 0
        self.binding = binding

    def reserve(self, size: int) -> None:
        from OpenGL.GL import (
            GL_DYNAMIC_DRAW, GL_SHADER_STORAGE_BUFFER, glBindBuffer, glBufferData,
        )
        if size <= self.capacity:
            return
        self.capacity = max(size, self.capacity * 2)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self.name)
        glBufferData(GL_SHADER_STORAGE_BUFFER, self.capacity, None, GL_DYNAMIC_DRAW)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)

    def write(self, data: np.ndarray) -> None:
        from OpenGL.GL import (
            GL_SHADER_STORAGE_BUFFER, glBindBuffer, glBufferSubData,
        )
        raw = np.ascontiguousarray(data)
        self.reserve(raw.nbytes)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, self.name)
        glBufferSubData(GL_SHADER_STORAGE_BUFFER, 0, raw.nbytes, raw)
        glBindBuffer(GL_SHADER_STORAGE_BUFFER, 0)

    def bind(self) -> None:
        from OpenGL.GL import GL_SHADER_STORAGE_BUFFER, glBindBufferBase
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, self.binding, self.name)

    def release(self) -> None:
        from OpenGL.GL import glDeleteBuffers
        if self.name:
            try:
                glDeleteBuffers(1, [self.name])
            except Exception:
                pass
            self.name = 0


class GPUSkeleton:
    """The skeleton and palette arithmetic of one crowd, run on the GPU.

    Built for one rig layout and reused; :meth:`run` takes a frame's poses and
    the skins to write, and leaves the palettes on the GPU.
    """

    def __init__(self, parents: np.ndarray, joints_per_figure: int) -> None:
        self.joints_per_figure = int(joints_per_figure)
        self._programs: Dict[str, int] = {}
        self._buffers: Dict[str, _Buffer] = {}
        self._skin_signature: Any = None
        self._target_signature: Any = None
        self.ok = self._build(parents)

    # -- setting up --------------------------------------------------------
    def _build(self, parents: np.ndarray) -> bool:
        try:
            self._programs['world'] = _compile('skeleton_world.comp')
            self._programs['palette'] = _compile('skeleton_palette.comp')
            for name, binding in (
                    ('pose', POSE_BINDING), ('hierarchy', HIERARCHY_BINDING),
                    ('world', WORLD_BINDING), ('joints', JOINTS_BINDING),
                    ('inverse_bind', INVERSE_BIND_BINDING),
                    ('targets', TARGETS_BINDING),
                    ('mesh_slots', MESH_SLOTS_BINDING)):
                self._buffers[name] = _Buffer(binding)
            self._buffers['hierarchy'].write(
                np.ascontiguousarray(parents, dtype=np.int32))
        except Exception as err:
            log.warning('GPU skeleton unavailable (%s); staying on the CPU', err)
            self.release()
            return False
        return True

    def describe_skins(self, plans: Sequence[Tuple[np.ndarray, np.ndarray]]) -> None:
        """Say which rig slots each skin's joints sit in, and their inverse binds.

        One call per rig, not per frame: the skins of a build do not change.
        """
        signature = tuple(len(slots) for slots, _bind in plans)
        if signature == self._skin_signature:
            return
        self._skin_signature = signature
        self.skin_offsets: List[int] = []
        slot_runs: List[np.ndarray] = []
        bind_runs: List[np.ndarray] = []
        offset = 0
        for slots, inverse_bind in plans:
            self.skin_offsets.append(offset)
            slot_runs.append(np.ascontiguousarray(slots, dtype=np.int32))
            bind_runs.append(np.ascontiguousarray(inverse_bind, dtype=np.float32))
            offset += len(slots)
        self.skin_counts = [len(s) for s in slot_runs]
        empty_slots = np.zeros(0, dtype=np.int32)
        empty_bind = np.zeros((0, 4, 4), dtype=np.float32)
        self._buffers['joints'].write(
            np.concatenate(slot_runs) if slot_runs else empty_slots)
        self._buffers['inverse_bind'].write(
            np.concatenate(bind_runs) if bind_runs else empty_bind)

    # -- the frame ---------------------------------------------------------
    def run(self, pose: Tuple[np.ndarray, np.ndarray, np.ndarray],
            targets: Sequence[Tuple[int, int, int, int]],
            palette_buffer: int) -> bool:
        """Compose ``pose`` into every named skin's palette. False if it could not.

        ``targets`` is one ``(figure, skin, joints, palette base)`` per palette
        range to write -- a figure has one per skinned mesh -- and
        ``palette_buffer`` is the GL buffer the skinning shader reads.
        """
        if not self.ok or not len(targets):
            return False
        from OpenGL.GL import (
            GL_SHADER_STORAGE_BARRIER_BIT, GL_SHADER_STORAGE_BUFFER,
            glBindBufferBase, glDispatchCompute, glMemoryBarrier, glUseProgram,
        )
        count = len(pose[0])
        joints = self.joints_per_figure
        self._buffers['pose'].write(_pack_pose(pose))
        self._buffers['world'].reserve(count * joints * 64)
        for name in ('pose', 'hierarchy', 'world'):
            self._buffers[name].bind()
        glUseProgram(self._programs['world'])
        _set_int(self._programs['world'], 'jointsPerFigure', joints)
        _set_int(self._programs['world'], 'figures', count)
        glDispatchCompute((count * joints + GROUP - 1) // GROUP, 1, 1)
        glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT)

        table, mesh_slots, widest = self._pack_targets(targets)
        self._buffers['targets'].write(table)
        self._buffers['mesh_slots'].write(mesh_slots)
        for name in ('world', 'joints', 'inverse_bind', 'targets', 'mesh_slots'):
            self._buffers[name].bind()
        glBindBufferBase(GL_SHADER_STORAGE_BUFFER, PALETTE_BINDING, palette_buffer)
        glUseProgram(self._programs['palette'])
        _set_int(self._programs['palette'], 'jointsPerFigure', joints)
        _set_int(self._programs['palette'], 'targetCount', len(targets))
        _set_int(self._programs['palette'], 'jointsPerTarget', widest)
        total = len(targets) * widest
        glDispatchCompute((total + GROUP - 1) // GROUP, 1, 1)
        glMemoryBarrier(GL_SHADER_STORAGE_BARRIER_BIT)
        glUseProgram(0)
        return True

    def _pack_targets(self, targets: Sequence[Tuple[int, int, int, int]]
                      ) -> Tuple[np.ndarray, np.ndarray, int]:
        table = np.empty((len(targets), 4), dtype=np.int32)
        mesh_slots = np.empty(len(targets), dtype=np.int32)
        widest = 1
        for row, (figure, skin, mesh_slot, base) in enumerate(targets):
            table[row] = (figure, self.skin_offsets[skin],
                          self.skin_counts[skin], base)
            mesh_slots[row] = mesh_slot
            widest = max(widest, self.skin_counts[skin])
        return table, mesh_slots, widest

    def release(self) -> None:
        """Delete the programs and buffers. Needs the owning context current."""
        from OpenGL.GL import glDeleteProgram
        for program in self._programs.values():
            try:
                glDeleteProgram(program)
            except Exception:
                pass
        self._programs = {}
        for buffer in self._buffers.values():
            buffer.release()
        self._buffers = {}
        self.ok = False


def _pack_pose(pose: Tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    """``(F, N, 3, 4)`` float32: translation, rotation and scale per joint."""
    translation, rotation, scale = pose
    count, joints = translation.shape[0], translation.shape[1]
    packed = np.zeros((count, joints, 3, 4), dtype=np.float32)
    packed[:, :, 0, :3] = translation
    packed[:, :, 1, :] = rotation
    packed[:, :, 2, :3] = scale
    return packed


def _compile(name: str) -> int:
    """Compile and link one compute shader from the shader directory."""
    from OpenGL.GL import GL_COMPUTE_SHADER
    from OpenGL.GL import shaders as GL_shaders
    from OpenGLContext.passes.shadersource import SHADER_DIR
    with open(os.path.join(SHADER_DIR, name)) as source:
        text = source.read()
    shader = GL_shaders.compileShader(text, GL_COMPUTE_SHADER)
    return int(GL_shaders.compileProgram(shader, validate=False))


def _set_int(program: int, name: str, value: int) -> None:
    from OpenGL.GL import glGetUniformLocation, glUniform1i
    location = glGetUniformLocation(program, name)
    if location != -1:
        glUniform1i(location, int(value))
