"""A body's pose between the world's quaternions and a scene Transform (:mod:`OpenGLContext.physics.poses`)."""
import numpy as np
import pytest

from OpenGLContext.physics.poses import quat_to_vrml_rotation, vrml_rotation_to_quat, write_pose, write_poses
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


def test_poses_written_in_bulk_land_on_each_transform_and_are_heard():
    from pydispatch import dispatcher
    from vrml import protofunctions

    nodes = [Transform() for _ in range(3)]
    heard = []

    def listener(sender, value=None, **named):
        heard.append((sender, tuple(np.round(value, 6))))

    field = protofunctions.getField(nodes[1], 'translation')
    dispatcher.connect(listener, signal=('set', field), sender=nodes[1], weak=False)
    try:
        positions = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]])
        turns = np.array([[0.0, 1.0, 0.0, 0.5], [1.0, 0.0, 0.0, 1.0], [0.0, 0.0, 1.0, 1.5]])
        write_poses(nodes, positions, turns)
    finally:
        dispatcher.disconnect(listener, signal=('set', field), sender=nodes[1], weak=False)
    for node, place, turn in zip(nodes, positions, turns, strict=True):
        assert np.allclose(node.translation, place)
        assert np.allclose(node.rotation, turn)
        assert node.translation.dtype == np.float32 and node.translation.shape == (3,)
    assert heard == [(nodes[1], (4.0, 5.0, 6.0))]


def test_a_transform_whose_translation_field_works_differently_is_set_through_it():
    class Offset(Transform):
        pass

    from vrml import field as vrml_field, protofunctions

    node = Offset()
    declared = protofunctions.getField(node, 'translation')

    class Doubled(type(declared)):
        def fset(self, client, value, notify=True):
            return super().fset(client, np.asarray(value) * 2.0, notify)

    doubled = Doubled('translation', 1, (0.0, 0.0, 0.0))
    Offset.translation = doubled
    try:
        write_poses([node], np.array([[1.0, 1.0, 1.0]]), np.array([[0.0, 1.0, 0.0, 0.0]]))
        assert np.allclose(node.translation, (2.0, 2.0, 2.0))
    finally:
        del Offset.translation
    assert isinstance(declared, vrml_field.Field)
