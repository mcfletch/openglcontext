#! /usr/bin/env python
"""Trace what a right-drag does, from the backend callback to the camera.

Run this instead of ``oglc-view`` and right-drag in the window; every step the
event takes is printed, so where it stops is visible rather than guessed at::

    python tests/diag_examine.py tests/wrls/viewpoints.wrl
    python tests/diag_examine.py path/to/model.glb

What each line means:

``BACKEND``   the GLFW callback fired, with the button number *it* reported and
              the number OpenGLContext mapped it to.  Examine is bound to
              button **1**, so a right button reporting anything else never
              reaches it.
``CONTEXT``   the event arrived at the context's ``ProcessEvent``.
``OVERLAY``   a panel is up, so it gets the event and the world does not.  A
              menu left open would do this.
``EXAMINE``   ``startExamineMode`` ran -- the drag was recognised.
``MOVE``      a mouse-move reached the context while a button was held, with
              which buttons it thinks are down.
``CAMERA``    the view platform's orientation, printed whenever it changes.

Nothing here is imported by the viewer; it is a diagnostic, and deleting it
costs nothing.
"""
import os
import sys

os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')

from OpenGLContext.bin import view                              # noqa: E402
from OpenGLContext.events import glfwevents                     # noqa: E402
from OpenGLContext.move import movementmanager                  # noqa: E402


def say(*parts):
    sys.stderr.write(' '.join(str(part) for part in parts) + '\n')
    sys.stderr.flush()


# -- the backend callback ---------------------------------------------------
_realButtonEvent = glfwevents.GLFWMouseButtonEvent.__init__


def tracedButtonEvent(self, context, button, state, x, y, modifiers=0):
    _realButtonEvent(self, context, button, state, x, y, modifiers)
    say('BACKEND  button glfw=%s -> oglc=%s  state=%s  at=%s'
        % (button, self.button, self.state, (x, y)))


glfwevents.GLFWMouseButtonEvent.__init__ = tracedButtonEvent

# -- the examine mode itself ------------------------------------------------
_realExamine = movementmanager.MovementManager.startExamineMode


def tracedExamine(self, event):
    say('EXAMINE  startExamineMode on %s' % (type(self).__name__,))
    try:
        return _realExamine(self, event)
    except Exception as error:                  # pragma: no cover - diagnostic
        say('EXAMINE  FAILED: %r' % (error,))
        raise


movementmanager.MovementManager.startExamineMode = tracedExamine


class Traced(view.TestContext):
    """The viewer, saying what reaches it and what the camera does about it."""

    _lastOrientation = None

    def ProcessEvent(self, event):
        kind = getattr(event, 'type', None)
        if kind == 'mousebutton':
            say('CONTEXT  mousebutton button=%s state=%s pick=%s'
                % (getattr(event, 'button', None), getattr(event, 'state', None),
                   getattr(event, 'pickPoint', None)))
        elif kind == 'mousemove' and getattr(event, 'buttons', ()):
            say('MOVE     buttons=%s pick=%s'
                % (tuple(event.buttons), getattr(event, 'pickPoint', None)))
        if kind in ('mousebutton', 'mousemove'):
            # Asked *before* dispatch and from the stack itself: a handled
            # event returns None from ProcessEvent whether or not anything
            # swallowed it, so the return value says nothing about this.
            stack = getattr(self, '_overlays', None)
            if stack is not None and stack.visible:
                say('OVERLAY  a panel is up; it gets this, the world does not')
        result = super(Traced, self).ProcessEvent(event)
        self._reportCamera()
        return result

    def _reportCamera(self):
        platform = getattr(self, 'platform', None)
        if platform is None:
            return
        now = tuple(round(float(v), 5) for v in platform.quaternion)
        if now != self._lastOrientation:
            self._lastOrientation = now
            say('CAMERA   %s' % (now,))

    def OnInit(self):
        super(Traced, self).OnInit()
        say('READY    movementManager=%s  examine is bound to oglc button 1'
            % (type(getattr(self, 'movementManager', None)).__name__,))
        say('READY    right-drag in the window now; ctrl-c or Escape to stop')


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    Traced.options = view.parse_args(argv, prog='diag_examine')
    view.apply_render_env(Traced.options)
    size = Traced.options.size
    return (Traced.ContextMainLoop(size=size) if size
            else Traced.ContextMainLoop())


if __name__ == '__main__':
    main()
