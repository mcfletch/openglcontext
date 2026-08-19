"""Build pygltflib documents from glTF JSON without dataclasses_json.

pygltflib decodes JSON through ``dataclasses_json``, which resolves a class's type
hints and runs ``issubclass`` checks *per decoded object*. A glTF file names one
object per accessor, bufferView, node and animation channel, so a rigged character
-- thousands of each -- spends seconds in that machinery for a document ``json``
itself parses in milliseconds.

The document is plain data and pygltflib's classes are plain dataclasses whose
field names are the glTF property names, with no custom per-field decoders. So the
same objects can be built directly: resolve each class's field types *once*, cache
the plan, and walk the parsed JSON applying it. :func:`decode_gltf` returns a
``GLTF2`` indistinguishable from ``GLTF2.from_json``; :func:`load_glb` is the same
for a binary ``.glb``, blob and all.

``Attributes`` is the one class pygltflib does not make a dataclass -- it accepts
arbitrary vertex-attribute names -- so it is rebuilt from its dict directly, custom
attributes included.
"""
from __future__ import annotations

import dataclasses
import json
import struct
import typing
from typing import Any, Callable, Dict, List, Tuple

import pygltflib

#: GLB container constants (glTF 2.0 §4.4): little-endian magic and chunk tags.
_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942

Converter = Callable[[Any], Any]

#: One decode plan per dataclass, resolved on first sight and reused. This is the
#: cache dataclasses_json lacks: the plan is the whole cost, and there are 28
#: classes against thousands of objects.
_PLANS: Dict[type, List[Tuple[str, Converter]]] = {}


def _identity(value: Any) -> Any:
    return value


def _attributes(value: Any) -> Any:
    """A mesh primitive's vertex attributes, custom names and all."""
    return pygltflib.Attributes(**value) if isinstance(value, dict) else value


def _converter(hint: Any) -> Converter:
    """How to decode one field of type ``hint`` into a pygltflib value.

    Optionals unwrap to their one real type; a list maps its element converter;
    a dataclass recurses; :class:`~pygltflib.Attributes` is rebuilt from its
    dict; everything else -- ints, floats, strings, the ``extensions``/``extras``
    dicts -- passes straight through.
    """
    origin = typing.get_origin(hint)
    if origin is typing.Union:
        real = [a for a in typing.get_args(hint) if a is not type(None)]
        return _converter(real[0]) if len(real) == 1 else _identity
    if origin in (list, List):
        args = typing.get_args(hint)
        # A morph target is typed List[Attributes], but pygltflib leaves those
        # elements as plain dicts (it decodes Attributes only as a direct field),
        # so a list of them passes straight through to match.
        element = (_identity if (args and args[0] is pygltflib.Attributes)
                   else _converter(args[0]) if args else _identity)
        if element is _identity:
            return _identity

        def decode_list(value: Any, element: Converter = element) -> Any:
            return value if value is None else [element(item) for item in value]

        return decode_list
    if hint is pygltflib.Attributes:
        return _attributes
    if dataclasses.is_dataclass(hint):

        def decode_struct(value: Any, hint: Any = hint) -> Any:
            return _decode(hint, value) if isinstance(value, dict) else value

        return decode_struct
    return _identity


def _plan(cls: type) -> List[Tuple[str, Converter]]:
    """The (field name, converter) list for ``cls``, resolved once."""
    plan = _PLANS.get(cls)
    if plan is None:
        hints = typing.get_type_hints(cls)
        plan = [(f.name, _converter(hints[f.name])) for f in dataclasses.fields(cls)]
        _PLANS[cls] = plan
    return plan


def _decode(cls: type, data: Dict[str, Any]) -> Any:
    """One dataclass instance from its JSON object.

    Only the properties the document names are passed to the constructor, so an
    absent property takes the class's own default -- the value pygltflib's decode
    reports for it too.
    """
    kwargs = {name: convert(data[name])
              for name, convert in _plan(cls) if name in data}
    return cls(**kwargs)


def decode_gltf(source: "str | bytes | bytearray | dict") -> "pygltflib.GLTF2":
    """A ``GLTF2`` from glTF JSON text, bytes, or an already-parsed dict.

    Equivalent to ``pygltflib.GLTF2.from_json`` for a ``.gltf`` document; the
    binary buffer of a ``.glb`` is handled by :func:`load_glb`.
    """
    if isinstance(source, dict):
        document = source
    else:
        text = source.decode('utf-8') if isinstance(source, (bytes, bytearray)) else source
        document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError('glTF document must be a JSON object, not %s'
                         % type(document).__name__)
    return _decode(pygltflib.GLTF2, document)


def load_glb(data: bytes) -> "pygltflib.GLTF2":
    """A ``GLTF2`` from binary ``.glb`` bytes, JSON decoded fast and blob attached.

    Reads the container's chunks (glTF 2.0 §4.4): the JSON chunk becomes the
    document through :func:`decode_gltf`, and the binary chunk becomes its
    buffer blob -- the same result as ``GLTF2.load_from_bytes``.
    """
    if len(data) < 12:
        raise ValueError('not a GLB file: shorter than a GLB header')
    magic, _version, length = struct.unpack('<III', data[:12])
    if magic != _GLB_MAGIC:
        raise ValueError('not a GLB file: bad magic %08x' % magic)
    gltf = None
    blob = None
    index = 12
    limit = min(length, len(data))
    while index + 8 <= limit:
        chunk_length, chunk_type = struct.unpack('<II', data[index:index + 8])
        index += 8
        chunk = data[index:index + chunk_length]
        index += chunk_length
        if chunk_type == _CHUNK_JSON and gltf is None:
            gltf = decode_gltf(chunk)
        elif chunk_type == _CHUNK_BIN and blob is None:
            blob = chunk
    if gltf is None:
        raise ValueError('GLB file has no JSON chunk')
    if blob is not None:
        gltf.set_binary_blob(bytes(blob))
    return gltf
