"""Testing context for the Pygame window system: the context class and main loop

You normally use this module via the testingcontext module.
"""
from typing import Any

from OpenGLContext.pygamecontext import PygameContext

BaseContext = PygameContext


def main(TestContext: Any, *args: Any, **named: Any) -> Any:
    """Run ``TestContext``'s main loop"""
    return TestContext.ContextMainLoop(*args, **named)
