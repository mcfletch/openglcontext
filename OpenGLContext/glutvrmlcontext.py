"""VRML97 context for GLUT
"""
from OpenGLContext import glutinteractivecontext
from OpenGLContext import vrmlcontext


class VRMLContext(
    vrmlcontext.VRMLContext,
    glutinteractivecontext.GLUTInteractiveContext
):
    """GLUT-specific VRML97-aware Testing Context

    ``ContextMainLoop`` is the GLUT context's own: it initialises GLUT once --
    a second ``glutInit`` ends the process -- builds the menus a VRML context
    offers, and drives the frame itself.
    """
