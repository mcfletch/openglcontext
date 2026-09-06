"""VRML97 context for Tk"""

from OpenGLContext import tkinteractivecontext, vrmlcontext


class VRMLContext(
    vrmlcontext.VRMLContext,
    tkinteractivecontext.TkInteractiveContext,
):
    """Tk-specific VRML97-aware context"""
