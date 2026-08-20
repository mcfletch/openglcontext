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
import logging
import threading
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple

log = logging.getLogger(__name__)

__all__ = ['AsyncSceneMixin', 'SCENE_MARK', 'SCENE_WAIT_SECONDS']

#: How long a replayed session waits for a load the recording already had, in
#: seconds.  Long enough for a level that took seconds to read the first time;
#: bounded because a replay is diagnostic equipment and may not hang on a load
#: that never arrives.
SCENE_WAIT_SECONDS = 30.0

#: What mounting a loaded scene is written down as in a session recording, and
#: what a replay holds the mounting until the recorded frame of.  A level
#: arrives when the disk and the decoder are finished with it, which is not the
#: same frame twice: a session in which it appeared three frames early is one
#: where every recorded input after it was given to a world that had already
#: started.  See :mod:`OpenGLContext.telemetry`.
SCENE_MARK = 'scene-mounted'


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

    #: What the last request was loading, so the mark that says it was mounted
    #: can name it.
    _loadLabel: str = ''
    #: Set when a worker posts its result; what a replayed session waits on.
    _loadFinished: Optional[threading.Event] = None
    #: How long such a session waits.  A field rather than the constant, so an
    #: application that knows its loads are quick can say so.
    sceneWaitSeconds: float = SCENE_WAIT_SECONDS

    if TYPE_CHECKING:
        def triggerRedraw(self, force: int = 0) -> Any: ...

    def setupAsyncScene(self) -> None:
        """Prepare the handover.  Call before the first :meth:`requestScene`."""
        self._loadLock = threading.Lock()
        self._loadFinished = threading.Event()
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
        self._loadLabel = str(label)
        if self._loadFinished is None:
            self._loadFinished = threading.Event()
        self._loadFinished.clear()
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
                    if self._loadFinished is not None:
                        self._loadFinished.set()
        threading.Thread(target=worker, name='scene-load', daemon=True).start()

    def pollPendingScene(self) -> bool:
        """On the render thread: apply a finished load, if there is one.

        Returns whether anything was applied.  Call from the idle handler before
        anything else touches the scenegraph.  The scenegraph is built here and
        not in the worker, which is what keeps every GL upload on this thread.

        **A replayed session mounts it on the frame it was mounted on.**  A
        load finishes when the disk and the decoder are finished with it, so a
        scene that is ready early here is held until the recording's own frame
        for it; see :data:`SCENE_MARK`.
        """
        if self._loadLock is None:
            return False
        if self.sceneLoading:
            self._waitIfOverdue()
        with self._loadLock:
            pending = self._pendingScene
            if pending is None:
                return False
            if not self._mountDue():
                return False
            self._pendingScene = None
        scene, error = pending
        if scene is not None:
            self.applyLoadedScene(scene)
        else:
            self.applyFailedLoad(error)
        self._markMounted(scene is not None)
        self.triggerRedraw(1)
        return True

    # -- recording when it happened ---------------------------------------
    def _mountDue(self) -> bool:
        """Whether a finished load may be mounted on this frame.

        Now, unless this session is a replay that has not yet reached the frame
        the recording mounted one on.  Asked of the host rather than of the
        telemetry package, since a host that is not a
        :class:`~OpenGLContext.context.Context` -- which is how this mix-in is
        tested -- has no session at all and is never held up.
        """
        reached = getattr(self, 'reachedMark', None)
        return True if reached is None else bool(reached(SCENE_MARK))

    def _waitIfOverdue(self) -> None:
        """Wait for a load a replayed recording had already mounted by now.

        A load takes what it takes, and the frames drawn meanwhile are whatever
        the machine managed: a session that spent 57 frames reading a level
        replays in 66 of them, and every recorded input after that is nine
        frames out of step.  So a replay that has reached the frame the scene
        was mounted on stops drawing and waits for it.

        Bounded (:data:`SCENE_WAIT_SECONDS`), and a wait that runs out is a
        warning and a session that carries on: a replay is diagnostic equipment
        and does not get to hang on a load that never arrives.
        """
        overdue = getattr(self, 'overdueMark', None)
        if overdue is None or not overdue(SCENE_MARK):
            return
        finished = self._loadFinished
        if finished is None or finished.wait(self.sceneWaitSeconds):
            return
        log.warning('waited %gs for %r, which the recorded session had by this '
                    'frame; the replay goes on without it',
                    self.sceneWaitSeconds, self._loadLabel)

    def _markMounted(self, loaded: bool) -> None:
        """Write down that a scene was mounted on this frame, for a replay."""
        mark = getattr(self, 'mark', None)
        if mark is not None:
            mark(SCENE_MARK, label=self._loadLabel, loaded=bool(loaded))

    # -- what a context fills in ------------------------------------------
    def onSceneLoading(self, label: str) -> None:
        """A load has started.  A hook for showing ``label``; does nothing here."""

    def applyLoadedScene(self, scene: Any) -> None:
        """Render thread: build the scenegraph for a freshly loaded scene."""
        raise NotImplementedError

    def applyFailedLoad(self, error: Optional[BaseException]) -> None:
        """Render thread: a load raised.  Say so and leave the view as it is."""
        raise NotImplementedError
