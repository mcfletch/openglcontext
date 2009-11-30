"""Testing context for GLUT API, providing default context class and main loop

You normally use this module via the testingcontext module.
"""

from OpenGLContext import glutinteractivecontext
def main( TestContext, *args, **named ):
    """Mainloop for the GLUT testing context"""
    return TestContext.ContextMainLoop( *args, **named )

BaseContext = glutinteractivecontext.GLUTInteractiveContext