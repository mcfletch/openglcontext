'''Mix-in providing event registration and management'''
from OpenGLContext import context
from OpenGLContext.events import eventhandlermixin, keyboardevents, mouseevents, timeeventgeneratormanager

class InteractiveContext( eventhandlermixin.EventHandlerMixin):
    """Context mix-in providing event-handling managers

    Supports:
        keyboard, keypress -- provided by the keyboardevents module
        mousebutton, mousemove -- provided by the mouseevents module
        timers -- provided by the timeeventgeneratormanager module

    Attributes:
        EventManagerClasses -- list of standard event-managers to be
            initialised for the context
        TimeManagerClass -- class for use in supporting the Timer
            functionality
    """
    EventManagerClasses = [
        ('keyboard', keyboardevents.KeyboardEventManager ),
        ('keypress', keyboardevents.KeypressEventManager ),
        ('mousebutton', mouseevents.MouseButtonEventManager ),
        ('mousemove', mouseevents.MouseMoveEventManager ),
        ('mousein', mouseevents.MouseInEventManager),
        ('mouseout', mouseevents.MouseOutEventManager),
    ]
    TimeManagerClass = timeeventgeneratormanager.TimeEventGeneratorManager

    