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

from OpenGLContext.loaders.gltf.animation import (
    Animation, compute_world_matrices, quat_multiply, quat_normalize,
    quat_slerp, quat_xyzw_to_vrml, vrml_to_quat_xyzw,
)

log = logging.getLogger(__name__)

__all__ = ['Track', 'Layer', 'AnimationMixer', 'BASE_LAYER']

#: The layer a clip plays on when none is named.
BASE_LAYER = 'base'

#: The identity rotation, as glTF stores one.
_IDENTITY = np.array([0.0, 0.0, 0.0, 1.0])


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
    """

    def __init__(self, clips: Mapping[str, Animation],
                 node_transforms: Optional[Mapping[int, Any]] = None,
                 node_morph: Optional[Mapping[int, Sequence[Callable]]] = None,
                 skins: Optional[Iterable[Any]] = None,
                 compute_worlds: Optional[Callable[[], dict]] = None) -> None:
        self.clips: Dict[str, Animation] = dict(clips)
        self.node_transforms: Dict[int, Any] = dict(node_transforms or {})
        self.node_morph: Dict[int, Sequence[Callable]] = dict(node_morph or {})
        self.skins: List[Any] = list(skins or ())
        self.compute_worlds = compute_worlds
        self.layers: List[Layer] = []
        self._by_name: Dict[str, Layer] = {}
        #: node index -> the paths some clip drives on it, and how wide each is.
        self._paths: Dict[int, Dict[str, int]] = {}
        #: node index -> path -> the value the model rests at, which is what a
        #: partly-weighted layer blends towards and what a stopped clip leaves.
        self._rest: Dict[int, Dict[str, np.ndarray]] = {}
        #: The last value written to each path, so an unchanged pose costs no
        #: field assignments -- and an idle character costs almost nothing.
        self._written: Dict[Tuple[int, str], Any] = {}
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

        def compute_worlds() -> dict:
            return compute_world_matrices(roots, children, transforms)

        return cls(clips, transforms,
                   node_morph=getattr(scene, 'node_morph', None),
                   skins=skins,
                   compute_worlds=compute_worlds if skins else None)

    def _survey(self) -> None:
        """Note what the clips can move, and where the model rests."""
        for clip in self.clips.values():
            for channel in clip.channels:
                width = int(np.asarray(channel.sampler.values).shape[1])
                paths = self._paths.setdefault(channel.node_index, {})
                paths[channel.path] = max(paths.get(channel.path, 0), width)
        for node, paths in self._paths.items():
            xform = self.node_transforms.get(node)
            rest: Dict[str, np.ndarray] = {}
            for path, width in paths.items():
                rest[path] = self._rest_value(xform, path, width)
            self._rest[node] = rest

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
        pose = {node: dict(rest) for node, rest in self._rest.items()}
        for layer in self.layers:
            if layer.weight and layer.tracks:
                self._apply_layer(layer, pose)
        self._write(pose)
        self._reskin()

    def _apply_layer(self, layer: Layer, pose: Dict[int, Dict[str, np.ndarray]]) -> None:
        """Blend one layer's tracks over the pose built so far."""
        blended: Dict[Tuple[int, str], List[Any]] = {}
        for track in layer.tracks:
            if track.weight <= 0:
                continue
            sampled = track.clip.evaluate(track.time)
            base = (track.clip.evaluate(track.reference) if layer.additive else None)
            for node, paths in sampled.items():
                if layer.mask is not None and node not in layer.mask:
                    continue
                for path, value in paths.items():
                    if layer.additive:
                        value = _delta(path, value, base[node][path])  # type: ignore[index]
                    _accumulate(blended, (node, path), value, track.weight,
                                path == 'rotation' and not layer.additive)
        for (node, path), (value, total) in blended.items():
            current = pose.setdefault(node, {}).get(path)
            if current is None:
                current = self._rest_value(self.node_transforms.get(node), path,
                                           len(np.atleast_1d(value)))
                pose[node][path] = current
            strength = layer.weight * (total if layer.additive else min(1.0, total))
            pose[node][path] = (_add(path, current, value, strength)
                                if layer.additive
                                else _lerp(path, current, value, strength))

    def _write(self, pose: Dict[int, Dict[str, np.ndarray]]) -> None:
        """Put the finished pose onto the scenegraph."""
        for node, paths in pose.items():
            xform = self.node_transforms.get(node)
            for path, value in paths.items():
                if path == 'weights':
                    self._write_weights(node, value)
                elif xform is not None:
                    self._write_trs(node, xform, path, value)

    def _write_trs(self, node: int, xform: Any, path: str, value: np.ndarray) -> None:
        if getattr(xform, '_forward', None) is not None:
            if node not in self._warned:
                self._warned.add(node)
                log.warning(
                    'node %d carries a baked matrix, which an animation cannot '
                    'drive; it is left where it is', node)
            return
        if path == 'rotation':
            written: Any = quat_xyzw_to_vrml(value)
        else:
            written = (float(value[0]), float(value[1]), float(value[2]))
        key = (node, path)
        if self._written.get(key) == written:
            return
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

    def _reskin(self) -> None:
        """Rebuild the joint matrices from the joint transforms just written."""
        if not self.skins or self.compute_worlds is None:
            return
        worlds = self.compute_worlds()
        for skin in self.skins:
            skin.apply(worlds)


# ======================================================================
# The arithmetic
# ======================================================================

def _accumulate(store: Dict[Tuple[int, str], List[Any]], key: Tuple[int, str],
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
