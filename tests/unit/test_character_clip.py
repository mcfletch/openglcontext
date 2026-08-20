"""Sampling a clip for a whole skeleton at once.

Pure Python/numpy -- no GL. :class:`OpenGLContext.character.clip.ClipSampler`
answers the question :meth:`Animation.evaluate` answers, for every joint in one
go, so the test is that the two agree -- at the keyframes, between them, and
outside the clip at either end -- over channels of every interpolation and
every path mixed together in one clip, which is what an exported clip is.
"""
import numpy as np
import pytest

from OpenGLContext.character.clip import ClipSampler
from OpenGLContext.character.rig import Rig
from OpenGLContext.loaders.gltf import animation as ga
from OpenGLContext.scenegraph.transform import Transform


def _rig(count=6):
    children = {0: list(range(1, count))}
    transforms = {i: Transform(translation=(0.0, float(i), 0.0),
                               scale=(1.0, 1.0, 1.0 + 0.1 * i))
                  for i in range(count)}
    return Rig([0], children, transforms)


def _sampler(times, values, interpolation='LINEAR', is_rotation=False):
    return ga.Sampler(np.array(times, dtype='d'), np.array(values, dtype='d'),
                      interpolation, is_rotation=is_rotation)


def _quat(degrees):
    half = np.radians(degrees) / 2.0
    return [0.0, 0.0, np.sin(half), np.cos(half)]


def _mixed_clip():
    """One clip carrying every shape an exporter emits.

    Two time grids, all three interpolations, every path, a constant channel
    and a moving one on the same grid -- the combination the grouping has to
    take apart and put back together.
    """
    coarse = [0.0, 1.0]
    fine = [0.0, 0.25, 0.5, 1.0]
    channels = [
        ga.Channel(1, 'translation', _sampler(coarse, [[0, 0, 0], [3, 4, 5]])),
        ga.Channel(2, 'translation', _sampler(coarse, [[1, 1, 1], [1, 1, 1]])),
        ga.Channel(3, 'translation', _sampler(
            fine, [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], 'STEP')),
        ga.Channel(1, 'rotation', _sampler(
            fine, [_quat(0), _quat(90), _quat(180), _quat(270)],
            'LINEAR', is_rotation=True)),
        ga.Channel(4, 'rotation', _sampler(
            coarse, [_quat(0), _quat(45)], 'STEP', is_rotation=True)),
        ga.Channel(2, 'scale', _sampler(coarse, [[1, 1, 1], [2, 3, 4]])),
        ga.Channel(5, 'scale', _sampler(
            fine,
            [[1, 1, 1], [0, 0, 0], [1.5, 1.5, 1.5], [0, 0, 0],
             [2, 2, 2], [0, 0, 0], [1, 1, 1], [0, 0, 0],
             [1, 2, 3], [0, 0, 0], [3, 2, 1], [0, 0, 0]],
            'CUBICSPLINE')),
    ]
    return ga.Animation('mixed', channels)


TIMES = [-0.5, 0.0, 0.1, 0.25, 0.4, 0.5, 0.75, 1.0, 1.5]


def _scattered(sampler, rig, t):
    """The sampler's answer as the dict ``Animation.evaluate`` returns."""
    translation, rotation, scale = sampler.sample(t)
    out = {}
    for values, slots, path in (
            (translation, sampler.slots_translation, 'translation'),
            (rotation, sampler.slots_rotation, 'rotation'),
            (scale, sampler.slots_scale, 'scale')):
        for row, slot in zip(values, slots, strict=True):
            out.setdefault(int(rig.indices[slot]), {})[path] = row
    return out


class TestAgreementWithTheOneAtATimeSampler:
    @pytest.mark.parametrize('t', TIMES)
    def test_every_channel_of_a_mixed_clip_matches(self, t):
        rig = _rig()
        clip = _mixed_clip()
        sampler = ClipSampler(clip, rig)

        got = _scattered(sampler, rig, t)
        want = clip.evaluate(t)

        assert set(got) == set(want)
        for node, paths in want.items():
            assert set(got[node]) == set(paths)
            for path, value in paths.items():
                assert np.allclose(got[node][path], value, atol=1e-12), (node, path)

    def test_the_duration_is_the_clips_own(self):
        rig = _rig()
        clip = _mixed_clip()

        assert ClipSampler(clip, rig).duration == clip.duration


class TestWhatAClipDrives:
    def test_a_channel_aimed_at_no_node_of_the_rig_is_left_out(self):
        """A retargeted clip may name joints this skeleton has not got."""
        rig = _rig(count=3)
        clip = ga.Animation('stray', [
            ga.Channel(99, 'translation', _sampler([0.0, 1.0], [[0, 0, 0], [1, 1, 1]])),
            ga.Channel(1, 'translation', _sampler([0.0, 1.0], [[0, 0, 0], [2, 2, 2]])),
        ])

        sampler = ClipSampler(clip, rig)

        assert list(sampler.slots_translation) == [rig.slot_of[1]]

    def test_two_channels_on_one_path_of_one_node_leave_one_value(self):
        """Malformed content: the value written is the later channel's, which
        is what the one-at-a-time sampler's dict leaves behind."""
        rig = _rig(count=3)
        clip = ga.Animation('doubled', [
            ga.Channel(1, 'translation', _sampler([0.0, 1.0], [[0, 0, 0], [1, 1, 1]])),
            ga.Channel(1, 'translation', _sampler([0.0, 1.0], [[0, 0, 0], [9, 9, 9]])),
        ])

        sampler = ClipSampler(clip, rig)
        translation, _, _ = sampler.sample(1.0)

        assert len(sampler.slots_translation) == 1
        assert np.allclose(translation[0], [9, 9, 9])

    def test_a_clip_that_drives_nothing_samples_to_nothing(self):
        rig = _rig(count=3)
        sampler = ClipSampler(ga.Animation('empty', []), rig)

        translation, rotation, scale = sampler.sample(0.5)

        assert len(translation) == 0 and len(rotation) == 0 and len(scale) == 0


class TestConstantChannels:
    def test_a_channel_that_never_moves_is_answered_without_interpolating(self):
        """Most of an exported clip's channels hold one value for its whole
        length; they should cost a lookup, not a search and a blend."""
        rig = _rig(count=3)
        clip = ga.Animation('still', [
            ga.Channel(1, 'translation', _sampler([0.0, 1.0], [[7, 8, 9], [7, 8, 9]])),
        ])

        sampler = ClipSampler(clip, rig)

        assert sampler.constant_channels == 1
        assert np.allclose(sampler.sample(0.3)[0][0], [7, 8, 9])
        assert np.allclose(sampler.sample(0.7)[0][0], [7, 8, 9])

    def test_a_cubic_channel_is_never_taken_for_a_constant(self):
        """Equal values with unequal tangents still move between the keys."""
        rig = _rig(count=3)
        clip = ga.Animation('curved', [
            ga.Channel(1, 'translation', _sampler(
                [0.0, 1.0],
                [[0, 0, 0], [1, 1, 1], [5, 0, 0], [-5, 0, 0], [1, 1, 1], [0, 0, 0]],
                'CUBICSPLINE')),
        ])

        sampler = ClipSampler(clip, rig)

        assert sampler.constant_channels == 0
        assert not np.allclose(sampler.sample(0.5)[0][0], [1, 1, 1])


class TestMorphWeights:
    def test_weights_come_back_keyed_by_node(self):
        """Morph weights are per mesh and of no fixed width, so they stay
        beside the skeleton's arrays rather than in them."""
        rig = _rig(count=3)
        clip = ga.Animation('blink', [
            ga.Channel(2, 'weights', _sampler([0.0, 1.0], [[0.0, 0.0], [1.0, 0.5]])),
        ])

        sampler = ClipSampler(clip, rig)

        assert np.allclose(sampler.sample_weights(1.0)[2], [1.0, 0.5])
        assert sampler.sample_weights(0.0)[2].tolist() == [0.0, 0.0]

    def test_a_clip_with_no_morph_channels_has_no_weights(self):
        rig = _rig(count=3)
        sampler = ClipSampler(_mixed_clip(), rig)

        assert sampler.sample_weights(0.5) == {}


class TestSamplingManyAtOnce:
    """A crowd is many bodies in one clip at different points in it."""

    @pytest.mark.parametrize('t', TIMES)
    def test_one_time_matches_sampling_it_alone(self, t):
        rig = _rig()
        sampler = ClipSampler(_mixed_clip(), rig)

        many = sampler.sample_many([t])
        one = sampler.sample(t)

        for batched, single in zip(many, one, strict=True):
            assert np.allclose(batched[0], single, atol=1e-12)

    def test_every_time_matches_sampling_them_one_by_one(self):
        rig = _rig()
        sampler = ClipSampler(_mixed_clip(), rig)

        many = sampler.sample_many(TIMES)

        for row, t in enumerate(TIMES):
            for batched, single in zip(many, sampler.sample(t), strict=True):
                assert np.allclose(batched[row], single, atol=1e-12), t

    def test_a_clip_that_drives_nothing_answers_for_every_time(self):
        rig = _rig(count=3)
        sampler = ClipSampler(ga.Animation('empty', []), rig)

        translation, rotation, scale = sampler.sample_many([0.0, 0.5])

        assert translation.shape == (2, 0, 3)
        assert rotation.shape == (2, 0, 4)
        assert scale.shape == (2, 0, 3)


class TestTheCubicTestContentIsReallyCubic:
    """A cubic clip whose tangents did nothing would prove nothing.

    The GPU blend is held against this sampler on a cubic asset, so the asset
    has to bend between its keys rather than draw the straight line a linear
    channel would draw through the same values.
    """

    def _sampler(self, interpolation):
        from OpenGLContext.loaders.gltf import load_gltf
        from tests.helpers._crowd_asset import crowd_character_glb

        scene = load_gltf(crowd_character_glb(
            joints=8, vertices=64, clips=1, keys=6, moving=3,
            interpolation=interpolation))
        for channel in scene.animations[0].channels:
            if channel.sampler.interpolation == interpolation:
                return channel.sampler
        raise AssertionError('no %s channel was written' % interpolation)

    def test_the_curve_leaves_the_line_between_its_keys(self):
        cubic = self._sampler('CUBICSPLINE')
        linear = self._sampler('LINEAR')

        # Halfway between two keys is where a curve is furthest from the chord.
        apart = max(float(np.abs(cubic.evaluate(t) - linear.evaluate(t)).max())
                    for t in (0.1, 0.3, 0.5, 0.7, 0.9))

        assert apart > 1e-3, apart

    def test_the_keys_themselves_still_agree(self):
        """Only between the keys: at one, both read the value that is there."""
        cubic = self._sampler('CUBICSPLINE')
        linear = self._sampler('LINEAR')

        for t in linear.times:
            assert np.allclose(cubic.evaluate(float(t)), linear.evaluate(float(t)),
                               atol=1e-6)


class TestAskingForAFewJointsOnly:
    """A caller wanting seven joints of fifty-seven should pay for seven.

    What it must not do is answer differently: a narrowed view is the same
    clip, read at the same moments, for the joints it was narrowed to.
    """

    def _narrowed(self, sampler, rig, wanted):
        wanted = np.asarray(sorted(wanted), dtype=np.int32)
        positions = np.full(rig.n, -1, dtype=np.int32)
        positions[wanted] = np.arange(len(wanted), dtype=np.int32)
        return sampler.restricted(wanted, positions), wanted

    @pytest.mark.parametrize('t', TIMES)
    def test_it_answers_what_the_whole_clip_answers(self, t):
        rig = _rig()
        sampler = ClipSampler(_mixed_clip(), rig)
        view, wanted = self._narrowed(sampler, rig, [1, 2, 5])

        whole = sampler.sample(t)
        part = view.sample(t)

        for index, (values, slots) in enumerate((
                (whole[0], sampler.slots_translation),
                (whole[1], sampler.slots_rotation),
                (whole[2], sampler.slots_scale))):
            narrowed_slots = (view.slots_translation, view.slots_rotation,
                              view.slots_scale)[index]
            for row, slot in enumerate(slots):
                if slot not in wanted:
                    continue
                place = int(np.flatnonzero(wanted == slot)[0])
                where = np.flatnonzero(narrowed_slots == place)
                assert len(where), (index, slot)
                assert np.allclose(part[index][int(where[0])], values[row],
                                   atol=1e-12)

    def test_it_leaves_out_the_joints_it_was_not_asked_for(self):
        rig = _rig()
        sampler = ClipSampler(_mixed_clip(), rig)
        view, wanted = self._narrowed(sampler, rig, [1])

        for slots in (view.slots_translation, view.slots_rotation,
                      view.slots_scale):
            assert len(slots) <= len(wanted)
        assert len(view.slots_translation) < len(sampler.slots_translation)

    def test_asking_twice_gives_the_same_view(self):
        """Which joints are read changes when equipment does, not per frame."""
        rig = _rig()
        sampler = ClipSampler(_mixed_clip(), rig)

        first, wanted = self._narrowed(sampler, rig, [1, 2])
        again, _ = self._narrowed(sampler, rig, [1, 2])

        assert first is again

    def test_a_view_of_joints_the_clip_does_not_move_samples_to_nothing(self):
        rig = _rig()
        sampler = ClipSampler(_mixed_clip(), rig)
        view, _wanted = self._narrowed(sampler, rig, [0])

        translation, rotation, scale = view.sample(0.5)

        assert len(translation) == 0 and len(rotation) == 0 and len(scale) == 0

    @pytest.mark.parametrize('t', TIMES)
    def test_many_at_once_agrees_too(self, t):
        rig = _rig()
        sampler = ClipSampler(_mixed_clip(), rig)
        view, _wanted = self._narrowed(sampler, rig, [1, 2, 5])

        many = view.sample_many([t, t])
        one = view.sample(t)

        for batched, single in zip(many, one, strict=True):
            assert np.allclose(batched[0], single, atol=1e-12)
            assert np.allclose(batched[1], single, atol=1e-12)
