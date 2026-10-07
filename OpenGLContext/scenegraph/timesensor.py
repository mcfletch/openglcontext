"""X3D's and VRML97's TimeSensor, polled on the engine's clock

The behaviour is pyvrml97's (:mod:`vrml.x3d.timesensor`). Bound to a context,
the sensor is one of the generators the context's time manager polls on each
pass of the event cascade with :func:`~OpenGLContext.events.systemtime.systemTime`,
which a capture steps a frame at a time; a poll that sends events asks the
context for a frame.

:meth:`TimeSensor.getTimer` answers a :class:`SensorTimer`, the
:class:`~OpenGLContext.events.timer.Timer`-style handle on the sensor: pause
and resume, start and stop, the speed as ``internal.multiplier`` (the sensor's
``rate``), and handlers for its fractions and cycles.
"""
from collections.abc import Callable
from typing import Any

from pydispatch import dispatcher
from vrml import protofunctions
from vrml.x3d import timesensor

from OpenGLContext.events import systemtime
from OpenGLContext.scenegraph.x3druntime import EngineTimed, Polled

__all__ = ['SensorTimer', 'TimeEvent', 'TimeSensor']


class TimeEvent:
    """What a SensorTimer's handler is called with: the fraction and the time"""

    def __init__(self, fraction: float, value: float) -> None:
        self._fraction = fraction
        self._value = value

    def fraction(self) -> float:
        """The part of the cycle gone by"""
        return self._fraction

    def value(self) -> float:
        """The engine's time of the event, in seconds"""
        return self._value


class SensorTimer:
    """A Timer-style handle on a TimeSensor

    ``internal`` is the handle itself, so ``timer.internal.multiplier`` sets
    the speed as it does on a Timer.
    """

    def __init__(self, sensor: 'TimeSensor') -> None:
        self.sensor = sensor
        self._handlers: list[Callable[..., Any]] = []

    @property
    def internal(self) -> 'SensorTimer':
        return self

    @property
    def active(self) -> bool:
        """Whether the sensor is running and not paused"""
        return self.sensor.running() and not self.sensor.paused()

    @property
    def multiplier(self) -> float:
        """How fast the sensor's cycles run against the clock"""
        return float(self.sensor.rate)

    @multiplier.setter
    def multiplier(self, value: float) -> None:
        self.sensor.rate = float(value)

    def pause(self) -> None:
        """Pause the sensor now"""
        self.sensor.pause()

    def resume(self) -> None:
        """Resume the sensor now"""
        self.sensor.resume()

    def set_active(self, value: Any) -> None:
        """Resume where `value` is true, pause otherwise"""
        if value:
            self.resume()
        else:
            self.pause()

    def start(self) -> None:
        """Start the sensor now"""
        self.sensor.startTime = systemtime.systemTime()

    def stop(self) -> None:
        """Stop the sensor now"""
        self.sensor.stopTime = systemtime.systemTime()

    def addEventHandler(self, timetype: str = 'fraction',
                        function: Callable[[TimeEvent], Any] | None = None) -> None:
        """Call `function` with a :class:`TimeEvent` at each fraction or each new cycle

        `timetype` is ``fraction`` or ``cycle``.
        """
        if function is None:
            return
        sensor = self.sensor
        name = {'fraction': 'fraction_changed', 'cycle': 'cycleTime'}[timetype]

        def deliver(value: Any) -> None:
            fraction = sensor.__dict__.get('fraction_changed', 0.0)
            # fraction_changed is sent ahead of time, so the clock is asked.
            when = value if timetype == 'cycle' else sensor.now()
            function(TimeEvent(float(fraction), float(when)))

        # Held here, since the dispatcher holds its receivers weakly.
        self._handlers.append(deliver)
        dispatcher.connect(deliver, signal=('set', protofunctions.getField(sensor, name)),
                           sender=sensor)


class TimeSensor(Polled, EngineTimed, timesensor.TimeSensor):
    """TimeSensor polled by each context it is bound to

    `pause()` and `resume()` take effect at the engine's time.

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/time.html#TimeSensor
    """

    def getTimer(self, context: Any = None) -> SensorTimer:
        """The Timer-style handle on this sensor; one for every context"""
        found: SensorTimer | None = self.__dict__.get('_timer')
        if found is None:
            found = self.__dict__['_timer'] = SensorTimer(self)
        return found
