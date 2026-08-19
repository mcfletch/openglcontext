"""Where a skinned figure's joint matrices live on the GPU.

Linear-blend skinning is the same short sum for every vertex of a body --
four joint matrices, weighted -- and doing it on the CPU means both the sum
*and* a re-upload of every deformed position, normal and tangent, every frame,
for every figure. Done in the vertex shader instead, the only thing that
crosses the bus per frame is the **joint palette**: one matrix per joint, a few
kilobytes for a crowd rather than a few megabytes.

:class:`JointPalette` is that palette, and it is **one buffer for the whole
context**, not one per figure. Every skinned mesh reserves a range of it and
writes its own matrices into that range; the shader reads the range starting at
the ``jointBase`` uniform it is given. One buffer because a crowd wants one
bind and one draw loop -- and because a buffer a compute shader fills for every
figure at once is the same buffer, reserved the same way.

The buffer is read by the vertex shader as a **texture buffer** (``samplerBuffer``,
GL 3.1), which puts no ceiling on how many joints a scene may hold, unlike a
uniform block. Each matrix is four RGBA32F texels, one per row of the row-vector
matrix the rest of the renderer uses, so ``mat4(r0, r1, r2, r3)`` in GLSL --
whose constructor takes columns -- yields the transpose, and multiplying a
column vector by it is the row-vector transform.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
from OpenGL.GL import (
    GL_DYNAMIC_DRAW, GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS,
    GL_RGBA32F, GL_TEXTURE0, GL_TEXTURE_BUFFER,
    glActiveTexture, glBindBuffer, glBindTexture, glBufferData, glBufferSubData,
    glDeleteBuffers, glDeleteTextures, glGenBuffers, glGenTextures,
    glGetIntegerv, glTexBuffer,
)

__all__ = ['JointPalette', 'MATRIX_FLOATS', 'SKIN_PALETTE_UNIT',
           'gpu_skinning_is_enabled', 'palette_for', 'palette_supported']

#: Floats per joint matrix in the palette (four RGBA32F texels).
MATRIX_FLOATS = 16

#: Texture unit the vertex shader reads the palette from. Above every fragment
#: sampler the PBR program assigns, so the two never contend for a unit; a
#: driver whose combined budget does not reach it keeps skinning on the CPU.
SKIN_PALETTE_UNIT = 30

#: Joints the palette is made to hold before it has to grow. A crowd of a
#: hundred fifty-seven-bone figures fits without a reallocation.
INITIAL_JOINTS = 8192

_PALETTE_ATTR = '_oglc_joint_palette'


def gpu_skinning_is_enabled(source: Any = None) -> bool:
    """Whether skinning runs in the vertex shader (``OPENGLCONTEXT_GPU_SKINNING``).

    On by default. Off puts the deform back on the CPU, which is the reference
    the shader is measured against and the path a driver without the sampler
    budget for a palette falls back to; a capture that wants byte-stable output
    from either can pin it.
    """
    from OpenGLContext import renderoptions
    default = renderoptions.env_flag('OPENGLCONTEXT_GPU_SKINNING', True)
    if source is None:
        return default
    return renderoptions.flag(source, 'gpuSkinning', default)


def palette_supported() -> bool:
    """Whether this driver has a texture unit to spare for the palette."""
    try:
        combined = int(glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS))
    except Exception:       # pragma: no cover - needs a driver that refuses the query
        return False
    return combined > SKIN_PALETTE_UNIT


class JointPalette:
    """One growable GPU buffer of joint matrices, shared by every skinned mesh.

    A mesh calls :meth:`reserve` once for its joint count and keeps the base it
    is given; :meth:`write` puts that mesh's matrices at the base each frame,
    and :meth:`bind` makes the whole buffer readable by the shader. Ranges are
    handed out in order and never moved, so a base stays valid for the life of
    the context.
    """

    def __init__(self, capacity: int = INITIAL_JOINTS) -> None:
        self.capacity = int(max(1, capacity))
        self.used = 0
        self._reserved: Dict[int, int] = {}
        self.buffer = int(glGenBuffers(1))
        self.texture = int(glGenTextures(1))
        glBindBuffer(GL_TEXTURE_BUFFER, self.buffer)
        glBufferData(GL_TEXTURE_BUFFER, self.capacity * MATRIX_FLOATS * 4,
                     None, GL_DYNAMIC_DRAW)
        glBindBuffer(GL_TEXTURE_BUFFER, 0)
        self._attach()

    # -- ranges ------------------------------------------------------------
    def reserve(self, owner: Any, joints: int) -> int:
        """The first joint index of a range of ``joints``, made on first ask.

        Keyed by the id of the owner, so a mesh asking again gets the range it
        already has rather than another one.
        """
        key = id(owner)
        found = self._reserved.get(key)
        if found is not None:
            return found
        base = self.used
        self.used += int(joints)
        if self.used > self.capacity:
            self._grow(self.used)
        self._reserved[key] = base
        return base

    def reserved_base(self, owner: Any) -> Optional[int]:
        """The range this owner already holds, or None if it holds none."""
        return self._reserved.get(id(owner))

    def _grow(self, wanted: int) -> None:
        """Make the buffer big enough for ``wanted`` joints, keeping what is in it.

        Doubling, so a scene that streams figures in reallocates a handful of
        times rather than once per figure. What was written before is not
        copied across: every range is rewritten by its owner each frame, so a
        frame's worth of matrices is all that is ever at stake.
        """
        capacity = self.capacity
        while capacity < wanted:
            capacity *= 2
        self.capacity = capacity
        glBindBuffer(GL_TEXTURE_BUFFER, self.buffer)
        glBufferData(GL_TEXTURE_BUFFER, capacity * MATRIX_FLOATS * 4,
                     None, GL_DYNAMIC_DRAW)
        glBindBuffer(GL_TEXTURE_BUFFER, 0)
        # A texture buffer takes its extent from the buffer object as it stands,
        # so a reallocated buffer has to be attached again for the shader to see
        # past the old end of it.
        self._attach()

    # -- the frame ---------------------------------------------------------
    def write(self, base: int, matrices: np.ndarray) -> None:
        """Put a ``(J, 4, 4)`` stack of row-vector matrices at ``base``."""
        data = np.ascontiguousarray(matrices, dtype=np.float32)
        glBindBuffer(GL_TEXTURE_BUFFER, self.buffer)
        glBufferSubData(GL_TEXTURE_BUFFER, base * MATRIX_FLOATS * 4,
                        data.nbytes, data)
        glBindBuffer(GL_TEXTURE_BUFFER, 0)

    def write_runs(self, entries: Any) -> int:
        """Write many ``(base, matrices)`` pairs, joining the ones that adjoin.

        A crowd's figures take their ranges in the order they were first drawn,
        so a build's figures hold one long run between them and the whole crowd
        is a single upload rather than one per body. Returns how many uploads it
        came to.
        """
        pending = sorted(entries, key=lambda item: item[0])
        if not pending:
            return 0
        uploads = 0
        glBindBuffer(GL_TEXTURE_BUFFER, self.buffer)
        try:
            run: list = []
            start = expected = pending[0][0]
            for base, matrices in pending:
                if base != expected and run:
                    self._write_run(start, run)
                    uploads += 1
                    run, start = [], base
                run.append(np.ascontiguousarray(matrices, dtype=np.float32))
                if not len(run) - 1:
                    start = base
                expected = base + len(matrices)
            if run:
                self._write_run(start, run)
                uploads += 1
        finally:
            glBindBuffer(GL_TEXTURE_BUFFER, 0)
        return uploads

    def _write_run(self, base: int, run: list) -> None:
        data = run[0] if len(run) == 1 else np.concatenate(run)
        glBufferSubData(GL_TEXTURE_BUFFER, base * MATRIX_FLOATS * 4,
                        data.nbytes, data)

    def _attach(self, unit: int = SKIN_PALETTE_UNIT) -> None:
        """Point the palette texture at the buffer and leave it bound to its unit.

        Bound once and left there rather than re-bound per draw: the unit is
        above every one the material, shadow and IBL samplers use, so nothing
        else in a frame disturbs it, and a crowd of skinned meshes then costs
        no texture binds at all.
        """
        glActiveTexture(GL_TEXTURE0 + unit)
        glBindTexture(GL_TEXTURE_BUFFER, self.texture)
        glTexBuffer(GL_TEXTURE_BUFFER, GL_RGBA32F, self.buffer)
        glActiveTexture(GL_TEXTURE0)

    def release(self) -> None:
        """Delete the buffer and its texture. Needs the owning context current."""
        for name, deleter in (('texture', glDeleteTextures),
                              ('buffer', glDeleteBuffers)):
            handle = getattr(self, name, None)
            if handle:
                try:
                    deleter(1, [handle])
                except Exception:
                    pass
                setattr(self, name, 0)


def palette_for(mode: Any) -> Optional[JointPalette]:
    """The context's joint palette, made on first ask; None where it cannot be.

    Hung off the context rather than the render pass, because the ranges a mesh
    holds have to outlive any one frame and any one pass.
    """
    target = getattr(mode, 'context', None) or mode
    found = getattr(target, _PALETTE_ATTR, None)
    if found is not None:
        return found if found is not False else None
    if not palette_supported():
        try:
            setattr(target, _PALETTE_ATTR, False)
        except Exception:
            pass
        return None
    palette = JointPalette()
    try:
        setattr(target, _PALETTE_ATTR, palette)
    except Exception:       # pragma: no cover - a mode that refuses attributes
        pass
    return palette
