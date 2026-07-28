"""The ``KHR_audio_emitter`` data model, natively.

Plain dataclasses mirroring the glTF audio extension field-for-field, with the
extension's own defaults and its own spelling.  The loader, the scenegraph nodes
and :class:`~OpenGLContext.audio.engine.AudioEngine` all speak this structure,
so glTF import and export are a near-identity mapping and there is no private
format to keep in sync -- the same decision :mod:`omi_physics.model` makes for
physics.

Three arrays, referenced by index, and the indirection is worth understanding
because it is what lets one file's sounds be shared:

``audio``
    Where the encoded bytes are -- a ``uri`` beside the document, or a
    ``bufferView`` inside it.
``sources``
    One piece of audio *plus how to play it*: gain, playback rate, whether it
    loops, whether it starts by itself.  Several emitters may use one source.
``emitters``
    Where the sound comes from: ``global`` for music and ambience that ignores
    the listener, ``positional`` for a sound in the world, which carries the
    distance curve and cone in its :class:`PositionalProperties`.

References:
    ``KHR_audio_emitter``
    https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/KHR_audio_emitter
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional

from OpenGLContext.audio import spatial

#: The extension's name, as it appears in ``extensionsUsed`` and in the
#: ``extensions`` object of the document, its scenes and its nodes.
EXTENSION = 'KHR_audio_emitter'

#: An emitter fixed to the listener: background music, ambience, narration.
GLOBAL = 'global'
#: An emitter at a place in the scene, attenuated by distance and direction.
POSITIONAL = 'positional'

#: The one MIME type the base extension requires.  ``OMI_audio_ogg_vorbis`` and
#: ``OMI_audio_opus`` add others; what this engine can actually decode is a
#: separate question, answered in :mod:`OpenGLContext.audio.clip`.
MIME_MPEG = 'audio/mpeg'


@dataclass
class Audio:
    """One piece of encoded audio data, by ``uri`` or by ``bufferView``.

    ``mimeType`` is required alongside a ``bufferView``, since there is no file
    name to infer the format from.
    """

    uri: str = ''
    bufferView: Optional[int] = None
    mimeType: str = ''
    name: str = ''


@dataclass
class AudioSource:
    """A piece of audio data and the playback settings applied to it.

    ``gain`` is a linear multiplier, not decibels: 0.5 is half amplitude.
    ``playbackRate`` changes speed and pitch together, as speeding up a record
    does -- it is a resampling ratio, not a pitch shift.
    """

    audio: Optional[int] = None
    gain: float = 1.0
    playbackRate: float = 1.0
    loop: bool = False
    autoplay: bool = False
    name: str = ''


@dataclass
class PositionalProperties:
    """How a positional emitter's loudness depends on where the listener is.

    Two independent curves, multiplied: :func:`~.spatial.distance_gain` over
    ``distanceModel``/``refDistance``/``maxDistance``/``rolloffFactor``, and
    :func:`~.spatial.cone_gain` over the three cone fields.  The cone applies
    only when ``shapeType`` is ``cone``; the defaults describe a full sphere in
    any case, so an emitter that sets none of them is unattenuated by direction.
    """

    shapeType: str = spatial.ShapeType.OMNIDIRECTIONAL.value
    coneInnerAngle: float = spatial.TAU
    coneOuterAngle: float = spatial.TAU
    coneOuterGain: float = 0.0
    distanceModel: str = spatial.DistanceModel.INVERSE.value
    maxDistance: float = 0.0
    refDistance: float = 1.0
    rolloffFactor: float = 1.0

    def gain(self, distance: float, angle: float = 0.0) -> float:
        """Combined distance and cone attenuation, as a linear multiplier.

        ``distance`` is listener-to-emitter; ``angle`` is how far off the
        emitter's forward axis the listener lies, in radians.
        """
        gain = spatial.distance_gain(
            distance, self.distanceModel, ref_distance=self.refDistance,
            max_distance=self.maxDistance, rolloff_factor=self.rolloffFactor)
        if self.shapeType == spatial.ShapeType.CONE.value:
            gain *= spatial.cone_gain(angle, self.coneInnerAngle,
                                      self.coneOuterAngle, self.coneOuterGain)
        return gain


@dataclass
class AudioEmitter:
    """Where sound comes from: a place in the scene, or everywhere at once.

    A ``positional`` emitter always has :class:`PositionalProperties`, defaulted
    if the document left them out, so nothing downstream tests for their
    absence.  A ``global`` emitter has none, because the extension forbids them.
    """

    type: str = POSITIONAL
    gain: float = 1.0
    sources: List[int] = field(default_factory=list)
    positional: Optional[PositionalProperties] = None
    name: str = ''

    def __post_init__(self) -> None:
        if self.positional_audio and self.positional is None:
            self.positional = PositionalProperties()
        elif not self.positional_audio:
            self.positional = None

    @property
    def positional_audio(self) -> bool:
        """Whether this emitter is placed in the scene rather than global."""
        return self.type == POSITIONAL


@dataclass
class AudioDocument:
    """The three arrays a document's ``KHR_audio_emitter`` block holds.

    Indices are resolved through :meth:`sources_for` and :meth:`audio_for`
    rather than by indexing directly, because content is not always well formed
    and an index that points at nothing should cost a sound, not a traceback.
    """

    audio: List[Audio] = field(default_factory=list)
    sources: List[AudioSource] = field(default_factory=list)
    emitters: List[AudioEmitter] = field(default_factory=list)

    def sources_for(self, emitter: AudioEmitter) -> List[AudioSource]:
        """The sources ``emitter`` plays, skipping any index out of range."""
        return [self.sources[index] for index in emitter.sources
                if 0 <= index < len(self.sources)]

    def audio_for(self, source: AudioSource) -> Optional[Audio]:
        """The audio data ``source`` names, or None if it names none."""
        if source.audio is None or not (0 <= source.audio < len(self.audio)):
            return None
        return self.audio[source.audio]


def _read(cls: type, block: Dict[str, Any]) -> Any:
    """Build ``cls`` from ``block``, taking the fields it declares.

    Keys the model does not declare are dropped rather than rejected: a document
    may use extensions this engine has never heard of, and refusing to load it
    would trade a missing feature for a missing scene.
    """
    names = {entry.name for entry in fields(cls)}
    return cls(**{key: value for key, value in block.items() if key in names})


def from_gltf(block: Dict[str, Any]) -> AudioDocument:
    """Read a document-level ``KHR_audio_emitter`` extension block."""
    emitters = []
    for entry in block.get('emitters', ()):
        emitter = _read(AudioEmitter, entry)
        positional = entry.get('positional')
        if positional is not None and emitter.positional_audio:
            emitter.positional = _read(PositionalProperties, positional)
        emitters.append(emitter)
    return AudioDocument(
        audio=[_read(Audio, entry) for entry in block.get('audio', ())],
        sources=[_read(AudioSource, entry) for entry in block.get('sources', ())],
        emitters=emitters,
    )


def _write(record: Any) -> Dict[str, Any]:
    """``record`` as JSON, omitting every field still at its default."""
    default = type(record)()
    return {entry.name: getattr(record, entry.name) for entry in fields(record)
            if getattr(record, entry.name) != getattr(default, entry.name)}


def to_gltf(document: AudioDocument) -> Dict[str, Any]:
    """Write an :class:`AudioDocument` back as an extension block.

    Only non-default fields are written, and only non-empty arrays, so a
    round-tripped document is no larger than the one that was read.
    """
    block: Dict[str, Any] = {}
    if document.audio:
        block['audio'] = [_write(entry) for entry in document.audio]
    if document.sources:
        block['sources'] = [_write(entry) for entry in document.sources]
    if document.emitters:
        emitters = []
        for emitter in document.emitters:
            entry = _write(emitter)
            positional = entry.pop('positional', None)
            entry.setdefault('type', emitter.type)      # `type` is required
            if positional is not None:
                entry['positional'] = _write(positional)
            emitters.append(entry)
        block['emitters'] = emitters
    return block
