"""Loading a scene without freezing the window.

The slow part of showing a model is the download and the decode, and neither
touches GL: they produce plain data -- numpy arrays, decoded images.  So they
run on a worker thread while the render loop keeps drawing, and only the result
crosses back to the render thread, where the scenegraph is built and the
geometry and textures are uploaded to the card.

That split is the whole point, and it is a rule rather than a convenience:
**nothing the worker does may touch GL.**  A context switching between models
never freezes, and a model that fails to load leaves the previous one on screen
with a message rather than an empty window.

A request supersedes the one before it.  Someone paging through a catalogue
faster than it downloads would otherwise get whichever load happened to finish
last, which is not necessarily the model they stopped on.

Format-neutral: what a load *produces* is whatever :meth:`requestScene`'s
``produce`` callable returns.
"""
import threading
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple

__all__ = ['AsyncSceneMixin']


class AsyncSceneMixin(object):
    """Gives a context background scene loading with a render-thread handover."""

    #: Whether a real scene has been applied, as opposed to whatever placeholder
    #: the context is showing while the first one arrives.
    sceneLoaded: bool = False
    #: Whether a load is in flight.
    sceneLoading: bool = False

    #: Guards the handover between the worker and the render thread.
    _loadLock: Optional[threading.Lock] = None
    #: ``(scene, error)`` waiting to be applied, or None.
    _pendingScene: Optional[Tuple[Any, Any]] = None
    #: Bumped per request; a worker whose token is stale is dropped.
    _loadToken: int = 0

    if TYPE_CHECKING:
        def triggerRedraw(self, force: int = 0) -> Any: ...

    def setupAsyncScene(self) -> None:
        """Prepare the handover.  Call before the first :meth:`requestScene`."""
        self._loadLock = threading.Lock()
        self._pendingScene = None
        self._loadToken = 0
        self.sceneLoading = False
        self.sceneLoaded = False

    def requestScene(self, produce: Callable[[], Any], label: str = '') -> None:
        """Load a scene off the render thread.

        ``produce`` is a no-arg callable run on a worker: it downloads and
        decodes, returns a scene, and **must not touch GL**.  Its result reaches
        :meth:`applyLoadedScene` on the render thread by way of
        :meth:`pollPendingScene`.  ``label`` says what is being loaded, for
        whatever the context shows meanwhile.
        """
        if self._loadLock is None:
            self.setupAsyncScene()
        assert self._loadLock is not None
        self._loadToken += 1
        token = self._loadToken
        self.sceneLoading = True
        self.onSceneLoading(label)
        self.triggerRedraw(1)

        def worker() -> None:
            error = None
            try:
                scene = produce()
            except Exception as err:    # an unreachable model must not kill the thread
                scene, error = None, err
            assert self._loadLock is not None
            with self._loadLock:
                if token == self._loadToken:    # a newer request wins; drop this
                    self._pendingScene = (scene, error)
                    self.sceneLoading = False
        threading.Thread(target=worker, name='scene-load', daemon=True).start()

    def pollPendingScene(self) -> bool:
        """On the render thread: apply a finished load, if there is one.

        Returns whether anything was applied.  Call from the idle handler before
        anything else touches the scenegraph.  The scenegraph is built here and
        not in the worker, which is what keeps every GL upload on this thread.
        """
        if self._loadLock is None:
            return False
        with self._loadLock:
            pending = self._pendingScene
            self._pendingScene = None
        if pending is None:
            return False
        scene, error = pending
        if scene is not None:
            self.applyLoadedScene(scene)
        else:
            self.applyFailedLoad(error)
        self.triggerRedraw(1)
        return True

    # -- what a context fills in ------------------------------------------
    def onSceneLoading(self, label: str) -> None:
        """A load has started.  A hook for showing ``label``; does nothing here."""

    def applyLoadedScene(self, scene: Any) -> None:
        """Render thread: build the scenegraph for a freshly loaded scene."""
        raise NotImplementedError

    def applyFailedLoad(self, error: Optional[BaseException]) -> None:
        """Render thread: a load raised.  Say so and leave the view as it is."""
        raise NotImplementedError
