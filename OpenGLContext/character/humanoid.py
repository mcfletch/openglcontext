"""The humanoid skeleton a character rig is addressed through.

A game asks for "the right hand" or "everything above the waist"; a glTF file
offers node indices and whatever names its author typed. This is the map
between the two, and it uses **VRM 1.0's humanoid bone vocabulary** -- the
55 names in ``VRMC_vrm.humanoid.humanBones``, their required subset and their
fixed parent chain -- rather than a vocabulary of our own, because a name that
an avatar toolchain already knows is a name an asset can arrive carrying.

Three sources are consulted, in this order:

1. ``VRMC_vrm``: an avatar that states its own bone map. Authoritative --
   nothing guesses over an answer the file gives.
2. ``VRMC_vrm_animation``: the same map in a clip-only document (``.vrma``),
   which is how a retargetable animation names the joints it drives.
3. **The joint names**, through :func:`bones_by_name`, which reads the
   conventions in circulation -- VRM's own, Mixamo's, Unreal's, Blender's
   Rigify and the numbered joint chains the Khronos rigged samples use. Where
   one name alone is ambiguous the *rig* is recognised instead, by the company
   the name keeps: see :data:`FAMILIES`.

The third is what makes an ordinary rigged glTF usable without any extension at
all, and it is what most content is. See :doc:`the character documentation
<../../docs/characters>` for the naming a model should carry to be recognised.

A bone map is not a pose. What it buys is addressing: :meth:`Humanoid.transform`
for a joint to hang a weapon on, :meth:`Humanoid.mask` for the set of joints an
animation layer is allowed to move, :meth:`Humanoid.position` for where a bone
has ended up this frame.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

import numpy as np

from OpenGLContext.loaders.gltf.animation import compute_world_matrices

__all__ = [
    'HUMAN_BONES', 'REQUIRED_BONES', 'BONE_PARENT', 'FINGERS', 'FAMILIES',
    'VRM_EXTENSION', 'VRM_ANIMATION_EXTENSION',
    'bone_for_name', 'bones_by_name', 'bones_from_extensions', 'Humanoid',
]

#: The document extension carrying an avatar's own humanoid bone map.
VRM_EXTENSION = 'VRMC_vrm'
#: The same map in a document that is only animation.
VRM_ANIMATION_EXTENSION = 'VRMC_vrm_animation'

#: The finger names, in the order a hand has them.
FINGERS = ('Thumb', 'Index', 'Middle', 'Ring', 'Little')

#: The segments of a finger. The thumb's first segment is the metacarpal; on
#: every other finger the first segment is the proximal phalanx.
_THUMB_SEGMENTS = ('Metacarpal', 'Proximal', 'Distal')
_FINGER_SEGMENTS = ('Proximal', 'Intermediate', 'Distal')


def _finger_bones() -> Dict[str, Optional[str]]:
    """The thirty finger bones and their parents, both hands."""
    out: Dict[str, Optional[str]] = {}
    for side in ('left', 'right'):
        for finger in FINGERS:
            segments = _THUMB_SEGMENTS if finger == 'Thumb' else _FINGER_SEGMENTS
            parent = '%sHand' % (side,)
            for segment in segments:
                bone = '%s%s%s' % (side, finger, segment)
                out[bone] = parent
                parent = bone
    return out


#: Every humanoid bone, mapped to the bone it hangs from. ``hips`` hangs from
#: nothing: it is the root of the humanoid, whatever a file's node graph puts
#: above it. Bones between two humanoid bones in the file are permitted and are
#: simply not humanoid bones.
BONE_PARENT: Dict[str, Optional[str]] = {
    'hips': None,
    'spine': 'hips',
    'chest': 'spine',
    'upperChest': 'chest',
    'neck': 'upperChest',
    'head': 'neck',
    'leftEye': 'head',
    'rightEye': 'head',
    'jaw': 'head',
    'leftShoulder': 'upperChest',
    'leftUpperArm': 'leftShoulder',
    'leftLowerArm': 'leftUpperArm',
    'leftHand': 'leftLowerArm',
    'rightShoulder': 'upperChest',
    'rightUpperArm': 'rightShoulder',
    'rightLowerArm': 'rightUpperArm',
    'rightHand': 'rightLowerArm',
    'leftUpperLeg': 'hips',
    'leftLowerLeg': 'leftUpperLeg',
    'leftFoot': 'leftLowerLeg',
    'leftToes': 'leftFoot',
    'rightUpperLeg': 'hips',
    'rightLowerLeg': 'rightUpperLeg',
    'rightFoot': 'rightLowerLeg',
    'rightToes': 'rightFoot',
}
BONE_PARENT.update(_finger_bones())

#: Every humanoid bone, parents before children.
HUMAN_BONES: tuple = tuple(BONE_PARENT)

#: The bones a humanoid must have for a clip authored against one rig to mean
#: anything on another: the spine, the head, and both complete limbs.
REQUIRED_BONES = frozenset({
    'hips', 'spine', 'head',
    'leftUpperLeg', 'leftLowerLeg', 'leftFoot',
    'rightUpperLeg', 'rightLowerLeg', 'rightFoot',
    'leftUpperArm', 'leftLowerArm', 'leftHand',
    'rightUpperArm', 'rightLowerArm', 'rightHand',
})


# ======================================================================
# Reading a bone out of a joint's name
# ======================================================================

#: Tokens that name the rig rather than the bone, and are dropped before the
#: rest is matched: exporter prefixes, Rigify's layer tags, the word "joint"
#: itself. Dropping them is what lets one table cover ``DEF-thigh.L``,
#: ``b_LeftLeg01`` and ``Skeleton_arm_joint_R`` alike.
_FILLER = frozenset({
    'def', 'org', 'mch', 'ctrl', 'ik', 'fk', 'tweak',
    'b', 'j', 'f', 'bn', 'bone', 'joint', 'jnt', 'skeleton', 'armature',
    'rig', 'mixamorig', 'character', 'char', 'body', 'deform',
})

_LEFT = frozenset({'left', 'lft', 'l'})
_RIGHT = frozenset({'right', 'rgt', 'r'})

#: Cores that name one bone outright, whichever side of the body they are on.
_PLAIN: Dict[str, str] = {
    'hips': 'hips', 'hip': 'hips', 'pelvis': 'hips',
    'spine': 'spine', 'chest': 'chest', 'ribcage': 'chest',
    'upperchest': 'upperChest',
    'neck': 'neck', 'head': 'head', 'jaw': 'jaw',
}

#: Cores that name one bone only once a chain position is known. A rig that
#: numbers its spine, and the ``<part>_joint_<n>`` chains, land here.
_PLAIN_NUMBERED: Dict[tuple, str] = {
    ('spine', 1): 'chest', ('spine', 2): 'upperChest',
    ('torso', 1): 'hips', ('torso', 2): 'spine', ('torso', 3): 'chest',
    ('neck', 1): 'neck', ('neck', 2): 'head',
}

#: Cores that name a bone once the side is known, as the suffix after the side.
_SIDED: Dict[str, str] = {
    'shoulder': 'Shoulder', 'clavicle': 'Shoulder',
    'upperarm': 'UpperArm', 'arm': 'UpperArm',
    'lowerarm': 'LowerArm', 'forearm': 'LowerArm', 'elbow': 'LowerArm',
    'hand': 'Hand', 'wrist': 'Hand',
    'upperleg': 'UpperLeg', 'upleg': 'UpperLeg', 'thigh': 'UpperLeg',
    'lowerleg': 'LowerLeg', 'leg': 'LowerLeg', 'shin': 'LowerLeg',
    'calf': 'LowerLeg', 'knee': 'LowerLeg',
    'foot': 'Foot', 'ankle': 'Foot',
    'toes': 'Toes', 'toe': 'Toes', 'toebase': 'Toes', 'ball': 'Toes',
    'eye': 'Eye',
}

#: The limb chains a numbered rig writes instead of naming each joint.
_SIDED_NUMBERED: Dict[tuple, str] = {
    ('arm', 1): 'UpperArm', ('arm', 2): 'LowerArm', ('arm', 3): 'Hand',
    ('leg', 1): 'UpperLeg', ('leg', 2): 'LowerLeg', ('leg', 3): 'Foot',
    ('leg', 4): 'Toes', ('leg', 5): 'Toes',
}

#: What a finger is called, mapped to the VRM name for it.
_FINGER_NAMES: Dict[str, str] = {
    'thumb': 'Thumb', 'index': 'Index', 'middle': 'Middle', 'ring': 'Ring',
    'little': 'Little', 'pinky': 'Little',
}

#: What a finger *segment* is called when a rig spells it out rather than
#: numbering it.
_SEGMENT_NAMES: Dict[str, str] = {
    'metacarpal': 'Metacarpal', 'proximal': 'Proximal',
    'intermediate': 'Intermediate', 'medial': 'Intermediate',
    'distal': 'Distal',
}

#: Split a name into words: on punctuation, and at every lower-to-upper and
#: letter-to-digit boundary, so ``LeftUpLeg``, ``upper_arm.L`` and ``f_index.02``
#: all come apart into the words they are made of.
_WORDS = re.compile(r'[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|[0-9]+')


def _words(name: str) -> List[str]:
    """The lower-case words of a joint name, namespace and filler removed."""
    for separator in (':', '|'):
        if separator in name:
            name = name.rsplit(separator, 1)[-1]
    return [word.lower() for word in _WORDS.findall(name)]


def bone_for_name(name: str) -> Optional[str]:
    """The humanoid bone a joint name denotes, or None if it denotes none.

    Reads the naming conventions in circulation rather than one of them: a side
    may lead or trail and may be spelled out or abbreviated, a chain position
    may be a number or a word, and the rig's own prefixes are ignored. A name
    that needs a side and carries none -- a bare ``UpperArm`` -- is not a bone,
    because guessing which arm it is would be guessing.
    """
    words = _words(name)
    side: Optional[str] = None
    number: Optional[int] = None
    core: List[str] = []
    for word in words:
        if word in _LEFT and side is None:
            side = 'left'
        elif word in _RIGHT and side is None:
            side = 'right'
        elif word.isdigit():
            number = int(word)
        elif word not in _FILLER:
            core.append(word)
    return _bone_for_words(core, side, number)


def _bone_for_words(core: List[str], side: Optional[str],
                    number: Optional[int]) -> Optional[str]:
    """The bone named by the words left after side and chain position."""
    finger = _finger_bone(core, side, number)
    if finger is not None:
        return finger
    key = ''.join(core)
    if not key:
        return None
    if number is not None:
        plain = _PLAIN_NUMBERED.get((key, number))
        if plain is not None:
            return plain
        sided = _SIDED_NUMBERED.get((key, number))
        if sided is not None:
            return None if side is None else side + sided
    # A chain position a table has no entry for names the chain's first bone --
    # a rig that writes ``Hip_01`` for its one and only hip bone means the hips.
    if number is None or number <= 1:
        if key in _PLAIN:
            return _PLAIN[key]
        if key in _SIDED:
            return None if side is None else side + _SIDED[key]
    return None


def _finger_bone(core: List[str], side: Optional[str],
                 number: Optional[int]) -> Optional[str]:
    """The finger bone these words name, if they name one."""
    finger = next((_FINGER_NAMES[word] for word in core if word in _FINGER_NAMES), None)
    if finger is None or side is None:
        return None
    segments = _THUMB_SEGMENTS if finger == 'Thumb' else _FINGER_SEGMENTS
    named = next((_SEGMENT_NAMES[word] for word in core if word in _SEGMENT_NAMES), None)
    if named is None:
        if number is None or not (1 <= number <= len(segments)):
            return None
        named = segments[number - 1]
    return '%s%s%s' % (side, finger, named)


#: Rigs whose naming a bone at a time would read wrongly, recognised by the
#: names they *all* carry and then read from a table of their own.
#:
#: Unreal's mannequin numbers its spine from one -- ``spine_01`` is the first
#: -- where Mixamo numbers from zero, so ``Spine1`` is the *second*. Nothing
#: about either name says which, and a rig read the wrong way has its chest
#: where its waist should be. What tells them apart is the company the name
#: keeps: only the Unreal skeleton has a ``pelvis`` and a ``clavicle_l``
#: beside it.
FAMILIES: tuple = (
    (frozenset({'pelvis', 'spine_01', 'clavicle_l', 'clavicle_r'}),
     {'spine_01': 'spine', 'spine_02': 'chest', 'spine_03': 'upperChest',
      'spine_04': 'upperChest', 'pelvis': 'hips'}),
)


def _family(names: Iterable[str]) -> Dict[str, str]:
    """The exact-name table for the rig these names are from, or an empty one."""
    plain = {name.rsplit(':', 1)[-1].rsplit('|', 1)[-1].strip().lower()
             for name in names}
    for signature, table in FAMILIES:
        if signature <= plain:
            return table
    return {}


def bones_by_name(names: Mapping[int, str]) -> Dict[str, int]:
    """Map humanoid bones onto node indices by reading the nodes' names.

    A rig from a family this recognises (see :data:`FAMILIES`) is read from
    that family's table first, and whatever the table does not name falls to
    :func:`bone_for_name` as any other rig does.

    Where two nodes claim one bone the lower node index keeps it: a file's own
    order is the only tie-break available, and taking the first keeps the answer
    stable across loads.
    """
    table = _family(names.values())
    out: Dict[str, int] = {}
    for index in sorted(names):
        plain = names[index].rsplit(':', 1)[-1].rsplit('|', 1)[-1].strip().lower()
        bone = table.get(plain) or bone_for_name(names[index])
        if bone is not None:
            out.setdefault(bone, index)
    return out


def bones_from_extensions(extensions: Mapping[str, Any]) -> Dict[str, int]:
    """The humanoid bone map a document states for itself, or an empty map.

    Reads ``VRMC_vrm`` and, for a clip-only document, ``VRMC_vrm_animation``.
    Both put the map at ``humanoid.humanBones``, keyed by bone name, each entry
    an object naming the node it is.
    """
    for key in (VRM_EXTENSION, VRM_ANIMATION_EXTENSION):
        block = extensions.get(key)
        if not isinstance(block, dict):
            continue
        human_bones = (block.get('humanoid') or {}).get('humanBones')
        if not isinstance(human_bones, dict):
            continue
        out: Dict[str, int] = {}
        for bone, entry in human_bones.items():
            node = entry.get('node') if isinstance(entry, dict) else None
            if bone in BONE_PARENT and isinstance(node, int):
                out[bone] = node
        if out:
            return out
    return {}


# ======================================================================
# The map, once it is made
# ======================================================================

class Humanoid:
    """Which node of a loaded document is which bone of a body.

    ``bones`` maps a humanoid bone name to a glTF node index; the hierarchy and
    the built ``Transform`` nodes come with it so the map can answer the
    questions a game actually asks -- where a bone is, what hangs off it, and
    which node to parent a held object to.
    """

    def __init__(self, bones: Mapping[str, int],
                 children: Optional[Mapping[int, Sequence[int]]] = None,
                 transforms: Optional[Mapping[int, Any]] = None,
                 names: Optional[Mapping[int, str]] = None,
                 roots: Optional[Sequence[int]] = None) -> None:
        self.bones: Dict[str, int] = dict(bones)
        self.children: Dict[int, List[int]] = {
            k: list(v) for k, v in (children or {}).items()}
        self.transforms: Dict[int, Any] = dict(transforms or {})
        self.names: Dict[int, str] = dict(names or {})
        self.roots: List[int] = list(roots if roots is not None else ())

    # -- construction -----------------------------------------------------
    @classmethod
    def from_scene(cls, scene: Any) -> "Optional[Humanoid]":
        """The humanoid a loaded glTF describes, or None if it describes none.

        ``scene`` is a :class:`~OpenGLContext.loaders.gltf.scene.GLTFScene`.
        None means no bone could be identified at all -- a prop, a vehicle, a
        rig whose joints are named in a convention nothing here reads -- which
        is a thing a caller must be able to tell apart from a partial skeleton.
        """
        bones = bones_from_extensions(getattr(scene, 'extensions', None) or {})
        if not bones:
            bones = bones_by_name(getattr(scene, 'node_names', None) or {})
        if not bones:
            return None
        return cls(bones,
                   children=getattr(scene, 'node_children', None),
                   transforms=getattr(scene, 'node_transforms', None),
                   names=getattr(scene, 'node_names', None),
                   roots=getattr(scene, 'node_roots', None))

    # -- what is here -----------------------------------------------------
    def __bool__(self) -> bool:
        return 'hips' in self.bones

    def __len__(self) -> int:
        return len(self.bones)

    def __contains__(self, bone: str) -> bool:
        return bone in self.bones

    def __iter__(self) -> Iterator[str]:
        return iter(self.bones)

    @property
    def missing(self) -> frozenset:
        """The required bones this skeleton does not have."""
        return frozenset(REQUIRED_BONES - set(self.bones))

    @property
    def complete(self) -> bool:
        """Whether every required bone is here, so a clip can be retargeted."""
        return not self.missing

    # -- addressing -------------------------------------------------------
    def node(self, bone: str) -> Optional[int]:
        """The glTF node index of ``bone``, or None if the rig has no such bone."""
        return self.bones.get(bone)

    def transform(self, bone: str) -> Optional[Any]:
        """The scenegraph ``Transform`` built for ``bone``, or None.

        This is the node to parent a held object to: it carries the bone's
        animated transform, so anything under it moves with the bone.
        """
        index = self.bones.get(bone)
        return None if index is None else self.transforms.get(index)

    def position(self, bone: str) -> Optional[np.ndarray]:
        """Where ``bone`` is in the model's own space, as it is posed now.

        None if the rig has no such bone. Recomputed from the current joint
        transforms on each call, so it answers for the frame it is asked in.
        """
        index = self.bones.get(bone)
        if index is None:
            return None
        worlds = compute_world_matrices(self.roots, self.children, self.transforms)
        world = worlds.get(index)
        if world is None:
            return None
        return np.asarray((np.array([0.0, 0.0, 0.0, 1.0]) @ world)[:3])

    def mask(self, *bones: str, exclude: Iterable[str] = ()) -> frozenset:
        """The node indices under ``bones``, less those under ``exclude``.

        What an animation layer is allowed to move. ``mask('spine')`` is the
        upper body -- spine to fingertips, and anything unnamed hanging off it,
        which is how a held weapon and a hair chain come along with the joint
        they are attached to. ``mask('hips', exclude=('spine',))`` is the rest.
        """
        included: set = set()
        for bone in bones:
            self._descend(self.bones.get(bone), included)
        removed: set = set()
        for bone in exclude:
            self._descend(self.bones.get(bone), removed)
        return frozenset(included - removed)

    def _descend(self, node: Optional[int], into: set) -> None:
        """Add ``node`` and everything under it to ``into``, cycles and all."""
        if node is None:
            return
        stack = [node]
        while stack:
            current = stack.pop()
            if current in into:
                continue
            into.add(current)
            stack.extend(self.children.get(current, ()))
