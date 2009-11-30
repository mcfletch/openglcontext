"""Testing context for PyGame API, providing default context class and main loop

You normally use this module via the testingcontext module.
"""
from OpenGLContext import wxinteractivecontext
from OpenGLContext import vrmlcontext
import os, glob

class VRMLContext(
    vrmlcontext.VRMLContext,
    wxinteractivecontext.wxInteractiveContext
):
    """GLUT-specific VRML97-aware Testing Context"""