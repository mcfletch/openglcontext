"""A sheet is meshed finely enough to carry its own swell
(:func:`OpenGLContext.scenegraph.water.surface.mesh_across`).

The density comes from the wavelength rather than from a count chosen once,
because a fixed count cannot be right for both a pond and a lake the size of a
valley: the lake samples its own ripple every few hundred metres, the wave
aliases away, and what is left is a flat plate.

How many samples a wavelength gets decides how much of the wave survives.  Two
is the Nyquist limit -- enough to represent a sine in principle, and in practice
whether the mesh lands on the crests or on the zero crossings is down to where
the sheet happens to start.  These cases measure what actually survives, against
the field sampled finely enough to be the answer.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.water.surface import (
    CHOPPY,
    FLOWING,
    MESH_LIMIT,
    STILL,
    mesh_across,
    wave_height,
)

#: Least of the true wave height a mesh must carry, as a fraction.  Short of
#: this the swell the mesh is there to hold is visibly flattened.
CARRIED = 0.85


def _span(style, side, across, when=2.0):
    """The height range a mesh of ``across`` vertices actually captures."""
    line = np.linspace(-side / 2.0, side / 2.0, across)
    x, z = np.meshgrid(line, line)
    height = wave_height(style, x, z, when)
    return float(height.max() - height.min())


def _carried(style, side):
    """What fraction of the true span the chosen mesh keeps."""
    true = _span(style, side, 600)
    if true <= 0.0:
        return 1.0
    return _span(style, side, mesh_across(side, style)) / true


class TestTheMeshCarriesTheSwell:
    @pytest.mark.parametrize('style', [FLOWING, CHOPPY])
    @pytest.mark.parametrize('side', [12.0, 40.0, 120.0, 400.0])
    def test_enough_of_the_wave_survives(self, style, side):
        kept = _carried(style, side)
        assert kept >= CARRIED, (
            '%s over %g m keeps only %.0f%% of its wave at %d vertices across'
            % (style.name, side, 100 * kept, mesh_across(side, style)))

    def test_a_small_sheet_is_not_meshed_coarser_than_the_old_default(self):
        """The nine-across default was not wrong everywhere -- only on big sheets.

        A pool a few metres across was already carried by it, so a density
        rule that returns fewer vertices there is a regression dressed as a
        fix.
        """
        for side in (8.0, 12.0, 20.0):
            assert mesh_across(side, CHOPPY) >= 9, (
                '%g m sheet meshed at %d across' % (side, mesh_across(side, CHOPPY)))


class TestTheBudgetHolds:
    def test_a_huge_sheet_stops_at_the_limit(self):
        assert mesh_across(100000.0, CHOPPY) == MESH_LIMIT

    def test_still_water_needs_no_swell_carried(self):
        """Still water has no displacement, so any density carries all of it."""
        assert _carried(STILL, 400.0) == 1.0

    def test_it_never_returns_a_degenerate_mesh(self):
        for side in (0.0, 0.01, 1.0):
            assert mesh_across(side, CHOPPY) >= 2
