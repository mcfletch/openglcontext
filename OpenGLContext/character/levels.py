"""Giving a figure a coarser mesh to be drawn as when it is far away.

A character usually ships twice: the mesh it is seen with and a lighter one for
when it is a few dozen metres off, exported from the same armature. Both are
the same body, so what differs is only the geometry -- the skeleton, the clips
and the pose are one thing, computed once, whichever mesh is on screen.

:func:`add_level` is what says so. It reads the coarser document, checks that
its skeleton really is the same one joint for joint, hands its meshes to the
skins that are already being posed, and puts both under an
:class:`~OpenGLContext.scenegraph.lod.LOD` so the renderer draws whichever the
distance calls for::

    model = CharacterModel.load('marine.glb')
    model.add_level('marine_lod1.glb', 25.0)

Nothing else changes: the model plays and poses exactly as before, and a crowd
of figures batches by whichever level each of them is showing -- the near ones
in one instanced draw and the far ones in another.

**A level that does not match is refused**, not adapted. A coarse mesh skinned
to a different joint order would be posed by the wrong bones, and a figure
whose elbow is driven by its hip is worse than a figure drawn at full detail.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

# The engine's own Group, which is what offers ``renderedChildren``: the
# renderer walks a scenegraph by asking each node for that and nothing else, so
# a level wrapped in the plain VRML97 node is a level it never descends into.
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.lod import LOD

log = logging.getLogger(__name__)

__all__ = ['add_level', 'levels_match']


def levels_match(fine: Any, coarse: Any) -> bool:
    """Whether ``coarse`` is the same skeleton as ``fine``, joint for joint.

    Names rather than indices: two exports of one armature agree on what a
    joint is called, and an index means nothing without the document it came
    from.
    """
    fine_skins, coarse_skins = list(fine.skins or ()), list(coarse.skins or ())
    if not fine_skins or len(fine_skins) != len(coarse_skins):
        return False
    for one, other in zip(fine_skins, coarse_skins, strict=True):
        if _joint_names(fine, one) != _joint_names(coarse, other):
            return False
    return True


def _joint_names(scene: Any, skin: Any) -> List[Optional[str]]:
    names = getattr(scene, 'node_names', None) or {}
    return [names.get(int(joint)) for joint in skin.joints]


def add_level(model: Any, source: Any, distance: float,
              document: Any = None, **named: Any) -> bool:
    """Draw ``source``'s meshes instead of the model's own beyond ``distance``.

    ``source`` is anything :func:`~OpenGLContext.loaders.gltf.load_gltf` takes,
    or an already-loaded scene; ``document`` passes a shared parse, as
    everywhere else. Returns whether the level was taken -- False, with a
    warning, where its skeleton is not the model's.
    """
    scene = source if hasattr(source, 'skins') else _load(source, document, named)
    if not levels_match(model.scene, scene):
        log.warning(
            'level of detail refused: %s is not skinned to the same skeleton',
            getattr(scene, 'name', source))
        return False
    ranges = _ranges(model, distance)
    for fine, coarse in zip(model.scene.skins, scene.skins, strict=True):
        if not _adopt(model, fine, coarse, scene, ranges):
            return False
    return True


def _load(source: Any, document: Any, named: dict) -> Any:
    from OpenGLContext.loaders.gltf import load_gltf
    if document is not None:
        return load_gltf(document=document, **named)
    return load_gltf(source, **named)


def _ranges(model: Any, distance: float) -> Sequence[float]:
    """The distance list an LOD of this model's levels wants."""
    return [float(distance)]


def _adopt(model: Any, fine: Any, coarse: Any, scene: Any,
           ranges: Sequence[float]) -> bool:
    """Put one skin's coarse meshes under the fine one's node, behind an LOD."""
    node = model.scene.node_transforms.get(int(fine.mesh_node))
    other = scene.node_transforms.get(int(coarse.mesh_node))
    if node is None or other is None:
        log.warning('level of detail refused: a skinned mesh has no node')
        return False
    if not _placed_alike(node, other):
        # The joint matrices cancel the mesh node's own transform, so a coarse
        # mesh drawn under the fine node has to have been modelled about the
        # same origin. Two exports of one rig are; anything else would be drawn
        # displaced.
        log.warning('level of detail refused: the meshes are placed differently')
        return False
    fine_children = list(node.children)
    coarse_children = list(other.children)
    if not fine_children or not coarse_children:
        return False
    node.children = [LOD(
        level=[Group(children=fine_children), Group(children=coarse_children)],
        range=list(ranges))]
    # Both levels are posed by the skin that was already being posed, so the
    # pose is computed once however many levels a figure carries -- and they
    # read one joint palette between them, since what they are handed is the
    # same matrices.
    peer = fine.meshes[0] if fine.meshes else None
    for mesh in coarse.meshes:
        mesh._palette_peer = peer
    fine.meshes = list(fine.meshes) + list(coarse.meshes)
    return True


def _placed_alike(one: Any, other: Any, tolerance: float = 1e-5) -> bool:
    for field in ('translation', 'scale'):
        first = [float(v) for v in getattr(one, field, (0.0, 0.0, 0.0))]
        second = [float(v) for v in getattr(other, field, (0.0, 0.0, 0.0))]
        if any(abs(a - b) > tolerance for a, b in zip(first, second, strict=True)):
            return False
    return _same_rotation(getattr(one, 'rotation', None),
                          getattr(other, 'rotation', None), tolerance)


def _same_rotation(one: Any, other: Any, tolerance: float) -> bool:
    if one is None or other is None:
        return one is other
    from OpenGLContext.loaders.gltf.animation import vrml_to_quat_xyzw
    first, second = vrml_to_quat_xyzw(one), vrml_to_quat_xyzw(other)
    # A quaternion and its negation are one rotation.
    same = max(abs(a - b) for a, b in zip(first, second, strict=True))
    opposite = max(abs(a + b) for a, b in zip(first, second, strict=True))
    return bool(same <= tolerance or opposite <= tolerance)
