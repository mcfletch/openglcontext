"""A view in a Tkinter window

Tkinter ships with CPython, so this is the window system a project can use
without adding a GUI toolkit to its dependencies.  ``context.window`` is an
:class:`OpenGL.Tk.GLFrame` -- an ordinary ``tkinter.Frame`` with a GL context
of its own, made through the platform's own API -- so a context here can
either own the whole window or sit as one widget beside an application's other
controls.  See ``OpenGL/Tk/`` in PyOpenGL.

To put a view inside an existing Tk application, build the context with the
widget that is to hold it::

    context = Context(windowsystem='tk', parent=someFrame)
    context.window.pack(fill='both', expand=True)

and drive it from the application's own ``mainloop`` by calling
``context.loopIteration()`` from an ``after`` callback, or let ``MainLoop`` own
the loop when the context is the application.
"""
from __future__ import annotations

import logging
import tkinter
from collections.abc import Hashable
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from OpenGLContext import renderoptions
from OpenGLContext.events import keyboardevents
from OpenGLContext.events.tkevents import (
    X11_WHEEL_BUTTONS, WHEEL_DELTA, keyName, modifiersOf, tkKeyboardEvent,
    tkKeypressEvent, tkMouseButtonEvent, tkMouseMoveEvent, tkWheelEvent,
)
from OpenGLContext.events.wheel import WheelNotches
from OpenGLContext.windowsystem.base import WindowSystem, wantsVSync

try:
    from OpenGL.Tk import ContextAttributes, GLFrame
except ImportError as err:              # pragma: no cover - an old PyOpenGL
    raise ImportError(
        "The Tk GL widget is required for the Tk window system; it needs "
        "PyOpenGL 4 or newer, and tkinter: %s" % (err,)
    ) from err

if TYPE_CHECKING:
    from OpenGLContext.contextdefinition import ContextDefinition

log = logging.getLogger(__name__)

#: How many milliseconds Tk waits between the frames the loop drives.  Small
#: enough that the loop is not the thing limiting the frame rate; the frame's
#: own work is what paces it.
FRAME_INTERVAL = 1


def attributesFromDefinition(definition: Any) -> ContextAttributes:
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
            "The Tk window system provides no accumulation buffer; ignoring "
            "the %d bits requested", definition.accumulationBuffer,
        )
    major, minor = (int(value) for value in definition.version)
    return ContextAttributes(
        profile=definition.profile,
        version=(major, minor) if major else None,
        doubleBuffer=bool(definition.doubleBuffer),
        alphaSize=8 if definition.alpha else 0,
        depthSize=definition.depthBuffer if definition.depthBuffer > -1 else 24,
        stencilSize=max(0, definition.stencilBuffer),
        samples=max(0, definition.multisampleSamples),
        stereo=definition.stereo > 0,
        debug=bool(definition.debug),
    )


class TkWindowSystem(WindowSystem):
    """A GLFrame in a Tk window, and the translation of its events

    Rendering is driven from a Tk timer rather than from expose events: the
    engine's frame is an event cascade followed by a render, only the cascade
    always runs -- animations, timers and queued events live there -- and only
    sometimes is there anything new to draw.
    """

    name = 'tk'
    acceptsParent = True
    pollsEvents = False

    #: Tk's cursor names, by the name a control asks for. Tk takes the X11
    #: names on every platform and maps them to the native pointer, so these
    #: are the spellings rather than a picture this has to carry. The X11 set
    #: has no "not allowed" pointer, so ``'no'`` is refused.
    CURSOR_SHAPES: ClassVar[dict[str, str]] = {
        'arrow': '',
        'hand': 'hand2',
        'text': 'xterm',
        'crosshair': 'crosshair',
        'resize-x': 'sb_h_double_arrow',
        'resize-y': 'sb_v_double_arrow',
        'resize': 'fleur',
    }

    window: Optional[GLFrame] = None
    #: The toplevel this window system created, or None where it was given a
    #: parent to sit inside.
    root: Optional[tkinter.Tk] = None
    #: The pending ``after`` callback that drives the next frame.
    frameJob: Optional[str] = None
    #: True while the pointer is hidden and being warped back to the middle of
    #: the window for a mouse-look mode.
    pointerGrabbed = False
    #: Where the pointer was last warped to, so the movement the warp itself
    #: generates can be told from a real one.
    pointerWarpedTo: Optional[tuple[int, int]] = None
    #: Counts a stream of ``<MouseWheel>`` reports into whole notches.
    wheelCounter: Optional[WheelNotches] = None

    # -- lifetime ----------------------------------------------------------

    def open(self, definition: ContextDefinition, parent: Any = None) -> bool:
        width, height = [int(value) for value in definition.size]
        if parent is None:
            self.root = parent = tkinter.Tk()
            self.root.title(definition.title or self.context.getApplicationName())
            self.root.geometry('%dx%d' % (width, height))
            self.root.protocol('WM_DELETE_WINDOW', self.context.OnQuit)
        frame = self.window = GLFrame(
            parent, attributes=attributesFromDefinition(definition),
            width=width, height=height,
        )
        frame.pack(fill=tkinter.BOTH, expand=tkinter.YES)
        frame.focus_set()
        # A window has no native handle until the window system has mapped it,
        # so there is nothing to make a context against before then; OnInit
        # runs inside the constructor as it does under every other window
        # system, and it needs a current context to build textures and shaders.
        frame.waitForMap()
        self.applyHidden()
        self.applyVSync(definition)
        return True

    def applyHidden(self) -> bool:
        """Take the window off the screen where the environment asked for that

        ``OPENGLCONTEXT_HIDDEN`` is for a capture subprocess and for a suite of
        GL scripts that should not take over the screen of whoever is running
        it.  It is applied **after** the context exists: a Tk window that was
        never mapped has no native window for one to be made against, so this
        is a window that appeared and then went rather than one that never
        appeared.  Rendering and reading back are unaffected, since both happen
        in the back buffer.

        A view sitting inside somebody else's application is left alone: the
        window is not this context's to withdraw.
        """
        if self.root is not None and renderoptions.hidden_window():
            self.root.withdraw()
            self.root.update()
            return True
        return False

    def release(self) -> None:
        """Drop the context's GL objects and let the widget go"""
        frame, self.window = self.window, None
        if frame is None:
            return
        self.stopFrameTimer(frame)
        if frame.makeCurrent():
            self.context.releaseContextResources(self.glHandle())
        else:
            self.context.releaseContextResources(None)
        frame.destroyContext()
        root, self.root = self.root, None
        if root is not None:
            try:
                root.destroy()
            except tkinter.TclError:
                pass                    # the interpreter is already going

    def quit(self) -> bool:
        """Close the view; the application ends only if it is this window

        A view embedded in somebody else's Tk application is a view inside it,
        and closing a view must not take the host program down.
        """
        ownsApplication = self.root is not None
        super().quit()
        return ownsApplication

    # -- current and presenting --------------------------------------------

    def makeCurrent(self) -> Optional[Hashable]:
        if self.window is None:
            return None
        self.context.releaseForeignContext()
        self.window.makeCurrent()
        return self.glHandle()

    def swap(self) -> None:
        if self.window is not None:
            self.window.swapBuffers()

    def drawableSize(self) -> tuple[int, int]:
        assert self.window is not None
        return int(self.window.winfo_width()), int(self.window.winfo_height())

    def applyVSync(self, definition: Any) -> bool:
        """Set the swap interval from ``definition.vsync``

        Answers whether it was set; the platform's own swap-control extension
        is what does it, and there is not one everywhere.
        """
        if self.window is None:
            return False
        return bool(self.window.setSwapInterval(1 if wantsVSync(definition) else 0))

    # -- requests of the window --------------------------------------------

    def setFullscreen(self, fullscreen: bool) -> bool:
        """Fill the screen, or go back to the window this context opened with

        Tk moves a toplevel between the two without re-making anything, so the
        GL context and everything loaded into it survive the trip.  A view
        inside somebody else's window has no toplevel of its own to fill the
        screen with, and says so.
        """
        if self.root is None:
            return False
        if bool(fullscreen) == self.isFullscreen():
            return True
        self.root.attributes('-fullscreen', bool(fullscreen))
        self.root.update_idletasks()
        self.context.triggerRedraw(1)
        return True

    def isFullscreen(self) -> bool:
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

    def setPointerShape(self, name: str) -> bool:
        """Show this pointer; False for a shape Tk has no name for."""
        if self.window is None or self.pointerGrabbed:
            return False
        wanted = str(name or 'arrow')
        if wanted not in self.CURSOR_SHAPES:
            return False
        try:
            self.window.configure(cursor=self.CURSOR_SHAPES[wanted])
        except tkinter.TclError:
            return False
        return True

    def setPointerCapture(self, capture: bool) -> bool:
        """Hide the pointer and keep it in the window, for a mouse-look mode

        Tk has no relative-motion mode, so the pointer is warped back to the
        middle of the widget after every movement -- which is what makes the
        motion unbounded, since a pointer that stops at the edge of the screen
        is a view that stops turning there.  The warp arrives back as an
        ordinary movement and is recognised and dropped; see
        :meth:`onMouseMove`.
        """
        frame = self.window
        if frame is None:
            return False
        capture = bool(capture)
        self.pointerGrabbed = capture
        self.pointerWarpedTo = None
        frame.configure(cursor='none' if capture else '')
        if capture:
            frame.grab_set()
        else:
            frame.grab_release()
        # Where the pointer is means something different on each side of this,
        # so the first report afterwards establishes a position rather than
        # arriving as one flick of the view.
        self.context.forgetPointerOrigin()
        if capture:
            self.recentrePointer()
        return True

    def recentrePointer(self) -> None:
        """Put the pointer back in the middle of the widget, if it is grabbed"""
        frame = self.window
        if not self.pointerGrabbed or frame is None:
            return
        middle = (frame.winfo_width() // 2, frame.winfo_height() // 2)
        self.pointerWarpedTo = middle
        # Tk's own way of moving the pointer: a warping motion event, which the
        # server acts on rather than merely reporting.
        frame.event_generate('<Motion>', warp=True, x=middle[0], y=middle[1])

    def pointerWarpEcho(self, x: float, y: float) -> bool:
        """Whether this movement is the one :meth:`recentrePointer` caused

        A movement the program made itself is not motion the user asked for:
        left in, it cancels out every real movement and mouse-look never turns.
        """
        if self.pointerWarpedTo is None:
            return False
        echo = (int(x), int(y)) == self.pointerWarpedTo
        if echo:
            self.pointerWarpedTo = None
        return echo

    # -- the loop -----------------------------------------------------------

    def bindCallbacks(self) -> None:
        """Bind the widget's input events to this window system's handlers"""
        frame = self.window
        if frame is None:
            return
        frame.bind('<KeyPress>', self.onKeyDown)
        frame.bind('<KeyRelease>', self.onKeyUp)
        frame.bind('<FocusOut>', self.onFocusOut)
        for number in (1, 2, 3, 4, 5):
            frame.bind('<Button-%d>' % (number,), self.onMouseButton)
            frame.bind('<ButtonRelease-%d>' % (number,), self.onMouseRelease)
        frame.bind('<Motion>', self.onMouseMove)
        frame.bind('<MouseWheel>', self.onMouseWheel)
        frame.bind('<Configure>', self.onConfigure)
        # The widget's own drawing is this context's, so the frame's
        # expose-driven render is replaced rather than left to draw a scene it
        # knows nothing about.
        frame.redraw = self.drawFrame     # type: ignore[method-assign]  # GLFrame's hook, replaced per instance
        frame.reshape = self.context.OnResize     # type: ignore[method-assign]  # GLFrame's hook, replaced per instance

    def drawFrame(self) -> None:
        """What the widget draws: one engine frame

        The frame's own ``render`` makes the context current and swaps
        afterwards, and ``Context.OnDraw`` is what goes between.
        """
        self.context.OnDraw(force=1)

    def pump(self) -> bool:
        if self.window is None:
            return False
        try:
            self.window.update()
        except tkinter.TclError:
            return False                # the interpreter is already going
        return True

    def running(self) -> bool:
        frame = self.window
        return (frame is not None and not self.finished
                and frame.context is not None)

    def startFrameTimer(self) -> Optional[str]:
        """Begin the timer that drives the render loop"""
        if self.frameJob is None and self.window is not None:
            self.frameJob = self.window.after(FRAME_INTERVAL, self.frameStep)
        return self.frameJob

    def stopFrameTimer(self, frame: Optional[GLFrame] = None) -> None:
        """Stop the render loop's timer"""
        frame = frame or self.window
        job, self.frameJob = self.frameJob, None
        if job is not None and frame is not None:
            try:
                frame.after_cancel(job)
            except tkinter.TclError:
                pass                    # the interpreter is already going

    def frameStep(self) -> None:
        self.frameJob = None
        if not self.running():
            return
        self.loopIteration()
        if self.running():
            assert self.window is not None
            self.frameJob = self.window.after(FRAME_INTERVAL, self.frameStep)

    def mainLoop(self) -> Any:
        """Run Tk's event loop with this context rendering inside it"""
        if self.root is None:
            raise RuntimeError(
                "This view was built inside somebody else's window, so the "
                "main loop is theirs to run; call loopIteration from it")
        # Tk's own dispatch delivers the input, so a burst of it only flags a
        # redraw and costs one frame.
        self.context.deferRedraw = True
        self.startFrameTimer()
        try:
            self.root.mainloop()
        finally:
            self.stopFrameTimer()
            self.context.closeJournals('mainloop-ended')
            self.release()

    # -- keyboard -----------------------------------------------------------

    def onKeyDown(self, event: Any) -> None:
        context = self.context
        name = keyName(event)
        if name in context.heldKeys():
            context.noteNativeRepeat()      # already down, so Tk is repeating it
        context.noteKeyDown(name, modifiersOf(event))
        context.ProcessEvent(tkKeyboardEvent(context, event, 1))
        if event.char:
            context.ProcessEvent(tkKeypressEvent(context, event))

    def onKeyUp(self, event: Any) -> None:
        self.context.noteKeyUp(keyName(event))
        self.context.ProcessEvent(tkKeyboardEvent(self.context, event, 0))

    def onFocusOut(self, event: Any) -> None:
        """Let go of every held key as the widget loses focus

        No key-up arrives for a key that was down when focus went elsewhere, so
        without this the key stays held for the rest of the session and the
        camera keeps moving with nobody touching the keyboard.
        """
        self.context.clearHeldKeys()

    def emitKey(self, key: Any, state: int, modifiers: Any) -> None:
        """Send a key transition Tk did not report

        ``modifiers`` is the triple that came with the press, so the synthetic
        release matches the binding the press did.
        """
        context = self.context
        made = tkKeyboardEvent.__new__(tkKeyboardEvent)
        keyboardevents.KeyboardEvent.__init__(made)
        if hasattr(context, 'currentPass'):
            made.renderingPass = context.currentPass
        made.modifiers = modifiers
        made.name = key
        made.state = state
        context.ProcessEvent(made)

    # -- pointer -------------------------------------------------------------

    def onMouseButton(self, event: Any) -> None:
        """A button went down

        A wheel notch arrives here on X11, where Tk reports it as a press of
        button 4 or 5; on Windows and macOS it arrives as ``<MouseWheel>``
        instead (:meth:`onMouseWheel`).
        """
        if event.num in X11_WHEEL_BUTTONS:
            self.postWheel(event, X11_WHEEL_BUTTONS[event.num])
            return
        self.context.addPickEvent(tkMouseButtonEvent(self.context, event, state=1))
        self.context.triggerPick()

    def onMouseRelease(self, event: Any) -> None:
        if event.num in X11_WHEEL_BUTTONS:
            return                      # the notch was delivered by the press
        self.context.addPickEvent(tkMouseButtonEvent(self.context, event, state=0))
        self.context.triggerPick()

    def onMouseWheel(self, event: Any) -> None:
        """A Windows or macOS wheel report, as notches

        Tk states the rotation there rather than naming a button, so each whole
        notch becomes the press and release of one; see
        :data:`~OpenGLContext.events.mouseevents.WHEEL_UP`.
        """
        if self.wheelCounter is None:
            self.wheelCounter = WheelNotches(WHEEL_DELTA)
        for button in self.wheelCounter.notches(getattr(event, 'delta', 0)):
            self.postWheel(event, button)

    def postWheel(self, event: Any, button: int) -> None:
        """One notch, as the press and release of a button that is never held"""
        for state in (1, 0):
            self.context.addPickEvent(
                tkWheelEvent(self.context, event, button=button, state=state))
        self.context.triggerPick()

    def onMouseMove(self, event: Any) -> None:
        """The pointer moved

        The movement sampler is told directly as well as through the pick
        queue: a mouse-look mode wants every scrap of motion as it happens,
        while a pick event is only delivered once the selection buffer resolves
        it -- and not at all when the pointer is over nothing or picking is off.

        A movement the window made itself -- the warp that keeps a grabbed
        pointer in the middle of the window -- updates where the pointer is and
        goes no further: it is not motion the user asked for, and it is not a
        click on anything.
        """
        context = self.context
        echo = self.pointerWarpEcho(event.x, event.y)
        if echo:
            context.forgetPointerOrigin()
        context.recordPointerMotion(
            int(event.x), context.getViewPort()[1] - int(event.y))
        if echo:
            return
        self.recentrePointer()
        context.addPickEvent(tkMouseMoveEvent(context, event))
        context.triggerPick()

    def onConfigure(self, event: Any) -> None:
        """Follow the widget's new size with the viewport"""
        self.context.OnResize(int(event.width), int(event.height))
