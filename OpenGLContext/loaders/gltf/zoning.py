"""Reading ``OGLC_zone``: a shape, and the extensions that apply inside it.

A glTF node carrying ``OGLC_zone`` is a region of space. Its block names a
shape from the document's shape table (:mod:`~OpenGLContext.loaders.gltf.shapes`)
and lists what holds inside it::

    {"OGLC_zone": {
        "shape": 0, "priority": 0, "blend": 1.0,
        "environment": {"intensity": 0.12},
        "reverb": {"level": 0.4, "decay": 1.8},
        "extensions": {
            "KHR_audio_emitter": {"emitters": [2]},
            "KHR_lights_punctual": {"nodes": [5]}
        }}}

The zone's own properties (``environment`` and ``reverb``) are settings no
extension defines. Each entry of ``extensions`` is the form that extension
takes at scene level, or ``false`` to switch the extension off inside the
zone, and is read by the reader registered for that extension's name. The
specification is ``docs/extensions/OGLC_zone.rst``.

**A document names an extension; it never names code.** The readers are a
registry the running program fills: the engine registers the extensions it
supports (:data:`BUILTIN`) when this module is imported, and an application
adds its own with :func:`register_scoped`. A name nothing is registered for
is reported once per document and the zone's other settings still apply,
which is also what happens for a whole ``OGLC_zone`` block in a viewer that
does not read it: the file loads without zones.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, overload

from OpenGLContext.loaders.documentvalues import DocumentValues, JSONObject, require_object
from OpenGLContext.loaders.gltf import shapes as shapetable
from OpenGLContext.scenegraph.zone import (
    AUDIO, GRAVITY, LIGHTS, MIRRORS, VISIBILITY, Zone, ZoneAudio,
    ZoneEnvironment, ZoneGravity, ZoneLights, ZoneMirrors, ZoneReverb,
    ZoneSetting, ZoneVisibility,
)

log = logging.getLogger(__name__)

__all__ = [
    'EXTENSION', 'BUILTIN', 'ZoneReading', 'ZoneReader', 'Reader',
    'register_scoped', 'unregister_scoped', 'registered_scoped',
]

#: The node extension a zone is written as.
EXTENSION = 'OGLC_zone'


@dataclass
class ZoneReading:
    """What a reader is given to turn one extension's block into a setting.

    ``document`` is the parsed glTF and ``zone`` the node being built.
    ``node_transform`` gives the scenegraph node built for a glTF node index,
    ``light`` the light built for it, ``emitters`` the emitter nodes built for
    an emitter index (building one for a global emitter the document does not
    place anywhere else), and ``place`` puts a node the reader built at the
    root of the scene. ``warn`` reports a problem with the block once per
    document.
    """

    document: Any
    zone: Zone
    node_index: int
    node_transform: Callable[[int], Any]
    light: Callable[[int], Any]
    emitters: Callable[[int], List[Any]]
    place: Callable[[Any], None]
    warn: Callable[[str], None]
    #: The ``EXT_lights_image_based`` light at an index, or None.
    image_light: Callable[[int], Any] = lambda index: None
    #: Settings other readers made for this zone, which a reader may extend
    #: rather than add a second of.
    settings: List[ZoneSetting] = field(default_factory=list)
    #: What a reader reads a block's values through, reporting by ``warn``.
    values: DocumentValues = field(default_factory=DocumentValues)


#: A reader: the extension's block (a dict, or False) and the reading, to a
#: setting node, or None where the block says nothing the engine can use.
Reader = Callable[[object, ZoneReading], Optional[ZoneSetting]]

_READERS: Dict[str, Reader] = {}


@overload
def register_scoped(name: str) -> Callable[[Reader], Reader]: ...


@overload
def register_scoped(name: str, reader: Reader) -> Reader: ...


def register_scoped(name: str, reader: Optional[Reader] = None
                    ) -> Union[Reader, Callable[[Reader], Reader]]:
    """Read extension ``name``'s block in a zone with ``reader``.

    Usable as a call, which returns ``reader``, or as a decorator. Registering
    a name again replaces the reader, which is how an application overrides
    one of the engine's.
    """
    def bind(function: Reader) -> Reader:
        _READERS[name] = function
        return function
    if reader is not None:
        return bind(reader)
    return bind


def unregister_scoped(name: str) -> None:
    """Stop reading extension ``name`` in zones."""
    _READERS.pop(name, None)


def registered_scoped() -> List[str]:
    """The extension names zones are read for, sorted."""
    return sorted(_READERS)


def _indices(block: object, key: str) -> List[int]:
    values = block.get(key) if isinstance(block, dict) else None
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, int) and not isinstance(v, bool)]


@register_scoped(LIGHTS)
def _read_lights(block: object, reading: ZoneReading) -> Optional[ZoneSetting]:
    """``KHR_lights_punctual``: ``{"nodes": [...]}`` names light nodes."""
    if block is False:
        return ZoneLights(enabled=False)
    lights = []
    for index in _indices(block, 'nodes'):
        light = reading.light(index)
        if light is None:
            reading.warn('KHR_lights_punctual names node %d, which carries no '
                         'light' % (index,))
            continue
        lights.append(light)
    return ZoneLights(lights=lights)


@register_scoped(AUDIO)
def _read_audio(block: object, reading: ZoneReading) -> Optional[ZoneSetting]:
    """``KHR_audio_emitter``: the scene form, ``{"emitters": [...]}``."""
    if block is False:
        return ZoneAudio(enabled=False)
    emitters: List[Any] = []
    for index in _indices(block, 'emitters'):
        found = reading.emitters(index)
        if not found:
            reading.warn('KHR_audio_emitter names emitter %d, which is neither '
                         'placed on a node nor global' % (index,))
        emitters.extend(found)
    return ZoneAudio(emitters=emitters)


@register_scoped(VISIBILITY)
def _read_visibility(block: object, reading: ZoneReading) -> Optional[ZoneSetting]:
    """``KHR_node_visibility``: ``{"nodes": [...], "visible": true}``."""
    if block is False or not isinstance(block, dict):
        reading.warn('KHR_node_visibility in a zone names the nodes it shows; '
                     'false has nothing to switch off')
        return None
    nodes = [n for n in (reading.node_transform(i) for i in _indices(block, 'nodes'))
             if n is not None]
    return ZoneVisibility(nodes=nodes, visible=reading.values.flag(
        block.get('visible'), True, 'KHR_node_visibility visible'))


@register_scoped('OGLC_hook')
def _read_hooks(block: object, reading: ZoneReading) -> Optional[ZoneSetting]:
    """``OGLC_hook``, addressed by kind: ``{"mirror": false | {"nodes": [...]}}``."""
    if not isinstance(block, dict):
        reading.warn('OGLC_hook in a zone is addressed by kind, as '
                     '{"mirror": false}')
        return None
    for kind in block:
        if kind != 'mirror':
            reading.warn('OGLC_hook kind %r has no zone setting' % (kind,))
    mirror = block.get('mirror')
    if mirror is None:
        return None
    if mirror is False:
        return ZoneMirrors(enabled=False)
    nodes = [n for n in (reading.node_transform(i) for i in _indices(mirror, 'nodes'))
             if n is not None]
    return ZoneMirrors(nodes=nodes)


@register_scoped(GRAVITY)
def _read_gravity(block: object, reading: ZoneReading) -> Optional[ZoneSetting]:
    """``OMI_physics_gravity``, as a gravity volume's block."""
    if block is False:
        return ZoneGravity(stop=True)
    if not isinstance(block, dict):
        return None
    values = reading.values
    return ZoneGravity(
        type=values.text(block.get('type'), 'directional', 'the zone gravity type'),
        gravity=values.number(block.get('gravity'), 9.81, 'the zone gravity'),
        direction=values.vector(block.get('direction'), (0.0, -1.0, 0.0),
                                'the zone gravity direction'),
        center=values.vector(block.get('center'), (0.0, 0.0, 0.0),
                             'the zone gravity centre'),
        replace=values.flag(block.get('replace'), False, 'the zone gravity replace'),
        stop=values.flag(block.get('stop'), False, 'the zone gravity stop'))


@register_scoped('EXT_lights_image_based')
def _read_image_light(block: object, reading: ZoneReading) -> Optional[ZoneSetting]:
    """``EXT_lights_image_based``: ``{"light": n}``, its scene form.

    The light becomes the zone's environment probe; the zone's own
    ``environment`` block, where it has one, still sets the intensity.
    """
    if block is False:
        return ZoneEnvironment(enabled=False)
    index = block.get('light') if isinstance(block, dict) else None
    light = reading.image_light(index) if isinstance(index, int) else None
    if light is None:
        reading.warn('EXT_lights_image_based names light %r, which the document '
                     'does not have' % (index,))
        return None
    for setting in reading.settings:
        if isinstance(setting, ZoneEnvironment):
            setting.light = light
            return None
    return ZoneEnvironment(light=light)


#: The extensions the engine reads in a zone. Registered on import.
BUILTIN = tuple(registered_scoped())


#: The most and least a zone's ``priority`` may be: an ``SFInt32``.
_INT32 = (-2 ** 31, 2 ** 31 - 1)


def _environment(block: object, values: DocumentValues) -> Optional[ZoneEnvironment]:
    if not isinstance(block, dict):
        return None
    raw = block.get('capture', False)
    centre: Tuple[float, ...] = (0.0, 0.0, 0.0)
    if isinstance(raw, dict):
        centre = values.vector(raw.get('position'), centre,
                               'the environment capture position')
        capture = True
    else:
        capture = values.flag(raw, False, 'the environment capture')
    return ZoneEnvironment(
        intensity=values.number(block.get('intensity'), 1.0,
                                'the environment intensity', minimum=0.0),
        capture=capture, captureCentre=centre)


def _reverb(block: object, values: DocumentValues) -> Optional[ZoneReverb]:
    if not isinstance(block, dict):
        return None
    return ZoneReverb(
        level=values.number(block.get('level'), 0.4, 'the reverb level',
                            minimum=0.0, maximum=1.0),
        decay=values.number(block.get('decay'), 1.5, 'the reverb decay',
                            minimum=0.0),
        damping=values.number(block.get('damping'), 0.4, 'the reverb damping',
                              minimum=0.0, maximum=1.0))


class ZoneReader:
    """Reads a document's ``OGLC_zone`` blocks into :class:`Zone` nodes.

    :meth:`zone_for` is called for each glTF node as the scene is built and
    returns the node's zone, carrying the zone's own settings. Blocks that
    name other nodes wait for :meth:`finish`, after every node has been built,
    since a zone may name a light or an emitter further down the document.
    """

    def __init__(self, document: Any) -> None:
        self.document = document
        self.shapes = shapetable.document_shapes(document)
        self.zones: List[Zone] = []
        #: Each zone with its glTF node index and the blocks it borrows,
        #: read once every node is built.
        self._pending: List[Tuple[Zone, int, JSONObject]] = []
        self._warned: Set[str] = set()
        #: What the zones' own values are read through, reporting by :meth:`warn`.
        self.values = DocumentValues(warn=self.warn)

    def warn(self, message: str) -> None:
        """Log ``message`` once for this document."""
        if message not in self._warned:
            self._warned.add(message)
            log.warning('%s: %s', EXTENSION, message)

    def zone_for(self, node: Any, node_index: int) -> Optional[Zone]:
        """The zone glTF node ``node_index`` declares, or None.

        A value the zone cannot use is reported and left at its default; a
        block that cannot be made into a zone at all is reported and is no
        zone, and the document loads without it.
        """
        extensions = getattr(node, 'extensions', None) or {}
        block = extensions.get(EXTENSION) if isinstance(extensions, dict) else None
        if not isinstance(block, dict):
            return None
        try:
            return self._zone(require_object(block, EXTENSION), node, node_index)
        except (TypeError, ValueError, OverflowError) as error:
            self.warn('node %r could not be read as a zone: %s'
                      % (getattr(node, 'name', None) or node_index, error))
            return None

    def _zone(self, block: JSONObject, node: Any,
              node_index: int) -> Optional[Zone]:
        values = self.values
        index = block.get('shape')
        spec = shapetable.shape_at(self.document, index, self.shapes)
        if spec is None:
            self.warn('node %r names shape %r, which is not a box, sphere, capsule '
                      'or cylinder in the document\'s shape table; it is not a zone'
                      % (getattr(node, 'name', None) or node_index, index))
            return None
        zone = Zone(shapeType=spec.kind, size=spec.size, radius=spec.radius,
                    height=spec.height, radiusTop=spec.radius_top,
                    radiusBottom=spec.radius_bottom,
                    priority=values.integer(block.get('priority'), 0,
                                            'the zone priority',
                                            minimum=_INT32[0], maximum=_INT32[1]),
                    blend=values.number(block.get('blend'), 0.0, 'the zone blend',
                                        minimum=0.0))
        own = [setting for setting in (_environment(block.get('environment'), values),
                                       _reverb(block.get('reverb'), values))
               if setting is not None]
        zone.settings = own
        borrowed = block.get('extensions')
        if isinstance(borrowed, dict) and borrowed:
            self._pending.append((zone, node_index,
                                  require_object(borrowed, 'the zone extensions')))
        self.zones.append(zone)
        return zone

    def finish(self, node_transform: Callable[[int], Any],
               light: Callable[[int], Any],
               emitters: Callable[[int], List[Any]],
               place: Callable[[Any], None],
               image_light: Callable[[int], Any] = lambda index: None) -> None:
        """Read every zone's borrowed extension blocks, now every node is built."""
        for zone, node_index, borrowed in self._pending:
            reading = ZoneReading(self.document, zone, node_index, node_transform,
                                  light, emitters, place, self.warn, image_light,
                                  list(zone.settings), self.values)
            for name, block in borrowed.items():
                reader = _READERS.get(name)
                if reader is None:
                    self.warn('no reader is registered for %r; zones leave it '
                              'unchanged' % (name,))
                    continue
                try:
                    setting = reader(block, reading)
                except Exception as error:
                    self.warn('the %s block could not be read: %s' % (name, error))
                    continue
                if setting is not None and setting not in reading.settings:
                    reading.settings.append(setting)
            zone.settings = reading.settings
        self._pending = []
