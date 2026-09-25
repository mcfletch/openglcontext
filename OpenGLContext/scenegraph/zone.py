"""The ``Zone`` node: a region of space and the settings that hold inside it.

A zone is a shape -- a box, sphere, capsule or cylinder, placed by the
transforms above it -- and a list of settings, each one a node of its own in
:attr:`Zone.settings`:

==========================  ================================================
:class:`ZoneEnvironment`    The image-based lighting of what is drawn inside:
                            a multiplier, and optionally a probe captured
                            inside the zone.
:class:`ZoneLights`         Punctual lights that light only what is inside.
:class:`ZoneAudio`          Emitters heard while the camera is inside.
:class:`ZoneReverb`         The reverb heard while the camera is inside.
:class:`ZoneVisibility`     Nodes shown, or hidden, while the camera is inside.
:class:`ZoneMirrors`        Mirrors that draw their reflection only while the
                            camera is inside.
:class:`ZoneGravity`        The gravity bodies inside feel.
==========================  ================================================

A setting whose ``enabled`` is false switches that setting off inside the
zone: a ``ZoneLights`` that is not enabled turns off every light a document
brought for what is inside, and a ``ZoneMirrors`` that is not enabled stops
every mirror drawing its reflection for a camera inside.

Something a zone switches on is controlled by zones from then on: a light,
an emitter or a mirror named by any zone is on for what is inside a zone
naming it and off everywhere else. A light no zone names lights everything,
as it would in a scene with no zones.

Where zones overlap, each setting is decided on its own. The zone with the
higher ``priority`` wins, a tie goes to the smaller zone, and ``blend`` fades
a zone's effect out over that many metres beyond its shape; see
:func:`OpenGLContext.scenegraph.zones.layers`.

A glTF document declares zones with the ``OGLC_zone`` extension, which
:mod:`OpenGLContext.loaders.gltf.zoning` reads into these nodes. The guide is
``docs/zones.rst`` and the specification ``docs/extensions/OGLC_zone.rst``.
"""
from __future__ import annotations

import logging
import weakref
from dataclasses import dataclass
from typing import Any, Dict, Hashable, Iterable, List, Optional, Tuple

import numpy as np
from pydispatch import dispatcher
from vrml import field, node
from vrml.vrml97 import nodetypes

from OpenGLContext.scenegraph import zones
from OpenGLContext.scenegraph.zones import PlacedShape, ShapeSpec

log = logging.getLogger(__name__)

__all__ = [
    'Zone', 'ZoneSetting', 'ZoneEnvironment', 'ZoneLights', 'ZoneAudio',
    'ZoneReverb', 'ZoneVisibility', 'ZoneMirrors', 'ZoneGravity',
    'PlacedZone', 'ENVIRONMENT', 'LIGHTS', 'AUDIO', 'REVERB', 'VISIBILITY',
    'MIRRORS', 'GRAVITY', 'placed_zones', 'setting_version',
]

#: The key each kind of setting is decided under. The zone's own settings use
#: the name the ``OGLC_zone`` block gives them; the rest use the name of the
#: extension whose block they were read from.
ENVIRONMENT = 'environment'
REVERB = 'reverb'
LIGHTS = 'KHR_lights_punctual'
AUDIO = 'KHR_audio_emitter'
VISIBILITY = 'KHR_node_visibility'
MIRRORS = 'OGLC_hook.mirror'
GRAVITY = 'OMI_physics_gravity'


class ZoneSetting(node.Node):
    """One setting a zone carries; see the subclasses."""

    #: What the setting is decided under; see :func:`zones.layers`.
    SETTING = ''
    #: False switches the setting off inside the zone.
    enabled = field.newField('enabled', 'SFBool', 1, True)


class ZoneEnvironment(ZoneSetting):
    """Image-based lighting for what is drawn inside the zone.

    ``intensity`` multiplies the environment's diffuse and specular light,
    the way the context's ``iblIntensity`` does for the whole scene. With
    ``capture`` false the environment is the scene's own; with it true, it is
    a probe captured from ``captureCentre`` (in the zone's own frame, its
    centre by default) the first time something the zone lights is drawn,
    and captured again the first time the camera is inside the zone. The
    probe replaces the scene's environment inside the zone rather than being
    added to it. ``light`` names an ``ImageBasedLight`` to use as the probe
    instead, which is what a document's ``EXT_lights_image_based`` block
    becomes.

    Lightmaps and light grids are not scaled: a bake already holds its own
    occlusion.
    """
    PROTO = 'ZoneEnvironment'
    SETTING = ENVIRONMENT
    intensity = field.newField('intensity', 'SFFloat', 1, 1.0)
    capture = field.newField('capture', 'SFBool', 1, False)
    captureCentre = field.newField('captureCentre', 'SFVec3f', 1, (0.0, 0.0, 0.0))
    light = field.newField('light', 'SFNode', 1, node.NULL)


class ZoneLights(ZoneSetting):
    """Punctual lights that light only what is drawn inside the zone."""
    PROTO = 'ZoneLights'
    SETTING = LIGHTS
    lights = field.newField('lights', 'MFNode', 1, list)


class ZoneAudio(ZoneSetting):
    """Emitters heard only while the camera is inside the zone.

    An emitter's gain is multiplied by how far the camera is inside, so it
    fades out over the zone's ``blend``.
    """
    PROTO = 'ZoneAudio'
    SETTING = AUDIO
    emitters = field.newField('emitters', 'MFNode', 1, list)


class ZoneReverb(ZoneSetting):
    """The reverb heard while the camera is inside the zone.

    ``level`` runs from 0 to 1 against the dry sound, ``decay`` is the time in
    seconds for a sound to fall by 60 dB, and ``damping`` from 0 to 1 is how
    much of the top each return loses. See :mod:`omi_audio.reverb`.
    """
    PROTO = 'ZoneReverb'
    SETTING = REVERB
    level = field.newField('level', 'SFFloat', 1, 0.4)
    decay = field.newField('decay', 'SFFloat', 1, 1.5)
    damping = field.newField('damping', 'SFFloat', 1, 0.4)


class ZoneVisibility(ZoneSetting):
    """Nodes shown only while the camera is inside, or hidden while it is.

    With ``visible`` true the nodes are drawn only for a camera inside the
    zone; with it false they are hidden from a camera inside and drawn for
    one outside.
    """
    PROTO = 'ZoneVisibility'
    SETTING = VISIBILITY
    nodes = field.newField('nodes', 'MFNode', 1, list)
    visible = field.newField('visible', 'SFBool', 1, True)


class ZoneMirrors(ZoneSetting):
    """Mirrors that draw their reflection only while the camera is inside.

    ``nodes`` are the nodes whose meshes are mirrors. A mirror whose
    reflection is not drawn reflects the environment probe, as a mirror too
    small or too far to be worth a reflection does.
    """
    PROTO = 'ZoneMirrors'
    SETTING = MIRRORS
    nodes = field.newField('nodes', 'MFNode', 1, list)


class ZoneGravity(ZoneSetting):
    """The gravity bodies inside the zone feel, as ``OMI_physics_gravity`` defines it.

    ``type`` is ``directional`` (along ``direction``) or ``point`` (towards
    ``center``, in the zone's own frame), ``gravity`` the acceleration in
    metres per second squared. ``replace`` overrides gravity from volumes
    below this one and ``stop`` cancels it; otherwise the fields add. The
    fields are named as the extension names its properties, ``type``
    included, so a block and its node read alike.
    """
    PROTO = 'ZoneGravity'
    SETTING = GRAVITY
    type = field.newField('type', 'SFString', 1, 'directional')
    gravity = field.newField('gravity', 'SFFloat', 1, 9.81)
    direction = field.newField('direction', 'SFVec3f', 1, (0.0, -1.0, 0.0))
    center = field.newField('center', 'SFVec3f', 1, (0.0, 0.0, 0.0))
    replace = field.newField('replace', 'SFBool', 1, False)
    stop = field.newField('stop', 'SFBool', 1, False)


class Zone(nodetypes.Children, node.Node):
    """A region of space, and the settings that hold inside it.

    The shape is ``shapeType`` -- ``box``, ``sphere``, ``capsule`` or
    ``cylinder`` -- with its dimensions as glTF's implicit shapes give them:
    a box's full ``size``, a sphere's ``radius``, and a capsule's or
    cylinder's ``height``, ``radiusTop`` and ``radiusBottom``, round about +Y.
    It is centred on the node's origin and placed by the transforms above it,
    so a box is an oriented box.

    ``priority`` decides between overlapping zones and ``blend`` is how many
    metres beyond the shape its effect takes to fade to nothing.
    """
    PROTO = 'Zone'
    shapeType = field.newField('shapeType', 'SFString', 1, zones.BOX)
    size = field.newField('size', 'SFVec3f', 1, (1.0, 1.0, 1.0))
    radius = field.newField('radius', 'SFFloat', 1, 0.5)
    height = field.newField('height', 'SFFloat', 1, 0.5)
    radiusTop = field.newField('radiusTop', 'SFFloat', 1, 0.25)
    radiusBottom = field.newField('radiusBottom', 'SFFloat', 1, 0.25)
    priority = field.newField('priority', 'SFInt32', 1, 0)
    blend = field.newField('blend', 'SFFloat', 1, 0.0)
    settings = field.newField('settings', 'MFNode', 1, list)

    def shape(self) -> ShapeSpec:
        """The zone's shape in its own frame."""
        x, y, z = (float(v) for v in self.size)
        return ShapeSpec(str(self.shapeType), size=(x, y, z),
                         radius=float(self.radius), height=float(self.height),
                         radius_top=float(self.radiusTop),
                         radius_bottom=float(self.radiusBottom))

    def setting(self, key: str) -> Optional[ZoneSetting]:
        """The zone's setting decided under ``key``, or None where it has none."""
        for item in self.settings or ():
            if getattr(item, 'SETTING', None) == key:
                found: ZoneSetting = item
                return found
        return None

    def keys(self) -> List[str]:
        """The settings this zone carries, by the key each is decided under."""
        return [item.SETTING for item in self.settings or ()
                if getattr(item, 'SETTING', '')]


@dataclass(frozen=True, eq=False)
class PlacedZone:
    """A zone where it is this frame: its node, its placed shape and its rules.

    :func:`placed_zones` hands back the same object while nothing about the
    zone has changed -- its place, its shape, its rules or any of its
    settings -- so a new object is how a caller learns that one did. Two
    placements compare equal only when they are the same object.
    """

    zone: Zone
    shape: PlacedShape
    priority: int
    blend: float
    #: The zone's local-to-world matrix, row-vector.
    matrix: np.ndarray

    @property
    def volume(self) -> float:
        return self.shape.volume

    def weight(self, point: Any) -> float:
        """How much the world ``point`` is inside the zone, from nought to one."""
        return float(zones.weight(self.shape.distance(point), self.blend))

    def setting(self, key: str) -> Optional[ZoneSetting]:
        return self.zone.setting(key)

    def candidate(self, key: str, weight: float) -> Tuple[Any, Any, float, int, float]:
        """This zone's entry in :func:`zones.layers` for setting ``key``.

        The block is the setting node, or None where it switches the setting
        off.
        """
        item = self.zone.setting(key)
        block = item if item is not None and bool(item.enabled) else None
        return (id(self.zone), block, weight, self.priority, self.volume)

    def to_world(self, local: Iterable[float]) -> np.ndarray:
        """A point in the zone's own frame, in the world."""
        point = np.ones(4)
        point[:3] = tuple(local)
        world: np.ndarray = (point @ self.matrix)[:3]
        return world


#: Each setting node's count of changes, by node; see :func:`setting_version`.
_setting_changes: "weakref.WeakKeyDictionary[ZoneSetting, int]" = weakref.WeakKeyDictionary()

#: The zones whose shape type was refused, each reported once.
_refused: "weakref.WeakSet[Zone]" = weakref.WeakSet()


def setting_version(setting: ZoneSetting) -> int:
    """How many times a field of ``setting`` has been set or deleted.

    A zone's placement is made again when this moves for any of its
    settings, so an edit to a setting reaches what was worked out from it.
    """
    return _setting_changes.get(setting, 0)


def _setting_changed(sender: Any = None, **_named: Any) -> None:
    if isinstance(sender, ZoneSetting):
        _setting_changes[sender] = _setting_changes.get(sender, 0) + 1


def _watch_setting_fields() -> None:
    """Count every set and delete of a field of any setting class."""
    todo = [ZoneSetting]
    while todo:
        cls = todo.pop()
        todo.extend(cls.__subclasses__())
        for value in vars(cls).values():
            if isinstance(value, field.Field):
                for signal in ('set', 'del'):
                    dispatcher.connect(_setting_changed, signal=(signal, value),
                                       weak=False)


def _settings_key(zone: Zone) -> Tuple[Tuple[Hashable, int], ...]:
    """The zone's settings, each with its version, as a comparable value."""
    return tuple((setting, setting_version(setting)) for setting in zone.settings or ())


def placed_zones(found: Iterable[Tuple[Zone, Any]],
                 cache: Optional[Dict[Tuple[Zone, int], Tuple[Any, Tuple[Any, ...], PlacedZone]]] = None
                 ) -> List[PlacedZone]:
    """Each zone placed by its world matrix, for one frame.

    ``found`` pairs each zone with its row-vector world matrix, in the same
    order from frame to frame; a zone met more than once (a ``USE``) is a
    placement for each time. ``cache``, a dict the caller keeps between
    frames, holds each placement against the matrix object, the shape and
    rules, and the settings with their versions it was made from, so a zone
    that has not moved or changed keeps its :class:`PlacedZone`. A zone
    whose shape type is not one a zone may use is left out, and reported
    once.
    """
    result = []
    seen: Dict[Zone, int] = {}
    for zone, matrix in found:
        occurrence = seen.get(zone, 0)
        seen[zone] = occurrence + 1
        key = (str(zone.shapeType), tuple(zone.size), float(zone.radius),
               float(zone.height), float(zone.radiusTop),
               float(zone.radiusBottom), int(zone.priority), float(zone.blend),
               _settings_key(zone))
        held = cache.get((zone, occurrence)) if cache is not None else None
        if held is not None and held[0] is matrix and held[1] == key:
            result.append(held[2])
            continue
        try:
            spec = zone.shape()
        except ValueError as error:
            if zone not in _refused:
                _refused.add(zone)
                log.warning('zone %s is left out: %s',
                            getattr(zone, 'DEF', None) or '(unnamed)', error)
            continue
        m = np.asarray(matrix, dtype='d')
        placed = PlacedZone(zone, zones.place(spec, m), int(zone.priority),
                            max(float(zone.blend), 0.0), m)
        if cache is not None:
            cache[(zone, occurrence)] = (matrix, key, placed)
        result.append(placed)
    return result


_watch_setting_fields()
