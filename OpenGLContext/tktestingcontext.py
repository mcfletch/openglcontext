"""Testing context for the Tk API, providing the context class and main loop

You normally use this module via the testingcontext module.
"""

from OpenGLContext import tkinteractivecontext


def main(TestContext, *args, **named):
    return TestContext.ContextMainLoop(*args, **named)


BaseContext = tkinteractivecontext.TkInteractiveContext
