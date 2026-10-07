"""X3D's and VRML97's TimeSensor, polled on the engine's clock

The behaviour is pyvrml97's (:mod:`vrml.x3d.timesensor`). Bound to a context,
the sensor is one of the generators the context's time manager polls on each
pass of the event cascade with :func:`~OpenGLContext.events.systemtime.systemTime`,
which a capture steps a frame at a time; a poll that sends events asks the
context for a frame.
"""
from vrml.x3d import timesensor

from OpenGLContext.scenegraph.x3druntime import EngineTimed, Polled


class TimeSensor(Polled, EngineTimed, timesensor.TimeSensor):
    """TimeSensor polled by each context it is bound to

    `pause()` and `resume()` take effect at the engine's time.

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/time.html#TimeSensor
    """
