"""The event-handling mix-in under the name it is also published as

Every :class:`~OpenGLContext.context.Context` has the keyboard, mouse and
timer event managers :class:`InteractiveContext` names, since
:class:`~OpenGLContext.events.eventhandlermixin.EventHandlerMixin` is one of
its bases; this is that mix-in.
"""
from OpenGLContext.events.eventhandlermixin import EventHandlerMixin

InteractiveContext = EventHandlerMixin

__all__ = ('InteractiveContext',)
