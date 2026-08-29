"""Posing many figures together, against posing them one at a time.

Pure Python/numpy -- no GL. A crowd exists only to be faster, so the whole of
what it has to prove is that it is not *different*: every figure ends the frame
in the pose it would have been in had it been updated on its own, whatever it
happens to be doing -- one clip, a cross-fade, a masked layer over another, an
additive layer on top.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.character.crowd import Crowd
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.loaders.gltf import load_gltf, parse_gltf
from tests.unit._character_assets import character_glb


@pytest.fixture(scope='module')
def document():
    return parse_gltf(character_glb())


def _figure(document):
    model = CharacterModel(load_gltf(document=document))
    model.mixer.pose_write = 'all'
    return model


def _pose_of(model):
    """Where every joint of a figure has ended up."""
    return np.concatenate([
        np.asarray([list(x.translation) for x in model.mixer.rig.transforms]),
        np.asarray([list(x.rotation) for x in model.mixer.rig.transforms]),
        np.asarray([list(x.scale) for x in model.mixer.rig.transforms]),
    ], axis=1)


def _skin_of(model):
    return [np.asarray(mesh._skin_matrices)
            for skin in model.mixer.skins for mesh in skin.meshes]


def _both_ways(document, arrange, steps=6, dt=1 / 30.0):
    """One figure updated alone and one in a crowd, told to do the same thing."""
    alone, together = _figure(document), _figure(document)
    crowd = Crowd()
    crowd.add(together)
    for model in (alone, together):
        arrange(model)
    for _ in range(steps):
        alone.update(dt)
        crowd.update(dt)
    return alone, together


class TestOneFigureAgrees:
    def test_a_single_clip(self, document):
        alone, together = _both_ways(document, lambda m: m.play('raise'))

        assert np.allclose(_pose_of(alone), _pose_of(together), atol=1e-9)

    def test_a_cross_fade_in_progress(self, document):
        def arrange(model):
            model.play('raise')
            model.play('kick', fade=1.0)

        alone, together = _both_ways(document, arrange, steps=3)

        assert np.allclose(_pose_of(alone), _pose_of(together), atol=1e-9)

    def test_a_masked_layer_over_the_base(self, document):
        def arrange(model):
            model.play('kick')
            model.layer('upper', mask=model.mask('spine')).play('raise')

        alone, together = _both_ways(document, arrange)

        assert np.allclose(_pose_of(alone), _pose_of(together), atol=1e-9)

    def test_a_layer_at_part_weight(self, document):
        def arrange(model):
            model.play('kick')
            model.layer('half', weight=0.4).play('raise')

        alone, together = _both_ways(document, arrange)

        assert np.allclose(_pose_of(alone), _pose_of(together), atol=1e-9)

    def test_an_additive_layer(self, document):
        def arrange(model):
            model.play('kick')
            model.layer('recoil', additive=True).play('raise')

        alone, together = _both_ways(document, arrange)

        assert np.allclose(_pose_of(alone), _pose_of(together), atol=1e-9)

    def test_the_joint_matrices_agree_too(self, document):
        """The pose is what is seen; the joint matrices are what is drawn."""
        alone, together = _both_ways(document, lambda m: m.play('raise'))

        for one, other in zip(_skin_of(alone), _skin_of(together), strict=True):
            assert np.allclose(one, other, atol=1e-9)


class TestManyFiguresAgree:
    def test_every_figure_of_a_mixed_crowd(self, document):
        """Figures on different clips at different phases, together and alone."""
        clips = ['raise', 'kick']
        crowd = Crowd()
        alone, together = [], []
        for index in range(7):
            one, other = _figure(document), _figure(document)
            for model in (one, other):
                model.play(clips[index % 2])
                model.mixer.layers[0].tracks[0].time = 0.13 * index
            alone.append(one)
            together.append(crowd.add(other) and other)
        for _ in range(5):
            for model in alone:
                model.update(1 / 30.0)
            crowd.update(1 / 30.0)

        for one, other in zip(alone, together, strict=True):
            assert np.allclose(_pose_of(one), _pose_of(other), atol=1e-9)

    def test_figures_whose_layers_are_at_different_weights_agree(self, document):
        """The same layers at unequal weights is one group, not one weight.

        A crowd gathers figures by the *shape* of the work, so a layer dialled
        between two poses puts every figure of the crowd in one group whatever
        each has that layer turned up to -- which is what a crowd part way
        through stopping and starting looks like. The strength has to come from
        each figure rather than from whichever of them the group is led by.
        """
        weights = [1.0, 0.65, 0.3, 1.0, 0.0]
        crowd = Crowd()
        alone, together = [], []
        for weight in weights:
            one, other = _figure(document), _figure(document)
            for model in (one, other):
                model.play('kick')
                model.layer('upper').play('raise')
                model.layer('upper').weight = weight
            alone.append(one)
            crowd.add(other)
            together.append(other)
        for _ in range(4):
            for model in alone:
                model.update(1 / 30.0)
            crowd.update(1 / 30.0)

        for one, other in zip(alone, together, strict=True):
            assert np.allclose(_pose_of(one), _pose_of(other), atol=1e-9)

    def test_figures_doing_different_things_still_agree(self, document):
        crowd = Crowd()
        alone, together = [], []
        for index in range(4):
            one, other = _figure(document), _figure(document)
            for model in (one, other):
                model.play('raise')
                if index % 2:
                    model.layer('upper', mask=model.mask('spine')).play('kick')
            alone.append(one)
            crowd.add(other)
            together.append(other)
        for _ in range(4):
            for model in alone:
                model.update(1 / 30.0)
            crowd.update(1 / 30.0)

        for one, other in zip(alone, together, strict=True):
            assert np.allclose(_pose_of(one), _pose_of(other), atol=1e-9)


class TestMembership:
    def test_a_figure_of_another_build_is_refused(self, document):
        """A joint has to mean the same joint in every figure of a crowd."""
        from tests.unit._character_assets import skinned_bar_glb

        crowd = Crowd()
        crowd.add(_figure(document))
        other = CharacterModel(load_gltf(document=parse_gltf(skinned_bar_glb())))

        with pytest.raises(ValueError):
            crowd.add(other)

    def test_a_figure_taken_out_is_no_longer_posed(self, document):
        crowd = Crowd()
        model = _figure(document)
        crowd.add(model)
        crowd.remove(model)

        assert len(crowd) == 0
        assert crowd.update(1 / 30.0) == 0


class TestNotPosingEveryone:
    def test_a_budget_poses_that_many_and_takes_turns(self, document):
        crowd = Crowd()
        for _ in range(5):
            crowd.add(_figure(document))

        assert crowd.update(1 / 30.0, budget=2) == 2
        assert crowd.update(1 / 30.0, budget=2) == 2

    def test_every_figure_comes_round_within_a_few_frames(self, document):
        """A budget must not starve a figure; whose turn it is moves on."""
        crowd = Crowd()
        models = [_figure(document) for _ in range(4)]
        for model in models:
            crowd.add(model)
            model.play('raise')
        seen = set()
        for _ in range(4):
            posed = crowd._take_turns(list(crowd.members), 1)
            seen.update(id(member) for member in posed)
            crowd._turn = crowd._turn

        assert len(seen) == 4

    def test_a_rate_poses_a_figure_less_often_than_every_frame(self, document):
        crowd = Crowd()
        member = crowd.add(_figure(document), rate=10.0)
        member.mixer.play('raise')

        posed = sum(crowd.update(1 / 60.0) for _ in range(60))

        assert 8 <= posed <= 12, posed

    def test_the_clock_still_runs_for_a_figure_not_being_posed(self, document):
        """A figure posed every third frame is where its clip says it is when
        its turn comes, not three frames behind."""
        crowd = Crowd()
        member = crowd.add(_figure(document), rate=1.0)
        track = member.mixer.play('raise')

        for _ in range(30):
            crowd.update(1 / 30.0)

        assert track.time == pytest.approx(1.0, abs=1e-6)
