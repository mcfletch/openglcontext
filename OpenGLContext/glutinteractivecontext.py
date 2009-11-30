"""Interactive context using the GLUT API (provides navigation support)"""

from OpenGLContext import interactivecontext, glutcontext, context
from OpenGLContext.move import viewplatformmixin
from OpenGL.GLUT import *

class GLUTInteractiveContext (
    viewplatformmixin.ViewPlatformMixin,
    interactivecontext.InteractiveContext,
    glutcontext.GLUTContext,
):
    '''GLUT context providing camera, mouse and keyboard interaction '''
        
    
if __name__ == "__main__":
    from drawcube import drawCube
    from OpenGL.GL import glTranslated
    class TestRenderer(GLUTInteractiveContext):
        def Render( self, mode = None):
            GLUTInteractiveContext.Render (self, mode)
            glTranslated ( 2,0,-4)
            drawCube()
    # initialize GLUT windowing system
    TestRenderer.ContextMainLoop( )