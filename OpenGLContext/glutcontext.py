'''Context functionality using the GLUT windowing API
'''
import logging

from OpenGL.GL import *
from OpenGL.GLUT import *
try:
    from OpenGL.GLUT import GLUT_INIT_STATE
except ImportError:                     # pragma: no cover - an original GLUT
    GLUT_INIT_STATE = None
from OpenGLContext import contextresources
from OpenGLContext.context import Context
from OpenGLContext.events import glutevents
from OpenGLContext.looptrace import LoopTrace

log = logging.getLogger(__name__)

#: Set once ``glutInit`` has been called in this process.  Read through
#: :func:`glutInitialised`; nothing outside this module writes it.
_initialised = False


def glutInitialised():
    """Whether ``glutInit`` has been called in this process

    freeglut offers ``glutGet(GLUT_INIT_STATE)`` and is asked where it does,
    since a process that initialised GLUT some other way -- a host application,
    another library -- is one this module has not seen do it.  Where the query
    is not there, what this module itself did is the best answer available.
    """
    if _initialised:
        return True
    if not glutGet or GLUT_INIT_STATE is None:
        return False
    try:
        return bool(glutGet(GLUT_INIT_STATE))
    except Exception:                   # pragma: no cover - an original GLUT
        return False


def ensureGlutInitialised(argv=None):
    """Call ``glutInit`` unless somebody already has; answer whether it ran

    **Both halves matter, and each is fatal on its own.**  ``glutCreateWindow``
    before ``glutInit`` makes freeglut print

        freeglut ERROR: Function <glutCreateWindow> called without first
        calling 'glutInit'.

    and call ``exit()``; a *second* ``glutInit`` makes it say ``illegal
    glutInit() reinitialization attempt`` and exit as well.  Neither is an
    exception a caller could answer, so the question is asked here, once, on
    every path that needs a window -- the constructor as much as
    :meth:`GLUTContext.ContextMainLoop`.
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


class GLUTContext(
    glutevents.EventHandlerMixin,
    Context,
):
    """Implementation of Context API under GLUT

    The DISPLAYMODE attribute of the class determines the
    context format iff there is no contextDefinition override
    (parameter definition in init).
    """

    DISPLAYMODE = GLUT_DOUBLE | GLUT_DEPTH
    currentModifiers = 0
    providesGLUT = True
    windowID = None
    #: True while the pointer is hidden and being warped back to the middle of
    #: the window for a mouse-look mode.
    _pointerGrabbed = False
    #: Where the pointer was last warped to, so the movement the warp itself
    #: generates can be told from a real one.
    _pointerWarpedTo = None
    #: Set when the loop should end; the window's close button and OnQuit both
    #: raise it, and MainLoop watches it.
    _finished = False

    def __init__(self, definition=None, **named):
        # set up double buffering and rgb display mode.  Resolved before the
        # window exists, since the display mode and the profile below are both
        # built from it -- see Context.resolveDefinition.
        definition = self.resolveDefinition(definition, **named)
        self.contextDefinition = definition

        # The order of operations for forward-compatible contexts is critical,
        # and the first step is not optional: a window asked for before
        # glutInit ends the process.  See ensureGlutInitialised.
        # 1. glutInit
        # 2. glutInitContextVersion
        # 3. glutInitContextFlags + glutInitContextProfile
        # 4. glutInitDisplayMode
        # 5. glutCreateWindow

        ensureGlutInitialised()
        if glutInitContextVersion and definition.version[0]:
            glutInitContextVersion(*[int(v) for v in definition.version])
        if glutInitContextProfile:
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
        glutInitDisplayMode(self.glutFlagsFromDefinition(definition))
        # set up window size for newly created windows
        glutInitWindowSize(*[int(i) for i in definition.size])
        # A new GLUT window takes the thread as it is made, and a thread
        # another window system's context is holding is an X BadAccess that
        # ends the process.  See Context.releaseForeignContext.
        self.releaseForeignContext()
        # create a new rendering window
        self.windowID = glutCreateWindow(definition.title or self.getApplicationName())
        # Recorded while GLUT's own window is current, which it is the moment
        # it is made: without it the first setCurrent would take the context
        # for a foreign one.
        self.bindContextResources(self._glHandle())
        # GLUT has no "create it hidden" hint, so it is hidden the instant it
        # exists.  See renderoptions.hidden_window: rendering and reading back
        # are unaffected, and a suite of GL scripts should not take over the
        # screen of whoever is running it.
        from OpenGLContext import renderoptions
        if renderoptions.hidden_window():
            glutHideWindow()
        elif renderoptions.fullscreen_window(definition):
            glutFullScreen()
        # Before the base class has stored it, so the definition is passed
        # rather than read back off self.
        self.applyVSync(definition)
        Context.__init__(self, definition)
        # GLUT reports a window's size through its reshape callback, which is
        # delivered by the main loop -- so a context whose first frame is drawn
        # before the loop has run would size everything from a zero viewport.
        # The window itself knows, and can be asked.
        self.ViewPort(glutGet(GLUT_WINDOW_WIDTH), glutGet(GLUT_WINDOW_HEIGHT))

    def setFullscreen(self, fullscreen):
        """Fill the screen, or go back to the size the definition asked for."""
        if not self.windowID:
            return False
        glutSetWindow(self.windowID)
        if fullscreen:
            glutFullScreen()
        else:
            width, height = [int(i) for i in self.contextDefinition.size]
            glutPositionWindow(100, 100)
            glutReshapeWindow(width, height)
        return True

    def settingsChanged(self):
        """Re-apply the window-level settings a changed definition affects."""
        from OpenGLContext import renderoptions
        self.applyVSync()
        self.setFullscreen(renderoptions.fullscreen_window(self))
        Context.settingsChanged(self)

    def applyVSync(self, definition=None):
        """Wait for the display's refresh, or don't (ContextDefinition.vsync)

        GLUT names nothing for this, so it goes to the window system's own
        swap-control extension; see :mod:`OpenGLContext.swapcontrol`, which
        answers False where there is none.
        """
        from OpenGLContext import renderoptions, swapcontrol
        source = self if definition is None else definition
        wanted = renderoptions.flag(
            source, 'vsync',
            not renderoptions.env_flag('OPENGLCONTEXT_NO_VSYNC', False))
        if self.windowID:
            glutSetWindow(self.windowID)
        return swapcontrol.set_swap_interval(1 if wanted else 0)

    def setPointerCapture(self, capture):
        """Hide the pointer and keep it in the window, for a mouse-look mode

        GLUT has no relative-motion mode, so the pointer is warped back to the
        middle of the window after every movement -- which is what makes the
        motion unbounded, since a pointer that stops at the edge of the screen
        is a view that stops turning there.  The warp arrives back as an
        ordinary movement and is recognised and dropped; see
        :meth:`OpenGLContext.events.glutevents.EventHandlerMixin.glutOnMouseMove`.
        """
        if not self.windowID:
            return False
        glutSetWindow(self.windowID)
        self._pointerGrabbed = bool(capture)
        self._pointerWarpedTo = None
        glutSetCursor(GLUT_CURSOR_NONE if capture else GLUT_CURSOR_INHERIT)
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
        """Put the pointer back in the middle of the window, if it is grabbed"""
        if not self._pointerGrabbed or not self.windowID:
            return
        glutSetWindow(self.windowID)
        middle = (int(glutGet(GLUT_WINDOW_WIDTH)) // 2,
                  int(glutGet(GLUT_WINDOW_HEIGHT)) // 2)
        self._pointerWarpedTo = middle
        glutWarpPointer(*middle)

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

    CONTEXT_DEFINITION_FLAG_MAPPING = (
        ("doubleBuffer", GLUT_DOUBLE, GLUT_SINGLE, GLUT_DOUBLE),
        ("depthBuffer", GLUT_DEPTH, 0, GLUT_DEPTH),
        # -1 means "don't ask", as it does for this buffer in every other
        # backend: an accumulation buffer is deprecated in GL 3.0 and absent
        # from core, and a driver that publishes no accumulation-buffer config
        # gives freeglut nothing to match, which aborts the process rather than
        # falling back.  A caller that wants one still says so.
        ("accumulationBuffer", GLUT_ACCUM, 0, 0),
        ("stencilBuffer", GLUT_STENCIL, 0, GLUT_STENCIL),
        ("rgb", GLUT_RGB, GLUT_INDEX, GLUT_RGB),
        # Alpha doesn't seem to be supported...
        # ("alpha", GLUT_ALPHA, 0 ),
        ("multisampleBuffer", GLUT_MULTISAMPLE, 0, 0),
        ("multisampleSamples", GLUT_MULTISAMPLE, 0, 0),
        ("stereo", GLUT_STEREO, 0, 0),
        ("debug", GLUT_DEBUG, 0, 0),
    )

    def glutFlagsFromDefinition(cls, definition):
        """Create our initialisation flags from a definition"""
        if definition:
            result = 0
            for field, ifYes, ifNo, default in cls.CONTEXT_DEFINITION_FLAG_MAPPING:
                if hasattr(definition, field):
                    if getattr(definition, field) > -1:
                        if getattr(definition, field):
                            result |= ifYes
                        else:
                            result |= ifNo
                    elif getattr(definition, field) == -1:
                        result |= default
            return result
        return cls.DISPLAYMODE

    glutFlagsFromDefinition = classmethod(glutFlagsFromDefinition)

    def setupCallbacks(self):
        '''Setup the various callbacks for this context'''
        glutSetWindow(self.windowID)
        try:
            glutSetReshapeFuncCallback(self.OnResize)
            glutReshapeFunc()
        except NameError:
            glutReshapeFunc(self.OnResize)
        try:
            glutSetDisplayFuncCallback(self.OnRedisplay)
            glutDisplayFunc()
        except NameError:
            glutDisplayFunc(self.OnRedisplay)
        try:
            glutSetKeyboardFuncCallback(self.glutOnCharacter)
            glutKeyboardFunc()
        except NameError:
            glutKeyboardFunc(self.glutOnCharacter)
        try:
            glutSetKeyboardUpFuncCallback(self.glutOnKeyUp)
            glutKeyboardUpFunc()
        except NameError:
            glutKeyboardUpFunc(self.glutOnKeyUp)
        try:
            glutSetSpecialFuncCallback(self.glutOnKeyDown)
            glutSpecialFunc()
        except NameError:
            glutSpecialFunc(self.glutOnKeyDown)
        try:
            glutSetSpecialUpFuncCallback(self.glutOnKeyUp)
            glutSpecialUpFunc()
        except NameError:
            glutSpecialUpFunc(self.glutOnKeyUp)
        try:
            glutSetMouseFuncCallback(self.glutOnMouseButton)
            glutMouseFunc()
        except NameError:
            glutMouseFunc(self.glutOnMouseButton)
        try:
            glutSetMotionFuncCallback(self.glutOnMouseMove)
            glutMotionFunc()
        except NameError:
            glutMotionFunc(self.glutOnMouseMove)
        try:
            glutSetPassiveMotionFuncCallback(self.glutOnMouseMove)
            glutPassiveMotionFunc()
        except NameError:
            glutPassiveMotionFunc(self.glutOnMouseMove)
        # GLUT reports no focus change; the pointer leaving the window is the
        # nearest thing it has, and it is when a held key is about to stop
        # being reported.  See glutOnEntry.
        try:
            glutSetEntryFuncCallback(self.glutOnEntry)
            glutEntryFunc()
        except NameError:
            glutEntryFunc(self.glutOnEntry)

    def pumpWindowEvents(self):
        """Dispatch what GLUT has queued; see Context.pumpWindowEvents

        Needs freeglut's ``glutMainLoopEvent``; an original GLUT owns its loop
        and offers no way to step it, and says so by answering False.
        """
        if not glutMainLoopEvent:
            return False
        glutMainLoopEvent()
        return True

    def glutOnEntry(self, state):
        """Let go of held keys as the pointer leaves the window

        GLUT reports no focus change of its own, and this is the moment after
        which a key that is down stops being reported: without a release the
        key stays held for the rest of the session, and the camera keeps moving
        with nobody touching the keyboard.
        """
        if not state:
            self.clearHeldKeys()

    def setCurrent(self):
        '''Acquire the GL "focus"

        **Nothing is released here**, unlike every other backend.  GLUT
        remembers which of its windows is current and ``glutSetWindow`` on that
        one does nothing, so a context let go of behind its back can never be
        taken again: after an external release, ``glutSetWindow`` leaves
        ``glGetString(GL_VERSION)`` answering None.  The one release GLUT can
        afford is before its window is made, where it is the thing about to
        take the thread (see ``__init__``).
        '''
        Context.setCurrent(self)
        glutSetWindow(self.windowID)
        handle = self._glHandle()
        if handle is None and self._ownContext is not None:
            log.warning(
                'GLUT cannot take the drawing thread back: something else in '
                'this process holds a GL context, and GLUT re-makes a window '
                'current only when it believes another one was. Frames from '
                'this window will be empty.'
            )
        self.bindContextResources(handle)

    def _glHandle(self):
        """The GL context handle the caches and PyOpenGL key on.

        The GLUT window id is not it: what identifies a context to PyOpenGL is
        the platform's own handle.  Read with this window current, which is the
        only moment the answer is about this window.
        """
        return contextresources.context_key()

    def releaseWindow(self):
        """Let this window's GL objects go, then destroy the window

        With the window still whole and its context current, so the caches
        holding its GL names let go of them before they stop meaning anything.
        Calling it twice is calling it once.
        """
        if not self.windowID:
            return
        glutSetWindow(self.windowID)
        self.releaseContextResources(self._glHandle())
        glutDestroyWindow(self.windowID)
        self.windowID = None

    def OnIdle(self, *arguments):
        """Animation hook for the GLUT loop

        The default ``Context.OnIdle`` renders through ``drawPoll``, which would
        double up with the render :meth:`MainLoop` performs. Demos that animate
        override this to call ``triggerRedraw``.
        """
        return 0

    def OnQuit(self, event=None):
        """Quit the application (forcibly)"""
        self._finished = True
        glutDisplayFunc(null_display)
        glutIdleFunc(None)
        self.releaseWindow()
        if glutLeaveMainLoop:
            glutLeaveMainLoop()
        try:
            # Asked for as a truth value first, exactly as glutLeaveMainLoop is
            # above: the name being bound says PyOpenGL declares the entry
            # point, not that the GLUT in front of us exports it. A build that
            # does not -- and the GLUT most often found on Windows does not --
            # raises NullFunctionError from the call, which is not a NameError
            # and so took the whole shutdown with it.
            if fgDeinitialize:
                fgDeinitialize(False)
        except NameError:
            # older PyOpenGL without the FreeGLUT deinitialize function
            pass
        return super(GLUTContext, self).OnQuit(event)

    def OnRedisplay(self):
        '''windowing library has asked us to redisplay'''
        self.triggerRedraw(1)

    def OnResize(self, width, height):
        """Windowing library has resized the window"""
        self.setCurrent()
        try:
            self.ViewPort(width, height)
        finally:
            self.unsetCurrent()
        self.triggerRedraw(1)

    def SwapBuffers(
        self,
    ):
        """Implementation: swap the buffers"""
        glutSwapBuffers()  # should really check to be sure we are double buffered

    def MainLoop(self):
        """Run the event loop, one iteration at a time

        Built on ``glutMainLoopEvent`` rather than ``glutMainLoop`` so the
        engine drives the frame here as it does under every other backend: one
        render per iteration whatever arrived, so a burst of input coalesces
        into a single frame; the phases timed; and an end to the loop that the
        journals can be closed at.

        A GLUT without ``glutMainLoopEvent`` -- an original GLUT rather than
        freeglut -- keeps the older arrangement, where GLUT owns the loop and
        calls back.
        """
        if not glutMainLoopEvent:
            log.info("this GLUT has no glutMainLoopEvent; "
                     "the toolkit will own the loop")
            return glutMainLoop()
        # We drive rendering ourselves, so suppress the synchronous
        # in-callback renders triggerPick/triggerRedraw would otherwise do.
        self.deferRedraw = True
        # Otherwise freeglut calls exit() from inside the window's close
        # button, and nothing below this line ever runs.
        if glutSetOption:
            glutSetOption(GLUT_ACTION_ON_WINDOW_CLOSE,
                          GLUT_ACTION_CONTINUE_EXECUTION)
        renderedFirst = False
        # A private trace when a subclass has cleared setupLoopTrace's: a
        # diagnostic must never be the reason a loop will not run.
        trace = self.loopTrace or LoopTrace()
        try:
            while self.windowID and not self._finished:
                renderedFirst = self._loopIteration(trace, renderedFirst)
        finally:
            # A loop left while it was still slow -- a closed window, a Ctrl-C
            # -- holds an episode nobody has written, and what it holds of the
            # last few seconds is what a session that ended badly is worth
            # reading for.
            if self.stallJournal is not None:
                self.stallJournal.close()
            self.stopTelemetry('mainloop-ended')
            # The engine's caches own GL objects in this context, so they have
            # to be let go before it is destroyed rather than left for a later
            # window the driver hands the same identifier.
            self.releaseWindow()

    def _loopIteration(self, trace, renderedFirst):
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
            if not self.windowID or self._finished:
                return renderedFirst
            with trace.phase('repeats'):
                self.pumpKeyRepeats()
            with trace.phase('idle'):
                self.OnIdle()
            # Wait briefly so input and time events accumulate before
            # rendering; bounded by drawPollTimeout, so this phase can go up
            # but never far up.
            with trace.phase('wait'):
                self.redrawRequest.wait(self.drawPollTimeout)
            with trace.phase('draw'):
                # force=1 when a redraw is pending; force=0 still runs the
                # event cascade so animations advance, and renders only if they
                # produced a visible change.
                if self.redrawRequest.isSet() or not renderedFirst:
                    renderedFirst = True
                    self.OnDraw(force=1)
                else:
                    self.OnDraw(force=0)
        return renderedFirst

    def ContextMainLoop(cls, *args, **named):
        """Mainloop for the GLUT testing context"""
        # The constructor asks for this too; asking here as well costs nothing
        # and keeps the windowing system up before anything else in this
        # method touches it.
        ensureGlutInitialised()
        render = cls(*args, **named)
        if hasattr(render, 'createMenus'):
            render.createMenus()
        if render.contextDefinition.profileFile:
            import cProfile
            return cProfile.runctx(
                "render.MainLoop()",
                globals(),
                locals(),
                render.contextDefinition.profileFile,
            )
        return render.MainLoop()

    ContextMainLoop = classmethod(ContextMainLoop)


def null_display():
    return


if __name__ == "__main__":

    class TestRenderer(GLUTContext):
        center = 2, 0, -4

        def Render(self, mode=None):
            print('rendering')
            GLUTContext.Render(self, mode)
            print('done render')

    ##			glTranslated ( *self.center )
    ##			drawCube()
    TestRenderer.ContextMainLoop()
