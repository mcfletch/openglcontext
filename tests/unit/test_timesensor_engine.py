"""The engine's TimeSensor: X3D's (``vrml.x3d.timesensor``), polled on the engine's clock.

Bound to a context, the sensor is one of the generators the context's time
manager polls on each pass of the event cascade, with
``systemtime.systemTime()``; a poll that sends events asks for a frame.
"""
import gc

import pytest
from vrml.x3d import timesensor

from OpenGLContext.events import systemtime
from OpenGLContext.events.timeeventgeneratormanager import TimeEventGeneratorManager
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph.timesensor import TimeSensor


def test_it_is_x3ds():
    assert issubclass(TimeSensor, timesensor.TimeSensor)
    assert prototypes()['TimeSensor'] is TimeSensor


class Timing:
    def __init__(self):
        self.manager = TimeEventGeneratorManager()

    def getTimeManager(self):
        return self.manager


def test_a_bound_sensor_runs_on_the_engines_clock(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
    sensor = TimeSensor(cycleInterval=4.0, loop=True)
    context = Timing()
    sensor.bind(context)
    sensor.bind(context)
    assert context.manager(context) == 1
    assert sensor.fraction_changed == pytest.approx(0.5)
    now[0] = 11.0
    context.manager(context)
    assert sensor.fraction_changed == pytest.approx(0.75)


def test_a_sensor_that_is_not_running_asks_for_no_frame(monkeypatch):
    monkeypatch.setattr(systemtime, 'systemTime', lambda: 100.0)
    sensor = TimeSensor(cycleInterval=4.0, loop=False)
    context = Timing()
    sensor.bind(context)
    assert context.manager(context) == 0


def test_a_dropped_sensor_stops_being_polled(monkeypatch):
    monkeypatch.setattr(systemtime, 'systemTime', lambda: 1.0)
    context = Timing()
    TimeSensor(cycleInterval=4.0, loop=True).bind(context)
    gc.collect()
    assert context.manager(context) == 0
    assert context.manager.generators() == []


def test_a_documents_sensor_animates_on_a_capture_clock(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    from OpenGLContext.video.clock import FixedStepClock  # noqa: PLC0415 kept with its use
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <TimeSensor DEF="CLOCK" cycleInterval="2" loop="true"/>
      <PositionInterpolator DEF="MOVE" key="0 1" keyValue="0 0 0 4 0 0"/>
      <Transform DEF="T"/>
      <ROUTE fromNode="CLOCK" fromField="fraction_changed" toNode="MOVE" toField="set_fraction"/>
      <ROUTE fromNode="MOVE" fromField="value_changed" toNode="T" toField="set_translation"/>
    </Scene></X3D>''', 'scene.x3d')
    with FixedStepClock(4, start=0.0) as clock, scene_context(scene) as context:
        context.OnDraw(force=1)
        clock.advance(2)
        context.OnDraw(force=1)
        assert tuple(scene.getDEF('T').translation) == pytest.approx((1.0, 0, 0))


class TestGetTimer:
    """``getTimer(context)``: the Timer-style handle on the sensor"""

    def running(self, monkeypatch):
        now = [10.0]
        monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
        sensor = TimeSensor(cycleInterval=4.0, loop=True)
        context = Timing()
        sensor.bind(context)
        return sensor, context, now

    def test_pause_and_resume(self, monkeypatch):
        sensor, context, now = self.running(monkeypatch)
        timer = sensor.getTimer(context)
        context.manager(context)
        assert timer.active
        timer.pause()
        context.manager(context)
        assert sensor.paused() and not timer.active
        now[0] = 11.0
        timer.resume()
        context.manager(context)
        assert timer.active

    def test_the_multiplier_is_the_sensors_rate(self, monkeypatch):
        sensor, context, _now = self.running(monkeypatch)
        timer = sensor.getTimer(context)
        timer.internal.multiplier = 2.0
        assert sensor.rate == 2.0
        assert timer.internal.multiplier == 2.0

    def test_fraction_and_cycle_handlers(self, monkeypatch):
        sensor, context, now = self.running(monkeypatch)
        timer = sensor.getTimer(context)
        fractions, cycles = [], []
        timer.addEventHandler('fraction', function=lambda event: fractions.append(
            (event.fraction(), event.value())))
        timer.addEventHandler('cycle', function=lambda event: cycles.append(event.value()))
        context.manager(context)
        assert fractions == [(pytest.approx(0.5), 10.0)]
        assert cycles == [10.0]

    def test_one_handle_per_sensor(self, monkeypatch):
        sensor, context, _now = self.running(monkeypatch)
        assert sensor.getTimer(context) is sensor.getTimer(Timing())
