#! /usr/bin/env python3
"""Build GLUT contexts one way or another and report whether the process lived.

Run as a subprocess by ``tests/unit/test_glut_initialisation.py``: freeglut ends
the process rather than raising when it is unhappy, so "did it survive" is a
question only another process can ask.

Usage:  _glut_init_drive.py <step> [<step> ...]
"""
import os
import sys

os.environ['OPENGLCONTEXT_BACKEND'] = 'glut'
os.environ.setdefault('OPENGLCONTEXT_HIDDEN', '1')
os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'

from OpenGL.GL import (                                     # noqa: E402
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_RGB, GL_UNSIGNED_BYTE,
    glClear, glClearColor, glReadPixels,
)
from OpenGLContext.glutinteractivecontext import (          # noqa: E402
    GLUTInteractiveContext,
)


def say(name, value):
    print('%s %s' % (name, value), flush=True)


class Driven(GLUTInteractiveContext):
    """A context that clears to a known colour and nothing else"""

    def OnInit(self):
        pass

    def Render(self, mode=None):
        glClearColor(0.25, 0.5, 0.75, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)


def build():
    """The case that used to end the process: a context made directly"""
    context = Driven(size=(128, 96))
    say('BUILT', context.windowID is not None)
    context.releaseWindow()


def render():
    context = Driven(size=(128, 96))
    context.OnDraw(force=1)
    context.setCurrent()
    read = glReadPixels(64, 48, 1, 1, GL_RGB, GL_UNSIGNED_BYTE)
    say('PIXEL', ' '.join(str(value) for value in bytes(read)))
    context.releaseWindow()


def several():
    """One context per test is what a suite does"""
    made = 0
    for _ in range(5):
        context = Driven(size=(64, 48))
        context.OnDraw(force=1)
        context.releaseWindow()
        made += 1
    say('MADE', made)


def mainloop():
    """``ContextMainLoop`` initialised GLUT itself, and must not do it twice"""
    class Bounded(Driven):
        frames = 0

        def OnIdle(self, *arguments):
            self.frames += 1
            if self.frames > 3:
                say('LOOPED', True)
                self._finished = True
            self.triggerRedraw(1)
            return 0

    Bounded.ContextMainLoop(size=(64, 48))


STEPS = {'build': build, 'render': render, 'several': several,
         'mainloop': mainloop}


if __name__ == '__main__':
    for name in sys.argv[1:]:
        STEPS[name]()
    say('DONE', '')
