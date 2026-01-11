"""VRML97 context for GLFW"""
from OpenGLContext import glfwinteractivecontext
from OpenGLContext import vrmlcontext


class VRMLContext(
    vrmlcontext.VRMLContext,
    glfwinteractivecontext.GLFWInteractiveContext
):
    """GLFW-specific VRML97-aware Testing Context"""
    pass
