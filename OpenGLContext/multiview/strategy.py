"""How a context draws several views, and what one view's part of a frame is.

A :class:`~OpenGLContext.multiview.views.ViewLayout` can put several cameras on one
window. There are three ways to draw them, and which a context can use depends
on its driver:

``vertex``
    One submission of the scene. Each draw is instanced across the views that
    can see it and the vertex shader writes ``gl_ViewportIndex``. Needs GL 4.1
    and ``GL_ARB_shader_viewport_layer_array`` (or
    ``GL_AMD_vertex_shader_viewport_index``).
``geometry``
    One submission. A geometry shader, invoked once per view, emits each
    triangle to the views in the draw's mask. Needs viewport arrays (core in GL
    4.1, or ``GL_ARB_viewport_array``) and instanced geometry shaders (core in
    GL 4.0, or ``GL_ARB_gpu_shader5``). A GL 4.1 driver without the
    vertex-shader extension, such as Apple silicon's, draws this way.
``sequential``
    The scene is drawn once per view, with ``glViewport`` and ``glScissor``
    between. Needs nothing beyond GL 3.3; the other strategies are tested
    against its images.

:class:`MultiviewCapabilities` decides from the extension list and version.
The decision is a pure function (:meth:`MultiviewCapabilities.from_features`)
and the driver is asked once per GL context (:meth:`MultiviewCapabilities.detect`).
``ContextDefinition.multiview`` (env ``OPENGLCONTEXT_MULTIVIEW``) asks for one
strategy by name, so each can be run and compared on one machine; a strategy
the driver cannot run is reported and the best one it can run is used instead.
The render pass chooses again on the frame after the field changes.

:class:`ViewFrame` is one view's part of a frame: the camera's matrices, the
frustum, the rectangle and the culled, sorted draw list. The pass builds one per
view before it draws any, because the shadow pass and the pick paths need the
views' answers before the first view is drawn.

A shared submission draws in a *reference* camera's eye space -- the active
view's -- so modelviews, instance buffers, lights and shadow matrices are the
ones a single view would use. Each view's record in the ``ViewBlock`` uniform
block (:func:`view_records`, :func:`pack_view_table`) says how to reach it from
there: the matrix from reference eye space to the view's clip space, where the
view's eye is in reference space, and whether it reads the directional shadow
cascades by depth or by containment.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Collection, Dict, Iterable, List, NamedTuple, Optional, Sequence, Set, Tuple

import numpy as np

from OpenGL.GL import (
    glDrawArrays, glDrawArraysInstanced, glDrawElements, glDrawElementsInstanced,
)

from OpenGLContext import contextresources, renderoptions
from OpenGLContext.multiview.views import MAX_VIEWS, Rect, View

log = logging.getLogger(__name__)

__all__ = [
    'MAX_VIEWS', 'MultiviewCapabilities', 'STRATEGIES',
    'VIEW_BLOCK_BINDING', 'VIEW_RECORD_BYTES', 'ViewFrame', 'ViewRecord',
    'driver_view_offsets', 'pack_view_table', 'program_views', 'requested_strategy',
    'reset_detected', 'view_mask', 'view_record_offsets', 'view_records',
    'draw_arrays', 'draw_elements', 'view_list',
]

#: Every strategy, fastest first.
STRATEGIES: Tuple[str, ...] = ('vertex', 'geometry', 'sequential')

#: The uniform-buffer binding point the ``ViewBlock`` is read from.
VIEW_BLOCK_BINDING = 2

#: One view's record in the ``ViewBlock``, std140: ``mat4 refToClip`` (64
#: bytes), ``vec4 eye`` (16) and ``ivec4 flags`` (16).
VIEW_RECORD_BYTES = 96

#: The extensions that let a vertex shader write ``gl_ViewportIndex``, in the
#: order they are preferred.
VERTEX_VIEWPORT_EXTENSIONS: Tuple[str, ...] = (
    'GL_ARB_shader_viewport_layer_array',
    'GL_AMD_vertex_shader_viewport_index',
)

#: What each GL context turned out to be able to do, keyed by the context
#: (:func:`~OpenGLContext.contextresources.context_key`), and dropped as the
#: context dies, since a driver hands its address to the next one.
_DETECTED: Dict[Optional[contextresources.ContextKey], 'MultiviewCapabilities'] = {}


def reset_detected() -> None:
    """Forget every context's answer, so the next ask reaches the driver."""
    _DETECTED.clear()


@contextresources.on_context_lost
def _forget_dying_context() -> None:
    """Drop the answer for the context being torn down."""
    _DETECTED.pop(contextresources.context_key(), None)


def requested_strategy(source: Any) -> str:
    """The strategy ``source``'s ContextDefinition asks for.

    Where nothing set the field, ``OPENGLCONTEXT_MULTIVIEW`` does, read once
    per session, and ``'auto'`` where neither says.
    """
    return renderoptions.choice(source, 'multiview', renderoptions.env_choice_once(
        'OPENGLCONTEXT_MULTIVIEW', renderoptions.CHOICES['multiview'],
        renderoptions.SYNONYMS['multiview']))


class MultiviewCapabilities:
    """What a driver offers for drawing several views, and the strategy that follows.

    ``gl_version`` is ``(major, minor)``, ``extensions`` the driver's extension
    names and ``max_viewports`` its ``GL_MAX_VIEWPORTS`` (1 where it has no
    viewport arrays). ``detected`` says whether this came from a real driver
    rather than the GL 3.3 floor assumed with no context current.
    """

    def __init__(self, gl_version: Tuple[int, int] = (3, 3),
                 extensions: Optional[Set[str]] = None,
                 max_viewports: int = 1, detected: bool = False) -> None:
        self.gl_version = (int(gl_version[0]), int(gl_version[1]))
        self.extensions = frozenset(
            name if name.startswith('GL_') else 'GL_' + name
            for name in (extensions or ()))
        self.max_viewports = int(max_viewports)
        self.detected = detected

    def __repr__(self) -> str:
        return '<MultiviewCapabilities GL %d.%d, %s>' % (
            self.gl_version + (', '.join(self.available()),))

    # -- what is there -----------------------------------------------------
    @property
    def viewport_array(self) -> bool:
        """Whether one draw can reach more than one viewport."""
        offered = self.gl_version >= (4, 1) or 'GL_ARB_viewport_array' in self.extensions
        return offered and self.max_viewports >= 2

    @property
    def geometry_invocations(self) -> bool:
        """Whether a geometry shader can be invoked once per view."""
        return self.gl_version >= (4, 0) or 'GL_ARB_gpu_shader5' in self.extensions

    @property
    def vertex_extension(self) -> Optional[str]:
        """The extension a vertex shader writes ``gl_ViewportIndex`` through, or None."""
        for name in VERTEX_VIEWPORT_EXTENSIONS:
            if name in self.extensions:
                return name
        return None

    @property
    def max_views(self) -> int:
        """How many views one submission can reach: the viewports, and the view table."""
        if not self.viewport_array:
            return MAX_VIEWS
        return min(self.max_viewports, MAX_VIEWS)

    def available(self) -> Tuple[str, ...]:
        """The strategies this driver can run, fastest first."""
        found = []
        if self.viewport_array:
            if self.vertex_extension is not None and self.gl_version >= (4, 1):
                found.append('vertex')
            if self.geometry_invocations:
                found.append('geometry')
        found.append('sequential')
        return tuple(found)

    def choose(self, requested: str = 'auto',
               implemented: Sequence[str] = STRATEGIES,
               failed: Collection[str] = ()) -> str:
        """The strategy to draw with: ``requested`` if it can run here, else the best that can.

        ``failed`` names strategies the driver offered and then could not
        build programs for; they are passed over. ``sequential`` needs no
        programs of its own and is never passed over.

        A request that cannot be honoured -- a name that is not a strategy, or
        one the driver or this build lacks -- is logged, because it is how a
        strategy is pinned for a comparison and a comparison run on the wrong
        one measures nothing.
        """
        runnable = [name for name in self.available()
                    if name in implemented and (name == 'sequential' or name not in failed)]
        if requested in ('auto', '', None):
            return runnable[0]
        if requested in runnable:
            return requested
        if requested not in STRATEGIES:
            log.warning('%r is not a multi-view strategy (%s); using %s',
                        requested, ', '.join(STRATEGIES), runnable[0])
        elif requested in failed:
            log.warning('multi-view strategy %r did not compile on %r; using %s',
                        requested, self, runnable[0])
        else:
            log.warning('multi-view strategy %r cannot run on %r; using %s',
                        requested, self, runnable[0])
        return runnable[0]

    # -- construction ------------------------------------------------------
    @classmethod
    def from_features(cls, extensions: Set[str], gl_version: Tuple[int, int],
                      max_viewports: int = 1) -> 'MultiviewCapabilities':
        """From an extension set, a version and ``GL_MAX_VIEWPORTS``; no GL."""
        return cls(gl_version, extensions, max_viewports)

    @classmethod
    def detect(cls) -> 'MultiviewCapabilities':
        """What the current GL context offers, asked once per context.

        With no context current the answer is the GL 3.3 floor, and it is not
        remembered, so the real answer is had once there is one. A context
        whose driver reports no version or extensions is answered with the
        floor too, and that answer is kept for the context's life.
        """
        key = contextresources.context_key()
        if key is None:
            return cls()
        cached = _DETECTED.get(key)
        if cached is not None:
            return cached
        found = cls._detect()
        _DETECTED[key] = found
        log.info('multi-view: %r', found)
        return found

    @classmethod
    def _detect(cls) -> 'MultiviewCapabilities':
        """The driver's answer; see :meth:`detect`."""
        from OpenGL import extensions as glextensions
        from OpenGL.GL import glGetIntegerv, GL_MAX_VIEWPORTS

        version = glextensions.GLQuerier.getVersion()
        names = glextensions.GLQuerier.getExtensions()
        if not version or not names:
            return cls()
        found = cls.from_features(
            {name.decode('latin-1') if isinstance(name, bytes) else name
             for name in names},
            (int(version[0]), int(version[1])), 1)
        viewports = 1
        if found.gl_version >= (4, 1) or 'GL_ARB_viewport_array' in found.extensions:
            viewports = int(glGetIntegerv(GL_MAX_VIEWPORTS))
        return cls(found.gl_version, set(found.extensions), viewports, detected=True)


@dataclass
class ViewFrame:
    """One view's part of one frame, worked out before any view is drawn.

    ``modelView`` and ``projection`` are the camera's, the projection already
    trimmed to the frame's depth; ``frustum`` is the one culling was done
    against, ``toRender`` the draw records that survived it and
    ``visiblePlacements`` which copies of each instanced set it kept.
    ``fitted`` marks the view the directional shadow cascades were fitted to.
    """

    view: View
    camera: Any
    rect: Rect
    modelView: Any
    projection: Any
    modelproj: Any
    frustum: Any
    maxDepth: float = 0.0
    toRender: List[Any] = field(default_factory=list)
    visiblePlacements: Dict[int, Any] = field(default_factory=dict)
    fitted: bool = False


class ViewRecord(NamedTuple):
    """One view's entry in the ``ViewBlock``, as the shaders read it.

    ``refToClip`` takes a point in the reference camera's eye space to this
    view's clip space (row-vector, as the engine's matrices are). ``eye`` is
    this view's camera position in reference eye space, ``w`` 1.
    ``cascadeByFit`` is 1 where the view reads a directional light's cascades
    by which map holds a point rather than by its depth.
    """

    refToClip: Any
    eye: Any
    cascadeByFit: int


def view_records(frames: Sequence[ViewFrame], reference: ViewFrame) -> List[ViewRecord]:
    """Each frame's :class:`ViewRecord`, for drawing in ``reference``'s eye space."""
    to_world = np.linalg.inv(np.asarray(reference.modelView, 'd'))
    reference_view = np.asarray(reference.modelView, 'd')
    records = []
    for frame in frames:
        view = np.asarray(frame.modelView, 'd')
        if frame is reference:
            to_clip = np.asarray(frame.projection, 'd')
            eye = np.array([0.0, 0.0, 0.0, 1.0])
        else:
            to_clip = to_world @ view @ np.asarray(frame.projection, 'd')
            camera = np.linalg.inv(view)[3]
            eye = camera @ reference_view
            eye = eye / eye[3]
        records.append(ViewRecord(to_clip, eye, 0 if frame.fitted else 1))
    return records


def pack_view_table(frames: Sequence[ViewFrame], reference: ViewFrame,
                    capacity: int = 0) -> bytes:
    """The ``ViewBlock`` contents for ``frames`` drawn in ``reference``'s eye space.

    A row-vector matrix's rows are the column vectors GLSL reads, so each
    matrix goes in as it is stored, as ``glUniformMatrix4fv`` takes it untransposed.
    ``capacity`` is the views the program was compiled for; the records past
    ``frames`` are zero, and no view mask names them.
    """
    parts = []
    for record in view_records(frames, reference):
        parts.append(np.ascontiguousarray(record.refToClip, '<f4').tobytes())
        parts.append(np.ascontiguousarray(record.eye, '<f4').tobytes())
        parts.append(np.array([record.cascadeByFit, 0, 0, 0], '<i4').tobytes())
    parts.append(bytes(max(0, int(capacity) - len(frames)) * VIEW_RECORD_BYTES))
    return b''.join(parts)


def program_views(views: int) -> int:
    """The views a program for a shared draw of ``views`` views is compiled for.

    The next power of two, and at least two: a program serves any draw of up
    to as many views as it was compiled for, since a view mask names only the
    views drawn, so a frame whose count of views changes compiles again only
    when the count passes the next power of two.
    """
    count = 2
    while count < int(views):
        count *= 2
    return count


def view_record_offsets(count: int) -> Dict[str, int]:
    """The std140 byte offset of each ``ViewBlock`` member, by GLSL name."""
    offsets = {}
    for index in range(count):
        base = index * VIEW_RECORD_BYTES
        offsets['views[%d].refToClip' % index] = base
        offsets['views[%d].eye' % index] = base + 64
        offsets['views[%d].flags' % index] = base + 80
    return offsets


def driver_view_offsets(program: int) -> Dict[str, int]:
    """The offsets the driver gives the ``ViewBlock`` members of ``program``.

    What :func:`view_record_offsets` is held to; a program whose block is
    missing answers an empty mapping.
    """
    from OpenGL import GL

    def indices_of(names: List[str]) -> Any:
        found = np.zeros(len(names), 'I')
        GL.glGetUniformIndices(program, len(names), names, found)
        return found

    count = 0
    while int(indices_of(['views[%d].eye' % count])[0]) != GL.GL_INVALID_INDEX:
        count += 1
    names = list(view_record_offsets(count))
    if not names:
        return {}
    indices = indices_of(names)
    offsets = np.zeros(len(names), 'i')
    GL.glGetActiveUniformsiv(program, len(names), indices, GL.GL_UNIFORM_OFFSET, offsets)
    return {name: int(offset) for name, offset in zip(names, offsets)}


def view_mask(indices: Iterable[int]) -> int:
    """The bit mask of the view indices a draw is to reach."""
    mask = 0
    for index in indices:
        mask |= 1 << int(index)
    return mask


def view_list(mask: int) -> Tuple[int, List[int]]:
    """``(count, indices)`` of the views in ``mask``, padded to :data:`MAX_VIEWS`.

    What the ``vertex`` strategy's routing reads: a draw instanced ``count``
    times over sends copy ``i`` to view ``indices[i % count]``.
    """
    indices = [index for index in range(MAX_VIEWS) if mask >> index & 1]
    return len(indices), indices + [0] * (MAX_VIEWS - len(indices))


def draw_arrays(mode: Any, primitive: int, first: int, count: int) -> None:
    """``glDrawArrays``, once for every view the draw in progress serves.

    ``mode.viewCopies`` is how many views a shared draw of the ``vertex``
    strategy reaches; the draw is then instanced that many times and the
    vertex stage routes each copy to its view. Otherwise it is one draw.
    """
    copies = int(getattr(mode, 'viewCopies', 0) or 0)
    if copies:
        glDrawArraysInstanced(primitive, first, count, copies)
    else:
        glDrawArrays(primitive, first, count)


def draw_elements(mode: Any, primitive: int, count: int, index_type: int,
                  indices: Any) -> None:
    """``glDrawElements``, once for every view; see :func:`draw_arrays`."""
    copies = int(getattr(mode, 'viewCopies', 0) or 0)
    if copies:
        glDrawElementsInstanced(primitive, count, index_type, indices, copies)
    else:
        glDrawElements(primitive, count, index_type, indices)
