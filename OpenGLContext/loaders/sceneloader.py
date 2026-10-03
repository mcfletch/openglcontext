"""Loading scenes without freezing the window: the loader package's front door.

A :class:`SceneLoader` reads a file, a URL or a document held in memory, on a
worker thread, and hands the result back on the render thread through a
:class:`~OpenGLContext.events.renderqueue.RenderQueue`.  Every
:class:`~OpenGLContext.context.Context` holds one as ``self.sceneLoader``,
sharing the context's ``self.renderQueue``; a program with no context builds its
own and calls :meth:`SceneLoader.poll`.

    def OnInit(self):
        self.load_request = self.sceneLoader.load('model.glb', on_loaded=self.showModel)

    def showModel(self, request):
        self.sg = SceneGraph(children=[request.result.group])

Sources are strings.  The format is chosen from the source's name, from its
content type or from ``format=``, through the adapters registered under
:class:`OpenGLContext.plugins.Adapter` (:mod:`OpenGLContext.loaders.formats`),
so a format registered by a third party -- a game's levels, say -- loads
through the same call.  What comes
back is what the format's own loader produces -- a ``GLTFScene`` for glTF, a
``SceneGraph`` for VRML97 -- and the loader decides nothing about what is done
with it.

The slow part of showing a model is the download and the decode, and neither
touches GL: they produce plain data -- numpy arrays, decoded images.  So they
run on a worker while the render loop keeps drawing, and only the result crosses
back to the render thread, where the scenegraph is built and the geometry and
textures are uploaded.  **Nothing a worker does may touch GL.**

Requests are independent: any number may be in flight, each is delivered once
when it finishes, and one that fails reports through its own ``on_failed``
without disturbing the others.  A program that wants only the newest of a
sequence -- paging through a catalogue faster than it downloads -- keeps the
request it made last and calls :meth:`LoadRequest.cancel` on it before making
the next; a cancelled request is never delivered.

A request announces itself three ways: the callbacks it was made with, the
signals :data:`SCENE_LOADING`, :data:`SCENE_LOADED` and :data:`SCENE_FAILED`
sent through :mod:`pydispatch` with the loader as sender and ``request=``, and
the request's own state.  Callbacks and signals both run on the render thread, from the queue, before the
frame's idle hook.
"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional

from pydispatch import dispatcher

from OpenGLContext.events.renderqueue import DEFER, RenderQueue
from OpenGLContext.loaders.formats import (
    UnknownSourceType, adapter_for, adapter_named,
)

if TYPE_CHECKING:
    from OpenGLContext.loaders.readers import SceneReader

log = logging.getLogger(__name__)

__all__ = ['LoadRequest', 'SceneLoader', 'SCENE_FAILED', 'SCENE_LOADED',
           'SCENE_LOADING', 'SCENE_MARK', 'SCENE_WAIT_SECONDS']

#: Sent when a request is made.
SCENE_LOADING = 'scene-loading'
#: Sent when a finished request is delivered.
SCENE_LOADED = 'scene-loaded'
#: Sent when a request that raised is delivered.
SCENE_FAILED = 'scene-failed'

#: How long a replayed session waits for a load the recording already had, in
#: seconds.  Long enough for a level that took seconds to read the first time;
#: bounded because a replay is diagnostic equipment and may not hang on a load
#: that never arrives.
SCENE_WAIT_SECONDS = 30.0

#: What delivering a loaded scene is written down as in a session recording, and
#: what a replay holds the delivery until the recorded frame of.  A level
#: arrives when the disk and the decoder are finished with it, which is not the
#: same frame twice: a session in which it appeared three frames early is one
#: where every recorded input after it was given to a world that had already
#: started.  See :mod:`OpenGLContext.telemetry`.
SCENE_MARK = 'scene-mounted'

#: A request's states.  ``loading`` until the worker finishes, then ``loaded``
#: or ``failed`` until it is delivered; ``cancelled`` is final.
LOADING, LOADED, FAILED, CANCELLED = 'loading', 'loaded', 'failed', 'cancelled'

#: What a callback is given: the request, whose ``result`` or ``error`` is set.
Callback = Callable[['LoadRequest'], Any]


class LoadRequest:
    """One load: what was asked for, how it stands, and what came of it.

    Made by :meth:`SceneLoader.load` and :meth:`SceneLoader.submit`.

    ``label``
        What is being loaded, in words, for whatever the program shows meanwhile.
    ``source``
        The path or URL asked for; None for a document in memory or a
        :meth:`~SceneLoader.submit`.
    ``reader``
        The :class:`~OpenGLContext.loaders.readers.SceneReader` that
        reads it, one per request and kept for the scene's life -- a streamed
        dataset's runtime is on it -- or None for a ``submit``.
    ``result``
        What the format's loader produced, once ``state`` is ``loaded``.
    ``error``
        The exception, once ``state`` is ``failed``.
    ``state``
        ``loading``, ``loaded``, ``failed`` or ``cancelled``.
    """

    def __init__(self, label: str, source: Optional[str] = None,
                 reader: Optional[SceneReader] = None,
                 on_loaded: Optional[Callback] = None,
                 on_failed: Optional[Callback] = None) -> None:
        self.label = label
        self.source = source
        self.reader = reader
        self.on_loaded = on_loaded
        self.on_failed = on_failed
        self.state = LOADING
        self.result: Any = None
        self.error: Optional[BaseException] = None
        #: Whether the request has been handed to its callbacks.
        self.delivered = False
        self._finished = threading.Event()

    def __repr__(self) -> str:
        return '<%s %r %s>' % (type(self).__name__, self.label, self.state)

    @property
    def cancelled(self) -> bool:
        """Whether :meth:`cancel` was called before the request was delivered."""
        return self.state == CANCELLED

    @property
    def done(self) -> bool:
        """Whether the worker has finished, whatever came of it."""
        return self._finished.is_set()

    def cancel(self) -> None:
        """Drop this request: its worker runs on, but nothing is delivered.

        A read cannot be interrupted, so a cancelled download still completes
        in the background and its result is discarded.  Cancelling a request
        already delivered does nothing.
        """
        if self.state in (LOADING, LOADED, FAILED) and not self.delivered:
            self.state = CANCELLED

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until the worker has finished; False if ``timeout`` ran out.

        Finishing is not delivery: the callbacks run when the render queue is next
        run.  For a script or a test that has no loop to run it.
        """
        return self._finished.wait(timeout)


class SceneLoader:
    """Loads scenes on worker threads and delivers them on the render thread.

    ``owner`` is the context the loader serves, or None.  It is asked to redraw
    when a load starts and when one is delivered, and a context that is
    recording or replaying a session (:mod:`OpenGLContext.telemetry`) has the
    delivery held to the frame it was recorded on.

    ``queue`` is where a finished load is delivered from: the context's
    :class:`~OpenGLContext.events.renderqueue.RenderQueue`, which its main loop
    runs before the idle hook.  Given none, the loader makes one of its own and
    :meth:`poll` runs it.
    """

    #: How long a replayed session waits for a load the recording had by now.  A
    #: field rather than the constant, so an application that knows its loads
    #: are quick can say so.
    sceneWaitSeconds: float = SCENE_WAIT_SECONDS

    def __init__(self, owner: Any = None, queue: Optional[RenderQueue] = None) -> None:
        self._owner = owner
        self._queue = queue if queue is not None else RenderQueue()
        self._queue.before_run(self._waitIfOverdue)
        self._lock = threading.Lock()
        #: Requests not yet delivered, oldest first; a cancelled one is pruned
        #: when next looked at.
        self._active: list[LoadRequest] = []
        self._closed = False
        self._delivered = 0

    # -- asking -------------------------------------------------------------
    def load(self, source: str | bytes | os.PathLike[str], *,
             format: Optional[str] = None, name: str = '',
             content_type: Optional[str] = None, label: str = '',
             options: Any = None, reader: Optional[SceneReader] = None,
             on_loaded: Optional[Callback] = None,
             on_failed: Optional[Callback] = None) -> LoadRequest:
        """Read a file, a URL or a document in memory in the background.

        ``source`` is a path or an http(s) URL, or the bytes of a document.
        ``format`` names a registered reader (``'gltf'``, ``'vrml97'``,
        ``'obj'``, ``'tiles3d'``, or one registered since); without it the
        format comes from ``content_type`` where there is one, then from the
        source's name, then from looking inside a local file.  Bytes have no
        name of their own, so ``name`` says what they would be called as a
        file -- ``'chair.glb'`` -- which chooses the format and is the base the
        document's relative references resolve against.

        ``options`` are given to the reader's ``configure`` before it reads, for
        a format with settings of its own.  ``reader`` is a reader to use
        instead of choosing one, for a program that keeps it to ask more of it
        later -- a streamed dataset's runtime is on its reader.  ``on_loaded``
        and ``on_failed`` are called with the request when it is delivered; a
        failure with no ``on_failed`` is logged.

        Raises :class:`~OpenGLContext.loaders.formats.UnknownSourceType` at once,
        before anything is started, for a source that no reader opens or bytes
        of no stated format.
        """
        request, produce = self._prepare(
            source, format, name, content_type, label, options, reader,
            on_loaded, on_failed)
        return self._start(request, produce)

    def load_now(self, source: str | bytes | os.PathLike[str], *,
                 format: Optional[str] = None, name: str = '',
                 content_type: Optional[str] = None, label: str = '',
                 options: Any = None,
                 reader: Optional[SceneReader] = None) -> LoadRequest:
        """Read a source on this thread, as :meth:`load` reads it on a worker.

        For a program that has to have the scene before it goes on -- a capture
        that must see the model it is about to photograph.  Returns the finished
        request, with no callbacks and no signals; what the reader raises is
        raised.
        """
        request, produce = self._prepare(
            source, format, name, content_type, label, options, reader,
            None, None)
        request.result = produce()
        request.state = LOADED
        request.delivered = True
        request._finished.set()
        return request

    def submit(self, produce: Callable[[], Any], *, label: str = '',
               on_loaded: Optional[Callback] = None,
               on_failed: Optional[Callback] = None) -> LoadRequest:
        """Run ``produce`` in the background; its return value is the result.

        For what no registered format reads: a scene built from several files,
        a generator.  ``produce`` takes no arguments and **must not touch GL**.
        """
        return self._start(LoadRequest(label, on_loaded=on_loaded,
                                       on_failed=on_failed), produce)

    def _prepare(self, source: str | bytes | os.PathLike[str],
                 format: Optional[str], name: str, content_type: Optional[str],
                 label: str, options: Any, chosen: Optional[SceneReader],
                 on_loaded: Optional[Callback],
                 on_failed: Optional[Callback]) -> tuple[LoadRequest, Callable[[], Any]]:
        """Choose and configure the reader; the request and what reads it."""
        content: Optional[bytes] = None
        path: Optional[str] = None
        if isinstance(source, (bytes, bytearray, memoryview)):
            content = bytes(source)
        else:
            path = os.fsdecode(source)
        hint = name if content is not None else path or ''
        if chosen is not None:
            reader = chosen
        elif format:
            reader = adapter_named(format)
        elif hint or content_type:
            reader = adapter_for(hint, content_type)
        else:
            raise UnknownSourceType(
                'bytes need a format= or a name= to say what they are')
        if content is not None and not reader.accepts_content:
            raise UnknownSourceType(
                'the %r reader reads from a path or a URL, not from memory'
                % (reader.name,))
        if options is not None:
            reader.configure(options)

        def produce() -> Any:
            if content is not None:
                return reader.read_content(content, name)
            return reader.read(path or '')

        request = LoadRequest(label or os.path.basename(hint) or 'scene',
                              source=path, reader=reader,
                              on_loaded=on_loaded, on_failed=on_failed)
        log.warning("Request to load: %s", path)
        return request, produce

    def _start(self, request: LoadRequest, produce: Callable[[], Any]) -> LoadRequest:
        if self._closed:
            raise RuntimeError('this SceneLoader is closed')

        def worker() -> None:
            result, error = None, None
            try:
                result = produce()
            except Exception as err:    # an unreachable model must not kill the thread
                error = err
            with self._lock:
                if request.state != LOADING:
                    request._finished.set()
                    return
                request.result, request.error = result, error
                request.state = FAILED if error is not None else LOADED
            request._finished.set()
            self._queue.call(self._deliver, request)

        with self._lock:
            self._active.append(request)
        self._send(SCENE_LOADING, request)
        self._redraw()
        threading.Thread(target=worker, name='scene-load', daemon=True).start()
        return request

    # -- what is going on ---------------------------------------------------
    @property
    def loading(self) -> bool:
        """Whether any request is still being read by a worker."""
        with self._lock:
            return any(request.state == LOADING for request in self._active)

    @property
    def pending(self) -> tuple[LoadRequest, ...]:
        """The requests made and neither delivered nor cancelled, oldest first."""
        with self._lock:
            self._active = [r for r in self._active if not r.cancelled]
            return tuple(self._active)

    def cancel_all(self) -> None:
        """Cancel every request that has not been delivered."""
        with self._lock:
            for request in self._active:
                request.cancel()
            self._active.clear()

    def close(self) -> None:
        """Cancel what is pending and refuse further requests.

        Workers still reading run to the end and their results are discarded.
        Called when the owning context releases its window.
        """
        self._closed = True
        self.cancel_all()
        self._owner = None

    # -- delivering ---------------------------------------------------------
    def poll(self) -> int:
        """Run the queue this loader delivers through; how many it delivered.

        A context's main loop runs its queue itself, so only a program with no
        loop calls this, after :meth:`LoadRequest.wait`.
        """
        before = self._delivered
        self._queue.run()
        return self._delivered - before

    def _deliver(self, request: LoadRequest) -> Any:
        """Hand a finished request to its callbacks, from the render queue.

        **A replayed session mounts each on the frame it was mounted on.**  A
        load finishes when the disk and the decoder are finished with it, so a
        scene that is ready early is held until the recording's own frame for
        it, by deferring the call; see :data:`SCENE_MARK`.
        """
        if request.cancelled or self._closed:
            return None
        if not self._deliveryDue():
            return DEFER
        with self._lock:
            if request in self._active:
                self._active.remove(request)
            request.delivered = True
            self._delivered += 1
        loaded = request.state == LOADED
        callback = request.on_loaded if loaded else request.on_failed
        if callback is not None:
            callback(request)
        elif not loaded:
            log.error('could not load %s: %s', request.label, request.error)
        self._send(SCENE_LOADED if loaded else SCENE_FAILED, request)
        self._markDelivered(request)
        self._redraw()
        return None

    def _send(self, signal: str, request: LoadRequest) -> None:
        dispatcher.send(signal=signal, sender=self, request=request)

    def _redraw(self) -> None:
        trigger = getattr(self._owner, 'triggerRedraw', None)
        if trigger is not None:
            trigger(1)

    # -- recording when it happened ------------------------------------------
    def _deliveryDue(self) -> bool:
        """Whether a finished load may be delivered on this frame.

        Now, unless this session is a replay that has not yet reached the frame
        the recording delivered one on.  Asked of the owner rather than of the
        telemetry package, since an owner that is not a
        :class:`~OpenGLContext.context.Context`, or no owner, has no session and
        is never held up.
        """
        reached = getattr(self._owner, 'reachedMark', None)
        return True if reached is None else bool(reached(SCENE_MARK))

    def _waitIfOverdue(self) -> None:
        """Wait for a load a replayed recording had already delivered by now.

        A load takes what it takes, and the frames drawn meanwhile are whatever
        the machine managed: a session that spent 57 frames reading a level
        replays in 66 of them, and every recorded input after that is nine
        frames out of step.  So a replay that has reached the frame the scene
        was delivered on stops drawing and waits for it.

        Bounded (:attr:`sceneWaitSeconds`), and a wait that runs out is a
        warning and a session that carries on: a replay is diagnostic equipment
        and does not get to hang on a load that never arrives.
        """
        overdue = getattr(self._owner, 'overdueMark', None)
        if overdue is None or not overdue(SCENE_MARK):
            return
        with self._lock:
            waiting = next((r for r in self._active if r.state == LOADING), None)
        if waiting is None or waiting.wait(self.sceneWaitSeconds):
            return
        log.warning('waited %gs for %r, which the recorded session had by this '
                    'frame; the replay goes on without it',
                    self.sceneWaitSeconds, waiting.label)

    def _markDelivered(self, request: LoadRequest) -> None:
        """Write down that a scene was delivered on this frame, for a replay."""
        mark = getattr(self._owner, 'mark', None)
        if mark is not None:
            mark(SCENE_MARK, label=request.label, loaded=request.state == LOADED)
