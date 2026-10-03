"""What a format provides to :class:`~OpenGLContext.loaders.sceneloader.SceneLoader`.

A reader knows one kind of source and nothing about what is done with it: it
turns a path, a URL or bytes into whatever that format's own loader produces --
a ``GLTFScene``, a ``SceneGraph``, a game's level -- and the caller decides the
rest.  It is registered under :class:`OpenGLContext.plugins.Adapter` against the
suffixes and content types it handles::

    from OpenGLContext.plugins import Adapter
    Adapter('stl', 'mypackage.stl.STLReader', ['.stl', 'model/stl'])

so a package adds a format by registering one more entry, and
``SceneLoader.load('part.stl')`` reads it.  A viewer that can also *show* the
format registers a :class:`~OpenGLContext.viewer.adapters.base.SceneAdapter`,
which is a reader with the questions a viewer asks of a scene.
"""
from __future__ import annotations

from typing import Any

__all__ = ['SceneReader']


class SceneReader:
    """How one kind of source is read.

    Instantiated per request: a reader may keep state for what it read, which
    is how a streaming format keeps its runtime alive.
    """

    #: Registry key, for ``format=`` and for error messages.
    name: str = ''

    #: Whether :meth:`read_content` can read bytes already in memory.  A format
    #: that is a tree of files, or a service, can only be read from where it is.
    accepts_content: bool = False

    def configure(self, options: Any) -> None:
        """Take what the caller's ``options`` say about *this kind of* source.

        Called before :meth:`read`, with whatever was passed as ``options=``.
        Most formats are read the one way there is to read them and want
        nothing here.
        """

    def read(self, source: str) -> Any:
        """Read ``source`` and return what the format's own loader produces.

        **Runs on a worker thread, so it must not touch GL.**  Everything that
        uploads is left to the render thread, which is what lets the window keep
        drawing through a download.
        """
        raise NotImplementedError("%s.read" % (type(self).__name__,))

    def read_content(self, data: bytes, name: str = '') -> Any:
        """Read a document held in memory, as :meth:`read` reads one from a path.

        ``name`` is what the document would be called as a file; it is the
        base its relative references resolve against, and for a format whose
        loader dispatches on a suffix, it is what says which one.  Only for a
        reader with :attr:`accepts_content`.
        """
        raise NotImplementedError(
            "the %r reader reads from a path or a URL, not from memory"
            % (self.name or type(self).__name__,))

    def shutdown(self) -> None:
        """Release anything the result is still holding.  Called on teardown."""
