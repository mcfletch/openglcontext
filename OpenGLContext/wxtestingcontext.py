"""Testing context for the wxPython API, providing default context class and main loop

You normally use this module via the testingcontext module.
"""
from typing import Any

from OpenGLContext import wxinteractivecontext
def main( TestContext: Any, *args: Any, **named: Any ) -> Any:
    return TestContext.ContextMainLoop( *args, **named )

BaseContext = wxinteractivecontext.wxInteractiveContext