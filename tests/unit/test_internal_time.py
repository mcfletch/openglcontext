"""What an :class:`~OpenGLContext.events.internaltime.InternalTime` does with
the arguments it is given.

A duration of zero has no cycle to be a fraction of, so it is refused -- and the
refusal has to say so, because a duration usually arrives from a scene file
(``TimeSensor.cycleInterval``) rather than from the line that raises.
"""

import pytest

from OpenGLContext.events.internaltime import InternalTime


class TestADurationOfZeroIsRefused:
    def test_it_raises_value_error(self):
        with pytest.raises(ValueError):
            InternalTime(duration=0)

    def test_the_message_names_the_duration(self):
        with pytest.raises(ValueError) as raised:
            InternalTime(duration=0)
        assert '0' in str(raised.value)


class TestAnOrdinaryDurationIsAccepted:
    def test_the_fraction_starts_at_zero(self):
        assert InternalTime(duration=2.0).getFraction() == 0.0

    def test_polling_advances_the_fraction(self):
        timer = InternalTime(duration=2.0)
        timer.start(0.0)
        timer.poll(1.0)
        assert timer.getFraction() == pytest.approx(0.5)
