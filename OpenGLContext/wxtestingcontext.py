"""Testing context for the wx window system: the context class and main loop

You normally use this module via the testingcontext module.
"""
from typing import Any

from OpenGLContext.wxcontext import wxContext

BaseContext = wxContext


def main(TestContext: Any, *args: Any, **named: Any) -> Any:
    """Run ``TestContext``'s main loop"""
    return TestContext.ContextMainLoop(*args, **named)
