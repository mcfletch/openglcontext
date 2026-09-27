"""A window through Pygame (SDL2)

``context.window`` is the display surface.  SDL settles the swap interval when
the window is made and holds one GL context that is always current, so a
change to ``vsync`` takes effect in the next window, and making the context
current is a matter of telling PyOpenGL which one it is.
"""
from __future__ import annotations

try:
    import pygame
    import pygame.display
    import pygame.key
except ImportError:
    raise ImportError(
        "The pygame package is required for the Pygame window system") from None

import logging
from collections.abc import Callable, Hashable
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from OpenGLContext import renderoptions
from OpenGLContext.events import keyboardevents
from OpenGLContext.events.pygameevents import (
    PygameKeyboardEvent, PygameKeypressEvent, PygameMouseButtonEvent,
    PygameMouseMoveEvent, modifierState,
)
from OpenGLContext.windowsystem.base import WindowSystem, wantsVSync

if TYPE_CHECKING:
    from OpenGLContext.contextdefinition import ContextDefinition

log = logging.getLogger(__name__)

# SDL's window flags and GL attributes are reached through `pygame` rather than
# imported loose, because several of the names it gives them are OpenGL's as
# well and mean something else there: SDL's GL_STEREO is the twelfth entry in
# its attribute table, OpenGL's is the enumerant 0x0C33, and SDL answers a
# request carrying the wrong one with "Unknown OpenGL attribute" -- so the
# window is never opened at all.

#: How many events one loop iteration will take from SDL's queue before
#: rendering anyway.  A burst of pointer motion can arrive faster than frames
#: are drawn, and a loop that drained the whole queue would never reach the
#: draw while the hand kept moving.
EVENT_BUDGET = 200


def setGLAttributes(definition: Any) -> None:
    """Tell SDL the buffers, profile and version ``definition`` asks for"""
    set = pygame.display.gl_set_attribute
    if definition.depthBuffer > -1:
        set(pygame.GL_DEPTH_SIZE, definition.depthBuffer)
    if definition.stencilBuffer > -1:
        set(pygame.GL_STENCIL_SIZE, definition.stencilBuffer)
    if definition.accumulationBuffer > -1:
        for attribute in (pygame.GL_ACCUM_ALPHA_SIZE, pygame.GL_ACCUM_RED_SIZE,
                          pygame.GL_ACCUM_GREEN_SIZE, pygame.GL_ACCUM_BLUE_SIZE):
            set(attribute, definition.accumulationBuffer)
    if definition.multisampleBuffer > -1 and definition.multisampleSamples > -1:
        set(pygame.GL_MULTISAMPLEBUFFERS, definition.multisampleBuffer)
        set(pygame.GL_MULTISAMPLESAMPLES, definition.multisampleSamples)
    if definition.stereo > -1:
        set(pygame.GL_STEREO, definition.stereo)
    if definition.profile == 'core':
        set(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
        version = definition.version
        if version is not None and len(version) >= 2 and version[0] >= 3:
            set(pygame.GL_CONTEXT_MAJOR_VERSION, int(version[0]))
            set(pygame.GL_CONTEXT_MINOR_VERSION, int(version[1]))
    elif definition.profile == 'compatibility':
        set(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_COMPATIBILITY)


def windowFlags(definition: Any) -> int:
    """The creation flags ``definition`` asks SDL for.

    Reads the definition and the rendering options, and nothing of SDL's
    state, so the choice can be examined without a display to open a window
    on.
    """
    # SDL takes "do not map it" as a creation flag.  See
    # renderoptions.hidden_window: rendering and reading back are unaffected,
    # and a suite of GL scripts should not take over the screen of whoever is
    # running it.
    hidden = pygame.HIDDEN if renderoptions.hidden_window() else 0
    # Borderless rather than a mode switch: SDL then leaves the desktop
    # resolution alone, which is what a window filling the screen is being
    # asked for.  See renderoptions.fullscreen_window.
    filling = (pygame.FULLSCREEN | pygame.NOFRAME
               if renderoptions.fullscreen_window(definition) else 0)
    double = pygame.DOUBLEBUF if definition.doubleBuffer else 0
    return int(double | pygame.RESIZABLE | hidden | filling)


class PygameWindowSystem(WindowSystem):
    """An SDL window through Pygame, and the translation of its events"""

    name = 'pygame'

    #: SDL's system cursors, by the name a control asks for. SDL carries a
    #: picture for each rather than reading a desktop theme, so every one of
    #: these is there on every platform pygame runs on.
    CURSOR_SHAPES: ClassVar[dict[str, str]] = {
        'arrow': 'SYSTEM_CURSOR_ARROW',
        'hand': 'SYSTEM_CURSOR_HAND',
        'text': 'SYSTEM_CURSOR_IBEAM',
        'crosshair': 'SYSTEM_CURSOR_CROSSHAIR',
        'resize-x': 'SYSTEM_CURSOR_SIZEWE',
        'resize-y': 'SYSTEM_CURSOR_SIZENS',
        'resize': 'SYSTEM_CURSOR_SIZEALL',
        'no': 'SYSTEM_CURSOR_NO',
    }

    #: What the swap interval was set to when the window was made, so a later
    #: change to the field can be recognised and reported.
    vsyncApplied: Optional[bool] = None
    #: True while the pointer is hidden and in SDL's relative mode.  Read
    #: rather than asking SDL, so what the events do follows from what this
    #: window system asked for.
    pointerGrabbed = False
    #: Where the pointer would be if it had gone on moving, while it is
    #: grabbed and so no longer moving at all.
    walked: Optional[tuple[int, int]] = None

    # -- lifetime ----------------------------------------------------------

    def open(self, definition: ContextDefinition, parent: Any = None) -> bool:
        pygame.display.init()
        self.displayMode(definition)
        pygame.display.set_caption(
            definition.title or self.context.getApplicationName())
        pygame.key.set_repeat(500, 30)
        return True

    def displayMode(self, definition: Any) -> Any:
        """Open the SDL window this context draws into

        **Calling this again destroys the GL context**, and with it every
        texture, buffer and program the engine's caches hold, so it belongs to
        opening a window and to nothing else.  A resizable SDL2 window follows
        the user's drag without being re-made; see :meth:`onWindowResized`.
        """
        # A size of (0,0) is SDL's "whatever the desktop is at", which is the
        # resolution a window filling the screen wants; asking for the
        # definition's size instead would letterbox it.
        size = ((0, 0) if renderoptions.fullscreen_window(definition)
                else tuple([int(i) for i in definition.size]))
        self.vsyncApplied = wantsVSync(definition)
        # SDL takes the thread as it makes the context, and a thread another
        # window system's context is holding is refused -- fatally, on the GLX
        # side.  See Context.releaseForeignContext.
        self.context.releaseForeignContext()
        setGLAttributes(definition)
        self.window = pygame.display.set_mode(
            size,
            pygame.OPENGL | windowFlags(definition),
            vsync=1 if self.vsyncApplied else 0,
        )
        return self.window

    def release(self) -> None:
        """Drop the context's GL objects and let the display go"""
        if self.window is None:
            return
        self.context.releaseContextResources(self.glHandle())
        self.abandon()

    def abandon(self) -> None:
        """Close the display, and the GL context with it, telling no cache

        ``open`` initialises the display before it makes the window, so the
        display is closed whether or not the window was made.
        """
        self.window = None
        pygame.display.quit()

    # -- current and presenting --------------------------------------------

    def makeCurrent(self) -> Optional[Hashable]:
        """Name the context to PyOpenGL: SDL's is always current

        **Nothing is released here**, unlike every other window system.  SDL
        offers no way to make its context current again, so letting go of it
        would be letting go for good; the one release pygame can afford is
        before the context is made (see :meth:`displayMode`).
        """
        return self.glHandle()

    def swap(self) -> None:
        pygame.display.flip()

    def drawableSize(self) -> tuple[int, int]:
        """The surface's own size, not the requested one: a window filling the
        screen was given the desktop's resolution instead of what it asked for"""
        width, height = self.window.get_size()
        return int(width), int(height)

    def applyVSync(self, definition: Any) -> bool:
        """Answer that the swap interval cannot be changed for a live context

        SDL settles it when the window is made, and re-making the window would
        take the GL context and everything in it with it -- so a change is
        reported and takes effect the next time the program runs.
        """
        if wantsVSync(definition) != self.vsyncApplied:
            log.info(
                "vsync is settled when the SDL window is made; the change "
                "takes effect in a new window"
            )
        return False

    # -- requests of the window --------------------------------------------

    def setFullscreen(self, fullscreen: bool) -> bool:
        """Fill the screen, or go back to the window this context opened with

        SDL swaps the window between the two without re-making the GL context,
        so nothing the engine has uploaded is lost, and it remembers the
        windowed size across the trip.
        """
        if self.window is None:
            return False
        surface = pygame.display.get_surface()
        already = bool(surface and (surface.get_flags() & pygame.FULLSCREEN))
        if bool(fullscreen) == already:
            return True
        pygame.display.toggle_fullscreen()
        self.context.OnResize(*pygame.display.get_window_size())
        return True

    def setPointerShape(self, name: str) -> bool:
        """Show this pointer; False for a shape SDL has not got."""
        if self.window is None:
            return False
        shape = self.CURSOR_SHAPES.get(str(name or 'arrow'))
        if shape is None:
            return False
        constant = getattr(pygame, shape, None)
        if constant is None:
            return False
        try:
            pygame.mouse.set_cursor(constant)
        except (pygame.error, TypeError):
            return False
        return True

    def setPointerCapture(self, capture: bool) -> bool:
        """Grab and hide the pointer for a mouse-look movement mode

        SDL's *relative* mode is the one that reports unbounded motion: the
        pointer stops moving and only the deltas continue, so a view can go on
        turning past the edge of the screen.  The grab keeps the events coming
        while the pointer would have been over another window.
        """
        if self.window is None:
            return False
        capture = bool(capture)
        self.pointerGrabbed = capture
        pygame.event.set_grab(capture)
        pygame.mouse.set_visible(not capture)
        relative = getattr(pygame.mouse, 'set_relative_mode', None)
        if relative is not None:
            relative(capture)
        # Where the pointer is means something different on each side of this,
        # so the first report afterwards establishes a position rather than
        # arriving as one flick of the view.
        self.context.forgetPointerOrigin()
        return True

    # -- the loop -----------------------------------------------------------

    def pump(self) -> bool:
        """Dispatch what SDL has queued

        Each SDL event goes to the method named ``on`` and its SDL name --
        ``onKeyDown``, ``onWindowResized`` -- where there is one.  A handler
        that answers falsely is one saying the loop should end -- the quit
        event, the window's close button -- and that is recorded rather than
        answered here, so this means "the events were delivered" on every
        window system alike.
        """
        for _count in range(EVENT_BUDGET):
            event = pygame.event.poll()
            if not event.type:
                break
            handler: Optional[Callable[[Any], Any]] = getattr(
                self, 'on' + pygame.event.event_name(event.type), None)
            if handler is not None and not handler(event):
                self.finished = True
                break
        return True

    # -- the window's events --------------------------------------------------

    def onQuit(self, event: Any) -> bool:
        """The loop should end"""
        return False

    def onWindowClose(self, event: Any) -> bool:
        """The window's own close button, which SDL reports separately"""
        return False

    def onWindowResized(self, event: Any) -> bool:
        """Follow the window's new size with the viewport

        Nothing is re-made: SDL2 resizes a ``RESIZABLE`` window in place, and
        calling ``set_mode`` again to "apply" the size would build a new GL
        context and strand every object the engine has uploaded into the old
        one.
        """
        self.context.OnResize(*pygame.display.get_window_size())
        return True

    def onVideoResize(self, event: Any) -> bool:
        """The older spelling of a resize, for an SDL1-era event queue"""
        return self.onWindowResized(event)

    def onVideoExpose(self, event: Any) -> bool:
        """The window has been uncovered and wants drawing again"""
        self.context.triggerRedraw(1)
        return True

    def onWindowFocusLost(self, event: Any) -> bool:
        """Let go of every held key: no release arrives for one held now"""
        self.context.clearHeldKeys()
        return True

    # -- keyboard -----------------------------------------------------------

    def onKeyDown(self, event: Any) -> bool:
        """A key went down

        SDL repeats a held key for itself once :func:`pygame.key.set_repeat`
        has been called, and says so, so the held-key map is told and the
        synthetic repeat stays out of the way.  What the map is for here is
        focus loss, where no release arrives at all; see
        :class:`OpenGLContext.events.eventhandlermixin.HeldKeyMixin`.
        """
        context = self.context
        if event.key in context.heldKeys():
            context.noteNativeRepeat()      # already down, so this is SDL's repeat
        context.noteKeyDown(event.key, modifierState())
        context.ProcessEvent(PygameKeyboardEvent(context, event, 1))
        if event.unicode:
            context.ProcessEvent(PygameKeypressEvent(context, event))
        return True

    def onKeyUp(self, event: Any) -> bool:
        self.context.noteKeyUp(event.key)
        self.context.ProcessEvent(PygameKeyboardEvent(self.context, event, 0))
        return True

    def emitKey(self, key: Any, state: int, modifiers: Any) -> None:
        """Send a key transition SDL did not report

        The name is what the key event carries, so a synthetic release reads
        exactly as the real one would have.
        """
        context = self.context
        made = PygameKeyboardEvent.__new__(PygameKeyboardEvent)
        keyboardevents.KeyboardEvent.__init__(made)
        made.context = context
        if hasattr(context, 'currentPass'):
            made.renderingPass = context.currentPass
        made.modifiers = modifiers
        made.name = made._translateKey(pygame.key.name(key))
        made.state = state
        context.ProcessEvent(made)

    # -- pointer -------------------------------------------------------------

    def onMouseButtonDown(self, event: Any) -> bool:
        self.context.addPickEvent(PygameMouseButtonEvent(self.context, event, state=1))
        self.context.triggerPick()
        return True

    def onMouseButtonUp(self, event: Any) -> bool:
        self.context.addPickEvent(PygameMouseButtonEvent(self.context, event, state=0))
        self.context.triggerPick()
        return True

    def onMouseMotion(self, event: Any) -> bool:
        """The pointer moved

        The movement sampler is told directly as well as through the pick
        queue: a mouse-look mode wants every scrap of motion as it happens,
        while a pick event is only delivered once the selection buffer resolves
        it -- and not at all when the pointer is over nothing or picking is off.
        """
        self.recordMotion(event)
        self.context.addPickEvent(PygameMouseMoveEvent(self.context, event))
        self.context.triggerPick()
        return True

    def recordMotion(self, event: Any) -> None:
        """Feed one SDL motion event to the sampler, as a position it can take
        a difference from.

        SDL reports both where the pointer is and how far it moved, and the
        second is what a grabbed pointer has to be followed by: in relative
        mode the position stops changing while the motion does not.  The
        sampler works in absolute positions and takes the delta itself, so a
        relative-mode report is turned back into one by accumulating SDL's
        ``rel`` from wherever the pointer last was.  Both are given in the pick
        point's origin, y counting *upward*.
        """
        record = self.context.recordPointerMotion
        height = self.context.getViewPort()[1]
        if self.pointerGrabbed and getattr(event, 'rel', None):
            walked = self.walked
            if walked is None:
                walked = (event.pos[0], height - event.pos[1])
            self.walked = walked = (walked[0] + event.rel[0],
                                    walked[1] - event.rel[1])
            record(walked[0], walked[1])
            return
        self.walked = None
        record(event.pos[0], height - event.pos[1])
