"""Stride measured from a clip: how fast a body is carried when it plays."""
import numpy as np
import pytest

import pygltflib

from OpenGLContext.character import CharacterModel
from OpenGLContext.character.gaitmeasure import (
    Stride, _fill_gaps, measure, measure_stride)

from ._locomotion_assets import PLANTED, marching, striding, walker_glb, waving


def _model(**clips):
    return CharacterModel.load(walker_glb(clips))


class TestSpeed:
    def test_a_planted_foot_sliding_back_is_the_speed_of_the_body(self):
        model = _model(walk=striding(duration=1.0))
        assert measure_stride(model, 'walk') == pytest.approx(1.0 / PLANTED, rel=0.02)

    def test_a_shorter_cycle_is_a_faster_body(self):
        model = _model(run=striding(duration=0.5))
        assert measure_stride(model, 'run') == pytest.approx(2.0 / PLANTED, rel=0.02)

    def test_root_motion_reports_the_travel_of_the_hips(self):
        model = _model(roll=striding(duration=2.0, hips_travel=5.0))
        found = measure(model, 'roll')
        assert found.root_motion
        assert found.speed == pytest.approx(2.5, rel=0.02)

    def test_a_clip_that_plants_no_foot_carries_nothing(self):
        model = _model(wave=waving(1.0))
        found = measure(model, 'wave')
        assert found.speed == 0.0
        assert not found.root_motion
        assert found.contacts == ()

    def test_feet_lifting_in_place_carry_nothing(self):
        model = _model(march=marching(1.0))
        assert measure_stride(model, 'march') == 0.0

    def test_the_model_is_left_animatable(self):
        model = _model(walk=striding(), wave=waving(1.0))
        measure_stride(model, 'walk')
        model.play('wave')
        model.update(0.5)
        assert model.mixer.playing == ('wave',)


class TestContacts:
    def test_each_foot_lands_once_a_cycle_half_a_cycle_apart(self):
        model = _model(walk=striding(duration=1.0))
        found = measure(model, 'walk')
        assert [foot for foot, _ in found.contacts] == ['left', 'right']
        times = dict(found.contacts)
        assert times['left'] == pytest.approx(0.0, abs=0.04)
        assert times['right'] == pytest.approx(0.5, abs=0.04)

    def test_contact_times_scale_with_the_clip(self):
        model = _model(walk=striding(duration=2.0))
        times = dict(measure(model, 'walk').contacts)
        assert times['right'] == pytest.approx(1.0, abs=0.08)


class TestReport:
    def test_the_measurement_names_the_clip_and_its_length(self):
        model = _model(walk=striding(duration=1.25))
        found = measure(model, 'walk')
        assert isinstance(found, Stride)
        assert (found.clip, found.duration) == ('walk', pytest.approx(1.25))

    def test_a_model_with_no_skeleton_cannot_be_measured(self):
        model = _model(walk=striding())
        model.humanoid = None
        with pytest.raises(ValueError, match='humanoid'):
            measure(model, 'walk')

    def test_an_unknown_clip_is_a_key_error(self):
        with pytest.raises(KeyError):
            measure(_model(walk=striding()), 'run')

    def test_a_model_without_feet_cannot_be_measured(self):
        model = _model(walk=striding())
        del model.humanoid.bones['leftFoot']
        del model.humanoid.bones['rightFoot']
        with pytest.raises(ValueError, match='feet'):
            measure(model, 'walk')


class TestFragmentedPlanting:
    """Sampling noise can split one planting in two; a foot lands once."""

    @staticmethod
    def _filled(text, longest=3):
        planted = np.array([c == '#' for c in text])
        return ''.join('#' if v else '.' for v in _fill_gaps(planted, longest))

    def test_a_short_gap_between_two_plantings_is_closed(self):
        assert self._filled('..##..#####....') == '..#########....'

    def test_a_gap_across_the_end_of_the_cycle_is_closed(self):
        assert self._filled('.##....##.') == '###....###'

    def test_a_long_gap_is_a_swing(self):
        assert self._filled('##.....##', longest=3) == '##.....##'

    def test_no_plantings_stay_none(self):
        assert self._filled('.....') == '.....'
