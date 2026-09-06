#!/usr/bin/env python
'''Context functionality within the PyGame environment
'''

#test and import pygame
try:
    import pygame
    from pygame.locals import *
    import pygame.key
    import pygame.display
except ImportError:
    raise ImportError("The pygame package is required for the Pygame GL Context")
if pygame.ver < '1.1':
    raise ImportError("Pygame v1.1 or greater is required for the Pygame GL Context")

#import opengl stuff
from OpenGL.GL import *
from OpenGLContext.context import Context
from OpenGLContext.events import pygameevents
from OpenGLContext.looptrace import LoopTrace
import logging
log = logging.getLogger( __name__ )

#: How many events one loop iteration will take from SDL's queue before
#: rendering anyway.  A burst of pointer motion can arrive faster than frames
#: are drawn, and a loop that drained the whole queue would never reach the
#: draw while the hand kept moving.
EVENT_BUDGET = 200

class PygameContext(
    pygameevents.EventHandlerMixin,
    Context,
):
    """Context sub-class providing basic API support under PyGame

    Unlike most of the windowing APIs, PyGame requires you to write
    an explicit event handler loop, we provide a default loop method
    called MainLoop.
    """
    #: What the swap interval was set to when the window was made, so a later
    #: change to the field can be recognised and reported.
    _vsyncApplied = None
    #: Set when the loop should end; a quit event raises it, and MainLoop
    #: watches it so the display is still up when the caches are told.
    _finished = False

    def __init__(self, definition=None, **named):
        #init pygame
        pygame.display.init()
        # Resolved before the display mode is set, since the profile, version
        # and buffer sizes below all come from it -- see
        # Context.resolveDefinition.
        definition = self.resolveDefinition( definition, **named )
        self.contextDefinition = definition
        self.screen = self.pygameDisplayMode( definition )
        pygame.display.set_caption(definition.title or self.getApplicationName())
        pygame.key.set_repeat(500,30)
        Context.__init__ (self, definition)
        # The surface's own size, not the requested one: a window filling the
        # screen was given the desktop's resolution instead of what it asked
        # for, and a viewport from the request would leave a border undrawn.
        self.ViewPort(*self.screen.get_size())

    def pygameFlagsFromDefinition( cls, definition ):
        """Setup the various non-initialising flags, return init flags"""
        set = pygame.display.gl_set_attribute
        if definition.depthBuffer > -1:
            set( GL_DEPTH_SIZE, definition.depthBuffer )
        if definition.stencilBuffer > -1:
            set( GL_STENCIL_SIZE, definition.stencilBuffer )
        if definition.accumulationBuffer > -1:
            set( GL_ACCUM_ALPHA_SIZE, definition.accumulationBuffer )
            set( GL_ACCUM_RED_SIZE, definition.accumulationBuffer )
            set( GL_ACCUM_GREEN_SIZE, definition.accumulationBuffer )
            set( GL_ACCUM_BLUE_SIZE, definition.accumulationBuffer )
        if definition.multisampleBuffer > -1 and definition.multisampleSamples > -1:
            set( GL_MULTISAMPLEBUFFERS, definition.multisampleBuffer )
            set( GL_MULTISAMPLESAMPLES, definition.multisampleSamples )
        if definition.stereo > -1:
            set( GL_STEREO, definition.stereo )
        # Set OpenGL profile (core vs compatibility) via SDL2
        # SDL_GL_CONTEXT_PROFILE_MASK constants:
        #   SDL_GL_CONTEXT_PROFILE_CORE = 1
        #   SDL_GL_CONTEXT_PROFILE_COMPATIBILITY = 2
        profile = getattr(definition, 'profile', 'compatibility')
        if profile == 'core':
            set( pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE )
            # Set minimum version for core profile
            version = getattr(definition, 'version', (3, 3))
            if version is not None and len(version) >= 2 and version[0] >= 3:
                set( pygame.GL_CONTEXT_MAJOR_VERSION, int(version[0]) )
                set( pygame.GL_CONTEXT_MINOR_VERSION, int(version[1]) )
        elif profile == 'compatibility':
            set( pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_COMPATIBILITY )
        return cls.pygameWindowFlags( definition )
    pygameFlagsFromDefinition = classmethod( pygameFlagsFromDefinition )
    def pygameWindowFlags( cls, definition ):
        """The creation flags this definition asks SDL for.

        Reads the definition and the rendering options, and nothing of SDL's
        state, so the choice can be examined without a display to open a window
        on.  :meth:`pygameFlagsFromDefinition` is this plus the GL attributes,
        which do go to SDL and so need it initialised.
        """
        # SDL takes "do not map it" as a creation flag.  See
        # renderoptions.hidden_window: rendering and reading back are
        # unaffected, and a suite of GL scripts should not take over the
        # screen of whoever is running it.
        from OpenGLContext import renderoptions
        hidden = pygame.HIDDEN if renderoptions.hidden_window() else 0
        # Borderless rather than a mode switch: SDL then leaves the desktop
        # resolution alone, which is what a window filling the screen is being
        # asked for.  See renderoptions.fullscreen_window.
        filling = (pygame.FULLSCREEN | pygame.NOFRAME
                   if renderoptions.fullscreen_window(definition) else 0)
        if definition.doubleBuffer:
            return DOUBLEBUF|RESIZABLE|hidden|filling
        else:
            return RESIZABLE|hidden|filling
    pygameWindowFlags = classmethod( pygameWindowFlags )
    def pygameDisplayMode( self, definition=None ):
        """Open (or re-open) the SDL window this context draws into

        **Calling this again destroys the GL context**, and with it every
        texture, buffer and program the engine's caches hold, so it belongs to
        opening a window and to nothing else.  A resizable SDL2 window follows
        the user's drag without being re-made; see :meth:`PygameWindowResized`.
        """
        if definition is None:
            definition = self.contextDefinition
        from OpenGLContext import renderoptions
        # A size of (0,0) is SDL's "whatever the desktop is at", which is the
        # resolution a window filling the screen wants; asking for the
        # definition's size instead would letterbox it.
        size = ((0, 0) if renderoptions.fullscreen_window(definition)
                else tuple([int(i) for i in definition.size]))
        self._vsyncApplied = self.wantsVSync( definition )
        # SDL takes the thread as it makes the context, and a thread another
        # window system's context is holding is refused -- fatally, on the GLX
        # side.  See Context.releaseForeignContext.
        self.releaseForeignContext()
        self.screen = pygame.display.set_mode(
            size,
            OPENGL | self.pygameFlagsFromDefinition( definition ),
            vsync=1 if self._vsyncApplied else 0,
        )
        return self.screen
    def CallVirtual(self, name, *args, **namedarguments):
        "Call a potentially undefined method"
        func = getattr(self, name, lambda *x, **y:1)
        return func( *args, **namedarguments)


    def SwapBuffers (self):
        "flip opengl doublebuffers"
        pygame.display.flip()


    def _glHandle(self):
        """The GL context handle the caches and PyOpenGL key on.

        SDL owns the context and does not name it, so it is read from the
        platform with the window current -- which for pygame is any time the
        display is up, since it holds one context.
        """
        from OpenGLContext import contextresources
        return contextresources.context_key()

    def setCurrent(self, blocking=1):
        """Take the OpenGL focus.

        SDL holds one context and it is always current, so there is nothing to
        bind; what this adds is telling PyOpenGL which context that is, so its
        per-context dispatch table is this window's.

        **Nothing is released here**, unlike every other backend.  SDL offers no
        way to make its context current again, so letting go of it would be
        letting go for good; the one release pygame can afford is before the
        context is made (see :meth:`pygameDisplayMode`).
        """
        Context.setCurrent(self, blocking)
        self.bindContextResources(self._glHandle())

    ### window-level settings
    def wantsVSync( self, definition=None ):
        """Whether this definition asks to wait for the display's refresh"""
        from OpenGLContext import renderoptions
        source = self if definition is None else definition
        return renderoptions.flag(
            source, 'vsync',
            not renderoptions.env_flag('OPENGLCONTEXT_NO_VSYNC', False))

    def applyVSync( self, definition=None ):
        """Answer that the swap interval cannot be changed for a live context

        SDL settles it when the window is made (see
        :meth:`pygameDisplayMode`), and re-making the window would take the GL
        context and everything in it with it -- so a change is reported and
        takes effect the next time the program runs.
        """
        if self.wantsVSync( definition ) != self._vsyncApplied:
            log.info(
                "vsync is settled when the SDL window is made; the change "
                "takes effect in a new window"
            )
        return False

    def setFullscreen( self, fullscreen ):
        """Fill the screen, or go back to the window this context opened with

        SDL swaps the window between the two without re-making the GL context,
        so nothing the engine has uploaded is lost.
        """
        if self.screen is None:
            return False
        surface = pygame.display.get_surface()
        already = bool(surface and (surface.get_flags() & pygame.FULLSCREEN))
        if bool(fullscreen) == already:
            return True
        # SDL remembers the windowed size across the trip and puts it back, so
        # there is nothing to restore here.
        pygame.display.toggle_fullscreen()
        self.ViewPort(*pygame.display.get_window_size())
        self.triggerRedraw(1)
        return True

    def settingsChanged( self ):
        """Re-apply the window-level settings a changed definition affects."""
        from OpenGLContext import renderoptions
        self.applyVSync()
        self.setFullscreen(renderoptions.fullscreen_window(self))
        Context.settingsChanged(self)

    def setPointerCapture( self, capture ):
        """Grab and hide the pointer for a mouse-look movement mode

        SDL's *relative* mode is the one that reports unbounded motion: the
        pointer stops moving and only the deltas continue, so a view can go on
        turning past the edge of the screen.  The grab keeps the events coming
        while the pointer would have been over another window.
        """
        if self.screen is None:
            return False
        capture = bool(capture)
        self._pointerGrabbed = capture
        pygame.event.set_grab(capture)
        pygame.mouse.set_visible(not capture)
        relative = getattr(pygame.mouse, 'set_relative_mode', None)
        if relative is not None:
            relative(capture)
        forget = getattr(self, 'forgetPointerOrigin', None)
        if forget is not None:
            # Where the pointer is means something different on each side of
            # this, so the first report afterwards establishes a position
            # rather than arriving as one flick of the view.
            forget()
        return True

    ### the loop
    def MainLoop( self ):
        """Run until the window is closed

        One render per iteration, whatever arrived: a burst of input -- a
        mouse-drag rotate, say -- then coalesces into a single frame instead of
        forcing a full render per event.
        """
        self.deferRedraw = True
        renderedFirst = False
        # A private trace when a subclass has cleared setupLoopTrace's: a
        # diagnostic must never be the reason a loop will not run.
        trace = self.loopTrace or LoopTrace()
        try:
            while self.screen is not None and not self._finished:
                renderedFirst = self._loopIteration( trace, renderedFirst )
        finally:
            # A loop left while it was still slow -- a closed window, a Ctrl-C
            # -- holds an episode nobody has written, and what it holds of the
            # last few seconds is what a session that ended badly is worth
            # reading for.
            if self.stallJournal is not None:
                self.stallJournal.close()
            self.stopTelemetry('mainloop-ended')
            self.releaseWindow()

    def _loopIteration( self, trace, renderedFirst ):
        """One pass of the main loop, timed phase by phase

        Answers the new renderedFirst, which is the only state an iteration
        carries into the next one.  The phases exist because the frame counter
        can only see the render: an application whose simulation lives in
        ``OnIdle`` stutters without the counter ever dipping, and the phase
        that names the culprit is the difference between a rendering problem
        and a simulation one.  See :mod:`OpenGLContext.looptrace`.
        """
        with trace.iteration():
            with trace.phase('poll'):
                self.pumpWindowEvents()
                if self._finished:
                    # Left for MainLoop to act on rather than closing the
                    # display here: the release belongs in one place, and it
                    # needs the display still up to take the GL names with it.
                    return renderedFirst
            with trace.phase('repeats'):
                self.pumpKeyRepeats()
            with trace.phase('idle'):
                self.OnIdle()
            # Wait briefly so input and time events accumulate before
            # rendering; bounded by drawPollTimeout, so this phase can go up
            # but never far up.
            with trace.phase('wait'):
                self.redrawRequest.wait( self.drawPollTimeout )
            with trace.phase('draw'):
                # force=1 when a redraw is pending; force=0 still runs the
                # event cascade so animations advance, and renders only if they
                # produced a visible change.
                if self.redrawRequest.isSet() or not renderedFirst:
                    renderedFirst = True
                    self.OnDraw( force = 1 )
                else:
                    self.OnDraw( force = 0 )
        return renderedFirst

    def pumpWindowEvents( self ):
        """Dispatch what SDL has queued; see Context.pumpWindowEvents

        A handler that answers falsely is one saying the loop should end --
        the quit event, the window's close button -- and that is recorded
        rather than answered here, so this means "the events were delivered"
        on every backend alike.
        """
        for _count in range( EVENT_BUDGET ):
            event = pygame.event.poll()
            if not event.type:
                break
            name = 'Pygame' + pygame.event.event_name(event.type)
            if not self.CallVirtual(name, event):
                self._finished = True
                break
        return True

    def OnQuit(self, event=None):
        """Let go of this window's GL objects, then end the application

        The release happens **here** rather than after the loop because
        :meth:`Context.OnQuit` ends the process with ``os._exit``: nothing
        after it runs, no ``finally`` and no ``atexit`` hook, and closing the
        window or pressing Escape is the path a user actually takes.
        """
        self.releaseWindow()
        return Context.OnQuit(self, event)

    def releaseWindow( self ):
        """Drop this context's GL objects and let the display go

        The engine's caches own GL objects in this context, so they have to be
        let go before it is destroyed rather than left for a later window that
        SDL hands the same identifier.  Calling this twice is harmless; the
        second call has nothing to do.
        """
        if self.screen is None:
            return
        self.screen = None
        self.releaseContextResources( self._glHandle() )
        pygame.display.quit()

    def PygameQuit(self, event):
        """Return a value indicating that the MainLoop should exit"""
        return 0

    def PygameWindowClose(self, event):
        """The window's own close button, which SDL reports separately"""
        return 0

    def PygameWindowResized(self, event):
        """Follow the window's new size with the viewport

        Nothing is re-made: SDL2 resizes a ``RESIZABLE`` window in place, and
        calling ``set_mode`` again to "apply" the size would build a new GL
        context and strand every object the engine has uploaded into the old
        one.
        """
        width, height = pygame.display.get_window_size()
        self.contextDefinition.size = (width, height)
        self.ViewPort(width, height)
        self.CallVirtual('OnResize', width, height)
        self.triggerRedraw(1)
        return 1

    def PygameVideoResize(self, event):
        """The older spelling of a resize, for an SDL1-era event queue"""
        return self.PygameWindowResized(event)

    def PygameVideoExpose(self, event):
        """The window has been uncovered and wants drawing again"""
        self.triggerRedraw(1)
        return 1

    def ContextMainLoop( cls, *args, **named ):
        """Initialise the context and start the mainloop"""
        instance = cls( *args, **named )
        if instance.contextDefinition.profileFile:
            # profiling run...
            import cProfile
            return cProfile.runctx(
                "instance.MainLoop()",
                globals(),
                locals(),
                instance.contextDefinition.profileFile
            )
        return instance.MainLoop()
    ContextMainLoop = classmethod( ContextMainLoop )


if __name__ == '__main__':
    from drawcube import drawCube
    class TestContext(PygameContext):
        def Render(self, mode):
            glTranslated(0, 0, -3)
            glRotated(30, 1, 0, 0)
            glRotated(40, 0, 1, 0)
            drawCube()
    TestContext.ContextMainLoop()
