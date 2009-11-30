"""Testing context for PyGame API, providing default context class and main loop

You normally use this module via the testingcontext module.
"""
from OpenGLContext import pygameinteractivecontext
from OpenGLContext import vrmlcontext
import os, glob

class VRMLContext(
    vrmlcontext.VRMLContext,
    pygameinteractivecontext.PygameInteractiveContext
):
    """GLUT-specific VRML97-aware Testing Context"""