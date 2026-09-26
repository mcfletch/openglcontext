"""The GLFW window system's Context, under the name ``VRMLContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.glfwcontext.GLFWContext`.
"""
from OpenGLContext.glfwcontext import GLFWContext

VRMLContext = GLFWContext

__all__ = ('VRMLContext',)
