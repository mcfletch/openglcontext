"""Testing context for the wxPython API, providing default context class and main loop

You normally use this module via the testingcontext module.
"""
from OpenGLContext import tkinteractivecontext
from OpenGL.Tk import *

def main( TestContext, *args, **named ):
	return TestContext.ContextMainLoop( *args, **named )
BaseContext = tkinteractivecontext.TkInteractiveContext
