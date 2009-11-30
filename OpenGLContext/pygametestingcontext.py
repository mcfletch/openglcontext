"""Testing context for PyGame API, providing default context class and main loop

You normally use this module via the testingcontext module.
"""
from OpenGLContext import pygameinteractivecontext

def main( TestContext, *args, **named ):
    TestContext.ContextMainLoop( *args, **named )

BaseContext = pygameinteractivecontext.PygameInteractiveContext