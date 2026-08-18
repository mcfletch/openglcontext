"""Unit tests for the humanoid skeleton vocabulary and its resolution.

Pure Python -- no GL. Builds small glTF documents in memory and checks that the
humanoid bone map is recovered from ``VRMC_vrm``, from ``VRMC_vrm_animation``
and, failing both, from the joint names themselves.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.character import humanoid as hm
from OpenGLContext.loaders import gltf

from ._character_assets import SKELETON, skeleton_glb as _skeleton_glb


# --------------------------------------------------------------------------
# The vocabulary itself
# --------------------------------------------------------------------------

class TestVocabulary:
    def test_the_fifty_five_bones(self):
        assert len(hm.HUMAN_BONES) == 55
        assert hm.HUMAN_BONES[0] == 'hips'
        assert 'leftLittleDistal' in hm.HUMAN_BONES

    def test_required_bones_are_bones(self):
        assert hm.REQUIRED_BONES <= set(hm.HUMAN_BONES)
        assert len(hm.REQUIRED_BONES) == 15

    def test_every_bone_but_hips_has_a_parent(self):
        assert hm.BONE_PARENT['hips'] is None
        for bone in hm.HUMAN_BONES:
            parent = hm.BONE_PARENT[bone]
            assert bone == 'hips' or parent in hm.HUMAN_BONES

    def test_parents_come_before_children(self):
        order = {bone: i for i, bone in enumerate(hm.HUMAN_BONES)}
        for bone, parent in hm.BONE_PARENT.items():
            if parent is not None:
                assert order[parent] < order[bone]


# --------------------------------------------------------------------------
# Name matching
# --------------------------------------------------------------------------

class TestBoneForName:
    @pytest.mark.parametrize('name,bone', [
        ('hips', 'hips'),
        ('Hips', 'hips'),
        ('Pelvis', 'hips'),
        ('mixamorig:Hips', 'hips'),
        ('Armature|Hips', 'hips'),
        ('Spine', 'spine'),
        ('Spine1', 'chest'),
        ('Spine2', 'upperChest'),
        ('spine.001', 'chest'),
        ('Chest', 'chest'),
        ('UpperChest', 'upperChest'),
        ('Neck', 'neck'),
        ('Head', 'head'),
        ('mixamorig:LeftShoulder', 'leftShoulder'),
        ('shoulder.L', 'leftShoulder'),
        ('mixamorig:LeftArm', 'leftUpperArm'),
        ('upper_arm.L', 'leftUpperArm'),
        ('LeftUpperArm', 'leftUpperArm'),
        ('mixamorig:RightForeArm', 'rightLowerArm'),
        ('forearm.R', 'rightLowerArm'),
        ('lowerarm_r', 'rightLowerArm'),
        ('hand.L', 'leftHand'),
        ('mixamorig:LeftUpLeg', 'leftUpperLeg'),
        ('thigh.R', 'rightUpperLeg'),
        ('mixamorig:RightLeg', 'rightLowerLeg'),
        ('shin.L', 'leftLowerLeg'),
        ('calf_r', 'rightLowerLeg'),
        ('foot.R', 'rightFoot'),
        ('mixamorig:LeftToeBase', 'leftToes'),
        ('toe.L', 'leftToes'),
        ('eye.L', 'leftEye'),
        ('Jaw', 'jaw'),
    ])
    def test_conventional_names(self, name, bone):
        assert hm.bone_for_name(name) == bone

    @pytest.mark.parametrize('name,bone', [
        ('mixamorig:LeftHandThumb1', 'leftThumbMetacarpal'),
        ('mixamorig:LeftHandThumb3', 'leftThumbDistal'),
        ('mixamorig:RightHandIndex1', 'rightIndexProximal'),
        ('mixamorig:RightHandIndex2', 'rightIndexIntermediate'),
        ('f_middle.02.L', 'leftMiddleIntermediate'),
        ('LeftLittleDistal', 'leftLittleDistal'),
        ('pinky_03_r', 'rightLittleDistal'),
    ])
    def test_finger_names(self, name, bone):
        assert hm.bone_for_name(name) == bone

    @pytest.mark.parametrize('name', [
        '', 'Armature', 'weapon_grip', 'tail_01', 'Cesium_Man', 'Cube.001',
    ])
    def test_names_that_are_not_bones(self, name):
        assert hm.bone_for_name(name) is None

    def test_a_side_is_needed_for_a_sided_bone(self):
        assert hm.bone_for_name('UpperArm') is None
        assert hm.bone_for_name('foot') is None

    def test_numbered_joint_chains(self):
        # The naming the Khronos rigged samples use.
        assert hm.bone_for_name('torso_joint_1') == 'hips'
        assert hm.bone_for_name('leg_joint_L_1') == 'leftUpperLeg'
        assert hm.bone_for_name('leg_joint_R_3') == 'rightFoot'
        assert hm.bone_for_name('arm_joint_L_2') == 'leftLowerArm'
        assert hm.bone_for_name('neck_joint_2') == 'head'

    def test_first_match_wins_over_a_later_duplicate(self):
        names = {3: 'Hips', 7: 'pelvis'}
        assert hm.bones_by_name(names)['hips'] == 3


# --------------------------------------------------------------------------
# Resolution against a loaded document
# --------------------------------------------------------------------------

class TestFromScene:
    def test_from_names(self):
        scene = gltf.load_gltf(_skeleton_glb())
        human = hm.Humanoid.from_scene(scene)
        assert human is not None
        assert human.bones['hips'] == 0
        assert human.bones['leftLowerArm'] == 13
        assert human.complete
        assert human.missing == frozenset()
        assert bool(human)

    def test_vrm_extension_wins_over_names(self):
        # A document that says, in VRM's own words, that node 5 is the head.
        ext = {'VRMC_vrm': {
            'specVersion': '1.0',
            'meta': {'name': 'test', 'authors': ['t'], 'licenseUrl': 'http://x'},
            'humanoid': {'humanBones': {
                'hips': {'node': 0}, 'spine': {'node': 1}, 'head': {'node': 5},
            }},
        }}
        scene = gltf.load_gltf(_skeleton_glb(ext))
        human = hm.Humanoid.from_scene(scene)
        assert human.bones['head'] == 5          # not node 4, which is named Head
        assert human.bones == {'hips': 0, 'spine': 1, 'head': 5}
        assert not human.complete
        assert 'leftFoot' in human.missing

    def test_vrm_animation_extension(self):
        ext = {'VRMC_vrm_animation': {
            'specVersion': '1.0',
            'humanoid': {'humanBones': {'hips': {'node': 0}, 'head': {'node': 4}}},
        }}
        scene = gltf.load_gltf(_skeleton_glb(ext))
        human = hm.Humanoid.from_scene(scene)
        assert human.bones == {'hips': 0, 'head': 4}

    def test_no_bones_at_all(self):
        blank = ['thing%d' % i for i in range(len(SKELETON))]
        scene = gltf.load_gltf(_skeleton_glb(names=blank))
        assert hm.Humanoid.from_scene(scene) is None

    def test_transform_and_node_lookup(self):
        scene = gltf.load_gltf(_skeleton_glb())
        human = hm.Humanoid.from_scene(scene)
        assert human.node('head') == 4
        assert human.node('jaw') is None
        assert human.transform('head') is scene.node_transforms[4]
        assert human.transform('jaw') is None
        assert 'head' in human
        assert len(human) == len(human.bones)

    def test_mask_is_the_subtree(self):
        scene = gltf.load_gltf(_skeleton_glb())
        human = hm.Humanoid.from_scene(scene)
        upper = human.mask('spine')
        assert 1 in upper and 4 in upper          # spine .. head
        assert 13 in upper                        # and the arms
        assert 6 not in upper                     # but not the legs
        assert 0 not in upper                     # nor the hips

    def test_mask_excludes_a_named_subtree(self):
        scene = gltf.load_gltf(_skeleton_glb())
        human = hm.Humanoid.from_scene(scene)
        lower = human.mask('hips', exclude=('spine',))
        assert 0 in lower and 6 in lower and 9 in lower
        assert 1 not in lower and 13 not in lower

    def test_mask_of_an_absent_bone_is_empty(self):
        scene = gltf.load_gltf(_skeleton_glb())
        human = hm.Humanoid.from_scene(scene)
        assert human.mask('jaw') == frozenset()

    def test_mask_takes_in_unnamed_children(self):
        # The socket under RightHand is not a bone, and rides with the hand.
        scene = gltf.load_gltf(_skeleton_glb())
        human = hm.Humanoid.from_scene(scene)
        assert 18 in human.mask('rightHand')

    def test_a_cycle_in_the_hierarchy_terminates(self):
        human = hm.Humanoid({'hips': 0}, children={0: [1], 1: [0]})
        assert human.mask('hips') == frozenset({0, 1})


class TestPose:
    def test_bone_world_positions(self):
        scene = gltf.load_gltf(_skeleton_glb())
        human = hm.Humanoid.from_scene(scene)
        # Each node is 0.1 up from its parent; the head is five deep.
        assert np.allclose(human.position('head'), [0.0, 0.5, 0.0])
        assert human.position('jaw') is None


class TestEdges:
    def test_a_finger_with_no_segment(self):
        assert hm.bone_for_name('LeftThumb') is None
        assert hm.bone_for_name('index_9_l') is None

    def test_an_extension_with_no_usable_bone_map(self):
        ext = {'VRMC_vrm': {'specVersion': '1.0', 'humanoid': {}}}
        scene = gltf.load_gltf(_skeleton_glb(ext))
        human = hm.Humanoid.from_scene(scene)
        assert human.bones['head'] == 4          # read from the names instead

    def test_an_extension_naming_bones_that_are_not_bones(self):
        ext = {'VRMC_vrm': {'humanoid': {'humanBones': {'tail': {'node': 5}}}}}
        scene = gltf.load_gltf(_skeleton_glb(ext))
        assert hm.Humanoid.from_scene(scene).bones['head'] == 4

    def test_iterating_names_the_bones(self):
        scene = gltf.load_gltf(_skeleton_glb())
        human = hm.Humanoid.from_scene(scene)
        assert set(human) == set(human.bones)

    def test_a_bone_outside_the_hierarchy_has_no_position(self):
        human = hm.Humanoid({'hips': 99}, roots=[0], transforms={})
        assert human.position('hips') is None


class TestRigFamilies:
    #: An Unreal mannequin's skeleton, which is what Quaternius and most
    #: engine-ready content is rigged to.
    UNREAL = ['root', 'pelvis', 'spine_01', 'spine_02', 'spine_03', 'neck_01',
              'head', 'clavicle_l', 'upperarm_l', 'lowerarm_l', 'hand_l',
              'clavicle_r', 'upperarm_r', 'lowerarm_r', 'hand_r',
              'thigh_l', 'calf_l', 'foot_l', 'ball_l',
              'thigh_r', 'calf_r', 'foot_r', 'ball_r',
              'index_01_l', 'index_02_l', 'index_03_l', 'thumb_01_l']

    def bones(self, names):
        return hm.bones_by_name(dict(enumerate(names)))

    def test_the_spine_is_read_from_the_bottom(self):
        bones = self.bones(self.UNREAL)
        assert bones['hips'] == self.UNREAL.index('pelvis')
        assert bones['spine'] == self.UNREAL.index('spine_01')
        assert bones['chest'] == self.UNREAL.index('spine_02')
        assert bones['upperChest'] == self.UNREAL.index('spine_03')

    def test_the_rest_still_comes_from_the_names(self):
        bones = self.bones(self.UNREAL)
        assert bones['leftUpperArm'] == self.UNREAL.index('upperarm_l')
        assert bones['leftToes'] == self.UNREAL.index('ball_l')
        assert bones['leftIndexIntermediate'] == self.UNREAL.index('index_02_l')
        assert bones['leftThumbMetacarpal'] == self.UNREAL.index('thumb_01_l')

    def test_a_whole_unreal_rig_resolves(self):
        assert not (hm.REQUIRED_BONES - set(self.bones(self.UNREAL)))

    def test_mixamo_still_counts_from_zero(self):
        # Spine1 is the *second* spine bone; without the family signature
        # nothing here may read a numbered spine as Unreal's.
        names = ['mixamorig:Hips', 'mixamorig:Spine', 'mixamorig:Spine1',
                 'mixamorig:Spine2', 'mixamorig:Neck', 'mixamorig:Head']
        bones = self.bones(names)
        assert bones['spine'] == 1 and bones['chest'] == 2
        assert bones['upperChest'] == 3

    def test_a_family_needs_all_of_its_signature(self):
        # A pelvis and a numbered spine, but no clavicles: not the family.
        bones = self.bones(['pelvis', 'spine_01', 'spine_02'])
        assert bones.get('spine') is None
        assert bones['chest'] == 1

    def test_namespaced_names_still_match_the_family(self):
        names = ['rig:pelvis', 'rig:spine_01', 'rig:spine_02', 'rig:spine_03',
                 'rig:clavicle_l', 'rig:clavicle_r']
        assert self.bones(names)['spine'] == 1
