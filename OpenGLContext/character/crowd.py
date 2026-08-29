"""Many figures of one build, posed together rather than one at a time.

A figure's pose is a few dozen rows of arithmetic -- sample the clips, blend
them, compose the skeleton, build the joint matrices -- and on a few dozen rows
almost all of what a numpy call costs is setting the call up. Posing two
hundred and fifty figures one at a time therefore costs two hundred and fifty
times that set-up and barely more arithmetic than posing one.

:class:`Crowd` does the same work for every figure it holds in one pass over
arrays with a figure axis on them. Figures that are doing *the same kind of
thing* -- the same layers, the same masks, the same clips, whatever their
weights and wherever their clocks stand -- are gathered into a group and
answered together; a figure doing something no other figure is doing forms a
group of one and costs what it always did.

    crowd = Crowd()
    for model in cast:
        crowd.add(model)
    ...
    crowd.update(dt)          # once a frame, instead of model.update(dt)

**One build.** Every figure in a crowd must come from one loaded document, so
that a joint means the same joint in all of them. :meth:`add` checks it and
refuses a figure whose skeleton is laid out differently.

**Not every figure need be posed every frame.** ``budget`` caps how many are
brought up to date in one frame and the rest hold the pose they have, taken in
turn so none is starved; a figure's ``rate`` asks for it less often than that
again. A body far enough away that a tenth of a second of its animation is
invisible does not need sixty of them a second, and what is saved is the
largest single lever a crowd has.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

from OpenGLContext.character.clip import ClipSampler
from OpenGLContext.character.mixer import AnimationMixer, _PATHS
from OpenGLContext.character.rig import Rig, compose_local
from OpenGLContext.loaders.gltf.animation import (
    quat_conjugate_rows, quat_multiply_rows, quat_slerp_rows,
    quat_xyzw_to_vrml_rows,
)

log = logging.getLogger(__name__)

__all__ = ['Crowd', 'Member']


class Member:
    """One figure in a crowd: its mixer, and how often it wants posing."""

    __slots__ = ('mixer', 'rate', '_due', '_group')

    def __init__(self, mixer: AnimationMixer, rate: float = 0.0) -> None:
        self.mixer = mixer
        #: Poses per second this figure asks for, or 0 for every frame. A
        #: distance-based scheduler writes this; nothing else reads it.
        self.rate = float(rate)
        self._due = 0.0
        self._group: Any = None


class Crowd:
    """Every figure of one build, posed in one pass over arrays."""

    #: Frames between refreshes of the CPU-side joint matrices when a compute
    #: shader is doing the per-frame work. Those matrices are what a mesh's
    #: bounds are worked out from, and bounds move slowly enough that ten times
    #: a second is plenty for culling and for what reads a scene's extent.
    BOUNDS_INTERVAL = 6

    def __init__(self, compute: bool = True) -> None:
        #: Whether to compose skeletons and palettes on the GPU where the
        #: driver allows it. Off keeps everything in numpy, which is the
        #: reference the GPU path is held to.
        self.compute = bool(compute)
        self._skeleton: Any = None
        self._skeleton_tried = False
        self._frame = 0
        self.members: List[Member] = []
        self._by_mixer: Dict[int, Member] = {}
        self._layout: Optional[Rig] = None
        #: Runs of arithmetic the last :meth:`update` took -- one per set of
        #: figures doing the same kind of thing. It is what says whether a
        #: crowd is gathering: a hundred and fifty figures in three runs costs
        #: three set-ups, and in a hundred and fifty runs costs a hundred and
        #: fifty of them.
        self.groups = 0
        #: One sampler per clip *name*, shared by every figure: the figures are
        #: separate scenegraphs over one document, so their clips are separate
        #: objects holding the same keyframes, and regrouping them once is
        #: enough for all of them.
        self._samplers: Dict[str, ClipSampler] = {}
        self._turn = 0

    # -- membership --------------------------------------------------------
    def add(self, figure: Any, rate: float = 0.0) -> Member:
        """Take a :class:`~OpenGLContext.character.model.CharacterModel` or a
        mixer into the crowd, and stop it being posed on its own."""
        mixer = getattr(figure, 'mixer', figure)
        if self._layout is None:
            self._layout = mixer.rig
        elif not self._matches(mixer.rig):
            raise ValueError(
                'a crowd holds figures of one build; this one\'s skeleton is '
                'laid out differently (%d joints against %d)'
                % (mixer.rig.n, self._layout.n))
        member = Member(mixer, rate=rate)
        self.members.append(member)
        self._by_mixer[id(mixer)] = member
        return member

    def remove(self, figure: Any) -> None:
        """Take a figure out of the crowd; it poses on its own again."""
        mixer = getattr(figure, 'mixer', figure)
        member = self._by_mixer.pop(id(mixer), None)
        if member is not None:
            self.members.remove(member)
        if not self.members:
            self._layout = None

    def _matches(self, rig: Rig) -> bool:
        layout = self._layout
        return (layout is not None and rig.n == layout.n
                and np.array_equal(rig.indices, layout.indices))

    def __len__(self) -> int:
        return len(self.members)

    # -- the frame ---------------------------------------------------------
    def update(self, dt: float, budget: Optional[int] = None,
               mode: Any = None) -> int:
        """Advance every figure's clocks and pose the ones that are due.

        Returns how many figures were posed. Clocks always move -- a figure
        posed every third frame is still where its clip says it is when its
        turn comes -- so what a budget or a rate saves is the pose, not the
        playback.
        """
        step = max(0.0, float(dt))
        self._frame += 1
        self._mode = mode
        due: List[Member] = []
        for member in self.members:
            for layer in member.mixer.layers:
                layer._settle(step)
            if self._is_due(member, step):
                due.append(member)
        if budget is not None and len(due) > budget:
            due = self._take_turns(due, budget)
        groups = self._groups(due)
        self.groups = len(groups)
        for group in groups.values():
            self._pose_group(group)
        return len(due)

    def _is_due(self, member: Member, dt: float) -> bool:
        if member.rate <= 0:
            return True
        member._due -= dt
        if member._due > 0:
            return False
        member._due += 1.0 / member.rate
        if member._due <= 0:            # a rate faster than the frame rate
            member._due = 0.0
        return True

    def _take_turns(self, due: List[Member], budget: int) -> List[Member]:
        """The next ``budget`` figures, starting where the last frame stopped."""
        count = len(due)
        start = self._turn % count
        self._turn = (start + budget) % count
        ordered = due[start:] + due[:start]
        return ordered[:budget]

    # -- grouping ----------------------------------------------------------
    def _groups(self, due: Iterable[Member]) -> Dict[Any, List[Member]]:
        """Figures doing the same kind of thing, gathered under one key."""
        groups: Dict[Any, List[Member]] = {}
        for member in due:
            groups.setdefault(self._signature(member.mixer), []).append(member)
        return groups

    @staticmethod
    def _signature(mixer: AnimationMixer) -> Any:
        """What makes two figures poseable by the same run of arithmetic.

        The shape of the work, not what it is being done to: which layers are
        contributing, how many clips are on each, what each is masked to, and
        whether it is additive. Weights, clocks and *which* clips are read into
        arrays afterwards -- a figure running and a figure walking blend the
        same way and belong in one run, and only the sampling itself has to
        know they are different clips.
        """
        parts = []
        for index, layer in enumerate(mixer.layers):
            tracks = sum(1 for track in layer.tracks if track.weight > 0)
            if not tracks or not layer.weight:
                continue
            parts.append((index, layer.mask, layer.additive, tracks))
        return tuple(parts)

    # -- posing ------------------------------------------------------------
    def _pose_group(self, group: List[Member]) -> None:
        """Pose every figure of one group, then skin and write each of them."""
        layout = self._layout
        assert layout is not None
        count = len(group)
        # A frame that owes nobody a bounds refresh, for figures playing plain
        # clips with nothing hung on them, never needs the pose on this side at
        # all: the whole chain from keyframes to joint palette runs on the GPU.
        if self._frame % self.BOUNDS_INTERVAL != 1 and self._blend_on_gpu(group):
            return
        if self._has_morph_weights(group):
            # Morph weights are per mesh and of no fixed width, so a figure
            # whose clips drive them is posed on its own rather than bending
            # the group's arrays around it.
            for member in group:
                member.mixer.apply()
            return
        translation = np.repeat(layout.rest_translation[None], count, axis=0)
        rotation = np.repeat(layout.rest_rotation[None], count, axis=0)
        scale = np.repeat(layout.rest_scale[None], count, axis=0)
        pose = (translation, rotation, scale)
        first = group[0].mixer
        for index, layer in enumerate(first.layers):
            tracks = [track for track in layer.tracks if track.weight > 0]
            if not tracks or not layer.weight:
                continue
            if self._plain(group, index, len(tracks)):
                self._lay_layer(group, index, pose)
            else:
                self._apply_layer(group, index, len(tracks), pose)
        if not self._skin_on_gpu(group, pose):
            self._skin_group(group, pose)
        self._write_group(group, pose)

    @staticmethod
    def _has_morph_weights(group: List[Member]) -> bool:
        for member in group:
            for layer in member.mixer.layers:
                for track in layer.tracks:
                    if member.mixer._sampler(track.clip)._weights:
                        return True
        return False

    @staticmethod
    def _plain(group: List[Member], index: int, tracks: int) -> bool:
        """Whether this layer is one clip at full weight with nothing masked.

        Which is what a figure is doing nearly all of the time -- a cross-fade
        is a fifth of a second and the walking is the rest -- and it needs no
        blend at all: the clip's values *are* the pose for the joints it moves.

        A group is gathered by the shape of the work and not by the weights, so
        the weights are the group's own figure by figure: one member part way
        through a fade is enough to make the whole group take the blend.
        """
        if tracks != 1:
            return False
        first = group[0].mixer.layers[index]
        if first.additive or first.mask is not None:
            return False
        return all(member.mixer.layers[index].weight == 1.0
                   and member.mixer.layers[index].tracks[0].weight >= 1.0
                   for member in group)

    def _lay_layer(self, group: List[Member], index: int,
                   pose: Tuple[np.ndarray, ...],
                   restriction: Optional["_Restriction"] = None) -> None:
        """Write one clip straight into the pose, for every figure at once.

        ``restriction`` narrows it to a few joints, for a pose being worked out
        only where the scenegraph reads it.
        """
        picked = [self._track(member, index, 0) for member in group]
        by_clip: Dict[str, List[Tuple[int, Any]]] = {}
        for row, track in enumerate(picked):
            by_clip.setdefault(track.clip.name, []).append((row, track))
        for entries in by_clip.values():
            rows = np.asarray([row for row, _ in entries], dtype=np.intp)
            sampler = self._sampler(entries[0][1].clip)
            if restriction is not None:
                sampler = restriction.narrow(sampler)
            times = np.asarray([t.time for _, t in entries], dtype='d')
            sampled = sampler.sample_many(times)
            for path_index in range(len(_PATHS)):
                slots = (sampler.slots_translation, sampler.slots_rotation,
                         sampler.slots_scale)[path_index]
                if len(slots):
                    pose[path_index][np.ix_(rows, slots)] = sampled[path_index]

    def _apply_layer(self, group: List[Member], index: int, tracks: int,
                     pose: Tuple[np.ndarray, ...],
                     restriction: Optional["_Restriction"] = None) -> None:
        """Blend one layer of every figure of the group over the pose so far.

        ``restriction`` narrows the whole run to a few joints -- the ones
        something outside the rig reads -- so a figure whose pose is being
        worked out on the GPU can still have those joints written here without
        paying for the skeleton it is not asking about.
        """
        layout = self._layout
        assert layout is not None
        count = len(group)
        first = group[0].mixer.layers[index]
        mask = first.slot_mask(layout)
        additive = first.additive
        joints = layout.n if restriction is None else len(restriction.slots)
        if mask is not None and restriction is not None:
            # The layer's mask is over the whole skeleton; a narrowed run reads
            # it by the joint's place in the narrowed set, not by its slot.
            mask = mask[restriction.slots]
        blends = [_GroupBlend(count, joints, width,
                              rotation=(path == 'rotation' and not additive))
                  for path, width in _PATHS]
        for position in range(tracks):
            picked = [self._track(member, index, position) for member in group]
            # One sampling call per distinct clip, whatever the figures are
            # playing; everything after it is the same arithmetic for all of
            # them, so the blend below runs once over the whole group.
            by_clip: Dict[str, List[Tuple[int, Any]]] = {}
            for row, track in enumerate(picked):
                by_clip.setdefault(track.clip.name, []).append((row, track))
            for entries in by_clip.values():
                rows = np.asarray([row for row, _ in entries], dtype=np.intp)
                sampler = self._sampler(entries[0][1].clip)
                if restriction is not None:
                    sampler = restriction.narrow(sampler)
                times = np.asarray([t.time for _, t in entries], dtype='d')
                weights = np.asarray([t.weight for _, t in entries], dtype='d')
                sampled = sampler.sample_many(times)
                base = (sampler.sample_many([t.reference for _, t in entries])
                        if additive else None)
                for path_index, (path, _width) in enumerate(_PATHS):
                    slots = (sampler.slots_translation, sampler.slots_rotation,
                             sampler.slots_scale)[path_index]
                    if not len(slots):
                        continue
                    values = sampled[path_index]
                    if base is not None:
                        values = _delta_group(path, values, base[path_index])
                    if mask is not None:
                        keep = mask[slots]
                        slots, values = slots[keep], values[:, keep]
                    blends[path_index].add(slots, values, weights, rows)
        layer_weight = np.asarray(
            [member.mixer.layers[index].weight for member in group], dtype='d')
        for path_index, (path, _width) in enumerate(_PATHS):
            blends[path_index].combine(path, pose[path_index], layer_weight,
                                       additive)

    @staticmethod
    def _track(member: Member, layer: int, position: int) -> Any:
        return [track for track in member.mixer.layers[layer].tracks
                if track.weight > 0][position]

    def _sampler(self, clip: Any) -> ClipSampler:
        """The regrouped form of a clip, shared across the whole crowd."""
        found = self._samplers.get(clip.name)
        if found is None:
            layout = self._layout
            assert layout is not None, 'a crowd samples only for figures it holds'
            found = ClipSampler(clip, layout)
            self._samplers[clip.name] = found
        return found

    # -- the same work, on the GPU ----------------------------------------
    def _skin_on_gpu(self, group: List[Member],
                     pose: Tuple[np.ndarray, ...]) -> bool:
        """Compose this group's skeletons and palettes with a compute shader.

        False where there is no context to do it in, no compute in the driver,
        or no palette to write into -- and then the caller does the same
        arithmetic in numpy instead.

        The CPU-side joint matrices are still refreshed every
        :attr:`BOUNDS_INTERVAL` frames, because they are what each mesh's
        bounds are worked out from and nothing reads them back off the GPU.
        """
        skeleton = self._compute_skeleton()
        if skeleton is None:
            return False
        targets = self._palette_targets(group)
        if targets is None:
            return False
        if not skeleton.run(pose, targets, self._palette.buffer):
            return False
        if self._frame % self.BOUNDS_INTERVAL == 1:
            self._skin_group(group, pose)
        return True

    def _blend_on_gpu(self, group: List[Member]) -> bool:
        """Sample, blend, compose and skin this group entirely on the GPU.

        False -- and the caller does it all in numpy -- unless every figure of
        the group is doing what the blend shader reads: layers in order, each
        masked or not, and none of them additive. What the scenegraph reads of
        the result is worked out here afterwards, for those joints only.
        """
        skeleton = self._compute_skeleton()
        layout = self._layout
        if skeleton is None or layout is None:
            return False
        if not skeleton.describe_clips(self._all_samplers(), layout.rest_pose()):
            return False
        played = self._blend_tables(group, skeleton)
        if played is None:
            return False
        tracks, layers, spans, masks = played
        targets = self._palette_targets(group)
        if targets is None:
            return False
        if not (skeleton.blend(tracks, layers, spans, masks)
                and skeleton.run(None, targets, self._palette.buffer,
                                 count=len(group))):
            return False
        self._write_read_joints(group)
        return True

    def _write_read_joints(self, group: List[Member]) -> None:
        """Put the joints something reads onto the scenegraph, and no others.

        The pose is on the GPU and nothing reads it back, but a weapon hanging
        off a hand is reached by walking the scenegraph -- so that hand, and
        the joints down to it, have to say where they are. That is a handful of
        joints out of a skeleton, and working out a handful is a fraction of
        working out all of them: the clips are read for those joints only.
        """
        layout = self._layout
        if layout is None:
            return
        wanted = [member.mixer._writable() for member in group]
        if not sum(len(slots) for slots in wanted):
            return
        slots = np.unique(np.concatenate(wanted)).astype(np.int32)
        columns = np.full(layout.n, 0, dtype=np.intp)
        columns[slots] = np.arange(len(slots))
        self._write_slots(group, self._partial_pose(group, slots), wanted,
                          columns=columns)

    def _partial_pose(self, group: List[Member],
                      slots: np.ndarray) -> Tuple[np.ndarray, ...]:
        """The pose of ``slots`` only, for every figure of a plain group."""
        layout = self._layout
        assert layout is not None
        count = len(group)
        positions = np.full(layout.n, -1, dtype=np.int32)
        positions[slots] = np.arange(len(slots), dtype=np.int32)
        restriction = _Restriction(slots, positions)
        pose = (np.repeat(layout.rest_translation[slots][None], count, axis=0),
                np.repeat(layout.rest_rotation[slots][None], count, axis=0),
                np.repeat(layout.rest_scale[slots][None], count, axis=0))
        first = group[0].mixer
        for index, layer in enumerate(first.layers):
            tracks = [track for track in layer.tracks if track.weight > 0]
            if not tracks or not layer.weight:
                continue
            # The same choice the whole-skeleton pose makes: one clip at full
            # weight is a scatter, not a blend.
            if self._plain(group, index, len(tracks)):
                self._lay_layer(group, index, pose, restriction=restriction)
            else:
                self._apply_layer(group, index, len(tracks), pose,
                                  restriction=restriction)
        return pose

    def _all_samplers(self) -> List[ClipSampler]:
        """Every clip of the build, regrouped, in a stable order."""
        first = self.members[0].mixer
        return [self._sampler(clip) for _name, clip in sorted(first.clips.items())]

    def _blend_tables(self, group: List[Member], skeleton: Any) -> Optional[tuple]:
        """What every figure is playing, as the tables the blend shader reads.

        ``(tracks, layers, spans, masks)`` -- or None where any figure is doing
        something the shader does not read, and the whole group is then blended
        in numpy instead.
        """
        clip_index = skeleton.clip_index
        tracks: List[Tuple[float, float, float, float]] = []
        layers: List[Tuple[float, float, float, float]] = []
        spans: List[Tuple[int, int]] = []
        masks = _MaskTable(self._layout, skeleton.mask_words())
        for member in group:
            first = len(layers)
            for layer in member.mixer.layers:
                if not layer.weight or not layer.tracks:
                    continue
                if layer.additive:
                    return None
                start = len(tracks)
                for track in layer.tracks:
                    if track.weight <= 0:
                        continue
                    clip = clip_index.get(track.clip.name)
                    if clip is None:
                        return None
                    tracks.append((clip, track.time, track.weight, 0.0))
                if len(tracks) == start:
                    continue
                layers.append((start, len(tracks) - start,
                               masks.index(layer), layer.weight))
            spans.append((first, len(layers) - first))
        return tracks, layers, spans, masks.rows()

    def _compute_skeleton(self) -> Any:
        """The compute-shader skeleton for this crowd's rig, built on first use."""
        if self._skeleton is not None or self._skeleton_tried:
            return self._skeleton
        mode = getattr(self, '_mode', None)
        layout = self._layout
        if mode is None or layout is None or not self.compute:
            return None
        from OpenGLContext.character import gpuskeleton
        from OpenGLContext.scenegraph.skinning import palette_for
        self._skeleton_tried = True
        if not (gpuskeleton.compute_skeleton_is_enabled()
                and gpuskeleton.compute_is_available()):
            return None
        palette = palette_for(mode)
        if palette is None:
            return None
        self._palette = palette
        skeleton = gpuskeleton.GPUSkeleton(layout.parent, layout.n)
        if not skeleton.ok:
            return None
        self._skeleton = skeleton
        return skeleton

    def _palette_targets(self, group: List[Member]) -> Optional[List[tuple]]:
        """Where every skinned mesh of the group reads its joints.

        One entry per mesh, since a mesh is what holds a range of the palette;
        two meshes of one skin are two entries carrying the same joints.
        """
        skeleton = self._skeleton
        plans = group[0].mixer._skin_plans
        skeleton.describe_skins([(slots, bind) for _s, slots, bind, _m in plans])
        mode = self._mode
        targets: List[tuple] = []
        for figure, member in enumerate(group):
            for index, (skin, _slots, _bind, mesh_slot) in enumerate(
                    member.mixer._skin_plans):
                written = set()
                for mesh in skin.meshes:
                    base = mesh.skin_from_gpu(mode, self.skeleton_joints(index))
                    if base is None:
                        return None
                    # A figure's levels share one range between them; writing
                    # it once is writing it for both.
                    if base not in written:
                        written.add(base)
                        targets.append((figure, index, mesh_slot, base))
        return targets

    def skeleton_joints(self, skin: int) -> int:
        """How many joints one skin of this crowd's build carries."""
        return int(self._skeleton.skin_counts[skin])

    # -- what comes out of the pose ---------------------------------------
    def _skin_group(self, group: List[Member], pose: Tuple[np.ndarray, ...]) -> None:
        """Build every figure's joint matrices from one composed skeleton."""
        layout = self._layout
        assert layout is not None
        worlds = self._world_matrices(len(group), pose)
        identity = np.eye(4)
        for plan_index, (_skin, slots, inverse_bind, mesh_slot) in enumerate(
                group[0].mixer._skin_plans):
            known = slots >= 0
            if known.all():
                joints = worlds[:, slots]
            else:
                joints = np.tile(identity, (len(group), len(slots), 1, 1))
                joints[:, known] = worlds[:, slots[known]]
            node_inverse = (np.linalg.inv(worlds[:, mesh_slot]) if mesh_slot >= 0
                            else np.tile(identity, (len(group), 1, 1)))
            # Flat stacks rather than a broadcast triple product: multiplying
            # ``(1, J, 4, 4)`` into ``(F, J, 4, 4)`` takes numpy's slow path,
            # and the mesh-node inverse is one matrix per figure, so the rows
            # of all its joints can go through it in a single block.
            count, joint_count = joints.shape[0], joints.shape[1]
            matrices = (np.broadcast_to(inverse_bind, joints.shape
                                        ).reshape(-1, 4, 4)
                        @ joints.reshape(-1, 4, 4))
            matrices = (matrices.reshape(count, joint_count * 4, 4)
                        @ node_inverse).reshape(count, joint_count, 4, 4)
            for row, member in enumerate(group):
                plans = member.mixer._skin_plans
                if plan_index >= len(plans):
                    continue
                for mesh in plans[plan_index][0].meshes:
                    mesh.set_skin_matrices(matrices[row])

    def _world_matrices(self, count: int,
                        pose: Tuple[np.ndarray, ...]) -> np.ndarray:
        """``(F, N, 4, 4)`` world matrices, one generation of the skeleton at a time."""
        layout = self._layout
        assert layout is not None
        n = layout.n
        local = compose_local(pose[0].reshape(-1, 3), pose[1].reshape(-1, 4),
                              pose[2].reshape(-1, 3))
        if layout._any_baked:
            baked = np.flatnonzero(layout.baked)
            for figure in range(count):
                local[figure * n + baked] = layout.baked_matrices[baked]
        world = local.reshape(count, n, 4, 4)
        for first, past, parents in layout.level_ranges:
            world[:, first:past] = world[:, first:past] @ world[:, parents]
        return world

    def _write_group(self, group: List[Member],
                     pose: Tuple[np.ndarray, ...]) -> None:
        """Put each figure's pose onto its own scenegraph nodes."""
        self._write_slots(group, pose, [member.mixer._writable()
                                        for member in group])

    def _write_slots(self, group: List[Member], pose: Tuple[np.ndarray, ...],
                     wanted: List[np.ndarray],
                     columns: Optional[np.ndarray] = None) -> None:
        """Write the named joints of every figure, converting once for all of them.

        ``wanted`` is each figure's joints as rig slots; ``columns`` maps a rig
        slot to its place in the pose arrays, for a pose worked out for a few
        joints rather than the whole skeleton. A conversion out of numpy per
        figure -- let alone per joint -- is most of what writing a pose back
        costs, so the group's whole set is converted in one go and the loop
        that follows does nothing but assign.
        """
        counts = [len(slots) for slots in wanted]
        if not sum(counts):
            return
        slots = np.concatenate(wanted)
        figures = np.repeat(np.arange(len(group)), counts)
        places = slots if columns is None else columns[slots]
        translations = pose[0][figures, places].tolist()
        rotations = quat_xyzw_to_vrml_rows(pose[1][figures, places]).tolist()
        scales = pose[2][figures, places].tolist()
        at = 0
        for row, member in enumerate(group):
            mixer = member.mixer
            for slot in wanted[row]:
                mixer._write_slot(int(slot), translations[at], rotations[at],
                                  scales[at])
                at += 1


# ======================================================================
# The arithmetic, with a figure axis on it
# ======================================================================

class _MaskTable:
    """The distinct joint masks a group's layers use, as bits.

    A layer masked to the arms moves those joints and leaves the rest as it
    found them, and the shader asks that a bit at a time. Two layers masked to
    the same joints are one row here, which is what a crowd of figures all
    firing from the shoulder comes to.
    """

    def __init__(self, layout: Any, words: int) -> None:
        self._layout = layout
        self._words = words
        self._rows: List[np.ndarray] = []
        self._of: Dict[Any, int] = {}

    def index(self, layer: Any) -> float:
        """Which row this layer's mask is, or -1 where it masks nothing."""
        if layer.mask is None:
            return -1.0
        found = self._of.get(layer.mask)
        if found is None:
            found = len(self._rows)
            self._of[layer.mask] = found
            self._rows.append(_mask_bits(layer.slot_mask(self._layout),
                                         self._words))
        return float(found)

    def rows(self) -> Optional[np.ndarray]:
        return np.stack(self._rows) if self._rows else None


def _mask_bits(flags: np.ndarray, words: int) -> np.ndarray:
    """A boolean per joint as ``words`` of thirty-two bits."""
    out = np.zeros(words, dtype=np.uint32)
    for slot in np.flatnonzero(flags):
        out[slot >> 5] |= np.uint32(1) << np.uint32(slot & 31)
    return out


class _Restriction:
    """The few joints a partial pose is being worked out for.

    A figure whose pose lives on the GPU still owes the scenegraph the joints
    something reaches through -- a hand with a weapon on it, and the joints
    down to that hand. This is which ones, and the narrowed clips that answer
    for them; the views are kept, because which joints those are changes when
    equipment does and not per frame.
    """

    __slots__ = ('slots', 'positions')

    def __init__(self, slots: np.ndarray, positions: np.ndarray) -> None:
        self.slots = slots
        self.positions = positions

    def narrow(self, sampler: ClipSampler) -> ClipSampler:
        return sampler.restricted(self.slots, self.positions)


class _GroupBlend:
    """A layer's running weighted mean of one path, for every figure at once.

    The arithmetic of :class:`~OpenGLContext.character.mixer._Blend`, over
    ``(figures, slots)`` instead of ``(slots,)``.
    """

    __slots__ = ('values', 'total', 'touched', 'rotation')

    def __init__(self, count: int, n: int, width: int, rotation: bool) -> None:
        self.values = np.zeros((count, n, width), dtype='d')
        self.total = np.zeros((count, n), dtype='d')
        self.touched = np.zeros((count, n), dtype=bool)
        self.rotation = rotation

    def add(self, slots: np.ndarray, values: np.ndarray, weights: np.ndarray,
            rows: Optional[np.ndarray] = None) -> None:
        """Fold one track into the mean, for the figures ``rows`` names.

        ``rows`` is which figures of the group this call answers for -- the
        ones playing the clip that was just sampled -- or None for all of them.
        """
        if not len(slots):
            return
        if rows is None:
            index = (slice(None), slots)
        else:
            index = np.ix_(rows, slots)
        seen = self.touched[index]
        current = self.values[index]
        running = self.total[index]
        weight = weights[:, None]
        fraction = weight / (running + weight)
        if self.rotation:
            shape = current.shape
            blended = quat_slerp_rows(
                current.reshape(-1, shape[2]), values.reshape(-1, shape[2]),
                fraction.ravel()).reshape(shape)
        else:
            blended = current + (values - current) * fraction[:, :, None]
        self.values[index] = np.where(seen[:, :, None], blended, values)
        self.total[index] = running + weight
        self.touched[index] = True

    def combine(self, path: str, target: np.ndarray, layer_weight: np.ndarray,
                additive: bool) -> None:
        """Write this layer's contribution over the pose built so far."""
        if not self.touched.any():
            return
        strength = layer_weight[:, None] * (
            self.total if additive else np.minimum(1.0, self.total))
        blended = (_add_group(path, target, self.values, strength) if additive
                   else _lerp_group(path, target, self.values, strength))
        target[:] = np.where(self.touched[:, :, None], blended, target)


def _lerp_group(path: str, current: np.ndarray, value: np.ndarray,
                strength: np.ndarray) -> np.ndarray:
    full = strength >= 1.0
    if full.all():
        return value
    if path == 'rotation':
        shape = current.shape
        out = quat_slerp_rows(current.reshape(-1, shape[2]),
                              value.reshape(-1, shape[2]),
                              strength.ravel()).reshape(shape)
    else:
        out = current + (value - current) * strength[:, :, None]
    return np.where(full[:, :, None], value, out)


def _delta_group(path: str, value: np.ndarray,
                 reference: np.ndarray) -> np.ndarray:
    if path == 'rotation':
        shape = value.shape
        return quat_multiply_rows(
            value.reshape(-1, shape[2]),
            quat_conjugate_rows(reference.reshape(-1, shape[2]))).reshape(shape)
    if path == 'scale':
        safe = np.where(np.abs(reference) < 1e-9, 1.0, reference)
        return np.asarray(value / safe)
    return np.asarray(value - reference)


def _add_group(path: str, current: np.ndarray, delta: np.ndarray,
               strength: np.ndarray) -> np.ndarray:
    if path == 'rotation':
        shape = delta.shape
        identity = np.zeros(shape)
        identity[..., 3] = 1.0
        eased = quat_slerp_rows(identity.reshape(-1, shape[2]),
                                delta.reshape(-1, shape[2]),
                                strength.ravel())
        return quat_multiply_rows(
            eased, current.reshape(-1, shape[2])).reshape(shape)
    if path == 'scale':
        return np.asarray(current * (1.0 + (delta - 1.0) * strength[:, :, None]))
    return np.asarray(current + delta * strength[:, :, None])
