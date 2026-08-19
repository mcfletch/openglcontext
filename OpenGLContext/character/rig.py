"""A document's node hierarchy as arrays: one skeleton, every joint at once.

A pose is a fact about a whole skeleton, not about one joint, and the per-frame
work a character costs -- composing local transforms, walking them into world
space, assembling a skin's joint matrices -- is the same short arithmetic
repeated over every joint. :class:`Rig` lays the hierarchy out so that
arithmetic runs once over arrays rather than once per joint: parents before
children in a dense slot order, the parent of each slot as an index, and the
slots grouped by depth so composing a generation is a single matrix product.

A rig is a fact about the *document*, so one is built per loaded build and
shared by every figure of it. It holds no pose: a pose is three arrays --
translation ``(N, 3)``, rotation ``(N, 4)`` as glTF's ``[x, y, z, w]``, and
scale ``(N, 3)`` -- passed in and out, so a caller may hold as many poses as it
has bodies.

Matrices are the row-vector form the rest of the renderer uses: a point is a
row, ``p @ M`` transforms it, and ``world = local @ parent``.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.loaders.gltf.animation import vrml_to_quat_xyzw

__all__ = ['Rig', 'quat_to_matrices', 'compose_local']

#: Translation, rotation and scale for every slot of a rig.
Pose = Tuple[np.ndarray, np.ndarray, np.ndarray]


def quat_to_matrices(quaternions: np.ndarray) -> np.ndarray:
    """``(N, 4)`` glTF ``[x, y, z, w]`` quaternions -> ``(N, 3, 3)`` rotations.

    Row-vector matrices, so ``p @ R`` rotates the row ``p``. Input need not be
    normalised: the quaternion length is divided out, which is what makes a
    blended rotation usable without a separate normalising pass.
    """
    q = np.asarray(quaternions, dtype='d').reshape(-1, 4)
    n = np.linalg.norm(q, axis=1, keepdims=True)
    q = np.divide(q, n, out=np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (len(q), 1)),
                  where=n > 0)
    x, y, z, w = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    out = np.empty((len(q), 3, 3), dtype='d')
    # The transpose of the usual column-vector rotation matrix.
    out[:, 0, 0] = 1.0 - 2.0 * (yy + zz)
    out[:, 1, 0] = 2.0 * (xy - wz)
    out[:, 2, 0] = 2.0 * (xz + wy)
    out[:, 0, 1] = 2.0 * (xy + wz)
    out[:, 1, 1] = 1.0 - 2.0 * (xx + zz)
    out[:, 2, 1] = 2.0 * (yz - wx)
    out[:, 0, 2] = 2.0 * (xz - wy)
    out[:, 1, 2] = 2.0 * (yz + wx)
    out[:, 2, 2] = 1.0 - 2.0 * (xx + yy)
    return out


def compose_local(translation: np.ndarray, rotation: np.ndarray,
                  scale: np.ndarray) -> np.ndarray:
    """``(N, 4, 4)`` row-vector local matrices from a pose: scale, rotate, translate."""
    n = len(translation)
    out = np.zeros((n, 4, 4), dtype='d')
    out[:, :3, :3] = np.asarray(scale, dtype='d').reshape(n, 3, 1) \
        * quat_to_matrices(rotation)
    out[:, 3, :3] = translation
    out[:, 3, 3] = 1.0
    return out


class Rig:
    """The node hierarchy of one loaded document, laid out for array arithmetic.

    Built from what a :class:`~OpenGLContext.loaders.gltf.scene.GLTFScene`
    exposes -- its root node indices, its child lists and the ``Transform`` it
    built for each node -- and covering every node a root leads to, which is
    the same set the node-at-a-time walk visits.
    """

    def __init__(self, roots: Iterable[int], children: Mapping[int, Sequence[int]],
                 node_transforms: Mapping[int, Any]) -> None:
        self._build_order(roots, children)
        self._read_rest(node_transforms)
        self._exposed: Optional[frozenset] = None
        self._exposed_signature: Optional[int] = None

    # -- layout ------------------------------------------------------------
    def _build_order(self, roots: Iterable[int],
                     children: Mapping[int, Sequence[int]]) -> None:
        """Number the nodes parents-first and note each one's depth.

        Breadth-first, so a slot's parent always has the lower number and the
        slots of one generation are contiguous -- which is what lets a whole
        generation be composed in one matrix product. A node already numbered
        is not numbered again, so a hierarchy that loops back on itself costs a
        wasted edge rather than the process.
        """
        indices: List[int] = []
        slot_of: Dict[int, int] = {}
        parents: List[int] = []
        depths: List[int] = []
        frontier = [(int(r), -1) for r in roots]
        while frontier:
            following: List[Tuple[int, int]] = []
            for index, parent_slot in frontier:
                if index in slot_of:
                    continue
                slot_of[index] = len(indices)
                indices.append(index)
                parents.append(parent_slot)
                depths.append(0 if parent_slot < 0 else depths[parent_slot] + 1)
                following.extend((int(c), slot_of[index])
                                 for c in (children.get(index) or ()))
            frontier = following
        self.indices = np.asarray(indices, dtype=np.int32)
        self.slot_of = slot_of
        self.parent = np.asarray(parents, dtype=np.int32)
        self.n = len(indices)
        depth = np.asarray(depths, dtype=np.int32)
        #: Slots grouped by generation, roots first.
        self.levels: List[np.ndarray] = [
            np.flatnonzero(depth == d) for d in range(int(depth.max()) + 1)
        ] if self.n else []
        # Numbering is breadth-first, so a generation is a contiguous run of
        # slots: (first, past-the-end, parent slot of each). Composing a
        # generation is then a slice on one side and one gather on the other,
        # which is what a crowd's world matrices are built out of.
        self.level_ranges: List[Tuple[int, int, np.ndarray]] = [
            (int(level[0]), int(level[-1]) + 1, self.parent[level])
            for level in self.levels[1:]
        ]

    def _read_rest(self, node_transforms: Mapping[int, Any]) -> None:
        """Take the pose the document rests at off the ``Transform`` nodes.

        A node carrying a composed matrix has no TRS to read: its matrix is
        kept whole and used in place of a composed one, which is also why an
        animation cannot drive such a node.
        """
        self.transforms: List[Any] = [node_transforms.get(int(i)) for i in self.indices]
        self.rest_translation = np.zeros((self.n, 3), dtype='d')
        self.rest_rotation = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (self.n, 1))
        self.rest_scale = np.ones((self.n, 3), dtype='d')
        self.baked = np.zeros(self.n, dtype=bool)
        self.baked_matrices = np.tile(np.eye(4), (self.n, 1, 1))
        for slot, xform in enumerate(self.transforms):
            if xform is None:
                continue
            forward = getattr(xform, '_forward', None)
            if forward is not None:
                matrix = np.asarray(forward, dtype='d')
                if matrix.shape == (4, 4):
                    self.baked[slot] = True
                    self.baked_matrices[slot] = matrix
                    continue
            self.rest_translation[slot] = getattr(xform, 'translation', (0.0, 0.0, 0.0))
            self.rest_scale[slot] = getattr(xform, 'scale', (1.0, 1.0, 1.0))
            self.rest_rotation[slot] = vrml_to_quat_xyzw(
                getattr(xform, 'rotation', (0.0, 1.0, 0.0, 0.0)))
        self._any_baked = bool(self.baked.any())

    # -- the pose ----------------------------------------------------------
    def rest_pose(self) -> Pose:
        """Fresh copies of the rest translation, rotation and scale."""
        return (self.rest_translation.copy(), self.rest_rotation.copy(),
                self.rest_scale.copy())

    def local_matrices(self, translation: np.ndarray, rotation: np.ndarray,
                       scale: np.ndarray) -> np.ndarray:
        """``(N, 4, 4)`` local matrices for a pose, one per slot."""
        local = compose_local(translation, rotation, scale)
        if self._any_baked:
            local[self.baked] = self.baked_matrices[self.baked]
        return local

    def world_matrices(self, translation: np.ndarray, rotation: np.ndarray,
                       scale: np.ndarray) -> np.ndarray:
        """``(N, 4, 4)`` world matrices for a pose, one generation at a time."""
        world = self.local_matrices(translation, rotation, scale)
        for level in self.levels[1:]:
            world[level] = world[level] @ world[self.parent[level]]
        return world

    def world_matrix_map(self, worlds: np.ndarray) -> Dict[int, np.ndarray]:
        """World matrices keyed by glTF node index, for a caller wanting a dict."""
        return {int(index): worlds[slot] for slot, index in enumerate(self.indices)}

    # -- what has to be written back --------------------------------------
    def exposed_slots(self) -> frozenset:
        """The slots whose ``Transform`` something outside the rig reads.

        A joint whose only children are further joints is read by nothing: the
        skin takes its pose from :meth:`world_matrices` directly, so writing
        the joint's fields would be arithmetic nobody collects. A node with a
        ``Shape`` under it, or with a weapon hung on it, is another matter --
        the renderer walks to those through the scenegraph, so their transforms
        have to say where the pose put them.

        Re-read when something is hung on a joint or taken off one, so
        equipping a figure mid-game brings the joint that now holds something
        into the set. That question is a counter
        (:func:`~OpenGLContext.character.attachment.generation`) rather than a
        walk of the skeleton, because a crowd asks it once a figure a frame.
        A caller that rearranges a joint's children without going through
        :func:`~OpenGLContext.character.attachment.attach` says so with
        :meth:`invalidate_exposed`.
        """
        from OpenGLContext.character import attachment
        signature = attachment.generation()
        if signature != self._exposed_signature:
            self._exposed_signature = signature
            self._exposed = self._find_exposed()
        return self._exposed  # type: ignore[return-value]

    def invalidate_exposed(self) -> None:
        """Say that what hangs off this rig's joints has changed."""
        self._exposed_signature = None

    def _find_exposed(self) -> frozenset:
        """The slots read from outside, and every slot read *through*.

        A renderer reaches a weapon by walking the scenegraph from the top, so
        the hand that holds it is not enough: every joint between the hand and
        the root composes the matrix the weapon arrives at, and each of them
        has to be written too.
        """
        mine = {id(x) for x in self.transforms if x is not None}
        exposed = set()
        for slot, xform in enumerate(self.transforms):
            if xform is None or slot in exposed:
                continue
            if any(id(child) not in mine
                   for child in (getattr(xform, 'children', ()) or ())):
                walk = slot
                while walk >= 0 and walk not in exposed:
                    exposed.add(walk)
                    walk = int(self.parent[walk])
        return frozenset(exposed)

    def refresh_rest(self, slots: np.ndarray) -> None:
        """Re-read the rest pose of ``slots`` from their ``Transform`` nodes.

        A slot no clip drives sits wherever its own transform says, which is
        where a joint a game placed by hand is read from; a slot a clip drives
        is overwritten every frame and has nothing to re-read.
        """
        for slot in slots:
            xform = self.transforms[slot]
            if xform is None or self.baked[slot]:
                continue
            self.rest_translation[slot] = getattr(xform, 'translation', (0.0, 0.0, 0.0))
            self.rest_scale[slot] = getattr(xform, 'scale', (1.0, 1.0, 1.0))
            self.rest_rotation[slot] = vrml_to_quat_xyzw(
                getattr(xform, 'rotation', (0.0, 1.0, 0.0, 0.0)))
