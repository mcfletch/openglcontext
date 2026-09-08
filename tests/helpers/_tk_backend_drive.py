#! /usr/bin/env python3
"""Exercise one thing the Tk backend does, and report what happened.

Run as a subprocess by ``tests/unit/test_tk_backend.py``: each named step opens
a real Tk window with a real GL context, does the one thing, prints what came of
it and stops.  A subprocess per step because a Tk application is a process with
one interpreter in it, and because the steps that quit really do quit.

Usage:  _tk_backend_drive.py <step> [<step> ...]
"""
import os
import sys

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'tk')
os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'

import tkinter                                              # noqa: E402

from OpenGL.GL import (                                     # noqa: E402
    GL_COLOR_BUFFER_BIT, GL_CONTEXT_CORE_PROFILE_BIT, GL_CONTEXT_PROFILE_MASK,
    GL_DEPTH_BUFFER_BIT, GL_RGB, GL_UNSIGNED_BYTE, GL_VIEWPORT, glClear,
    glClearColor, glDeleteLists, glGenLists, glGetIntegerv, glReadPixels,
)
from OpenGL.error import GLError                            # noqa: E402
from OpenGLContext import contextresources                  # noqa: E402
from OpenGLContext.tkinteractivecontext import (            # noqa: E402
    TkInteractiveContext,
)


def say(name, value):
    print('%s %s' % (name, value), flush=True)


#: The clear colour, as the bytes it must come back as.  Whole steps of 1/255
#: so the answer is the same on every driver: a component landing halfway
#: between two bytes -- 0.5 is 127.5 -- may round either way, and both are
#: conformant.
COLOUR = (64, 128, 192)


class Driven(TkInteractiveContext):
    """A context that clears to a known colour and nothing else"""

    captured = None

    def OnInit(self):
        pass

    def Render(self, mode=None):
        glClearColor(*[component / 255 for component in COLOUR], 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    def presentFrame(self):
        """Read the middle of the frame, then put it up.

        This is the one moment the frame is both complete and still there: a
        swap recycles the back buffer, so a read afterwards returns whatever
        the driver handed back rather than what was drawn.
        """
        width, height = self.getViewPort()
        read = glReadPixels(width // 2, height // 2, 1, 1, GL_RGB,
                            GL_UNSIGNED_BYTE)
        self.captured = ' '.join(str(value) for value in bytes(read))
        return super().presentFrame()

    def pixel(self):
        """The colour in the middle of the frame that was drawn last"""
        return self.captured


def built(**named):
    """A context with its first frame drawn"""
    named.setdefault('size', (200, 150))
    context = Driven(**named)
    context.OnDraw(force=1)
    return context


# -- the steps --------------------------------------------------------------
def render():
    context = built()
    say('DRAWN', True)
    context.setCurrent()
    say('PIXEL', context.pixel())


def profile():
    context = built(profile='core', version=(3, 3))
    context.setCurrent()
    mask = int(glGetIntegerv(GL_CONTEXT_PROFILE_MASK))
    say('CORE', bool(mask & GL_CONTEXT_CORE_PROFILE_BIT))


def compatibility():
    """Whether the old pipeline is there to use.

    Asked for compatibility without naming a version, the widget creates the
    context without a profile attribute at all: a profile is a GL 3.2 idea, and
    naming one with no version asks for 1.0, where a driver ignores it.  Such a
    context reports ``GL_CONTEXT_PROFILE_MASK`` as zero and carries the old
    pipeline in full, so the mask is not the question -- the pipeline is, and a
    display list is the part of it a core profile most plainly lacks.
    """
    context = built(profile='compatibility')
    context.setCurrent()
    try:
        lists = glGenLists(1)
    except GLError:
        say('COMPATIBILITY', False)
    else:
        say('COMPATIBILITY', bool(lists))
        glDeleteLists(lists, 1)


def resize():
    context = built()
    context.root.geometry('240x180')
    context.root.update()
    context.OnDraw(force=1)
    context.setCurrent()
    say('VIEWPORT', ' '.join(
        str(int(value)) for value in glGetIntegerv(GL_VIEWPORT)[2:]))


def hidden():
    os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
    context = built()
    say('MAPPED', bool(context.root.winfo_ismapped()))
    context.OnDraw(force=1)
    context.setCurrent()
    say('PIXEL', context.pixel())


def capture():
    context = built()
    say('CAPTURED', bool(context.setPointerCapture(True)))
    context.setPointerCapture(False)


def fullscreen():
    """Whether the request is made and answered

    Whether the window *ends up* filling the screen is the window manager's to
    decide, and a bare X server has none -- so what is checked here is that the
    context asks, both ways, and says it did.
    """
    context = built()
    say('ASKEDFULL', bool(context.setFullscreen(True)))
    context.root.update()
    say('REPORTED', bool(context.isFullscreen()))
    say('ASKEDBACK', bool(context.setFullscreen(False)))
    context.root.update()
    say('BACK', not context.isFullscreen())


def quit():
    told = []
    real = contextresources.context_lost
    contextresources.context_lost = lambda: (told.append(1), real())[1]
    context = built()
    context.releaseWindow()
    say('RELEASED', bool(told))


def embedded():
    """A view inside somebody else's window, which is the reason for Tk"""
    root = tkinter.Tk()
    root.geometry('300x200')
    controls = tkinter.Frame(root, width=80)
    controls.pack(side='left', fill='y')
    tkinter.Label(controls, text='controls').pack()
    holder = tkinter.Frame(root)
    holder.pack(side='right', fill='both', expand=True)
    context = Driven(parent=holder, size=(200, 150))
    say('PARENTED', context.root is None and context.frame.master is holder)
    context.OnDraw(force=1)
    say('DRAWN', True)
    context.releaseWindow()
    root.destroy()


STEPS = {
    'render': render,
    'profile': profile,
    'compatibility': compatibility,
    'resize': resize,
    'hidden': hidden,
    'capture': capture,
    'fullscreen': fullscreen,
    'quit': quit,
    'embedded': embedded,
}


if __name__ == '__main__':
    for name in sys.argv[1:]:
        STEPS[name]()
    say('DONE', '')
