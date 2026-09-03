"""VRML97 context rendering offscreen on EGL"""
from OpenGLContext import eglcontext, vrmlcontext


class VRMLContext(
    vrmlcontext.VRMLContext,
    eglcontext.EGLContext
):
    """Offscreen VRML97-aware context: loads a world and renders it headlessly"""
    pass
