"""A crowd's gait read from a ClipMap: the clips by role, and their speeds as strides."""
import pytest

from OpenGLContext.character.locomotion import ClipMap, ClipSpec
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.character.wander import Gait, WanderingCrowd

from ._character_assets import character_glb

CLIPS = ClipMap(idle='raise', walk=('kick', 1.2), run=('raise', 2.4))


def figure():
    return CharacterModel.load(character_glb())


def test_a_gait_from_a_clip_map_plays_its_roles_at_their_speeds():
    gait = Gait.from_clips(figure(), CLIPS)
    assert gait.idles == ['raise']
    assert gait.walk.tracks[0].name == 'kick'
    assert gait.run.tracks[0].name == 'raise'
    assert (gait.walk_stride, gait.run_stride) == (1.2, 2.4)
    assert gait.fade == CLIPS.fade


def test_a_map_with_no_run_walks_at_every_speed():
    gait = Gait.from_clips(figure(), ClipMap(walk=('kick', 1.0)))
    assert gait.idles == []
    assert gait.run_stride == 1.0
    gait.apply(1.0, 3.0)
    assert gait.walk.tracks[0].speed == pytest.approx(3.0)


def test_a_map_with_no_walk_is_refused():
    with pytest.raises(ValueError, match='walk'):
        Gait.from_clips(figure(), ClipMap(idle='raise'))


def test_a_walk_with_no_speed_is_refused():
    with pytest.raises(ValueError, match='speed'):
        Gait.from_clips(figure(), ClipMap(walk=ClipSpec('kick')))


def test_a_crowd_given_clips_builds_each_figure_its_gait_from_them():
    crowd = WanderingCrowd((-5.0, 5.0, -5.0, 5.0), clips=CLIPS)
    crowd.add(figure())
    crowd.add(figure())
    assert [gait.walk_stride for gait in crowd.gaits] == [1.2, 1.2]
    assert all(gait.run.tracks[0].name == 'raise' for gait in crowd.gaits)


def test_a_crowd_takes_clips_or_a_gait_and_not_both():
    with pytest.raises(TypeError):
        WanderingCrowd(clips=CLIPS, gait=lambda model: Gait(model, 'kick'))
