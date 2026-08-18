"""Unit tests for blending more than one animation clip at a time.

Pure Python/numpy -- no GL. Drives :class:`OpenGLContext.character.mixer`
against hand-built clips and plain ``Transform`` nodes, so what is under test is
the blend arithmetic and the layer rules rather than any file parsing.
"""
import math

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.character.mixer import AnimationMixer
from OpenGLContext.loaders.gltf import animation as ga
from OpenGLContext.scenegraph.transform import Transform


def _clip(name, node, path, values, times=(0.0, 1.0), is_rotation=False,
          interpolation='LINEAR'):
    """One clip driving one path of one node."""
    sampler = ga.Sampler(np.array(times, dtype='d'), np.array(values, dtype='d'),
                         interpolation, is_rotation=is_rotation)
    return ga.Animation(name, [ga.Channel(node, path, sampler)])


def _still(name, node, path, value, is_rotation=False):
    """A clip that holds one value for a second, so time does not matter."""
    return _clip(name, node, path, [value, value], is_rotation=is_rotation)


def _quat_z(degrees):
    half = math.radians(degrees) / 2.0
    return [0.0, 0.0, math.sin(half), math.cos(half)]


def _mixer(*clips, **kwargs):
    nodes = {1: Transform(), 2: Transform(), 3: Transform()}
    return AnimationMixer({c.name: c for c in clips}, nodes, **kwargs), nodes


# --------------------------------------------------------------------------
# One clip
# --------------------------------------------------------------------------

class TestOneTrack:
    def test_plays_a_named_clip(self):
        mixer, nodes = _mixer(_still('walk', 1, 'translation', [10, 0, 0]))
        mixer.play('walk')
        mixer.update(0.0)
        assert np.allclose(nodes[1].translation, [10, 0, 0])

    def test_an_unknown_clip_is_an_error(self):
        mixer, _ = _mixer(_still('walk', 1, 'translation', [10, 0, 0]))
        with pytest.raises(KeyError):
            mixer.play('sprint')

    def test_untouched_nodes_keep_their_rest_pose(self):
        mixer, nodes = _mixer(_still('walk', 1, 'translation', [10, 0, 0]))
        mixer.play('walk')
        mixer.update(0.0)
        assert np.allclose(nodes[2].translation, [0, 0, 0])

    def test_a_track_advances_with_the_clock(self):
        mixer, nodes = _mixer(_clip('slide', 1, 'translation',
                                    [[0, 0, 0], [10, 0, 0]]))
        track = mixer.play('slide')
        mixer.update(0.25)
        assert math.isclose(track.time, 0.25)
        assert np.allclose(nodes[1].translation, [2.5, 0, 0])

    def test_speed_scales_the_clock(self):
        mixer, nodes = _mixer(_clip('slide', 1, 'translation',
                                    [[0, 0, 0], [10, 0, 0]]))
        mixer.play('slide', speed=2.0)
        mixer.update(0.25)
        assert np.allclose(nodes[1].translation, [5, 0, 0])

    def test_a_loop_wraps(self):
        mixer, nodes = _mixer(_clip('slide', 1, 'translation',
                                    [[0, 0, 0], [10, 0, 0]]))
        track = mixer.play('slide', loop=True)
        mixer.update(1.25)
        assert math.isclose(track.time, 0.25)
        assert not track.finished
        assert np.allclose(nodes[1].translation, [2.5, 0, 0])

    def test_a_one_shot_holds_its_last_frame(self):
        mixer, nodes = _mixer(_clip('land', 1, 'translation',
                                    [[0, 0, 0], [10, 0, 0]]))
        track = mixer.play('land', loop=False)
        mixer.update(4.0)
        assert track.finished
        assert math.isclose(track.time, 1.0)
        assert np.allclose(nodes[1].translation, [10, 0, 0])

    def test_playing_the_same_clip_again_does_not_restart_it(self):
        mixer, _ = _mixer(_clip('run', 1, 'translation', [[0, 0, 0], [10, 0, 0]]))
        track = mixer.play('run')
        mixer.update(0.5)
        again = mixer.play('run')
        assert again is track
        assert math.isclose(track.time, 0.5)

    def test_restart_rewinds_it(self):
        mixer, _ = _mixer(_clip('run', 1, 'translation', [[0, 0, 0], [10, 0, 0]]))
        track = mixer.play('run')
        mixer.update(0.5)
        mixer.play('run', restart=True)
        assert math.isclose(track.time, 0.0)


# --------------------------------------------------------------------------
# Blending within a layer
# --------------------------------------------------------------------------

class TestCrossfade:
    def test_halfway_between_two_clips(self):
        mixer, nodes = _mixer(_still('a', 1, 'translation', [10, 0, 0]),
                              _still('b', 1, 'translation', [0, 10, 0]))
        mixer.play('a')
        mixer.update(0.0)
        mixer.play('b', fade=1.0)
        mixer.update(0.5)
        assert np.allclose(nodes[1].translation, [5, 5, 0], atol=1e-6)

    def test_the_outgoing_clip_is_gone_at_the_end(self):
        mixer, nodes = _mixer(_still('a', 1, 'translation', [10, 0, 0]),
                              _still('b', 1, 'translation', [0, 10, 0]))
        mixer.play('a')
        mixer.play('b', fade=1.0)
        mixer.update(1.0)
        assert np.allclose(nodes[1].translation, [0, 10, 0], atol=1e-6)
        assert mixer.playing == ('b',)

    def test_rotations_take_the_short_way(self):
        mixer, nodes = _mixer(
            _still('a', 1, 'rotation', _quat_z(0), is_rotation=True),
            _still('b', 1, 'rotation', _quat_z(90), is_rotation=True))
        mixer.play('a')
        mixer.update(0.0)
        mixer.play('b', fade=1.0)
        mixer.update(0.5)
        axis = nodes[1].rotation
        assert math.isclose(abs(axis[3]), math.radians(45.0), abs_tol=1e-5)

    def test_scales_blend(self):
        mixer, nodes = _mixer(_still('a', 1, 'scale', [1, 1, 1]),
                              _still('b', 1, 'scale', [3, 3, 3]))
        mixer.play('a')
        mixer.update(0.0)
        mixer.play('b', fade=1.0)
        mixer.update(0.5)
        assert np.allclose(nodes[1].scale, [2, 2, 2], atol=1e-6)

    def test_fading_out_returns_to_the_rest_pose(self):
        mixer, nodes = _mixer(_still('a', 1, 'translation', [10, 0, 0]))
        mixer.play('a')
        mixer.update(0.0)
        mixer.stop(fade=1.0)
        mixer.update(0.5)
        assert np.allclose(nodes[1].translation, [5, 0, 0], atol=1e-6)
        mixer.update(0.5)
        assert np.allclose(nodes[1].translation, [0, 0, 0], atol=1e-6)
        assert mixer.playing == ()

    def test_fading_in_from_the_rest_pose(self):
        mixer, nodes = _mixer(_still('a', 1, 'translation', [10, 0, 0]))
        mixer.play('a', fade=1.0)
        mixer.update(0.25)
        assert np.allclose(nodes[1].translation, [2.5, 0, 0], atol=1e-6)


# --------------------------------------------------------------------------
# Layers
# --------------------------------------------------------------------------

class TestLayers:
    def test_a_masked_layer_moves_only_its_own_bones(self):
        whole = ga.Animation('run', [
            ga.Channel(node, 'translation',
                       ga.Sampler(np.array([0.0, 1.0]),
                                  np.array([[10, 0, 0], [10, 0, 0]], dtype='d')))
            for node in (1, 2)])
        mixer, nodes = _mixer(whole, _still('fire', 2, 'translation', [0, 0, 7]))
        mixer.play('run')
        mixer.layer('upper', mask={2}).play('fire')
        mixer.update(0.0)
        assert np.allclose(nodes[1].translation, [10, 0, 0])
        assert np.allclose(nodes[2].translation, [0, 0, 7])

    def test_a_masked_layer_fades_into_the_layer_below(self):
        mixer, nodes = _mixer(_still('run', 2, 'translation', [10, 0, 0]),
                              _still('fire', 2, 'translation', [0, 10, 0]))
        mixer.play('run')
        mixer.layer('upper', mask={2}).play('fire', fade=1.0)
        mixer.update(0.5)
        assert np.allclose(nodes[2].translation, [5, 5, 0], atol=1e-6)

    def test_a_layer_weight_scales_its_whole_contribution(self):
        mixer, nodes = _mixer(_still('run', 2, 'translation', [10, 0, 0]),
                              _still('fire', 2, 'translation', [0, 10, 0]))
        mixer.play('run')
        upper = mixer.layer('upper', mask={2}, weight=0.25)
        upper.play('fire')
        mixer.update(0.0)
        assert np.allclose(nodes[2].translation, [7.5, 2.5, 0], atol=1e-6)

    def test_layers_apply_in_the_order_they_were_made(self):
        mixer, nodes = _mixer(_still('a', 1, 'translation', [10, 0, 0]),
                              _still('b', 1, 'translation', [0, 10, 0]),
                              _still('c', 1, 'translation', [0, 0, 10]))
        mixer.play('a')
        mixer.layer('middle').play('b')
        mixer.layer('top').play('c')
        mixer.update(0.0)
        assert np.allclose(nodes[1].translation, [0, 0, 10])

    def test_asking_for_a_layer_twice_gives_the_same_layer(self):
        mixer, _ = _mixer(_still('a', 1, 'translation', [10, 0, 0]))
        assert mixer.layer('upper', mask={2}) is mixer.layer('upper')

    def test_an_additive_layer_adds_its_delta(self):
        mixer, nodes = _mixer(
            _still('run', 1, 'translation', [10, 0, 0]),
            _clip('recoil', 1, 'translation', [[0, 0, 0], [0, 5, 0]]))
        mixer.play('run')
        recoil = mixer.layer('recoil', additive=True)
        recoil.play('recoil', loop=False)
        mixer.update(1.0)
        assert np.allclose(nodes[1].translation, [10, 5, 0], atol=1e-6)

    def test_an_additive_layer_at_half_weight_adds_half(self):
        mixer, nodes = _mixer(
            _still('run', 1, 'translation', [10, 0, 0]),
            _clip('recoil', 1, 'translation', [[0, 0, 0], [0, 5, 0]]))
        mixer.play('run')
        mixer.layer('recoil', additive=True, weight=0.5).play('recoil', loop=False)
        mixer.update(1.0)
        assert np.allclose(nodes[1].translation, [10, 2.5, 0], atol=1e-6)

    def test_an_additive_rotation_composes(self):
        mixer, nodes = _mixer(
            _still('aim', 1, 'rotation', _quat_z(30), is_rotation=True),
            _clip('kick', 1, 'rotation', [_quat_z(0), _quat_z(20)],
                  is_rotation=True))
        mixer.play('aim')
        mixer.layer('kick', additive=True).play('kick', loop=False)
        mixer.update(1.0)
        assert math.isclose(abs(nodes[1].rotation[3]), math.radians(50.0),
                            abs_tol=1e-5)


# --------------------------------------------------------------------------
# What a mixer drives besides node transforms
# --------------------------------------------------------------------------

class TestMorphAndSkin:
    def test_morph_weights_blend(self):
        got = []
        clips = [_still('a', 1, 'weights', [1.0, 0.0]),
                 _still('b', 1, 'weights', [0.0, 1.0])]
        mixer, _ = _mixer(*clips, node_morph={1: [got.append]})
        mixer.play('a')
        mixer.update(0.0)
        mixer.play('b', fade=1.0)
        mixer.update(0.5)
        assert np.allclose(got[-1], [0.5, 0.5], atol=1e-6)

    def test_skins_are_reapplied_once_a_frame(self):
        class Recorder:
            def __init__(self):
                self.count = 0

            def apply(self, worlds):
                self.count += 1

        skin = Recorder()
        mixer, _ = _mixer(_still('a', 1, 'translation', [10, 0, 0]),
                          skins=[skin], compute_worlds=dict)
        mixer.play('a')
        mixer.update(0.0)
        mixer.update(0.1)
        assert skin.count == 2


# --------------------------------------------------------------------------
# Binding to a loaded document
# --------------------------------------------------------------------------

class TestFromScene:
    def test_names_the_clips_a_document_carries(self):
        import types
        scene = types.SimpleNamespace(
            animations=[ga.Animation('walk', []), ga.Animation(None, [])],
            node_transforms={}, node_morph={}, skins=[],
            node_roots=[], node_children={})
        mixer = AnimationMixer.from_scene(scene)
        assert set(mixer.clips) == {'walk', 'animation1'}


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------

class TestEdges:
    def test_a_clip_with_no_duration_stays_at_zero(self):
        clip = _clip('pose', 1, 'translation', [[4, 0, 0]], times=(0.0,))
        mixer, nodes = _mixer(clip)
        track = mixer.play('pose')
        mixer.update(3.0)
        assert track.time == 0.0
        assert np.allclose(nodes[1].translation, [4, 0, 0])

    def test_a_track_fading_in_from_nothing_contributes_nothing_yet(self):
        mixer, nodes = _mixer(_still('a', 1, 'translation', [10, 0, 0]))
        mixer.play('a', fade=1.0)
        mixer.update(0.0)
        assert np.allclose(nodes[1].translation, [0, 0, 0])

    def test_a_masked_layer_ignores_what_is_outside_its_mask(self):
        both = ga.Animation('fire', [
            ga.Channel(node, 'translation',
                       ga.Sampler(np.array([0.0, 1.0]),
                                  np.array([[0, 9, 0], [0, 9, 0]], dtype='d')))
            for node in (1, 2)])
        mixer, nodes = _mixer(both)
        mixer.layer('upper', mask={2}).play('fire')
        mixer.update(0.0)
        assert np.allclose(nodes[1].translation, [0, 0, 0])
        assert np.allclose(nodes[2].translation, [0, 9, 0])

    def test_a_layer_names_the_track_it_is_heading_for(self):
        mixer, _ = _mixer(_still('a', 1, 'translation', [10, 0, 0]))
        base = mixer.layer()
        assert base.current is None
        track = base.play('a')
        assert base.current is track
        base.stop(fade=1.0)
        assert base.current is None

    def test_a_rotation_layer_eases_in_over_the_one_below(self):
        mixer, nodes = _mixer(
            _still('aim', 1, 'rotation', _quat_z(0), is_rotation=True),
            _still('turn', 1, 'rotation', _quat_z(90), is_rotation=True))
        mixer.play('aim')
        mixer.layer('upper', mask={1}).play('turn', fade=1.0)
        mixer.update(0.5)
        assert math.isclose(abs(nodes[1].rotation[3]), math.radians(45.0),
                            abs_tol=1e-5)

    def test_an_additive_scale_multiplies(self):
        mixer, nodes = _mixer(_still('big', 1, 'scale', [2, 2, 2]),
                              _clip('swell', 1, 'scale',
                                    [[1, 1, 1], [3, 3, 3]]))
        mixer.play('big')
        mixer.layer('swell', additive=True).play('swell', loop=False)
        mixer.update(1.0)
        assert np.allclose(nodes[1].scale, [6, 6, 6], atol=1e-6)

    def test_an_additive_layer_at_half_weight_scales_halfway(self):
        mixer, nodes = _mixer(_still('big', 1, 'scale', [2, 2, 2]),
                              _clip('swell', 1, 'scale',
                                    [[1, 1, 1], [3, 3, 3]]))
        mixer.play('big')
        mixer.layer('swell', additive=True, weight=0.5).play('swell', loop=False)
        mixer.update(1.0)
        assert np.allclose(nodes[1].scale, [4, 4, 4], atol=1e-6)

    def test_an_additive_morph_weight_adds(self):
        got = []
        mixer, _ = _mixer(_still('a', 1, 'weights', [0.25, 0.0]),
                          _clip('b', 1, 'weights', [[0.0, 0.0], [0.0, 0.5]]),
                          node_morph={1: [got.append]})
        mixer.play('a')
        mixer.layer('extra', additive=True).play('b', loop=False)
        mixer.update(1.0)
        assert np.allclose(got[-1], [0.25, 0.5], atol=1e-6)

    def test_an_unchanged_pose_is_not_rewritten(self):
        got = []
        mixer, _ = _mixer(_still('a', 1, 'weights', [1.0, 0.0]),
                          node_morph={1: [got.append]})
        mixer.play('a')
        mixer.update(0.0)
        mixer.update(0.0)
        assert len(got) == 1

    def test_a_clip_added_after_the_fact_still_plays(self):
        mixer, nodes = _mixer(_still('a', 1, 'translation', [10, 0, 0]))
        mixer.clips['later'] = _still('later', 2, 'translation', [0, 6, 0])
        mixer.play('later')
        mixer.update(0.0)
        assert np.allclose(nodes[2].translation, [0, 6, 0])

    def test_a_baked_matrix_node_is_left_alone(self, caplog):
        from OpenGLContext.scenegraph.transform import MatrixTransform
        clip = _still('a', 1, 'translation', [10, 0, 0])
        node = MatrixTransform(localMatrix=np.eye(4))
        mixer = AnimationMixer({'a': clip}, {1: node})
        mixer.play('a')
        with caplog.at_level('WARNING'):
            mixer.update(0.0)
            mixer.update(0.0)
        assert sum('baked matrix' in r.message for r in caplog.records) == 1
