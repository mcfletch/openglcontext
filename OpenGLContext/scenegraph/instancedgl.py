"""Small GL helpers shared by the terrain and vegetation scenegraph nodes.

These nodes drive raw core-profile GL inside their ``render()`` (VAOs, instanced
draws, array textures) rather than going through the fixed-function/VRML97 shader
path, so they need a couple of utilities the rest of the scenegraph doesn't:
compile a standalone program from files under :data:`SHADER_DIR`, and upload a
2D texture. Kept here so ``terrain`` and ``vegetation`` share one copy.
"""
import os
import ctypes
import logging
from collections.abc import Iterable
from typing import Any

import numpy as np
from PIL import Image
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BLEND, GL_CLAMP_TO_EDGE, GL_CULL_FACE, GL_CULL_FACE_MODE,
    GL_DEPTH_TEST, GL_DEPTH_WRITEMASK, GL_DYNAMIC_DRAW, GL_FALSE, GL_FLOAT,
    GL_FRAGMENT_SHADER, GL_FRONT_FACE, GL_LINEAR, GL_LINEAR_MIPMAP_LINEAR, GL_REPEAT,
    GL_RGBA, GL_RGBA8, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_TRUE, GL_UNSIGNED_BYTE, GL_VERTEX_SHADER,
    glBindBuffer, glBindTexture, glBufferData, glBufferSubData, glCullFace,
    glDeleteBuffers, glDeleteProgram, glDeleteTextures, glDeleteVertexArrays,
    glDepthMask, glDisable, glEnable, glEnableVertexAttribArray, glFrontFace,
    glGenBuffers, glGenTextures, glGenerateMipmap, glGetBooleanv, glGetIntegerv,
    glIsEnabled, glTexImage2D, glTexParameteri, glVertexAttribDivisor,
    glVertexAttribPointer,
)
from OpenGL.GL.shaders import compileProgram, compileShader

log = logging.getLogger(__name__)

# OpenGLContext/shaders (this file lives in OpenGLContext/scenegraph/).
SHADER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'shaders')


def load_program(vert_name: str, frag_name: str) -> int:
    """Compile a program from two shader files under :data:`SHADER_DIR`."""
    with open(os.path.join(SHADER_DIR, vert_name)) as f:
        vs = f.read()
    with open(os.path.join(SHADER_DIR, frag_name)) as f:
        fs = f.read()
    return compileProgram(compileShader(vs, GL_VERTEX_SHADER),
                          compileShader(fs, GL_FRAGMENT_SHADER))


def texture_rgba(source: Any, clamp: bool = True, mipmap: bool = True) -> int:
    """Upload an RGBA texture; mipmapped + trilinear by default.

    ``source`` is a filesystem path or an already-decoded ``PIL.Image``. Accepting
    an in-memory image lets a texture embedded in an asset (e.g. a GLB's baked-in
    PNG) upload without first writing a file beside the asset -- a write that fails
    on a read-only install."""
    im = (source if isinstance(source, Image.Image) else Image.open(source)).convert("RGBA")
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tid)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, im.width, im.height, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, np.asarray(im))
    wrap = GL_CLAMP_TO_EDGE if clamp else GL_REPEAT
    if mipmap:
        glGenerateMipmap(GL_TEXTURE_2D)
        minf = GL_LINEAR_MIPMAP_LINEAR
    else:
        minf = GL_LINEAR
    for p, v in [(GL_TEXTURE_MIN_FILTER, minf), (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
                 (GL_TEXTURE_WRAP_S, wrap), (GL_TEXTURE_WRAP_T, wrap)]:
        glTexParameteri(GL_TEXTURE_2D, p, v)
    return tid


def setup_instance_attribs(loc_xform: int, loc_scale: int) -> None:
    """Configure the per-instance transform attributes on the currently bound VAO.

    The instanced veg nodes all pack instance data identically: a ``vec4`` transform
    (x, y, z, yaw) at offset 0 and a ``float`` height scale at offset 16, stride 20,
    advancing once per instance (divisor 1). Reads from the buffer currently bound to
    ``GL_ARRAY_BUFFER``; the caller binds its instance buffer first."""
    glVertexAttribPointer(loc_xform, 4, GL_FLOAT, GL_FALSE, 20, ctypes.c_void_p(0))
    glEnableVertexAttribArray(loc_xform)
    glVertexAttribDivisor(loc_xform, 1)
    glVertexAttribPointer(loc_scale, 1, GL_FLOAT, GL_FALSE, 20, ctypes.c_void_p(16))
    glEnableVertexAttribArray(loc_scale)
    glVertexAttribDivisor(loc_scale, 1)


class InstanceBuffer:
    """A GL array buffer that restreams per-instance data without per-frame reallocation.

    A camera-following field restreams its instances every frame. Reallocating the
    store (``glBufferData``) each time churns driver memory; instead the buffer is
    grown only when a frame's instance count exceeds the current capacity, and
    otherwise the live prefix is rewritten in place with ``glBufferSubData``.
    :attr:`id` is stable so it can be wired into a VAO once at setup, and
    :attr:`count` is the live instance count to pass to the instanced draw."""
    def __init__(self) -> None:
        self.id = int(glGenBuffers(1))
        self.capacity = 0   # allocated bytes
        self.count = 0      # live instances

    def upload(self, rows: Any) -> None:
        """Stream ``rows`` (an (N, k) float32 instance array, possibly empty)."""
        rows = np.ascontiguousarray(rows, np.float32)
        self.count = len(rows)
        glBindBuffer(GL_ARRAY_BUFFER, self.id)
        if rows.nbytes > self.capacity:
            glBufferData(GL_ARRAY_BUFFER, rows.nbytes, rows, GL_DYNAMIC_DRAW)
            self.capacity = rows.nbytes
        elif rows.nbytes:
            glBufferSubData(GL_ARRAY_BUFFER, 0, rows.nbytes, rows)

    def delete(self) -> None:
        delete_gl(buffers=[self.id])


def ensure_gl(node: Any) -> bool:
    """Lazily run ``node._init_gl()``, disabling the node on a GL/shader failure.

    Returns True when GL is ready to draw. A compile/link/driver failure must not
    crash the frame loop -- the node sets ``_disabled`` (logged once) and its
    ``render`` becomes a no-op, so the layer just goes missing on hardware that
    cannot support it instead of taking down the whole app."""
    if getattr(node, '_disabled', False):
        return False
    if node._gl is None:
        try:
            node._init_gl()
        except Exception as err:
            node._disabled = True
            log.warning("%s disabled: GL init failed: %s", type(node).__name__, err)
            return False
    return True


def save_draw_state() -> tuple[bool, int, int, bool, bool, bool]:
    """Snapshot the cull/depth/blend GL state the instanced veg/terrain nodes mutate.

    A node draws with its own setup and restores this snapshot afterwards, so it
    composes with the PBR pass's cached draw state
    (``pbrmesh._apply_draw_state``/``reset_draw_state``) instead of invalidating
    that cache by hand. Cull *mode* and *front face* are captured too: the terrain
    sets them explicitly, and leaving them changed would desync the PBR cache."""
    mask = glGetBooleanv(GL_DEPTH_WRITEMASK)
    return (
        bool(glIsEnabled(GL_CULL_FACE)),
        int(glGetIntegerv(GL_CULL_FACE_MODE)),
        int(glGetIntegerv(GL_FRONT_FACE)),
        bool(glIsEnabled(GL_DEPTH_TEST)),
        bool(mask[0]) if hasattr(mask, '__len__') else bool(mask),
        bool(glIsEnabled(GL_BLEND)),
    )


def restore_draw_state(state: tuple[bool, int, int, bool, bool, bool]) -> None:
    """Restore a :func:`save_draw_state` snapshot."""
    cull, cull_mode, front_face, depth, depth_mask, blend = state
    (glEnable if cull else glDisable)(GL_CULL_FACE)
    glCullFace(cull_mode)
    glFrontFace(front_face)
    (glEnable if depth else glDisable)(GL_DEPTH_TEST)
    glDepthMask(GL_TRUE if depth_mask else GL_FALSE)
    (glEnable if blend else glDisable)(GL_BLEND)


def delete_gl(vaos: Iterable[int] = (), buffers: Iterable[int] = (),
              textures: Iterable[int] = (), programs: Iterable[int] = ()) -> None:
    """Delete GL objects, tolerating already-freed handles / no current context."""
    for vao in vaos:
        try:
            glDeleteVertexArrays(1, [vao])
        except Exception:
            pass
    for buf in buffers:
        try:
            glDeleteBuffers(1, [buf])
        except Exception:
            pass
    for tex in textures:
        try:
            glDeleteTextures([tex])
        except Exception:
            pass
    for prog in programs:
        try:
            glDeleteProgram(prog)
        except Exception:
            pass
