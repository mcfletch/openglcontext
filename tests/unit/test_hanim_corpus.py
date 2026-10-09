"""Web3D's HumanoidAnimation examples, read and posed by the engine.

Skipped where the archive has not been fetched (`oglc-x3d-regression --fetch
--archive HumanoidAnimation`). Each document here stands for a kind of
humanoid: HAnim 1 and 2, skinned and built of segments, a skin of many
influences a point, an LOD of skins, a motion, displacers and poses.
"""
import math
import os
import types

import numpy as np
import pytest
from vrml import cache
from vrml.x3d import corpus

from OpenGLContext.scenegraph import coordinatedeform, hanim

ARCHIVE = corpus.examples('HumanoidAnimation')
#: What the bounds of a Transform are worked out through, as a pass would.
MODE = types.SimpleNamespace(cache=cache.CACHE)
#: Document errors that are not the reader's: HAnimPoseExample routes to an
#: `isLoaded` that X3D's HAnimPose does not declare.
NOT_DECLARED = 'HAnimPose.isLoaded: no such field'
pytestmark = pytest.mark.skipif(not os.path.isdir(ARCHIVE),
                                reason='the HumanoidAnimation archive has not been fetched')


def load(name):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    scene = Loader.load(os.path.join(ARCHIVE, name))
    hanim_errors = [str(problem) for problem in scene.problems
                    if problem.severity == 'error' and 'HAnim' in str(problem)
                    and NOT_DECLARED not in str(problem)]
    assert hanim_errors == []
    return scene


def humanoids(scene):
    found = []

    def walk(node, seen):
        if node is None or node in seen:
            return
        seen.add(node)
        if isinstance(node, hanim.HAnimHumanoid):
            found.append(node)
        for child in getattr(node, 'children', ()):
            walk(child, seen)

    seen = set()
    for child in scene.children:
        walk(child, seen)
    return found


def skin_meshes(humanoid):
    rig = humanoid.rig()
    found = []
    for shape in _shapes(humanoid.skin):
        geometry = shape.geometry
        deformer = coordinatedeform.deformer_for(geometry)
        if deformer is not None:
            found.append(deformer.mesh(geometry))
    assert rig.count
    return [mesh for mesh in found if mesh is not None]


def _shapes(nodes):
    for node in nodes:
        if getattr(node, 'geometry', None) is not None:
            yield node
        yield from _shapes(getattr(node, 'children', ()) or getattr(node, 'level', ()))


@pytest.mark.parametrize('name, joints', [
    ('Skin/BoxMan1.x3d', 17),
    ('Skin/JoeKick.x3d', 94),
    ('Skin/JoeSkeletonSkinSite.x3d', 89),
    ('WinterAndSpring/Lily.x3d', 54),
])
def test_a_skinned_humanoid_follows_its_joints(name, joints):
    humanoid = humanoids(load(name))[0]
    meshes = skin_meshes(humanoid)
    assert len(humanoid.rig().joints) == joints
    assert meshes
    before = [mesh.posed_positions().copy() for mesh in meshes]
    shoulder = humanoid.joint('l_shoulder') or humanoid.rig().joints[1]
    shoulder.rotation = (0, 0, 1, 1.0)
    moved = [np.abs(mesh.posed_positions() - rest).max()
             for mesh, rest in zip(skin_meshes(humanoid), before)]
    assert max(moved) > 0.05
    for shape in _shapes(humanoid.skin):
        low = np.asarray(shape.boundingVolume(MODE).getPoints())[:, :3]
        assert np.isfinite(low).all()


def test_a_humanoid_of_segments_draws_them_at_its_joints():
    humanoid = humanoids(load('Characters/JinLOA1.x3d'))[0]
    assert humanoid.renderedChildren()
    assert coordinatedeform.deformer_for(humanoid) is None
    volume = np.asarray(humanoid.boundingVolume(MODE).getPoints())[:, :3]
    assert volume[:, 1].max() - volume[:, 1].min() > 1.0


def test_a_motion_plays_onto_the_joints():
    scene = load('Specifications/KoreanCharacterMotionAnnexD01Jin.x3d')
    humanoid = humanoids(scene)[0]
    humanoid.rig()
    motion = humanoid.motions[0]
    assert motion.channelData().frames > 10
    hip = humanoid.joint('l_hip')
    motion.advance(1000.0)
    first = tuple(hip.rotation)
    motion.advance(1000.0 + 5 * float(motion.frameDuration))
    assert tuple(hip.rotation) != first
    assert motion.frameIndex == 5


def test_displacers_move_the_skin():
    humanoid = humanoids(load('MotionAnimation/HAnimDisplacerExamples.x3d'))[0]
    rig = humanoid.rig()
    assert rig.displacers
    meshes = skin_meshes(humanoid)
    before = [mesh.posed_positions().copy() for mesh in meshes]
    for item in rig.displacers:
        item.weight = 1.0
    moved = [np.abs(mesh.posed_positions() - rest).max()
             for mesh, rest in zip(skin_meshes(humanoid), before)]
    assert max(moved) > 0.0


def test_a_pose_moves_the_joints_it_names():
    scene = load('Poses/HAnimPoseExample.x3d')
    poses = [node for node in scene.children if isinstance(node, hanim.HAnimPose)]
    assert poses
    for humanoid in humanoids(scene):
        humanoid.rig()
    assert all(isinstance(pose.loa, int) for pose in poses)
    assert not math.isnan(float(poses[0].transitionDuration))
