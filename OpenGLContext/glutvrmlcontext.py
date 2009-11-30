"""VRML97 context for GLUT
"""
from OpenGL.GLUT import *
from OpenGLContext import glutinteractivecontext
from OpenGLContext import vrmlcontext
import os, glob

class VRMLContext(
    vrmlcontext.VRMLContext,
    glutinteractivecontext.GLUTInteractiveContext
):
    """GLUT-specific VRML97-aware Testing Context"""
    def ContextMainLoop( cls, *args, **named ):
        """Mainloop for the GLUT testing context"""
        # initialize GLUT windowing system
        import sys
        try:
            glutInit( sys.argv)
        except TypeError:
            import string
            glutInit( ' '.join(sys.argv))
        
        render = cls()
        if hasattr( render, 'createMenus' ):
            render.createMenus()
        glutMainLoop()
    ContextMainLoop = classmethod( ContextMainLoop )