"""Context functionality using the GLFW windowing API

GLFW provides modern OpenGL context creation with support for:
- Core and compatibility profiles
- OpenGL version selection
- Debug contexts
- Forward compatibility
"""
try:
    import glfw
except ImportError:
    raise ImportError("The glfw package is required for the GLFW GL Context. Install with: pip install glfw")

from OpenGL.GL import *
from OpenGLContext import contextresources
from OpenGLContext.context import Context
from OpenGLContext.events import glfwevents
from OpenGLContext.looptrace import LoopTrace
import logging
import warnings

log = logging.getLogger(__name__)


def fullscreenMonitor(definition):
    """The monitor a window built from ``definition`` should fill, or None.

    ``OPENGLCONTEXT_HIDDEN`` wins over the request, because GLFW ignores the
    visibility hint for a full-screen window: a capture subprocess that asked
    for both would map itself over the display of whoever started the run.
    A machine with no monitor attached answers None for the same reason it
    answers no size -- there is nothing to fill.
    """
    from OpenGLContext import renderoptions
    if not renderoptions.fullscreen_window(definition):
        return None
    return glfw.get_primary_monitor() or None


class GLFWContext(
    glfwevents.EventHandlerMixin,
    Context,
):
    """Implementation of Context API under GLFW

    GLFW provides modern OpenGL context creation with better support
    for OpenGL core profiles, version selection, and debug contexts.
    """

    window = None
    #: Where and how big the window is when it is not filling the screen, as
    #: (x, y, width, height).  A position of None means the platform has never
    #: placed this window and should choose.
    _windowedGeometry = (None, None, 300, 300)

    def __init__(self, definition=None, **named):
        # Resolved before the window exists: profile, version, buffers and size
        # are all window-creation parameters, so a class that declares a
        # definition has to be consulted now rather than by Context.__init__.
        definition = self.resolveDefinition(definition, **named)
        self.contextDefinition = definition

        # Initialize GLFW
        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")

        # Set window hints from definition
        self._setWindowHints(definition)

        # Create window
        width, height = [int(i) for i in definition.size]
        title = definition.title or self.getApplicationName()
        # Kept for the trip back out of full-screen, which has to be told a
        # size and a position: the definition's size is the only statement of
        # how big a window this application wanted.
        self._windowedGeometry = (None, None, width, height)
        monitor = fullscreenMonitor(definition)
        if monitor is not None:
            width, height = self._fillMonitor(monitor)
        self.window = glfw.create_window(width, height, title, monitor, None)

        if not self.window:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")

        # Make context current before calling Context.__init__
        glfw.make_context_current(self.window)

        # Before the base class has stored it, so the definition is passed
        # rather than read back off self: two references to the same object is
        # one too many, and only one of them belongs to this class.
        self.applyVSync(definition)

        # Call base Context initialization
        Context.__init__(self, definition)

        # Set initial viewport from the real framebuffer size, not the requested
        # window size. Under HiDPI/fractional scaling (e.g. Wayland) the
        # framebuffer is measured in pixels and differs from the window's screen
        # coordinates; using definition.size would leave an undrawn border.
        fbWidth, fbHeight = glfw.get_framebuffer_size(self.window)
        self.ViewPort(fbWidth, fbHeight)

    def settingsChanged(self):
        """Re-apply the window-level settings a changed definition affects."""
        self.applyVSync()
        self.applyFullscreen()
        Context.settingsChanged(self)

    def _fillMonitor(self, monitor):
        """The size to ask for on ``monitor``, with the refresh rate to match.

        The monitor's *current* mode, so nothing switches resolution: a mode
        change is slow, it rearranges the icons on every other desktop the
        display is showing, and a game that wanted a different resolution would
        say so in its definition's size rather than by filling the screen.
        """
        mode = glfw.get_video_mode(monitor)
        glfw.window_hint(glfw.REFRESH_RATE, mode.refresh_rate)
        return int(mode.size.width), int(mode.size.height)

    def applyFullscreen(self, definition=None):
        """Match the window to what the definition now says about full-screen.

        Called when the settings screen writes the field, so a player can leave
        a full-screen game without restarting it.  Moving the window between a
        monitor and the desktop keeps the GL context and everything in it, so
        nothing is reloaded.
        """
        source = self if definition is None else definition
        self.setFullscreen(fullscreenMonitor(source) is not None)

    def setFullscreen(self, fullscreen):
        """Fill the screen, or go back to the window this context opened with."""
        if not self.window:
            return False
        # Truthiness, not ``is not None``: the binding hands back a ctypes
        # pointer either way, and the NULL one that means "windowed" is an
        # object like any other.
        already = bool(glfw.get_window_monitor(self.window))
        if bool(fullscreen) == already:
            return True
        if fullscreen:
            monitor = glfw.get_primary_monitor()
            if not monitor:
                return False
            # Wayland does not tell a client where its window is, and says so
            # by warning.  A position is the one part of this that can be done
            # without -- the size is what has to come back, and a compositor
            # that places windows itself would ignore the position anyway -- so
            # the complaint is not worth showing a player.
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                try:
                    x, y = glfw.get_window_pos(self.window)
                except Exception:
                    x = y = None
            width, height = glfw.get_window_size(self.window)
            self._windowedGeometry = (x, y, width, height)
            width, height = self._fillMonitor(monitor)
            glfw.set_window_monitor(self.window, monitor, 0, 0, width, height,
                                    glfw.get_video_mode(monitor).refresh_rate)
        else:
            x, y, width, height = self._windowedGeometry
            # A window that was born full-screen has no remembered position, so
            # it is handed back to the platform to place rather than pinned to
            # the top-left corner of a display it may not be on.
            if x is None:
                x, y = 100, 100
            glfw.set_window_monitor(self.window, None, x, y, width, height,
                                    glfw.DONT_CARE)
        # A monitor swap re-creates the drawable underneath us on some
        # platforms, so the swap interval has to be asked for again.
        self.applyVSync()
        return True

    def applyVSync(self, definition=None):
        """Wait for the display's refresh, or don't (ContextDefinition.vsync).

        Off uncaps the frame rate, which is what a benchmark wants. It also
        matters on Wayland, where a vsynced swap blocks on a compositor frame
        callback that a leaked GL context from an abnormally-terminated process
        can wedge -- so the test suite turns it off and one flaky run cannot
        stall every later swap.

        Called again when the setting changes, so a settings screen's Apply
        takes effect without a restart.  ``definition`` is for the call made
        while the window is being built, before the base class has stored it.
        """
        from OpenGLContext import renderoptions
        source = self if definition is None else definition
        wanted = renderoptions.flag(
            source, 'vsync',
            not renderoptions.env_flag('OPENGLCONTEXT_NO_VSYNC', False))
        try:
            glfw.swap_interval(1 if wanted else 0)
        except Exception:
            log.debug("this GLFW build would not set the swap interval",
                      exc_info=True)

    def _setWindowHints(self, definition):
        """Apply ContextDefinition to GLFW window hints"""
        # Reset to defaults
        glfw.default_window_hints()

        # Double buffering (GLFW default is True)
        if definition.doubleBuffer:
            glfw.window_hint(glfw.DOUBLEBUFFER, glfw.TRUE)
        else:
            glfw.window_hint(glfw.DOUBLEBUFFER, glfw.FALSE)

        # Depth buffer
        if definition.depthBuffer > -1:
            glfw.window_hint(glfw.DEPTH_BITS, definition.depthBuffer)
        else:
            glfw.window_hint(glfw.DEPTH_BITS, 24)  # sensible default

        # Stencil buffer
        if definition.stencilBuffer > -1:
            glfw.window_hint(glfw.STENCIL_BITS, definition.stencilBuffer)

        # Accumulation buffer (deprecated in modern GL, but GLFW supports it)
        if definition.accumulationBuffer > -1:
            bits = definition.accumulationBuffer
            glfw.window_hint(glfw.ACCUM_RED_BITS, bits)
            glfw.window_hint(glfw.ACCUM_GREEN_BITS, bits)
            glfw.window_hint(glfw.ACCUM_BLUE_BITS, bits)
            glfw.window_hint(glfw.ACCUM_ALPHA_BITS, bits)

        # Color buffer alpha. GLFW defaults to 8 alpha bits; compositors that
        # honor destination alpha (Wayland/EGL, forwarded GL) then treat
        # cleared pixels as transparent, bleeding through windows behind ours.
        # Only request a window alpha channel when explicitly asked for.
        if definition.alpha:
            glfw.window_hint(glfw.ALPHA_BITS, 8)
        else:
            glfw.window_hint(glfw.ALPHA_BITS, 0)

        # Multisampling
        if definition.multisampleSamples > 0:
            glfw.window_hint(glfw.SAMPLES, definition.multisampleSamples)

        # Stereo
        if definition.stereo > 0:
            glfw.window_hint(glfw.STEREO, glfw.TRUE)

        # OpenGL version
        if definition.version[0] > 0:
            glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, int(definition.version[0]))
            glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, int(definition.version[1]))

        # Profile (core vs compatibility)
        if definition.profile == "core":
            glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
            glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
        elif definition.profile == "compatibility" and definition.version[0] >= 3:
            # Only set compatibility profile for GL 3.0+
            glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_COMPAT_PROFILE)

        # Debug context
        if definition.debug:
            glfw.window_hint(glfw.OPENGL_DEBUG_CONTEXT, glfw.TRUE)

        # Make window resizable
        glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)

        # Offscreen/hidden window (OPENGLCONTEXT_HIDDEN) for captures. A mapped
        # Wayland surface serializes on the compositor's frame callback, so back-
        # to-back capture subprocesses stall each other's SwapBuffers; a hidden
        # window renders + glReadPixels the same but never maps, so captures don't
        # contend. Pair with OPENGLCONTEXT_NO_VSYNC=1 (swap_interval 0).
        from OpenGLContext import renderoptions
        if renderoptions.hidden_window():
            glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        
        # If on EGL allow for specifying the EGLDisplay
        # only practical on EGL environments...


    def setupCallbacks(self):
        """Register GLFW callbacks"""
        if self.window:
            glfw.set_key_callback(self.window, self._keyCallback)
            glfw.set_char_callback(self.window, self._charCallback)
            glfw.set_mouse_button_callback(self.window, self._mouseButtonCallback)
            glfw.set_cursor_pos_callback(self.window, self._cursorPosCallback)
            glfw.set_scroll_callback(self.window, self._scrollCallback)
            glfw.set_framebuffer_size_callback(self.window, self._framebufferSizeCallback)
            glfw.set_window_close_callback(self.window, self._windowCloseCallback)
            glfw.set_window_focus_callback(self.window, self._windowFocusCallback)

    def _keyCallback(self, window, key, scancode, action, mods):
        """GLFW key callback wrapper"""
        self.glfwOnKey(window, key, scancode, action, mods)

    def _charCallback(self, window, codepoint):
        """GLFW character callback wrapper"""
        self.glfwOnCharacter(window, codepoint)

    def _mouseButtonCallback(self, window, button, action, mods):
        """GLFW mouse button callback wrapper"""
        self.glfwOnMouseButton(window, button, action, mods)

    def _cursorPosCallback(self, window, xpos, ypos):
        """GLFW cursor position callback wrapper"""
        self.glfwOnCursorPos(window, xpos, ypos)

    def _scrollCallback(self, window, xoffset, yoffset):
        """GLFW scroll callback wrapper"""
        self.glfwOnScroll(window, xoffset, yoffset)

    def _framebufferSizeCallback(self, window, width, height):
        """GLFW framebuffer size callback wrapper"""
        self.glfwOnFramebufferSize(window, width, height)

    def _windowCloseCallback(self, window):
        """GLFW window close callback"""
        self.OnQuit()

    def _windowFocusCallback(self, window, focused):
        """Drop held-key state on focus loss (no RELEASE arrives when unfocused)."""
        if not focused:
            clear = getattr(self, 'clearHeldKeys', None)
            if clear is not None:
                clear()

    def setPointerCapture(self, capture):
        """Grab or release the pointer for a mouse-look movement mode.

        The disabled cursor is the one that reports unbounded motion: hidden
        still stops at the edge of the screen, and a view that stops turning
        there is unusable.  Raw motion is asked for where the platform has it,
        since pointer acceleration is a desktop convenience that would make how
        far a turn goes depend on how fast it started.
        """
        if not self.window:
            return False
        glfw.set_input_mode(
            self.window, glfw.CURSOR,
            glfw.CURSOR_DISABLED if capture else glfw.CURSOR_NORMAL)
        if glfw.raw_mouse_motion_supported():
            glfw.set_input_mode(self.window, glfw.RAW_MOUSE_MOTION,
                                bool(capture))
        return True

    def setCurrent(self):
        """Make this context's OpenGL context current"""
        Context.setCurrent(self)
        if self.window:
            glfw.make_context_current(self.window)

    def SwapBuffers(self):
        """Swap the front and back buffers"""
        if self.window:
            glfw.swap_buffers(self.window)

    def OnResize(self, width, height):
        """Handle window resize"""
        self.setCurrent()
        try:
            self.ViewPort(width, height)
        finally:
            self.unsetCurrent()
        self.triggerRedraw(1)

    def OnQuit(self, event=None):
        """Clean up and exit"""
        if self.window:
            glfw.set_window_should_close(self.window, True)
        return super(GLFWContext, self).OnQuit(event)

    def OnIdle(self, *arguments):
        """Animation hook for the GLFW loop.

        The default Context.OnIdle renders via drawPoll, which would double up
        with MainLoop's own OnDraw. Demos that animate override this to call
        triggerRedraw; the base behaviour here is to do nothing and let
        MainLoop drive rendering.
        """
        return 0

    def _loopIteration(self, trace, renderedFirst):
        """One pass of the main loop, timed phase by phase.

        Answers the new renderedFirst, which is the only state an iteration
        carries into the next one.

        The phases exist because the frame counter can only see the render. An
        application whose simulation lives in OnIdle stutters without the
        counter ever dipping, and the phase that names the culprit is the
        difference between a rendering problem and a simulation one. See
        OpenGLContext.looptrace.
        """
        with trace.iteration():
            # Dispatch queued GLFW callbacks; with deferRedraw set these only
            # flag a redraw and coalesce pick events (keyed by buttons/modifiers)
            # down to the latest position.
            with trace.phase('poll'):
                glfw.poll_events()

            # Synthesise key-repeat where the platform doesn't deliver it (the
            # GLFW Wayland backend in a nested compositor). No-op otherwise.
            pump = getattr(self, 'pumpKeyRepeats', None)
            if pump is not None:
                with trace.phase('repeats'):
                    pump()

            # Animation hook (overridden by animating demos to triggerRedraw).
            with trace.phase('idle'):
                self.OnIdle()

            # Wait briefly so input and time events accumulate before rendering.
            # Bounded by drawPollTimeout, so this phase can go up but never far
            # up: a large 'wait' is a quiet loop, never a stalled one.
            with trace.phase('wait'):
                self.redrawRequest.wait(self.drawPollTimeout)

            # One OnDraw per iteration. force=1 when a redraw is pending; force=0
            # still runs DoEventCascade so time events (animations) are processed
            # and only renders if they produced a visible change.
            with trace.phase('draw'):
                if self.redrawRequest.isSet() or not renderedFirst:
                    renderedFirst = True
                    self.OnDraw(force=1)
                else:
                    self.OnDraw(force=0)
        return renderedFirst

    def MainLoop(self):
        """Run the main event loop"""
        # We drive rendering ourselves, so suppress the synchronous in-callback
        # renders triggerPick/triggerRedraw would otherwise do. A burst of input
        # events (e.g. mouse-drag rotate) then coalesces into a single render per
        # iteration instead of one full render per event, which kept the display
        # lagging behind the cursor.
        self.deferRedraw = True
        renderedFirst = False
        # A private trace when a subclass has cleared setupLoopTrace's: a
        # diagnostic must never be the reason a loop will not run, and nothing
        # reads a trace that no provider can reach.
        trace = self.loopTrace or LoopTrace()

        try:
            while self.window and not glfw.window_should_close(self.window):
                renderedFirst = self._loopIteration(trace, renderedFirst)
        finally:
            # A loop left while it was still slow -- a closed window, a Ctrl-C
            # -- holds an episode nobody has written. Writing it is the
            # difference between a trace of the session and a trace of all but
            # its last, and worst, few seconds.
            if self.stallJournal is not None:
                self.stallJournal.close()
            # The same argument for the session recording: what it holds of the
            # last few seconds is exactly what a session that ended badly is
            # worth reading for.
            self.stopTelemetry('mainloop-ended')

        # Cleanup.  The engine's caches own GL objects in this context, so they
        # have to be let go before it is destroyed rather than left for a later
        # window that the driver hands the same identifier.
        if self.window:
            contextresources.context_lost()
            glfw.destroy_window(self.window)
            self.window = None
        glfw.terminate()

    def ContextMainLoop(cls, *args, **named):
        """Class method to create and run the context"""
        instance = cls(*args, **named)

        if instance.contextDefinition.profileFile:
            import cProfile
            return cProfile.runctx(
                "instance.MainLoop()",
                globals(),
                locals(),
                instance.contextDefinition.profileFile
            )

        return instance.MainLoop()

    ContextMainLoop = classmethod(ContextMainLoop)


if __name__ == "__main__":

    class TestRenderer(GLFWContext):
        def Render(self, mode=None):
            print('rendering')
            GLFWContext.Render(self, mode)
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            print('done render')

    TestRenderer.ContextMainLoop()
