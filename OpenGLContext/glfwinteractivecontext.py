"""The GLFW window system's Context, under the name ``GLFWInteractiveContext``

Every Context has the event managers, the camera and the scene loading, so
this name is :class:`~OpenGLContext.glfwcontext.GLFWContext`.
"""
from OpenGLContext.glfwcontext import GLFWContext

GLFWInteractiveContext = GLFWContext

__all__ = ('GLFWInteractiveContext',)
