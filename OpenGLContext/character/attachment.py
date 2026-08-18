"""Attachment points: where a weapon, a tool or a hat goes on a rig.

glTF has no extension for this, and it needs none. A node parented to a joint
already inherits that joint's animated transform, so an **empty node under the
joint, named for what it holds** is an attachment point in the format's own
terms -- it survives every exporter, every importer and every validator,
because it is nothing but a node.

The convention this reads is a name prefix, ``socket_`` by default: a node
called ``socket_grip`` under the right hand is the point called ``grip``. What a
particular model must carry is the model's contract to state; what this module
provides is finding those points and putting something on one.

**The convention has two sides.** On a rig, ``socket_grip`` is *where a thing
goes*. On the thing, a node of the same name is *where it is held* -- the grip
its own artist put on it, rather than wherever its origin happens to sit.
:func:`mounted` lines the two up, so a rifle sits in a fist instead of hanging
off it, and a game needs no table of per-model offsets to make that true. Both
sides are ordinary named nodes: nothing in the file says "socket", so nothing
can fail to read one.

Anything mounted is an ordinary scenegraph node, so a weapon loaded from its
own file goes straight on::

    weapon = load_gltf('handgun.glb')
    attach(sockets(scene)['grip'], mounted(weapon, 'grip'))

Where a model declares no attachment point, a humanoid bone is the fallback:
:meth:`OpenGLContext.character.humanoid.Humanoid.transform` returns the joint
itself, and hanging a weapon on ``rightHand`` puts it in the hand -- at the
joint rather than at a grip the artist placed, which is the difference the
named point buys.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from OpenGLContext import quaternion
from OpenGLContext.loaders.gltf.animation import compute_world_matrices
from OpenGLContext.scenegraph.transform import Transform

__all__ = ['SOCKET_PREFIX', 'sockets', 'mounted', 'attach', 'detach']

#: What an attachment point's node name starts with.
SOCKET_PREFIX = 'socket_'


def sockets(scene: Any, prefix: str = SOCKET_PREFIX) -> Dict[str, Any]:
    """The attachment points a loaded glTF declares, by the name after ``prefix``.

    ``scene`` is a :class:`~OpenGLContext.loaders.gltf.scene.GLTFScene`. The
    values are the ``Transform`` nodes to mount things on, so the result is
    ready to hand to :func:`attach`.
    """
    names = getattr(scene, 'node_names', None) or {}
    transforms = getattr(scene, 'node_transforms', None) or {}
    out: Dict[str, Any] = {}
    for index, name in sorted(names.items()):
        if name.startswith(prefix):
            transform = transforms.get(index)
            if transform is not None:
                out.setdefault(name[len(prefix):], transform)
    return out


def mounted(scene: Any, point: str = 'grip',
            prefix: str = SOCKET_PREFIX) -> Optional[Any]:
    """``scene``'s drawable, placed so the point *it* declares is at the origin.

    The other half of an attachment point. A rig says where a thing goes; the
    thing says where it is held -- by carrying a node of the same name, at the
    grip its artist put there. Lining the two up is what lets a rifle sit in a
    fist rather than hang off it by whatever the modeller happened to make the
    origin, and it is the model's own business rather than a table of offsets
    every game that loads it has to keep::

        weapon = load_gltf('sniper-rifle.glb')
        attach(sockets(scene)['grip'], mounted(weapon, 'grip'))

    A model may declare several -- ``socket_grip`` for the hand, ``socket_back``
    for how it stows -- and which one is read is the point it is going on, so
    the same file hangs correctly in both places.

    A model that declares nothing is mounted by its own origin, which is what
    every model did before it could say otherwise: the answer is then
    ``scene.group`` itself, with no wrapper to draw.
    """
    group = getattr(scene, 'group', None)
    names = getattr(scene, 'node_names', None) or {}
    wanted = prefix + point
    index = next((i for i, name in sorted(names.items()) if name == wanted), None)
    if group is None or index is None:
        return group
    worlds = compute_world_matrices(getattr(scene, 'node_roots', ()) or (),
                                    getattr(scene, 'node_children', None) or {},
                                    getattr(scene, 'node_transforms', None) or {})
    world = worlds.get(index)
    if world is None:
        return group
    inverse = np.linalg.inv(np.asarray(world, dtype='d'))
    basis = inverse[:3, :3]
    # Row-vector TRS, so each row of the basis is one scaled axis: its length
    # is that axis' scale and what is left is the rotation.
    scale = np.linalg.norm(basis, axis=1)
    scale[scale == 0.0] = 1.0
    axis = np.asarray(quaternion.fromMatrix(basis / scale[:, None]).XYZR(), 'd')
    # A point that is only offset -- which most are -- leaves an axis that is
    # 0/0 and an angle of nothing. Say so rather than passing the noise on.
    length = float(np.linalg.norm(axis[:3]))
    if abs(axis[3]) < 1e-9 or length < 1e-9:
        rotation = (0.0, 1.0, 0.0, 0.0)
    else:
        rotation = (float(axis[0] / length), float(axis[1] / length),
                    float(axis[2] / length), float(axis[3]))
    return Transform(translation=tuple(float(v) for v in inverse[3, :3]),
                     rotation=rotation,
                     scale=tuple(float(v) for v in scale),
                     children=[group])


def attach(point: Any, node: Any) -> Any:
    """Hang ``node`` on ``point``; returns the node.

    Mounting the same node twice leaves it mounted once, so a caller re-arming
    somebody with what they are already holding does not draw two of it.
    """
    children = list(point.children)
    if node not in children:
        point.children = children + [node]
    return node


def detach(point: Any, node: Any) -> bool:
    """Take ``node`` off ``point``; False if it was not on it."""
    children = list(point.children)
    if node not in children:
        return False
    point.children = [child for child in children if child is not node]
    return True
