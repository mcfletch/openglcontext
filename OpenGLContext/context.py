"""Abstract base class for all rendering contexts

OpenGL operates with the idea of a current context
in which OpenGL calls will operate.  This is something
a little bit more than a "window", as it includes
a number of (optional) off-screen buffers, and
a great deal of state which is manipulated by the
various OpenGL functions. (OpenGL is basically a huge
state machine).

The Context in OpenGLContext is your basic interface
to the context, and simple operation of OpenGLContext
(such as that you'll see in most of the test scripts)
can focus almost entirely on the Context object and
its various customization points.

If you wish to use the scene graph facilities of
OpenGLContext, look particularly at the abstract
function getSceneGraph, which can be overridden to
provide a particular scenegraph object to the renderer.
SceneGraph objects provide their own light, background,
and render-traversal mechanisms, which allow you to
largely ignore the Context objects.

The bulk of the actual rendering work is done by the
FlatPass (``passes/_flat.py`` and its profile subclasses
``flatcore``/``flatcompat``), which the Context selects
through ``passes.renderpass.defaultRenderPasses``. The pass
observes the scenegraph and drives the rendering callbacks
the Context exposes.
"""
from OpenGL.GL import *
from OpenGLContext import texturecache, plugins
from OpenGLContext.screenshot import ScreenshotMixin
from OpenGLContext.passes import renderpass
from vrml.vrml97 import nodetypes
from vrml import node, cache
import weakref
import os
import sys
import time
import logging

log = logging.getLogger(__name__)


def _fieldIsSet(definition, name):
    """Whether ``name`` holds a value, as opposed to resolving to its default.

    A field default is a callable the field runs on first read, so reading the
    field to find out would settle it and destroy the answer.
    """
    from vrml import protofunctions
    return protofunctions.getField(definition, name).fhas(definition)


#: How far inside its own bounding sphere the camera has to be before an
#: examine drag stops orbiting the scene's centre.  Standing well outside a
#: model, its centre is what you mean; standing in the middle of a building,
#: the far side of the room is not.
EXAMINE_INSIDE_FRACTION = 0.25
#: How far ahead of the camera to pivot when it *is* inside the scene, as a
#: fraction of the scene's radius.
EXAMINE_AHEAD_FRACTION = 0.5
#: Distance ahead to pivot when there is no scene to measure at all.
EXAMINE_PIVOT_FALLBACK = 10.0
def _distanceBetween(first, second):
    """Straight-line distance between two points, ignoring any fourth element."""
    offset = [float(a) - float(b)
              for a, b in zip(first[:3], second[:3], strict=True)]
    return (offset[0] ** 2 + offset[1] ** 2 + offset[2] ** 2) ** 0.5


#: How far outside the scene's bounding sphere a picked point may lie and still
#: be treated as part of the scene, as a multiple of its radius.  Generous: what
#: this is for is rejecting the far plane, which is an order of magnitude out.
EXAMINE_PICK_REACH = 1.5
from OpenGLContext.contextconfig import ContextConfigMixin
from OpenGLContext.ui.screen import ScreenMixin


class LockingError(Exception):
    pass


try:
    import Queue
except ImportError:
    import queue as Queue
import threading
from contextlib import nullcontext

perf = time.perf_counter if hasattr(time, "perf_counter") else time.clock
contextLock = threading.RLock()
contextThread = None


def inContextThread():
    """Return true if the current thread is the context thread"""
    if threading:
        if threading.current_thread() == contextThread:
            return 1
        elif threading.current_thread().name == contextThread.name:
            return 1
        else:
            return 0
    return 1


class Context(ScreenMixin, ScreenshotMixin, ContextConfigMixin):
    """Abstract base class on which all Rendering Contexts are based

    The Context object represents a single rendering context
    for use by the application.  This base class provides only
    the most rudimentary of application support, but sub-classes
    provide such things as navigation, and/or event handling.

    Attributes:

        sg -- OpenGLContext.scenegraph.basenodes.sceneGraph; the root of the
            node-rendering tree.  If not NULL, is used to control
            most aspects of the rendering process.
            See: getSceneGraph

        renderPasses -- callable object, normally
            OpenGLContext.passes.renderpass.defaultRenderPasses, which selects
            and caches the FlatPass that renders this Context

        alreadyDrawn -- flag which is set/checked to determine
            whether the context needs to be redrawn, see:
                Context.triggerRedraw( ... )
                Context.shouldRedraw( ... )
                Context.suppressRedraw( ... )
            for the API to use to interact with this attribute.

        viewportDimensions -- Storage for the current viewport
            dimensions, see:
                Context.ViewPort( ... )
                Context.getViewPort( ... )
            for the API used to interact with this attribute.

        drawPollTimeout -- default timeout for the drawPoll method

        currentContext -- class attribute pointing to the currently
            rendering Context instance.  This allows code called
            during a Render-pass to access the Context object.

            Note: wherever possible, use the passed render-pass's
            "context" attribute, rather than this class attribute.
            If that isn't possible, use the deprecated
            getCurrentContext function in this module.

        allContexts -- list of weak references to all instantiated
            Context objects, mostly of use for code which wants to
            refresh all contexts when shared resources/states are
            updated

        drawing -- flag set to indicate that this Context is
            currently drawing, mostly used internally

        frameCounter -- node, normally a framecounter.FrameCounter
            instance which is used to track frame rates, must have
            an addFrame method as seen in framecounter.FrameCounter,
            See setupFrameRateCounter

        loopTrace -- looptrace.LoopTrace measuring the wall-clock cost
            of a whole main-loop iteration, divided among named phases.
            The frame counter times only the inside of OnDraw and only
            for frames that changed something; a backend's loop also
            polls events and runs OnIdle, so an application whose
            simulation lives there can stutter while the frame rate
            reads healthy. See setupLoopTrace.

        telemetry -- the session recording, when one was asked for, else
            None. A whole session -- every input, every frame time, every
            exception -- written to a file that can be read back or
            replayed. See setupTelemetry and OpenGLContext.telemetry.

        extensions -- extensionmanager.ExtensionManager instance
            with which to find and initialise extensions for this
            context.
            See setupExtensionManager

        cache -- vrml.cache.Cache instance used for optimising the
            rendering of scenegraphs.
            See setupCache

        redrawRequest -- threading Event for triggering a request

        scenegraphLock -- threading Lock for blocking rendering
            from re-entering during a rendering pass

        pickEvents -- dictionary mapping event type and key to
            event object where each event requires select-render-pass
            support

        contextDefinition -- node describing the options used to
            create this context, passed in as "definition" argument
            on init, see OpenGLContext.contextdefinition.ContextDefinition
            for details.

        coreProfile -- set if the contextDefinition specifies that this
            is a core-profile-only context, that is, it does not support
            compatibility (legacy) entry points.
    """

    currentContext = None
    allContexts = []
    renderPasses = renderpass.defaultRenderPasses
    frameCounter = None
    loopTrace = None
    stallJournal = None
    telemetry = None
    contextDefinition = None
    #: The OpenGL profile a subclass needs, when that is all it has to say:
    #: ``profile = 'compatibility'`` on a demo that draws with the
    #: fixed-function pipeline.  It is applied over :attr:`contextDefinition`
    #: rather than replacing it, so a class can name its profile and still
    #: inherit the size, buffers and rendering features its base declared.
    #: ``None`` leaves the choice to the definition, and thence to
    #: ``OPENGLCONTEXT_PROFILE``.  See :meth:`resolveDefinition`.
    profile = None

    ### State flags/values
    # Set to false to trigger a redraw on the next available iteration
    alreadyDrawn = None
    drawing = None
    # When true, triggerRedraw/triggerPick only flag a redraw request rather
    # than rendering synchronously in-thread. Backends that drive their own
    # render loop (e.g. GLFW) set this so a burst of input events coalesces
    # into a single render per loop iteration instead of one render per event.
    deferRedraw = False
    viewportDimensions = (0, 0)
    drawPollTimeout = 0.01
    coreProfile = False
    # True only for backends that have called glutInit and can safely use
    # GLUT bitmap fonts. GLUT functions segfault if used without a GLUT
    # context, so font providers must consult this before selecting them.
    providesGLUT = False

    # Auto-exit support for automated testing
    # Set OPENGLCONTEXT_AUTO_EXIT_FRAMES environment variable to exit after N frames
    # Set OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR to capture screenshot before exit
    _autoExitFrames = None
    _autoExitFrameCount = 0
    _autoExitCaptureDir = None
    _autoExitClock = None

    ### Node-like attributes
    PROTO = "Context"
    DEF = "#Context"

    def __init__(self, definition=None):
        """Establish the Context working environment

        definition -- an OpenGLContext.contextdefinition.ContextDefinition
            instance which controls the context features (size, bit-depth, etc).
            If null, then use self.contextDefinition if it exists, otherwise
            create a default ContextDefinition instance.
            Alternately, can be a dictionary of key:value pairs to set on the
            default ContextDefinition to specify required parameters.

        Calls the following:

            setupThreading,
            setupExtensionManager,
            initializeEventManagers,
            setupDefaultEventCallbacks,
            setupCallbacks,
            setupCache,
            setupFontProviders,
            setupFrameRateCounter,
            setupLoopTrace,
            setupEntropy,
            setupTelemetry,
            DoInit
        """
        self.setupLogging()
        definition = self.setDefinition(definition)
        self.setupThreading()
        self.setupExtensionManager()
        self.initializeEventManagers()
        # Defaults first: a key can have only one handler, and the second
        # registration for it replaces the first.  ``setupCallbacks`` is where a
        # context says what a key should do *here*, so it has to land on top.
        self.setupDefaultEventCallbacks()
        self.setupCallbacks()
        self.allContexts.append(weakref.ref(self))
        self.pickEvents = {}
        self.eventCascadeQueue = Queue.Queue()
        self.setupCache()
        self.setupFontProviders()
        self.setupFrameRateCounter()
        self.setupLoopTrace()
        self.setupEntropy()
        self.setupTelemetry()
        self.setupAutoExit()
        self.DoInit()

    def setupAutoExit(self):
        """Setup auto-exit for automated testing.

        If OPENGLCONTEXT_AUTO_EXIT_FRAMES environment variable is set,
        the context will automatically exit after rendering that many frames.
        This enables automated testing of interactive scripts.

        If OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR is also set, a screenshot
        will be captured before exiting.
        """
        auto_exit = os.environ.get('OPENGLCONTEXT_AUTO_EXIT_FRAMES')
        if auto_exit:
            try:
                self._autoExitFrames = int(auto_exit)
                self._autoExitFrameCount = 0
                log.info(f"Auto-exit enabled: will exit after {self._autoExitFrames} frames")
            except ValueError:
                log.warning(f"Invalid OPENGLCONTEXT_AUTO_EXIT_FRAMES value: {auto_exit}")

        capture_dir = os.environ.get('OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR')
        if capture_dir:
            self._autoExitCaptureDir = capture_dir
            log.info(f"Auto-exit capture enabled: screenshots will be saved to {capture_dir}")

        self.setupAutoExitClock()

    #: Frames per second a capture run advances the world at. The value only
    #: decides which instant of an animation the capture lands on; that it is
    #: the *same* instant every run is the point.
    CAPTURE_FRAME_RATE = 60

    def setupAutoExitClock(self):
        """Advance the world a frame at a time while capturing

        A scene animated from the clock is at whatever pose the wall clock had
        reached when the capture was taken, and how long a frame takes is not
        the same twice -- so a stored reference frame is being compared against
        a different moment each run.  A capture therefore renders against
        :class:`~OpenGLContext.video.clock.FixedStepClock`, which every
        time-driven node reads (Timers and the TimeSensors that drive scenegraph
        animation alike), so each run reaches the same instant.
        """
        if self._autoExitFrames is None:
            return
        from OpenGLContext.video.clock import FixedStepClock
        self._autoExitClock = FixedStepClock(
            fps=self.CAPTURE_FRAME_RATE, start=0.0
        ).install()

    def advanceCaptureClock(self):
        """Finish a frame's worth of world time, if a capture pinned the clock"""
        if self._autoExitClock is not None:
            self._autoExitClock.advance()

    def _autoExitDraw(self):
        """Render one final frame and capture it before auto-exit.

        The auto-exit check runs at the top of OnDraw, where the context is not yet
        current and the previous frame has already been swapped to the front buffer,
        so the back buffer holds stale (often black) data. To capture the on-screen
        image we draw one more frame and read the back buffer *before* that frame's
        swap, by intercepting the single SwapBuffers that presenting it performs.
        """
        if not self._autoExitCaptureDir:
            return
        # Suppress the auto-exit branch so the forced redraw below renders normally
        # instead of recursing back into here.
        self._autoExitFrames = None
        swap = self.SwapBuffers
        captured = []

        def _captureThenSwap():
            if not captured:
                captured.append(True)
                self._autoExitCapture()
            swap()

        self.SwapBuffers = _captureThenSwap
        try:
            self.OnDraw(force=1)
        finally:
            self.SwapBuffers = swap
        if not captured:
            # Render produced no visible change, so no swap occurred and the back
            # buffer was never captured; fall back to a direct read.
            self.setCurrent()
            try:
                self._autoExitCapture()
            finally:
                self.unsetCurrent()

    def _autoExitCapture(self):
        """Write the current back buffer to the configured capture path."""
        if not self._autoExitCaptureDir:
            return
        try:
            from OpenGLContext.capture import capture_to_png
            # Use test name from environment, or fall back to class attribute or class name
            test_name = os.environ.get(
                'OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME',
                getattr(self, 'test_name', self.__class__.__name__)
            )
            filepath = os.path.join(self._autoExitCaptureDir, f"{test_name}.png")
            if capture_to_png(filepath, skip_blank=False):
                log.info(f"Auto-exit capture saved: {filepath}")
        except Exception as e:
            log.warning(f"Auto-exit capture failed: {e}")

    def setupLogging(self):
        import logging

        logging.basicConfig(level=logging.WARNING)

    @classmethod
    def resolveDefinition(cls, definition=None, **named):
        """The definition a context of this class should be created from.

        A backend calls this at the top of its ``__init__``, before it opens
        anything: the window's profile, version, buffers and size all come from
        the definition, so a class that declares one has to be consulted while
        there is still a window to configure.  Doing it here rather than in each
        backend is what keeps them from disagreeing about it.

        The order is: the ``definition`` passed in, then the one the class
        declares as :attr:`contextDefinition`, then a fresh one -- whose field
        defaults read the environment.  ``named`` sets fields on whichever of
        those it lands on.  A mapping rather than a node is read as the fields
        to set.

        A declared definition is *copied*, never handed out: a context writes
        its own size back to its definition as the window is resized, and two
        contexts of one class sharing a node means the second inherits the
        first's window size.  The copy carries only the fields the declaration
        actually set, so every other field still resolves its default when it is
        read -- an environment variable set after import reaches it as usual.
        """
        from OpenGLContext import contextdefinition

        declared = definition is None
        if declared:
            definition = cls.contextDefinition
            if definition is not None:
                definition = definition.copy()
        if definition is None:
            definition = contextdefinition.ContextDefinition(**named)
        else:
            if not isinstance(definition, contextdefinition.ContextDefinition):
                definition = contextdefinition.ContextDefinition(**definition)
            for key, value in named.items():
                setattr(definition, key, value)
        if declared and cls.profile and not _fieldIsSet(definition, 'profile'):
            definition.profile = cls.profile
            if not _fieldIsSet(definition, 'version'):
                definition.version = contextdefinition.version_for_profile(cls.profile)
        return definition

    def setDefinition(self, definition):
        """Store the definition this context was created from, and read it.

        The backend has normally resolved it already and passes it here; an
        instance that set one on itself before calling up is honoured too.
        """
        if definition is None:
            definition = self.__dict__.get('contextDefinition')
        self.contextDefinition = definition = self.resolveDefinition(definition)
        self.coreProfile = definition.profile == "core"
        return self.contextDefinition

    def DoInit(self):
        """Call the OnInit method at a time when the context is valid

        This method provides a customization point where
        contexts which do not completely initialize during
        their __init__ method can arrange to have the OnInit
        method processed after their initialization has
        completed.  The default implementation here simply
        calls OnInit directly w/ appropriate setCurrent
        and unsetCurrent calls.

        Redraws asked for while OnInit runs are **deferred**.  A forced
        triggerRedraw() draws immediately when it can, and during OnInit it can
        -- so a context that adds a HUD layer or reports its progress would
        re-enter OnDraw against a scenegraph it has not built yet.  The request
        itself is kept: the context is left needing a frame, and the first real
        one satisfies it.
        """
        self.setCurrent()
        self.deferRedraw = True
        try:
            self.OnInit()
        finally:
            self.deferRedraw = False
            self.unsetCurrent()

    ### Customisation points
    def setupCallbacks(self):
        """Establishes GUI callbacks for asynchronous event GUI systems

        Subclasses and applications will register events
        here for those event types in which they are interested.
        Most minor applications should use interactivecontext's
        abstract callbacks (which translate the GUI library's
        native events into a common event framework for all
        interactivecontexts).

        This runs **after** :meth:`setupDefaultEventCallbacks`, and a key can
        have only one handler, so a binding made here wins over the default for
        the same key.  Claiming a key the framework also binds is simply binding
        it.

        The default implementation does nothing.
        """

    def setupCache(self):
        """Setup caching strutures for content

        This includes the general compiled-geometry caches
        and the texture cache
        """
        self.textureCache = texturecache.TextureCache()
        self.cache = cache.Cache()

    def setupExtensionManager(self):
        """Create an extension manager for this context"""
        from OpenGLContext import extensionmanager

        self.extensions = extensionmanager.ExtensionManager()

    def setupFontProviders(self):
        """Load font providers for the context

        See the OpenGLContext.scenegraph.text package for the
        available font providers.
        """

    def setupDefaultEventCallbacks(self):
        """Setup common callbacks for the context

        This will normally be done in the GUI-lib's sub-class of
        context.  You might override it to provide other default
        callbacks, but you'll normally want to call the base-class
        implementation somewhere in that overridden method.

        What a key does when nobody has said otherwise: this runs *before*
        :meth:`setupCallbacks`, so anything an application binds for the same
        key replaces what is bound here.
        """
        self.addEventHandler("keyboard", name="<escape>", function=self.OnEscape)
        # On ``keyboard`` rather than ``keypress``: a keypress *is* character
        # input, raised from the backend's character callback, and Alt + a
        # letter produces no character on any of the platforms here -- so a
        # keypress binding for one is accepted, registered, and then never
        # fires.  Alt, because plain `f` is flying or the next font in half
        # the demos.
        self.addEventHandler(
            "keyboard",
            name="f",
            state=1,
            modifiers=(False, False, True),  # ALT
            function=self.OnFrameRate,
        )
        self.addEventHandler(
            "keyboard", name="<pagedown>", function=self.OnNextViewpoint
        )
        # F2 takes a screenshot, and so does Alt+S: F2 is what a player reaches
        # for, Alt+S what the demos here have always used.  Both only ask for
        # one -- see OpenGLContext.screenshot for why the picture cannot be
        # taken from the handler.  Alt+S is a key-down for the same reason
        # Alt+F is.
        self.setupScreenshotKey()
        self.addEventHandler(
            "keyboard",
            name="s",
            state=1,
            modifiers=(False, False, True),
            function=self.requestScreenshot,
        )

    def OnEscape(self, event=None):
        """What Escape means to this context.  Quitting, unless it says otherwise.

        The default is :meth:`OnQuit`, which exits the process forcibly.  For a
        demo that is right.  For anything holding state -- a game part-way
        through a match, a viewer with a world loaded and a camera somewhere --
        a key pressed to back out of *something else* would throw the session
        away with no confirmation and no way back.

        So a context that has somewhere to go instead overrides this: a game or
        a viewer puts its menu up, where Resume and Quit are both a click away.
        """
        return self.OnQuit(event)

    def OnQuit(self, event=None):
        """Quit the application (forcibly)"""
        self.suppressRedraw()

        # A node that raised on every frame has been counted rather than logged
        # sixty times a second; this is where the run says which ones, and it
        # has to be before the forcible exit below.
        try:
            from OpenGLContext.passes.renderpass import report_render_failures
            report_render_failures()
        except Exception:
            log.debug('could not report render failures', exc_info=True)

        # Before the forcible exit, which runs no finally block and no atexit
        # hook: a session quit in the middle of a stall is exactly the session
        # whose record is worth having, and that episode is still open.
        if self.stallJournal is not None:
            try:
                self.stallJournal.close()
            except Exception:
                log.debug('could not close the stall journal', exc_info=True)
        self.stopTelemetry('quit')

        # Likewise: sys.stdout is block-buffered whenever it is a pipe rather
        # than a terminal, and os._exit discards whatever is still in it. A
        # program run by a harness -- every demo under tests/ is -- would
        # otherwise lose everything it printed, and look right only when a
        # person ran it by hand.
        for stream in (sys.stdout, sys.stderr):
            try:
                if stream is not None:
                    stream.flush()
            except Exception:
                pass            # a closed or broken pipe is not worth dying on

        os._exit(0)

    def OnFrameRate(self, event=None):
        """Show or hide the developer overlay, where the frame rate is drawn"""
        self.toggleDebugOverlay()

    def OnNextViewpoint(self, event=None):
        """Go to the next viewpoint for the scenegraph"""
        sg = self.getSceneGraph()
        if sg:
            current = getattr(sg, "boundViewpoint", None)
            if current:
                current.isBound = False
                current.set_bound = False
        self.triggerRedraw(1)

    def setupThreading(self):
        """Setup primitives (locks, events) for threading"""
        global contextThread
        if threading:
            contextThread = threading.current_thread()
            contextThread.name = "GUIThread"
        self.setupScenegraphLock()
        self.setupRedrawRequest()

    def setupFrameRateCounter(self):
        """Setup structures for managing frame-rate

        This sets self.frameCounter to an instance of
        framecounter.FrameCounter, which is a simple node
        used to track frame-rate metadata during rendering.

        Updates to the framecounter are performed by OnDraw
        iff there is a visible change processed.

        The rate is *displayed* by the developer overlay
        (OpenGLContext.ui.debugoverlay), which reads this node through a
        provider; OPENGLCONTEXT_DISABLE_FPS_DISPLAY decides whether that
        overlay starts on screen.

        Note:
            If you override this method, you need to either use
            an object which has the same API as a FrameCounter or
            use None, anything else will cause failures in the
            core rendering loop!
        """
        from OpenGLContext import framecounter

        self.frameCounter = framecounter.FrameCounter()

    def setupLoopTrace(self):
        """Setup the main loop's wall-clock instrumentation

        This sets self.loopTrace to a looptrace.LoopTrace, which
        measures how long each pass of the backend's main loop takes
        and where that time went. It is the counterpart to the frame
        counter rather than a duplicate of it: the counter reports how
        fast the renderer is, and this reports how fast the whole loop
        is, which is what the user's hands feel.

        A backend drives it from its own loop (see GLFWContext.MainLoop);
        OnDraw divides its share into the event cascade and the render.
        Backends that have not been taught to drive it simply leave the
        iteration count at zero, and the developer overlay then omits
        the section rather than reporting nothing as if it were idle.

        Counting is unconditional and costs a few clock reads per
        iteration. Reporting is opt-in through OPENGLCONTEXT_STALL_MS /
        OPENGLCONTEXT_TRACE_STALLS.

        OPENGLCONTEXT_STALL_TRACE=<path> additionally records each slow
        period to a file, with the main thread's stack sampled while it
        is happening -- which is the only way to learn *which code* was
        running, since the stack has unwound by the time the iteration
        closes. See OpenGLContext.stalltrace.
        """
        from OpenGLContext import looptrace, stalltrace

        self.loopTrace = looptrace.LoopTrace()
        self.stallJournal = stalltrace.install(self.loopTrace, context=self)

    def setupEntropy(self):
        """Settle where this session's randomness comes from

        Before DoInit, and so before the application builds anything: a
        world generated from different numbers is a different world, and
        OPENGLCONTEXT_SEED has to be in force by the time the first one is
        drawn rather than whenever something first happens to ask.

        Establishes the session seed, which named streams
        (OpenGLContext.entropy.generator) derive from, and which telemetry
        records. When the environment named a seed this also seeds the
        process's own random and numpy.random generators from it, so a
        whole run is reproducible; when it did not, those are left exactly
        as they were. See OpenGLContext.entropy.
        """
        from OpenGLContext import entropy

        return entropy.seed()

    def setupTelemetry(self):
        """Record or replay this session, if the environment asked for one

        OPENGLCONTEXT_TELEMETRY=<path> writes the whole session -- every
        input the platform delivered, every frame's time, every exception,
        and the developer overlay's own description of the application --
        to a file, which OpenGLContext.telemetry.report reads back.

        OPENGLCONTEXT_TELEMETRY_REPLAY=<path> runs such a file again
        instead of taking live input: the same keys and clicks arrive on
        the same frames, against the recorded clock.

        Nothing is installed unless one of those is set, so a game nobody
        has switched this on for pays nothing. See OpenGLContext.telemetry,
        and startTelemetry for switching it on from the application.
        """
        from OpenGLContext import telemetry

        self.telemetry = telemetry.install(self)

    def mark(self, name, /, **fields):
        """Note something this application knows and the engine cannot

        The engine knows what was pressed and how long the frame took. It
        does not know that a level finished loading, that a match started,
        or that the player picked up the thing they were about to fall
        through the floor with:

            self.mark('level-loaded', map='ztn3dm1', bots=4)

        A mark is the line a reader looks for first when a journal is four
        minutes long and the failure is at the end of it, so this is a
        call whatever the session is: nothing recording, a recording, or a
        replay of one. A game that had to ask first would end up guarding
        the calls away, and those are exactly the ones that would have
        explained the failure nobody could reproduce.

        In a replay the mark is compared with the one the recording holds
        in its place, which is how a session says whether it played out
        the same way; see OpenGLContext.telemetry.replay.MarkComparison.

        Fields are data: numbers, strings, and numpy's numbers, which are
        written as theirs. A field may be called anything, `name`
        included -- what a game calls the map, the weapon and the player --
        because the mark's own name is positional.
        """
        session = self.telemetry
        if session is not None:
            session.mark(name, **fields)

    def reachedMark(self, name):
        """Whether this session is at the point a recording made `name`

        For the things a replay cannot get from the input or the clock:
        a level a worker thread finished decoding, a download that landed.
        They happen on whatever frame the disk decides, and a session in
        which the level appeared three frames early is one where every
        recorded input after it was given to a world that had already
        started. So the code that acts on one asks first:

            if not self.reachedMark('scene-mounted'):
                return          # the recording had it later; wait for that

        and marks it when it does act, which is what the replay reads.
        True whenever nothing is being replayed, and true in a replay whose
        recording holds no such mark still to answer -- so a replay never
        waits for something that never happened.
        """
        session = self.telemetry
        return True if session is None else session.reached(name)

    def overdueMark(self, name):
        """Whether a recording had made `name` by the frame this session is on

        The other half of reachedMark, and the half that says *hurry*: a
        thing that arrives when a worker thread is finished with it can be
        late as easily as early, and a replay that mounts a level nine
        frames after the recording did is as far out of step as one that
        mounted it nine frames before. Code that can wait for its own work
        waits while this is true.

        False whenever nothing is being replayed, and false in a replay
        whose recording holds no such mark still to answer.
        """
        session = self.telemetry
        return False if session is None else session.overdue(name)

    def startTelemetry(self, path=None, **named):
        """Begin recording this session to path (None for a dated default)

        What a "report a problem" menu item calls: recording can start at
        any point in a session, and what it records from then on is a
        complete session record less the part before it was asked for.

        Returns the OpenGLContext.telemetry.SessionRecording, which is also
        self.telemetry, and which the application marks its own events on:

            self.telemetry.mark('level-loaded', map='ztn3dm1')
        """
        from OpenGLContext import telemetry

        self.stopTelemetry()
        return telemetry.start(self, path, **named)

    def stopTelemetry(self, reason='stopped'):
        """Finish any recording or replay in progress"""
        session = self.telemetry
        if session is not None:
            try:
                session.close(reason)
            except Exception:
                log.debug('could not close the session recording', exc_info=True)
            self.telemetry = None

    def tracePhase(self, name):
        """Charge the wrapped block to a named phase of the loop iteration

        Answers a do-nothing context manager when there is no trace, so
        a caller writes `with self.tracePhase('render'):` without also
        writing the branch that asks whether anyone is measuring.

        A phase opened outside a main-loop iteration -- from drawPoll,
        or from a test that calls OnDraw directly -- is measured and
        discarded, so this is safe wherever OnDraw is safe.
        """
        trace = self.loopTrace
        if trace is None:
            return nullcontext()
        return trace.phase(name)

    def initializeEventManagers(self, managerClasses=()):
        """Customisation point for initialising event manager objects

        See:
            OpenGLContext.events.eventhandlermixin.EventHandlerMixin
        """

    def setupRedrawRequest(self):
        """Setup the redraw-request (threading) event"""
        if threading:
            self.redrawRequest = threading.Event()

    def setupScenegraphLock(self):
        """Setup lock to protect scenegraph from updates during rendering"""
        if threading:
            self.scenegraphLock = threading.RLock()

    def lockScenegraph(self, blocking=1):
        """Lock scenegraph locks to prevent other update/rendering actions

        Potentially this could be called from a thread other than the
        GUI thread, allowing the other thread to update structures in
        the scenegraph without mucking up any active rendering pass.
        """
        if threading:
            self.scenegraphLock.acquire(blocking)

    def unlockScenegraph(self):
        """Unlock scenegraph locks to allow other update/rendering actions

        Potentially this could be called from a thread other than the
        GUI thread, allowing the other thread to update structures in
        the scenegraph without mucking up any active rendering pass.
        """
        if threading:
            self.scenegraphLock.release()

    def setCurrent(self, blocking=1):
        """Set the OpenGL focus to this context"""
        assert inContextThread(), (
            """setCurrent called from outside of the context/GUI thread! %s"""
            % (threading.current_thread())
        )
        if not contextLock.acquire(blocking):
            raise LockingError("""Cannot acquire without blocking""")
        Context.currentContext = self
        self.lockScenegraph()

    def unsetCurrent(self):
        """Give up the OpenGL focus from this context"""
        assert inContextThread(), (
            """unsetCurrent called from outside of the context/GUI thread! %s"""
            % (threading.current_thread())
        )
        self.unlockScenegraph()
        Context.currentContext = None
        contextLock.release()

    @classmethod
    def ContextMainLoop(cls, *args, **named):
        """Enter the GUI toolkit's main loop; each backend sub-class overrides this"""
        raise NotImplementedError(
            """No mainloop specified for context class %r""" % (cls,)
        )

    def OnInit(self):
        """Customization point for scene set up and initial processing

        You override this method to do housekeeping chores such as
        loading images and generating textures, loading pre-established
        geometry, spawning new threads, etc.

        This method is called after the completion of the Context.__init__
        method for the rendering context.  GUI implementers:
            Wherever possible, this should be the very last function
            called in the initialization of the context to allow user
            code to use all the functionality of the context.
        """

    def OnIdle(self, *arguments):
        """Override to perform actions when the rendering loop is idle"""
        return self.drawPoll()

    def OnDraw(self, force=1, *arguments):
        """Callback for the rendering/drawing mechanism

        force -- if true, force a redraw.  If false, then only
            do a redraw if the event cascade has generated events.

        return value is whether a visible change occured

        This implementation does the following:

            * calls self.lockScenegraph()
                o calls self.DoEventCascade()
            * calls self.unlockScenegraph()
            * calls self.setCurrent()
            * calls self.renderPasses( self )
                See: the passes sub-package. renderPasses defaults to
                passes.renderpass.defaultRenderPasses, which selects and
                caches the FlatPass (passes/_flat.py, profile subclasses
                flatcore/flatcompat) that renders the context.

                The default pass defers most rendering options to the
                scenegraph returned by self.getSceneGraph().  If that value
                is None (default) then the pass renders the Context's
                callbacks.

                You can assign a different callable to self.renderPasses to
                replace the rendering algorithm, override the Context's
                various callbacks to write raw OpenGL code, or work by
                customizing the scene graph library.
            * if there was a visible change (which is the return value
                from the render-pass-set), calls self.SwapBuffers()
            * calls self.unsetCurrent()
        """
        assert inContextThread(), (
            """OnDraw called from outside of the context/GUI thread! %s"""
            % (threading.current_thread())
        )
        # could use if self.frameCounter, but that introduces a
        # potential race condition, so eat the extra call...
        t = perf()

        # Check for auto-exit on each OnDraw call, even if we return early
        # This ensures we count total calls rather than just rendered frames
        if self._autoExitFrames is not None:
            self._autoExitFrameCount += 1
            # Before the cascade below, which is where the timers are polled:
            # this frame is meant to see the instant it belongs to.
            self.advanceCaptureClock()
            if self._autoExitFrameCount >= self._autoExitFrames:
                log.info(f"Auto-exit: {self._autoExitFrameCount} OnDraw calls")
                self._autoExitDraw()
                self.OnQuit()
                return 0

        self.lockScenegraph()
        try:
            with self.tracePhase('cascade'):
                changed = self.DoEventCascade()
            if not force and not changed:
                return 0
        finally:
            self.unlockScenegraph()
        self.setCurrent()
        self.drawing = 1
        if threading:
            self.redrawRequest.clear()
        try:
            try:
                with self.tracePhase('render'):
                    visibleChange = self.renderPasses(self)
                if visibleChange:
                    if self.frameCounter is not None:
                        self.frameCounter.addFrame(perf() - t)
                    return 1
                return 0
            except KeyboardInterrupt:
                self.OnQuit()
        finally:
            glFlush()
            self.drawing = None
            self.unsetCurrent()

    def drawPoll(self, timeout=None):
        """Wait timeout seconds for a redraw request

        timeout -- timeout in seconds, if None, use
            self.drawPollTimeout

        returns 0 if timeout, 1 if true
        """
        if timeout is None:
            timeout = self.drawPollTimeout
        if threading:
            self.redrawRequest.wait(timeout)
            if self.redrawRequest.isSet():
                self.OnDraw(force=1)
                return 1
            else:
                self.OnDraw(force=0)
                return 1
        return 0

    def Render(self, mode=None):
        """Customization point for geometry rendering

        This method is called by the default render passes to
        render the geometry for the system.  Wherever possible,
        you should pay attention to the rendering modes to allow
        for optimization of your geometry (for instance,
        selection passes do not require lighting).

        The default implementation merely ensures that matrix mode
        is currently model view.

        See: passes/_flat.py for the pass that defines the properties of
        the mode.
        """
        ### Put your rendering code here

    def DoEventCascade(self):
        """Customization point for generating non-GUI event cascades

        This method should only be called after self.lockScenegraph
        has been called.  self.unlockScenegraph should then be called

        Most Contexts will use the eventhandler mix-in's version of this
        method.  That provides support for the defered-execution of
        functions/method during the event cascade.
        """
        return 0

    def OnResize(self, *arguments):
        """Resize the window when the windowing library says to"""
        self.triggerRedraw(1)

    def triggerPick(self):
        """Trigger a selection rendering pass

        If the context is not currently drawing, the selection render will
        occur immediately, otherwise it will occur the next time the
        rendering loop reaches the selection stage.
        """
        contextLock.acquire()
        try:
            if (not self.drawing) and (not self.deferRedraw) and inContextThread():
                self.OnDraw()
            elif threading:
                self.redrawRequest.set()
        finally:
            contextLock.release()

    def settingsChanged(self):
        """The context definition has been edited; re-read what is not per-frame.

        Most rendering options are read by the render pass every frame (see
        :mod:`OpenGLContext.renderoptions`), so a change shows up on its own.
        The few that are set once on the window -- the swap interval, the buffer
        format -- are re-applied here. A backend overrides this for its own;
        anything that cannot be changed without a new context is left alone.

        Called by the settings screen when Apply is pressed.
        """
        self.triggerRedraw(1)

    def triggerRedraw(self, force=0):
        """Indicate to the context that it should redraw when possible

        If force is true, the rendering will begin immediately if the
        context is not already drawing.  Otherwise only the indicator flag
        will be set.
        """
        contextLock.acquire()
        try:
            self.alreadyDrawn = 0
        finally:
            contextLock.release()
        if force and (not self.drawing) and (not self.deferRedraw) and inContextThread():
            self.OnDraw()
        elif threading:
            self.redrawRequest.set()
        else:
            raise RuntimeError("""Unreasonable threading state!""")

    def shouldRedraw(self):
        """Return whether or not the context contents need to be redrawn"""
        return not self.alreadyDrawn

    def suppressRedraw(self):
        """Indicate to the context that there is no need to re-render

        This method signals to the context that there are no updates
        currently requiring redrawing of the context's contents.

        See:
            Context.shouldRedraw and Context.triggerRedraw
        """
        self.alreadyDrawn = 1

    def presentFrame(self):
        """Put the finished frame on the screen.

        The render pass calls this, and it is the one moment the frame is both
        complete and still readable: once the buffers are swapped the driver has
        recycled the back buffer and what is in it is an older frame.  Anything
        that has to see what the player saw -- the screenshot key, a capture, a
        recording -- reads it here, and a subclass wanting the same overrides
        *this* rather than :meth:`SwapBuffers`, which stays the backend's single
        job of putting the buffer up.
        """
        self.takePendingScreenshot()
        return self.SwapBuffers()

    def SwapBuffers(self):
        """Called by the rendering loop when the buffers should be swapped

        Each GUI library needs to override this method with the appropriate
        code for the library.
        """

    def ViewPort(self, width, height):
        """Set the size of the OpenGL rendering viewport for the context

        This implementation assumes that the context takes up the entire
        underlying window (i.e. that it starts at 0,0 and that width, height
        will represent the entire size of the window).
        """
        assert inContextThread(), (
            """ViewPort called from outside of the context/GUI thread! %s"""
            % (threading.current_thread())
        )
        self.setCurrent()
        try:
            self.viewportDimensions = width, height
            glViewport(0, 0, int(width), int(height))
        finally:
            self.unsetCurrent()
        if self.contextDefinition:
            self.contextDefinition.size = width, height

    def getViewPort(self):
        """Method to retrieve the current dimensions of the context

        Return value is a width, height tuple. See Context.ViewPort
        for setting of this value.
        """
        return self.viewportDimensions

    # Case-insensitive alias: a render pass exposes ``getViewport`` (a 4-tuple),
    # the context ``getViewPort`` (a width,height pair), and the two differ only by
    # capitalisation -- an easy typo that used to AttributeError on the context.
    # Accept either spelling here so a mixed-case call degrades to the right value
    # instead of crashing.
    getViewport = getViewPort

    def addPickEvent(self, event):
        """Add event to list of events to be processed by selection-render-mode

        This is a method of the Context, rather than the
        rendering pass (which might seem more elegant given
        that it is the rendering pass which deals with the
        events being registered) because the requests to
        render a pick event occur outside of the rendering
        loop.  As a result, there is (almost) never an
        active context when the pick-event-request comes in.

        Events are held under Event.getPickKey, which is what says whether two
        of them within one frame are the same news twice (a click, a movement)
        or two separate increments (the wheel, where each notch is another
        line). An event object that does not offer one is keyed as it always
        was, so a hand-rolled event still records.
        """
        cd = self.contextDefinition
        if cd is not None and not cd.pickEnabled:
            return
        key = getattr(event, 'getPickKey', event.getKey)()
        self.pickEvents[(event.type, key)] = event

    def getPickEvents(self):
        """Get the currently active pick-events"""
        return self.pickEvents

    def hasMouseMoveHandlers(self):
        """Check if any mouse-move related handlers are registered.

        Returns True if there are handlers for mousemove, mousein, or mouseout
        events. Used to optimize selection by skipping mouse-move processing
        when no handlers would receive the events. Asks each relevant event
        manager whether it has live receivers rather than walking the pydispatch
        registry here.

        **A captured type counts.** ``captureEvents`` swaps a manager into the
        slot instead of registering anything with the dispatcher, which is how
        a drag receives its own events -- so the receiver test answers "no" for
        precisely the interaction that exists to consume them. Right-drag to
        examine started and then never saw a single movement, because every one
        was filtered away before it arrived.
        """
        for event_type in ('mousemove', 'mousein', 'mouseout'):
            if self.isCapturingEvents(event_type):
                return True
            manager = self.getEventManager(event_type)
            if manager is not None and manager.hasReceivers():
                return True
        return False

    def sceneBounds(self):
        """``(centre, radius)`` around this context's scene, or None.

        What is on screen and how big it is -- for framing a camera on it, or
        for choosing the point a drag should pivot about.
        """
        from OpenGLContext.scenegraph.boundingvolume import boundingSphere
        sg = self.getSceneGraph()
        if sg is None:
            return None
        return boundingSphere(getattr(sg, 'children', None) or ())

    def examineCenter(self, event):
        """The world point an examine drag should orbit about.

        **What was clicked on, when the click landed on the scene.** Examining
        the thing you touched is the whole gesture, and unprojecting the pick
        gives exactly that.

        A click that hit *nothing* still unprojects: a depth of 1.0 is a real,
        usable-looking world point out at the far plane -- measured at 127 units
        for a model three units across -- and orbiting that is orbiting the sky.
        So a picked point is taken only where it is within reach of the scene.

        A click that picked nothing -- empty sky, or a context whose selection
        pass had nothing to report -- used to fall back to a point *ten units*
        in front of the camera, a constant with no relation to what was on
        screen. A model framed four units away then orbited about a pivot six
        units behind itself and a small drag threw the camera right around it;
        a model a kilometre across pivoted about a point inside its own surface.
        So the fallback is the scene's own bounding sphere.

        Standing **inside** those bounds -- walking a building -- orbiting the
        far side of the room is not what the gesture means either, so the pivot
        is a little way ahead of the camera instead, at a distance taken from
        the scene rather than from a constant.
        """
        platform = self.getViewPlatform()
        bounds = self.sceneBounds()
        try:
            picked = event.unproject()
        except Exception:
            picked = None           # nothing was under the cursor
        if picked is not None and self._withinScene(picked, bounds):
            return picked
        ahead = EXAMINE_PIVOT_FALLBACK      # nothing to go on at all
        if bounds is not None:
            centre, radius = bounds
            distance = _distanceBetween(centre, platform.position)
            radius = max(float(radius), 1e-6)
            if distance > radius * EXAMINE_INSIDE_FRACTION:
                return centre
            ahead = radius * EXAMINE_AHEAD_FRACTION
        return platform.quaternion * [0, 0, -ahead, 0] + platform.position

    @staticmethod
    def _withinScene(point, bounds):
        """Whether a picked point is near enough the scene to be part of it.

        Generously: a bounding sphere already overstates a scene's extent, and
        its surface is not a hard edge.  What this rejects is the far plane,
        which is an order of magnitude out, not a point a little proud of the
        model.
        """
        if bounds is None:
            return True             # nothing to judge it against
        centre, radius = bounds
        return (_distanceBetween(point, centre)
                <= max(float(radius), 1e-6) * EXAMINE_PICK_REACH)

    def getSceneGraph(self):
        """Get the scene graph for the context (or None)

        You must return an instance of:

            OpenGLContext.scenegraph.scenegraph.SceneGraph

        Normally you would create that with the loader, which reads
        VRML97, glTF and OBJ from a path or a URL:

            from OpenGLContext.loaders.loader import Loader
            def OnInit( self ):
                self.sg = Loader.load( 'world.wrl' )

        or by using the classes in OpenGLContext.scenegraph.basenodes:

            from OpenGLContext.scenegraph import basenodes
            def OnInit( self ):
                self.sg = basenodes.sceneGraph(
                    children = [
                        basenodes.Transform(...)
                    ],
                )

        to define the scenegraph in Python code.
        """
        return getattr(self, "sg", None)

    def renderedChildren(self, types=None):
        """Get the rendered children of the scenegraph"""
        sg = self.getSceneGraph()
        if not sg:
            return (ContextRenderNode,)
        else:
            return (sg,)

    # App-framework config / backend factory lives in ContextConfigMixin
    # (getApplicationName, getUserAppDataDirectory, get/setDefault*, getContextType*).
    # getTTFFiles and fromConfig stay here: they name the concrete Context class
    # directly.
    ttfFileRegistry = None

    def getTTFFiles(self):
        """Get TrueType font-file registry object"""
        if not self.ttfFileRegistry:

            registryFile = os.path.join(
                self.getUserAppDataDirectory(), "font_metadata.cache"
            )
            from OpenGLContext.scenegraph.text import ttfregistry

            registry = ttfregistry.TTFRegistry()
            if os.path.isfile(registryFile):
                log.info("Loading font metadata from cache %r", registryFile)
                registry.load(registryFile)
                if not registry.fonts:
                    log.warning("Re-scanning fonts, no fonts found in cache")
                    registry.scan()
                    registry.save()
                    log.info("Font metadata stored in cache %r", registryFile)
            else:
                log.warning(
                    "Scanning font metadata into cache %r, please wait", registryFile
                )
                registry.scan()
                registry.save(registryFile)
                log.info("Font metadata stored in cache %r", registryFile)
            # make this a globally-available object
            Context.ttfFileRegistry = registry
        # Keep the font-provider class registry in sync so that font providers
        # registered without a full setupFontProviders() call (e.g. plain
        # InteractiveContext + a direct toolsfont import) can still resolve fonts.
        from OpenGLContext.scenegraph.text import fontprovider
        fontprovider.setTTFRegistry(self.ttfFileRegistry)
        return self.ttfFileRegistry

    ##	def getUserContextPreferences( cls ):
    ##		"""Retrieve user-specific context preferences"""
    ##		raise NotImplementedError( """Don't have preferences working yet""" )
    @staticmethod
    def fromConfig(cfg):
        """Given a ConfigParser instance, produce a configured sub-class"""
        from OpenGLContext import contextdefinition

        type = gui = None
        if cfg.has_option("context", "type"):
            type = cfg.get("context", "type")
        if cfg.has_option("context", "gui"):
            gui = cfg.get("context", "gui")
        if type is None:
            type = "vrml"
        for plug_type in [
            plugins.InteractiveContext,
            plugins.VRMLContext,
            plugins.Context,
        ]:
            if type == plug_type.type_key:
                type = plug_type
        baseCls = Context.getContextType(gui, type)
        baseCls = type(
            "TestingContext",
            (baseCls,),
            {
                "contextDefinition": contextdefinition.ContextDefinition.fromConfig(
                    cfg,
                ),
            },
        )
        return baseCls


### Context render-calling child...
class _ContextRenderNode(nodetypes.Rendering, nodetypes.Children, node.Node):
    """The Context object as a RenderNode

    Returned as the child of the Context if there
    is no getSceneGraph() result.
    """

    def Render(self, mode):
        """Delegate rendering to the mode.context.Render method"""
        return mode.context.Render(mode)

    def sortKey(self, passes, matrix):
        return (0, None)


ContextRenderNode = _ContextRenderNode()


def getCurrentContext():
    """Get the currently-rendering context

    This function allows code running during the render cycle
    to determine the current context.  As a general rule, the
    context is available as rendermode.context from the render
    mode/pass which is passed to the rendering functions as an
    argument.

    Note: this function is deprecated, use the passed rendering
    mode/pass's context attribute instead.
    """
    return Context.currentContext
