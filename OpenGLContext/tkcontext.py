"""Context functionality in a Tkinter window

Tkinter ships with CPython, so this is the backend a project can use without
adding a GUI toolkit to its dependencies.  The window is an
:class:`OpenGL.Tk.GLFrame` -- an ordinary ``tkinter.Frame`` with a GL context of
its own, made through the window system's own API -- so a context here can
either own the whole window or sit as one widget beside an application's other
controls.  See ``OpenGL/Tk/`` in PyOpenGL and ``plans/TK-WIDGET.md`` there.

To put a view inside an existing Tk application, build the context with the
frame that is to hold it::

    context = TkInteractiveContext(parent=someFrame)
    context.frame.pack(fill='both', expand=True)

and drive it from the application's own ``mainloop`` by calling
:meth:`TkContext.loopIteration` from an ``after`` callback, or let
:meth:`TkContext.MainLoop` own the loop when the context is the application.
"""

import logging
import tkinter

from OpenGLContext.context import Context
from OpenGLContext.events import tkevents
from OpenGLContext.looptrace import LoopTrace

try:
    from OpenGL.Tk import ContextAttributes, GLFrame
except ImportError as err:              # pragma: no cover - an old PyOpenGL
    raise ImportError(
        "The Tk GL widget is required for the Tk GL Context; it needs "
        "PyOpenGL 4 or newer, and tkinter: %s" % (err,)
    ) from err

log = logging.getLogger(__name__)

#: How many milliseconds Tk waits between the frames :meth:`TkContext.MainLoop`
#: drives.  Small enough that the loop is not the thing limiting the frame
#: rate; the loop's own wait is what paces it.
FRAME_INTERVAL = 1


def attributesFromDefinition(definition):
    """The GL context a ``ContextDefinition`` asks for, as PyOpenGL's Tk widget
    wants it stated

    Every field that describes the *window* rather than the rendering; the
    rendering features (shadows, bloom, IBL and the rest) are read from the
    definition by the render passes themselves.

    An accumulation buffer has no equivalent here -- it is absent from a core
    profile, and the widget asks the window system for a modern context -- and
    is reported rather than silently ignored, since a caller asking for one is
    asking for something this window will not have.
    """
    if definition.accumulationBuffer > -1:
        log.warning(
            "The Tk backend provides no accumulation buffer; ignoring the %d "
            "bits requested", definition.accumulationBuffer,
        )
    version = tuple(int(value) for value in definition.version)
    return ContextAttributes(
        profile=definition.profile,
        version=version if version[0] else None,
        doubleBuffer=bool(definition.doubleBuffer),
        alphaSize=8 if definition.alpha else 0,
        depthSize=definition.depthBuffer if definition.depthBuffer > -1 else 24,
        stencilSize=max(0, definition.stencilBuffer),
        samples=max(0, definition.multisampleSamples),
        stereo=definition.stereo > 0,
        debug=bool(definition.debug),
    )


class TkContext(tkevents.EventHandlerMixin, Context):
    """Implementation of the Context API in a Tkinter widget

    The widget is an :class:`OpenGL.Tk.GLFrame` held as ``self.frame`` rather
    than something this class *is*: a ``Context`` is not a Tk widget, and a
    host application that wants the view in its own layout needs the frame to
    pack, not the context.

    Rendering is driven from a Tk timer rather than from expose events: the
    engine's frame is an event cascade followed by a render, only the cascade
    always runs -- animations, timers and queued events live there -- and only
    sometimes is there anything new to draw.
    """

    #: The GLFrame this draws into.
    frame = None
    #: The toplevel this context created, or None where it was given a parent
    #: to sit inside.
    root = None
    #: Set when the loop should end.
    _finished = False
    _renderedFirst = False
    _frameJob = None
    #: True while the pointer is hidden and being warped back to the middle of
    #: the window for a mouse-look mode.
    _pointerGrabbed = False
    #: Where the pointer was last warped to, so the movement the warp itself
    #: generates can be told from a real one.
    _pointerWarpedTo = None

    def __init__(self, definition=None, parent=None, **named):
        """Create the widget, its GL context, and the engine on top of them

        definition -- ContextDefinition (or a dictionary of its fields)
            describing the window to create
        parent -- a Tk widget to put the view inside, or None to make a
            toplevel of this context's own
        named -- individual definition fields, overriding the definition
        """
        # Resolved before the widget exists: profile, version, buffers and size
        # are all context-creation parameters, so a class that declares a
        # definition has to be consulted now rather than by Context.__init__.
        definition = self.resolveDefinition(definition, **named)
        self.contextDefinition = definition

        width, height = [int(value) for value in definition.size]
        if parent is None:
            self.root = parent = tkinter.Tk()
            self.root.title(definition.title or self.getApplicationName())
            self.root.geometry('%dx%d' % (width, height))
            self.root.protocol('WM_DELETE_WINDOW', self.OnQuit)
        self.frame = GLFrame(
            parent, attributes=attributesFromDefinition(definition),
            width=width, height=height,
        )
        self.frame.pack(fill=tkinter.BOTH, expand=tkinter.YES)
        self.frame.focus_set()
        # A window has no native handle until the window system has mapped it,
        # so there is nothing to make a context against before then; OnInit
        # runs inside this constructor as it does under every other backend,
        # and it needs a current context to build textures and shaders in.
        self.frame.waitForMap()
        self.applyHidden()
        self.applyVSync(definition)
        Context.__init__(self, definition)
        self.ViewPort(self.frame.winfo_width(), self.frame.winfo_height())

    ### the window's own settings
    def applyHidden(self):
        """Take the window off the screen where the environment asked for that

        ``OPENGLCONTEXT_HIDDEN`` is for a capture subprocess and for a suite of
        GL scripts that should not take over the screen of whoever is running
        it.  It is applied **after** the context exists: a Tk window that was
        never mapped has no native window for one to be made against, so this
        is a window that appeared and then went rather than one that never
        appeared.  Rendering and reading back are unaffected, since both happen
        in the back buffer.

        A context sitting inside somebody else's application is left alone: the
        window is not this context's to withdraw.
        """
        from OpenGLContext import renderoptions

        if self.root is not None and renderoptions.hidden_window():
            self.root.withdraw()
            self.root.update()
            return True
        return False

    def applyVSync(self, definition=None):
        """Wait for the display's refresh, or don't (ContextDefinition.vsync)

        Answers whether the interval was set; the window system's own
        swap-control extension is what does it, and there is not one
        everywhere.
        """
        from OpenGLContext import renderoptions

        source = self if definition is None else definition
        wanted = renderoptions.flag(
            source, 'vsync',
            not renderoptions.env_flag('OPENGLCONTEXT_NO_VSYNC', False))
        if self.frame is None:
            return False
        return bool(self.frame.setSwapInterval(1 if wanted else 0))

    def setFullscreen(self, fullscreen):
        """Fill the screen, or go back to the window this context opened with

        Tk moves a toplevel between the two without re-making anything, so the
        GL context and everything loaded into it survive the trip.  A context
        inside somebody else's window has no toplevel of its own to fill the
        screen with, and says so.
        """
        if self.root is None:
            return False
        if bool(fullscreen) == self.isFullscreen():
            return True
        self.root.attributes('-fullscreen', bool(fullscreen))
        self.root.update_idletasks()
        self.triggerRedraw(1)
        return True

    def isFullscreen(self):
        """Whether this window is filling the screen now

        Tk answers the attribute as 0 or 1, and some builds answer it as the
        *string* '0' -- which is true.  The window manager is what actually
        honours the request, so a session with none reports False however often
        it is asked.
        """
        if self.root is None:
            return False
        try:
            return bool(int(self.root.attributes('-fullscreen')))
        except (ValueError, TypeError, tkinter.TclError):
            return False

    def settingsChanged(self):
        """Re-apply the window-level settings a changed definition affects."""
        from OpenGLContext import renderoptions

        self.applyVSync()
        self.setFullscreen(renderoptions.fullscreen_window(self))
        Context.settingsChanged(self)

    def setPointerCapture(self, capture):
        """Hide the pointer and keep it in the window, for a mouse-look mode

        Tk has no relative-motion mode, so the pointer is warped back to the
        middle of the widget after every movement -- which is what makes the
        motion unbounded, since a pointer that stops at the edge of the screen
        is a view that stops turning there.  The warp arrives back as an
        ordinary movement and is recognised and dropped; see
        :meth:`OpenGLContext.events.tkevents.EventHandlerMixin.tkOnMouseMove`.
        """
        if self.frame is None:
            return False
        capture = bool(capture)
        self._pointerGrabbed = capture
        self._pointerWarpedTo = None
        self.frame.configure(cursor='none' if capture else '')
        if capture:
            self.frame.grab_set()
        else:
            self.frame.grab_release()
        forget = getattr(self, 'forgetPointerOrigin', None)
        if forget is not None:
            # Where the pointer is means something different on each side of
            # this, so the first report afterwards establishes a position
            # rather than arriving as one flick of the view.
            forget()
        if capture:
            self.recentrePointer()
        return True

    def recentrePointer(self):
        """Put the pointer back in the middle of the widget, if it is grabbed"""
        if not self._pointerGrabbed or self.frame is None:
            return
        middle = (self.frame.winfo_width() // 2,
                  self.frame.winfo_height() // 2)
        self._pointerWarpedTo = middle
        # Tk's own way of moving the pointer: a warping motion event, which the
        # server acts on rather than merely reporting.
        self.frame.event_generate('<Motion>', warp=True,
                                  x=middle[0], y=middle[1])

    def pointerWarpEcho(self, x, y):
        """Whether this movement is the one :meth:`recentrePointer` caused

        A movement the program made itself is not motion the user asked for:
        left in, it cancels out every real movement and mouse-look never turns.
        """
        if self._pointerWarpedTo is None:
            return False
        echo = (int(x), int(y)) == self._pointerWarpedTo
        if echo:
            self._pointerWarpedTo = None
        return echo

    ### Context API
    def setupCallbacks(self):
        """Bind the widget's input events to this context's handlers"""
        frame = self.frame
        frame.bind('<KeyPress>', self.tkOnKeyDown)
        frame.bind('<KeyRelease>', self.tkOnKeyUp)
        frame.bind('<FocusOut>', self.tkOnFocusOut)
        for number in (1, 2, 3, 4, 5):
            frame.bind('<Button-%d>' % (number,), self.tkOnMouseButton)
            frame.bind('<ButtonRelease-%d>' % (number,), self.tkOnMouseRelease)
        frame.bind('<Motion>', self.tkOnMouseMove)
        frame.bind('<MouseWheel>', self.tkOnMouseWheel)
        frame.bind('<Configure>', self.tkOnConfigure)
        # The widget's own drawing is this context's, so the frame's
        # expose-driven render is replaced rather than left to draw a scene it
        # knows nothing about.
        frame.redraw = self.drawFrame
        frame.reshape = self.OnResize

    def tkOnConfigure(self, event):
        """Follow the widget's new size with the viewport"""
        self.OnResize(int(event.width), int(event.height))

    def drawFrame(self):
        """What the widget draws: one engine frame, without the swap

        The frame's own ``render`` makes the context current and swaps
        afterwards, and ``Context.OnDraw`` is what goes between.
        """
        self.OnDraw(force=1)

    def setCurrent(self, blocking=1):
        """Take the OpenGL focus"""
        Context.setCurrent(self, blocking)
        if self.frame is not None:
            self.releaseForeignContext()
            self.frame.makeCurrent()
            self.bindContextResources(self._glHandle())

    def _glHandle(self):
        """The GL context handle the caches and PyOpenGL key on

        The widget's context object is not it: what identifies a context to
        PyOpenGL is the platform's own handle, and asking for it is what the
        platform layer does.  Read after the widget is current, which is the
        only moment the answer is about this window.
        """
        from OpenGLContext import contextresources

        return contextresources.context_key()

    def SwapBuffers(self):
        """Present the rendered frame"""
        if self.frame is not None:
            self.frame.swapBuffers()

    def OnIdle(self, *arguments):
        """Animation hook for the Tk loop

        The default ``Context.OnIdle`` renders through ``drawPoll``, which
        would double up with the render this backend's own loop performs.
        Demos that animate override this to call ``triggerRedraw``.
        """
        return 0

    def OnResize(self, width, height):
        """Take the new widget size"""
        self.ViewPort(int(width), int(height))
        self.triggerRedraw(1)

    def OnQuit(self, event=None):
        """Let go of this window's GL objects, then end the application

        The release happens **here** rather than after the loop because
        :meth:`Context.OnQuit` ends the process with ``os._exit``: nothing
        after it runs, no ``finally`` and no ``atexit`` hook, and closing the
        window or pressing Escape is the path a user actually takes.

        A context embedded in somebody else's Tk application is a view inside
        it, and closing a view must not take the host program down: there, this
        releases the context and returns.
        """
        self._finished = True
        self.releaseWindow()
        if self.root is None:
            return 0
        return Context.OnQuit(self, event)

    def releaseWindow(self):
        """Drop this context's GL objects and let the widget go

        The engine's caches own GL objects in this context, so they have to be
        let go before it is destroyed rather than left for a later window that
        the driver hands the same identifier.  Calling this twice is calling it
        once.
        """
        frame, self.frame = self.frame, None
        if frame is None:
            return
        self.stopFrameTimer()
        if frame.makeCurrent():
            self.releaseContextResources(self._glHandle())
        else:
            self.releaseContextResources(None)
        frame.destroyContext()
        root, self.root = self.root, None
        if root is not None:
            try:
                root.destroy()
            except tkinter.TclError:
                pass                    # the interpreter is already going

    ### the loop
    def startFrameTimer(self):
        """Begin the timer that drives the render loop"""
        if self._frameJob is None and self.frame is not None:
            self._frameJob = self.frame.after(FRAME_INTERVAL, self._frameStep)
        return self._frameJob

    def stopFrameTimer(self):
        """Stop the render loop's timer"""
        job, self._frameJob = self._frameJob, None
        if job is not None and self.frame is not None:
            try:
                self.frame.after_cancel(job)
            except tkinter.TclError:
                pass                    # the interpreter is already going

    def _frameStep(self):
        self._frameJob = None
        if self._finished or self.frame is None:
            return
        self.loopIteration()
        if not self._finished and self.frame is not None:
            self._frameJob = self.frame.after(FRAME_INTERVAL, self._frameStep)

    def pumpWindowEvents(self):
        """Dispatch what Tk has queued; see Context.pumpWindowEvents"""
        if self.frame is None:
            return False
        try:
            self.frame.update()
        except tkinter.TclError:
            return False                # the interpreter is already going
        return True

    def loopIteration(self):
        """One pass of the render loop, timed phase by phase

        Public, because a host application that owns the Tk main loop drives
        the view by calling this from its own ``after`` callback.

        The phases exist because the frame counter can only see the render: an
        application whose simulation lives in ``OnIdle`` stutters without the
        counter ever dipping, and the phase that names the culprit is the
        difference between a rendering problem and a simulation one.  See
        :mod:`OpenGLContext.looptrace`.  Tk's own event dispatch is what calls
        this, so there is no polling phase to charge for.
        """
        if self._finished or self.frame is None or self.frame.context is None:
            return False
        trace = self.loopTrace or LoopTrace()
        with trace.iteration():
            with trace.phase('repeats'):
                self.pumpKeyRepeats()
            with trace.phase('idle'):
                self.OnIdle()
            with trace.phase('draw'):
                # force=1 when a redraw is pending; force=0 still runs the
                # event cascade so animations advance, and renders only if they
                # produced a visible change.
                if self.redrawRequest.is_set() or not self._renderedFirst:
                    self._renderedFirst = True
                    self.OnDraw(force=1)
                else:
                    self.OnDraw(force=0)
        return True

    def MainLoop(self):
        """Run Tk's event loop with this context rendering inside it"""
        if self.root is None:
            raise RuntimeError(
                "This context was built inside somebody else's window, so the "
                "main loop is theirs to run; call loopIteration from it")
        # We drive rendering ourselves, so suppress the synchronous
        # in-callback renders triggerPick/triggerRedraw would otherwise do.  A
        # burst of input events then coalesces into a single render per
        # iteration instead of one full render per event.
        self.deferRedraw = True
        self.startFrameTimer()
        try:
            self.root.mainloop()
        finally:
            self.stopFrameTimer()
            # A loop left while it was still slow -- a closed window, a Ctrl-C
            # -- holds an episode nobody has written, and what it holds of the
            # last few seconds is what a session that ended badly is worth
            # reading for.
            if self.stallJournal is not None:
                self.stallJournal.close()
            self.stopTelemetry('mainloop-ended')
            self.releaseWindow()

    @classmethod
    def ContextMainLoop(cls, *args, **named):
        """Create the context and run it as an application"""
        instance = cls(*args, **named)
        if instance.contextDefinition.profileFile:
            import cProfile

            return cProfile.runctx(
                "instance.MainLoop()",
                globals(),
                locals(),
                instance.contextDefinition.profileFile,
            )
        return instance.MainLoop()


if __name__ == "__main__":
    from OpenGL.GL import (
        GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, glClear, glClearColor,
    )

    class TestRenderer(TkContext):
        def Render(self, mode=None):
            TkContext.Render(self, mode)
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    TestRenderer.ContextMainLoop()
