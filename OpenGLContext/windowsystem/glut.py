"""A window through GLUT (freeglut, in practice)

``context.window`` is GLUT's window id, which every GLUT call about a window
names.  GLUT is the one window system that provides its own bitmap fonts, so a
context here reports ``providesGLUT`` and the GLUT font provider is offered.
"""
from __future__ import annotations

import logging
from collections.abc import Hashable, Sequence
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from OpenGL import GLUT as _glut
from OpenGL.GLUT import (
    GLUT_ACCUM, GLUT_ACTION_CONTINUE_EXECUTION, GLUT_ACTION_ON_WINDOW_CLOSE,
    GLUT_COMPATIBILITY_PROFILE, GLUT_CORE_PROFILE, GLUT_CURSOR_INHERIT,
    GLUT_CURSOR_NONE, GLUT_DEBUG, GLUT_DEPTH, GLUT_DOUBLE,
    GLUT_FORWARD_COMPATIBLE, GLUT_INDEX, GLUT_MIDDLE_BUTTON, GLUT_MULTISAMPLE,
    GLUT_RGB, GLUT_SINGLE, GLUT_STENCIL, GLUT_STEREO, GLUT_WINDOW_HEIGHT,
    GLUT_WINDOW_WIDTH, glutAddMenuEntry, glutAddSubMenu, glutAttachMenu,
    glutCreateMenu, glutCreateWindow, glutDestroyWindow, glutDisplayFunc,
    glutEntryFunc, glutFullScreen, glutGet, glutGetModifiers, glutHideWindow,
    glutIdleFunc, glutInit, glutInitContextFlags, glutInitContextProfile,
    glutInitContextVersion, glutInitDisplayMode, glutInitWindowSize,
    glutKeyboardFunc, glutKeyboardUpFunc, glutLeaveMainLoop, glutMainLoop,
    glutMainLoopEvent, glutMotionFunc, glutMouseFunc, glutPassiveMotionFunc,
    glutPositionWindow, glutReshapeFunc, glutReshapeWindow, glutSetCursor,
    glutSetOption, glutSetWindow, glutSpecialFunc, glutSpecialUpFunc,
    glutSwapBuffers, glutWarpPointer,
)
from OpenGL.extensions import available

from OpenGLContext import renderoptions, swapcontrol
from OpenGLContext.events.glutevents import (
    GLUTKeyboardEvent, GLUTKeypressEvent, GLUTMouseButtonEvent,
    GLUTMouseMoveEvent,
)
from OpenGLContext.windowsystem.base import WarpedPointer, WindowSystem, wantsVSync

if TYPE_CHECKING:
    from OpenGLContext.context import Context
    from OpenGLContext.contextdefinition import ContextDefinition

log = logging.getLogger(__name__)

#: What to ask glutGet for to learn whether GLUT is initialised.  freeglut's
#: own; an original GLUT has no such state, and None is how this module says
#: the question cannot be put at all.
INIT_STATE_QUERY: Optional[int] = getattr(_glut, 'GLUT_INIT_STATE', None)

#: Set once ``glutInit`` has been called in this process.  Read through
#: :func:`glutInitialised`; nothing outside this module writes it.
_initialised = False


def glutInitialised() -> bool:
    """Whether ``glutInit`` has been called in this process

    freeglut offers ``glutGet(GLUT_INIT_STATE)`` and is asked where it does,
    since a process that initialised GLUT some other way -- a host application,
    another library -- is one this module has not seen do it.  Where the query
    is not there, what this module itself did is the best answer available.
    """
    if _initialised:
        return True
    if not available(glutGet) or INIT_STATE_QUERY is None:
        return False
    try:
        return bool(glutGet(INIT_STATE_QUERY))
    except Exception:                   # pragma: no cover - an original GLUT
        return False


def ensureGlutInitialised(argv: Optional[Sequence[str]] = None) -> bool:
    """Call ``glutInit`` unless somebody already has; answer whether it ran

    **Both halves matter, and each is fatal on its own.**  ``glutCreateWindow``
    before ``glutInit`` makes freeglut print

        freeglut ERROR: Function <glutCreateWindow> called without first
        calling 'glutInit'.

    and call ``exit()``; a *second* ``glutInit`` makes it say ``illegal
    glutInit() reinitialization attempt`` and exit as well.  Neither is an
    exception a caller could answer, so the question is asked here, once, on
    every path that needs a window.
    """
    global _initialised
    if glutInitialised():
        _initialised = True
        return False
    import sys

    argv = list(sys.argv if argv is None else argv)
    try:
        glutInit(argv)
    except TypeError:                   # an older PyOpenGL wants one string
        glutInit(' '.join(argv))
    _initialised = True
    return True


#: What each ContextDefinition field asks GLUT's display mode for, as
#: (field, flag if set, flag if clear, flag if left at -1).
CONTEXT_DEFINITION_FLAG_MAPPING = (
    ("doubleBuffer", GLUT_DOUBLE, GLUT_SINGLE, GLUT_DOUBLE),
    ("depthBuffer", GLUT_DEPTH, 0, GLUT_DEPTH),
    # -1 means "don't ask", as it does for this buffer in every other window
    # system: an accumulation buffer is deprecated in GL 3.0 and absent from
    # core, and a driver that publishes no accumulation-buffer config gives
    # freeglut nothing to match, which aborts the process rather than falling
    # back.  A caller that wants one still says so.
    ("accumulationBuffer", GLUT_ACCUM, 0, 0),
    ("stencilBuffer", GLUT_STENCIL, 0, GLUT_STENCIL),
    ("rgb", GLUT_RGB, GLUT_INDEX, GLUT_RGB),
    ("multisampleBuffer", GLUT_MULTISAMPLE, 0, 0),
    ("multisampleSamples", GLUT_MULTISAMPLE, 0, 0),
    ("stereo", GLUT_STEREO, 0, 0),
    ("debug", GLUT_DEBUG, 0, 0),
)


def displayModeFromDefinition(definition: Any) -> int:
    """GLUT's display-mode flags for the buffers ``definition`` asks for"""
    result = 0
    for field, ifYes, ifNo, default in CONTEXT_DEFINITION_FLAG_MAPPING:
        value = getattr(definition, field)
        if value > -1:
            result |= ifYes if value else ifNo
        elif value == -1:
            result |= default
    return result


def null_display() -> None:
    """A display callback that draws nothing, for a window on its way out"""


class GLUTWindowSystem(WarpedPointer, WindowSystem):
    """A GLUT window, and the translation of its callbacks into events"""

    name = 'glut'
    providesGLUT = True

    #: GLUT's own cursors, by the name a control asks for. It has a fixed set
    #: and no way to add to it, so what is not here is answered rather than
    #: approximated: it has no "not allowed" pointer, and ``'no'`` is refused.
    CURSOR_SHAPES: ClassVar[dict[str, str]] = {
        'arrow': 'GLUT_CURSOR_RIGHT_ARROW',
        'hand': 'GLUT_CURSOR_INFO',
        'text': 'GLUT_CURSOR_TEXT',
        'crosshair': 'GLUT_CURSOR_CROSSHAIR',
        'resize-x': 'GLUT_CURSOR_LEFT_RIGHT',
        'resize-y': 'GLUT_CURSOR_UP_DOWN',
    }

    window: Optional[int] = None
    #: What each entry of the world menu loads, by the entry's own value; see
    #: :meth:`createWorldMenu`.
    worldPaths: list[str]

    # -- lifetime ----------------------------------------------------------

    def open(self, definition: ContextDefinition, parent: Any = None) -> bool:
        """Create the window, in the order GLUT needs:

        1. glutInit, without which a window request ends the process
        2. glutInitContextVersion
        3. glutInitContextFlags and glutInitContextProfile
        4. glutInitDisplayMode
        5. glutCreateWindow
        """
        ensureGlutInitialised()
        if available(glutInitContextVersion) and definition.version[0]:
            glutInitContextVersion(*[int(v) for v in definition.version])
        if available(glutInitContextProfile):
            # **Both hints, on both paths.**  GLUT keeps what a window is
            # created from as process-global state, so a hint only ever set is
            # a hint left over: a compatibility context asked for after a core
            # one kept GLUT_FORWARD_COMPATIBLE and arrived with the
            # fixed-function pipeline removed, every glMatrixMode in it raising
            # GL_INVALID_OPERATION.  Named either way for the same reason a
            # profile is named at all: a version hint of 3.2 or above with no
            # profile hint leaves the choice to the driver, and a driver that
            # answers with a core context has taken the fixed-function pipeline
            # away from a caller who asked for it.
            if definition.profile == 'core':
                glutInitContextFlags(GLUT_FORWARD_COMPATIBLE)
                glutInitContextProfile(GLUT_CORE_PROFILE)
            elif definition.profile == 'compatibility':
                glutInitContextFlags(0)
                glutInitContextProfile(GLUT_COMPATIBILITY_PROFILE)
        glutInitDisplayMode(displayModeFromDefinition(definition))
        glutInitWindowSize(*[int(i) for i in definition.size])
        # A new GLUT window takes the thread as it is made, and a thread
        # another window system's context is holding is an X BadAccess that
        # ends the process.  See Context.releaseForeignContext.
        self.context.releaseForeignContext()
        self.window = glutCreateWindow(
            definition.title or self.context.getApplicationName())
        # Recorded while GLUT's own window is current, which it is the moment
        # it is made: without it the first makeCurrent would take the context
        # for a foreign one.
        self.context.bindContextResources(self.glHandle())
        # GLUT has no "create it hidden" hint, so it is hidden the instant it
        # exists.  See renderoptions.hidden_window: rendering and reading back
        # are unaffected, and a suite of GL scripts should not take over the
        # screen of whoever is running it.
        if renderoptions.hidden_window():
            glutHideWindow()
        elif renderoptions.fullscreen_window(definition):
            glutFullScreen()
        self.applyVSync(definition)
        return True

    def release(self) -> None:
        """Let this window's GL objects go, then destroy the window

        With the window still whole and its context current, so the caches
        holding its GL names let go of them before they stop meaning anything.
        """
        if not self.window:
            return
        glutSetWindow(self.window)
        self.context.releaseContextResources(self.glHandle())
        self.abandon()

    def abandon(self) -> None:
        """Destroy the window without telling any cache"""
        window, self.window = self.window, None
        if window:
            glutDestroyWindow(window)

    def quit(self) -> bool:
        self.finished = True
        if self.window:
            glutSetWindow(self.window)
            glutDisplayFunc(null_display)
            glutIdleFunc(None)
        self.release()
        if available(glutLeaveMainLoop):
            glutLeaveMainLoop()
        # Asked for as a truth value, exactly as glutLeaveMainLoop is above:
        # the name being bound says PyOpenGL declares the entry point, not that
        # the GLUT in front of us exports it.  A build that does not -- and the
        # GLUT most often found on Windows does not -- raises NullFunctionError
        # from the call.
        deinitialize = getattr(_glut, 'fgDeinitialize', None)
        if deinitialize is not None and available(deinitialize):
            deinitialize(False)
        return True

    # -- current and presenting --------------------------------------------

    def makeCurrent(self) -> Optional[Hashable]:
        """Make the window current

        **Nothing is released here**, unlike every other window system.  GLUT
        remembers which of its windows is current and ``glutSetWindow`` on that
        one does nothing, so a context let go of behind its back can never be
        taken again: after an external release, ``glutSetWindow`` leaves
        ``glGetString(GL_VERSION)`` answering None.  The one release GLUT can
        afford is before its window is made, where it is the thing about to
        take the thread (see :meth:`open`).
        """
        if self.window:
            glutSetWindow(self.window)
        handle = self.glHandle()
        if handle is None and self.context._ownContext is not None:
            log.warning(
                'GLUT cannot take the drawing thread back: something else in '
                'this process holds a GL context, and GLUT re-makes a window '
                'current only when it believes another one was. Frames from '
                'this window will be empty.'
            )
        return handle

    def swap(self) -> None:
        glutSwapBuffers()

    def drawableSize(self) -> tuple[int, int]:
        """The window's size, asked of GLUT rather than waited for

        GLUT reports a window's size through its reshape callback, which the
        loop delivers -- so a first frame drawn before the loop has run would
        size everything from a zero viewport.
        """
        if self.window:
            glutSetWindow(self.window)
        return int(glutGet(GLUT_WINDOW_WIDTH)), int(glutGet(GLUT_WINDOW_HEIGHT))

    def applyVSync(self, definition: Any) -> bool:
        """Set the swap interval from ``definition.vsync``

        GLUT names nothing for this, so it goes to the window system's own
        swap-control extension; see :mod:`OpenGLContext.swapcontrol`, which
        answers False where there is none.
        """
        if self.window:
            glutSetWindow(self.window)
        return swapcontrol.set_swap_interval(1 if wantsVSync(definition) else 0)

    # -- requests of the window --------------------------------------------

    def setFullscreen(self, fullscreen: bool) -> bool:
        """Fill the screen, or go back to the size the definition asked for."""
        if not self.window:
            return False
        glutSetWindow(self.window)
        if fullscreen:
            glutFullScreen()
        else:
            definition = self.context.contextDefinition
            width, height = ([int(i) for i in definition.size]
                             if definition is not None else (300, 300))
            glutPositionWindow(100, 100)
            glutReshapeWindow(width, height)
        return True

    def setPointerShape(self, name: str) -> bool:
        """Show this pointer; False for a shape GLUT has not got.

        False too while mouse-look has the pointer: GLUT hides it by setting
        the cursor to none, and any other shape would show it again.
        """
        if not self.window or self.pointerGrabbed:
            return False
        shape = self.CURSOR_SHAPES.get(str(name or 'arrow'))
        if shape is None:
            return False
        constant = getattr(_glut, shape, None)
        if constant is None:
            return False
        glutSetWindow(self.window)
        glutSetCursor(constant)
        return True

    def setPointerCapture(self, capture: bool) -> bool:
        """Hide the pointer and keep it in the window, for a mouse-look mode

        GLUT has no relative-motion mode, so the pointer is warped back to the
        middle of the window after every movement; see :class:`WarpedPointer`.
        """
        if not self.window:
            return False
        glutSetWindow(self.window)
        glutSetCursor(GLUT_CURSOR_NONE if capture else GLUT_CURSOR_INHERIT)
        self.grabPointer(capture)
        return True

    def pointerMiddle(self) -> Optional[tuple[int, int]]:
        if not self.window:
            return None
        glutSetWindow(self.window)
        return (int(glutGet(GLUT_WINDOW_WIDTH)) // 2,
                int(glutGet(GLUT_WINDOW_HEIGHT)) // 2)

    def warpPointer(self, x: int, y: int) -> None:
        glutWarpPointer(x, y)


    # -- the loop -----------------------------------------------------------

    def bindCallbacks(self) -> None:
        if not self.window:
            return
        glutSetWindow(self.window)
        glutReshapeFunc(self.context.OnResize)
        glutDisplayFunc(self.onDisplay)
        glutKeyboardFunc(self.onCharacter)
        glutKeyboardUpFunc(self.onKeyUp)
        glutSpecialFunc(self.onKeyDown)
        glutSpecialUpFunc(self.onKeyUp)
        glutMouseFunc(self.onMouseButton)
        glutMotionFunc(self.onMouseMove)
        glutPassiveMotionFunc(self.onMouseMove)
        # GLUT reports no focus change; the pointer leaving the window is the
        # nearest thing it has, and it is when a held key is about to stop
        # being reported.  See onEntry.
        glutEntryFunc(self.onEntry)

    def pump(self) -> bool:
        """Dispatch what GLUT has queued

        Needs freeglut's ``glutMainLoopEvent``; an original GLUT owns its loop
        and offers no way to step it, and says so by answering False.
        """
        if not available(glutMainLoopEvent):
            return False
        glutMainLoopEvent()
        return True

    def mainLoop(self) -> Any:
        """Run the event loop, one iteration at a time

        Built on ``glutMainLoopEvent`` rather than ``glutMainLoop`` so the
        engine drives the frame here as it does under every other window
        system: one render per iteration whatever arrived, the phases timed,
        and an end to the loop that the journals can be closed at.

        A GLUT without ``glutMainLoopEvent`` -- an original GLUT rather than
        freeglut -- keeps the older arrangement, where GLUT owns the loop and
        calls back.
        """
        if not available(glutMainLoopEvent):
            log.info("this GLUT has no glutMainLoopEvent; "
                     "the toolkit will own the loop")
            try:
                return glutMainLoop()
            finally:
                self.context.closeJournals('mainloop-ended')
                self.release()
        # Otherwise freeglut calls exit() from inside the window's close
        # button, and nothing after the loop ever runs.
        if available(glutSetOption):
            glutSetOption(GLUT_ACTION_ON_WINDOW_CLOSE,
                          GLUT_ACTION_CONTINUE_EXECUTION)
        return super().mainLoop()

    @classmethod
    def run(cls, contextClass: type[Context], *args: Any, **named: Any) -> Any:
        """GLUT up first, then the context, then its loop

        A context class that sets ``glutWorldMenu`` gets the pop-up menu of
        worlds to load (:meth:`createWorldMenu`).
        """
        ensureGlutInitialised()
        context = contextClass(*args, **named)
        system = context.windowsystem
        if getattr(context, 'glutWorldMenu', False) and isinstance(system, cls):
            system.createWorldMenu()
        return context.profiledMainLoop()

    # -- input ----------------------------------------------------------------

    def onDisplay(self) -> None:
        """GLUT has asked for the window to be drawn"""
        self.context.triggerRedraw(1)

    def onKeyDown(self, character: Any, x: int, y: int) -> None:
        context = self.context
        modifiers = glutGetModifiers()
        if character in context.heldKeys():
            context.noteNativeRepeat()      # already down, so GLUT is repeating
        context.noteKeyDown(character, modifiers)
        context.ProcessEvent(
            GLUTKeyboardEvent(context, character, x, y, 1, modifiers))

    def onKeyUp(self, character: Any, x: int, y: int) -> None:
        self.context.noteKeyUp(character)
        self.context.ProcessEvent(
            GLUTKeyboardEvent(self.context, character, x, y, 0, glutGetModifiers()))

    def onCharacter(self, character: Any, x: int, y: int) -> None:
        """A character key: the key going down, and the character it typed"""
        self.onKeyDown(character, x, y)
        self.context.ProcessEvent(
            GLUTKeypressEvent(self.context, character, x, y, glutGetModifiers()))

    def emitKey(self, key: Any, state: int, modifiers: Any) -> None:
        """Send a key transition GLUT did not report

        ``modifiers`` is the mask that came with the press, so the synthetic
        release matches the binding the press did.  A key event carries a
        pointer position that nothing reads, hence the zeroes.
        """
        self.context.ProcessEvent(
            GLUTKeyboardEvent(self.context, key, 0, 0, state, modifiers))

    def onEntry(self, state: int) -> None:
        """Let go of held keys as the pointer leaves the window

        GLUT reports no focus change of its own, and this is the moment after
        which a key that is down stops being reported: without a release the
        key stays held for the rest of the session, and the camera keeps moving
        with nobody touching the keyboard.
        """
        if not state:
            self.context.clearHeldKeys()

    def onMouseButton(self, button: int, state: int, x: int, y: int) -> None:
        self.context.addPickEvent(
            GLUTMouseButtonEvent(self.context, button, state, x, y,
                                 glutGetModifiers()))
        self.context.triggerPick()

    def onMouseMove(self, x: int, y: int) -> None:
        """The pointer moved

        The movement sampler is told directly as well as through the pick
        queue: a mouse-look mode wants every scrap of motion as it happens,
        while a pick event is only delivered once the selection buffer resolves
        it -- and not at all when the pointer is over nothing or picking is off.

        A movement the window made itself -- the warp that keeps a grabbed
        pointer in the middle of the window -- updates where the pointer is and
        goes no further: it is not motion the user asked for, and it is not a
        click on anything.

        Both are told in the pick point's origin, y counting *upward* from the
        bottom, since that is what everything downstream of the context works
        in and GLUT counts it the other way.
        """
        context = self.context
        if not self.pointerMoved(x, y):
            return
        context.addPickEvent(GLUTMouseMoveEvent(context, x, y))
        context.triggerPick()

    # -- the world menu -------------------------------------------------------

    def createWorldMenu(self) -> Any:
        """Attach a pop-up menu of worlds to load to the middle button

        The VRML97 worlds under ``OpenGLContext/tests/wrls`` and the URLs in
        the test set, each loaded into the context with
        :meth:`~OpenGLContext.vrmlcontext.VRMLSceneMixin.load` when chosen.
        """
        import glob
        import os

        from OpenGLContext import tests
        from OpenGLContext.tests.resources import test_vrml_set_txt

        self.worldPaths = []
        base = os.path.join(os.path.dirname(tests.__file__), 'wrls', '*.wrl')
        fileMenu = glutCreateMenu(self.onMenuLoad)
        for path in glob.glob(base):
            self.worldPaths.append(path)
            glutAddMenuEntry(os.path.join('wrls', os.path.basename(path)),
                             len(self.worldPaths) - 1)
        urlMenu = glutCreateMenu(self.onMenuLoad)
        for line in test_vrml_set_txt.data.split('\n'):
            path = line.strip()
            if path and not path.startswith('#'):
                self.worldPaths.append(path)
                glutAddMenuEntry(path, len(self.worldPaths) - 1)
        loadMenu = glutCreateMenu(self.onMenuLoad)
        glutAddSubMenu("Load File", fileMenu)
        glutAddSubMenu("Load URL", urlMenu)
        glutAttachMenu(GLUT_MIDDLE_BUTTON)
        return loadMenu

    def onMenuLoad(self, item: int) -> None:
        """Load the world the chosen menu entry names"""
        context = self.context
        context.load(self.worldPaths[item])
        platform = context.getViewPlatform()
        platform.setPosition(context.initialPosition)
        platform.setOrientation(context.initialOrientation)
        context.triggerRedraw(force=1)
