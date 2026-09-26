"""A view in a wxPython window

``context.window`` is a :class:`wx.glcanvas.GLCanvas`, which an application
places in its own layout like any other window::

    view = Context(windowsystem='wx', parent=splitter)
    sizer.Add(view.window, 1, wx.EXPAND)
    view.window.SetFocus()

Given no parent, the view opens in a frame of its own; a ``wx.App`` has to
exist either way, which :meth:`WxWindowSystem.run` (and so
``ContextMainLoop``) makes.

wxPython on GTK3 makes its GL context through EGL rather than GLX, and on X11
it may be either.  Which one it was is a question PyOpenGL answers for itself:
its Linux platform loads both interfaces and probes for the live context, so
nothing here has to name one (``OpenGL.platform.linux``).
"""
from __future__ import annotations

import logging
from collections.abc import Hashable
from io import BytesIO
from typing import TYPE_CHECKING, Any, ClassVar, Optional

import wx
from wx import glcanvas

from OpenGLContext import renderoptions, swapcontrol
from OpenGLContext.events import keyboardevents
from OpenGLContext.events.wheel import WheelNotches
from OpenGLContext.events.wxevents import (
    keyName, modifiersOf, wxKeyboardEvent, wxKeypressEvent, wxMouseButtonEvent,
    wxMouseMoveEvent, wxWheelEvent,
)
from OpenGLContext.windowsystem.base import WindowSystem, wantsVSync

if TYPE_CHECKING:
    from OpenGLContext.context import Context
    from OpenGLContext.contextdefinition import ContextDefinition

log = logging.getLogger(__name__)


def canvasAttributes(definition: Any) -> list[int]:
    """The canvas attribute list (``attribList``) ``definition`` asks for"""
    attributes: list[int] = []
    if definition.rgb:
        attributes.append(glcanvas.WX_GL_RGBA)
    else:
        attributes += [glcanvas.WX_GL_BUFFER_SIZE, 8]
    if definition.doubleBuffer:
        attributes.append(glcanvas.WX_GL_DOUBLEBUFFER)
    if definition.stereo > -1:
        attributes.append(glcanvas.WX_GL_STEREO)
    if definition.depthBuffer > -1:
        attributes += [glcanvas.WX_GL_DEPTH_SIZE, definition.depthBuffer]
    if definition.stencilBuffer > -1:
        attributes += [glcanvas.WX_GL_STENCIL_SIZE, definition.stencilBuffer]
    if definition.accumulationBuffer > -1:
        for flag in (
            glcanvas.WX_GL_MIN_ACCUM_RED,
            glcanvas.WX_GL_MIN_ACCUM_GREEN,
            glcanvas.WX_GL_MIN_ACCUM_BLUE,
            glcanvas.WX_GL_MIN_ACCUM_ALPHA,
        ):
            attributes += [flag, definition.accumulationBuffer]
    return attributes


def contextAttributes(definition: Any) -> Any:
    """The ``GLContextAttrs`` for the profile and version ``definition`` asks for"""
    attrs = glcanvas.GLContextAttrs()
    major = int(definition.version[0]) if definition.version[0] > 0 else 0
    minor = int(definition.version[1]) if definition.version[0] > 0 else 0
    if definition.profile == "core":
        if major == 0:
            major, minor = 3, 3
        attrs.CoreProfile().OGLVersion(major, minor)
    elif definition.profile == "compatibility" and major >= 3:
        # A profile exists only from GL 3.0 up; below that the driver chooses.
        attrs.CompatibilityProfile().OGLVersion(major, minor)
    else:
        attrs.PlatformDefaults()
    attrs.EndList()
    return attrs


def getIcon(data: bytes) -> Any:
    """Return the data from the resource as a wxIcon"""
    image = wx.Image(BytesIO(data))
    icon = wx.Icon()
    icon.CopyFromBitmap(wx.Bitmap(image))
    return icon


def getDefaultIcons() -> Any:
    """The OpenGLContext icons as a wx.IconBundle, or None without them

    ``frame.SetIcons(bundle)`` takes the result: two icons, 16x16 and 32x32.
    """
    try:
        from OpenGLContext.resources import context_icon_png, context_icon_small_png
    except ImportError:
        return None
    bundle = wx.IconBundle()
    bundle.AddIcon(getIcon(context_icon_png.data))
    bundle.AddIcon(getIcon(context_icon_small_png.data))
    return bundle


class WxWindowSystem(WindowSystem):
    """A GLCanvas in a wx window, and the translation of its events

    The canvas's GL context is not ready for ``OnInit`` until the toolkit has
    created the native window, which on GTK is after the constructor returns;
    :meth:`open` answers so, and the canvas's creation (or its first paint,
    whichever arrives first) completes the context.
    """

    name = 'wx'
    acceptsParent = True
    pollsEvents = False

    #: wx's stock cursors, by the name a control asks for.
    CURSOR_SHAPES: ClassVar[dict[str, str]] = {
        'arrow': 'CURSOR_ARROW',
        'hand': 'CURSOR_HAND',
        'text': 'CURSOR_IBEAM',
        'crosshair': 'CURSOR_CROSS',
        'resize-x': 'CURSOR_SIZEWE',
        'resize-y': 'CURSOR_SIZENS',
        'resize': 'CURSOR_SIZING',
        'no': 'CURSOR_NO_ENTRY',
    }

    window: Any = None
    #: The wx.GLContext the canvas renders through.
    glContext: Any = None
    #: The frame this window system made, where it was given no parent.
    frame: Any = None
    #: True while the pointer is hidden and being warped back to the middle of
    #: the canvas for a mouse-look mode.
    pointerGrabbed = False
    #: Where the pointer was last warped to, so the movement the warp itself
    #: generates can be told from a real one.
    pointerWarpedTo: Optional[tuple[int, int]] = None
    #: Counts a stream of wheel reports into whole notches; wx states its own
    #: detent size on the event, so the counter is built on the first one.
    wheelCounter: Optional[WheelNotches] = None

    # -- lifetime ----------------------------------------------------------

    def open(self, definition: ContextDefinition, parent: Any = None) -> bool:
        if wx.GetApp() is None:
            raise RuntimeError(
                "A wx.App must exist before a wx view can be made; use "
                "ContextMainLoop, or create the application first")
        if parent is None:
            self.frame = parent = wx.Frame(
                None, -1, definition.title or self.context.getApplicationName())
        size = tuple(int(x) for x in definition.size)
        canvas = self.window = glcanvas.GLCanvas(
            parent, id=-1, size=size, style=wx.WANTS_CHARS, name="GLContext",
            attribList=canvasAttributes(definition),
        )
        self.glContext = glcanvas.GLContext(canvas, None, contextAttributes(definition))
        if not self.glContext.IsOK():
            log.warning(
                "Failed to create OpenGL context with requested profile=%s, "
                "version=%s. Falling back to default context.",
                definition.profile, definition.version
            )
            self.glContext = glcanvas.GLContext(canvas, None)
        # Showing is a step of its own here, so hiding is not taking one.  See
        # renderoptions.hidden_window: rendering and reading back are
        # unaffected, and a suite of GL scripts should not take over the screen
        # of whoever is running it.
        if not renderoptions.hidden_window():
            canvas.Show()
            if self.frame is not None:
                self.frame.SetClientSize(size)
                self.frame.Show()
        return False

    def release(self) -> None:
        """Drop the context's GL objects, with its GL context current

        The caches may *delete* what they hold rather than merely forget it,
        and deleting a name needs the context that issued it.
        """
        canvas, self.window = self.window, None
        if canvas is None:
            return
        try:
            self.glContext.SetCurrent(canvas)
        except Exception as err:
            log.debug("cannot take the context to release it: %s", err)
            self.context.releaseContextResources(None)
        else:
            self.context.releaseContextResources(self.glHandle())
        frame, self.frame = self.frame, None
        if frame is not None:
            frame.Destroy()

    # -- current and presenting --------------------------------------------

    def makeCurrent(self) -> Optional[Hashable]:
        if self.window is None:
            return None
        self.context.releaseForeignContext()
        self.glContext.SetCurrent(self.window)
        return self.glHandle()

    def swap(self) -> None:
        if self.window is not None:
            self.window.SwapBuffers()

    def drawableSize(self) -> tuple[int, int]:
        size = self.window.GetClientSize()
        return int(size.width), int(size.height)

    def applyVSync(self, definition: Any) -> bool:
        """Set the swap interval from ``definition.vsync``

        wx names nothing for this, so it goes to the platform's own
        swap-control extension; see :mod:`OpenGLContext.swapcontrol`, which
        answers False where there is none.  Asked with the canvas current,
        since that is the drawable the interval is set for.
        """
        if self.window is None:
            return False
        self.glContext.SetCurrent(self.window)
        return swapcontrol.set_swap_interval(1 if wantsVSync(definition) else 0)

    # -- requests of the window --------------------------------------------

    def setFullscreen(self, fullscreen: bool) -> bool:
        """Fill the screen, or go back to a window.

        The frame the canvas sits in is what fills the screen -- a canvas
        cannot, and the menu bar and status bar a frame may carry have to go
        with it.
        """
        if self.window is None:
            return False
        frame = self.window.GetTopLevelParent()
        if frame is None:
            return False
        frame.ShowFullScreen(bool(fullscreen))
        return True

    def setPointerShape(self, name: str) -> bool:
        """Show this pointer; False for a shape wx has not got."""
        if self.window is None or self.pointerGrabbed:
            return False
        shape = self.CURSOR_SHAPES.get(str(name or 'arrow'))
        if shape is None:
            return False
        constant = getattr(wx, shape, None)
        if constant is None:
            return False
        self.window.SetCursor(wx.Cursor(constant))
        return True

    def setPointerCapture(self, capture: bool) -> bool:
        """Hide the pointer and keep it in the window, for a mouse-look mode

        wx has no relative-motion mode, so the pointer is warped back to the
        middle of the canvas after every movement -- which is what makes the
        motion unbounded, since a pointer that stops at the edge of the screen
        is a view that stops turning there.  The warp arrives back as an
        ordinary movement and is recognised and dropped; see
        :meth:`onMouseMove`.
        """
        canvas = self.window
        if canvas is None:
            return False
        capture = bool(capture)
        self.pointerGrabbed = capture
        self.pointerWarpedTo = None
        if capture:
            canvas.SetCursor(wx.Cursor(wx.CURSOR_BLANK))
            if not canvas.HasCapture():
                canvas.CaptureMouse()
        else:
            canvas.SetCursor(wx.NullCursor)
            while canvas.HasCapture():
                # wx counts captures, and releases one per call.
                canvas.ReleaseMouse()
        # Where the pointer is means something different on each side of this,
        # so the first report afterwards establishes a position rather than
        # arriving as one flick of the view.
        self.context.forgetPointerOrigin()
        if capture:
            self.recentrePointer()
        return True

    def recentrePointer(self) -> None:
        """Put the pointer back in the middle of the canvas, if it is grabbed"""
        if not self.pointerGrabbed or self.window is None:
            return
        size = self.window.GetClientSize()
        middle = (int(size.width) // 2, int(size.height) // 2)
        self.pointerWarpedTo = middle
        self.window.WarpPointer(*middle)

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
        canvas = self.window
        if canvas is None:
            return
        # Ignoring the background erase is what keeps the canvas from
        # flickering between frames.
        canvas.Bind(wx.EVT_ERASE_BACKGROUND, self.onEraseBackground)
        canvas.Bind(wx.EVT_WINDOW_CREATE, self.onCreate)
        canvas.Bind(wx.EVT_SIZE, self.onSize)
        canvas.Bind(wx.EVT_PAINT, self.onPaint)
        canvas.Bind(wx.EVT_KEY_DOWN, self.onKeyDown)
        canvas.Bind(wx.EVT_KEY_UP, self.onKeyUp)
        canvas.Bind(wx.EVT_CHAR, self.onCharacter)
        for event in (wx.EVT_LEFT_DOWN, wx.EVT_RIGHT_DOWN, wx.EVT_MIDDLE_DOWN,
                      wx.EVT_LEFT_UP, wx.EVT_RIGHT_UP, wx.EVT_MIDDLE_UP):
            canvas.Bind(event, self.onMouseButton)
        canvas.Bind(wx.EVT_MOTION, self.onMouseMove)
        canvas.Bind(wx.EVT_MOUSEWHEEL, self.onMouseWheel)
        # No key-up arrives for a key that was down when focus went elsewhere;
        # see onKillFocus.
        canvas.Bind(wx.EVT_KILL_FOCUS, self.onKillFocus)
        # The canvas going is the end of its GL context, and the caches
        # holding that context's names have to be told while it is still
        # whole.  EVT_WINDOW_DESTROY rather than EVT_CLOSE: a canvas is
        # destroyed with its frame and never sees a close of its own.
        canvas.Bind(wx.EVT_WINDOW_DESTROY, self.onWindowDestroy)
        canvas.Bind(wx.EVT_IDLE, self.onIdle)

    def pump(self) -> bool:
        application = wx.GetApp()
        if application is None:
            return False
        application.Yield(True)
        return True

    def mainLoop(self) -> Any:
        """Run wx's event loop with this context rendering inside it"""
        application = wx.GetApp()
        if application is None:
            raise RuntimeError(
                "A wx.App must exist before the wx main loop can run; use "
                "ContextMainLoop, or create the application yourself")
        try:
            return application.MainLoop()
        finally:
            self.context.closeJournals('mainloop-ended')

    @classmethod
    def run(cls, contextClass: type[Context], *args: Any, **named: Any) -> Any:
        """Make the wx application and a frame, the context in it, and run"""
        made: list[Context] = []

        class ContextApp(wx.App):
            def OnInit(self) -> bool:
                frame = wx.Frame(
                    None, -1, contextClass.getApplicationName(),
                    wx.DefaultPosition, wx.Size(600, 300))
                self.SetTopWindow(frame)
                frame.Show(not renderoptions.hidden_window())
                context = contextClass(*args, parent=frame, **named)
                made.append(context)
                context.window.SetFocus()
                definition = context.contextDefinition
                assert definition is not None
                frame.SetSize(tuple(int(x) for x in definition.size))
                if renderoptions.fullscreen_window(definition):
                    context.setFullscreen(True)
                icons = getDefaultIcons()
                if icons is not None:
                    frame.SetIcons(icons)
                return True

        application = ContextApp(0)
        try:
            return application.MainLoop()
        finally:
            for context in made:
                context.closeJournals('mainloop-ended')

    # -- the canvas's own events ----------------------------------------------

    def onCreate(self, event: Any) -> None:
        """The native window exists: the context can run ``OnInit`` now"""
        self.context.completeInit()

    def onPaint(self, event: Any) -> None:
        """Size the viewport to the canvas and draw

        A ``wx.PaintDC`` has to be made in a paint handler even though nothing
        is drawn through it.  A paint that arrives before the canvas's creation
        was reported completes the context first.
        """
        canvas = self.window
        if canvas is None:
            return
        wx.PaintDC(canvas)
        size = canvas.GetClientSize()
        if size.width == 0 or size.height == 0:
            return
        context = self.context
        if not context.completeInit():
            context.ViewPort(size.width, size.height)
        context.triggerRedraw(1)

    def onSize(self, event: Any) -> None:
        """Ask for a paint, which sizes the viewport

        wx sends size events before the canvas has a context to draw with, so
        the resize is left to the paint that follows.
        """
        if self.window is not None:
            self.window.Refresh()
        event.Skip()

    def onIdle(self, event: Any) -> None:
        """Run the context's idle hook and draw, then ask for more idle time"""
        context = self.context
        if self.window is not None and context.initialised:
            context.pumpKeyRepeats()
            context.OnIdle()
            context.drawPoll()
        event.RequestMore()

    def onEraseBackground(self, event: Any) -> None:
        """Nothing is erased: the frame covers the whole canvas"""

    def onWindowDestroy(self, event: Any) -> None:
        """Let go of the context's GL objects as the canvas is destroyed."""
        event.Skip()
        if event.GetEventObject() is not self.window:
            return                      # a child's destruction, not ours
        self.release()

    # -- keyboard -----------------------------------------------------------

    def onKeyDown(self, event: Any) -> None:
        context = self.context
        code = event.GetKeyCode()
        if code in context.heldKeys():
            context.noteNativeRepeat()      # already down, so wx is repeating it
        context.noteKeyDown(code, modifiersOf(event))
        context.ProcessEvent(wxKeyboardEvent(context, event, 1))
        event.Skip()

    def onKeyUp(self, event: Any) -> None:
        self.context.noteKeyUp(event.GetKeyCode())
        self.context.ProcessEvent(wxKeyboardEvent(self.context, event, 0))

    def onCharacter(self, event: Any) -> None:
        self.context.ProcessEvent(wxKeypressEvent(self.context, event))

    def onKillFocus(self, event: Any) -> None:
        """Let go of every held key as the canvas loses focus

        No key-up arrives for a key that was down when focus went elsewhere, so
        without this the key stays held for the rest of the session and the
        camera keeps moving with nobody touching the keyboard.
        """
        self.context.clearHeldKeys()
        event.Skip()

    def emitKey(self, key: Any, state: int, modifiers: Any) -> None:
        """Send a key transition wx did not report

        ``modifiers`` is the triple that came with the press, so the synthetic
        release matches the binding the press did.
        """
        context = self.context
        made = wxKeyboardEvent.__new__(wxKeyboardEvent)
        keyboardevents.KeyboardEvent.__init__(made)
        if hasattr(context, 'currentPass'):
            made.renderingPass = context.currentPass
        made.modifiers = modifiers
        made.name = keyName(key)
        made.state = state
        context.ProcessEvent(made)

    # -- pointer -------------------------------------------------------------

    def onMouseButton(self, event: Any) -> None:
        self.context.addPickEvent(wxMouseButtonEvent(self.context, event))
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
        x, y = event.GetX(), event.GetY()
        echo = self.pointerWarpEcho(x, y)
        if echo:
            context.forgetPointerOrigin()
        context.recordPointerMotion(int(x), context.getViewPort()[1] - int(y))
        if echo:
            return
        self.recentrePointer()
        context.addPickEvent(wxMouseMoveEvent(context, event))
        context.triggerPick()

    def onMouseWheel(self, event: Any) -> None:
        """Scrolling, as the pair of button events a wheel notch is

        wx reports scrolling as an amount of rotation rather than as the wheel
        buttons everything downstream reads (see
        :data:`~OpenGLContext.events.mouseevents.WHEEL_UP`), so each whole
        notch becomes a press and a release here.  Only vertical rotation is
        used: nothing in the interface scrolls sideways.
        """
        if event.GetWheelAxis() != wx.MOUSE_WHEEL_VERTICAL:
            return
        if self.wheelCounter is None:
            self.wheelCounter = WheelNotches(event.GetWheelDelta() or 120)
        for button in self.wheelCounter.notches(event.GetWheelRotation()):
            for state in (1, 0):
                self.context.addPickEvent(
                    wxWheelEvent(self.context, event, button=button, state=state))
        self.context.triggerPick()
