'''Context functionality using the GLUT windowing API
'''
from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGLContext import contextresources
from OpenGLContext.context import Context
from OpenGLContext.events import glutevents


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
        self.setFullscreen(renderoptions.fullscreen_window(self))
        Context.settingsChanged(self)

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

        if hasattr(self, 'OnIdle'):
            try:
                glutSetIdleFuncCallback(self.OnIdle)
                glutIdleFunc()
            except NameError:
                glutIdleFunc(self.OnIdle)

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
        from OpenGLContext import contextresources
        return contextresources.context_key()

    def OnQuit(self, event=None):
        """Quit the application (forcibly)"""
        glutDisplayFunc(null_display)
        glutIdleFunc(None)
        if self.windowID:
            # With the window still whole and its context current, so the caches
            # holding its GL names let go of them before they stop meaning
            # anything.
            self.releaseContextResources(self._glHandle())
            glutDestroyWindow(self.windowID)
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

    def ContextMainLoop(cls, *args, **named):
        """Mainloop for the GLUT testing context"""
        from OpenGL.GLUT import glutInit, glutMainLoop

        # initialize GLUT windowing system
        import sys

        try:
            glutInit(sys.argv)
        except TypeError:
            glutInit(' '.join(sys.argv))

        render = cls(*args, **named)
        if hasattr(render, 'createMenus'):
            render.createMenus()
        return glutMainLoop()

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
