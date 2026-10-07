"""X3D's and VRML97's TimeSensor, polled on the engine's clock

The behaviour is pyvrml97's (:mod:`vrml.x3d.timesensor`). Bound to a context,
the sensor is one of the generators the context's time manager polls on each
pass of the event cascade with :func:`~OpenGLContext.events.systemtime.systemTime`,
which a capture steps a frame at a time; a poll that sends events asks the
context for a frame.
"""
from typing import Any

import weakref

from vrml.x3d import timesensor

from OpenGLContext.scenegraph.x3druntime import EngineTimed


class Polling:
    """A sensor as one of a time manager's generators, holding neither"""

    def __init__(self, sensor: Any, manager: Any) -> None:
        self.sensor = weakref.ref(sensor)
        self.manager = weakref.ref(manager)

    def poll(self, realTime: float) -> int:
        """Advance the sensor to `realTime`; how many events it sent (0 or 1)"""
        sensor = self.sensor()
        if sensor is None:
            manager = self.manager()
            if manager is not None:
                manager.removeEventGenerator(self)
            return 0
        return int(sensor.advance(realTime))


class TimeSensor(EngineTimed, timesensor.TimeSensor):
    """TimeSensor polled by each context it is bound to

    `pause()` and `resume()` take effect at the engine's time.

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/time.html#TimeSensor
    """

    def bind(self, context: Any) -> bool:
        """Be polled by `context`'s time manager"""
        manager = context.getTimeManager()
        polled = self.__dict__.setdefault('_polledBy', weakref.WeakSet())
        if manager not in polled:
            polled.add(manager)
            manager.addEventGenerator(Polling(self, manager))
        return True
