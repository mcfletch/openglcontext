"""Context functionality using the GLFW windowing API

GLFW provides modern OpenGL context creation with support for:
- Core and compatibility profiles
- OpenGL version selection
- Debug contexts
- Forward compatibility
"""
from __future__ import print_function

try:
    import glfw
except ImportError:
    raise ImportError("The glfw package is required for the GLFW GL Context. Install with: pip install glfw")

from OpenGL.GL import *
from OpenGLContext.context import Context
from OpenGLContext.events import glfwevents
from OpenGLContext import contextdefinition
import logging

log = logging.getLogger(__name__)


class GLFWContext(
    glfwevents.EventHandlerMixin,
    Context,
):
    """Implementation of Context API under GLFW

    GLFW provides modern OpenGL context creation with better support
    for OpenGL core profiles, version selection, and debug contexts.
    """

    window = None

    def __init__(self, definition=None, **named):
        # Set up the context definition
        if definition is None:
            definition = contextdefinition.ContextDefinition(**named)
        else:
            for key, value in named.items():
                setattr(definition, key, value)
        self.contextDefinition = definition

        # Initialize GLFW
        if not glfw.init():
            raise RuntimeError("Failed to initialize GLFW")

        # Set window hints from definition
        self._setWindowHints(definition)

        # Create window
        width, height = [int(i) for i in definition.size]
        title = definition.title or self.getApplicationName()
        self.window = glfw.create_window(width, height, title, None, None)

        if not self.window:
            glfw.terminate()
            raise RuntimeError("Failed to create GLFW window")

        # Make context current before calling Context.__init__
        glfw.make_context_current(self.window)

        # Call base Context initialization
        Context.__init__(self, definition)

        # Set initial viewport
        self.ViewPort(*definition.size)

    def _setWindowHints(self, definition):
        """Apply ContextDefinition to GLFW window hints"""
        # Reset to defaults
        glfw.default_window_hints()

        # Double buffering (GLFW default is True)
        if definition.doubleBuffer:
            glfw.window_hint(glfw.DOUBLEBUFFER, glfw.TRUE)
        else:
            glfw.window_hint(glfw.DOUBLEBUFFER, glfw.FALSE)

        # Depth buffer
        if definition.depthBuffer > -1:
            glfw.window_hint(glfw.DEPTH_BITS, definition.depthBuffer)
        else:
            glfw.window_hint(glfw.DEPTH_BITS, 24)  # sensible default

        # Stencil buffer
        if definition.stencilBuffer > -1:
            glfw.window_hint(glfw.STENCIL_BITS, definition.stencilBuffer)

        # Accumulation buffer (deprecated in modern GL, but GLFW supports it)
        if definition.accumulationBuffer > -1:
            bits = definition.accumulationBuffer
            glfw.window_hint(glfw.ACCUM_RED_BITS, bits)
            glfw.window_hint(glfw.ACCUM_GREEN_BITS, bits)
            glfw.window_hint(glfw.ACCUM_BLUE_BITS, bits)
            glfw.window_hint(glfw.ACCUM_ALPHA_BITS, bits)

        # Multisampling
        if definition.multisampleSamples > 0:
            glfw.window_hint(glfw.SAMPLES, definition.multisampleSamples)

        # Stereo
        if definition.stereo > 0:
            glfw.window_hint(glfw.STEREO, glfw.TRUE)

        # OpenGL version
        if definition.version[0] > 0:
            glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, int(definition.version[0]))
            glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, int(definition.version[1]))

        # Profile (core vs compatibility)
        if definition.profile == "core":
            glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
            glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
        elif definition.profile == "compatibility" and definition.version[0] >= 3:
            # Only set compatibility profile for GL 3.0+
            glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_COMPAT_PROFILE)

        # Debug context
        if definition.debug:
            glfw.window_hint(glfw.OPENGL_DEBUG_CONTEXT, glfw.TRUE)

        # Make window resizable
        glfw.window_hint(glfw.RESIZABLE, glfw.TRUE)

    def setupCallbacks(self):
        """Register GLFW callbacks"""
        if self.window:
            glfw.set_key_callback(self.window, self._keyCallback)
            glfw.set_char_callback(self.window, self._charCallback)
            glfw.set_mouse_button_callback(self.window, self._mouseButtonCallback)
            glfw.set_cursor_pos_callback(self.window, self._cursorPosCallback)
            glfw.set_framebuffer_size_callback(self.window, self._framebufferSizeCallback)
            glfw.set_window_close_callback(self.window, self._windowCloseCallback)

    def _keyCallback(self, window, key, scancode, action, mods):
        """GLFW key callback wrapper"""
        self.glfwOnKey(window, key, scancode, action, mods)

    def _charCallback(self, window, codepoint):
        """GLFW character callback wrapper"""
        self.glfwOnCharacter(window, codepoint)

    def _mouseButtonCallback(self, window, button, action, mods):
        """GLFW mouse button callback wrapper"""
        self.glfwOnMouseButton(window, button, action, mods)

    def _cursorPosCallback(self, window, xpos, ypos):
        """GLFW cursor position callback wrapper"""
        self.glfwOnCursorPos(window, xpos, ypos)

    def _framebufferSizeCallback(self, window, width, height):
        """GLFW framebuffer size callback wrapper"""
        self.glfwOnFramebufferSize(window, width, height)

    def _windowCloseCallback(self, window):
        """GLFW window close callback"""
        self.OnQuit()

    def setCurrent(self):
        """Make this context's OpenGL context current"""
        Context.setCurrent(self)
        if self.window:
            glfw.make_context_current(self.window)

    def SwapBuffers(self):
        """Swap the front and back buffers"""
        if self.window:
            glfw.swap_buffers(self.window)

    def OnResize(self, width, height):
        """Handle window resize"""
        self.setCurrent()
        try:
            self.ViewPort(width, height)
        finally:
            self.unsetCurrent()
        self.triggerRedraw(1)

    def OnQuit(self, event=None):
        """Clean up and exit"""
        if self.window:
            glfw.set_window_should_close(self.window, True)
        return super(GLFWContext, self).OnQuit(event)

    def MainLoop(self):
        """Run the main event loop"""
        renderedFirst = False

        while self.window and not glfw.window_should_close(self.window):
            # Process pending events first
            glfw.poll_events()

            # Call OnIdle if defined - this is how animations trigger redraws
            # (e.g. nehe4.py calls triggerRedraw(1) in OnIdle)
            if hasattr(self, 'OnIdle'):
                self.OnIdle()

            # Wait briefly for redraw requests (allows time events to accumulate)
            timeout = self.drawPollTimeout
            self.redrawRequest.wait(timeout)

            # Always call OnDraw - force=0 allows DoEventCascade to process
            # time events which may trigger redraws for animations
            if self.redrawRequest.isSet() or not renderedFirst:
                renderedFirst = True
                self.OnDraw(force=1)
            else:
                # This processes time events and redraws if they generated changes
                self.OnDraw(force=0)

        # Cleanup
        if self.window:
            glfw.destroy_window(self.window)
            self.window = None
        glfw.terminate()

    def ContextMainLoop(cls, *args, **named):
        """Class method to create and run the context"""
        instance = cls(*args, **named)

        if instance.contextDefinition.profileFile:
            import cProfile
            return cProfile.runctx(
                "instance.MainLoop()",
                globals(),
                locals(),
                instance.contextDefinition.profileFile
            )

        return instance.MainLoop()

    ContextMainLoop = classmethod(ContextMainLoop)


if __name__ == "__main__":

    class TestRenderer(GLFWContext):
        def Render(self, mode=None):
            print('rendering')
            GLFWContext.Render(self, mode)
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            print('done render')

    TestRenderer.ContextMainLoop()
