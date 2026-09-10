"""Testing context for the Tk API, providing the context class and main loop

You normally use this module via the testingcontext module.
"""

from typing import Any

from OpenGLContext import tkinteractivecontext


def main(TestContext: Any, *args: Any, **named: Any) -> Any:
    return TestContext.ContextMainLoop(*args, **named)


BaseContext = tkinteractivecontext.TkInteractiveContext
