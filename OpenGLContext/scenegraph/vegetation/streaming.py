"""Work a camera-following field needs, done on a worker thread.

A field that follows the camera -- ground cover, a forest's near geometry --
recomputes what it draws when the camera has moved far enough. That work is
numpy and touches no GL, so it can run beside the frame rather than inside it.
:class:`BackgroundCompute` runs it: :meth:`~BackgroundCompute.request` hands
the worker the newest arguments, the worker computes, and
:meth:`~BackgroundCompute.drain`, called once a frame on the render thread,
hands the newest result to ``apply``, which does the GL-side staging. numpy
releases the interpreter lock across its array work, so the worker overlaps
the frame. What is drawn trails the camera by the frames the work takes; the
fade bands at each field's edges are wider than that.

``compute`` touches no GL, and nothing ``apply`` changes; ``apply`` runs on the
render thread and is the only side that changes nodes.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, Optional

log = logging.getLogger(__name__)

__all__ = ['BackgroundCompute']


class BackgroundCompute:
    """A worker thread computing the newest request, and its newest result.

    ``compute(*args) -> payload`` runs on the worker; ``apply(payload)`` runs
    in :meth:`drain`. A request made while an earlier one has not started
    replaces it; ``merge(old_args, new_args) -> args``, where given, decides
    what the replacement asks for, for a caller whose requests each ask for
    part of the work.

    A request whose ``compute`` raises is logged, and ``failed(args, error)``,
    where given, is called with it in the next :meth:`drain`, so a caller that
    moved on when it asked can ask again.
    """

    def __init__(self, compute: Callable[..., Any], apply: Callable[[Any], None],
                 merge: Optional[Callable[[tuple, tuple], tuple]] = None,
                 name: str = 'background-compute',
                 failed: Optional[Callable[[tuple, BaseException], None]] = None,
                 ) -> None:
        self._compute = compute
        self._apply = apply
        self._merge = merge
        self._failed = failed
        self._cv = threading.Condition()
        self._request: Optional[tuple] = None
        self._result: Any = None
        self._have_result = False
        self._failures: list[tuple[tuple, BaseException]] = []
        #: Whether the worker is computing a request now.
        self.busy = False
        self._stop = False
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    @property
    def alive(self) -> bool:
        """Whether the worker thread is running."""
        return self._thread.is_alive()

    def request(self, *args: Any) -> None:
        """Ask for ``compute(*args)``, replacing a request not yet started."""
        with self._cv:
            if self._request is not None and self._merge is not None:
                args = tuple(self._merge(self._request, args))
            self._request = args
            self._cv.notify_all()

    def drain(self) -> bool:
        """Apply the newest result, on the calling thread; whether there was one.

        Failures since the last drain go to ``failed`` first, in order.
        """
        with self._cv:
            failures, self._failures = self._failures, []
            have = self._have_result
            payload, self._result, self._have_result = self._result, None, False
        if self._failed is not None:
            for args, error in failures:
                self._failed(args, error)
        if not have:
            return bool(failures)
        self._apply(payload)
        return True

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Wait until every request has been computed; whether that happened in time.

        The results are not applied: :meth:`drain` does that.
        """
        with self._cv:
            return self._cv.wait_for(
                lambda: self._request is None and not self.busy, timeout)

    def stop(self) -> None:
        """Stop the worker and wait for it to finish what it is computing.

        Called on the worker itself, from inside ``compute``, it stops the
        worker once that returns.
        """
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while True:
            with self._cv:
                self._cv.wait_for(lambda: self._request is not None or self._stop)
                if self._stop:
                    return
                args, self._request = self._request, None
                self.busy = True
            assert args is not None
            try:
                payload = self._compute(*args)
            except Exception as error:
                log.exception('background recompute failed')
                with self._cv:
                    self._failures.append((args, error))
                    self.busy = False
                    self._cv.notify_all()
                continue
            with self._cv:
                self._result, self._have_result = payload, True
                self.busy = False
                self._cv.notify_all()
