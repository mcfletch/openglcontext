"""The VRML97 NURBS extension's CoordinateDeformer: points moved through a NURBS volume.

The node's fields and what each means are in
`specs/vrml97-nurbs-coordinatedeformer.md`.
"""
import logging

import numpy as np
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.coordinatedeformer import (
    CoordinateDeformer, Lattice, lattice_of, volume_points,
)

#: The corners of the unit cube, u fastest, then v, then w.
CUBE = [[float(i), float(j), float(k)] for k in range(2) for j in range(2) for i in range(2)]
LINEAR = [0.0, 0.0, 1.0, 1.0]

POINTS = [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5], [1.0, 1.0, 1.0], [0.25, 0.75, 0.5]]


def cube(control=CUBE, weights=None):
    return Lattice(np.asarray(control, np.float64).reshape(2, 2, 2, 3),
                   (np.asarray(LINEAR),) * 3, (1, 1, 1),
                   None if weights is None else np.asarray(weights, np.float64).reshape(2, 2, 2))


def deformer(**fields):
    named = dict(
        uDimension=2, vDimension=2, wDimension=2, uKnot=LINEAR, vKnot=LINEAR, wKnot=LINEAR,
        controlPoint=CUBE,
        inputCoord=[basenodes.Coordinate(point=POINTS)],
        outputCoord=[basenodes.Coordinate()])
    named.update(fields)
    return CoordinateDeformer(**named)


def output(node, index=0):
    return np.asarray(node.outputCoord[index].point, np.float64).reshape(-1, 3)


class TestTheVolume:
    def test_a_cube_of_its_own_corners_leaves_points_where_they_are(self):
        assert np.allclose(volume_points(POINTS, cube()), POINTS)

    def test_the_first_index_runs_along_u(self):
        control = np.asarray(CUBE)
        control[1] = [5.0, 0.0, 0.0]    # u=1, v=0, w=0
        assert np.allclose(volume_points([[1.0, 0.0, 0.0]], cube(control)), [[5.0, 0.0, 0.0]])
        control = np.asarray(CUBE)
        control[4] = [0.0, 0.0, 7.0]    # u=0, v=0, w=1
        assert np.allclose(volume_points([[0.0, 0.0, 1.0]], cube(control)), [[0.0, 0.0, 7.0]])

    def test_a_moved_corner_moves_the_middle_by_an_eighth(self):
        control = np.asarray(CUBE)
        control[7] += [8.0, 0.0, 0.0]
        assert np.allclose(volume_points([[0.5, 0.5, 0.5]], cube(control)), [[1.5, 0.5, 0.5]])

    def test_a_weight_draws_the_volume_towards_its_point(self):
        weights = [1.0] * 7 + [9.0]
        found = volume_points([[0.5, 0.5, 0.5]], cube(weights=weights))
        # eight corners of basis 1/8 each: (sum of the others + 9 * corner) / 16
        expected = (np.asarray(CUBE)[:7].sum(0) + 9.0 * np.asarray(CUBE)[7]) / 16.0
        assert np.allclose(found, [expected])

    def test_a_quadratic_direction(self):
        control = np.zeros((2, 2, 3, 3))
        control[..., 0, 0], control[..., 1, 0], control[..., 2, 0] = 0.0, 4.0, 2.0
        lattice = Lattice(control, (np.asarray([0.0, 0, 0, 1, 1, 1]),
                                    np.asarray(LINEAR), np.asarray(LINEAR)), (2, 1, 1), None)
        found = volume_points([[0.5, 0.3, 0.9]], lattice)
        assert np.allclose(found[0, 0], 0.25 * 0.0 + 0.5 * 4.0 + 0.25 * 2.0)

    def test_a_parameter_outside_the_knots_is_held_at_their_end(self):
        found = volume_points([[-3.0, 0.5, 9.0]], cube())
        assert np.allclose(found, [[0.0, 0.5, 1.0]])

    def test_no_points_give_none(self):
        assert volume_points(np.zeros((0, 3)), cube()).shape == (0, 3)


class TestTheLattice:
    def test_the_fields_of_a_node(self):
        found = lattice_of(deformer())
        assert isinstance(found, Lattice)
        assert found.control.shape == (2, 2, 2, 3)
        assert found.degrees == (1, 1, 1)
        assert found.weights is None

    def test_the_control_points_are_w_then_v_then_u(self):
        node = deformer(uDimension=3, uOrder=3, uKnot=[0, 0, 0, 1, 1, 1],
                        controlPoint=[[i, j, k] for k in range(2) for j in range(2)
                                      for i in range(3)])
        found = lattice_of(node)
        assert found.control.shape == (2, 2, 3, 3)
        assert found.control[1, 0, 2].tolist() == [2.0, 0.0, 1.0]
        assert found.degrees == (2, 1, 1)

    @pytest.mark.parametrize('fields, reason', [
        (dict(controlPoint=[]), 'has no control points'),
        (dict(uDimension=6, vDimension=6, wDimension=6),
         'has 8 control points for a 6 by 6 by 6 lattice'),
        (dict(uKnot=[0, 1]), 'has 2 u knots, where 2 control points at order 2 need 4'),
        (dict(vOrder=3), 'has 2 v control points, fewer than its order of 3'),
        (dict(wKnot=[1, 1, 0, 0]), 'has w knots that decrease'),
        (dict(wKnot=[1, 1, 1, 1]), 'has w knots that span nothing'),
        (dict(uOrder=1, uKnot=[0, 0, 1]), 'has a u order of 1; the least is 2'),
    ])
    def test_fields_that_describe_no_volume(self, fields, reason):
        assert lattice_of(deformer(**fields)) == reason

    def test_weights_of_another_count_are_left_out(self):
        assert lattice_of(deformer(weight=[1.0, 2.0])).weights is None
        assert lattice_of(deformer(weight=[2.0] * 8)).weights.shape == (2, 2, 2)

    def test_a_weight_that_is_not_positive_leaves_them_all_out(self):
        assert lattice_of(deformer(weight=[1.0] * 7 + [0.0])).weights is None


class TestTheNode:
    def test_the_output_is_the_input_through_the_volume(self):
        control = np.asarray(CUBE) * 2.0
        node = deformer(controlPoint=control)
        node.deform()
        assert np.allclose(output(node), np.asarray(POINTS) * 2.0)

    def test_drawing_the_group_deforms_it_first(self):
        node = deformer(children=[basenodes.Shape()])
        assert len(node.renderedChildren()) == 1
        assert np.allclose(output(node), POINTS)

    def test_bounding_the_group_deforms_it_first(self):
        geometry = basenodes.PointSet(coord=basenodes.Coordinate())
        node = deformer(outputCoord=[geometry.coord],
                        children=[basenodes.Shape(geometry=geometry)])
        node.boundingVolume(None)
        assert np.allclose(output(node), POINTS)

    def test_a_control_point_set_moves_the_output(self):
        node = deformer()
        node.deform()
        node.controlPoint = np.asarray(CUBE) + [0.0, 3.0, 0.0]
        assert np.allclose(output(node), np.asarray(POINTS) + [0.0, 3.0, 0.0])

    def test_an_input_point_set_moves_the_output(self):
        node = deformer()
        node.deform()
        node.inputCoord[0].point = [[1.0, 0.0, 0.0]]
        assert np.allclose(output(node), [[1.0, 0.0, 0.0]])

    def test_a_weight_set_moves_the_output(self):
        node = deformer()
        node.deform()
        node.weight = [1.0] * 7 + [9.0]
        assert not np.allclose(output(node)[1], POINTS[1])

    def test_each_input_has_its_output(self):
        node = deformer(
            inputCoord=[basenodes.Coordinate(point=POINTS[:2]),
                        basenodes.Coordinate(point=POINTS[2:])],
            outputCoord=[basenodes.Coordinate(), basenodes.Coordinate()])
        node.deform()
        assert np.allclose(output(node, 0), POINTS[:2])
        assert np.allclose(output(node, 1), POINTS[2:])

    def test_a_null_entry_is_passed_over(self):
        from vrml import node as vrmlnode
        untouched = basenodes.Coordinate(point=[[7.0, 7.0, 7.0]])
        node = deformer(
            inputCoord=[vrmlnode.NULL, basenodes.Coordinate(point=POINTS)],
            outputCoord=[untouched, basenodes.Coordinate()])
        node.deform()
        assert np.allclose(untouched.point, [[7.0, 7.0, 7.0]])
        assert np.allclose(output(node, 1), POINTS)

    def test_an_input_list_set_is_followed(self):
        node = deformer()
        node.deform()
        replacement = basenodes.Coordinate(point=[[1.0, 1.0, 0.0]])
        node.inputCoord = [replacement]
        assert np.allclose(output(node), [[1.0, 1.0, 0.0]])
        replacement.point = [[0.0, 1.0, 0.0]]
        assert np.allclose(output(node), [[0.0, 1.0, 0.0]])

    def test_an_input_transform_moves_the_points_through_the_volume(self):
        carrier = basenodes.Transform(translation=(0.5, 0.0, 0.0))
        control = np.asarray(CUBE) * [10.0, 1.0, 1.0]
        node = deformer(controlPoint=control, inputTransform=[carrier],
                        inputCoord=[basenodes.Coordinate(point=[[0.0, 0.0, 0.0]])])
        node.deform()
        assert np.allclose(output(node), [[5.0, 0.0, 0.0]])
        carrier.translation = (1.0, 0.0, 0.0)
        assert np.allclose(output(node), [[10.0, 0.0, 0.0]])

    def test_an_input_transform_that_moves_nothing(self):
        carrier = basenodes.Transform(translation=(0.5, 0.0, 0.0))
        node = deformer(inputTransform=[carrier])
        node.deform()
        carrier.translation = (0.0, 0.0, 0.0)
        assert np.allclose(output(node), POINTS)

    def test_the_input_points_are_left_as_they_were(self):
        node = deformer(controlPoint=np.asarray(CUBE) * 2.0)
        node.deform()
        assert np.allclose(node.inputCoord[0].point, POINTS)

    def test_an_output_that_is_an_input_is_not_deformed_again(self):
        shared = basenodes.Coordinate(point=POINTS)
        node = deformer(controlPoint=np.asarray(CUBE) * 0.5,
                        inputCoord=[shared], outputCoord=[shared])
        node.deform()
        assert np.allclose(shared.point, np.asarray(POINTS) * 0.5)

    def test_children_are_added_and_removed(self):
        first, second = basenodes.Shape(), basenodes.Shape()
        node = deformer(children=[first])
        node.addChildren = [second]
        assert list(node.children) == [first, second]
        node.removeChildren = [first]
        assert list(node.children) == [second]


class TestFieldsThatDescribeNoVolume:
    """Published worlds give the lattice from a Script, which is not run."""

    def test_the_points_pass_through(self, caplog):
        node = deformer(uDimension=6, vDimension=6, wDimension=6)
        node.deform()
        assert np.allclose(output(node), POINTS)

    def test_the_reason_is_logged_once(self, caplog):
        node = deformer(controlPoint=[])
        with caplog.at_level(logging.WARNING):
            node.deform()
            node.inputCoord[0].point = POINTS[:2]
            node.inputCoord[0].point = POINTS[:3]
        said = [r.message for r in caplog.records if 'control points' in r.message]
        assert len(said) == 1
        assert 'has no control points -> its points are not deformed' in said[0]
        assert np.allclose(output(node), POINTS[:3])

    def test_an_input_with_no_output_is_reported(self, caplog):
        node = deformer(outputCoord=[])
        with caplog.at_level(logging.WARNING):
            node.deform()
        assert any('1 inputCoord and 0 outputCoord' in r.message for r in caplog.records)


WORLD = b'''#VRML V2.0 utf8
Transform { children [
  DEF nurb CoordinateDeformer {
    uOrder 2 vOrder 2 wOrder 2 uDimension 2 vDimension 2 wDimension 2
    uKnot [ 0 0 1 1 ] vKnot [ 0 0 1 1 ] wKnot [ 0 0 1 1 ]
    controlPoint [ 0 0 0, 2 0 0, 0 2 0, 2 2 0, 0 0 2, 2 0 2, 0 2 2, 2 2 2 ]
    inputCoord [ Coordinate { point [ 0 0 0, 1 0 0, 0 1 0, 1 1 1 ] } ]
    outputCoord [ DEF outCoord Coordinate { point [ ] } ]
    children [
      DEF mesh Shape { geometry IndexedFaceSet { coord USE outCoord coordIndex [ 0 1 2 -1 ] } }
      Shape { geometry DEF patch NurbsSurface {
        uDimension 2 vDimension 2 uOrder 2 vOrder 2 uKnot [ 0 0 1 1 ] vKnot [ 0 0 1 1 ] } }
    ]
  }
] }
ROUTE outCoord.point_changed TO patch.set_controlPoint
'''


class TestInAWorld:
    def test_a_world_builds_the_node_and_what_is_in_it(self):
        scene = Loader.loads(WORLD, 'ffd.wrl')
        assert [str(p) for p in scene.problems if p.severity != 'info'] == []
        node = scene.getDEF('nurb')
        assert type(node) is CoordinateDeformer
        assert type(scene.getDEF('mesh')) is basenodes.Shape
        assert node.outputCoord[0] is scene.getDEF('outCoord')

    def test_the_output_reaches_what_it_is_routed_to(self):
        scene = Loader.loads(WORLD, 'ffd.wrl')
        scene.getDEF('nurb').deform()
        expected = [[0, 0, 0], [2, 0, 0], [0, 2, 0], [2, 2, 2]]
        assert np.allclose(scene.getDEF('outCoord').point, expected)
        assert np.allclose(scene.getDEF('patch').controlPoint, expected)

    def test_a_routed_control_point_moves_the_output(self):
        scene = Loader.loads(WORLD + b'''
DEF mover CoordinateInterpolator { key [ 0 1 ] keyValue [
  0 0 0, 2 0 0, 0 2 0, 2 2 0, 0 0 2, 2 0 2, 0 2 2, 2 2 2,
  0 0 0, 4 0 0, 0 4 0, 4 4 0, 0 0 4, 4 0 4, 0 4 4, 4 4 4 ] }
ROUTE mover.value_changed TO nurb.set_controlPoint
''', 'ffd.wrl')
        scene.getDEF('nurb').deform()
        scene.getDEF('mover').set_fraction = 1.0
        assert np.allclose(scene.getDEF('outCoord').point,
                           [[0, 0, 0], [4, 0, 0], [0, 4, 0], [4, 4, 4]])


X3D_WORLD = b'''#X3D V4.0 utf8
PROFILE Immersive
DEF nurb CoordinateDeformer {
  uDimension 2 vDimension 2 wDimension 2
  uKnot [ 0 0 1 1 ] vKnot [ 0 0 1 1 ] wKnot [ 0 0 1 1 ]
  controlPoint [ 0 0 0, 2 0 0, 0 2 0, 2 2 0, 0 0 2, 2 0 2, 0 2 2, 2 2 2 ]
  inputCoord [ Coordinate { point [ 0 0 0, 1 1 1 ] } ]
  outputCoord [ DEF outCoord Coordinate { } ]
  children [ Shape {
    appearance Appearance { material PhysicalMaterial { metallic 1 } }
    geometry PointSet { coord USE outCoord }
  } ]
}
DEF mover CoordinateInterpolator { key [ 0 1 ] keyValue [
  0 0 0, 2 0 0, 0 2 0, 2 2 0, 0 0 2, 2 0 2, 0 2 2, 2 2 2,
  0 0 0, 4 0 0, 0 4 0, 4 4 0, 0 0 4, 4 0 4, 0 4 4, 4 4 4 ] }
ROUTE mover.value_changed TO nurb.controlPoint
'''


class TestInAnX3DDocument:
    """X3D has no such node; the engine's reader takes it as its own."""

    def test_a_document_may_name_the_node(self):
        scene = Loader.loads(X3D_WORLD, 'ffd.x3dv')
        assert [str(p) for p in scene.problems if p.severity != 'info'] == []
        assert type(scene.getDEF('nurb')) is CoordinateDeformer

    def test_it_is_in_the_x3d_vocabulary(self):
        from OpenGLContext.loaders import x3d
        assert x3d.prototypes()['CoordinateDeformer'] is CoordinateDeformer

    def test_a_routed_control_point_moves_the_output(self):
        scene = Loader.loads(X3D_WORLD, 'ffd.x3dv')
        scene.getDEF('nurb').deform()
        assert np.allclose(scene.getDEF('outCoord').point, [[0, 0, 0], [2, 2, 2]])
        scene.getDEF('mover').set_fraction = 1.0
        assert np.allclose(scene.getDEF('outCoord').point, [[0, 0, 0], [4, 4, 4]])

    def test_it_is_written_in_its_component_and_read_back(self):
        from vrml import x3d as documents
        scene = Loader.loads(X3D_WORLD, 'ffd.x3dv')
        for encoding in ('classic', 'xml', 'json'):
            text = documents.dumps(scene, encoding=encoding)
            assert 'OpenGLContext' in text and 'CoordinateDeformer' in text
            name = 'again.' + {'classic': 'x3dv', 'xml': 'x3d', 'json': 'x3dj'}[encoding]
            again = Loader.loads(text.encode('utf-8'), name)
            assert [str(p) for p in again.problems if p.severity != 'info'] == []
            node = again.getDEF('nurb')
            assert type(node) is CoordinateDeformer
            assert node.outputCoord[0] is again.getDEF('outCoord')
            assert node.children[0].geometry.coord is node.outputCoord[0]
            node.deform()
            assert np.allclose(again.getDEF('outCoord').point, [[0, 0, 0], [2, 2, 2]])

    def test_the_classic_text_names_the_component(self):
        from vrml import x3d as documents
        text = documents.dumps(Loader.loads(X3D_WORLD, 'ffd.x3dv'), encoding='classic')
        assert 'COMPONENT OpenGLContext:1' in text

    def test_a_document_naming_the_component_is_valid(self):
        from vrml import x3d as documents
        scene = Loader.loads(X3D_WORLD.replace(
            b'PROFILE Immersive', b'PROFILE Immersive\nCOMPONENT OpenGLContext:1'), 'ffd.x3dv')
        assert [str(p) for p in scene.problems if p.severity != 'info'] == []
        assert documents.validate(scene) == []
