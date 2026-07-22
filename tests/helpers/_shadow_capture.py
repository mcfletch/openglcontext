"""Off-screen-ish capture runner for shadow tests (invoked as a subprocess).

Renders tests/shadow_spot.py in a core-profile GLFW context and saves the
freshly rendered back buffer to a PNG. Capturing inside a SwapBuffers override
grabs the buffer *before* it is swapped away, which is reliable in the
dev-container where reading the back buffer after the swap returns stale data.

Usage:  python tests/helpers/_shadow_capture.py {on|off} OUTPUT.png
"""
import os
import sys


def main() -> int:
    shadows = sys.argv[1] == 'on'
    out_path = sys.argv[2]

    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
    os.environ['OPENGLCONTEXT_SHADOWS'] = '1' if shadows else '0'
    os.environ.setdefault('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '8')

    # Sibling scene modules (shadow_spot) live in the parent tests/ directory.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from OpenGLContext.capture import capture_to_png
    from OpenGLContext import testingcontext
    BaseContext = testingcontext.getInteractive()
    from shadow_spot import make_scene

    light_kind = sys.argv[3] if len(sys.argv) > 3 else os.environ.get('SHADOW_LIGHT', 'spot')

    # The context exits the process on auto-quit, so save each rendered frame
    # directly to disk (overwriting); the last good frame survives.
    class CaptureContext(BaseContext):
        def OnInit(self):
            self.sg = make_scene(light_kind)

        def SwapBuffers(self):
            capture_to_png(out_path)
            return super().SwapBuffers()

    CaptureContext.ContextMainLoop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
