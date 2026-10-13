"""The VRML97 NURBS extension's CoordinateDeformer: points moved through a NURBS volume

A `CoordinateDeformer` is a group holding a lattice of control points, a knot
vector and an order along each of u, v and w. Each point of each `Coordinate`
in `inputCoord` is a parameter (u, v, w); the volume's position there is the
point of the same index in the `Coordinate` at the same place in `outputCoord`.
A geometry among the children that uses an output `Coordinate` is drawn
deformed, and moving the control points moves it. A `Transform` at the same
place in `inputTransform` is applied to the input points first, so animating
it carries a mesh through the volume.

The output is written when the group is first drawn or bounded, and again
whenever a control point, a weight, an input point, an input transform or
either list of nodes is set, whether directly or by a ROUTE. The lattice's
dimensions, knots and orders are read with it. The input points are left as
they are.

Fields that describe no volume (:func:`lattice_of` gives the reason) leave the
points where they are: each output is its input, through its transform. Worlds
written for the Contact browsers fill the lattice in from a Script, which this
engine does not run, so their meshes are drawn undeformed.

A parameter outside the knots' range is held at the end of the range.

The node's fields are those of the blaxxun NURBS proposal, recorded in
`specs/vrml97-nurbs-coordinatedeformer.md`. X3D has no such node. It is in the
engine's own component, `OpenGLContext` (`vrml.x3d.components`), so an X3D
document of any encoding names it and a scene holding one is written with
``COMPONENT OpenGLContext:1``. A VRML97 world names it as the proposal's node.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from opengl_extrusions.nurbs import basis_functions
from pydispatch import dispatcher
from vrml import field, node, protofunctions
from vrml.vrml97 import nodetypes, transformmatrix
from vrml.x3d import components

from OpenGLContext.scenegraph import grouping
from OpenGLContext.scenegraph.nurbstess import report

__all__ = ['CoordinateDeformer', 'Lattice', 'lattice_of', 'volume_points']

#: The signals a field sends when it is set, deleted, or set by a ROUTE.
_CHANGES = ('set', 'del', 'route')

#: The fields a `Transform` in `inputTransform` is made of.
_TRANSFORM_FIELDS = ('translation', 'rotation', 'scale', 'scaleOrientation', 'center')

#: The lattice's own fields, each of which the output is worked out from.
_LATTICE_FIELDS = (
    'controlPoint', 'weight', 'uDimension', 'vDimension', 'wDimension',
    'uKnot', 'vKnot', 'wKnot', 'uOrder', 'vOrder', 'wOrder',
)


@dataclass
class Lattice:
    """A NURBS volume's control points, knots, degrees and weights

    control -- ``(w, v, u, 3)``
    knots -- the u, v and w knot vectors
    degrees -- the u, v and w degrees
    weights -- ``(w, v, u)``, or None where every weight is 1
    """

    control: np.ndarray
    knots: "tuple[np.ndarray, np.ndarray, np.ndarray]"
    degrees: "tuple[int, int, int]"
    weights: Optional[np.ndarray]


def volume_points(parameters: Any, lattice: Lattice) -> np.ndarray:
    """The volume's positions at ``(N, 3)`` parameters (u, v, w), ``(N, 3)``"""
    params = np.asarray(parameters, dtype=np.float64).reshape(-1, 3)
    if not len(params):
        return np.zeros((0, 3))
    bases = []
    for axis, (knot, degree) in enumerate(zip(lattice.knots, lattice.degrees)):
        count = lattice.control.shape[2 - axis]
        held = np.clip(params[:, axis], knot[degree], knot[count])
        bases.append(basis_functions(held, knot, degree, count))
    u, v, w = bases
    if lattice.weights is None:
        return np.asarray(np.einsum('ni,nj,nk,kjic->nc', u, v, w, lattice.control))
    weighted = lattice.control * lattice.weights[..., None]
    total = np.einsum('ni,nj,nk,kji->n', u, v, w, lattice.weights)
    return np.asarray(np.einsum('ni,nj,nk,kjic->nc', u, v, w, weighted) / total[:, None])


def lattice_of(deformer: Any) -> "Lattice | str":
    """The volume a deformer's fields describe, or why they describe none

    The reason completes "CoordinateDeformer ...". Weights of another count
    than the control points, or with one that is not positive, are left out.
    """
    control = np.asarray(deformer.controlPoint, dtype=np.float64).reshape(-1, 3)
    if not len(control):
        return 'has no control points'
    dimensions = [int(getattr(deformer, axis + 'Dimension')) for axis in 'uvw']
    if len(control) != dimensions[0] * dimensions[1] * dimensions[2]:
        return 'has %d control points for a %d by %d by %d lattice' % (
            len(control), *dimensions)
    knots, degrees = [], []
    for axis, dimension in zip('uvw', dimensions):
        order = int(getattr(deformer, axis + 'Order'))
        knot = np.asarray(getattr(deformer, axis + 'Knot'), dtype=np.float64).ravel()
        if order < 2:
            return 'has a %s order of %d; the least is 2' % (axis, order)
        if dimension < order:
            return 'has %d %s control points, fewer than its order of %d' % (
                dimension, axis, order)
        if len(knot) != dimension + order:
            return 'has %d %s knots, where %d control points at order %d need %d' % (
                len(knot), axis, dimension, order, dimension + order)
        if np.any(np.diff(knot) < 0):
            return 'has %s knots that decrease' % axis
        if not knot[dimension] > knot[order - 1]:
            return 'has %s knots that span nothing' % axis
        knots.append(knot)
        degrees.append(order - 1)
    u, v, w = dimensions
    weight = np.asarray(deformer.weight, dtype=np.float64).ravel()
    weights = (weight.reshape(w, v, u)
               if weight.size == len(control) and np.all(weight > 0) else None)
    return Lattice(control.reshape(w, v, u, 3), (knots[0], knots[1], knots[2]),
                   (degrees[0], degrees[1], degrees[2]), weights)


def _carried(points: np.ndarray, transform: Any) -> np.ndarray:
    """`points` through a Transform node's matrix; themselves with no node"""
    if not transform:
        return points
    matrix = transformmatrix.transformMatrix(
        **{name: getattr(transform, name) for name in _TRANSFORM_FIELDS})
    if matrix is None:      # a transform that moves nothing has no matrix
        return points
    homogeneous = np.concatenate([points, np.ones((len(points), 1))], axis=1)
    return (homogeneous @ np.asarray(matrix, dtype=np.float64))[:, :3]


class CoordinateDeformer(grouping.Grouping, nodetypes.Grouping, nodetypes.Children, node.Node):
    """A group whose output coordinates are its inputs moved through a NURBS volume

    See the module docstring. :meth:`deform` writes the outputs.
    """

    PROTO = 'CoordinateDeformer'
    COMPONENT = ('OpenGLContext', 1)
    SINCE = '3.0'
    CONTAINER_FIELD = 'children'
    addChildren = field.newEvent('addChildren', 'MFNode', 0)
    removeChildren = field.newEvent('removeChildren', 'MFNode', 0)
    bboxCenter = field.newField('bboxCenter', 'SFVec3f', 0, [0.0, 0.0, 0.0])
    bboxSize = field.newField('bboxSize', 'SFVec3f', 0, [-1.0, -1.0, -1.0])
    uDimension = field.newField('uDimension', 'SFInt32', 0, 0)
    vDimension = field.newField('vDimension', 'SFInt32', 0, 0)
    wDimension = field.newField('wDimension', 'SFInt32', 0, 0)
    uKnot = field.newField('uKnot', 'MFFloat', 0, list)
    vKnot = field.newField('vKnot', 'MFFloat', 0, list)
    wKnot = field.newField('wKnot', 'MFFloat', 0, list)
    uOrder = field.newField('uOrder', 'SFInt32', 0, 2)
    vOrder = field.newField('vOrder', 'SFInt32', 0, 2)
    wOrder = field.newField('wOrder', 'SFInt32', 0, 2)
    controlPoint = field.newField('controlPoint', 'MFVec3f', 1, list)
    weight = field.newField('weight', 'MFFloat', 1, list)
    inputCoord = field.newField('inputCoord', 'MFNode', 1, list)
    inputTransform = field.newField('inputTransform', 'MFNode', 1, list)
    outputCoord = field.newField('outputCoord', 'MFNode', 1, list)

    def __init__(self, **named: Any) -> None:
        super().__init__(**named)
        state = self.__dict__
        #: Whether the outputs have been written since the node was made.
        state['_deformed'] = False
        #: Whether the outputs are being written now.
        state['_deforming'] = False
        #: The (node, field) pairs outside the node that it is listening to.
        state['_watched'] = []
        for name in _LATTICE_FIELDS:
            self._listen(self, name, self._changed)
        for name in ('inputCoord', 'inputTransform', 'outputCoord'):
            self._listen(self, name, self._relisted)

    def _listen(self, source: Any, name: str, receiver: Any, on: bool = True) -> None:
        declared = protofunctions.getField(source, name)
        for change in _CHANGES:
            if on:
                dispatcher.connect(receiver, signal=(change, declared), sender=source)
            else:
                dispatcher.disconnect(receiver, signal=(change, declared), sender=source)

    def _watch(self) -> None:
        """Listen to the input points and transforms the lists hold now"""
        state = self.__dict__
        for source, name in state['_watched']:
            self._listen(source, name, self._changed, on=False)
        watched = [(entry, 'point') for entry in self.inputCoord if entry]
        watched += [(entry, name) for entry in self.inputTransform if entry
                    for name in _TRANSFORM_FIELDS]
        for source, name in watched:
            self._listen(source, name, self._changed)
        state['_watched'] = watched

    def _changed(self, **_named: Any) -> None:
        if self.__dict__['_deformed']:
            self.deform()

    def _relisted(self, **_named: Any) -> None:
        if self.__dict__['_deformed']:
            self._watch()
            self.deform()

    def deform(self) -> None:
        """Write each output `Coordinate`'s points from its input's"""
        state = self.__dict__
        if state['_deforming']:
            return
        if not state['_deformed']:
            state['_deformed'] = True
            self._watch()
        inputs, outputs = list(self.inputCoord), list(self.outputCoord)
        if len(inputs) != len(outputs):
            report(self, logging.WARNING,
                   'has %d inputCoord and %d outputCoord -> deforming the first %d'
                   % (len(inputs), len(outputs), min(len(inputs), len(outputs))))
        found = lattice_of(self)
        if isinstance(found, str):
            report(self, logging.WARNING, found + ' -> its points are not deformed')
        transforms = list(self.inputTransform)
        state['_deforming'] = True
        try:
            for index, (source, target) in enumerate(zip(inputs, outputs)):
                if not source or not target:
                    continue
                points = np.asarray(source.point, dtype=np.float64).reshape(-1, 3)
                points = _carried(points, transforms[index] if index < len(transforms) else None)
                if not isinstance(found, str):
                    points = volume_points(points, found)
                target.point = points
        finally:
            state['_deforming'] = False

    def _ensure(self) -> None:
        if not self.__dict__['_deformed']:
            self.deform()

    def renderedChildren(
        self, types: Any = (nodetypes.Children, nodetypes.Rendering),
    ) -> "list[Any]":
        self._ensure()
        return super().renderedChildren(types)

    def boundingVolume(self, mode: Any) -> Any:
        self._ensure()
        return super().boundingVolume(mode)

    def on_addChildren(self, value: Any) -> None:
        current = list(self.children)
        self.children = current + [entry for entry in value if entry and entry not in current]

    def on_removeChildren(self, value: Any) -> None:
        gone = list(value)
        self.children = [entry for entry in self.children if entry not in gone]


components.register(CoordinateDeformer)
