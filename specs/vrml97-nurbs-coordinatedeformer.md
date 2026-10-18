# CoordinateDeformer: the VRML97 NURBS extension's free-form deformation node

The facts `OpenGLContext.scenegraph.coordinatedeformer` relies on. Read on
2026-10-10 from the published node reference of the blaxxun NURBS proposal,
`https://www.bitmanagement.com/developer/contact/nurbs/spec/nodes.htm`, and
from two published worlds that use the node. No browser's source was read.

## Fields

| Access | Type | Name | Default |
|---|---|---|---|
| eventIn | MFNode | addChildren | |
| eventIn | MFNode | removeChildren | |
| exposedField | MFNode | children | [] |
| field | SFVec3f | bboxCenter | 0 0 0 |
| field | SFVec3f | bboxSize | -1 -1 -1 |
| field | SFInt32 | uDimension, vDimension, wDimension | 0 |
| field | MFFloat | uKnot, vKnot, wKnot | [] |
| field | SFInt32 | uOrder, vOrder, wOrder | 2 |
| exposedField | MFVec3f | controlPoint | [] |
| exposedField | MFFloat | weight | [] |
| exposedField | MFNode | inputCoord | NULL |
| exposedField | MFNode | inputTransform | NULL |
| exposedField | MFNode | outputCoord | NULL |

## What the reference states

- The node is a group, and its children are drawn.
- The dimensions, control points, weights, knots and orders define a NURBS
  volume in three parametric directions, as a `NurbsSurface`'s define a
  surface in two.
- `inputCoord` holds `Coordinate` nodes. Each point of each is a parameter
  (u, v, w) at which the volume is evaluated.
- `outputCoord` holds as many `Coordinate` nodes, distinct from the inputs.
  Each receives the evaluated positions for the input at the same place.
- `inputTransform`, where given, holds as many `Transform` nodes. Animating
  one moves a mesh through the deformation space.
- The outputs are recomputed when an input's points change, when an exposed
  field of the node changes, or when an input transform changes.
- A browser may put the evaluation off until the group is traversed.

## What the reference does not state

Each of these is the engine's own rule, described in the module:

- the order of control points along w (taken as the surface's rule carried
  one direction further: index `i + j * uDimension + k * uDimension * vDimension`);
- the number of knots a direction needs (taken as dimension plus order, the
  surface's rule);
- what a parameter outside the knots' range gives;
- what fields that describe no volume give;
- whether an input transform is applied before or after evaluation (taken as
  before, from "moved through the deformation space").

## Published worlds

`samples/ffd/deform_222_grid.wrl` and `samples/ffd/deform_sphere.wrl` under
`https://www.bitmanagement.com/developer/contact/nurbs/`. Both name the node
with no EXTERNPROTO. Both leave the lattice to a `Script`: the first gives
dimensions of 6 with eight control points and four knots a direction, the
second gives no control points and no knots. The second routes its output
`Coordinate`'s `point_changed` to a `NurbsSurface`'s `set_controlPoint`.
