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
:mod:`~OpenGLContext.viewer.overlay`
    A caption over the frame, and a key that saves a PNG.
:mod:`~OpenGLContext.viewer.capture`
    Render one settled frame to a file and quit.

Walking is not here: it is a capability of *every* interactive context, in
:class:`~OpenGLContext.move.physicswalk.PhysicsWalkMixin`.

See [docs/gltf.html](../../docs/gltf.html).
"""
from OpenGLContext.viewer.options import ViewerOptions

__all__ = ['ViewerOptions', 'ViewerContext', 'SceneViewerMixin']


def __getattr__(name: str) -> object:
    """Import the context classes on demand.

    Naming one binds a windowing backend, and a caller who only wants
    :class:`ViewerOptions` -- to build a configuration, or to read a default --
    should not have a window system chosen for them by the import.
    """
    if name in ('ViewerContext', 'SceneViewerMixin'):
        from OpenGLContext.viewer import sceneviewer
        return getattr(sceneviewer, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
