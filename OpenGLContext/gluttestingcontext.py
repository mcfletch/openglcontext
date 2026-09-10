"""Testing context for GLUT API, providing default context class and main loop

You normally use this module via the testingcontext module.
"""

from typing import Any

from OpenGLContext import glutinteractivecontext
def main( TestContext: Any, *args: Any, **named: Any ) -> Any:
    """Mainloop for the GLUT testing context"""
    return TestContext.ContextMainLoop( *args, **named )

BaseContext = glutinteractivecontext.GLUTInteractiveContext