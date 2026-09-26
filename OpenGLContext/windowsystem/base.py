"""What a context asks of the toolkit it draws in

A :class:`~OpenGLContext.context.Context` holds one :class:`WindowSystem`, made
for it as it is built and gone with it.  The window system owns everything that
differs between toolkits: the window and its GL context, making that current,
presenting a frame, the toolkit's own input callbacks and the loop that
delivers them.  The context owns everything that does not: the definition, the
render passes, events once they are OpenGLContext events, the camera and the
scene.

The toolkit's input arrives at the window system's own methods, which build
the events in :mod:`OpenGLContext.events` and hand them to the context
(:meth:`~OpenGLContext.context.Context.ProcessEvent`,
:meth:`~OpenGLContext.context.Context.addPickEvent`), so an application's
context never shares a namespace with a toolkit's.

A window system is written by subclassing this and registering the subclass
(:class:`OpenGLContext.plugins.WindowSystem`, or an entry point in the
``OpenGLContext.windowsystems`` group).  What it must provide is marked
abstract; everything else has a default that says "this toolkit cannot",
which the context passes on to its caller as False.  ``docs/backends.rst``
has a worked example.
"""
from __future__ import annotations

import abc
import logging
from collections.abc import Hashable
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from OpenGLContext import contextresources, renderoptions

if TYPE_CHECKING:
    from OpenGLContext.context import Context
    from OpenGLContext.contextdefinition import ContextDefinition
    from OpenGLContext.looptrace import LoopTrace

log = logging.getLogger(__name__)


def wantsVSync(definition: Any) -> bool:
    """Whether ``definition`` asks to wait for the display's refresh."""
    return renderoptions.flag(
        definition, 'vsync',
        not renderoptions.env_flag('OPENGLCONTEXT_NO_VSYNC', False))


class WindowSystem(abc.ABC):
    """A window, and the GL context in it, on one toolkit

    Attributes:

        context -- the :class:`~OpenGLContext.context.Context` this window
            system draws for.  The two are one object's two halves: each
            holds the other, and they go together.
        window -- the toolkit's own window or widget, as the toolkit knows it,
            once :meth:`open` has made it; None before then and after
            :meth:`release`.  What an application packs, sizes or parents.
    """

    #: The name this window system is registered under.
    name: ClassVar[str] = ''
    #: True where ``glutInit`` has been called, so GLUT's bitmap fonts can be
    #: drawn: a GLUT call without GLUT set up ends the process.
    providesGLUT: ClassVar[bool] = False
    #: True where nothing is on screen and nothing delivers input: the loop
    #: draws :attr:`~OpenGLContext.context.Context.frameCount` frames and
    #: returns.
    offscreen: ClassVar[bool] = False
    #: Whether a context here can be put inside a toolkit container given as
    #: ``parent``; one that cannot refuses a parent rather than ignoring it.
    acceptsParent: ClassVar[bool] = False
    #: Whether the loop takes the toolkit's queued events itself, as a
    #: ``poll`` phase, and waits for input to gather before each frame.  A
    #: toolkit whose own dispatcher calls the loop has neither.
    pollsEvents: ClassVar[bool] = True

    window: Any = None

    def __init__(self, context: Context) -> None:
        self.context = context
        #: Set when the loop should end.
        self.finished = False
        #: Whether the loop has drawn the frame it always draws first.
        self.renderedFirst = False

    # -- lifetime ----------------------------------------------------------

    @abc.abstractmethod
    def open(self, definition: ContextDefinition, parent: Any = None) -> bool:
        """Make the window and its GL context, current on this thread.

        ``definition`` has been resolved: its profile, version, buffers, size
        and title are what to open with.  ``parent`` is the toolkit container
        to open inside, where :attr:`acceptsParent` says there can be one.

        Answers whether GL is ready for the context's ``OnInit`` now.  Where
        it is not -- a window the compositor has not mapped yet -- the window
        system calls :meth:`~OpenGLContext.context.Context.completeInit`
        itself once it is.
        """

    @abc.abstractmethod
    def release(self) -> None:
        """Let the window, and the GL objects in it, go.

        The context's caches are told first, with this window's GL context
        current, through
        :meth:`~OpenGLContext.context.Context.releaseContextResources`: it is
        the moment they can still delete what they hold rather than merely
        forget it.  Calling this twice is calling it once.
        """

    def abandon(self) -> None:  # noqa: B027 an optional hook; doing nothing is the default
        """Give back what :meth:`open` made, after the context failed to build.

        No cache has seen this GL context, so none is told: announcing its loss
        would drop whichever context is current instead.  Most toolkits have
        nothing to do here that the process ending will not do.
        """

    def quit(self) -> bool:
        """Stop the loop and let the window go; answer whether the process ends.

        A context that *is* the application ends it.  A view inside somebody
        else's application answers False, and the host program carries on.
        """
        self.finished = True
        self.release()
        return True

    # -- current and presenting --------------------------------------------

    @abc.abstractmethod
    def makeCurrent(self) -> Optional[Hashable]:
        """Make this window's GL context current; answer its handle.

        The handle is what :meth:`glHandle` answers once the context is
        current, None where there is no window to make current.
        """

    def glHandle(self) -> Optional[Hashable]:
        """The GL context handle the engine's caches and PyOpenGL key on.

        The platform's own handle, rather than the toolkit's object for it:
        what identifies a context to PyOpenGL is what the binding API calls
        it.  Read with this window's context current, which is the only moment
        the answer is about this window.
        """
        return contextresources.current_handle()

    @abc.abstractmethod
    def swap(self) -> None:
        """Present the frame just drawn."""

    @abc.abstractmethod
    def drawableSize(self) -> tuple[int, int]:
        """The size of what is drawn into, in the pixels the viewport counts.

        On a scaled display a window's size in the toolkit's logical units
        and its framebuffer's size in pixels differ, and a viewport from the
        first leaves part of the second undrawn.
        """

    def resize(self, width: int, height: int) -> tuple[int, int]:
        """Draw at a new size from now on; answer the size drawn at.

        A window has already been resized by the time it says so, and this is
        a formality.  A pbuffer has a fixed size, and makes a new one.
        """
        return width, height

    def applyVSync(self, definition: Any) -> bool:
        """Wait for the display's refresh or don't, as ``definition`` says.

        Answers whether the interval was set.  One that is part of a surface
        format settled when the context was made cannot change for a live
        context, and answers False.
        """
        return False

    # -- requests of the window --------------------------------------------

    def setFullscreen(self, fullscreen: bool) -> bool:
        """Fill the screen, or go back to a window; answer whether it happened."""
        return False

    def settingsChanged(self, definition: Any) -> None:
        """Re-apply what an edited definition says about the window itself."""
        self.applyVSync(definition)
        self.setFullscreen(renderoptions.fullscreen_window(definition))

    def setPointerCapture(self, capture: bool) -> bool:
        """Hide and grab the pointer for mouse-look; answer whether it happened.

        Mouse-look needs unbounded motion: a pointer that stops at the edge of
        the screen is a view that stops turning there.
        """
        return False

    def setPointerShape(self, name: str) -> bool:
        """Show the pointer ``name``; False for one this toolkit has not got.

        The names are :data:`OpenGLContext.context.CURSORS`, and ``''`` is the
        ordinary pointer.
        """
        return False

    def emitKey(self, key: Any, state: int, modifiers: Any) -> None:  # noqa: B027 an optional hook; doing nothing is the default
        """Send one key transition the toolkit did not report.

        For the releases focus loss never delivers and the repeats a platform
        does not make; see
        :class:`OpenGLContext.events.eventhandlermixin.HeldKeyMixin`.  A
        window system with no keyboard has none to send.
        """

    # -- the loop -----------------------------------------------------------

    def bindCallbacks(self) -> None:  # noqa: B027 an optional hook; doing nothing is the default
        """Connect the toolkit's input callbacks to this window system.

        Called once, while the context is being built, after its event
        managers exist and before its default key bindings are made.
        """

    def pump(self) -> bool:
        """Let the toolkit deliver what it has queued; False where it cannot.

        For a program driving its own loop rather than calling ``MainLoop``.
        A window that is never pumped is one some platforms decide has stopped
        responding, and it never sees a keystroke or a resize.
        """
        return False

    def running(self) -> bool:
        """Whether the loop should go round again."""
        return self.window is not None and not self.finished

    def loopIteration(self, trace: Optional[LoopTrace] = None) -> bool:
        """One pass of the loop, timed phase by phase; False once it is over.

        Public, because a host application that owns its toolkit's loop drives
        the view by calling this from a timer of its own.

        The phases exist because the frame counter can only see the render:
        an application whose simulation lives in ``OnIdle`` stutters without
        the counter ever dipping, and the phase that names the culprit is the
        difference between a rendering problem and a simulation one.  See
        :mod:`OpenGLContext.looptrace`.
        """
        from OpenGLContext.looptrace import LoopTrace

        context = self.context
        if not self.running():
            return False
        # A private trace when a subclass has cleared setupLoopTrace's: a
        # diagnostic must never be the reason a loop will not run.
        trace = trace or context.loopTrace or LoopTrace()
        with trace.iteration():
            if self.pollsEvents:
                # With deferRedraw set, input only flags a redraw and pick
                # events coalesce down to the latest position.
                with trace.phase('poll'):
                    self.pump()
                if not self.running():
                    return False
            with trace.phase('repeats'):
                context.pumpKeyRepeats()
            with trace.phase('idle'):
                context.OnIdle()
            if self.pollsEvents:
                # Bounded by drawPollTimeout, so this phase can go up but never
                # far up: a large 'wait' is a quiet loop, never a stalled one.
                with trace.phase('wait'):
                    context.redrawRequest.wait(context.drawPollTimeout)
            with trace.phase('draw'):
                # force=1 when a redraw is pending; force=0 still runs the
                # event cascade so animations advance, and renders only if
                # they produced a visible change.
                if context.redrawRequest.is_set() or not self.renderedFirst:
                    self.renderedFirst = True
                    context.OnDraw(force=1)
                else:
                    context.OnDraw(force=0)
        return True

    def mainLoop(self) -> Any:
        """Run until the window closes, one frame per pass.

        One render per pass whatever arrived, so a burst of input -- a drag,
        say -- coalesces into a single frame instead of one per event.
        """
        from OpenGLContext.looptrace import LoopTrace

        context = self.context
        context.deferRedraw = True
        trace = context.loopTrace or LoopTrace()
        try:
            while self.running():
                self.loopIteration(trace)
        finally:
            context.closeJournals('mainloop-ended')
            self.release()

    @classmethod
    def run(cls, contextClass: type[Context], *args: Any, **named: Any) -> Any:
        """Make a context of ``contextClass`` here, and run its main loop.

        What :meth:`~OpenGLContext.context.Context.ContextMainLoop` calls.  A
        toolkit that needs an application object before it can make a window
        -- wx's ``App``, Qt's ``QGuiApplication``, GLUT's ``glutInit`` --
        overrides this to make it first.
        """
        return contextClass(*args, **named).profiledMainLoop()

    def __repr__(self) -> str:
        return '<%s %s>' % (self.__class__.__name__,
                            'open' if self.window is not None else 'closed')
