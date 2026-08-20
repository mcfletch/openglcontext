"""Putting a context inside a medium: the fog it binds and the mix it has.

Driven with a recording context, because what is asserted is what submersion
*asks for* -- a fog range, a muffle -- and neither needs a window or a sound
card.
"""
import pytest

from OpenGLContext.scenegraph.fog import Fog
from OpenGLContext.scenegraph.water.medium import LAVA, MEDIA, SLIME, WATER
from OpenGLContext.scenegraph.water.submersion import apply, muffle_for, submerge
from OpenGLContext.scenegraph.water.volumes import Volume, Volumes


class Engine:
    muffle = 0.0


class Context:
    """As much of a context as submersion asks anything of."""

    def __init__(self, fog=None):
        self.fog = fog


def _with_engine(context):
    """Give a context an audio engine the way the audio scene records one.

    Through the real registry rather than a stub, so what is exercised is the
    look-up submersion actually does -- including its refusal to open a device
    that is not already there.
    """
    from OpenGLContext.audio import scene as audioscene
    engine = Engine()
    audioscene._engines[context] = engine
    return engine


def _volumes():
    return Volumes([
        Volume(minimum=(-10.0, -5.0, -10.0), maximum=(10.0, 0.0, 10.0),
               medium=WATER),
        Volume(minimum=(20.0, -8.0, -10.0), maximum=(40.0, -2.0, 10.0),
               medium=LAVA),
    ])


class TestTheFog:
    def test_a_medium_closes_the_view_in(self) -> None:
        fog = Fog(visibilityRange=0.0)
        apply(fog, WATER)
        assert fog.visibilityRange == MEDIA[WATER].visibility

    def test_it_closes_to_the_medium_s_own_colour(self) -> None:
        fog = Fog()
        apply(fog, SLIME)
        assert tuple(fog.color) == pytest.approx(MEDIA[SLIME].color)

    def test_dry_air_switches_it_off(self) -> None:
        """Range zero is the specification's own way of saying no fog."""
        fog = Fog()
        apply(fog, WATER)
        apply(fog, '')
        assert fog.visibilityRange == 0.0

    def test_it_closes_in_rather_than_cutting_off(self) -> None:
        """Exponential: clear close up, then closing. A linear fog puts a wall
        at a distance, and water has no wall in it."""
        fog = Fog()
        apply(fog, WATER)
        assert str(fog.fogType) == 'EXPONENTIAL'

    def test_a_medium_nobody_declared_still_fogs(self) -> None:
        fog = Fog()
        apply(fog, 'quicksilver')
        assert fog.visibilityRange > 0.0


class TestTheMix:
    def test_a_medium_muffles(self) -> None:
        assert muffle_for(WATER) == MEDIA[WATER].muffle

    def test_dry_air_does_not(self) -> None:
        assert muffle_for('') == 0.0

    def test_thicker_media_muffle_more(self) -> None:
        assert muffle_for(LAVA) > muffle_for(WATER)


class TestPuttingAContextIn:
    def test_it_reports_what_the_point_is_in(self) -> None:
        context = Context(fog=Fog())
        _with_engine(context)
        assert submerge(context, _volumes(), (0.0, -1.0, 0.0)) == WATER

    def test_the_fog_follows_the_point(self) -> None:
        context = Context(fog=Fog())
        _with_engine(context)
        submerge(context, _volumes(), (0.0, -1.0, 0.0))
        assert context.fog.visibilityRange == MEDIA[WATER].visibility
        submerge(context, _volumes(), (0.0, 5.0, 0.0))
        assert context.fog.visibilityRange == 0.0

    def test_the_mix_follows_it_too(self) -> None:
        context = Context(fog=Fog())
        engine = _with_engine(context)
        submerge(context, _volumes(), (30.0, -4.0, 0.0))
        assert engine.muffle == MEDIA[LAVA].muffle

    def test_coming_out_clears_the_mix(self) -> None:
        context = Context(fog=Fog())
        engine = _with_engine(context)
        submerge(context, _volumes(), (0.0, -1.0, 0.0))
        submerge(context, _volumes(), (0.0, 90.0, 0.0))
        assert engine.muffle == 0.0

    def test_a_context_with_no_fog_is_not_a_failure(self) -> None:
        """A viewer between worlds has no volumes and a machine with no sound
        has no engine; neither is a reason for a frame to fail."""
        assert submerge(Context(), _volumes(), (0.0, -1.0, 0.0)) == WATER

    def test_a_context_with_no_engine_is_not_a_failure(self) -> None:
        """Muffling a silence must not be the thing that opens a device."""
        assert submerge(Context(fog=Fog()), _volumes(), (0.0, -1.0, 0.0)) == WATER

    def test_no_volumes_at_all_is_dry(self) -> None:
        context = Context(fog=Fog())
        _with_engine(context)
        assert submerge(context, None, (0.0, -1.0, 0.0)) == ''
        assert context.fog.visibilityRange == 0.0
