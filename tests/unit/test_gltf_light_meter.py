"""What exposure a scene lit in absolute units is read at.

``KHR_lights_punctual`` states intensities physically -- candela for a point or
a spot, lux for a directional -- so a room lit the way a room is actually lit
arrives with numbers in the hundreds and clips to white at neutral exposure.
The loader meters the scene and stops it down, which is the job a camera's
light meter does.

What a meter has to get right is that **light adds up**. Illuminance at a point
is the sum of what every lamp delivers there, so a hall with twenty lamps down
it is brighter than the same hall with one, and a meter that reports the
strongest single lamp reports the same number for both.
"""

import numpy as np
import pytest

from OpenGLContext.loaders.gltf.scene import _meter_exposure


class Lamp:
    """Enough of a punctual light for the meter: it reads one field."""

    def __init__(self, intensity):
        self.intensity = intensity


def point(intensity, position):
    return (Lamp(intensity), np.asarray(position, dtype='d'))


def directional(intensity):
    """A directional light delivers its illuminance everywhere, so no place."""
    return (Lamp(intensity), None)


CENTRE = (0.0, 0.0, 0.0)


class TestASceneThatNeedsNoStoppingDown:
    def test_no_lights_at_all_is_neutral(self):
        assert _meter_exposure([], CENTRE) == 1.0

    def test_a_normalised_test_scene_is_neutral(self):
        """Intensity around one is how the conformance models are lit."""
        assert _meter_exposure([point(1.0, (0, 2, 0))], CENTRE) == 1.0

    def test_a_modestly_lit_rig_is_neutral(self):
        """A few lux together still reads right without stopping down."""
        lamps = [point(2.0, (0, 1, 0)), point(2.0, (0, -1, 0))]

        assert _meter_exposure(lamps, CENTRE) == 1.0

    def test_it_never_brightens(self):
        assert _meter_exposure([point(0.01, (0, 5, 0))], CENTRE) == 1.0


class TestLightAddsUp:
    def test_two_lamps_stop_down_further_than_one(self):
        one = _meter_exposure([point(600.0, (0, 3, 0))], CENTRE)
        two = _meter_exposure([point(600.0, (0, 3, 0)),
                               point(600.0, (0, 3, 1))], CENTRE)

        assert two < one

    def test_a_hall_of_lamps_is_metered_as_a_hall(self):
        """Twenty lamps down a hall, which is what a lit room has in it.

        Metering the strongest one alone reads the hall as though the other
        nineteen were switched off, and the render comes out that much over.
        """
        one = [point(650.0, (2.5, 1.75, 0.0))]
        hall = one + [point(650.0, (2.5, 1.75, offset))
                      for offset in range(1, 20)]

        assert _meter_exposure(hall, CENTRE) < _meter_exposure(one, CENTRE) / 2

    def test_a_directional_adds_to_a_point(self):
        both = _meter_exposure([directional(40.0), point(600.0, (0, 3, 0))],
                               CENTRE)
        alone = _meter_exposure([point(600.0, (0, 3, 0))], CENTRE)

        assert both < alone

    def test_the_sum_is_what_sets_the_exposure(self):
        """Two lamps at the same place are one lamp of twice the intensity."""
        pair = _meter_exposure([point(300.0, (0, 3, 0)),
                                point(300.0, (0, 3, 0))], CENTRE)
        single = _meter_exposure([point(600.0, (0, 3, 0))], CENTRE)

        assert pair == pytest.approx(single)


class TestHowFarAwayALampIs:
    def test_a_distant_lamp_counts_for_less(self):
        near = _meter_exposure([point(600.0, (0, 2, 0))], CENTRE)
        far = _meter_exposure([point(600.0, (0, 20, 0))], CENTRE)

        assert far > near

    def test_a_lamp_at_the_centre_does_not_divide_by_nothing(self):
        assert 0.0 < _meter_exposure([point(600.0, CENTRE)], CENTRE) <= 1.0
