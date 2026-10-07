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
