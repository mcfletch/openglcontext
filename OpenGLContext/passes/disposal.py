"""Giving a render pass's GL objects back while its context is current.

A pass allocates textures, framebuffers, buffers, queries and programs as it
first needs them, and keeps them for its life. None of the classes holding
them has a finalizer, so the garbage collector never issues a GL call from
whatever thread and context happen to be current when it runs. Releasing them
is therefore an explicit act, made with the pass's own context current:
:func:`OpenGLContext.passes.renderpass.cached_pass` does it for a pass a new
scenegraph replaces, and the context-loss callback in the same module does it
as the context is destroyed.

Each class that owns GL objects on the pass -- the pass itself and each of the
mixins it is built from -- overrides :meth:`PassResources.disposeResources`,
releases its own objects, and calls ``super().disposeResources()``, so one call
on the pass reaches every owner in its method resolution order. A mixin joins
the chain by deriving from :class:`PassResources` and doing the same.

What is released is made again by the next frame that needs it, so a pass that
has been disposed of can still draw.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

__all__ = ('PassResources', 'let_go')


class PassResources:
    """The end of a pass's chain of GL-object owners.

    Holds nothing itself; its :meth:`disposeResources` is what the last
    ``super()`` call in the chain reaches.
    """

    def disposeResources(self) -> None:
        """Release every GL object this pass holds, with its context current.

        Idempotent. A failure to delete one object is logged and the rest are
        still released.
        """


def let_go(owner: Any, attribute: str, method: str = 'release') -> None:
    """Call ``method`` on what ``owner.attribute`` holds, and stop holding it.

    The attribute is cleared before the call, so an object whose release
    raises part-way is not kept to be released a second time; the failure is
    logged at debug level with its traceback, since at teardown nothing can
    act on it.
    """
    held = getattr(owner, attribute, None)
    if held is None:
        return
    setattr(owner, attribute, None)
    try:
        getattr(held, method)()
    except Exception:
        log.debug('releasing %s.%s failed', type(owner).__name__, attribute,
                  exc_info=True)
