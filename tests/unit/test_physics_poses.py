"""A body's pose between the world's quaternions and a scene Transform (:mod:`OpenGLContext.physics.poses`)."""
import numpy as np
import pytest

from OpenGLContext.physics.poses import quat_to_vrml_rotation, vrml_rotation_to_quat, write_pose
from OpenGLContext.scenegraph.basenodes import Transform

pytestmark = pytest.mark.engines('omi', 'jolt')


def test_a_rotation_survives_the_round_trip():
    rotation = quat_to_vrml_rotation(vrml_rotation_to_quat((0, 1, 0, 1.2)))
    assert np.allclose(rotation[:3], (0, 1, 0), atol=1e-9)
    assert rotation[3] == pytest.approx(1.2, abs=1e-9)


def test_a_rotation_of_nothing_has_the_default_axis():
    assert np.allclose(quat_to_vrml_rotation((0.0, 0.0, 0.0, 1.0)), (0.0, 1.0, 0.0, 0.0))


def test_a_pose_is_written_onto_the_transform():
    node = Transform()
    write_pose(node, np.array([1.0, 2.0, 3.0]), np.array([0.0, 0.0, 1.0, 0.5]))
    assert np.allclose(node.translation, (1.0, 2.0, 3.0))
    assert np.allclose(node.rotation, (0.0, 0.0, 1.0, 0.5))
