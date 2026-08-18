"""Unit tests for hanging things on a rig's attachment points."""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.character import attachment as at
from OpenGLContext.character.humanoid import Humanoid
from OpenGLContext.loaders import gltf
from OpenGLContext.scenegraph.transform import Transform

from ._character_assets import GRIP, held_glb, skeleton_glb


class TestSockets:
    def test_finds_the_named_points(self):
        scene = gltf.load_gltf(skeleton_glb())
        found = at.sockets(scene)
        assert set(found) == {'grip'}
        assert found['grip'] is scene.node_transforms[GRIP]

    def test_another_prefix(self):
        scene = gltf.load_gltf(skeleton_glb())
        assert set(at.sockets(scene, prefix='weapon_')) == {'sight'}

    def test_a_model_with_none(self):
        names = ['bone%d' % i for i in range(19)]
        scene = gltf.load_gltf(skeleton_glb(names=names))
        assert at.sockets(scene) == {}


class TestAttach:
    def test_adds_a_child(self):
        parent, held = Transform(), Transform()
        assert at.attach(parent, held) is held
        assert list(parent.children) == [held]

    def test_attaching_twice_holds_one(self):
        parent, held = Transform(), Transform()
        at.attach(parent, held)
        at.attach(parent, held)
        assert list(parent.children) == [held]

    def test_detach_removes_it(self):
        parent, held = Transform(), Transform()
        at.attach(parent, held)
        assert at.detach(parent, held) is True
        assert list(parent.children) == []

    def test_detaching_what_is_not_there(self):
        parent, held = Transform(), Transform()
        assert at.detach(parent, held) is False

    def test_an_attachment_rides_with_the_joint(self):
        scene = gltf.load_gltf(skeleton_glb())
        human = Humanoid.from_scene(scene)
        held = Transform()
        at.attach(human.transform('rightHand'), held)
        # Hips, spine, chest, upper arm, lower arm, hand: six joints, 0.1 each.
        assert np.allclose(human.position('rightHand'), [0.0, 0.6, 0.0])
        human.transform('rightHand').translation = (0.0, 0.5, 0.0)
        assert np.allclose(human.position('rightHand'), [0.0, 1.0, 0.0])


class TestMounting:
    """A model that says where it is held, and being taken at its word."""

    def test_the_point_it_declares_lands_on_the_origin(self):
        scene = gltf.load_gltf(held_glb(translation=(0.0, 0.1, 0.3)))
        mount = at.mounted(scene)
        assert mount is not scene.group
        assert np.allclose(mount.translation, (0.0, -0.1, -0.3))
        assert list(mount.children) == [scene.group]

    def test_a_point_deeper_in_composes(self):
        scene = gltf.load_gltf(held_glb(translation=(0.0, 0.1, 0.3), under=True))
        assert np.allclose(at.mounted(scene).translation, (0.0, -0.1, -0.3))

    def test_a_turned_point_turns_the_model(self):
        half = np.sin(np.pi / 4)
        scene = gltf.load_gltf(held_glb(translation=(0.0, 0.0, 0.0),
                                        rotation=(0.0, half, 0.0, half)))
        mount = at.mounted(scene)
        assert np.allclose(abs(np.asarray(mount.rotation[:3])), (0, 1, 0))
        assert abs(mount.rotation[3]) == pytest.approx(np.pi / 2, abs=1e-6)

    def test_a_point_that_is_only_offset_carries_no_rotation(self):
        scene = gltf.load_gltf(held_glb(translation=(0.0, 0.1, 0.3)))
        assert at.mounted(scene).rotation[3] == 0.0

    def test_a_model_that_says_nothing_is_mounted_as_it_is(self):
        scene = gltf.load_gltf(held_glb(socket='Handle'))
        assert at.mounted(scene) is scene.group

    def test_a_point_it_does_not_declare(self):
        scene = gltf.load_gltf(held_glb())
        assert at.mounted(scene, 'back') is scene.group

    def test_the_name_is_the_point_it_mounts_on(self):
        scene = gltf.load_gltf(held_glb(socket='socket_back'))
        assert at.mounted(scene, 'grip') is scene.group
        assert at.mounted(scene, 'back') is not scene.group
