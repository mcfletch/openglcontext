"""Interactive context using the GLFW API (provides navigation support)"""

from OpenGLContext import interactivecontext, glfwcontext, context
from OpenGLContext.move import viewplatformmixin


class GLFWInteractiveContext(
    viewplatformmixin.ViewPlatformMixin,
    interactivecontext.InteractiveContext,
    glfwcontext.GLFWContext,
):
    """GLFW context providing camera, mouse and keyboard interaction"""
    pass


if __name__ == "__main__":
    from OpenGL.GL import glTranslated, glClearColor, glClear, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT

    class TestRenderer(GLFWInteractiveContext):
        initialPosition = (0, 0, 10)

        def Render(self, mode=None):
            GLFWInteractiveContext.Render(self, mode)
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glTranslated(2, 0, -4)
            # Draw something simple
            from OpenGL.GLUT import glutSolidTeapot
            try:
                glutSolidTeapot(1.0)
            except:
                pass  # GLUT may not be available

    TestRenderer.ContextMainLoop()
