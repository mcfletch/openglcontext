"""X3D's HAnim nodes: humanoids drawn, skinned and animated -- docs/characters.rst

An `HAnimHumanoid` is drawn as a Transform of its `skeleton`, its `skin` and
those of its `viewpoints` the skeleton does not already place. Each
`HAnimJoint` and `HAnimSite` is a Transform of its children, and an
`HAnimSegment` a group of its own. A humanoid's `joints`, `segments` and
`sites` lists name nodes the skeleton holds and draw nothing themselves.

The skin is the shapes whose geometry reads the humanoid's `skinCoord`: the
humanoid registers itself as that Coordinate's deformer
(:mod:`~OpenGLContext.scenegraph.coordinatedeform`), and each such geometry is
drawn as a :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` skinned by the
joints, on the GPU where the renderer skins there and on the CPU where it does
not. The joint weights, the binding matrices, the joint displacers and the
skin's bounds are worked out by :mod:`OpenGLContext.character.hanim`. An
`HAnimSegment` with displacers deforms its `coord` the same way.

`HAnimMotion` plays its channels onto the joints of each humanoid that lists
it in `motions`, and `HAnimPose` moves them to its joints' values; both are
polled on the engine's clock (:class:`~OpenGLContext.scenegraph.x3druntime.Polled`)
through the contexts the humanoid is drawn in. Joints are fields, so
interpolators routed to them animate the humanoid as they would a Transform.
"""
from __future__ import annotations

import math
import weakref
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from pydispatch import dispatcher
from vrml import cache, node, protofunctions
from vrml.vrml97 import nodetypes
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import boundingvolume, coordinatedeform, grouping
from OpenGLContext.scenegraph.switch import CHILDREN_CHANGE_SIGNAL
from OpenGLContext.scenegraph.transform import Transforming
from OpenGLContext.scenegraph.x3druntime import EngineTimed, Polled

if TYPE_CHECKING:
    from OpenGLContext.character.hanim import MotionChannels

__all__ = ['HAnimDisplacer', 'HAnimHumanoid', 'HAnimJoint', 'HAnimMotion', 'HAnimPose',
           'HAnimSegment', 'HAnimSite', 'Placed', 'Pose', 'Rig']

#: The fields of a transform that place what it holds.
PLACING = ('translation', 'rotation', 'scale', 'scaleOrientation', 'center')
#: The vrml cache keys a humanoid keeps its rig and its pose under.
RIG_KEY = 'hanim-rig'
POSE_KEY = 'hanim-pose'
#: The key a deformed geometry's mesh is kept under in vrml's cache.
MESH_KEY = 'hanim-deformed-mesh'
#: The key a motion's channels are kept under.
CHANNELS_KEY = 'hanim-channels'


#: What a joint draws of its children (ISO/IEC 19775-1, 26.3.3).
_JOINT_CHILDREN = (x3d.HAnimJoint, x3d.HAnimSegment, x3d.HAnimSite)


def _rig() -> Any:
    """:mod:`OpenGLContext.character.hanim`, imported when first used

    The character package imports the loaders, which import the node registry
    this module is loaded from.
    """
    from OpenGLContext.character import hanim  # noqa: PLC0415 see the docstring
    return hanim


def _rotation(value: Any) -> tuple[float, float, float, float]:
    found = [float(item) for item in value]
    return (found[0], found[1], found[2], found[3])


class HAnimDisplacer(x3d.HAnimDisplacer):
    """X3D's HAnimDisplacer: points of its joint's or segment's mesh moved by `weight` times `displacements`

    Drawn by the humanoid or segment holding it.
    """


class Placed(Transforming):
    """A Transform whose matrix is the one its path is placed by, bounding what it draws"""

    #: The fields what it draws is read from.
    DRAWN: tuple[str, ...] = ('children',)

    def boundingVolume(self, mode: Any = None) -> Any:
        """The union of what it draws, in its own coordinates"""
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        volumes: list[Any] = []
        dependencies: list[tuple[Any, Optional[str]]] = [
            (self, name) for name in self.DRAWN + PLACING]
        try:
            for child in self.renderedChildren():  # type: ignore[attr-defined]  # Grouping's
                if not hasattr(child, 'boundingVolume'):
                    raise boundingvolume.UnboundedObject(child)
                volume = child.boundingVolume(mode)
                volumes.append(volume)
                dependencies.append((volume, None))
            volume = boundingvolume.BoundingBox.union(volumes, self.localMatrix(mode))
        except boundingvolume.UnboundedObject:
            volume = boundingvolume.UnboundedVolume()
        return boundingvolume.cacheVolume(self, volume, dependencies)

    def localMatrix(self, mode: Any = None) -> Any:
        """The forward matrix of its own fields, kept in vrml's cache"""
        found = self.localMatrices().data[0]  # type: ignore[attr-defined]  # the X3D declaration's LocalMatrices
        return np.eye(4) if found is None else found


class HAnimJoint(Placed, x3d.HAnimJoint):
    """X3D's HAnimJoint: a Transform of the joints, segments and sites it holds

    Other nodes among its children (an exporter's marker boxes) are kept and
    not drawn: X3D lists only joints, segments and sites there.
    `llimit`, `ulimit` and `limitOrientation` are kept; :meth:`limitedRotation`
    holds a rotation to them for an application that wants its joints held,
    and nothing applies them by itself.
    """

    def renderedChildren(self, types: Any = (nodetypes.Children, nodetypes.Rendering)) -> list:
        """The joints, segments and sites it holds"""
        return [item for item in super().renderedChildren(types)
                if isinstance(item, (*_JOINT_CHILDREN, node.PrototypedNode))]

    def limitedRotation(self, rotation: Any = None) -> tuple[float, float, float, float]:
        """`rotation` (the joint's own where None) held within the joint's limits"""
        return _rotation(_rig().limited_rotation(
            self.rotation if rotation is None else rotation,
            self.llimit, self.ulimit, self.limitOrientation))


class HAnimSite(Placed, x3d.HAnimSite):
    """X3D's HAnimSite: a Transform of what is attached at a named point of the body"""


class HAnimSegment(grouping.Grouping, x3d.HAnimSegment):
    """X3D's HAnimSegment: a group of the body's part between two joints

    With `displacers` and a `coord`, each geometry reading `coord` is drawn
    with the displacers' displacements added at their weights. `mass`,
    `centerOfMass` and `momentsOfInertia` are kept.
    """

    def __init__(self, *args: Any, **named: Any) -> None:
        super().__init__(*args, **named)
        for name in ('coord', 'displacers'):
            dispatcher.connect(self._settle, signal=('set', protofunctions.getField(self, name)),
                               sender=self)
        self._settle()

    def _settle(self, value: Any = None) -> None:
        """Register this segment as its coordinates' deformer, or let them go"""
        held: Optional[SegmentDeformer] = self.__dict__.get('_deformer')
        coord = self.coord
        if held is not None and held.coord is not coord:
            coordinatedeform.unregister(held.coord, held)
            held = None
        if coord and any(isinstance(item, x3d.HAnimDisplacer) for item in self.displacers):
            if held is None:
                held = SegmentDeformer(self)
            coordinatedeform.register(coord, held)
        elif held is not None:
            coordinatedeform.unregister(held.coord, held)
            held = None
        self.__dict__['_deformer'] = held


class Rig:
    """What a humanoid's skeleton and skin are made of, until a field they are read from is set

    chain -- every transform under the skeleton, as ``(node, parent row)``,
        parents first; a root's parent row is -1
    joints -- the humanoid's joints, in the order of its `joints` field (of the
        skeleton's, where that field is empty)
    rows -- each joint's row in `chain`, or -1 for one the skeleton lacks
    bindings -- each joint's binding matrix
    named -- each joint by its standard name
    placed -- every node the skeleton holds
    count -- the skin's points; zero for a humanoid with no skin
    """

    def __init__(self, humanoid: HAnimHumanoid) -> None:
        self.chain: list[tuple[Any, int]] = []
        self.placed: set[Any] = set()
        #: (node, field name) the rig is read from.
        self.structure: list[tuple[Any, str]] = [
            (humanoid, name) for name in (
                'skeleton', 'joints', 'skinCoord', 'skinNormal', 'skinBindingCoords',
                'skinBindingNormals', 'jointBindingPositions', 'jointBindingRotations',
                'jointBindingScales', 'displacers', 'motions', 'motionsEnabled', 'children')]
        #: (node, field name) the pose is read from.
        self.posing: list[tuple[Any, str]] = []
        for root in humanoid.skeleton:
            self._walk(root, -1)
        joints = [item for item in humanoid.joints if isinstance(item, x3d.HAnimJoint)]
        if not joints:
            joints = [found for found, _parent in self.chain if isinstance(found, x3d.HAnimJoint)]
        self.joints = joints
        rows = {found: row for row, (found, _parent) in enumerate(self.chain)}
        self.rows = [rows.get(joint, -1) for joint in joints]
        self.named: dict[str, Any] = {}
        for joint in joints:
            self.named.setdefault(_rig().canonical_joint(joint.name), joint)
        self.bindings = _rig().binding_matrices(
            len(joints), humanoid.jointBindingPositions, humanoid.jointBindingRotations,
            humanoid.jointBindingScales)
        coord = humanoid.skinCoord
        points = np.asarray(getattr(coord, 'point', None) if coord else [], dtype=np.float64)
        points = points.reshape(-1, 3)
        self.count = len(points)
        self.coord = coord if coord else None
        self.normal = humanoid.skinNormal if humanoid.skinNormal else None
        if coord:
            self.structure.append((coord, 'point'))
        self.rest_points = self._binding(humanoid.skinBindingCoords, 'point', self.count)
        self.rest_normals = self._binding(humanoid.skinBindingNormals, 'vector', self.count)
        for joint in joints:
            self.structure.extend((joint, name) for name in
                                  ('skinCoordIndex', 'skinCoordWeight', 'displacers', 'name'))
        self.skin_joints, self.skin_weights = _rig().skin_influences(
            self.count, [(joint.skinCoordIndex, joint.skinCoordWeight) for joint in joints])
        displacers = [item for joint in joints for item in joint.displacers]
        displacers.extend(humanoid.displacers)
        self.displacers = [item for item in displacers if isinstance(item, x3d.HAnimDisplacer)]
        self.displacements = [_rig().displacement(self.count, item.coordIndex, item.displacements)
                              for item in self.displacers]
        for item in self.displacers:
            self.structure.extend([(item, 'coordIndex'), (item, 'displacements')])
            self.posing.append((item, 'weight'))
        #: Whether every vertex is an average of its joints, so joint spheres bound it.
        self.convex = _rig().convex(self.skin_weights)

    def _walk(self, start: Any, parent: int) -> None:
        todo = [(start, parent)]
        while todo:
            found, above = todo.pop(0)
            if found is None or found in self.placed:
                continue
            self.placed.add(found)
            row = above
            if isinstance(found, nodetypes.Transforming):
                row = len(self.chain)
                self.chain.append((found, above))
                self.posing.extend((found, name) for name in PLACING)
            if isinstance(found, nodetypes.Grouping):
                self.structure.append((found, 'children'))
                todo.extend((child, row) for child in getattr(found, 'children', ()))

    def _binding(self, node: Any, name: str, count: int) -> Optional[np.ndarray]:
        """A binding Coordinate's or Normal's values, where it has one per skin point"""
        if not node:
            return None
        self.structure.append((node, name))
        values = np.asarray(getattr(node, name, []), dtype=np.float64).reshape(-1, 3)
        return values if len(values) == count and count else None


class Pose:
    """A humanoid's skin palette and displacer weights, as its joints stand now

    palette -- ``(joints + 1, 4, 4)`` row-vector matrices: :data:`REST_JOINT`'s
        identity, then each joint's binding matrix times its transform in the
        humanoid's coordinates
    weights -- each displacer's weight, in the rig's order
    """

    def __init__(self, palette: Optional[np.ndarray], weights: np.ndarray) -> None:
        self.palette = palette
        self.weights = weights


class Drawing:
    """A deformed geometry's mesh: what it was built from, and the pose last given it

    sources -- the coordinate each vertex of the mesh was read from
    reach -- each joint's sphere about the rest points it moves, once asked for
    """

    def __init__(self, structure: Any, mesh: Any, sources: np.ndarray) -> None:
        self.structure = structure
        self.mesh = mesh
        self.sources = sources
        self.pose: Optional[Pose] = None
        self.reach: Any = None


#: Each volume a deformer made, and the deformer, so a volume cached for the
#: geometry before it was deformed is not taken for one.
_BOUNDED: 'weakref.WeakKeyDictionary[Any, Deformer]' = weakref.WeakKeyDictionary()


class Deformer:
    """Drawing a geometry whose coordinates something deforms, as a PBRMesh it builds

    A subclass gives the rig (:meth:`structure`) and the pose; each geometry's
    mesh is built once for a rig and posed when the pose changes.
    """

    coord: Any = None

    def structure(self) -> Any:
        """What the meshes are built from; another object once that changes"""
        raise NotImplementedError

    def pose(self) -> Pose:
        """The pose the meshes are drawn in now"""
        raise NotImplementedError

    def poseHolder(self) -> Any:
        """The cache entry cleared when the pose changes"""
        raise NotImplementedError

    # -- the mesh ------------------------------------------------------------
    def drawing(self, geometry: Any) -> Optional[Drawing]:
        """`geometry`'s drawing, posed; None for a geometry with nothing to draw"""
        structure = self.structure()
        held: Optional[Drawing] = cache.CACHE.getData(geometry, MESH_KEY)
        if held is None or held.structure is not structure:
            held = self.build(geometry, structure)
            from OpenGLContext.scenegraph import meshgeometry  # noqa: PLC0415 imports the loader
            holder = cache.CACHE.holder(geometry, held, MESH_KEY)
            meshgeometry.depend_on_fields(holder, geometry)
        if held.mesh is None:
            return None
        pose = self.pose()
        if held.pose is not pose:
            held.pose = pose
            mesh = held.mesh
            if pose.palette is not None and mesh.skin_joints is not None:
                mesh.set_skin_matrices(pose.palette)
            if mesh.morph_targets:
                mesh.set_morph_weights(pose.weights)
        return held

    def mesh(self, geometry: Any) -> Any:
        """The PBRMesh `geometry` is drawn as, posed; None for a geometry with nothing to draw"""
        found = self.drawing(geometry)
        return None if found is None else found.mesh

    def build(self, geometry: Any, structure: Any) -> Drawing:
        """`geometry`'s drawing under `structure`, its mesh None where it draws nothing"""
        from OpenGLContext.loaders.gltf.meshes import estimate_tangents  # noqa: PLC0415 the loader imports GL
        from OpenGLContext.scenegraph.frommesh import mesh_from_primitive  # noqa: PLC0415 PBRMesh imports GL
        composed = getattr(geometry, 'composedArrays', None)
        arrays = composed() if composed is not None else None
        if arrays is None or arrays.sources is None or not len(arrays.sources):
            return Drawing(structure, None, np.zeros(0, dtype=np.int64))
        count = structure.count
        sources = np.clip(arrays.sources, 0, max(count - 1, 0))
        attributes = arrays.attributes
        if structure.rest_points is not None:
            attributes['POSITION'] = np.ascontiguousarray(
                structure.rest_points[sources], dtype=np.float32)
        if (structure.rest_normals is not None and structure.normal is not None
                and getattr(geometry, 'normal', None) is structure.normal):
            attributes['NORMAL'] = np.ascontiguousarray(
                structure.rest_normals[sources], dtype=np.float32)
        if 'TANGENT' not in attributes and 'TEXCOORD_0' in attributes:
            attributes['TANGENT'] = estimate_tangents(
                attributes['POSITION'], attributes['NORMAL'], attributes['TEXCOORD_0'],
                arrays.indices)
        named: dict[str, Any] = {}
        if structure.skin_joints is not None and count:
            named['skin_joints'] = structure.skin_joints[sources]
            named['skin_weights'] = structure.skin_weights[sources]
        if structure.displacements and count:
            named['morph_targets'] = [{'positions': moved[sources]}
                                      for moved in structure.displacements]
        mesh = mesh_from_primitive(arrays, solid=bool(getattr(geometry, 'solid', True)), **named)
        return Drawing(structure, mesh, sources)

    # -- drawing -----------------------------------------------------------
    def render(self, geometry: Any, visible: int = 1, lit: int = 1, textured: int = 1,
               transparent: int = 0, mode: Any = None) -> int:
        """Draw `geometry`'s mesh in the pose"""
        mesh = self.mesh(geometry)
        if mesh is None:
            return 0
        return int(mesh.render(visible=visible, lit=lit, textured=textured,
                               transparent=transparent, mode=mode))

    def boundingVolume(self, geometry: Any, mode: Any = None) -> Any:
        """`geometry`'s bounds in the pose, kept until the pose or the geometry changes"""
        current = boundingvolume.getCachedVolume(geometry)
        if current is not None and _BOUNDED.get(current) is self:
            return current
        found = self.drawing(geometry)
        volume = (boundingvolume.BoundingVolume() if found is None
                  else self._volume(found))
        _BOUNDED[volume] = self
        from OpenGLContext.scenegraph import meshgeometry  # noqa: PLC0415 imports the loader
        holder = boundingvolume.holdVolume(geometry, volume)
        holder.depend_holder(self.poseHolder())
        meshgeometry.depend_on_fields(holder, geometry)
        return volume

    def _volume(self, drawing: Drawing) -> Any:
        structure = self.structure()
        pose = self.pose()
        mesh = drawing.mesh
        rest = (mesh._base_positions if mesh._base_positions is not None
                else mesh.positions)
        margin = 0.0
        for moved, weight in zip(structure.displacements, pose.weights, strict=False):
            if weight:
                reach = np.linalg.norm(moved[drawing.sources], axis=1).max(initial=0.0)
                margin += abs(float(weight)) * float(reach)
        if pose.palette is not None and mesh.skin_joints is not None:
            if structure.convex:
                if drawing.reach is None:
                    drawing.reach = _rig().joint_reach(rest, mesh.skin_joints, mesh.skin_weights,
                                                       len(pose.palette))
                bounds = _rig().posed_bounds(drawing.reach, pose.palette)
                if bounds is None:
                    return boundingvolume.BoundingVolume()
                low, high = bounds
            else:
                posed = _rig().skin_points(rest, mesh.skin_joints, mesh.skin_weights, pose.palette)
                low, high = posed.min(axis=0), posed.max(axis=0)
        else:
            low = np.asarray(rest).min(axis=0)
            high = np.asarray(rest).max(axis=0)
        # A displacer moves a point along a vector the joints then turn and
        # scale; the largest stretch of any joint carries the margin.
        if margin and pose.palette is not None:
            margin *= float(np.linalg.norm(pose.palette[:, :3, :3], ord=2, axis=(1, 2)).max())
        return boundingvolume.AABoundingBox.fromPoints(
            np.array([low - margin, high + margin], dtype=np.float64))


class SkinDeformer(Deformer):
    """A humanoid's skin: the geometry reading its `skinCoord`, posed by its joints"""

    def __init__(self, humanoid: HAnimHumanoid) -> None:
        self._humanoid = weakref.ref(humanoid)
        self.coord = humanoid.skinCoord

    def humanoid(self) -> HAnimHumanoid:
        found = self._humanoid()
        if found is None:
            raise ReferenceError('the humanoid this skin belonged to has gone')
        return found

    def structure(self) -> Rig:
        return self.humanoid().rig()

    def pose(self) -> Pose:
        return self.humanoid().pose()

    def poseHolder(self) -> Any:
        return self.humanoid().poseHolder()


class _SegmentRig:
    """A segment's coordinates and its displacers' displacements"""

    skin_joints = None
    skin_weights = None
    rest_points = None
    rest_normals = None
    normal = None
    convex = True

    def __init__(self, segment: HAnimSegment) -> None:
        coord = segment.coord
        self.count = len(np.asarray(getattr(coord, 'point', []), dtype=np.float64).reshape(-1, 3))
        self.displacers = [item for item in segment.displacers
                           if isinstance(item, x3d.HAnimDisplacer)]
        self.displacements = [_rig().displacement(self.count, item.coordIndex, item.displacements)
                              for item in self.displacers]


class SegmentDeformer(Deformer):
    """A segment's `coord`, moved by its displacers"""

    def __init__(self, segment: HAnimSegment) -> None:
        self._segment = weakref.ref(segment)
        self.coord = segment.coord

    def segment(self) -> HAnimSegment:
        found = self._segment()
        if found is None:
            raise ReferenceError('the segment these coordinates belonged to has gone')
        return found

    def structure(self) -> _SegmentRig:
        segment = self.segment()
        found: Optional[_SegmentRig] = cache.CACHE.getData(segment, RIG_KEY)
        if found is None:
            found = _SegmentRig(segment)
            holder = cache.CACHE.holder(segment, found, RIG_KEY)
            holder.depend(segment, 'coord')
            holder.depend(segment, 'displacers')
            holder.depend(self.coord, 'point')
            for item in found.displacers:
                holder.depend(item, 'coordIndex')
                holder.depend(item, 'displacements')
            cleared = cache.CACHE.getHolder(segment, POSE_KEY)
            if cleared is not None:
                cleared()
        return found

    def pose(self) -> Pose:
        structure = self.structure()
        segment = self.segment()
        held = cache.CACHE.getHolder(segment, POSE_KEY)
        if held is not None and held.data is not None:
            found: Pose = held.data
            return found
        pose = Pose(None, np.array([float(item.weight) for item in structure.displacers]))
        if held is None:
            held = cache.CACHE.holder(segment, pose, POSE_KEY)
            for item in structure.displacers:
                held.depend(item, 'weight')
        else:
            held.data = pose
        return pose

    def poseHolder(self) -> Any:
        self.pose()
        return cache.CACHE.getHolder(self.segment(), POSE_KEY)


class HAnimHumanoid(Placed, x3d.HAnimHumanoid):
    """X3D's HAnimHumanoid: a Transform of its skeleton and skin, skinned by its joints

    Drawn: `skeleton`, the `viewpoints` the skeleton does not hold, and
    `skin`. `children` holds its poses, `motions` its motions, and neither
    is drawn. `skeletalConfiguration`, `version`, `info` and `loa` are kept.
    """

    def __init__(self, *args: Any, **named: Any) -> None:
        super().__init__(*args, **named)
        for name in ('skeleton', 'skin', 'viewpoints'):
            dispatcher.connect(self._onDrawnChange,
                               signal=('set', protofunctions.getField(self, name)), sender=self)

    def _onDrawnChange(self, value: Any = None) -> None:
        dispatcher.send(signal=CHILDREN_CHANGE_SIGNAL, sender=self)

    DRAWN = ('skeleton', 'skin', 'viewpoints')

    def renderedChildren(self, types: Any = (nodetypes.Children, nodetypes.Rendering)) -> list:
        """The skeleton, the viewpoints it does not place, and the skin"""
        held = self.rig()
        found = [item for item in self.skeleton if isinstance(item, types)]
        found.extend(item for item in self.viewpoints
                     if isinstance(item, types) and item not in held.placed)
        found.extend(item for item in self.skin if isinstance(item, types))
        return found

    # -- the rig -------------------------------------------------------------
    def rig(self) -> Rig:
        """The skeleton and skin as they are read now, made again once a field they come from is set"""
        found: Optional[Rig] = cache.CACHE.getData(self, RIG_KEY)
        if found is not None:
            return found
        found = Rig(self)
        holder = cache.CACHE.holder(self, found, RIG_KEY)
        for item, name in found.structure:
            holder.depend(item, name)
        stale = cache.CACHE.getHolder(self, POSE_KEY)
        if stale is not None:
            stale()
        rests = self._rests()
        for joint in found.joints:
            if joint not in rests:
                rests[joint] = (tuple(joint.translation), _rotation(joint.rotation),
                                tuple(joint.scale))
        self._settleSkin(found)
        self._claim(found)
        return found

    def _rests(self) -> 'weakref.WeakKeyDictionary[Any, tuple]':
        found: 'weakref.WeakKeyDictionary[Any, tuple]' = self.__dict__.setdefault(
            '_rest', weakref.WeakKeyDictionary())
        return found

    def restValues(self, joint: Any) -> tuple[Any, Any, Any]:
        """The translation, rotation and scale `joint` had when this humanoid first read it"""
        found = self._rests().get(joint)
        if found is None:
            return (tuple(joint.translation), _rotation(joint.rotation), tuple(joint.scale))
        return found

    def _settleSkin(self, found: Rig) -> None:
        held: Optional[SkinDeformer] = self.__dict__.get('_skin')
        if held is not None and held.coord is not found.coord:
            coordinatedeform.unregister(held.coord, held)
            held = None
        if found.coord is not None and found.count:
            if held is None:
                held = SkinDeformer(self)
            coordinatedeform.register(found.coord, held)
        elif held is not None:
            coordinatedeform.unregister(held.coord, held)
            held = None
        self.__dict__['_skin'] = held

    def _claim(self, found: Rig) -> None:
        """Tell this humanoid's motions and poses which humanoid they drive"""
        enabled = list(self.motionsEnabled)
        for index, motion in enumerate(self.motions):
            if isinstance(motion, HAnimMotion):
                motion.drive(self, index >= len(enabled) or bool(enabled[index]))
        for pose in self.children:
            if isinstance(pose, HAnimPose):
                pose.drive(self)

    def pose(self) -> Pose:
        """The palette and displacer weights of the joints as they stand now"""
        found = self.rig()
        held = cache.CACHE.getHolder(self, POSE_KEY)
        if held is not None and held.data is not None:
            current: Pose = held.data
            return current
        worlds = np.empty((len(found.chain), 4, 4))
        for row, (item, parent) in enumerate(found.chain):
            local = item.localMatrices().data[0]
            local = np.eye(4) if local is None else np.asarray(local, dtype=np.float64)
            worlds[row] = local if parent < 0 else local @ worlds[parent]
        palette = np.empty((len(found.joints) + 1, 4, 4))
        palette[_rig().REST_JOINT] = np.eye(4)
        for number, row in enumerate(found.rows):
            placed = worlds[row] if row >= 0 else np.eye(4)
            palette[number + 1] = found.bindings[number] @ placed
        pose = Pose(palette, np.array([float(item.weight) for item in found.displacers]))
        if held is None:
            held = cache.CACHE.holder(self, pose, POSE_KEY)
            for item, name in found.posing:
                held.depend(item, name)
        else:
            held.data = pose
        return pose

    def poseHolder(self) -> Any:
        """The cache entry the pose is kept in, cleared when a joint moves"""
        self.pose()
        return cache.CACHE.getHolder(self, POSE_KEY)

    def joint(self, name: str) -> Any:
        """The joint of standard name (or alias) `name`; None where the humanoid has none"""
        return self.rig().named.get(_rig().canonical_joint(name))

    # -- time ---------------------------------------------------------------
    def bind(self, context: Any) -> bool:
        """Poll this humanoid's motions and poses through `context`"""
        self.rig()
        for item in list(self.motions) + list(self.children):
            if isinstance(item, (HAnimMotion, HAnimPose)):
                item.bind(context)
        return True


def _set_joint(joint: Any, translation: Any, rotation: Any, scale: Any) -> None:
    if translation is not None:
        joint.translation = translation
    if rotation is not None:
        joint.rotation = rotation
    if scale is not None:
        joint.scale = scale


class HAnimMotion(Polled, EngineTimed, x3d.HAnimMotion):
    """X3D's HAnimMotion: BVH-style channel data played onto a humanoid's joints

    Plays while `enabled`, from `frameIndex`, `frameIncrement` frames each
    `frameDuration` seconds between `startFrame` and `endFrame` (the last
    frame where `endFrame` is not after `startFrame`), again from the other
    end where `loop` is true. Between frames the joints are interpolated.
    `next` and `previous` step by `frameIncrement`; setting `frameIndex`
    moves there. `frameIndex`, `frameCount`, `cycleTime` and `elapsedTime`
    are sent as it plays. A channel group whose `channelsEnabled` entry is
    false, or whose joint is above the motion's `loa`, drives nothing.
    """

    def __init__(self, *args: Any, **named: Any) -> None:
        super().__init__(*args, **named)
        for name in ('frameIndex', 'enabled', 'frameDuration', 'frameIncrement',
                     'startFrame', 'endFrame', 'loop'):
            dispatcher.connect(self._onSet, signal=('set', protofunctions.getField(self, name)),
                               sender=self)

    # -- what it drives -----------------------------------------------------
    def drive(self, humanoid: HAnimHumanoid, enabled: bool = True) -> None:
        """Drive `humanoid`'s joints, or stop driving them where `enabled` is false"""
        driven: 'weakref.WeakSet[Any]' = self.__dict__.setdefault('_driven', weakref.WeakSet())
        if enabled:
            driven.add(humanoid)
        else:
            driven.discard(humanoid)

    def humanoids(self) -> list[HAnimHumanoid]:
        """The humanoids this motion drives"""
        return list(self.__dict__.get('_driven', ()))

    def channelData(self) -> MotionChannels:
        """The channels, read again once `joints`, `channels` or `values` is set"""
        found: Optional[MotionChannels] = cache.CACHE.getData(self, CHANNELS_KEY)
        if found is None:
            found = _rig().MotionChannels(self.joints, self.channels, self.values)
            holder = cache.CACHE.holder(self, found, CHANNELS_KEY)
            for name in ('joints', 'channels', 'values'):
                holder.depend(self, name)
            if self.__dict__.get('frameCount') != found.frames:
                self.frameCount = found.frames
        return found

    def frameRange(self) -> tuple[int, int]:
        """The first and last frames played"""
        last = max(self.channelData().frames - 1, 0)
        first = min(max(int(self.startFrame), 0), last)
        end = int(self.endFrame)
        return first, (end if first < end <= last else last)

    # -- playing ----------------------------------------------------------
    def _write(self, name: str, value: Any) -> None:
        self.__dict__['_writing'] = True
        try:
            setattr(self, name, value)
        finally:
            self.__dict__['_writing'] = False

    def _onSet(self, value: Any = None, signal: Any = None) -> None:
        if self.__dict__.get('_writing'):
            return
        name = signal[1].name if signal else ''
        now = self.now()
        if name == 'enabled' and not value:
            self.__dict__['_playing'] = False
            return
        if name == 'frameIndex':
            self.goTo(float(value), now)
            return
        if 'position' in self.__dict__:
            self._start(now, self.__dict__['position'])

    def _start(self, now: float, frame: float) -> None:
        self.__dict__.update(start=now, origin=frame, position=frame, cycles=0,
                             _playing=bool(self.enabled))

    def goTo(self, frame: float, now: Optional[float] = None) -> None:
        """Move to `frame`: play on from it, or show it where play has ended"""
        first, last = self.frameRange()
        frame = min(max(float(frame), first), last)
        now = self.now() if now is None else now
        playing = self.__dict__.get('_playing', False)
        self._start(now, frame)
        self.__dict__['_playing'] = playing
        self._apply(frame)

    def _step(self, direction: int) -> None:
        first, last = self.frameRange()
        increment = int(self.frameIncrement) or 1
        frame = int(math.floor(self.__dict__.get('position', float(self.frameIndex))))
        target = frame + increment * direction
        if target > last or target < first:
            if not self.loop:
                return
            target = first if target > last else last
        self.goTo(target)

    def on_next(self, value: Any) -> None:
        if value:
            self._step(1)

    def on_previous(self, value: Any) -> None:
        if value:
            self._step(-1)

    def advance(self, now: float) -> int:
        """Play on to `now`; 1 where joints were moved"""
        if not self.enabled or not self.humanoids() or not self.channelData().frames:
            return 0
        if 'position' not in self.__dict__:
            first, last = self.frameRange()
            self._start(now, min(max(float(self.frameIndex), first), last))
            self._write('cycleTime', now)
        if not self.__dict__.get('_playing'):
            return 0
        first, last = self.frameRange()
        position, finished, cycles = _rig().motion_frame(
            now - self.__dict__['start'], self.__dict__['origin'], float(self.frameDuration),
            int(self.frameIncrement), first, last, bool(self.loop))
        self.__dict__['position'] = position
        self._apply(position)
        if cycles != self.__dict__['cycles']:
            self.__dict__['cycles'] = cycles
            self._write('cycleTime', now)
        self._write('elapsedTime', now - self.__dict__['start'])
        if finished:
            self.__dict__['_playing'] = False
        return 1

    def _apply(self, position: float) -> None:
        data = self.channelData()
        index = int(math.floor(position + 1e-9))
        if int(self.frameIndex) != index:
            self._write('frameIndex', index)
        enabled = list(self.channelsEnabled)
        values = data.sample(position)
        loa = int(self.loa)
        for humanoid in self.humanoids():
            named = humanoid.rig().named
            for group, (name, sample) in enumerate(zip(data.names, values, strict=True)):
                if name is None or (group < len(enabled) and not enabled[group]):
                    continue
                if not _rig().within_level(name, loa):
                    continue
                joint = named.get(name)
                if joint is not None:
                    _set_joint(joint, *sample)


class HAnimPose(Polled, EngineTimed, x3d.HAnimPose):
    """X3D's HAnimPose: a humanoid's joints moved to the values of the joints it holds

    `commencePose` true or `set_startTime` moves each joint the pose names to
    the pose's translation, rotation and scale over `transitionDuration`
    seconds (at once where that is zero), sending `isActive` as it starts and
    ends; `set_fraction` sets how far along that move the joints are.
    `resetAllJoints` true moves every joint back to the values it had when the
    humanoid was read. A pose with no joints resets every joint. Joints above
    the pose's `loa` are not moved. The humanoid is the one holding the pose
    in its `children`.
    """

    def drive(self, humanoid: HAnimHumanoid) -> None:
        """Move `humanoid`'s joints"""
        driven: 'weakref.WeakSet[Any]' = self.__dict__.setdefault('_driven', weakref.WeakSet())
        driven.add(humanoid)

    def humanoids(self) -> list[HAnimHumanoid]:
        """The humanoids this pose moves"""
        return list(self.__dict__.get('_driven', ()))

    def _prepare(self, reset: bool) -> None:
        targets = {_rig().canonical_joint(item.name): item for item in self.children
                   if isinstance(item, x3d.HAnimJoint)}
        loa = int(self.loa)
        moves = []
        for humanoid in self.humanoids():
            joints = []
            begin: list[tuple] = []
            end: list[tuple] = []
            for name, joint in humanoid.rig().named.items():
                if not _rig().within_level(name, loa):
                    continue
                if reset or not targets:
                    goal = humanoid.restValues(joint)
                elif name in targets:
                    target = targets[name]
                    goal = (tuple(target.translation), _rotation(target.rotation),
                            tuple(target.scale))
                else:
                    continue
                joints.append(joint)
                begin.append((tuple(joint.translation), _rotation(joint.rotation),
                              tuple(joint.scale)))
                end.append(goal)
            if joints:
                moves.append((joints, _rig().JointValues.of(*zip(*begin, strict=True)),
                              _rig().JointValues.of(*zip(*end, strict=True))))
        self.__dict__['_moves'] = moves

    def _applyAt(self, fraction: float) -> None:
        for joints, begin, end in self.__dict__.get('_moves', ()):
            values = _rig().blend_values(begin, end, fraction)
            for row, joint in enumerate(joints):
                _set_joint(joint, tuple(values.translations[row]),
                           tuple(values.rotations[row]), tuple(values.scales[row]))

    def begin(self, reset: bool = False) -> None:
        """Start moving the joints to the pose, or back to their first values where `reset`"""
        if not self.enabled:
            return
        self._prepare(reset)
        duration = float(self.transitionDuration)
        if duration <= 0:
            self._applyAt(1.0)
            return
        self.__dict__.update(_started=self.now(), _active=True)
        self.isActive = True

    def on_commencePose(self, value: Any) -> None:
        if value:
            self.begin()

    def on_set_startTime(self, value: Any) -> None:
        self.begin()

    def on_resetAllJoints(self, value: Any) -> None:
        if value:
            self.begin(reset=True)

    def on_set_fraction(self, value: Any) -> None:
        if not self.enabled:
            return
        if '_moves' not in self.__dict__:
            self._prepare(False)
        self._applyAt(float(value))

    def advance(self, now: float) -> int:
        """Move the joints on to `now`; 1 where they moved"""
        if not self.__dict__.get('_active'):
            return 0
        part = (now - self.__dict__['_started']) / float(self.transitionDuration or 1.0)
        self._applyAt(part)
        if part >= 1.0:
            self.__dict__['_active'] = False
            self.isActive = False
        return 1
