"""A figure with a coarser mesh for when it is far away.

Pure Python/numpy -- no GL. What a level has to be is the *same body*: posed by
the skeleton that is already being posed, drawn in the same place, and refused
outright where it is skinned to something else.
"""
import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.character.levels import levels_match
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.loaders.gltf import load_gltf, parse_gltf
from OpenGLContext.scenegraph.lod import LOD
from tests.unit._character_assets import character_glb, skinned_bar_glb


@pytest.fixture(scope='module')
def fine():
    return parse_gltf(skinned_bar_glb(rings=8))


@pytest.fixture(scope='module')
def coarse():
    return parse_gltf(skinned_bar_glb(rings=3))


def _model(document):
    return CharacterModel(load_gltf(document=document))


def _lods(node, seen=None):
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return []
    seen.add(id(node))
    found = [node] if isinstance(node, LOD) else []
    children = list(getattr(node, 'children', None) or ())
    children += list(getattr(node, 'level', None) or ())
    for child in children:
        found += _lods(child, seen)
    return found


class TestTakingALevel:
    def test_a_coarser_mesh_of_the_same_rig_is_taken(self, fine, coarse):
        model = _model(fine)

        assert model.add_level(None, 20.0, document=coarse) is True
        assert len(_lods(model.group)) == len(model.mixer.skins)

    def test_a_different_skeleton_is_refused(self, fine):
        """A coarse mesh posed by the wrong bones is worse than a fine one."""
        model = _model(fine)
        other = parse_gltf(character_glb())

        assert model.add_level(None, 20.0, document=other) is False
        assert _lods(model.group) == []

    def test_the_levels_are_told_apart_by_their_joint_names(self, fine, coarse):
        assert levels_match(load_gltf(document=fine), load_gltf(document=coarse))
        assert not levels_match(load_gltf(document=fine),
                                load_gltf(document=parse_gltf(character_glb())))

    def test_the_finer_level_is_the_one_named_first(self, fine, coarse):
        model = _model(fine)
        model.add_level(None, 20.0, document=coarse)

        node = _lods(model.group)[0]
        near = _skinned_under(node.level[0])
        far = _skinned_under(node.level[1])

        assert len(near[0].positions) > len(far[0].positions)


def _skinned_under(node, seen=None):
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return []
    seen.add(id(node))
    found = []
    if getattr(node, 'skin_joints', None) is not None:
        found.append(node)
    for name in ('children', 'geometry', 'level'):
        value = getattr(node, name, None)
        if value is None:
            continue
        for child in (value if isinstance(value, (list, tuple)) else [value]):
            found += _skinned_under(child, seen)
    return found


class TestOnePoseForEveryLevel:
    def test_both_levels_are_posed_by_the_one_skeleton(self, fine, coarse):
        """The point of a level: the geometry differs and nothing else does."""
        model = _model(fine)
        before = [len(skin.meshes) for skin in model.mixer.skins]
        model.add_level(None, 20.0, document=coarse)

        model.play(sorted(model.clips)[0])
        model.update(0.5)

        assert [len(skin.meshes) for skin in model.mixer.skins] == \
            [count + 1 for count in before], 'the coarse meshes joined the skin'
        for skin in model.mixer.skins:
            assert len(skin.meshes) >= 2
            posed = [mesh._skin_matrices for mesh in skin.meshes]
            assert all(matrices is not None for matrices in posed)
            for matrices in posed[1:]:
                assert np.allclose(matrices, posed[0])

    def test_the_levels_share_one_range_of_the_joint_palette(self, fine, coarse):
        """They are handed the same matrices, so there is one range to hold."""
        model = _model(fine)
        model.add_level(None, 20.0, document=coarse)

        for skin in model.mixer.skins:
            peers = [getattr(mesh, '_palette_peer', None)
                     for mesh in skin.meshes[1:]]
            assert peers and all(peer is skin.meshes[0] for peer in peers)

    def test_posing_costs_what_one_level_costs(self, fine, coarse):
        """A second level must not double the animation work."""
        plain = _model(fine)
        plain.play(sorted(plain.clips)[0])
        levelled = _model(fine)
        levelled.add_level(None, 20.0, document=coarse)
        levelled.play(sorted(levelled.clips)[0])

        assert len(levelled.mixer._skin_plans) == len(plain.mixer._skin_plans)
