"""Testing context for the GLUT window system: the context class and main loop

You normally use this module via the testingcontext module.
"""
from typing import Any

from OpenGLContext.glutcontext import GLUTContext

BaseContext = GLUTContext


def main(TestContext: Any, *args: Any, **named: Any) -> Any:
    """Run ``TestContext``'s main loop"""
    return TestContext.ContextMainLoop(*args, **named)
