"""How a context draws several views, and what one view's part of a frame is.

A :class:`~OpenGLContext.views.ViewLayout` can put several cameras on one
window. There are three ways to draw them, and which a context can use depends
on its driver:

``vertex``
    One submission of the scene. Each draw is instanced across the views that
    can see it and the vertex shader writes ``gl_ViewportIndex``. Needs
    ``GL_ARB_shader_viewport_layer_array`` (or
    ``GL_AMD_vertex_shader_viewport_index``) as well as viewport arrays.
``geometry``
    One submission. A geometry shader emits each primitive to the views in the
    draw's list. Needs viewport arrays: core in GL 4.1, or
    ``GL_ARB_viewport_array``. A GL 4.1 driver without the vertex-shader
    extension, such as Apple silicon's, draws this way.
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

:class:`ViewFrame` is one view's part of a frame: the camera's matrices, the
frustum, the rectangle and the culled, sorted draw list. The pass builds one per
view before it draws any, because the shadow pass and the pick paths need the
views' answers before the first view is drawn.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from OpenGLContext import renderoptions
from OpenGLContext.views import MAX_VIEWS, Rect, View

log = logging.getLogger(__name__)

__all__ = [
    'IMPLEMENTED', 'MAX_VIEWS', 'MultiviewCapabilities', 'STRATEGIES',
    'ViewFrame', 'requested_strategy', 'reset_detected',
]

#: Every strategy, fastest first.
STRATEGIES: Tuple[str, ...] = ('vertex', 'geometry', 'sequential')

#: The strategies this build of the engine can draw with, fastest first.
IMPLEMENTED: Tuple[str, ...] = ('sequential',)

#: The extensions that let a vertex shader write ``gl_ViewportIndex``, in the
#: order they are preferred.
VERTEX_VIEWPORT_EXTENSIONS: Tuple[str, ...] = (
    'GL_ARB_shader_viewport_layer_array',
    'GL_AMD_vertex_shader_viewport_index',
)

#: What each GL context turned out to be able to do, keyed by the context.
_DETECTED: Dict[Any, 'MultiviewCapabilities'] = {}


def reset_detected() -> None:
    """Forget every context's answer, so the next ask reaches the driver."""
    _DETECTED.clear()


def _current_gl_context() -> Any:
    """The GL context an answer would be about, or None when none is current."""
    try:
        from OpenGL import platform
        return platform.PLATFORM.GetCurrentContext() or None
    except Exception:
        return None


def requested_strategy(source: Any) -> str:
    """The strategy ``source``'s ContextDefinition asks for; ``'auto'`` where none."""
    return renderoptions.choice(source, 'multiview', 'auto')


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
            if self.vertex_extension is not None:
                found.append('vertex')
            found.append('geometry')
        found.append('sequential')
        return tuple(found)

    def choose(self, requested: str = 'auto',
               implemented: Sequence[str] = IMPLEMENTED) -> str:
        """The strategy to draw with: ``requested`` if it can run here, else the best that can.

        A request that cannot be honoured -- a name that is not a strategy, or
        one the driver or this build lacks -- is logged, because it is how a
        strategy is pinned for a comparison and a comparison run on the wrong
        one measures nothing.
        """
        runnable = [name for name in self.available() if name in implemented]
        if requested in ('auto', '', None):
            return runnable[0]
        if requested in runnable:
            return requested
        if requested not in STRATEGIES:
            log.warning('%r is not a multi-view strategy (%s); using %s',
                        requested, ', '.join(STRATEGIES), runnable[0])
        else:
            log.warning('multi-view strategy %r cannot run on %r; using %s',
                        requested, self, runnable[0])
        return runnable[0]

    # -- construction ------------------------------------------------------
    @classmethod
    def from_features(cls, extensions: Set[str], gl_version: Tuple[int, int],
                      max_viewports: int = 16) -> 'MultiviewCapabilities':
        """From an extension set, a version and ``GL_MAX_VIEWPORTS``; no GL."""
        return cls(gl_version, extensions, max_viewports)

    @classmethod
    def detect(cls) -> 'MultiviewCapabilities':
        """What the current GL context offers, asked once per context.

        With no context current the answer is the GL 3.3 floor, and it is not
        remembered, so the real answer is had once there is one.
        """
        key = _current_gl_context()
        if key is None:
            return cls()
        cached = _DETECTED.get(key)
        if cached is not None:
            return cached
        found = cls._detect()
        if found.detected:
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

    @property
    def viewport(self) -> Tuple[int, int, int, int]:
        """The rectangle as ``glViewport`` takes it."""
        return self.rect
