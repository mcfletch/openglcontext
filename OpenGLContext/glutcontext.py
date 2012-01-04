'''Context functionality using the GLUT windowing API
'''
from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGLContext.context import Context
from OpenGLContext.events import glutevents
from OpenGLContext import contextdefinition

class GLUTContext(
    glutevents.EventHandlerMixin,
    Context,
):
    """Implementation of Context API under GLUT

    The DISPLAYMODE attribute of the class determines the
    context format through a call to glutInitDisplayMode.
    See glutInitDisplayMode documentation for allowed values.
    """
    DISPLAYMODE = GLUT_DOUBLE | GLUT_DEPTH 
    currentModifiers = 0
    def __init__ (self, definition = None, **named ):
        # set up double buffering and rgb display mode
        if definition is None:
            definition = contextdefinition.ContextDefinition( **named )
        else:
            for key,value in named.items():
                setattr( definition, key, value )
        self.contextDefinition = definition
        #glutInitDisplayMode( self.glutFlagsFromDefinition( definition ) )
        glutInit([])
#        glutInitContextVersion(3, 2)
#        glutInitContextFlags(GLUT_FORWARD_COMPATIBLE)
#        glutInitContextProfile(GLUT_CORE_PROFILE)
        
        glutInitDisplayMode( self.DISPLAYMODE )
        # set up window size for newly created windows
        apply ( glutInitWindowSize, [int(i) for i in definition.size] )
        # create a new rendering window
        self.windowID = glutCreateWindow( 
            definition.title or 
            self.getApplicationName() 
        )
        Context.__init__ (self, definition)
    CONTEXT_DEFINITION_FLAG_MAPPING = (
        ("doubleBuffer", GLUT_DOUBLE, GLUT_SINGLE, GLUT_DOUBLE ),
        ("depthBuffer", GLUT_DEPTH, 0, GLUT_DEPTH ),
        ("accumulationBuffer", GLUT_ACCUM, 0, GLUT_ACCUM ),
        ("stencilBuffer", GLUT_STENCIL, 0, GLUT_STENCIL ),
        ("rgb", GLUT_RGB, GLUT_INDEX, GLUT_RGB),
        # Alpha doesn't seem to be supported...
        #("alpha", GLUT_ALPHA, 0 ),
        ("multisampleBuffer", GLUT_MULTISAMPLE, 0, 0),
        ("multisampleSamples", GLUT_MULTISAMPLE, 0, 0),
        ("stereo", GLUT_STEREO, 0, 0 ),
    )
    def glutFlagsFromDefinition( cls, definition ):
        """Create our initialisation flags from a definition"""
        if definition:
            result = 0
            for (field,ifYes,ifNo, default) in cls.CONTEXT_DEFINITION_FLAG_MAPPING:
                if hasattr( definition, field ):
                    if getattr(definition,field) > -1:
                        if getattr( definition, field ):
                            result |= ifYes
                        else:
                            result |= ifNo
                    elif getattr( definition,field) == -1:
                        result |= default
            return result
        return cls.DISPLAYMODE
    glutFlagsFromDefinition = classmethod( glutFlagsFromDefinition )
        
    def setupCallbacks( self ):
        '''Setup the various callbacks for this context'''
        glutSetWindow( self.windowID )
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
        
        if hasattr( self, 'OnIdle' ):
            try:
                glutSetIdleFuncCallback(self.OnIdle)
                glutIdleFunc()
            except NameError:
                glutIdleFunc(self.OnIdle)
            
    def setCurrent (self):
        ''' Acquire the GL "focus" '''
        Context.setCurrent( self )
        glutSetWindow( self.windowID )
    def OnRedisplay (self ):
        ''' windowing library has asked us to redisplay '''
        self.triggerRedraw(1)
    def OnResize (self, width, height):
        """Windowing library has resized the window"""
        self.setCurrent()
        try:
            self.ViewPort( width, height )
        finally:
            self.unsetCurrent()
        self.triggerRedraw(1)
    def SwapBuffers (self,):
        """Implementation: swap the buffers"""
        glutSwapBuffers() # should really check to be sure we are double buffered

    def ContextMainLoop( cls, *args, **named ):
        """Mainloop for the GLUT testing context"""
        from OpenGL.GLUT import glutInit, glutMainLoop
        # initialize GLUT windowing system
        import sys
        try:
            glutInit( sys.argv)
        except TypeError:
            import string
            glutInit( ' '.join(sys.argv))
        
        render = cls( *args, **named)
        if hasattr( render, 'createMenus' ):
            render.createMenus()
        return glutMainLoop()
    ContextMainLoop = classmethod( ContextMainLoop )

if __name__ == "__main__":
    from drawcube import drawCube
    class TestRenderer(GLUTContext):
        center = 2,0,-4
        def Render( self, mode = None):
            print 'rendering'
            GLUTContext.Render (self, mode)
            print 'done render'
##			glTranslated ( *self.center )
##			drawCube()
    TestRenderer.ContextMainLoop( )
