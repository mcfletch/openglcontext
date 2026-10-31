"""The engine's Cloth and Ragdoll nodes: a soft body and a ragdoll declared in a document.

X3D's RigidBodyPhysics and HAnim components have no cloth and no ragdoll, so
both are nodes of the engine's own component, ``OpenGLContext``
(:mod:`vrml.x3d.components`): an X3D document of any encoding names them, a
scene holding one is written with ``COMPONENT OpenGLContext:1``, and another
browser reads the document without them.

A ``Cloth`` is a group whose first ``Shape`` becomes a soft body when a
context draws it (:meth:`Physics.add_soft_mesh
<OpenGLContext.physics.service.Physics.add_soft_mesh>`): its geometry is
welded by position and simulated, placed by ``translation`` and ``rotation``,
with the vertices in ``pinned`` held where they start and a ``wind`` force
(N) blowing on it. ``pressure`` (Pa m3) holds a closed mesh round. The
cloth's vertices are world positions: put a Cloth in no Transform.

A ``Ragdoll`` draws the glTF character its ``url`` names and gives its
skeleton a ragdoll (:class:`~OpenGLContext.character.ragdoll.RagdollFigure`),
placed by ``translation`` and ``rotation``. ``mode`` is ``KINEMATIC`` (the
skeleton follows the model's first clip), ``POWERED`` (motors hold the clip's
pose against blows) or ``LIMP``; setting it changes mode over ``blend``
seconds. ``mass`` is kg; ``rootForce`` and ``rootTorque`` hold a powered
ragdoll up.

Both are stepped through each context that draws them, and let go of their
bodies when no context does.
"""
from __future__ import annotations

import logging
import weakref
from typing import Any

import numpy as np
from vrml import field, node
from vrml.vrml97 import nodetypes
from vrml.x3d import components

from OpenGLContext.events import systemtime
from OpenGLContext.events.renderqueue import DEFER
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.scenegraph import grouping

__all__ = ['Cloth', 'Ragdoll', 'rotation_quaternion']

log = logging.getLogger(__name__)


def rotation_quaternion(rotation: Any) -> tuple[float, float, float, float]:
    """An X3D SFRotation (axis, angle) as a quaternion ``(x, y, z, w)``."""
    x, y, z, angle = (float(v) for v in rotation)
    length = float(np.sqrt(x * x + y * y + z * z))
    if length == 0.0 or angle == 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    s = float(np.sin(angle / 2.0)) / length
    return (x * s, y * s, z * s, float(np.cos(angle / 2.0)))


class _Bound:
    """A node stepped once a frame through each context that draws it."""

    def bind(self, context: Any) -> bool:
        """Start the node's simulation in ``context`` and step it from the next frame."""
        contexts = self.__dict__.setdefault('_contexts', weakref.WeakSet())
        if context in contexts:
            return True
        contexts.add(context)
        try:
            self.start(context)
        except Exception:
            log.exception('%s is not simulated', self)
            return True
        context.renderQueue.call(self.tick, context)
        return True

    def unbindContext(self, context: Any) -> None:
        """Stop stepping through ``context`` and let go of the node's bodies there."""
        contexts = self.__dict__.setdefault('_contexts', weakref.WeakSet())
        if context in contexts:
            contexts.discard(context)
            self.stop(context)

    def tick(self, context: Any) -> Any:
        """One frame's step; DEFER while bound, so the next frame steps again."""
        if context not in self.__dict__.get('_contexts', ()):
            return None
        if self.step(context):
            context.triggerRedraw(1)
        return DEFER

    def start(self, context: Any) -> None:
        raise NotImplementedError

    def stop(self, context: Any) -> None:
        raise NotImplementedError

    def step(self, context: Any) -> bool:
        raise NotImplementedError


class Cloth(_Bound, grouping.Grouping, nodetypes.Grouping, nodetypes.Children, node.Node):
    """A group whose first Shape is simulated as a soft body; see the module docstring."""

    PROTO = 'Cloth'
    COMPONENT = ('OpenGLContext', 1)
    SINCE = '4.0'
    CONTAINER_FIELD = 'children'
    addChildren = field.newEvent('addChildren', 'MFNode', 0)
    removeChildren = field.newEvent('removeChildren', 'MFNode', 0)
    bboxCenter = field.newField('bboxCenter', 'SFVec3f', 0, [0.0, 0.0, 0.0])
    bboxSize = field.newField('bboxSize', 'SFVec3f', 0, [-1.0, -1.0, -1.0])
    enabled = field.newField('enabled', 'SFBool', 1, True)
    translation = field.newField('translation', 'SFVec3f', 1, [0.0, 0.0, 0.0])
    rotation = field.newField('rotation', 'SFRotation', 1, [0.0, 0.0, 1.0, 0.0])
    mass = field.newField('mass', 'SFFloat', 1, 1.0)
    compliance = field.newField('compliance', 'SFFloat', 1, 0.0)
    bendCompliance = field.newField('bendCompliance', 'SFFloat', 1, 0.01)
    pressure = field.newField('pressure', 'SFFloat', 1, 0.0)
    linearDamping = field.newField('linearDamping', 'SFFloat', 1, 0.1)
    friction = field.newField('friction', 'SFFloat', 1, 0.2)
    vertexRadius = field.newField('vertexRadius', 'SFFloat', 1, 0.0)
    pinned = field.newField('pinned', 'MFInt32', 1, list)
    wind = field.newField('wind', 'SFVec3f', 1, [0.0, 0.0, 0.0])

    def _shape(self) -> Any:
        for child in self.children:
            if getattr(child, 'geometry', None) is not None:
                return child
        return None

    def start(self, context: Any) -> None:
        if not self.enabled:
            return
        shape = self._shape()
        if shape is None:
            raise ValueError('a Cloth simulates its first Shape, and it has none')
        mesh = _simulable(shape)
        place = np.asarray(self.translation, dtype='d')
        turn = rotation_quaternion(self.rotation)
        pins = None
        if len(self.pinned):
            from OpenGLContext.physics.ragdolls import quat_rotate  # noqa: PLC0415 beside its use
            vertices = np.asarray(self.pinned, dtype=np.intp)
            points = quat_rotate(turn, np.asarray(mesh.positions, dtype='d')[vertices]) + place
            pins = (vertices, points)
        made = context.physics.add_soft_mesh(
            mesh, place, turn, pins=pins, mass=float(self.mass),
            compliance=float(self.compliance), bend_compliance=float(self.bendCompliance),
            pressure=float(self.pressure), linear_damping=float(self.linearDamping),
            friction=float(self.friction), vertex_radius=float(self.vertexRadius))
        self.__dict__.setdefault('_soft', weakref.WeakKeyDictionary())[context] = made
        self.__dict__.setdefault('_wind', weakref.WeakKeyDictionary())[context] = (0.0, 0.0, 0.0)

    def soft_mesh(self, context: Any) -> Any:
        """The :class:`~OpenGLContext.physics.softmesh.SoftMesh` simulating this cloth in ``context``, or None."""
        return self.__dict__.get('_soft', {}).get(context)

    def stop(self, context: Any) -> None:
        made = self.__dict__.get('_soft', {}).pop(context, None)
        if made is not None:
            made.remove()

    def step(self, context: Any) -> bool:
        made = self.soft_mesh(context)
        if made is None:
            return False
        wind = tuple(float(v) for v in self.wind)
        if self.__dict__['_wind'].get(context) != wind:
            self.__dict__['_wind'][context] = wind
            made.soft.set_wind(wind)
        return False


def _simulable(shape: Any) -> Any:
    """The PBRMesh a Shape draws, made from its geometry's triangles where it draws another."""
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh  # noqa: PLC0415 the mesh module loads GL
    geometry = shape.geometry
    if isinstance(geometry, PBRMesh):
        return geometry
    found = geometry.meshArrays() if hasattr(geometry, 'meshArrays') else None
    if found is None:
        raise ValueError('a Cloth simulates triangles, and %s has none' % (geometry,))
    attributes = found.attributes
    mesh = PBRMesh(positions=attributes['POSITION'], normals=attributes.get('NORMAL'),
                   texcoords=attributes.get('TEXCOORD_0'), indices=found.indices, solid=False)
    shape.geometry = mesh
    return mesh


class Ragdoll(_Bound, grouping.Grouping, nodetypes.Grouping, nodetypes.Children, node.Node):
    """A glTF character with a ragdoll for a skeleton; see the module docstring."""

    PROTO = 'Ragdoll'
    COMPONENT = ('OpenGLContext', 1)
    SINCE = '4.0'
    CONTAINER_FIELD = 'children'
    addChildren = field.newEvent('addChildren', 'MFNode', 0)
    removeChildren = field.newEvent('removeChildren', 'MFNode', 0)
    bboxCenter = field.newField('bboxCenter', 'SFVec3f', 0, [0.0, 0.0, 0.0])
    bboxSize = field.newField('bboxSize', 'SFVec3f', 0, [-1.0, -1.0, -1.0])
    enabled = field.newField('enabled', 'SFBool', 1, True)
    url = field.newField('url', 'MFString', 1, list)
    translation = field.newField('translation', 'SFVec3f', 1, [0.0, 0.0, 0.0])
    rotation = field.newField('rotation', 'SFRotation', 1, [0.0, 0.0, 1.0, 0.0])
    mode = field.newField('mode', 'SFString', 1, 'KINEMATIC')
    blend = field.newField('blend', 'SFTime', 1, 0.0)
    mass = field.newField('mass', 'SFFloat', 1, 70.0)
    rootForce = field.newField('rootForce', 'SFFloat', 1, 0.0)
    rootTorque = field.newField('rootTorque', 'SFFloat', 1, 0.0)

    def renderedChildren(self, types: Any = (nodetypes.Children, nodetypes.Rendering)) -> list[Any]:
        model = self.__dict__.get('_model')
        found = super().renderedChildren(types)
        return ([model.group] if model is not None else []) + list(found)

    def start(self, context: Any) -> None:
        if not self.enabled or not self.url:
            return
        from OpenGLContext.character.model import CharacterModel  # noqa: PLC0415 loads glTF on use
        from OpenGLContext.character.ragdoll import RagdollFigure  # noqa: PLC0415 beside it
        model = self.__dict__.get('_model')
        if model is None:
            model = CharacterModel.load(str(self.url[0]))
            if model.clips:
                model.play(sorted(model.clips)[0])
            self.__dict__['_model'] = model
            group = model.group
            group.translation = tuple(float(v) for v in self.translation)
            group.rotation = tuple(float(v) for v in self.rotation)
        placement = _placement(self.translation, self.rotation)
        figure = RagdollFigure(context.physics, model, mode=str(self.mode).lower(),
                               placement=placement, mass=float(self.mass),
                               root_force=float(self.rootForce),
                               root_torque=float(self.rootTorque))
        self.__dict__.setdefault('_figures', weakref.WeakKeyDictionary())[context] = figure
        self.__dict__.setdefault('_modes', weakref.WeakKeyDictionary())[context] = str(self.mode)

    def figure(self, context: Any) -> Any:
        """The :class:`~OpenGLContext.character.ragdoll.RagdollFigure` of this node in ``context``, or None."""
        return self.__dict__.get('_figures', {}).get(context)

    def stop(self, context: Any) -> None:
        figure = self.__dict__.get('_figures', {}).pop(context, None)
        if figure is not None:
            figure.remove()

    def step(self, context: Any) -> bool:
        figure = self.figure(context)
        if figure is None:
            return False
        mode = str(self.mode)
        if self.__dict__['_modes'].get(context) != mode:
            self.__dict__['_modes'][context] = mode
            figure.following = mode.upper() != 'LIMP'
            figure.set_mode(mode.lower(), float(self.blend))
        now = systemtime.systemTime()
        last = self.__dict__.setdefault('_times', weakref.WeakKeyDictionary()).get(context, now)
        self.__dict__['_times'][context] = now
        figure.update(max(0.0, now - last))
        figure.draw()
        return True


def _placement(translation: Any, rotation: Any) -> np.ndarray:
    """The row-vector world matrix of a translation and an SFRotation."""
    from OpenGLContext.character.rig import quat_to_matrices  # noqa: PLC0415 the rig's arithmetic
    matrix = np.eye(4)
    matrix[:3, :3] = quat_to_matrices(np.array([rotation_quaternion(rotation)]))[0]
    matrix[3, :3] = np.asarray(translation, dtype='d')
    return matrix


#: What a glTF document names the cloth hook (``OGLC_hook``), and the Cloth field each parameter sets.
CLOTH_HOOK = 'cloth'
CLOTH_PARAMETERS: dict[str, str] = {
    'mass': 'mass', 'compliance': 'compliance', 'bendCompliance': 'bendCompliance',
    'pressure': 'pressure', 'linearDamping': 'linearDamping', 'friction': 'friction',
    'vertexRadius': 'vertexRadius',
}


def cloth_hook(ctx: Any) -> Any:
    """A glTF node tagged ``cloth`` as a Cloth in its place, holding the node's children.

    The parameters are the Cloth's fields: the numbers above, ``pinned`` (a
    list of the mesh's vertex indices) and ``wind`` (three numbers, N). The
    node's placement becomes the cloth's ``translation`` and ``rotation``. A
    tag on a material is not read.
    """
    if ctx.at != 'node':
        return None
    values = ctx.values
    fields: dict[str, Any] = {}
    defaults = {name: float(getattr(Cloth, name).defaultobj) for name in CLOTH_PARAMETERS.values()}
    for key, name in CLOTH_PARAMETERS.items():
        if key in ctx.params:
            fields[name] = values.number(ctx.params[key], defaults[name], 'cloth %s' % key,
                                         minimum=0.0)
    if 'pinned' in ctx.params:
        fields['pinned'] = [int(v) for v in values.array(ctx.params['pinned'], 'cloth pinned')
                            if isinstance(v, int) and v >= 0]
    if 'wind' in ctx.params:
        fields['wind'] = values.vector(ctx.params['wind'], (0.0, 0.0, 0.0), 'cloth wind')
    matrix = np.eye(4) if ctx.local_matrix is None else np.asarray(ctx.local_matrix, dtype='d')
    from OpenGLContext.character.ragdoll import matrix_quaternions  # noqa: PLC0415 beside its use
    x, y, z, w = (float(v) for v in matrix_quaternions(matrix[None, :3, :3])[0])
    angle = 2.0 * float(np.arccos(np.clip(w, -1.0, 1.0)))
    axis = (x, y, z) if (x or y or z) else (0.0, 0.0, 1.0)
    cloth = Cloth(children=list(ctx.children), translation=tuple(matrix[3, :3]),
                  rotation=(*axis, angle), **fields)
    return cloth, True


components.register(Cloth, Ragdoll)

hooks.register(CLOTH_HOOK, cloth_hook, shareable=False)
