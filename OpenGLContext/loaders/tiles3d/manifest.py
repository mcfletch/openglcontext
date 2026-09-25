"""What a baked world *is*, written down beside the tiles that draw it.

A tileset says how to draw a world and nothing about what it is. Anything
offering somebody a **choice** of worlds needs more than that before it loads
one: what it is called, how long its road is, how much of that road is carried
on structures, and which picture shows it. Reading a tileset to find out means
loading the world, which is the thing being chosen between.

So whatever bakes a world writes a manifest -- one small JSON file named
:data:`MANIFEST`, beside the tileset -- and a chooser reads a directory of
them::

    >>> from OpenGLContext.loaders.tiles3d.manifest import WorldManifest
    >>> WorldManifest(name='Ashdown', road_length=8306.9).summary()
    'Ashdown, 8.3 km'

It is written for a person as much as for a program: indented, with the keys
spelled out, so a world can be renamed or given a picture by editing it.

Reading one is the runtime half and is here; *filling* one in is authoring, and
belongs to whatever built the world (``OpenGLContext_editor.bin.bake`` does it
for the shipped baker).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, TypeVar

from OpenGLContext import atomicfiles
from OpenGLContext.loaders.resolver import contained_source
from OpenGLContext.loaders.documentvalues import (
    DocumentValues, JSONObject, parse_object, require_number, require_object, require_text,
)

__all__ = ['MANIFEST', 'WorldManifest', 'carried', 'read_manifest',
           'write_manifest']

log = logging.getLogger(__name__)

#: What the manifest is called, beside the tileset it describes.
MANIFEST = 'world.json'

_T = TypeVar('_T')


@dataclass
class WorldManifest:
    """One baked world, as something choosing between them sees it.

    ``name`` is the only thing required, because it is the only thing that
    cannot be done without: everything else is description, and a manifest from
    an older bake that lacks a field is read rather than refused.

    ``tileset`` and ``picture`` are named relative to the manifest, so a whole
    world is one directory that can be moved or copied. ``road_length`` is in
    metres and ``structures`` is how many metres of the road are carried on each
    kind of structure -- what tells a bridge-and-tunnel circuit from a road that
    lies on the land.
    """

    name: str
    tileset: str = 'tileset.json'
    picture: str | None = None
    seed: int | None = None
    extent: float | None = None
    road_length: float | None = None
    structures: dict[str, float] = field(default_factory=dict)
    closed: bool = True
    baked: str | None = None

    def summary(self) -> str:
        """One line: what it is called and how far round it goes."""
        if self.road_length is None:
            return self.name
        return '%s, %.1f km' % (self.name, self.road_length / 1000.0)

    def to_json(self) -> dict[str, Any]:
        """The document written to disk, with nothing empty in it."""
        document: dict[str, Any] = {'name': self.name, 'tileset': self.tileset,
                                    'closed': bool(self.closed)}
        for key, value in (('picture', self.picture), ('seed', self.seed),
                           ('extent', self.extent),
                           ('roadLength', self.road_length),
                           ('baked', self.baked)):
            if value is not None:
                document[key] = value
        if self.structures:
            document['structures'] = dict(self.structures)
        return document

    @classmethod
    def from_json(cls, document: JSONObject) -> WorldManifest:
        """Read one back. A document with no name is not a world.

        A value of the wrong type is a
        :class:`~OpenGLContext.loaders.documentvalues.DocumentError`, which
        :func:`read_manifest` reports and reads as no manifest.
        """
        name = document.get('name')
        if not name:
            raise ValueError("a world manifest has to say what the world is called")

        def number(key: str) -> float:
            return require_number(document.get(key), 'the world manifest %s' % (key,))

        def text(key: str) -> str:
            return require_text(document.get(key), 'the world manifest %s' % (key,))

        structures = require_object(document.get('structures') or {},
                                    'the world manifest structures')
        return cls(
            name=require_text(name, 'the world manifest name'),
            tileset=text('tileset') if 'tileset' in document else 'tileset.json',
            picture=_or_none(document, 'picture', text),
            seed=_or_none(document, 'seed', lambda key: int(number(key))),
            extent=_or_none(document, 'extent', number),
            road_length=_or_none(document, 'roadLength', number),
            structures={kind: require_number(metres, 'the metres on %s' % (kind,))
                        for kind, metres in structures.items()},
            closed=DocumentValues(logger=log).flag(document.get('closed'), True,
                                                   'the world manifest closed'),
            baked=_or_none(document, 'baked', text))


def carried(path: Any) -> dict[str, float]:
    """How many metres of a road are carried on each kind of structure.

    ``path`` is anything with ``structure_runs()`` yielding ``(kind, start,
    end)`` in metres along the road -- what tells a bridge-and-tunnel circuit
    from a road that lies on the land, and one of the few things about a world
    worth knowing before it is loaded.
    """
    total: dict[str, float] = {}
    for kind, start, end in path.structure_runs():
        name = str(getattr(kind, 'value', kind))
        total[name] = total.get(name, 0.0) + float(end) - float(start)
    return total


def write_manifest(directory: str, manifest: WorldManifest) -> str:
    """Write one beside a tileset; answer where it went."""
    where = os.path.join(directory, MANIFEST)
    atomicfiles.write_text(
        where, json.dumps(manifest.to_json(), indent=2, sort_keys=True) + '\n')
    return where


def read_manifest(where: str) -> WorldManifest | None:
    """The manifest for a world, or None where there is not one to read.

    ``where`` is the world's directory, its tileset, or the manifest itself,
    since a caller has whichever of those it was handed. A manifest that will
    not parse is *absent* rather than an error: a chooser scanning a directory
    of worlds should skip the broken one and offer the rest.
    """
    path = contained_source(where if os.path.basename(where) == MANIFEST else os.path.join(
        where if os.path.isdir(where) else os.path.dirname(where), MANIFEST))
    try:
        with open(path, encoding='utf-8') as handle:
            return WorldManifest.from_json(parse_object(handle.read(), path))
    except FileNotFoundError:
        return None
    except (ValueError, OSError):
        log.warning('could not read the world manifest %s', path, exc_info=True)
        return None


def _or_none(document: JSONObject, key: str, read: Callable[[str], _T]) -> _T | None:
    """``read(key)``, or None for a key the document did not carry."""
    return None if document.get(key) is None else read(key)
