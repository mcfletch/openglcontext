'''Context functionality using the GLUT windowing API
'''
import logging

from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGLContext import contextresources
from OpenGLContext.context import Context
from OpenGLContext.events import glutevents
from OpenGLContext.looptrace import LoopTrace

log = logging.getLogger(__name__)


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

        # Note: glutInit is called by ContextMainLoop before this __init__
        # The order of operations for forward-compatible contexts is critical:
        # 1. glutInit (already done in ContextMainLoop)
        # 2. glutInitContextVersion
        # 3. glutInitContextFlags + glutInitContextProfile
        # 4. glutInitDisplayMode
        # 5. glutCreateWindow

        if glutInitContextVersion and definition.version[0]:
            glutInitContextVersion(*[int(v) for v in definition.version])
        if glutInitContextProfile:
            # Named either way: a version hint of 3.2 or above with no profile
            # hint leaves the choice to the driver, and a driver that answers
            # with a core context has taken the fixed-function pipeline away
            # from a caller who asked for it.
            if definition.profile == 'core':
                glutInitContextFlags(GLUT_FORWARD_COMPATIBLE)
                glutInitContextProfile(GLUT_CORE_PROFILE)
            elif definition.profile == 'compatibility':
                glutInitContextProfile(GLUT_COMPATIBILITY_PROFILE)
        glutInitDisplayMode(self.glutFlagsFromDefinition(definition))
        # set up window size for newly created windows
        glutInitWindowSize(*[int(i) for i in definition.size])
        # create a new rendering window
        self.windowID = glutCreateWindow(definition.title or self.getApplicationName())
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
        '''Acquire the GL "focus"'''
        Context.setCurrent(self)
        glutSetWindow(self.windowID)
        self.bindContextResources(self._glHandle())

    def _glHandle(self):
        """The GL context handle the caches and PyOpenGL key on.

        The GLUT window id is not it: what identifies a context to PyOpenGL is
        the platform's own handle.  Read with this window current, which is the
        only moment the answer is about this window.
        """
        return contextresources.context_key()

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
        if self.windowID:
            # With the window still whole and its context current, so the caches
            # holding its GL names let go of them before they stop meaning
            # anything.
            self.releaseContextResources(self._glHandle())
            glutDestroyWindow(self.windowID)
            self.windowID = None
        if glutLeaveMainLoop:
            glutLeaveMainLoop()
        try:
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
            if self.windowID:
                # The engine's caches own GL objects in this context, so they
                # have to be let go before it is destroyed rather than left for
                # a later window the driver hands the same identifier.
                self.releaseContextResources(self._glHandle())
                glutDestroyWindow(self.windowID)
                self.windowID = None

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
                glutMainLoopEvent()
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
        from OpenGL.GLUT import glutInit

        # initialize GLUT windowing system
        import sys

        try:
            glutInit(sys.argv)
        except TypeError:
            glutInit(' '.join(sys.argv))

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
