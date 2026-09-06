"""VRML97 context rendering offscreen on WGL"""
from OpenGLContext import vrmlcontext, wglcontext


class VRMLContext(
    vrmlcontext.VRMLContext,
    wglcontext.WGLContext
):
    """Offscreen VRML97-aware context: loads a world and renders it headlessly"""
    pass
