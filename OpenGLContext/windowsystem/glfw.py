"""A window through GLFW

GLFW makes core and compatibility contexts of any version on every desktop
platform, with debug contexts and forward compatibility, and reports the
framebuffer's size in pixels apart from the window's, which is what a scaled
display needs.  It is the window system an empty ``windowsystem`` field opens,
and what the engine's own suite renders through.

``context.window`` is GLFW's window handle.
"""
from __future__ import annotations

try:
    import glfw
except ImportError:
    raise ImportError(
        "The glfw package is required for the GLFW window system. "
        "Install with: pip install glfw") from None

import logging
import math
import warnings
from collections.abc import Hashable, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from OpenGLContext import renderoptions
from OpenGLContext.events.glfwevents import (
    GLFWKeyboardEvent, GLFWKeypressEvent, GLFWMouseButtonEvent,
    GLFWMouseMoveEvent,
)
from OpenGLContext.events.mouseevents import WHEEL_DOWN, WHEEL_UP
from OpenGLContext.windowsystem.base import WindowSystem, wantsVSync

if TYPE_CHECKING:
    from OpenGLContext.contextdefinition import ContextDefinition

log = logging.getLogger(__name__)

#: What ``glfw.set_window_monitor`` takes to put a window back on the desktop.
#: GLFW spells it NULL, and the binding declares the parameter as a monitor
#: pointer -- which nothing can be and still mean "no monitor".
_WINDOWED: Any = None

#: How near a whole wheel notch counts as one, for a touchpad reporting
#: fractions whose sum lands a rounding error short.
WHEEL_TOLERANCE = 1e-3

#: What one click of a wheel is assumed to report until a report says
#: otherwise.  **It is not the same everywhere**: GLFW gives a continuous
#: offset and no count of detents, X11 reports 1.0 for one click, and the
#: Wayland backend divides the protocol's 15.0 by ten and reports 1.5.
WHEEL_DETENT = 1.0

#: Below this an offset is a touchpad reporting *part* of a click rather than a
#: wheel reporting a whole one, and is summed instead.  A fraction that small
#: is also no evidence about how big a click is on this platform.
WHEEL_DETENT_MINIMUM = 0.5

#: Set this to have every scroll callback say what it was given and what it
#: made of it.  **Backends and compositors disagree about how a wheel reaches
#: an application**, and a compositor that reports one physical detent twice is
#: indistinguishable from a quick flick of the wheel unless somebody can see
#: the offsets themselves -- so this is what turns "the wheel skips a step"
#: into a number.  Off unless asked for: a line per notch would be a line per
#: notch for ever.
WHEEL_DEBUG_ENV = 'OPENGLCONTEXT_DEBUG_WHEEL'


def fullscreenMonitor(definition: Any) -> Any:
    """The monitor a window built from ``definition`` should fill, or None.

    ``OPENGLCONTEXT_HIDDEN`` wins over the request, because GLFW ignores the
    visibility hint for a full-screen window: a capture subprocess that asked
    for both would map itself over the display of whoever started the run.
    A machine with no monitor attached answers None for the same reason it
    answers no size -- there is nothing to fill.
    """
    if not renderoptions.fullscreen_window(definition):
        return None
    return glfw.get_primary_monitor() or None


def setWindowHints(definition: Any) -> None:
    """Ask GLFW for the window ``definition`` describes

    GLFW keeps window hints as process-global state, so they are reset to the
    defaults first: a hint only ever set is a hint left over for the next
    window.
    """
    glfw.default_window_hints()
    glfw.window_hint(glfw.DOUBLEBUFFER,
                     glfw.TRUE if definition.doubleBuffer else glfw.FALSE)
    glfw.window_hint(glfw.DEPTH_BITS,
                     definition.depthBuffer if definition.depthBuffer > -1 else 24)
    if definition.stencilBuffer > -1:
        glfw.window_hint(glfw.STENCIL_BITS, definition.stencilBuffer)
    if definition.accumulationBuffer > -1:
        bits = definition.accumulationBuffer
        for hint in (glfw.ACCUM_RED_BITS, glfw.ACCUM_GREEN_BITS,
                     glfw.ACCUM_BLUE_BITS, glfw.ACCUM_ALPHA_BITS):
            glfw.window_hint(hint, bits)
    # GLFW defaults to 8 alpha bits, and a compositor that honours destination
    # alpha (Wayland/EGL, forwarded GL) then treats cleared pixels as
    # transparent, showing the windows behind this one through it.
    glfw.window_hint(glfw.ALPHA_BITS, 8 if definition.alpha else 0)
    if definition.multisampleSamples > 0:
        glfw.window_hint(glfw.SAMPLES, definition.multisampleSamples)
    if definition.stereo > 0:
        glfw.window_hint(glfw.STEREO, glfw.TRUE)
    if definition.version[0] > 0:
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, int(definition.version[0]))
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, int(definition.version[1]))
    if definition.profile == "core":
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
    elif definition.profile == "compatibility" and definition.version[0] >= 3:
        # A profile exists only from GL 3.0 up; asking for one below that is
        # a request the driver refuses.
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_COMPAT_PROFILE)
    if definition.debug:
        glfw.window_hint(glfw.OPENGL_DEBUG_CONTEXT, glfw.TRUE)
    glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)
    # A hidden window for captures (OPENGLCONTEXT_HIDDEN).  A mapped Wayland
    # surface serialises on the compositor's frame callback, so back-to-back
    # capture subprocesses stall each other's swaps; a hidden window renders
    # and reads back the same but never maps.  It is also undecorated, because
    # a caption bar carries a minimum width: Windows widens a decorated window
    # narrower than the system menu and the close button, and a capture then
    # reads back a framebuffer wider than the size that was asked for.
    if renderoptions.hidden_window():
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        glfw.window_hint(glfw.DECORATED, glfw.FALSE)


class GLFWWindowSystem(WindowSystem):
    """A GLFW window, and the translation of its callbacks into events"""

    name = 'glfw'

    #: The pointers this window system can show, by the name a widget asks
    #: for, each with the GLFW shapes to try in order.  The names GLFW 3.4
    #: added are first because a Wayland compositor's cursor theme carries
    #: those and not the older ones: asking for `hand2` there fails, and
    #: `default` shapes answer.  The shapes themselves are made on first use,
    #: since a cursor is a GLFW object and the window has to exist first.
    CURSOR_SHAPES: ClassVar[dict[str, tuple[str, ...]]] = {
        'arrow': ('ARROW_CURSOR',),
        'hand': ('POINTING_HAND_CURSOR', 'HAND_CURSOR'),
        'text': ('IBEAM_CURSOR',),
        'crosshair': ('CROSSHAIR_CURSOR',),
        'resize-x': ('RESIZE_EW_CURSOR', 'HRESIZE_CURSOR'),
        'resize-y': ('RESIZE_NS_CURSOR', 'VRESIZE_CURSOR'),
        'resize': ('RESIZE_ALL_CURSOR',),
        'no': ('NOT_ALLOWED_CURSOR',),
    }

    #: Where and how big the window is when it is not filling the screen, as
    #: (x, y, width, height).  A position of None means the platform has never
    #: placed this window and should choose.
    windowedGeometry: tuple[Optional[int], Optional[int], int, int] = (
        None, None, 300, 300)
    #: The GLFW cursors this window has made, by name, until it is released.
    _cursors: Optional[dict[str, Any]] = None
    #: What one click of this platform's wheel reports, learned from what
    #: arrives; see :meth:`wheelClicks`.
    wheelDetent: float = WHEEL_DETENT
    #: Touchpad rotation reported so far that has not yet made a whole notch.
    wheelRemainder: float = 0.0

    # -- lifetime ----------------------------------------------------------

    def open(self, definition: ContextDefinition, parent: Any = None) -> bool:
        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")
        setWindowHints(definition)
        width, height = [int(i) for i in definition.size]
        title = definition.title or self.context.getApplicationName()
        # Kept for the trip back out of full-screen, which has to be told a
        # size and a position: the definition's size is the only statement of
        # how big a window this application wanted.
        self.windowedGeometry = (None, None, width, height)
        monitor = fullscreenMonitor(definition)
        if monitor is not None:
            width, height = self.fillMonitor(monitor)
        window = glfw.create_window(width, height, title, monitor, None)
        if not window:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")
        self.window = window
        # Whatever held the thread is let go of first: a thread another window
        # system's context is holding is refused.  See
        # Context.releaseForeignContext.
        self.context.releaseForeignContext()
        glfw.make_context_current(window)
        self.applyVSync(definition)
        return True

    def release(self) -> None:
        """Drop the context's GL objects and destroy the window

        This window is made current first.  The caches are told which context
        is going by asking which one *is* current, so an application closing
        one of two windows would otherwise retire the wrong one -- dropping a
        live context's programs, and leaving the closed context's names
        reachable by whatever the driver hands the address to next.
        """
        if not self.window:
            return
        try:
            glfw.make_context_current(self.window)
        except Exception:               # pragma: no cover - needs a lost window
            pass
        self.context.releaseContextResources(self.glHandle())
        self.abandon()

    def abandon(self) -> None:
        """Destroy the window and its cursors without telling any cache"""
        window, self.window = self.window, None
        # GLFW keeps a cursor until it is destroyed or GLFW is terminated, so a
        # process that opens many windows would otherwise collect them.
        for cursor in (self._cursors or {}).values():
            glfw.destroy_cursor(cursor)
        self._cursors = None
        if window:
            glfw.destroy_window(window)

    def quit(self) -> bool:
        if self.window:
            glfw.set_window_should_close(self.window, True)
        return super().quit()

    # -- current and presenting --------------------------------------------

    def makeCurrent(self) -> Optional[Hashable]:
        """Make the window's context current, letting go of a foreign one

        A thread may have one current context, and a platform's GL binding
        APIs do not know about each other: GLFW asking EGL for a thread a GLX
        context holds is ``EGL_BAD_ACCESS``.  Letting go first costs one query.
        """
        if not self.window:
            return None
        self.context.releaseForeignContext()
        glfw.make_context_current(self.window)
        return self.glHandle()

    def swap(self) -> None:
        if self.window:
            glfw.swap_buffers(self.window)

    def drawableSize(self) -> tuple[int, int]:
        """The framebuffer's size, which a scaled display makes differ from
        the window's"""
        width, height = glfw.get_framebuffer_size(self.window)
        return int(width), int(height)

    def applyVSync(self, definition: Any) -> bool:
        """Set the swap interval from ``definition.vsync``

        Off also matters on Wayland, where a vsynced swap blocks on a
        compositor frame callback that a leaked GL context from an
        abnormally-terminated process can wedge -- so the test suite turns it
        off and one flaky run cannot stall every later swap.
        """
        try:
            glfw.swap_interval(1 if wantsVSync(definition) else 0)
        except Exception:
            log.debug("this GLFW build would not set the swap interval",
                      exc_info=True)
            return False
        return True

    # -- requests of the window --------------------------------------------

    def fillMonitor(self, monitor: Any) -> tuple[int, int]:
        """The size to ask for on ``monitor``, with the refresh rate to match.

        The monitor's *current* mode, so nothing switches resolution: a mode
        change is slow, it rearranges the icons on every other desktop the
        display is showing, and a game that wanted a different resolution would
        say so in its definition's size rather than by filling the screen.
        """
        mode = glfw.get_video_mode(monitor)
        glfw.window_hint(glfw.REFRESH_RATE, mode.refresh_rate)
        return int(mode.size.width), int(mode.size.height)

    def setFullscreen(self, fullscreen: bool) -> bool:
        """Fill the screen, or go back to the window this context opened with.

        Moving the window between a monitor and the desktop keeps the GL
        context and everything in it, so nothing is reloaded.
        """
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
            position: tuple[Optional[int], Optional[int]] = (None, None)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                try:
                    position = glfw.get_window_pos(self.window)
                except Exception:
                    pass
            width, height = glfw.get_window_size(self.window)
            self.windowedGeometry = (position[0], position[1], width, height)
            width, height = self.fillMonitor(monitor)
            glfw.set_window_monitor(self.window, monitor, 0, 0, width, height,
                                    glfw.get_video_mode(monitor).refresh_rate)
        else:
            left, top, width, height = self.windowedGeometry
            # A window that was born full-screen has no remembered position, so
            # it is handed back to the platform to place rather than pinned to
            # the top-left corner of a display it may not be on.
            if left is None or top is None:
                left, top = 100, 100
            glfw.set_window_monitor(self.window, _WINDOWED, left, top,
                                    width, height, glfw.DONT_CARE)
        # A monitor swap re-creates the drawable underneath us on some
        # platforms, so the swap interval has to be asked for again.
        self.applyVSync(self.context.contextDefinition)
        return True

    def setPointerShape(self, name: str) -> bool:
        """Show this pointer; False for a name this platform has not got.

        ``''`` and ``'arrow'`` are the ordinary pointer. A shape the platform
        does not have answers False and leaves the pointer as it is, rather
        than showing a nearby shape.
        """
        if not self.window:
            return False
        wanted = str(name or 'arrow')
        shapes = self.CURSOR_SHAPES.get(wanted)
        if shapes is None:
            return False
        if self._cursors is None:
            self._cursors = {}
        cursor = self._cursors.get(wanted)
        if cursor is None:
            cursor = standardCursor(shapes)
            if cursor is None:
                return False
            self._cursors[wanted] = cursor
        glfw.set_cursor(self.window, cursor)
        return True

    def setPointerCapture(self, capture: bool) -> bool:
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

    # -- the loop -----------------------------------------------------------

    def bindCallbacks(self) -> None:
        window = self.window
        if not window:
            return
        glfw.set_key_callback(window, self.onKey)
        glfw.set_char_callback(window, self.onCharacter)
        glfw.set_mouse_button_callback(window, self.onMouseButton)
        glfw.set_cursor_pos_callback(window, self.onCursorPos)
        glfw.set_scroll_callback(window, self.onScroll)
        glfw.set_framebuffer_size_callback(window, self.onFramebufferSize)
        glfw.set_window_close_callback(window, self.onClose)
        glfw.set_window_focus_callback(window, self.onFocus)

    def pump(self) -> bool:
        glfw.poll_events()
        return True

    def running(self) -> bool:
        return (bool(self.window) and not self.finished
                and not glfw.window_should_close(self.window))

    def mainLoop(self) -> Any:
        try:
            return super().mainLoop()
        finally:
            glfw.terminate()

    # -- keyboard -----------------------------------------------------------

    def onKey(self, window: Any, key: int, scancode: int, action: int,
              mods: int) -> None:
        """A key went down, came up or repeated

        GLFW's Wayland platform emits ``glfw.REPEAT`` only where the compositor
        advertises ``repeat_info``, which a nested or container compositor often
        does not, so held-key navigation needs the repeats supplying; see
        :class:`OpenGLContext.events.eventhandlermixin.HeldKeyMixin`.
        """
        context = self.context
        if action == glfw.PRESS:
            context.noteKeyDown(key, mods)
            self.emitKey(key, 1, mods)
        elif action == glfw.RELEASE:
            context.noteKeyUp(key)
            self.emitKey(key, 0, mods)
        elif action == glfw.REPEAT:
            context.noteNativeRepeat()
            self.emitKey(key, 1, mods)

    def emitKey(self, key: Any, state: int, modifiers: Any) -> None:
        self.context.ProcessEvent(
            GLFWKeyboardEvent(self.context, key, state, modifiers))

    def onCharacter(self, window: Any, codepoint: int) -> None:
        """Character input, which is what a ``keypress`` is"""
        self.context.ProcessEvent(
            GLFWKeypressEvent(self.context, codepoint, self.currentModifiers()))

    def currentModifiers(self) -> tuple[bool, bool, bool]:
        """The (shift, ctrl, alt) triple as the keyboard stands now"""
        def held(*keys: int) -> bool:
            return any(glfw.get_key(self.window, key) == glfw.PRESS
                       for key in keys)
        return (
            held(glfw.KEY_LEFT_SHIFT, glfw.KEY_RIGHT_SHIFT),
            held(glfw.KEY_LEFT_CONTROL, glfw.KEY_RIGHT_CONTROL),
            held(glfw.KEY_LEFT_ALT, glfw.KEY_RIGHT_ALT),
        )

    def onFocus(self, window: Any, focused: int) -> None:
        """Let go of held keys as focus goes: no release arrives unfocused"""
        if not focused:
            self.context.clearHeldKeys()

    # -- pointer -------------------------------------------------------------

    def cursorToFramebuffer(self, window: Any, x: float,
                            y: float) -> tuple[float, float]:
        """Scale a GLFW cursor position to framebuffer pixels.

        GLFW reports the cursor in logical window coordinates, but the viewport
        and the selection buffer are sized in physical framebuffer pixels.  On
        a HiDPI or scaled display the two differ, so the raw position lands a
        pick on the wrong pixel; scaling by the framebuffer-to-window ratio
        makes the pick point match what was rendered.
        """
        winWidth, winHeight = glfw.get_window_size(window)
        fbWidth, fbHeight = glfw.get_framebuffer_size(window)
        if winWidth and winHeight:
            x = x * fbWidth / winWidth
            y = y * fbHeight / winHeight
        return x, y

    def onMouseButton(self, window: Any, button: int, action: int,
                      mods: int) -> None:
        state = 1 if action == glfw.PRESS else 0
        x, y = self.cursorToFramebuffer(window, *glfw.get_cursor_pos(window))
        self.context.addPickEvent(
            GLFWMouseButtonEvent(self.context, button, state, int(x), int(y), mods))
        self.context.triggerPick()

    def onCursorPos(self, window: Any, xpos: float, ypos: float) -> None:
        """The pointer moved.

        The movement sampler is told directly as well as through the pick
        queue: a mouse-look mode wants every scrap of motion as it happens,
        while a pick event is only delivered once the selection buffer resolves
        it -- and not at all when the pointer is over nothing or picking is off.

        Both are told in the **same** coordinates: GLFW reports y downward and
        everything else in OpenGLContext counts it upward from the bottom, so
        the flip happens once, here.  Feeding the sampler the raw value inverts
        mouse-look's vertical and nothing else.
        """
        context = self.context
        xpos, ypos = self.cursorToFramebuffer(window, xpos, ypos)
        height = context.getViewPort()[1]
        context.recordPointerMotion(int(xpos), height - int(ypos))
        context.addPickEvent(GLFWMouseMoveEvent(context, int(xpos), int(ypos)))
        context.triggerPick()

    def onScroll(self, window: Any, xoffset: float, yoffset: float) -> None:
        """Scrolling, as the pair of button events a wheel notch is.

        GLFW reports scrolling on a callback of its own, in offsets rather than
        in the wheel buttons everything downstream reads (see
        :data:`~OpenGLContext.events.mouseevents.WHEEL_UP`), so each whole
        notch becomes a press and a release here.  Only the vertical offset is
        used: nothing in the interface scrolls sideways.
        """
        notches = self.wheelNotches(yoffset)
        if renderoptions.env_flag(WHEEL_DEBUG_ENV, False):
            log.info('wheel: reported %+.4f, carrying %+.4f, sending %d notch(es)',
                     float(yoffset), self.wheelRemainder, len(notches))
        for button in notches:
            self.emitWheel(window, button)

    def wheelNotches(self, offset: float) -> list[int]:
        """The notches in one report: a wheel's clicks, or a touchpad's sum.

        **The two are different devices and are counted differently.**  A wheel
        reports a whole click at a time, in whatever units this platform
        measures a click in; a touchpad reports a stream of parts of one, which
        are summed so that a slow drag scrolls once it has asked for a whole
        notch and a fast one scrolls no further than it was pushed.  What
        separates them is :data:`WHEEL_DETENT_MINIMUM`.

        Assuming a click is 1.0 makes every *other* click of a Wayland wheel
        scroll twice: 1.5 is one notch with half of one carried, and the next
        1.5 makes 2.0 and fires two.  So the size of a click is
        :meth:`wheelClicks`'s to learn.
        """
        offset = float(offset)
        if not offset:
            return []
        button = WHEEL_UP if offset > 0.0 else WHEEL_DOWN
        if abs(offset) >= WHEEL_DETENT_MINIMUM:
            return [button] * self.wheelClicks(abs(offset))
        return [button] * self.padNotches(offset)

    def wheelClicks(self, size: float) -> int:
        """How many clicks of the wheel one report of ``size`` is.

        The size of a click is **learned from what arrives**, because GLFW
        offers no count of detents and the platforms disagree.  A report that
        is not a whole number of the click we assumed is itself the evidence
        that the assumption was wrong, and is one click of a smaller size.

        A wheel does not inherit a touchpad's carried fraction: they are two
        devices, and half a drag over a pad must not turn the next click of the
        wheel into two.
        """
        clicks = size / self.wheelDetent
        whole = int(round(clicks))
        if whole < 1 or abs(clicks - whole) > WHEEL_TOLERANCE:
            self.wheelDetent = size
            whole = 1
        self.wheelRemainder = 0.0
        return whole

    def padNotches(self, offset: float) -> int:
        """The whole notches in a touchpad's fraction, carrying the remainder.

        Turning back drops what was carried rather than letting a jitter over
        the pad accumulate into a notch the way it is not moving.
        """
        carried = self.wheelRemainder
        if (carried > 0.0) != (offset > 0.0):
            carried = 0.0
        total = carried + offset
        # Ten reported tenths sum to a hair under one, so a notch is anything
        # within a thousandth of whole: nobody can feel the difference, and
        # without it a steady drag loses a notch every so often for no reason
        # the user can see.
        notches = int(total + math.copysign(WHEEL_TOLERANCE, total))
        self.wheelRemainder = total - notches
        return abs(notches)

    def emitWheel(self, window: Any, button: int) -> None:
        """One notch, as the press and release of a button that is never held."""
        x, y = self.cursorToFramebuffer(window, *glfw.get_cursor_pos(window))
        for state in (1, 0):
            self.context.addPickEvent(
                GLFWMouseButtonEvent(self.context, button, state, int(x), int(y)))
        self.context.triggerPick()

    # -- the window itself ---------------------------------------------------

    def onFramebufferSize(self, window: Any, width: int, height: int) -> None:
        self.context.OnResize(width, height)

    def onClose(self, window: Any) -> None:
        self.context.OnQuit()


def standardCursor(shapes: Sequence[str]) -> Any:
    """The first of these GLFW cursor shapes this platform will make, or None.

    A cursor theme need not carry every shape, and GLFW answers a missing one
    with a warning and a null rather than an exception.
    """
    for shape in shapes:
        constant = getattr(glfw, shape, None)
        if constant is None:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                cursor = glfw.create_standard_cursor(constant)
            except Exception:
                cursor = None
        if cursor:
            return cursor
    return None
