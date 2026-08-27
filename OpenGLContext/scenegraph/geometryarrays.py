"""What a geometry node has to give, described once.

A geometry keeps its vertices in separate buffers (``IndexedFaceSet``,
``ArrayGeometry``), or interleaved in one (``Box``, the quadrics, ``Teapot``), or
in whatever a raw-GL layer builds for itself. Those are three ways of holding the
same thing, and they used to be three ways of *describing* it as well, each with
its own binder. :class:`GeometryArrays` is the one description they all turn
into: which semantic each buffer carries, how to read it, and how to draw the
result.

The semantics and the attribute locations are
:mod:`OpenGLContext.scenegraph.vertexsemantics`'s; because those locations are
the same in every conforming program, one vertex array object per geometry
serves the lit pass, the unlit pass and the shadow depth pass alike, and
:func:`bind_geometry` keeps it on the node.

:func:`report_missing_inputs` closes the other half: a shader that reads a
semantic the geometry has not got draws every vertex from a default value, with
no GL error to say so, and this says so instead.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, NamedTuple, Optional, Tuple

from OpenGL.GL import (
    GL_ACTIVE_ATTRIBUTES, GL_FALSE, GL_FLOAT, GL_TRIANGLES,
    GL_UNSIGNED_SHORT,
    glBindVertexArray, glDrawArrays, glDrawElements,
    glEnableVertexAttribArray, glGenVertexArrays, glGetActiveAttrib,
    glGetProgramiv, glVertexAttribPointer,
)

from OpenGLContext.scenegraph import vertexsemantics
from OpenGLContext.scenegraph.shadergeometry import (
    SHARED_LAYOUT, get_or_build_vao,
)

__all__ = [
    'VertexArray', 'GeometryArrays', 'bind_geometry', 'draw_geometry',
    'render_geometry', 'MissingVertexInput', 'report_missing_inputs',
]

#: The semantic each ``VertexFormat`` key describes, and how the engine's own
#: geometry nodes name the same array when they keep it in a buffer of its own.
INTERLEAVED_KEYS = (
    ('position', 'POSITION'),
    ('normal', 'NORMAL'),
    ('texcoord', 'TEXCOORD_0'),
)

#: Keyword name -> (semantic, components) for :meth:`GeometryArrays.separate`.
SEPARATE_KEYS = (
    ('positions', 'POSITION', 3),
    ('normals', 'NORMAL', 3),
    ('texcoords', 'TEXCOORD_0', 2),
    ('tangents', 'TANGENT', 4),
    ('colors', 'COLOR_0', 4),
    ('texcoords1', 'TEXCOORD_1', 2),
)


class VertexArray(NamedTuple):
    """One attribute's worth of a buffer: where it is and how to read it."""

    buffer: Any
    """The ``vbo.VBO`` (or buffer name) the values come from."""
    components: int
    """Values per vertex."""
    gl_type: int = GL_FLOAT
    stride: int = 0
    """Bytes between consecutive records; 0 means tightly packed."""
    offset: int = 0
    """Bytes from the start of the buffer to the first record."""
    normalized: bool = False


class GeometryArrays(object):
    """The buffers a geometry offers, keyed by vertex semantic.

    Built through :meth:`separate` or :meth:`interleaved` for the two shapes the
    engine's own geometry comes in, or directly by anything that already knows
    its layout.
    """

    def __init__(
        self,
        arrays: Dict[str, VertexArray],
        count: int,
        draw_mode: int = GL_TRIANGLES,
        indices: Optional[Any] = None,
        index_type: int = GL_UNSIGNED_SHORT,
    ) -> None:
        self.arrays = arrays
        self.count = count
        self.draw_mode = draw_mode
        self.indices = indices
        self.index_type = index_type

    @property
    def indexed(self) -> bool:
        """Whether the draw reads an element buffer rather than running straight
        through the vertices."""
        return self.indices is not None

    @property
    def semantics(self) -> frozenset:
        """What this geometry can feed a shader."""
        return frozenset(self.arrays)

    def buffers(self) -> Tuple[Any, ...]:
        """Every buffer this describes, for cache-invalidation by identity."""
        return tuple(entry.buffer for entry in self.arrays.values()) + (
            self.indices,)

    @classmethod
    def separate(
        cls,
        count: int,
        draw_mode: int = GL_TRIANGLES,
        indices: Optional[Any] = None,
        index_type: int = GL_UNSIGNED_SHORT,
        **buffers: Any
    ) -> 'GeometryArrays':
        """One buffer per attribute, named as the engine's geometry names them.

        ``positions``, ``normals``, ``texcoords``, ``tangents``, ``colors`` and
        ``texcoords1``; anything passed as None is simply not offered.
        """
        unknown = set(buffers) - {name for name, _, _ in SEPARATE_KEYS}
        if unknown:
            raise TypeError('not vertex arrays this engine names: %s'
                            % (', '.join(sorted(unknown)),))
        arrays = {
            semantic: VertexArray(buffers[name], components)
            for name, semantic, components in SEPARATE_KEYS
            if buffers.get(name) is not None
        }
        return cls(arrays, count, draw_mode, indices, index_type)

    @classmethod
    def interleaved(
        cls,
        buffer: Any,
        vertex_format: Dict[str, int],
        count: int,
        draw_mode: int = GL_TRIANGLES,
        indices: Optional[Any] = None,
        index_type: int = GL_UNSIGNED_SHORT,
    ) -> 'GeometryArrays':
        """One buffer holding every attribute, at the offsets ``vertex_format``
        gives (see ``shadergeometry.VertexFormat``)."""
        stride = vertex_format['stride']
        arrays = {
            semantic: VertexArray(
                buffer,
                vertex_format['%s_size' % (key,)],
                stride=stride,
                offset=vertex_format['%s_offset' % (key,)],
            )
            for key, semantic in INTERLEAVED_KEYS
            if '%s_offset' % (key,) in vertex_format
        }
        return cls(arrays, count, draw_mode, indices, index_type)


def bind_geometry(
    arrays: GeometryArrays,
    owner: Any = None,
    program: Optional[int] = None,
) -> Optional[int]:
    """Return a vertex array object describing ``arrays``.

    Cached on ``owner`` when one is given, keyed by the identity of the buffers
    it wraps, so a data change rebuilds it rather than drawing through stale
    pointers. The layout does not depend on the program, so one object serves
    every conforming one; ``program`` is here only so that a caller which has
    the program can have its inputs checked (:func:`report_missing_inputs`).
    """
    def build() -> None:
        for semantic, entry in arrays.arrays.items():
            location = vertexsemantics.location(semantic)
            entry.buffer.bind()
            glEnableVertexAttribArray(location)
            glVertexAttribPointer(
                location, entry.components, entry.gl_type,
                entry.normalized and 1 or GL_FALSE, entry.stride,
                entry.buffer + entry.offset,
            )
        if arrays.indices is not None:
            # The element-array binding is recorded in the vertex array object.
            arrays.indices.bind()
        for entry in arrays.arrays.values():
            entry.buffer.unbind()

    if owner is not None:
        cached = get_or_build_vao(
            owner, program or 0, arrays.buffers(), build,
            layout_key=SHARED_LAYOUT)
        if cached is not None:
            return int(cached)
    # No owner to cache on (or the owner refused): a transient object, which the
    # caller deletes.
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    try:
        build()
    finally:
        glBindVertexArray(0)
    return int(vao)


def draw_geometry(arrays: GeometryArrays) -> None:
    """Issue the draw ``arrays`` describes, with its vertex array bound."""
    if arrays.indexed:
        glDrawElements(arrays.draw_mode, arrays.count, arrays.index_type, None)
    else:
        glDrawArrays(arrays.draw_mode, 0, arrays.count)


def render_geometry(
    mode: Any,
    arrays: GeometryArrays,
    owner: Any = None,
    where: str = 'geometry',
) -> bool:
    """Bind ``arrays`` and draw them through the program the pass has bound.

    Returns False when the pass has no program to draw with, which is how a
    geometry node says "not this pass".
    """
    shader_program = getattr(mode, 'shader_program', None)
    if shader_program is None or not getattr(shader_program, 'program', None):
        return False
    program = shader_program.program
    vao = bind_geometry(arrays, owner=owner, program=program)
    if vao is None:
        return False
    report_missing_inputs(program, arrays, mode=mode, node=owner, where=where)
    glBindVertexArray(vao)
    try:
        draw_geometry(arrays)
    finally:
        glBindVertexArray(0)
    return True


class MissingVertexInput(Exception):
    """A shader reads a vertex input the geometry does not supply.

    Not raised: a missing attribute is not an error the GL reports, and the draw
    goes ahead reading a default value for every vertex. This exists so that the
    situation can be described to ``RenderFailureLog`` in the same shape as
    everything else that stopped a shape looking right.
    """


#: (program, semantics) pairs already checked, so the query costs one dict
#: lookup per draw after the first. Attribute sets do not change once a program
#: is linked, and a re-linked program gets a new name.
_CHECKED: set = set()


def program_inputs(program: int) -> Iterable[str]:
    """The attribute names ``program`` actually reads."""
    count = int(glGetProgramiv(program, GL_ACTIVE_ATTRIBUTES) or 0)
    for index in range(count):
        name, _size, _type = glGetActiveAttrib(program, index)
        if isinstance(name, bytes):
            name = name.decode('ascii', 'replace')
        yield name


def report_missing_inputs(
    program: int,
    arrays: GeometryArrays,
    mode: Any = None,
    node: Any = None,
    where: str = 'geometry',
) -> Optional[MissingVertexInput]:
    """Say which of ``program``'s inputs ``arrays`` has not got.

    An attribute nothing feeds reads the same default value for every vertex,
    which draws a shape flat, or black, or at the origin, and raises nothing.
    Reported once per program-and-geometry through the pass's failure log, which
    logs the first of each cause and counts the rest.

    Returns the description when something was missing, so a caller without a
    pass can still see it; returns None when everything the shader reads is
    offered.
    """
    key = (int(program), arrays.semantics)
    if key in _CHECKED:
        return None
    _CHECKED.add(key)
    provided = {vertexsemantics.BY_SEMANTIC[semantic].attribute
                for semantic in arrays.arrays}
    missing = [
        name for name in program_inputs(program)
        # Only the engine's own names are ours to supply; a shader's private
        # input at a free location is its own business.
        if name in vertexsemantics.BY_ATTRIBUTE and name not in provided
    ]
    if not missing:
        return None
    err = MissingVertexInput(
        'the shader reads %s, which this geometry does not supply'
        % (', '.join(sorted(missing)),))
    failed = getattr(mode, 'renderFailed', None)
    if failed is not None:
        failed(where, node, err)
    return err


def forget_checked_programs() -> None:
    """Drop the record of which programs have been checked.

    A context going away takes its program names with it, and the next context
    reuses them; tests that build a context per case call this between them.
    """
    _CHECKED.clear()
