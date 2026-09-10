"""Testing context for PyGame API, providing default context class and main loop

You normally use this module via the testingcontext module.
"""
from typing import Any

from OpenGLContext import pygameinteractivecontext

def main( TestContext: Any, *args: Any, **named: Any ) -> Any:
    return TestContext.ContextMainLoop( *args, **named )

BaseContext = pygameinteractivecontext.PygameInteractiveContext