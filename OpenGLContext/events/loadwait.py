"""How long a bounded run waits for loads before it counts frames -- no GL

A capture or an auto-exit counts the frames of the scene it is to draw, so
the frames drawn while a scene, an Inline or a texture is still arriving are
not among them (:meth:`OpenGLContext.context.Context.loadsPending`). A scene
that keeps loading -- streamed tiles, a url that never answers -- would hold
the count still for ever, so the wait has a limit: :attr:`LoadWait.limit`
seconds from the first frame it is asked about, ``OPENGLCONTEXT_LOAD_WAIT``
where the context's own is not set. :attr:`LoadWait.waited` says the limit
was reached.
"""
from __future__ import annotations

__all__ = ['DEFAULT_LIMIT', 'LoadWait']

#: Seconds a bounded run waits for loads, where nothing names another.
DEFAULT_LIMIT = 30.0


class LoadWait:
    """Whether a bounded run is still waiting for loads, given whether
    anything is loading and the time"""

    def __init__(self, limit: float = DEFAULT_LIMIT) -> None:
        self.limit = float(limit)
        #: When it was first asked; None before.
        self.started: float | None = None
        #: Whether the limit was reached with loads still under way.
        self.waited = False

    def pending(self, loading: bool, now: float) -> bool:
        """Whether to keep waiting at `now`, with `loading` saying whether any
        load is under way; false from the moment the limit is reached"""
        if self.started is None:
            self.started = now
        if not loading or self.waited:
            return False
        if now - self.started >= self.limit:
            self.waited = True
            return False
        return True
