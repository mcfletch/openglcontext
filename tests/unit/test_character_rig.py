"""Unit tests for the array form of a document's node hierarchy.

Pure Python/numpy -- no GL. :class:`OpenGLContext.character.rig.Rig` is the
skeleton laid out as arrays, and what it computes has to agree with the
node-at-a-time walk in :func:`OpenGLContext.loaders.gltf.animation.compute_world_matrices`
to the last few bits, because the two are alternative spellings of one answer.
"""
import math

import numpy as np
import pytest

from OpenGLContext.character.rig import Rig
from OpenGLContext.loaders.gltf.animation import compute_world_matrices
from OpenGLContext.scenegraph.transform import Transform


def _chain(depth, branch=1):
    """A skeleton `depth` deep where every node has `branch` children."""
    children, transforms = {}, {}
    order = [0]
    transforms[0] = Transform(translation=(0.0, 0.1, 0.0))
    next_index = 1
    frontier = [0]
    for level in range(depth - 1):
        following = []
        for parent in frontier:
            kids = []
            for b in range(branch):
                index = next_index
                next_index += 1
                transforms[index] = Transform(
                    translation=(0.1 * b, 0.2 + level, 0.3),
                    rotation=(0.0, 0.0, 1.0, 0.4 * (level + 1)),
                    scale=(1.0, 1.0 + 0.1 * b, 1.0))
                kids.append(index)
                following.append(index)
                order.append(index)
            children[parent] = kids
        frontier = following
    return [0], children, transforms


def _random_pose(rig, seed=7):
    """A pose with every path moved off its rest value."""
    rng = np.random.default_rng(seed)
    translation = rng.normal(size=(rig.n, 3))
    scale = 0.5 + rng.random((rig.n, 3))
    rotation = rng.normal(size=(rig.n, 4))
    rotation /= np.linalg.norm(rotation, axis=1, keepdims=True)
    return translation, rotation, scale


def _walked(rig, roots, children, translation, rotation, scale):
    """The same pose written onto Transforms and walked one node at a time."""
    from OpenGLContext.loaders.gltf.animation import quat_xyzw_to_vrml
    for slot in range(rig.n):
        xform = rig.transforms[slot]
        xform.translation = tuple(float(v) for v in translation[slot])
        xform.scale = tuple(float(v) for v in scale[slot])
        xform.rotation = quat_xyzw_to_vrml(rotation[slot])
    return compute_world_matrices(roots, children,
                                  {int(i): rig.transforms[s]
                                   for s, i in enumerate(rig.indices)})


class TestLayout:
    def test_every_parent_comes_before_its_children(self):
        """Composing world = local @ parent in slot order needs that order."""
        roots, children, transforms = _chain(4, branch=3)
        rig = Rig(roots, children, transforms)

        for slot in range(rig.n):
            assert rig.parent[slot] < slot

    def test_covers_every_node_reachable_from_a_root(self):
        roots, children, transforms = _chain(4, branch=2)
        rig = Rig(roots, children, transforms)

        assert rig.n == len(transforms)
        assert sorted(int(i) for i in rig.indices) == sorted(transforms)

    def test_a_node_no_root_reaches_is_left_out(self):
        """Matching the walk, which only visits what a root leads to."""
        roots, children, transforms = _chain(2)
        transforms[99] = Transform()

        rig = Rig(roots, children, transforms)

        assert 99 not in rig.slot_of

    def test_a_cycle_in_the_hierarchy_is_visited_once(self):
        """Content is not always well formed; a loop must not hang the load."""
        transforms = {0: Transform(), 1: Transform()}
        rig = Rig([0], {0: [1], 1: [0]}, transforms)

        assert rig.n == 2

    def test_several_roots_make_one_rig(self):
        transforms = {0: Transform(), 1: Transform(), 2: Transform()}
        rig = Rig([0, 2], {0: [1]}, transforms)

        assert rig.n == 3
        assert list(rig.parent[[rig.slot_of[0], rig.slot_of[2]]]) == [-1, -1]


class TestRestPose:
    def test_rest_reads_the_nodes_own_transform(self):
        transforms = {0: Transform(translation=(1.0, 2.0, 3.0),
                                   scale=(2.0, 2.0, 2.0),
                                   rotation=(0.0, 0.0, 1.0, math.pi / 2))}
        rig = Rig([0], {}, transforms)

        assert list(rig.rest_translation[0]) == [1.0, 2.0, 3.0]
        assert list(rig.rest_scale[0]) == [2.0, 2.0, 2.0]
        assert rig.rest_rotation[0][2] == pytest.approx(math.sin(math.pi / 4))
        assert rig.rest_rotation[0][3] == pytest.approx(math.cos(math.pi / 4))

    def test_rest_pose_hands_out_copies(self):
        """A caller poses into what it is given; the rest values must survive."""
        roots, children, transforms = _chain(3)
        rig = Rig(roots, children, transforms)

        translation, rotation, scale = rig.rest_pose()
        translation[0][0] = 999.0

        assert rig.rest_translation[0][0] != 999.0


class TestWorldMatrices:
    def test_matches_the_node_at_a_time_walk_at_rest(self):
        roots, children, transforms = _chain(4, branch=2)
        rig = Rig(roots, children, transforms)

        got = rig.world_matrices(*rig.rest_pose())
        want = compute_world_matrices(roots, children, transforms)

        for slot, index in enumerate(rig.indices):
            assert np.allclose(got[slot], want[int(index)], atol=1e-9)

    def test_matches_the_node_at_a_time_walk_when_posed(self):
        roots, children, transforms = _chain(4, branch=3)
        rig = Rig(roots, children, transforms)
        pose = _random_pose(rig)

        got = rig.world_matrices(*pose)
        want = _walked(rig, roots, children, *pose)

        # The walk composes single-precision matrices out of pyvrml97's
        # rotMatrix, so agreement is to single precision; the rig keeps double
        # throughout and is the closer of the two to the pose it was handed.
        for slot, index in enumerate(rig.indices):
            assert np.allclose(got[slot], want[int(index)], atol=1e-6), slot

    def test_a_baked_matrix_node_keeps_its_matrix(self):
        """A node carrying a composed matrix is not driven by TRS, and the
        rig must use the matrix rather than the fields underneath it."""
        baked = np.array([[2.0, 0, 0, 0], [0, 2.0, 0, 0], [0, 0, 2.0, 0],
                          [5.0, 6.0, 7.0, 1.0]])
        parent = Transform()
        parent._forward = baked
        child = Transform(translation=(1.0, 0.0, 0.0))
        rig = Rig([0], {0: [1]}, {0: parent, 1: child})

        worlds = rig.world_matrices(*rig.rest_pose())

        assert np.allclose(worlds[rig.slot_of[0]], baked)
        assert np.allclose(worlds[rig.slot_of[1]][3, :3], [7.0, 6.0, 7.0])

    def test_a_node_with_no_transform_is_the_identity(self):
        rig = Rig([0], {0: [1]}, {1: Transform(translation=(1.0, 2.0, 3.0))})

        worlds = rig.world_matrices(*rig.rest_pose())

        assert np.allclose(worlds[rig.slot_of[0]], np.eye(4))
        assert np.allclose(worlds[rig.slot_of[1]][3, :3], [1.0, 2.0, 3.0])


class TestWriteBack:
    def test_a_node_holding_something_foreign_is_written(self):
        """A weapon hung on a hand needs that hand's Transform kept current."""
        from OpenGLContext.character.attachment import attach

        roots, children, transforms = _chain(3)
        rig = Rig(roots, children, transforms)
        hand = rig.indices[-1]
        attach(transforms[int(hand)], Transform())

        assert rig.slot_of[int(hand)] in rig.exposed_slots()

    def test_every_joint_down_to_the_one_holding_it_is_written(self):
        """The renderer reaches the weapon by walking, so the whole chain has
        to say where the pose put it."""
        from OpenGLContext.character.attachment import attach

        roots, children, transforms = _chain(4)
        rig = Rig(roots, children, transforms)
        attach(transforms[int(rig.indices[-1])], Transform())

        assert rig.exposed_slots() == frozenset(range(rig.n))

    def test_a_joint_with_only_joints_under_it_is_not(self):
        roots, children, transforms = _chain(3)
        rig = Rig(roots, children, transforms)

        assert rig.slot_of[0] not in rig.exposed_slots()

    def test_the_exposed_set_notices_something_new_hung_on(self):
        from OpenGLContext.character.attachment import attach

        roots, children, transforms = _chain(3)
        rig = Rig(roots, children, transforms)
        before = rig.exposed_slots()

        attach(transforms[int(rig.indices[1])], Transform())

        assert rig.exposed_slots() != before

    def test_a_joint_rearranged_behind_the_rigs_back_needs_telling(self):
        """The set is kept against a counter the attachment API bumps, so a
        caller that goes around it says when it has."""
        roots, children, transforms = _chain(3)
        rig = Rig(roots, children, transforms)
        rig.exposed_slots()

        transforms[int(rig.indices[1])].children = [Transform()]
        rig.invalidate_exposed()

        assert rig.slot_of[int(rig.indices[1])] in rig.exposed_slots()
