"""Reusable viewing components: open a scene and let someone look around it.

An application embeds :class:`~OpenGLContext.viewer.sceneviewer.ViewerContext`
rather than reimplementing a viewer, and configures it with a
:class:`~OpenGLContext.viewer.options.ViewerOptions`:

    from OpenGLContext.viewer import ViewerContext, ViewerOptions

    class MyViewer(ViewerContext):
        options = ViewerOptions(source='model.glb', physics=True)

    MyViewer.ContextMainLoop()

``oglc-view`` (:mod:`OpenGLContext.bin.view`) is that class plus a command line,
and ``oglc-gltf-demo`` is it plus a catalogue to browse.

What format the source is in is decided by an *adapter*, not by the viewer, so
the same viewer opens a glTF model, a VRML world or a 3D Tiles dataset and every
format gets every feature.

The parts are useful separately, and each is worth reaching for on its own:

:mod:`~OpenGLContext.viewer.adapters`
    What a source is and how to read it, keyed by suffix and content type.
:mod:`~OpenGLContext.viewer.options`
    Everything a viewer can be told, in one dataclass that ``argparse`` also
    fills in, so a library caller needs no command line.
:mod:`~OpenGLContext.viewer.asyncscene`
    Loading a scene off the render thread, format-neutral, so the window keeps
    drawing through a download.
:mod:`~OpenGLContext.viewer.framing`
    Where to put a camera to see a thing -- pure arithmetic, no GL.
:mod:`~OpenGLContext.viewer.environment`
    The sky, and the skybox that matches what the model's metals reflect.
:mod:`~OpenGLContext.viewer.capture`
    Render one settled frame to a file and quit.

Walking is not here: it is a capability of *every* interactive context, in
:class:`~OpenGLContext.move.physicswalk.PhysicsWalkMixin`.

See [docs/gltf.html](../../docs/gltf.html).
"""
from typing import Any, Dict, Optional

from OpenGLContext.viewer.options import ViewerOptions

__all__ = ['ViewerOptions', 'ViewerContext', 'SceneViewerMixin', 'viewerFor']

#: The class built for each backend named, so a program asking twice gets one
#: class and ``isinstance`` means what a reader expects.
_viewers: Dict[str, type] = {}


def viewerFor(backend: Optional[str] = None) -> type:
    """The viewing context class over *backend*'s window

    backend -- the name a windowing backend is selected by (``tk``, ``qt``,
        ``wx``, ``glfw``, ``pygame``, ``glut``), or None for whichever the
        environment and the user's configuration choose, which is what
        :class:`ViewerContext` already is.

    A program putting a view inside its own window needs the viewer over the
    toolkit that owns that window, whatever the machine would otherwise pick::

        from OpenGLContext.viewer import viewerFor

        view = viewerFor('tk')(parent=someFrame)

    Raises ``RuntimeError`` naming the backends there are where that one is not
    among them, or where its toolkit is not installed.
    """
    if backend is None:
        from OpenGLContext.viewer.sceneviewer import ViewerContext

        return ViewerContext
    if backend not in _viewers:
        from OpenGLContext import plugins
        from OpenGLContext.context import Context
        from OpenGLContext.ui.overlay import OverlayMixin
        from OpenGLContext.viewer.sceneviewer import SceneViewerMixin

        base = Context.getContextType(backend, plugins.InteractiveContext)
        if base is None:
            registered = sorted(plugin.name for plugin in plugins.InteractiveContext.all())
            raise RuntimeError(
                "No interactive context is available for %r: it is either not one of the "
                "registered backends (%s) or its toolkit is not installed -- see the import "
                "error logged above." % (backend, ', '.join(registered) or 'none')
            )
        # ``OverlayMixin`` first, ahead of the navigation the base context
        # brings, for the reason :class:`ViewerContext` composes itself the same
        # way: a screen that is up takes the keys and the mouse instead of the
        # avatar walking off while somebody reads the settings.
        _viewers[backend] = type(
            '%sViewerContext' % (backend.title(),),
            (OverlayMixin, SceneViewerMixin, base),
            {'__doc__': 'The viewing component over the %s backend.' % (backend,)},
        )
    return _viewers[backend]


def __getattr__(name: str) -> Any:
    """Import the context classes on demand.

    Naming one binds a windowing backend, and a caller who only wants
    :class:`ViewerOptions` -- to build a configuration, or to read a default --
    should not have a window system chosen for them by the import.
    """
    if name in ('ViewerContext', 'SceneViewerMixin'):
        from OpenGLContext.viewer import sceneviewer
        return getattr(sceneviewer, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
