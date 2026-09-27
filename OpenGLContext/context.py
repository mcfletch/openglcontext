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
# Annotations are strings at run time, so a name only a checker needs -- the
# backend classes, the recording and telemetry types -- is declared under
# TYPE_CHECKING and written plainly rather than in quotes.
from __future__ import annotations

from OpenGL.GL import *
from OpenGLContext import contextresources, texturecache, plugins, renderoptions
from OpenGLContext.screenshot import ScreenshotMixin
from OpenGLContext.passes import renderpass
from vrml.vrml97 import nodetypes
from vrml import node, cache
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeVar, cast
from collections.abc import Callable, Mapping, Sequence
import weakref
import os
import sys
import time
import logging

if TYPE_CHECKING:
    from configparser import ConfigParser

    from OpenGLContext.contextdefinition import ContextDefinition
    from OpenGLContext.framecounter import FrameCounter
    from OpenGLContext.looptrace import LoopTrace
    from OpenGLContext.multiview.views import View, ViewLayout
    from OpenGLContext.stalltrace import StallJournal
    from OpenGLContext.telemetry.record import ReplaySession, SessionRecording
    from OpenGLContext.video.clock import FixedStepClock

log = logging.getLogger(__name__)

#: Whatever the read passed to :meth:`Context.drawAndReadFrame` produces, which
#: is what that call hands back.
_Read = TypeVar('_Read')
#: A point in space, as any sequence of at least three numbers.  The scenegraph
#: answers with numpy arrays and an application with tuples; both are read the
#: same way here.
Point = Sequence[float]


def _fieldIsSet(definition: ContextDefinition, name: str) -> bool:
    """Whether ``name`` holds a value, as opposed to resolving to its default.

    A field default is a callable the field runs on first read, so reading the
    field to find out would settle it and destroy the answer.
    """
    from vrml import protofunctions
    return bool(protofunctions.getField(definition, name).fhas(definition))


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
def _distanceBetween(first: Point, second: Point) -> float:
    """Straight-line distance between two points, ignoring any fourth element."""
    offset = [float(a) - float(b)
              for a, b in zip(first[:3], second[:3], strict=True)]
    return float((offset[0] ** 2 + offset[1] ** 2 + offset[2] ** 2) ** 0.5)


#: How far outside the scene's bounding sphere a picked point may lie and still
#: be treated as part of the scene, as a multiple of its radius.  Generous: what
#: this is for is rejecting the far plane, which is an order of magnitude out.
EXAMINE_PICK_REACH = 1.5
from OpenGLContext.contextconfig import ContextConfigMixin
from OpenGLContext.events.eventhandlermixin import EventHandlerMixin
from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin
from OpenGLContext.multiview.mixin import MultiViewMixin
from OpenGLContext.ui.overlay import OverlayStackMixin
from OpenGLContext.ui.screen import ScreenMixin
from OpenGLContext.vrmlcontext import VRMLSceneMixin
from OpenGLContext import windowsystem as _windowsystem

if TYPE_CHECKING:
    from OpenGLContext.windowsystem import WindowSystem


class LockingError(Exception):
    pass


import queue
import ctypes
import threading
from contextlib import AbstractContextManager, nullcontext

perf = time.perf_counter
contextLock = threading.RLock()
contextThread: threading.Thread | None = None


def _composed(core: ContextCore) -> Context:
    """``core`` as the :class:`Context` it is.

    :class:`ContextCore` is only ever composed into :class:`Context`, so this
    is a statement to a checker, which reads the core on its own.
    """
    return cast('Context', core)


def contextAddress(handle: Any) -> int | None:
    """``handle`` as a plain integer, or None where it names no context

    A platform answers with whatever its binding API calls a context, and some
    of them hand back a fresh ctypes pointer object for each query.  Two such
    objects pointing at the same context are not equal -- ``==`` on them is
    identity -- so the address is what the question is really about.
    """
    if handle is None:
        return None
    if isinstance(handle, int):
        return handle or None
    try:
        return ctypes.cast(handle, ctypes.c_void_p).value
    except (ctypes.ArgumentError, TypeError):
        return None


def sameContext(one: Any, other: Any) -> bool:
    """Whether two context handles name the same GL context"""
    address = contextAddress(one)
    return address is not None and address == contextAddress(other)


def inContextThread() -> int:
    """Return true if the current thread is the context thread

    Until a context has claimed one there is no wrong thread to be on, so a
    backend setting its window up answers true -- which is what the callers
    are asserting.
    """
    if threading:
        if contextThread is None:
            return 1
        if threading.current_thread() == contextThread:
            return 1
        elif threading.current_thread().name == contextThread.name:
            return 1
        else:
            return 0
    return 1


#: The pointers a window can be asked for, by name. Each is something the
#: windowing systems this engine runs on all have a word for, so a control
#: asks for one of these rather than for a platform's own spelling:
#:
#: ``arrow``
#:     the ordinary pointer, which is also what ``''`` means.
#: ``hand``
#:     over something that will act on a click.
#: ``text``
#:     over something that takes typing.
#: ``crosshair``
#:     over something being aimed or placed.
#: ``resize-x`` / ``resize-y``
#:     over a line that drags across or up and down.
#: ``resize``
#:     over something that drags either way.
#: ``no``
#:     over somewhere this gesture will not go.
CURSORS = ('arrow', 'hand', 'text', 'crosshair', 'resize-x', 'resize-y',
           'resize', 'no')


class ContextCore(ScreenMixin, ScreenshotMixin, ContextConfigMixin):
    """What a :class:`Context` is beneath its event, camera and scene mix-ins

    The definition, the window system, redraw scheduling, the render passes,
    picking, the frame counter and loop trace, telemetry, auto-exit and
    capture.  :class:`Context` composes this with
    :class:`~OpenGLContext.events.eventhandlermixin.EventHandlerMixin`,
    :class:`~OpenGLContext.move.viewplatformmixin.ViewPlatformMixin` and
    :class:`~OpenGLContext.vrmlcontext.VRMLSceneMixin`, which sit ahead of it
    so that the methods they extend -- ``ViewPort``,
    ``setupDefaultEventCallbacks``, ``hasMouseMoveHandlers`` -- reach this
    class's through ``super()``.  An application subclasses :class:`Context`,
    never this.

    Attributes:

        windowsystem -- the :class:`~OpenGLContext.windowsystem.WindowSystem`
            this context draws through, chosen by the definition's
            ``windowsystem`` field as the context is built.  See
            :mod:`OpenGLContext.windowsystem`.

        window -- the toolkit's own window or widget (a GLFW window handle,
            a Tk ``GLFrame``, a wx ``GLCanvas``, a Qt ``QWindow``...), which
            is what an application embedding the view packs, sizes or
            parents; None before it is opened and after it is released.

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

    currentContext: Context | None = None
    allContexts: ClassVar[list[weakref.ref[ContextCore]]] = []
    renderPasses = renderpass.defaultRenderPasses
    frameCounter: FrameCounter | None = None
    loopTrace: LoopTrace | None = None
    stallJournal: StallJournal | None = None
    telemetry: SessionRecording | ReplaySession | None = None
    contextDefinition: ContextDefinition | None = None
    #: The OpenGL profile a subclass needs, when that is all it has to say:
    #: ``profile = 'compatibility'`` on a demo that draws with the
    #: fixed-function pipeline.  It is applied over :attr:`contextDefinition`
    #: rather than replacing it, so a class can name its profile and still
    #: inherit the size, buffers and rendering features its base declared.
    #: ``None`` leaves the choice to the definition, and thence to
    #: ``OPENGLCONTEXT_PROFILE``.  See :meth:`resolveDefinition`.
    profile: str | None = None
    #: The core-profile renderer a subclass needs: ``'pbr'`` draws this
    #: context with the metallic/roughness pass whatever
    #: ``OPENGLCONTEXT_RENDERER`` says, so a tool that needs it (a bake) asks
    #: for it without changing the process environment every later context
    #: reads.  ``None`` leaves the choice to ``OPENGLCONTEXT_RENDERER``.
    renderer: str | None = None
    #: The window system a subclass opens on, when it has one it needs:
    #: ``windowSystemName = 'egl'`` on a bake that must never open a window.
    #: Applied over :attr:`contextDefinition` as :attr:`profile` is, and under
    #: a definition passed to the constructor that names one.  ``None`` leaves
    #: the choice to the definition, and thence to
    #: :func:`OpenGLContext.windowsystem.choose`.
    windowSystemName: ClassVar[str | None] = None

    ### State flags/values
    # Set to false to trigger a redraw on the next available iteration
    alreadyDrawn: int | None = None
    drawing: int | None = None
    # When true, triggerRedraw/triggerPick only flag a redraw request rather
    # than rendering synchronously in-thread. Backends that drive their own
    # render loop (e.g. GLFW) set this so a burst of input events coalesces
    # into a single render per loop iteration instead of one render per event.
    deferRedraw = False
    #: The session time a frame is owed at, or None; see :meth:`redrawAt`.
    redrawDue: float | None = None
    viewportDimensions: tuple[int, int] = (0, 0)
    drawPollTimeout = 0.01
    coreProfile = False
    #: How many frames ``MainLoop`` draws before returning on an offscreen
    #: window system, where there is no user to close a window.  One is the
    #: common case -- render an image, read it back -- and an animation that
    #: wants a sequence sets it higher; :meth:`wantsMoreFrames` carries the
    #: loop past it.
    frameCount = 1
    #: The window system this context draws through; set as it is built.
    windowsystem: WindowSystem
    #: Set once ``OnInit`` has run; see :meth:`completeInit`.
    initialised = False

    # Auto-exit support for automated testing
    # Set OPENGLCONTEXT_AUTO_EXIT_FRAMES environment variable to exit after N frames
    # Set OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR to capture screenshot before exit
    _autoExitFrames: int | None = None
    _autoExitFrameCount = 0
    _autoExitCaptureDir: str | None = None
    #: Whether this run's frames are read back.  Set once by
    #: :meth:`setupAutoExit` for a bounded run, and by the viewer's
    #: ``setupCapture`` for a settle capture; not cleared, because
    #: ``_autoExitFrames`` is -- ``_autoExitDraw`` clears that to keep its
    #: forced redraw from recursing, and that redraw is the frame the picture
    #: is of.
    _capturing = False
    #: The frame-counting clock this run advances, if it is a capture.
    _captureClock: FixedStepClock | None = None

    ### Node-like attributes
    PROTO = "Context"
    DEF = "#Context"

    if TYPE_CHECKING:
        # What this class calls on the mix-ins :class:`Context` puts ahead of
        # it.  Declarations rather than do-nothing definitions, which would be
        # a second implementation for the MRO to choose between.
        def isCapturingEvents(self, eventType: Any) -> Any: ...
        def getEventManager(self, eventType: Any) -> Any: ...
        def initializeEventManagers(self) -> None: ...
        def addEventHandler(self, eventType: Any, *arguments: Any,
                            **named: Any) -> None: ...
        def getViewPlatform(self) -> Any: ...
        def DoEventCascade(self) -> int: ...

    def __init__(
        self,
        definition: ContextDefinition | Mapping[str, Any] | None = None,
        *,
        parent: Any = None,
        **named: Any,
    ) -> None:
        """Open a window and establish the Context working environment

        definition -- an OpenGLContext.contextdefinition.ContextDefinition
            instance which controls the context features (window system,
            size, bit-depth, etc).  If null, then use self.contextDefinition
            if it exists, otherwise create a default ContextDefinition
            instance.  Alternately, can be a dictionary of key:value pairs to
            set on the default ContextDefinition to specify required
            parameters.
        parent -- the toolkit container to open the view inside (a Tk
            widget, a wx window), where the window system has such a thing;
            None opens a window of the context's own.
        named -- individual definition fields, overriding the definition:
            ``Context(windowsystem='egl', size=(640, 480))``.

        Opens the window system the definition names (see
        :meth:`createWindowSystem`), then calls the following:

            setupThreading,
            setupExtensionManager,
            initializeEventManagers,
            setupDefaultEventCallbacks,
            setupCallbacks,
            setupCache,
            setupFrameRateCounter,
            setupLoopTrace,
            setupEntropy,
            setupCaptureClock,
            setupTelemetry,
            setupAutoExit,
            completeInit

        ``completeInit`` runs ``OnInit`` as soon as there is a GL context to
        run it in -- here, unless the window system has to wait for the
        window to be shown, in which case it calls it then.
        """
        self.setupLogging()
        definition = self.setDefinition(definition, **named)
        self.windowsystem = self.createWindowSystem(definition)
        if parent is not None and not self.windowsystem.acceptsParent:
            raise TypeError(
                'The %r window system opens windows of its own and takes no '
                'parent' % (self.windowsystem.name,))
        try:
            # Inside: an ``open`` that fails after making its window gives
            # it back through ``abandon`` like any later step.
            ready = self.windowsystem.open(definition, parent)
            self.setupThreading()
            self.setupExtensionManager()
            self.initializeEventManagers()
            self.windowsystem.bindCallbacks()
            # Defaults first: a key can have only one handler, and the second
            # registration for it replaces the first.  ``setupCallbacks`` is
            # where a context says what a key should do *here*, so it has to
            # land on top.
            self.setupDefaultEventCallbacks()
            self.setupCallbacks()
            self.allContexts.append(weakref.ref(self))
            self.pickEvents: dict[tuple[str, Any], Any] = {}
            self.eventCascadeQueue: queue.Queue[Any] = queue.Queue()
            self.setupCache()
            self.setupFrameRateCounter()
            self.setupLoopTrace()
            self.setupEntropy()
            self.setupCaptureClock()
            self.setupTelemetry()
            self.setupAutoExit()
            if ready:
                self.completeInit()
        except BaseException:
            self.windowsystem.abandon()
            raise

    @classmethod
    def chooseWindowSystem(cls, definition: ContextDefinition) -> str:
        """The name of the window system a context of ``definition`` opens on.

        The definition's ``windowsystem`` field, and where that is empty,
        ``OPENGLCONTEXT_BACKEND``, then this user's preference
        (:meth:`setDefaultContextType`), then the first registered window
        system that imports.  Raises
        :class:`~OpenGLContext.windowsystem.WindowSystemUnavailable` naming
        what was asked for and why it cannot be had.  See
        :func:`OpenGLContext.windowsystem.choose`.
        """
        return _windowsystem.choose(
            str(definition.windowsystem or ''),
            environment=renderoptions.env_text('OPENGLCONTEXT_BACKEND') or None,
            preference=cls.getWindowSystemPreference(),
            registered=_windowsystem.registered(),
            probe=_windowsystem.probe,
        )

    def createWindowSystem(self, definition: ContextDefinition) -> WindowSystem:
        """The window system this context draws through, not yet opened."""
        chosen = _windowsystem.load(self.chooseWindowSystem(definition))
        return chosen(_composed(self))

    @property
    def window(self) -> Any:
        """The toolkit's own window or widget, or None when there is none."""
        system = getattr(self, 'windowsystem', None)
        return None if system is None else system.window

    @property
    def providesGLUT(self) -> bool:
        """Whether GLUT is set up here, so its bitmap fonts can be drawn.

        A GLUT call without GLUT set up ends the process, so font providers
        consult this before choosing a GLUT font.
        """
        system = getattr(self, 'windowsystem', None)
        return bool(system is not None and system.providesGLUT)

    def completeInit(self) -> bool:
        """Run ``OnInit`` and size the viewport; answer whether it ran now.

        The constructor calls this once the window system has a GL context to
        run ``OnInit`` in.  A window system that must wait for its window to
        be shown first calls it itself, when it has been.  Calling it again
        does nothing.
        """
        if self.initialised:
            return False
        self.initialised = True
        self.DoInit()
        self.ViewPort(*self.windowsystem.drawableSize())
        return True

    def setupAutoExit(self) -> None:
        """Setup auto-exit for automated testing.

        If OPENGLCONTEXT_AUTO_EXIT_FRAMES environment variable is set,
        the context will automatically exit after rendering that many frames.
        This enables automated testing of interactive scripts.

        If OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR is also set, a screenshot
        will be captured before exiting.
        """
        auto_exit = renderoptions.env_text('OPENGLCONTEXT_AUTO_EXIT_FRAMES')
        if auto_exit:
            try:
                self._autoExitFrames = int(auto_exit)
                self._autoExitFrameCount = 0
                self._capturing = True
                log.info(f"Auto-exit enabled: will exit after {self._autoExitFrames} frames")
            except ValueError:
                log.warning(f"Invalid OPENGLCONTEXT_AUTO_EXIT_FRAMES value: {auto_exit}")

        capture_dir = renderoptions.env_text('OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR')
        if capture_dir:
            self._autoExitCaptureDir = capture_dir
            log.info(f"Auto-exit capture enabled: screenshots will be saved to {capture_dir}")

    @property
    def renderingForCapture(self) -> bool:
        """Whether this run's frames are read back rather than looked at.

        True for a bounded run -- ``OPENGLCONTEXT_AUTO_EXIT_FRAMES``, which
        draws that many frames and reads the last one back -- and for a viewer
        given a settle capture. The adaptive renderer paths pin themselves
        where this is true, so the frame that is read back follows from the
        scene rather than from how quickly the machine reached it: adaptive IBL
        climbs back to ``full`` over tens of frames, and a capture of five
        would show whichever mode the climb had got to.
        :func:`OpenGLContext.video.clock.capture_clock` reads the same variable
        to put the world on a frame-counting clock.

        Wider than the viewer's own ``capturing``, which says that a settle
        capture is driving the run and that the scene is therefore loaded up
        front and simulated not at all.
        """
        return self._capturing

    def setupCaptureClock(self) -> FixedStepClock | None:
        """Put this run on a frame-counting clock if it is a capture.

        Before DoInit, so that a Timer or TimeSensor built while the scene is
        being constructed takes its start from the same clock it will later be
        advanced by.  See OpenGLContext.video.clock.capture_clock for when one
        is installed and what follows it.
        """
        from OpenGLContext.video.clock import capture_clock

        clock = capture_clock()
        if clock is not None:
            clock.install()
            log.info("Capture clock: %s frames a second, counted", clock.frame_rate[0])
        self._captureClock = clock
        return clock

    def stopCaptureClock(self) -> None:
        """Give back whatever clock this context replaced.  Safe to call twice.

        The time source is process-wide, so a context that has finished must
        not leave the world being advanced by frames nobody is drawing.
        """
        if self._captureClock is not None:
            self._captureClock.restore()
            self._captureClock = None

    def drawAndReadFrame(self, read: Callable[[], _Read]) -> _Read:
        """Draw one frame and call ``read()`` on it before it is presented.

        A caller that draws and *then* reads the back buffer reads the frame
        before last, or nothing at all: presenting a frame swaps it to the
        front, leaving the back buffer holding whatever the driver last put
        there, which on many drivers is black. The only moment the frame just
        drawn is in the back buffer is between the render and the swap, so this
        renders one frame and reads it there.

        ``read`` is called with the context current and no arguments; whatever
        it returns is returned here. Where the render produces no visible change
        there is no swap to intercept, and ``read`` is called afterwards against
        the buffer as it stands.

        This is what a test wanting the pixels of a scene should use --
        ``OpenGLContext.capture.read_back_buffer`` is the usual ``read``.
        """
        swap = self.SwapBuffers
        answer: list[_Read] = []

        def _readThenSwap() -> None:
            if not answer:
                answer.append(read())
            swap()

        # Intercepting the swap on *this instance* is the whole mechanism: the
        # frame is only in the back buffer between the render and the swap, and
        # the swap is the backend's own method.
        self.SwapBuffers = _readThenSwap    # type: ignore[method-assign]  # wrapped on this instance for one frame
        try:
            self.OnDraw(force=1)
        finally:
            self.SwapBuffers = swap         # type: ignore[method-assign]  # the backend's own swap restored
        if not answer:
            self.setCurrent()
            try:
                answer.append(read())
            finally:
                self.unsetCurrent()
        return answer[0]

    def _autoExitDraw(self) -> None:
        """Render one final frame and capture it before auto-exit."""
        if not self._autoExitCaptureDir:
            return
        # Suppress the auto-exit branch so the forced redraw below renders normally
        # instead of recursing back into here.
        self._autoExitFrames = None
        self.drawAndReadFrame(self._autoExitCapture)

    def _autoExitCapture(self) -> None:
        """Write the current back buffer to the configured capture path."""
        if not self._autoExitCaptureDir:
            return
        try:
            from OpenGLContext.capture import capture_to_png
            # Use test name from environment, or fall back to class attribute or class name
            test_name = renderoptions.env_text(
                'OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME',
                getattr(self, 'test_name', self.__class__.__name__)
            )
            filepath = os.path.join(self._autoExitCaptureDir, f"{test_name}.png")
            if capture_to_png(filepath, skip_blank=False):
                log.info(f"Auto-exit capture saved: {filepath}")
        except Exception as e:
            log.warning(f"Auto-exit capture failed: {e}")

    def setupLogging(self) -> None:
        logging.basicConfig(level=logging.WARNING)

    @classmethod
    def resolveDefinition(
        cls,
        definition: ContextDefinition | Mapping[str, Any] | None = None,
        **named: Any,
    ) -> ContextDefinition:
        """The definition a context of this class should be created from.

        The constructor calls this before the window system opens anything:
        the window system, and the window's profile, version, buffers and size,
        all come from the definition, so a class that declares one has to be
        consulted while there is still a window to configure.

        The order is: the ``definition`` passed in, then the one the class
        declares as :attr:`contextDefinition`, then a fresh one -- whose field
        defaults read the environment.  ``named`` sets fields on whichever of
        those it lands on.  A mapping rather than a node is read as the fields
        to set.  :attr:`profile` and :attr:`windowSystemName` are applied over
        the class's declaration, and under anything the caller passed.

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
            versionWasSet = _fieldIsSet(definition, 'version')
            for key, value in named.items():
                setattr(definition, key, value)
            if 'profile' in named and 'version' not in named and not versionWasSet:
                # The rule ContextDefinition.__init__ applies, applied again
                # where the profile arrives afterwards: a profile named without
                # a version settles the version from that profile.  Without it a
                # compatibility request keeps the 3.3 a core default left behind,
                # a backend turns "version >= 3" into a context hint, and the
                # driver answers a compatibility request with a core window --
                # which fails at the first fixed-function call it was asked for.
                definition.version = contextdefinition.version_for_profile(
                    definition.profile)
        if declared and cls.profile and not _fieldIsSet(definition, 'profile'):
            definition.profile = cls.profile
            if not _fieldIsSet(definition, 'version'):
                definition.version = contextdefinition.version_for_profile(cls.profile)
        callerNamedOne = 'windowsystem' in named or (
            not declared and _fieldIsSet(definition, 'windowsystem'))
        if cls.windowSystemName and not callerNamedOne:
            # Over the class's own declaration, but under what the caller
            # passed: a program that asked for PygameContext meant pygame,
            # whatever its base declared.
            definition.windowsystem = cls.windowSystemName
        return definition

    def setDefinition(
        self, definition: ContextDefinition | Mapping[str, Any] | None,
        **named: Any,
    ) -> ContextDefinition:
        """Resolve and store the definition this context is created from.

        See :meth:`resolveDefinition`; an instance that set one on itself
        before calling up is honoured too.
        """
        if definition is None:
            definition = self.__dict__.get('contextDefinition')
        self.contextDefinition = definition = self.resolveDefinition(
            definition, **named)
        self.coreProfile = definition.profile == "core"
        return definition

    def DoInit(self) -> None:
        """Call the OnInit method with this context current

        :meth:`completeInit` calls this once there is a GL context to run
        ``OnInit`` in.

        Redraws asked for while OnInit runs are **deferred**.  A forced
        triggerRedraw() draws immediately when it can, and during OnInit it can
        -- so a context that adds a HUD layer or reports its progress would
        re-enter OnDraw against a scenegraph it has not built yet.  The request
        itself is kept: the context is left needing a frame, and the first real
        one satisfies it.

        Deferral is put back as it was found rather than switched off, because
        it is not only start-up that wants it: a main loop defers for the whole
        session so that a burst of input costs one frame, and a window system
        that waits for its window to be shown runs this from inside that loop.
        """
        self.setCurrent()
        deferred = self.deferRedraw
        self.deferRedraw = True
        try:
            self.OnInit()
        finally:
            self.deferRedraw = deferred
            self.unsetCurrent()

    ### Customisation points
    def setupCallbacks(self) -> None:
        """Customization point: bind this context's own event handlers

        Subclasses and applications register handlers here, through
        :meth:`addEventHandler`, for the events they are interested in.  The
        window system has already connected the toolkit's callbacks, which
        arrive as the same events whichever toolkit it is.

        This runs **after** :meth:`setupDefaultEventCallbacks`, and a key can
        have only one handler, so a binding made here wins over the default for
        the same key.  Claiming a key the framework also binds is simply binding
        it.

        The default implementation does nothing.
        """

    def setupCache(self) -> None:
        """Setup caching structures for content

        This includes the general compiled-geometry caches
        and the texture cache
        """
        self.textureCache = texturecache.TextureCache()
        self.cache = cache.Cache()

    def setupExtensionManager(self) -> None:
        """Create an extension manager for this context"""
        from OpenGLContext import extensionmanager

        self.extensions = extensionmanager.ExtensionManager()

    def setupDefaultEventCallbacks(self) -> None:
        """Setup common callbacks for the context

        You might override it to provide other default callbacks, but
        you'll normally want to call the base-class implementation somewhere
        in that overridden method.

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

    def OnEscape(self, event: Any = None) -> None:
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

    def OnQuit(self, event: Any = None) -> None:
        """Close the window, and quit the application (forcibly) if it is one

        The window system lets its window and the GL objects in it go
        **here** rather than after the loop, because what follows ends the
        process with ``os._exit``: nothing after it runs, no ``finally`` and
        no ``atexit`` hook, and closing the window or pressing Escape is the
        path a user actually takes.

        A view embedded in somebody else's application is closed and this
        returns, since closing a view must not take the host program down;
        :meth:`OpenGLContext.windowsystem.WindowSystem.quit` answers which
        this is.
        """
        self.suppressRedraw()
        if not self.windowsystem.quit():
            return

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
        self.stopCaptureClock()

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

        os._exit(0)  # noqa: TID251 the streams are flushed above; the testing package's exit helper is not imported by a shipped context

    def wantsMoreFrames(self) -> bool:
        """Whether anything in this context still needs another frame drawn.

        A windowed backend never asks: it draws until the user closes the
        window. An offscreen one has no user, so it draws ``frameCount`` frames
        and returns -- and this is how something that cannot say in advance how
        many frames it needs keeps the loop going. A settle capture draws until
        the scene has converged and a recording until it has enough frames;
        neither knows the number when the loop starts.

        Answered by each mixin that has an opinion, passing the question on
        rather than replacing the answer, since a viewer may be recording and
        capturing at once.
        """
        return False

    def OnFrameRate(self, event: Any = None) -> None:
        """Show or hide the developer overlay, where the frame rate is drawn"""
        self.toggleDebugOverlay()

    def OnViewpointsChanged(self, paths: Any) -> None:
        """The scene's ``Viewpoint`` nodes are now these node-paths.

        Called by the render pass on the frame it first finds a different set
        -- a world or model loaded, a camera added or removed -- with every path
        in the order the pass found them; ``SceneGraph.viewpointPaths`` holds
        the same. Does nothing here; a window that offers the scene's cameras
        (:func:`OpenGLContext.multiview.viewpoints.scene_cameras`) overrides it.
        """

    def OnNextViewpoint(self, event: Any = None) -> None:
        """Go to the next viewpoint for the scenegraph"""
        sg = self.getSceneGraph()
        if sg:
            current = getattr(sg, "boundViewpoint", None)
            if current:
                current.isBound = False
                current.set_bound = False
        self.triggerRedraw(1)

    def setupThreading(self) -> None:
        """Setup primitives (locks, events) for threading"""
        global contextThread
        if threading:
            contextThread = threading.current_thread()
            contextThread.name = "GUIThread"
        self.setupScenegraphLock()
        self.setupRedrawRequest()

    def setupFrameRateCounter(self) -> None:
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

    def setupLoopTrace(self) -> None:
        """Setup the main loop's wall-clock instrumentation

        This sets self.loopTrace to a looptrace.LoopTrace, which
        measures how long each pass of the backend's main loop takes
        and where that time went. It is the counterpart to the frame
        counter rather than a duplicate of it: the counter reports how
        fast the renderer is, and this reports how fast the whole loop
        is, which is what the user's hands feel.

        The window system's loop drives it (see
        OpenGLContext.windowsystem.WindowSystem.loopIteration); OnDraw divides
        its share into the event cascade and the render.  A loop that does
        not drive it -- a host application stepping the view some other way --
        leaves the iteration count at zero, and the developer overlay then
        omits the section rather than reporting nothing as if it were idle.

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

    def setupEntropy(self) -> int:
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

    def setupTelemetry(self) -> None:
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

    def mark(self, name: str, /, **fields: Any) -> None:
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

    def reachedMark(self, name: str) -> bool:
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

    def overdueMark(self, name: str) -> bool:
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

    def startTelemetry(self, path: str | None = None,
                       **named: Any) -> SessionRecording:
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

    def stopTelemetry(self, reason: str = 'stopped') -> None:
        """Finish any recording or replay in progress"""
        session = self.telemetry
        if session is not None:
            try:
                session.close(reason)
            except Exception:
                log.debug('could not close the session recording', exc_info=True)
            self.telemetry = None

    def tracePhase(self, name: str) -> AbstractContextManager[None]:
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

    def setupRedrawRequest(self) -> None:
        """Setup the redraw-request (threading) event"""
        if threading:
            self.redrawRequest = threading.Event()

    def setupScenegraphLock(self) -> None:
        """Setup lock to protect scenegraph from updates during rendering"""
        if threading:
            self.scenegraphLock = threading.RLock()

    def lockScenegraph(self, blocking: int = 1) -> None:
        """Lock scenegraph locks to prevent other update/rendering actions

        Potentially this could be called from a thread other than the
        GUI thread, allowing the other thread to update structures in
        the scenegraph without mucking up any active rendering pass.
        """
        if threading:
            self.scenegraphLock.acquire(bool(blocking))

    def unlockScenegraph(self) -> None:
        """Unlock scenegraph locks to allow other update/rendering actions

        Potentially this could be called from a thread other than the
        GUI thread, allowing the other thread to update structures in
        the scenegraph without mucking up any active rendering pass.
        """
        if threading:
            self.scenegraphLock.release()

    def setCurrent(self, blocking: int = 1) -> None:
        """Set the OpenGL focus to this context

        Takes the context lock and the scenegraph lock, then has the window
        system make its GL context current and tells PyOpenGL which one that
        is (:meth:`bindContextResources`).
        """
        assert inContextThread(), (
            """setCurrent called from outside of the context/GUI thread! %s"""
            % (threading.current_thread())
        )
        if not contextLock.acquire(bool(blocking)):
            raise LockingError("""Cannot acquire without blocking""")
        Context.currentContext = _composed(self)
        self.lockScenegraph()
        self.bindContextResources(self.windowsystem.makeCurrent())

    def unsetCurrent(self) -> None:
        """Give up the OpenGL focus from this context"""
        assert inContextThread(), (
            """unsetCurrent called from outside of the context/GUI thread! %s"""
            % (threading.current_thread())
        )
        self.unlockScenegraph()
        Context.currentContext = None
        contextLock.release()

    #: The GL context handle this context last bound, so a *foreign* one -- a
    #: context belonging to another window system in the same process -- can be
    #: told from its own.  See :meth:`releaseForeignContext`.
    _ownContext: Any = None

    def releaseForeignContext(self) -> bool:
        """Let go of a context this one does not own; answer whether there was one

        **A thread may hold one GL context, and a platform's binding APIs do not
        know about each other.**  On Linux, asking EGL for a thread a GLX
        context holds is ``EGL_BAD_ACCESS``, and the reverse is an X
        ``BadAccess`` that Xlib's default error handler turns into a *process
        exit* -- not an exception anything could answer.

        Two window systems alive in one process is not an unusual arrangement:
        this engine's own suite runs on one while several tests open a window
        through another, and an application embedding a second renderer has
        the same shape.  So a window system says "let go" before it takes the
        thread, and the cost is one query where the context already current is
        its own.
        """
        from OpenGL import platform

        try:
            current = platform.PLATFORM.GetCurrentContext()
        except Exception:               # pragma: no cover - no GL at all
            return False
        if not current or sameContext(current, self._ownContext):
            return False
        return bool(platform.PLATFORM.releaseCurrentContext())

    def bindContextResources(self, handle: Any = None) -> None:
        """Say that ``handle`` is the GL context this thread now draws through.

        PyOpenGL gives each context its own table of resolved entry-point
        addresses, and this is what tells it which one to dispatch through.
        Without it the table is re-read only when an entry point needs
        resolving, so two contexts of differing capability can share a
        resolution that is right for one of them.

        :meth:`setCurrent` calls this with the handle the window system
        answers; ``None`` where it has no handle to give, which costs nothing.
        """
        if handle is None:
            return
        self._ownContext = handle
        from OpenGL import _dispatch

        _dispatch.make_current(handle)

    def releaseContextResources(self, handle: Any = None) -> None:
        """Say that this context is going away, **while it is still current**.

        Two things are holding its GL names.  :mod:`OpenGLContext.contextresources`
        tells the engine's own caches -- the render pass, the shader programs,
        the teapot's vertex arrays, the text renderers -- which is the moment
        they can still *delete* what they hold rather than merely forget it.
        And PyOpenGL retires its dispatch table for the context, so a handle the
        driver hands out again does not arrive with the dead context's function
        pointers already in it.

        Every window system calls this as it destroys a window, before the
        context goes, with the handle of the context now current.  Where that is
        not this context's own (``None``, or another window's, because this one
        could not be made current again), the caches are told this context's
        key instead, and forget its names without deleting any in the context
        that is current.  A window system that never named its handle
        (:meth:`bindContextResources`) is taken to have its context current.
        """
        from OpenGL import _dispatch

        own = getattr(self, '_ownContext', None)
        if own is None or (handle is not None
                           and (handle == own or sameContext(handle, own))):
            contextresources.context_lost()
            if handle is not None:
                _dispatch.forget_context(handle)
            return
        contextresources.context_lost(contextresources.key_for(own))
        _dispatch.forget_context(own)

    @classmethod
    def ContextMainLoop(cls, *args: Any, **named: Any) -> Any:
        """Make a context of this class and run its main loop

        The entry point of a program that is one window.  The arguments are
        the constructor's.  The window system the definition names runs it
        (:meth:`OpenGLContext.windowsystem.WindowSystem.run`), since a toolkit
        that needs an application object before it can make a window has to
        make that first.
        """
        definition = named.get('definition', args[0] if args else None)
        fields = {key: value for key, value in named.items()
                  if key not in ('definition', 'parent')}
        chosen = cls.chooseWindowSystem(cls.resolveDefinition(definition, **fields))
        return _windowsystem.load(chosen).run(
            cast('type[Context]', cls), *args, **named)

    def MainLoop(self) -> Any:
        """Run the window system's loop until the window is closed

        An offscreen window system draws :attr:`frameCount` frames, or as many
        as :meth:`wantsMoreFrames` asks for, and returns.  The window is let
        go of on the way out.
        """
        return self.windowsystem.mainLoop()

    def profiledMainLoop(self) -> Any:
        """:meth:`MainLoop`, under ``cProfile`` where the definition names a
        ``profileFile`` to write the profile to."""
        definition = self.contextDefinition
        if definition is not None and definition.profileFile:
            import cProfile
            return cProfile.runctx(
                "self.MainLoop()", globals(), {'self': self},
                definition.profileFile,
            )
        return self.MainLoop()

    def closeJournals(self, reason: str) -> None:
        """Finish the stall journal and any session recording, for ``reason``

        A loop left while it was still slow -- a closed window, a Ctrl-C --
        holds an episode nobody has written, and what the recording holds of
        the last few seconds is exactly what a session that ended badly is
        worth reading for.
        """
        if self.stallJournal is not None:
            self.stallJournal.close()
        self.stopTelemetry(reason)

    def loopIteration(self) -> bool:
        """One pass of the main loop; False once the loop is over

        For a host application that owns its toolkit's loop and drives the
        view from a timer of its own.  See
        :meth:`OpenGLContext.windowsystem.WindowSystem.loopIteration`.
        """
        return self.windowsystem.loopIteration()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exception: Any) -> Literal[False]:
        self.releaseWindow()
        return False

    def OnInit(self) -> None:
        """Customization point for scene set up and initial processing

        You override this method to do housekeeping chores such as
        loading images and generating textures, loading pre-established
        geometry, spawning new threads, etc.

        Called with this context current once its window has a GL context,
        which is at the end of ``Context.__init__`` for every window system
        but those that wait for the window to be shown first.  See
        :meth:`completeInit`.
        """

    def OnIdle(self, *arguments: Any) -> int:
        """Animation hook, called once per pass of the main loop

        The loop draws the frame itself after this, so the default does
        nothing.  A context that animates overrides it to advance its state
        and call :meth:`triggerRedraw`.
        """
        return 0

    def OnDraw(self, force: int = 1, *arguments: Any) -> int:
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

        # A capture's world moves on by one frame per call, before the cascade
        # that reads the clock.  Unconditionally: a scene whose only change is
        # the one a timer drives would otherwise return early below, leaving
        # the clock where it was and the animation stopped.
        if self._captureClock is not None:
            self._captureClock.advance()

        # Check for auto-exit on each OnDraw call, even if we return early
        # This ensures we count total calls rather than just rendered frames
        if self._autoExitFrames is not None:
            self._autoExitFrameCount += 1
            if self._autoExitFrameCount >= self._autoExitFrames:
                log.info(f"Auto-exit: {self._autoExitFrameCount} OnDraw calls")
                self._autoExitDraw()
                self.OnQuit()
                return 0

        self.lockScenegraph()
        try:
            with self.tracePhase('cascade'):
                changed = self.DoEventCascade()
            due = self.redrawFallsDue()
            if not force and not changed and not due:
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
                # OnQuit normally ends the process here; a context that has
                # given it another meaning reports the frame as unchanged.
                self.OnQuit()
                return 0
        finally:
            glFlush()
            self.drawing = None
            self.unsetCurrent()

    def drawPoll(self, timeout: float | None = None) -> int:
        """Wait timeout seconds for a redraw request

        timeout -- timeout in seconds, if None, use
            self.drawPollTimeout

        returns 0 if timeout, 1 if true
        """
        if timeout is None:
            timeout = self.drawPollTimeout
        if threading:
            self.redrawRequest.wait(timeout)
            if self.redrawRequest.is_set():
                self.OnDraw(force=1)
                return 1
            else:
                self.OnDraw(force=0)
                return 1
        return 0

    def Render(self, mode: Any = None) -> None:
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

    def OnResize(self, width: int, height: int) -> None:
        """Draw at the window's new size, in the pixels the viewport counts

        The window system calls this when its window has been resized.  A
        pbuffer, which has a fixed size, is made again at this one.
        """
        width, height = self.windowsystem.resize(int(width), int(height))
        self.ViewPort(width, height)
        self.triggerRedraw(1)

    def triggerPick(self) -> None:
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

    def setFullscreen(self, fullscreen: bool) -> bool:
        """Fill the screen, or go back to a window; answer whether it happened.

        False is how a caller finds out that a key or a settings toggle has
        nothing to offer on this window system: the
        :attr:`ContextDefinition.fullscreen` field still decides how the window
        is *opened*.
        """
        return self.windowsystem.setFullscreen(bool(fullscreen))

    def setPointerCapture(self, capture: bool) -> bool:
        """Hide and grab the pointer for mouse-look; answer whether it happened.

        Mouse-look needs *unbounded* motion: a pointer that stops at the edge of
        the screen is a view that stops turning there.  What provides it differs
        -- a relative-motion mode, a grab, or warping the pointer back to the
        middle of the window after every movement -- so each window system
        does it its own way.

        False means the caller should not offer mouse-look as though it worked;
        see
        :meth:`OpenGLContext.move.viewplatformmixin.ViewPlatformMixin.updateNavigation`,
        which is what asks.
        """
        return self.windowsystem.setPointerCapture(bool(capture))

    def applyVSync(self, definition: ContextDefinition | None = None) -> bool:
        """Wait for the display's refresh, or don't; answer whether it happened.

        Off uncaps the frame rate, which is what a benchmark wants.  The field
        is :attr:`ContextDefinition.vsync` and the settings screen writes it, so
        a window system that can change the swap interval of a live context
        re-reads it here.  One that cannot -- where the interval is part of a
        surface format settled when the context was created -- answers False,
        and the change takes effect in the next window.
        """
        source = self.contextDefinition if definition is None else definition
        return bool(self.windowsystem.applyVSync(source))

    def releaseWindow(self) -> None:
        """Let this context's window, and the GL objects in it, go.

        The caches holding this context's GL names are told first, then the
        window is destroyed.  Calling it twice is calling it once.

        It is what :meth:`OnQuit` does before the process ends, and what a
        program that built a context and is finished with it calls.
        """
        self.windowsystem.release()

    def pumpWindowEvents(self) -> bool:
        """Let the window system deliver whatever it has queued; False if it
        cannot.

        For a program driving its own loop rather than calling ``MainLoop`` --
        a benchmark, a headless probe, a host application stepping the view
        from its own timer.  A window that is never pumped is one some
        platforms decide has stopped responding, and it never sees a keystroke
        or a resize.  An offscreen window system has nothing to deliver and
        answers False.
        """
        return self.windowsystem.pump()

    def setVSync(self, wait: bool) -> bool:
        """Wait for the display's refresh from now on, or stop waiting.

        Writes :attr:`ContextDefinition.vsync` and asks the backend to act on
        it; answers whatever :meth:`applyVSync` did, so a caller learns whether
        this platform could.

        **This is the call an application makes.**  Uncapping the frame rate is
        what a benchmark wants, and what a headless capture *needs*: a forced
        redraw blocks on a buffer swap that nobody is presenting, so a probe
        renders one frame and then waits for ever.  Reaching for a particular
        toolkit's swap-interval call instead does nothing on any other backend.
        """
        definition = self.contextDefinition
        if definition is None:
            return False        # no definition to write the preference on yet
        definition.vsync = bool(wait)
        return bool(self.applyVSync())

    def settingsChanged(self) -> None:
        """The context definition has been edited; re-read what is not per-frame.

        Most rendering options are read by the render pass every frame (see
        :mod:`OpenGLContext.renderoptions`), so a change shows up on its own.
        The few that are set once on the window -- the swap interval, whether
        it fills the screen -- are re-applied by the window system; anything
        that cannot be changed without a new context is left alone.

        Called by the settings screen when Apply is pressed.
        """
        if self.contextDefinition is not None:
            self.windowsystem.settingsChanged(self.contextDefinition)
        self.triggerRedraw(1)

    def flushPendingPicks(self) -> int:
        """Deliver every pick still in flight, waiting for the GPU, and say how many.

        Pick readback is asynchronous: the selection pass asks the GPU for the
        object under the cursor and dispatches the click a frame or more later,
        once the answer has landed, so that a frame never stalls on a readback.
        How many frames that takes is a property of how busy the machine is.

        Call this where the answer is needed before going on rather than
        whenever it arrives -- a click that decides what to do next, a test
        asserting the click was delivered -- having drawn the frame that took
        the event.  It blocks, which is the cost of asking.

        Returns how many readbacks it waited for, which is 0 where none was
        outstanding -- a context that has not drawn yet, one picking
        synchronously, or one whose readback landed during the frame.  The
        click is delivered in that last case too: an event dispatched while the
        context is drawing goes on the event cascade queue rather than to its
        handler, and this empties that queue as a frame would.
        """
        pass_ = renderpass.current_pass()
        flush = getattr(pass_, 'flushAsyncPicks', None)
        delivered: int = flush() if flush is not None else 0
        self.DoEventCascade()
        return delivered

    def redrawAt(self, when: float) -> None:
        """Draw a frame once the session clock reaches ``when``.

        For what changes with time alone, in a window that draws only when
        something happens: a tooltip due after the pointer has rested, say.
        ``when`` is on :func:`OpenGLContext.events.systemtime.systemTime`'s
        clock. The earliest time asked for stands until a frame is drawn at or
        after it. The frame comes from the loop's next :meth:`OnDraw` once the
        time has passed, so it is as prompt as the backend's idle polling.
        """
        when = float(when)
        if self.redrawDue is None or when < self.redrawDue:
            self.redrawDue = when

    def redrawFallsDue(self) -> bool:
        """Whether a frame :meth:`redrawAt` asked for is owed now; clears it if so."""
        due = self.redrawDue
        if due is None:
            return False
        from OpenGLContext.events import systemtime
        if systemtime.systemTime() < due:
            return False
        self.redrawDue = None
        return True

    def triggerRedraw(self, force: int = 0) -> None:
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

    def shouldRedraw(self) -> bool:
        """Return whether or not the context contents need to be redrawn"""
        return not self.alreadyDrawn

    def suppressRedraw(self) -> None:
        """Indicate to the context that there is no need to re-render

        This method signals to the context that there are no updates
        currently requiring redrawing of the context's contents.

        See:
            Context.shouldRedraw and Context.triggerRedraw
        """
        self.alreadyDrawn = 1

    def presentFrame(self) -> Any:
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

    def SwapBuffers(self) -> None:
        """Put the back buffer on the screen, through the window system.

        What :meth:`presentFrame` calls.  An offscreen window system has
        nothing to present to, and finishes the frame so it can be read back.
        """
        self.windowsystem.swap()

    def ViewPort(self, width: int, height: int) -> None:
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

    def setPointerShape(self, name: str) -> bool:
        """Show the pointer ``name``; False where this window system cannot.

        The names are :data:`CURSORS`, and ``''`` is the ordinary pointer.
        What a control wants is
        :attr:`OpenGLContext.ui.widgets.Widget.cursor`, and the overlay asks
        for it as the pointer crosses the window.

        A window system answers False for a shape it has no picture for and
        leaves the pointer as it is, so the caller can show the same thing
        another way: the splitters draw a grip, since a cursor theme need not
        carry a resize pointer.
        """
        return self.windowsystem.setPointerShape(str(name or ''))

    #: The views this context draws, or None for one view through its own
    #: view platform; :meth:`getViewLayout` makes that layout on first use.
    #: Assign a :class:`~OpenGLContext.multiview.views.ViewLayout` to draw several.
    viewLayout: 'ViewLayout | None' = None

    def getViewLayout(self) -> 'ViewLayout':
        """The :class:`~OpenGLContext.multiview.views.ViewLayout` this context draws.

        One view through :meth:`getViewPlatform` unless the application has
        assigned :attr:`viewLayout`; see ``docs/multiview.rst``.
        """
        if self.viewLayout is None:
            from OpenGLContext.multiview.views import ViewLayout
            self.viewLayout = ViewLayout.single()
        return self.viewLayout

    def routeEvent(self, event: Any) -> 'View | None':
        """The view ``event`` belongs to, which is also recorded as ``event.view``.

        The view under the pointer, the one a held button's press began in,
        or for an event with no position the active view; see
        :meth:`OpenGLContext.multiview.views.ViewLayout.route`. An event already
        routed keeps its view; see
        :meth:`OpenGLContext.multiview.views.ViewLayout.view_of`.
        """
        return self.getViewLayout().view_of(event)

    def getViewPort(self) -> tuple[int, int]:
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

    def addPickEvent(self, event: Any) -> None:
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
        self.routeEvent(event)
        cd = self.contextDefinition
        if cd is not None and not cd.pickEnabled:
            return
        key = getattr(event, 'getPickKey', event.getKey)()
        self.pickEvents[(event.type, key)] = event

    def getPickEvents(self) -> dict[tuple[str, Any], Any]:
        """Get the currently active pick-events"""
        return self.pickEvents

    def hasMouseMoveHandlers(self) -> bool:
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

    def sceneBounds(self) -> tuple[Point, float] | None:
        """``(centre, radius)`` around this context's scene, or None.

        What is on screen and how big it is -- for framing a camera on it, or
        for choosing the point a drag should pivot about.
        """
        from OpenGLContext.scenegraph.boundingvolume import boundingSphere
        sg = self.getSceneGraph()
        if sg is None:
            return None
        return boundingSphere(getattr(sg, 'children', None) or ())

    def sceneBox(self) -> tuple[Point, Point] | None:
        """``(minimum, maximum)``, the corners of the box round this context's scene, or None.

        What the views are fitted to: the box keeps a scene's proportions,
        where :meth:`sceneBounds`'s sphere is as tall and as deep as it is long.
        """
        from OpenGLContext.scenegraph.boundingvolume import boundingBox
        sg = self.getSceneGraph()
        if sg is None:
            return None
        return boundingBox(getattr(sg, 'children', None) or ())

    def examineCenter(self, event: Any) -> Any:
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
    def _withinScene(point: Point, bounds: tuple[Point, float] | None) -> bool:
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

    def getSceneGraph(self) -> Any:
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

    def renderedChildren(self, types: Any = None) -> tuple[Any, ...]:
        """Get the rendered children of the scenegraph"""
        sg = self.getSceneGraph()
        if not sg:
            return (ContextRenderNode,)
        else:
            return (sg,)


    #: What ``[context] type`` may name in a configuration file.  One
    #: :class:`Context` has every capability each of these once named, so
    #: they are accepted and mean the same thing.
    CONFIG_CONTEXT_TYPES = ('context', 'interactive', 'vrml')

    @staticmethod
    def fromConfig(cfg: ConfigParser) -> type[Context] | None:
        """Given a ConfigParser instance, produce a configured sub-class

        The window's own fields come from the ``[contextdefinition]``
        section, and ``[context] gui`` names the window system where that
        section's ``windowsystem`` does not.  ``[context] type`` is accepted
        as one of :attr:`CONFIG_CONTEXT_TYPES`.

        Returns ``None`` when the named window system cannot be loaded, and
        raises ``ValueError`` when the named type is not one there is.
        """
        from OpenGLContext import contextdefinition

        if cfg.has_option("context", "type"):
            typeKey = cfg.get("context", "type")
            if typeKey not in Context.CONFIG_CONTEXT_TYPES:
                raise ValueError(
                    "%r is not a context type; expected one of %s"
                    % (typeKey, ", ".join(
                        repr(name) for name in Context.CONFIG_CONTEXT_TYPES)))
        definition = contextdefinition.ContextDefinition.fromConfig(cfg)
        if cfg.has_option("context", "gui") and not definition.windowsystem:
            definition.windowsystem = cfg.get("context", "gui")
        try:
            Context.chooseWindowSystem(definition)
        except _windowsystem.WindowSystemUnavailable as err:
            log.warning("The configured window system is not usable: %s", err)
            return None
        return type("TestingContext", (Context,), {"contextDefinition": definition})


class Context(OverlayStackMixin, MultiViewMixin, ViewPlatformMixin, EventHandlerMixin,
              VRMLSceneMixin, ContextCore):
    """A rendering context: a window, the GL context in it, and a scene

    The Context object represents a single rendering context for use by the
    application.  An application subclasses it, overrides the customisation
    points (``OnInit``, ``Render``, ``OnIdle``, ``setupCallbacks``...) and
    runs it with :meth:`ContextMainLoop`::

        class Viewer(Context):
            def OnInit(self):
                self.sg = Loader.load('world.glb')

        Viewer.ContextMainLoop(windowsystem='glfw', size=(800, 600))

    The window it draws in belongs to a
    :class:`~OpenGLContext.windowsystem.WindowSystem` it holds, chosen by the
    definition's ``windowsystem`` field; see :mod:`OpenGLContext.windowsystem`
    and ``docs/backends.rst``.  Every context has the overlay stack of
    :class:`~OpenGLContext.ui.overlay.OverlayStackMixin`, the event managers of
    :class:`~OpenGLContext.events.eventhandlermixin.EventHandlerMixin`, the
    camera and movement modes of
    :class:`~OpenGLContext.move.viewplatformmixin.ViewPlatformMixin`, the
    views of :class:`~OpenGLContext.multiview.mixin.MultiViewMixin` and the
    scene loading of :class:`~OpenGLContext.vrmlcontext.VRMLSceneMixin`, on
    top of what :class:`ContextCore` describes; the definition's
    ``navigation`` says which modes and views it has.
    """

    def emitKey(self, key: Any, state: int, modifiers: Any) -> None:
        """Send one key transition the window system did not report

        The held-key tracking of
        :class:`~OpenGLContext.events.eventhandlermixin.HeldKeyMixin` calls
        this for the releases focus loss never delivers and the repeats a
        platform does not make; the window system builds its own toolkit's
        event for it.
        """
        self.windowsystem.emitKey(key, state, modifiers)


### Context render-calling child...
class _ContextRenderNode(nodetypes.Rendering, nodetypes.Children, node.Node):
    """The Context object as a RenderNode

    Returned as the child of the Context if there
    is no getSceneGraph() result.
    """

    def Render(self, mode: Any) -> Any:
        """Delegate rendering to the mode.context.Render method"""
        return mode.context.Render(mode)

    def sortKey(self, passes: Any, matrix: Any) -> tuple[Any, ...]:
        return (0, None)


ContextRenderNode = _ContextRenderNode()


def getCurrentContext() -> Context | None:
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
