"""Choosing how to open a source, and opening it.

``oglc-view model.glb``, ``oglc-view world.wrl`` and ``oglc-view tileset.json``
are the same viewer; what differs is one adapter, chosen from the source itself
rather than from which command was typed.

The choice is *data*, not an ``if`` chain: adapters register against the
suffixes and content types they handle through
:class:`OpenGLContext.plugins.Adapter`, alongside the loader, context and node
registries.  A third party adds a format by registering one more entry.

    from OpenGLContext.viewer.adapters import adapter_for

    adapter = adapter_for('model.glb')
    scene = adapter.load('model.glb')

See [docs/gltf.html](../../../docs/gltf.html).
"""
import json
import os
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from OpenGLContext.viewer.adapters.base import (
    SceneAdapter, UnknownSourceType, ViewerScene,
)

__all__ = ['SceneAdapter', 'ViewerScene', 'UnknownSourceType', 'adapter_for',
           'adapter_named', 'known_sources']

#: How much of an unrecognised file to read when sniffing its content.  A
#: tileset's ``asset`` and ``root`` keys are at the top of the document, and a
#: viewer must not pull a gigabyte of JSON into memory to find out what it is.
SNIFF_BYTES = 64 * 1024


def _keys() -> Dict[str, Any]:
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


def _adapter(entry: Any) -> SceneAdapter:
    """Instantiate a plugin entry's adapter class."""
    loaded = entry.load()
    if loaded is None:
        raise UnknownSourceType(
            "the %r adapter is registered but could not be imported; see the "
            "log for why" % (entry.name,))
    adapter: SceneAdapter = loaded()
    return adapter


def known_sources() -> Tuple[str, ...]:
    """Every suffix and content type a viewer can open, sorted to be read."""
    return tuple(sorted(_keys()))


def adapter_named(name: str) -> SceneAdapter:
    """The adapter registered as ``name`` (``gltf``, ``vrml97``, ...)."""
    from OpenGLContext import plugins
    entry = plugins.Adapter.by_name(name)
    if entry is None:
        raise UnknownSourceType(
            "no viewer adapter named %r; registered: %s"
            % (name, ', '.join(sorted(e.name for e in plugins.Adapter.all()))))
    return _adapter(entry)


def _path_of(source: str) -> str:
    """The path part of ``source``, lowercased, with any query or fragment gone.

    A URL's ``?token=...`` is not part of the file's name, and a viewer that let
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


def _sniff(source: str) -> Optional[Any]:
    """Look inside a local file whose name did not settle it.

    Only JSON is sniffed, and only for 3D Tiles, because a tileset is the one
    format in regular use whose name (``anything.json``) says nothing.  Anything
    unreadable simply does not match -- sniffing must never be the thing that
    raises.
    """
    from OpenGLContext import plugins
    if not os.path.isfile(source):
        return None
    try:
        with open(source, 'rb') as handle:
            document = json.loads(handle.read(SNIFF_BYTES).decode('utf-8'))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if isinstance(document, dict) and 'asset' in document and 'root' in document:
        return plugins.Adapter.by_name('tiles3d')
    return None


def adapter_for(source: str, contentType: Optional[str] = None) -> SceneAdapter:
    """The adapter that opens ``source``.

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
