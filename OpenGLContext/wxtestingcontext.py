"""Testing context for the wxPython API, providing default context class and main loop

You normally use this module via the testingcontext module.
"""
from OpenGLContext import wxinteractivecontext
def main( TestContext, *args, **named ):
    return TestContext.ContextMainLoop( *args, **named )

BaseContext = wxinteractivecontext.wxInteractiveContext