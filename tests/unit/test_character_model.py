"""Unit tests for a loaded character: rig, clips and what it is holding."""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.character import CharacterModel
from OpenGLContext.loaders import gltf
from OpenGLContext.scenegraph.transform import Transform

from ._character_assets import GRIP, character_glb, skeleton_glb


def _skinned_mesh(node):
    """The first geometry under ``node``, which is the character's body."""
    if getattr(node, 'geometry', None) is not None:
        return node.geometry
    for child in getattr(node, 'children', None) or ():
        found = _skinned_mesh(child)
        if found is not None:
            return found
    return None


class TestLoading:
    def test_loads_rig_clips_and_points(self):
        model = CharacterModel.load(character_glb())
        assert model.group is model.scene.group
        assert set(model.clips) == {'raise', 'kick'}
        assert model.humanoid.complete
        assert set(model.points) == {'grip'}

    def test_a_model_with_no_recognised_rig(self):
        names = ['bone%d' % i for i in range(19)]
        model = CharacterModel.load(skeleton_glb(names=names))
        assert model.humanoid is None
        assert model.mask('spine') == frozenset()
        assert model.point('rightHand') is None


class TestPoints:
    def test_a_named_point_beats_a_bone(self):
        model = CharacterModel.load(skeleton_glb())
        assert model.point('grip') is model.scene.node_transforms[GRIP]

    def test_a_bone_is_a_point_too(self):
        model = CharacterModel.load(skeleton_glb())
        assert model.point('rightHand') is model.humanoid.transform('rightHand')

    def test_an_unknown_point(self):
        model = CharacterModel.load(skeleton_glb())
        assert model.point('scabbard') is None

    def test_attach_and_detach_by_name(self):
        model = CharacterModel.load(skeleton_glb())
        weapon = Transform()
        assert model.attach('grip', weapon) is weapon
        assert weapon in list(model.point('grip').children)
        assert model.detach('grip', weapon) is True
        assert model.detach('grip', weapon) is False

    def test_attaching_to_nowhere(self):
        model = CharacterModel.load(skeleton_glb())
        assert model.attach('scabbard', Transform()) is None
        assert model.detach('scabbard', Transform()) is False


class TestAnimating:
    def test_playing_a_clip_deforms_the_skin(self):
        model = CharacterModel.load(character_glb())
        mesh = _skinned_mesh(model.group)
        rest = np.array(mesh.positions)
        model.play('raise', loop=False)
        model.update(1.0)
        assert not np.allclose(mesh.positions, rest, atol=1e-4)

    def test_a_masked_layer_over_the_upper_body(self):
        model = CharacterModel.load(character_glb())
        arm = model.humanoid.transform('rightUpperArm')
        leg = model.humanoid.transform('rightUpperLeg')
        model.play('kick', loop=False)
        model.layer('upper', mask=model.mask('spine')).play('raise', loop=False)
        model.update(1.0)
        assert abs(arm.rotation[3]) > 1.0        # the arm follows 'raise'
        assert abs(leg.rotation[3]) > 1.0        # the leg still follows 'kick'

    def test_update_needs_no_clips(self):
        model = CharacterModel.load(character_glb())
        model.update(0.5)                        # nothing playing: still valid
        assert model.mixer.playing == ()


class TestFromScene:
    def test_wraps_an_already_loaded_scene(self):
        scene = gltf.load_gltf(character_glb())
        model = CharacterModel.from_scene(scene)
        assert model.scene is scene
        assert set(model.clips) == {'raise', 'kick'}
