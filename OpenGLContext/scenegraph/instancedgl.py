"""Small GL helpers shared by the terrain and vegetation scenegraph nodes.

These nodes drive raw core-profile GL inside their ``render()`` (VAOs, instanced
draws, array textures) rather than going through the fixed-function/VRML97 shader
path, so they need a couple of utilities the rest of the scenegraph doesn't:
compile a standalone program from files under :data:`SHADER_DIR`, upload a
2D texture, and draw with the program in a shared draw of several views
(:class:`ViewPrograms`, :func:`view_copies`). Kept here so ``terrain`` and
``vegetation`` share one copy.
"""
import os
import ctypes
import logging
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import numpy as np
from PIL import Image
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_CLAMP_TO_EDGE, GL_CURRENT_PROGRAM, GL_DYNAMIC_DRAW, GL_FALSE, GL_FLOAT,
    GL_FRAGMENT_SHADER, GL_LINEAR, GL_LINEAR_MIPMAP_LINEAR, GL_REPEAT,
    GL_RGBA, GL_RGBA8, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_SRGB8_ALPHA8, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_UNSIGNED_BYTE,
    GL_VERTEX_SHADER,
    glBindBuffer, glBindTexture, glBufferData, glBufferSubData,
    glDeleteBuffers, glDeleteProgram, glDeleteTextures, glDeleteVertexArrays,
    glEnableVertexAttribArray, glGenBuffers, glGenTextures,
    glGenerateMipmap, glGetIntegerv, glGetUniformLocation, glTexImage2D, glTexParameteri,
    glUniform1i, glUniform1ui, glUniform4iv, glUseProgram,
    glVertexAttribDivisor, glVertexAttribPointer,
)
from OpenGL.GL.shaders import compileProgram, compileShader

log = logging.getLogger(__name__)

# OpenGLContext/shaders (this file lives in OpenGLContext/scenegraph/).
SHADER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'shaders')


def load_program(vert_name: str, frag_name: str) -> int:
    """Compile a program from two shader files under :data:`SHADER_DIR`.

    ``validate=False`` suppresses ``compileProgram``'s link-time
    ``glValidateProgram``. Validation reports whether the program can run against
    the *current* GL state, and every sampler uniform reads unit 0 until a draw
    assigns it: a program that mixes sampler types -- the terrain's
    ``sampler2DArray`` layers alongside its ``sampler2D`` control and shadow maps
    -- then trips "active samplers with a different type refer to the same texture
    image unit" and the whole node disables itself. The real units are set per
    draw with ``glUniform1i``, so validation only means anything right before a
    draw, not at link; a genuine link failure is still raised on ``GL_LINK_STATUS``.
    """
    from OpenGLContext.passes.shadersource import preprocess_shader
    return int(compileProgram(
        compileShader(preprocess_shader(vert_name), GL_VERTEX_SHADER),
        compileShader(preprocess_shader(frag_name), GL_FRAGMENT_SHADER),
        validate=False))


#: A program and its uniforms' locations, by name.
Program = Tuple[int, Dict[str, int]]


class ViewPrograms:
    """A node's own program, and the same program compiled for shared draws.

    A pass draws a shape once for several views by compiling the program for
    that many views (:func:`OpenGLContext.passes.shaderpass.link_program`); a
    node that brings its own program does the same with this. :meth:`for_mode`
    answers the program the draw in progress wants: the one a single view
    draws with, or the form for the views and strategy the pass's own programs
    are compiled for at the moment. Each form is compiled the first time it is
    asked for and kept. ``names`` are the uniforms to look up; ``setup`` is
    called with the program bound and its locations whenever a form is made,
    for the uniforms that are set once. ``position`` is the vertex stage's
    eye-space position, which a geometry stage projects to each view.

    The shaders include ``_multiview_inc.glsl`` and end their vertex stage by
    calling ``routeToView`` under ``MULTIVIEW_VERTEX``.
    """

    def __init__(self, vert: str, frag: str, names: Sequence[str], base: int,
                 setup: Optional[Callable[[Dict[str, int]], None]] = None,
                 position: str = 'vEyePos') -> None:
        self.vert, self.frag = vert, frag
        self.names = tuple(names)
        self.setup = setup
        self.position = position
        self._forms: Dict[Tuple[str, int], Optional[Program]] = {
            ('', 0): (int(base), self._locations(int(base)))}

    def _locations(self, program: int) -> Dict[str, int]:
        return {name: int(glGetUniformLocation(program, name))
                for name in self.names + ('viewCount', 'viewList', 'viewMask')}

    @staticmethod
    def shared(mode: Any) -> Tuple[str, int]:
        """The strategy and view count the draw in progress is shared across."""
        shader = getattr(mode, 'shader_program', None)
        views = int(getattr(shader, 'program_set', 0) or 0)
        return (str(getattr(shader, 'program_strategy', '') or ''), views) if views else ('', 0)

    def for_mode(self, mode: Any) -> Optional[Program]:
        """The program to draw with now, and its locations; None where it would not compile."""
        key = self.shared(mode)
        if key not in self._forms:
            self._forms[key] = self._build(*key)
        return self._forms[key]

    def _build(self, strategy: str, views: int) -> Optional[Program]:
        from OpenGLContext.passes.shaderpass import link_program
        from OpenGLContext.passes.shadersource import preprocess_shader
        try:
            program = int(link_program(preprocess_shader(self.vert),
                                       preprocess_shader(self.frag), False,
                                       views, strategy, position=self.position))
        except Exception as err:
            log.error('%s/%s would not compile for %d views drawn by the %s strategy: %s',
                      self.vert, self.frag, views, strategy, err)
            return None
        found = (program, self._locations(program))
        if self.setup is not None:
            glUseProgram(program)
            self.setup(found[1])
        return found

    @staticmethod
    def apply_views(mode: Any, locations: Dict[str, int]) -> None:
        """Say which views the draw reaches, on the bound program, in a shared draw."""
        shader = getattr(mode, 'shader_program', None)
        if not getattr(shader, 'program_set', 0):
            return
        mask = int(getattr(shader, 'view_mask', 0))
        if getattr(shader, 'program_strategy', '') == 'vertex':
            from OpenGLContext.multiview.strategy import view_list
            count, indices = view_list(mask)
            glUniform1i(locations['viewCount'], count)
            glUniform4iv(locations['viewList'], 4, np.asarray(indices, np.int32))
        elif locations['viewMask'] != -1:
            glUniform1ui(locations['viewMask'], mask)

    def resend(self) -> None:
        """Call ``setup`` again on every form compiled, for constants that changed.

        Each form is bound in turn; the program bound before is bound again
        after.
        """
        if self.setup is None:
            return
        previous = int(glGetIntegerv(GL_CURRENT_PROGRAM))
        try:
            for form in self._forms.values():
                if form is not None:
                    glUseProgram(form[0])
                    self.setup(form[1])
        finally:
            glUseProgram(previous)

    def programs(self) -> Iterator[int]:
        """Every form compiled, for disposal."""
        for form in self._forms.values():
            if form is not None:
                yield form[0]


@contextmanager
def view_copies(mode: Any, locations: Sequence[int]) -> Iterator[int]:
    """How many times over to instance a draw, with its instance data made to fit.

    In a shared draw by the ``vertex`` strategy each instance is drawn once per
    view, so each per-instance attribute (at ``locations``, on the bound
    vertex array) advances once every that-many copies. Answers the
    multiplier: 1 outside such a draw.
    """
    copies = int(getattr(mode, 'viewCopies', 0) or 0)
    if copies <= 1:
        yield 1
        return
    for location in locations:
        glVertexAttribDivisor(location, copies)
    try:
        yield copies
    finally:
        for location in locations:
            glVertexAttribDivisor(location, 1)


def texture_rgba(source: Any, clamp: bool = True, mipmap: bool = True,
                 srgb: bool = False) -> int:
    """Upload an RGBA texture; mipmapped + trilinear by default.

    ``source`` is a filesystem path or an already-decoded ``PIL.Image``. Accepting
    an in-memory image lets a texture embedded in an asset (e.g. a GLB's baked-in
    PNG) upload without first writing a file beside the asset -- a write that fails
    on a read-only install. ``srgb`` stores an albedo/colour texture as
    ``GL_SRGB8_ALPHA8`` so the hardware decodes it to linear on sample (and filters
    and mip-averages in linear), letting the shader drop its ``pow(rgb, 2.2)``; leave
    it False for data textures (control/normal/roughness maps) that are already linear."""
    im = (source if isinstance(source, Image.Image) else Image.open(source)).convert("RGBA")
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tid)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_SRGB8_ALPHA8 if srgb else GL_RGBA8, im.width, im.height, 0,
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
    return int(tid)


#: How many floats one instance carries, and where each part of it starts. The
#: instanced vegetation nodes all pack the same row -- a ``vec4`` transform
#: (x, y, z, yaw), a ``float`` height scale, and a ``float`` shade -- so one
#: layout serves the cards, the clumps and the near meshes alike, and anything
#: that can place a plant can also say how much sun reaches it.
INSTANCE_FLOATS = 6
INSTANCE_STRIDE = INSTANCE_FLOATS * 4


def setup_instance_attribs(loc_xform: int, loc_scale: int,
                           loc_shade: int) -> None:
    """Configure the per-instance attributes on the currently bound VAO.

    Reads from the buffer currently bound to ``GL_ARRAY_BUFFER``; the caller
    binds its instance buffer first. Each attribute advances once per instance
    (divisor 1). See :data:`INSTANCE_FLOATS` for the row."""
    for location, size, offset in ((loc_xform, 4, 0), (loc_scale, 1, 16),
                                   (loc_shade, 1, 20)):
        glVertexAttribPointer(location, size, GL_FLOAT, GL_FALSE,
                              INSTANCE_STRIDE, ctypes.c_void_p(offset))
        glEnableVertexAttribArray(location)
        glVertexAttribDivisor(location, 1)


def instance_rows(positions: Any, yaws: Any, scales: Any,
                  shades: Any = None) -> "np.ndarray":
    """One instanced field's per-instance data, in the shared layout.

    ``shades`` is how much of the sun reaches each instance, in [0, 1]; left
    out, every instance is in full sun, which is what a caller with nothing to
    say about the light means.
    """
    points = np.asarray(positions, np.float32).reshape(-1, 3)
    count = len(points)
    if not count:
        return np.zeros((0, INSTANCE_FLOATS), np.float32)
    parts = [points,
             np.asarray(yaws, np.float32).reshape(count, 1),
             np.asarray(scales, np.float32).reshape(count, 1)]
    if shades is None:
        parts.append(np.ones((count, 1), np.float32))
    else:
        lit = np.asarray(shades, np.float32).reshape(-1)
        if len(lit) != count:
            raise ValueError(
                "%d instances need %d shades, not %d" % (count, count, len(lit)))
        parts.append(lit[:, None])
    return np.concatenate(parts, 1).astype(np.float32)


class InstanceBuffer:
    """A GL array buffer that restreams per-instance data without per-frame reallocation.

    A camera-following field restreams its instances every frame. Reallocating the
    store to a new size each time churns driver memory, so the store grows only when a
    frame's instance count exceeds capacity; otherwise the live prefix is rewritten.

    A buffer rewritten every frame is also read by the previous frame's still-in-flight
    draw, so a plain ``glBufferSubData`` into it blocks until that draw drains (an
    implicit sync — visible as a per-frame stall). The rewrite therefore *orphans*
    first: ``glBufferData(capacity, None)`` hands back fresh storage for the new frame
    and lets the driver retire the old storage when the draw reading it finishes, so
    the write never waits. :attr:`id` is stable so it can be wired into a VAO once at
    setup, and :attr:`count` is the live instance count for the instanced draw."""
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
            glBufferData(GL_ARRAY_BUFFER, self.capacity, None, GL_DYNAMIC_DRAW)  # orphan
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
