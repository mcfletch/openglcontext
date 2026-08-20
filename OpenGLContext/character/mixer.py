"""More than one animation clip at a time: cross-fades, layers and additives.

glTF stores clips; it says nothing about playing two of them at once, and a
character needs exactly that -- a run cycle that eases into a walk instead of
snapping, a firing animation on the arms while the legs keep running, a recoil
kick added on top of whatever the arms were already doing. That is this module,
and none of it is specific to a humanoid: it blends node transforms and morph
weights, whatever the model is.

**Layers, in order, each a blend of its own tracks.** A layer is a channel of
animation with a *mask* -- the node indices it is allowed to move -- and a
weight. Layers are applied in the order they were created, each one blended
over the pose built so far, so the base layer walks the whole body and an
``upper`` layer masked to the arms writes over it for those joints only.
:meth:`OpenGLContext.character.humanoid.Humanoid.mask` is where a mask for a
humanoid comes from.

**Within a layer, tracks cross-fade.** Playing a clip fades the layer's previous
clip out over the same interval, and the tracks are blended in proportion to
their weights. Where a layer's weights do not add up to one -- a clip fading in
with nothing to fade out of -- the shortfall is taken from the pose underneath,
so a layer eases in from the layer below rather than from nothing.

**An additive layer adds a difference instead of replacing.** Its pose is
measured against a reference frame of its own clip (frame zero by default) and
what that difference comes to is added to the pose below: a 20-degree recoil
authored once reads as 20 degrees on top of any aim.

The arithmetic is per node and per animated path, so a mask, a layer weight and
a cross-fade all compose without any of them knowing about the others::

    mixer = AnimationMixer.from_scene(scene)
    mixer.play('run', fade=0.2)
    mixer.layer('upper', mask=human.mask('spine')).play('fire', loop=False)
    ...
    mixer.update(dt)          # once a frame
"""

from __future__ import annotations

import logging
from typing import (
    Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple,
)

import numpy as np

from OpenGLContext.character.clip import ClipSampler
from OpenGLContext.character.rig import Rig
from OpenGLContext.loaders.gltf.animation import (
    Animation, quat_conjugate_rows, quat_multiply, quat_multiply_rows,
    quat_normalize, quat_slerp, quat_slerp_rows, quat_xyzw_to_vrml_rows,
    vrml_to_quat_xyzw,
)

log = logging.getLogger(__name__)

__all__ = ['Track', 'Layer', 'AnimationMixer', 'BASE_LAYER']

#: The layer a clip plays on when none is named.
BASE_LAYER = 'base'

#: The identity rotation, as glTF stores one.
_IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])

#: The paths a skeleton's pose is made of, and how wide each one is.
_PATHS = (('translation', 3), ('rotation', 4), ('scale', 3))


class Track:
    """One clip playing on a layer: where it is, how fast, how loud.

    ``weight`` is what the track currently contributes and moves towards
    ``target`` at ``rate`` per second, which is how a cross-fade is expressed --
    the incoming track rising while the outgoing one falls. A track whose target
    and weight are both zero has finished fading and is dropped.
    """

    __slots__ = ('clip', 'time', 'speed', 'loop', 'weight', 'target', 'rate',
                 'reference')

    def __init__(self, clip: Animation, *, weight: float = 1.0,
                 speed: float = 1.0, loop: bool = True,
                 reference: float = 0.0) -> None:
        self.clip = clip
        self.time = 0.0
        self.speed = float(speed)
        self.loop = bool(loop)
        self.weight = float(weight)
        self.target = self.weight
        self.rate = 0.0            # 0 means "instantly", not "never"
        #: The time in this clip an additive layer measures its delta from.
        self.reference = float(reference)

    @property
    def name(self) -> str:
        return self.clip.name

    @property
    def duration(self) -> float:
        return self.clip.duration

    @property
    def finished(self) -> bool:
        """Whether a one-shot has reached its end and is holding the last frame."""
        return not self.loop and self.time >= self.duration

    def advance(self, dt: float) -> None:
        """Move the clock on by ``dt`` seconds of real time."""
        self.time += dt * self.speed
        duration = self.duration
        if duration <= 0:
            self.time = 0.0
        elif self.loop:
            self.time %= duration
        else:
            self.time = min(max(self.time, 0.0), duration)

    def fade(self, target: float, seconds: float) -> None:
        """Head for ``target`` weight over ``seconds`` (0 is at once)."""
        self.target = float(target)
        self.rate = 1.0 / seconds if seconds > 0 else 0.0
        if not self.rate:
            self.weight = self.target

    def _settle(self, dt: float) -> None:
        if self.weight == self.target:
            return
        step = self.rate * dt
        if abs(self.target - self.weight) <= step:
            self.weight = self.target
        else:
            self.weight += step if self.target > self.weight else -step


class Layer:
    """One channel of animation: a set of cross-fading tracks over a mask.

    ``mask`` is the node indices this layer may move, or None for the whole
    model. ``weight`` scales everything the layer contributes, so a layer can be
    dialled in without touching the clips playing on it. ``additive`` makes the
    layer add its clips' *difference* from their reference frame rather than
    replace the pose beneath.
    """

    def __init__(self, name: str, mask: Optional[Iterable[int]] = None,
                 weight: float = 1.0, additive: bool = False) -> None:
        self.name = name
        self.mask: Optional[frozenset] = None if mask is None else frozenset(mask)
        self.weight = float(weight)
        self.additive = bool(additive)
        self.tracks: List[Track] = []
        self._clips: Optional[Mapping[str, Animation]] = None
        self._slot_mask: Optional[np.ndarray] = None
        self._masked: Optional[frozenset] = None

    def play(self, name: str, *, fade: float = 0.0, loop: bool = True,
             speed: float = 1.0, restart: bool = False,
             reference: float = 0.0) -> Track:
        """Play ``name`` on this layer, fading whatever else is on it out.

        Playing the clip that is already playing keeps its clock, so asking for
        the same clip every frame -- which is what a state machine does -- costs
        nothing and does not stutter. ``restart`` rewinds it instead.
        """
        clips = self._clips or {}
        clip = clips[name]
        found = next((t for t in self.tracks if t.clip is clip), None)
        for track in self.tracks:
            if track is not found:
                track.fade(0.0, fade)
        if found is None:
            found = Track(clip, weight=0.0 if fade > 0 else 1.0,
                          speed=speed, loop=loop, reference=reference)
            self.tracks.append(found)
        else:
            found.speed = float(speed)
            found.loop = bool(loop)
            found.reference = float(reference)
        if restart:
            found.time = 0.0
        found.fade(1.0, fade)
        return found

    def stop(self, fade: float = 0.0) -> None:
        """Fade everything on this layer out, leaving the pose beneath."""
        for track in self.tracks:
            track.fade(0.0, fade)

    @property
    def current(self) -> Optional[Track]:
        """The track this layer is heading towards, or None if it is fading out."""
        return next((t for t in self.tracks if t.target > 0), None)

    def _settle(self, dt: float) -> None:
        for track in self.tracks:
            track._settle(dt)
            track.advance(dt)
        self.tracks = [t for t in self.tracks if t.weight > 0 or t.target > 0]

    def slot_mask(self, rig: Rig) -> Optional[np.ndarray]:
        """This layer's mask as a flag per rig slot, or None for the whole model.

        Built on first use and rebuilt when the mask is replaced, so a game may
        swap a layer's mask between frames without paying for the set lookup
        joint by joint.
        """
        if self.mask is None:
            return None
        if self._slot_mask is None or self._masked is not self.mask:
            flags = np.zeros(rig.n, dtype=bool)
            for index in self.mask:
                slot = rig.slot_of.get(index)
                if slot is not None:
                    flags[slot] = True
            self._slot_mask = flags
            self._masked = self.mask
        return self._slot_mask


class AnimationMixer:
    """Every clip a model can play, and which of them are playing now.

    Built over the same registries the single-clip
    :class:`~OpenGLContext.loaders.gltf.animation.Player` writes into -- the
    node index to ``Transform`` map, the morph-weight setters and the skins --
    so a mixer is a drop-in replacement for a player wherever more than one clip
    is wanted. ``update(dt)`` once a frame is the whole runtime contract.

    A node the mixer drives must be a TRS ``Transform``. glTF requires that of
    any node an animation targets, so a document's own clips always satisfy it;
    a clip retargeted onto a node that carries a baked matrix is skipped, with
    one warning.

    **How much of the pose reaches the scenegraph** is :attr:`pose_write`.
    ``'all'``, the default, writes every joint a clip drives, so anything
    holding a joint's ``Transform`` reads where the pose put it. ``'exposed'``
    writes only the joints something outside the rig reaches -- a mesh, an
    attachment point with a weapon on it, and the joints on the way down to one
    -- plus whatever :meth:`observe` has been told about. The skin does not
    need the rest: it takes its matrices from the pose arrays directly, so for
    a crowd, where nothing is reading individual joints, ``'exposed'`` is a
    fifth of a millisecond a figure that nobody was going to collect.
    """

    #: Which joints of the pose are written back to the scenegraph:
    #: ``'all'`` or ``'exposed'`` -- see the class docstring.
    pose_write: str = 'all'

    def __init__(self, clips: Mapping[str, Animation],
                 node_transforms: Optional[Mapping[int, Any]] = None,
                 node_morph: Optional[Mapping[int, Sequence[Callable]]] = None,
                 skins: Optional[Iterable[Any]] = None,
                 compute_worlds: Optional[Callable[[], dict]] = None,
                 rig: Optional[Rig] = None) -> None:
        self.clips: Dict[str, Animation] = dict(clips)
        self.node_transforms: Dict[int, Any] = dict(node_transforms or {})
        self.node_morph: Dict[int, Sequence[Callable]] = dict(node_morph or {})
        self.skins: List[Any] = list(skins or ())
        self.compute_worlds = compute_worlds
        #: The skeleton as arrays. Built from a flat list of nodes where the
        #: caller gave no hierarchy, which is enough to blend a pose; a rig
        #: from a loaded document knows the hierarchy and can skin as well.
        self.rig: Rig = rig if rig is not None else Rig(
            sorted(self.node_transforms), {}, self.node_transforms)
        self.layers: List[Layer] = []
        self._by_name: Dict[str, Layer] = {}
        #: One :class:`~OpenGLContext.character.clip.ClipSampler` per clip,
        #: keyed by the clip object, so two mixers over one document share none
        #: of their playback and all of their regrouping.
        self._samplers: Dict[int, ClipSampler] = {}
        #: The last pose written to the scenegraph, so an unchanged joint costs
        #: no field assignment -- and an idle character costs almost nothing.
        self._written: Dict[Tuple[int, str], Any] = {}
        self._written_pose: Optional[Tuple[np.ndarray, ...]] = None
        self._warned: set = set()
        self._survey()

    # -- construction -----------------------------------------------------
    @classmethod
    def from_scene(cls, scene: Any) -> "AnimationMixer":
        """A mixer over everything a loaded glTF can play.

        Clips are keyed by the name the document gave each animation, or
        ``animation<index>`` where it named none.
        """
        clips: Dict[str, Animation] = {}
        for index, animation in enumerate(getattr(scene, 'animations', None) or []):
            clips[animation.name or ('animation%d' % index)] = animation
        roots = getattr(scene, 'node_roots', None) or []
        children = getattr(scene, 'node_children', None) or {}
        transforms = getattr(scene, 'node_transforms', None) or {}
        skins = list(getattr(scene, 'skins', None) or ())
        return cls(clips, transforms,
                   node_morph=getattr(scene, 'node_morph', None),
                   skins=skins,
                   rig=Rig(roots, children, transforms))

    def _survey(self) -> None:
        """Regroup every clip against the rig and note what they can move."""
        #: Slots some clip moves. The rest keep whatever their own transform
        #: says, which is where a joint a game placed by hand is read from.
        self.driven = np.zeros(self.rig.n, dtype=bool)
        self._undriven = np.arange(self.rig.n)
        self._all_write_slots = np.zeros(0, dtype=np.int32)
        self._exposed_signature: Any = None
        self._observed: set = set()
        self._write_slots: np.ndarray = np.zeros(0, dtype=np.int32)
        for clip in self.clips.values():
            self._sampler(clip)
        self._plan_skins()

    def _sampler(self, clip: Animation) -> ClipSampler:
        """The regrouped form of a clip, built on first sight of it.

        A clip put into :attr:`clips` after the mixer was made is regrouped
        here, and what it moves joins what the mixer knows how to write -- so
        a game may add a clip at any point and have it play.
        """
        found = self._samplers.get(id(clip))
        if found is None:
            found = ClipSampler(clip, self.rig)
            self._samplers[id(clip)] = found
            self._note_driven(found)
        return found

    def _note_driven(self, sampler: ClipSampler) -> None:
        before = int(self.driven.sum())
        for slots in (sampler.slots_translation, sampler.slots_rotation,
                      sampler.slots_scale):
            self.driven[slots] = True
        if int(self.driven.sum()) != before:
            self._undriven = np.flatnonzero(~self.driven)
            self._all_write_slots = np.flatnonzero(self.driven).astype(np.int32)
            self._exposed_signature = None

    def _plan_skins(self) -> None:
        """Note where each skin's joints sit in the rig, once rather than per frame."""
        self._skin_plans: List[Tuple[Any, np.ndarray, np.ndarray, int]] = []
        for skin in self.skins:
            joints = getattr(skin, 'joints', None)
            if joints is None or getattr(skin, 'inverse_bind', None) is None:
                continue
            slots = np.asarray([self.rig.slot_of.get(int(j), -1) for j in joints],
                               dtype=np.int32)
            mesh_slot = self.rig.slot_of.get(int(getattr(skin, 'mesh_node', -1)), -1)
            inverse_bind = np.asarray(skin.inverse_bind, dtype='d')
            if len(inverse_bind) < len(slots):
                # A skin with fewer inverse-bind matrices than joints binds the
                # remainder at the identity, as the one-at-a-time path does.
                pad = np.tile(np.eye(4), (len(slots) - len(inverse_bind), 1, 1))
                inverse_bind = np.concatenate([inverse_bind, pad])
            self._skin_plans.append(
                (skin, slots, inverse_bind[:len(slots)], mesh_slot))

    @staticmethod
    def _rest_value(xform: Any, path: str, width: int) -> np.ndarray:
        """Where one path sits with nothing playing.

        The node's authored transform for translation/rotation/scale. A
        ``weights`` channel rests at zero, which is the pose glTF gives a
        morphable mesh whose weights nothing has set.
        """
        if path == 'translation':
            return np.array(getattr(xform, 'translation', (0.0, 0.0, 0.0)), dtype='d')
        if path == 'scale':
            return np.array(getattr(xform, 'scale', (1.0, 1.0, 1.0)), dtype='d')
        if path == 'rotation':
            return vrml_to_quat_xyzw(getattr(xform, 'rotation', (0.0, 1.0, 0.0, 0.0)))
        return np.zeros(width, dtype='d')

    # -- layers and playback ---------------------------------------------
    def layer(self, name: str = BASE_LAYER, *,
              mask: Optional[Iterable[int]] = None,
              weight: Optional[float] = None,
              additive: bool = False) -> Layer:
        """The layer called ``name``, made on first use.

        ``mask``, ``weight`` and ``additive`` describe the layer when it is
        made; asking for an existing layer returns it as it is, so a caller may
        fetch it by name every frame without restating how it was set up.
        """
        found = self._by_name.get(name)
        if found is None:
            found = Layer(name, mask=mask,
                          weight=1.0 if weight is None else weight,
                          additive=additive)
            found._clips = self.clips
            self.layers.append(found)
            self._by_name[name] = found
        return found

    def play(self, name: str, *, layer: str = BASE_LAYER, fade: float = 0.0,
             loop: bool = True, speed: float = 1.0, restart: bool = False,
             reference: float = 0.0) -> Track:
        """Play ``name`` on ``layer`` -- see :meth:`Layer.play`."""
        return self.layer(layer).play(name, fade=fade, loop=loop, speed=speed,
                                      restart=restart, reference=reference)

    def stop(self, layer: str = BASE_LAYER, fade: float = 0.0) -> None:
        """Fade one layer out -- see :meth:`Layer.stop`."""
        self.layer(layer).stop(fade=fade)

    def reset(self) -> None:
        """Stop everything at once and put the model back in its rest pose.

        A respawn, a scene change, a review tool starting the next take: any
        moment where what a body was doing has no bearing on what it is about
        to do. Fading would be wrong for all of them -- a body that comes back
        alive should not ease out of dying -- so every track goes now, and the
        pose is written from the rest values rather than left where the last
        frame put it.
        """
        for layer in self.layers:
            layer.tracks = []
        self.apply()

    @property
    def playing(self) -> tuple:
        """The names of every clip contributing to the pose, in layer order."""
        return tuple(track.name for layer in self.layers for track in layer.tracks
                     if track.weight > 0)

    # -- the frame --------------------------------------------------------
    def update(self, dt: float) -> None:
        """Advance every track by ``dt`` seconds and pose the model."""
        step = max(0.0, float(dt))
        for layer in self.layers:
            layer._settle(step)
        self.apply()

    def apply(self) -> None:
        """Pose the model from where the tracks stand, without moving them on.

        Separate from :meth:`update` so a caller holding the clock still -- a
        capture, a paused game, a posed still -- can put the model where its
        tracks say it is without time passing.
        """
        pose = self.pose()
        weights: Dict[int, np.ndarray] = {}
        for layer in self.layers:
            if layer.weight and layer.tracks:
                self._apply_layer(layer, pose, weights)
        self._write(pose, weights)
        self._reskin(pose)

    def pose(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The rest pose to blend over: translation, rotation and scale arrays.

        Fresh arrays, one row per rig slot. A slot no clip drives is re-read
        from its own transform first, so a joint a game placed by hand is where
        the game put it rather than where the document rested.
        """
        if len(self._undriven):
            self.rig.refresh_rest(self._undriven)
        return self.rig.rest_pose()

    def _apply_layer(self, layer: Layer,
                     pose: Tuple[np.ndarray, np.ndarray, np.ndarray],
                     weights: Dict[int, np.ndarray]) -> None:
        """Blend one layer's tracks over the pose built so far."""
        mask = layer.slot_mask(self.rig)
        blends = [_Blend(self.rig.n, width,
                         rotation=(path == 'rotation' and not layer.additive))
                  for path, width in _PATHS]
        blended_weights: Dict[int, List[Any]] = {}
        for track in layer.tracks:
            if track.weight <= 0:
                continue
            sampler = self._sampler(track.clip)
            sampled = sampler.sample(track.time)
            base = sampler.sample(track.reference) if layer.additive else None
            for index, (path, _width) in enumerate(_PATHS):
                slots = (sampler.slots_translation, sampler.slots_rotation,
                         sampler.slots_scale)[index]
                if not len(slots):
                    continue
                values = sampled[index]
                if layer.additive:
                    values = _delta_rows(path, values, base[index])  # type: ignore[index]
                if mask is not None:
                    keep = mask[slots]
                    slots, values = slots[keep], values[keep]
                blends[index].add(slots, values, track.weight)
            self._accumulate_weights(layer, sampler, track, blended_weights)
        for index, (path, _width) in enumerate(_PATHS):
            blends[index].combine(path, pose[index], layer)
        for node, (value, total) in blended_weights.items():
            current = weights.get(node)
            if current is None:
                current = np.zeros(len(np.atleast_1d(value)), dtype='d')
            strength = layer.weight * (total if layer.additive else min(1.0, total))
            weights[node] = (_add('weights', current, value, strength)
                             if layer.additive
                             else _lerp('weights', current, value, strength))

    def _accumulate_weights(self, layer: Layer, sampler: ClipSampler, track: Track,
                            store: Dict[int, List[Any]]) -> None:
        """Fold a track's morph weights into the layer's running mean.

        Morph weights are per mesh and of no fixed width, so they keep the
        one-at-a-time arithmetic rather than joining the skeleton's arrays.
        """
        sampled = sampler.sample_weights(track.time)
        if not sampled:
            return
        base = sampler.sample_weights(track.reference) if layer.additive else {}
        for node, value in sampled.items():
            if layer.mask is not None and node not in layer.mask:
                continue
            if layer.additive:
                value = _delta('weights', value, base[node])
            _accumulate(store, node, value, track.weight, False)

    def _write(self, pose: Tuple[np.ndarray, np.ndarray, np.ndarray],
               weights: Dict[int, np.ndarray]) -> None:
        """Put the finished pose onto the scenegraph, where anything reads it.

        A joint whose only children are further joints is read by nothing: the
        skin takes its matrices from the pose arrays directly, so writing that
        joint's fields would be arithmetic nobody collects. What is written is
        every slot something outside the rig reaches -- a mesh, an attachment
        point with a weapon on it -- and every joint on the way down to one.
        """
        slots = self._writable()
        if len(slots):
            axis_angle = quat_xyzw_to_vrml_rows(pose[1][slots])
            # One conversion out of numpy for the lot: a tuple built a float at
            # a time, once a joint, is most of what writing a pose back costs.
            translations = pose[0][slots].tolist()
            rotations = axis_angle.tolist()
            scales = pose[2][slots].tolist()
            for row, slot in enumerate(slots):
                self._write_slot(int(slot), translations[row], rotations[row],
                                 scales[row])
        for node, value in weights.items():
            self._write_weights(node, value)

    def observe(self, *nodes: int) -> None:
        """Say that these glTF nodes' transforms are going to be read.

        Only meaningful under ``pose_write = 'exposed'``, where a joint nothing
        reaches is left unwritten: naming one here brings it back into the set,
        so a game that wants to read where a figure's head ended up can, at the
        cost of that one joint.
        """
        self._observed.update(int(n) for n in nodes)
        self._exposed_signature = None

    def _writable(self) -> np.ndarray:
        """The slots to write, recomputed when the hierarchy's shape changes."""
        if self.pose_write != 'exposed':
            return self._all_write_slots
        exposed = self.rig.exposed_slots()
        if exposed is not self._exposed_signature:
            self._exposed_signature = exposed
            wanted = set(exposed)
            for node in self._observed:
                slot = self.rig.slot_of.get(node)
                if slot is not None:
                    wanted.add(slot)
            self._write_slots = np.asarray(
                sorted(s for s in wanted if self.driven[s]), dtype=np.int32)
        return self._write_slots

    def _write_slot(self, slot: int, translation: Sequence[float],
                    rotation: Sequence[float], scale: Sequence[float]) -> None:
        """Put one joint's translation, rotation and scale on its Transform.

        The values come as plain sequences of floats rather than array rows:
        the caller converts the whole pose out of numpy in one go, because
        doing it a number at a time is most of what writing a pose costs.
        """
        xform = self.rig.transforms[slot]
        if xform is None:
            return
        if self.rig.baked[slot]:
            node = int(self.rig.indices[slot])
            if node not in self._warned:
                self._warned.add(node)
                log.warning(
                    'node %d carries a baked matrix, which an animation cannot '
                    'drive; it is left where it is', node)
            return
        for path, value in (('translation', translation), ('rotation', rotation),
                            ('scale', scale)):
            written = tuple(value)
            key = (slot, path)
            if self._written.get(key) == written:
                continue
            self._written[key] = written
            setattr(xform, path, written)

    def _write_weights(self, node: int, value: np.ndarray) -> None:
        written = np.asarray(value, dtype='f')
        key = (node, 'weights')
        previous = self._written.get(key)
        if previous is not None and np.array_equal(previous, written):
            return
        self._written[key] = written
        for setter in self.node_morph.get(node, ()):
            setter(written)

    def _reskin(self, pose: Tuple[np.ndarray, np.ndarray, np.ndarray]) -> None:
        """Rebuild every skin's joint matrices from the pose just blended."""
        if not self.skins:
            return
        if self.compute_worlds is not None:
            worlds = self.compute_worlds()
            for skin in self.skins:
                skin.apply(worlds)
            return
        matrices = self.joint_matrices(pose)
        for (skin, _slots, _bind, _mesh), mats in zip(self._skin_plans, matrices,
                                                      strict=True):
            for mesh in skin.meshes:
                mesh.set_skin_matrices(mats)
        planned = {id(skin) for skin, _s, _b, _m in self._skin_plans}
        strangers = [s for s in self.skins if id(s) not in planned]
        if strangers:
            mapped = self.rig.world_matrix_map(
                self.rig.world_matrices(*pose))
            for skin in strangers:
                skin.apply(mapped)

    def joint_matrices(self, pose: Optional[Tuple[np.ndarray, ...]] = None) -> List[np.ndarray]:
        """The ``(J, 4, 4)`` joint-matrix stack of each skin, in skin order.

        What a skinning shader wants uploaded, and what the CPU deform applies
        directly. ``pose`` defaults to where the tracks stand now.
        """
        if pose is None:
            pose = self.pose()
            for layer in self.layers:
                if layer.weight and layer.tracks:
                    self._apply_layer(layer, pose, {})
        worlds = self.rig.world_matrices(*pose)
        identity = np.eye(4)
        out: List[np.ndarray] = []
        for _skin, slots, inverse_bind, mesh_slot in self._skin_plans:
            joint_worlds = np.tile(identity, (len(slots), 1, 1))
            known = slots >= 0
            joint_worlds[known] = worlds[slots[known]]
            node_inverse = (np.linalg.inv(worlds[mesh_slot]) if mesh_slot >= 0
                            else identity)
            out.append(inverse_bind @ joint_worlds @ node_inverse)
        return out


# ======================================================================
# The arithmetic
# ======================================================================

class _Blend:
    """A layer's running weighted mean of one path, over the whole skeleton.

    The same arithmetic :func:`_accumulate` and :func:`_lerp` do one value at a
    time -- a mean rather than a sum, so two clips at full weight give the
    midpoint between them and not twice either -- kept for every slot at once,
    with a note of which slots any track of the layer has reached. Slots no
    track reached keep whatever the layer beneath them left.
    """

    __slots__ = ('values', 'total', 'touched', 'rotation')

    def __init__(self, n: int, width: int, rotation: bool) -> None:
        self.values = np.zeros((n, width), dtype='d')
        self.total = np.zeros(n, dtype='d')
        self.touched = np.zeros(n, dtype=bool)
        self.rotation = rotation

    def add(self, slots: np.ndarray, values: np.ndarray, weight: float) -> None:
        """Fold one track's values, at ``weight``, into the mean."""
        if not len(slots):
            return
        seen = self.touched[slots]
        fresh = ~seen
        if fresh.any():
            self.values[slots[fresh]] = values[fresh]
        if seen.any():
            rows = slots[seen]
            fraction = weight / (self.total[rows] + weight)
            current = self.values[rows]
            incoming = values[seen]
            self.values[rows] = (
                quat_slerp_rows(current, incoming, fraction) if self.rotation
                else current + (incoming - current) * fraction[:, None])
        self.total[slots] += weight
        self.touched[slots] = True

    def combine(self, path: str, target: np.ndarray, layer: "Layer") -> None:
        """Write this layer's contribution over the pose built so far."""
        rows = np.flatnonzero(self.touched)
        if not len(rows):
            return
        total = self.total[rows]
        strength = layer.weight * (total if layer.additive
                                   else np.minimum(1.0, total))
        current, value = target[rows], self.values[rows]
        target[rows] = (_add_rows(path, current, value, strength) if layer.additive
                        else _lerp_rows(path, current, value, strength))


def _lerp_rows(path: str, current: np.ndarray, value: np.ndarray,
               strength: np.ndarray) -> np.ndarray:
    """``strength`` of the way from the pose so far to this layer's, per row.

    A layer at full strength everywhere -- one clip playing, nothing fading,
    which is what a figure does almost all of the time -- is this layer's own
    values and nothing else, so the blend is not worth computing to throw away.
    """
    full = strength >= 1.0
    if full.all():
        return value
    if path == 'rotation':
        out = quat_slerp_rows(current, value, strength)
    else:
        out = current + (value - current) * strength[:, None]
    if full.any():
        out[full] = value[full]
    return out


def _delta_rows(path: str, value: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """How far each row is from the additive layer's reference frame."""
    if path == 'rotation':
        return quat_multiply_rows(value, quat_conjugate_rows(reference))
    if path == 'scale':
        safe = np.where(np.abs(reference) < 1e-9, 1.0, reference)
        return np.asarray(value / safe)
    return np.asarray(value - reference)


def _add_rows(path: str, current: np.ndarray, delta: np.ndarray,
              strength: np.ndarray) -> np.ndarray:
    """Apply an additive layer's difference on top of the pose so far, per row."""
    if path == 'rotation':
        eased = quat_slerp_rows(np.tile(_IDENTITY, (len(delta), 1)), delta, strength)
        return quat_multiply_rows(eased, current)
    if path == 'scale':
        return np.asarray(current * (1.0 + (delta - 1.0) * strength[:, None]))
    return np.asarray(current + delta * strength[:, None])


def _accumulate(store: Dict[Any, List[Any]], key: Any,
                value: Any, weight: float, rotation: bool) -> None:
    """Fold one track's value into a running weighted mean.

    A mean rather than a sum, because two clips at weight one each should give
    the midpoint between them and not twice either. Additive layers pass
    ``rotation`` False and read the accumulated *total* rather than the mean,
    which is what makes them add up instead.
    """
    entry = store.get(key)
    incoming = np.asarray(value, dtype='d')
    if entry is None:
        store[key] = [incoming.copy(), weight]
        return
    current, total = entry
    fraction = weight / (total + weight)
    if rotation:
        entry[0] = quat_slerp(current, incoming, fraction)
    else:
        entry[0] = current + (incoming - current) * fraction
    entry[1] = total + weight


def _lerp(path: str, current: np.ndarray, value: np.ndarray,
          strength: float) -> np.ndarray:
    """``strength`` of the way from the pose so far to this layer's."""
    if strength >= 1.0:
        return value
    if path == 'rotation':
        return quat_slerp(current, value, strength)
    return np.asarray(current + (value - current) * strength)


def _delta(path: str, value: np.ndarray,
           reference: np.ndarray) -> np.ndarray:
    """How far ``value`` is from the additive layer's reference frame."""
    if path == 'rotation':
        return quat_multiply(value, _conjugate(reference))
    if path == 'scale':
        safe = np.where(np.abs(reference) < 1e-9, 1.0, reference)
        return np.asarray(np.asarray(value, dtype='d') / safe)
    return np.asarray(np.asarray(value, dtype='d') - reference)


def _add(path: str, current: np.ndarray, delta: np.ndarray,
         strength: float) -> np.ndarray:
    """Apply an additive layer's difference on top of the pose so far."""
    if path == 'rotation':
        return quat_multiply(quat_slerp(_IDENTITY, delta, strength), current)
    if path == 'scale':
        return current * (1.0 + (delta - 1.0) * strength)
    return current + delta * strength


def _conjugate(q: np.ndarray) -> np.ndarray:
    """The inverse of a unit [x, y, z, w] quaternion."""
    q = quat_normalize(q)
    return np.array([-q[0], -q[1], -q[2], q[3]])
