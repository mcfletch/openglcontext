"""Interactive context using the wxPython API (provides navigation support)"""
from OpenGLContext import interactivecontext, wxcontext, context
from OpenGLContext.move import viewplatformmixin
from OpenGL.GLUT import *

class wxInteractiveContext (
    viewplatformmixin.ViewPlatformMixin,
    interactivecontext.InteractiveContext,
    wxcontext.wxContext,
):
    """Sub-class of Context providing navigation support

    This is basically just a shell class which inherits
    all of its functionality from its superclasses.
    """

if __name__ == '__main__':
    from drawcube import drawCube
    from OpenGL.GL import glTranslated 
    class TestContext( wxInteractiveContext ):
        def Render( self, mode=None):
            wxInteractiveContext.Render (self, mode)
            glTranslated ( 2,0,-4)
            drawCube()
    TestContext.ContextMainLoop()