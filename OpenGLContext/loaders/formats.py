"""Choosing the reader for a source.

``model.glb``, ``world.wrl`` and ``tileset.json`` are opened by the same call;
what differs is one :class:`~OpenGLContext.loaders.readers.SceneReader`,
chosen from the source itself.  The choice is data, not an ``if`` chain:
readers register against the suffixes and content types they handle through
:class:`OpenGLContext.plugins.Adapter`, alongside the loader, context and node
registries, and a third party adds a format by registering one more entry.  A
:class:`~OpenGLContext.viewer.adapters.base.SceneAdapter` is a reader that a
viewer can also show.

    from OpenGLContext.loaders.formats import adapter_for

    reader = adapter_for('model.glb')    # an instance, one per request

:class:`~OpenGLContext.loaders.sceneloader.SceneLoader` is the interface most
code wants; this module is what it asks.
"""
from __future__ import annotations

import os
import re
import urllib.parse
from typing import TYPE_CHECKING, Any, Optional

from OpenGLContext.loaders.documentvalues import parse_object
from OpenGLContext.loaders.resolver import contained_source, open_contained

if TYPE_CHECKING:
    from OpenGLContext.loaders.readers import SceneReader

__all__ = ['SNIFF_BYTES', 'UnknownSourceType', 'adapter_for', 'adapter_named',
           'known_sources', 'scene_names']

#: How much of an unrecognised file to read when sniffing its content.  A
#: tileset's ``asset`` and ``root`` keys are at the top of the document, and a
#: loader must not pull a gigabyte of JSON into memory to find out what it is.
SNIFF_BYTES = 64 * 1024


class UnknownSourceType(ValueError):
    """No adapter is registered for this source."""


def _keys() -> dict[str, Any]:
    """Every registered key -> its plugin entry, lowercased.

    Read afresh each time rather than memoised: registrations are a module-level
    side effect of importing a package, so a cache built during start-up would
    miss whatever registered next.
    """
    from OpenGLContext import plugins
    found = {}
    for entry in plugins.Adapter.all():
        for key in entry.check or ():
            found[key.lower()] = entry
    return found


def _adapter(entry: Any) -> SceneReader:
    """Instantiate a plugin entry's reader class."""
    loaded = entry.load()
    if loaded is None:
        raise UnknownSourceType(
            "the %r reader is registered but could not be imported; see the "
            "log for why" % (entry.name,))
    reader: SceneReader = loaded()
    return reader


def known_sources() -> tuple[str, ...]:
    """Every suffix and content type a registered reader opens, sorted to be read."""
    return tuple(sorted(_keys()))


def scene_names() -> tuple[str, ...]:
    """Every file-name ending a registered reader opens (``.x3d``,
    ``.wrl.gz``, ``tileset.json``), longest first; content types left out"""
    return tuple(sorted((key for key in _keys() if '/' not in key),
                        key=lambda key: (-len(key), key)))


def adapter_named(name: str) -> SceneReader:
    """The reader registered as ``name`` (``gltf``, ``vrml97``, ...)."""
    from OpenGLContext import plugins
    entry = plugins.Adapter.by_name(name)
    if entry is None:
        raise UnknownSourceType(
            "no format named %r; registered: %s"
            % (name, ', '.join(sorted(e.name for e in plugins.Adapter.all()))))
    return _adapter(entry)


def _path_of(source: str) -> str:
    """The path part of ``source``, lowercased, with any query or fragment gone.

    A URL's ``?token=...`` is not part of the file's name, and a loader that let
    it decide the format would open ``model.glb?v=2`` as nothing at all.
    """
    return urllib.parse.urlsplit(source).path.lower() or source.lower()


def _by_suffix(source: str) -> Optional[Any]:
    """The entry whose key the source's name ends with, longest key first.

    Longest wins so a specific name beats a generic suffix: ``tileset.json`` is
    3D Tiles where a bare ``.json`` is whatever registered for it.
    """
    path = _path_of(source)
    keys = {key: entry for key, entry in _keys().items() if '/' not in key}
    for key in sorted(keys, key=len, reverse=True):
        if path.endswith(key):
            return keys[key]
    return None


def _by_content_type(contentType: str) -> Optional[Any]:
    """The entry registered for a served resource's type.

    Parameters are dropped: ``model/vrml; charset=utf-8`` is ``model/vrml``.
    """
    return _keys().get(contentType.split(';')[0].strip().lower())


#: The start of an X3D JSON document: an object whose first key is "X3D".
_X3D_JSON = re.compile(rb'^\s*\{\s*"X3D"\s*:')


def _sniff(source: str) -> Optional[Any]:
    """Look inside a local file whose name did not settle it.

    Only JSON is sniffed: a 3D Tiles tileset and an X3D JSON document are the
    formats in regular use named ``anything.json``. X3D JSON is told by its
    first key, a tileset by its ``asset`` and ``root``.  Anything unreadable
    simply does not match -- sniffing must never be the thing that raises.
    """
    from OpenGLContext import plugins
    if not os.path.isfile(source):
        return None
    try:
        with open_contained(contained_source(source)) as handle:
            head = handle.read(SNIFF_BYTES)
        if _X3D_JSON.match(head.lstrip(b'\xef\xbb\xbf')):
            return plugins.Adapter.by_name('x3d')
        document = parse_object(head, source)
    except (OSError, ValueError):
        return None
    if 'asset' in document and 'root' in document:
        return plugins.Adapter.by_name('tiles3d')
    return None


def adapter_for(source: str, contentType: Optional[str] = None) -> SceneReader:
    """The reader that opens ``source``.

    Decided by content type when one is known -- a served resource is named by
    its type, not by a suffix -- then by the source's own name, then by looking
    inside a local file whose name settled nothing.

    Raises :class:`UnknownSourceType` naming what *is* known, since "cannot open
    that" without "these are what I open" sends the reader to the source.
    """
    entry = None
    if contentType:
        entry = _by_content_type(contentType)
    if entry is None:
        entry = _by_suffix(source) or _sniff(source)
    if entry is None:
        raise UnknownSourceType(
            "do not know how to open %r; recognised: %s"
            % (source, ', '.join(known_sources())))
    return _adapter(entry)
