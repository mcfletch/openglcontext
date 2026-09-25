"""The props a baked world carries in its tileset's ``extras``, read back.

A baker writes what stands in a world -- boulders, loose stone -- into the
tileset's ``extras`` by channel name, so a game can stand colliders up for
them without the tiles, whose geometry arrives and leaves with the level of
detail. A channel takes one of two forms:

* a list of props as JSON, one object each
  (:meth:`~OpenGLContext.scenegraph.props.Prop.to_json`), for a channel of
  hundreds;
* ``{"table": name, "count": n}``, a binary table beside the tileset
  (:func:`~OpenGLContext.scenegraph.props.props_table`), for a channel of tens
  of thousands, which as JSON would be megabytes every reader of the tileset
  parses.

The table's name is resolved within the tileset's reach
(:func:`~OpenGLContext.loaders.tiles3d.fetch.beside`).
"""
from __future__ import annotations

from typing import List, Mapping, Optional

from OpenGLContext.loaders.documentvalues import (
    JSONObject, require_object, require_text, require_whole,
)

from OpenGLContext.loaders.tiles3d import fetch
from OpenGLContext.scenegraph.props import Prop, props_from_table

__all__ = ['baked_props']


def baked_props(extras: JSONObject, channel: str, base: str,
                max_bytes: Optional[int] = fetch.DEFAULT_MAX_TILE_BYTES) -> List[Prop]:
    """The props in ``extras[channel]``, in either form; empty where absent.

    ``base`` is the tileset's directory or URL directory
    (:func:`~OpenGLContext.loaders.tiles3d.fetch.dir_of`). Raises ``IOError``
    for a table outside the tileset's reach and ``ValueError`` for one that is
    not a table or holds another number of props than ``count`` says.
    """
    record = extras.get(channel)
    if not record:
        return []
    if isinstance(record, list):
        return [Prop.from_json(require_object(one, 'a prop in %s' % (channel,)))
                for one in record]
    if not isinstance(record, Mapping) or not isinstance(record.get('table'), str):
        raise ValueError('%s is %r, which is neither a list of props nor a '
                         'table' % (channel, record))
    where = fetch.beside(base, require_text(record['table'], '%s table' % (channel,)))
    found = props_from_table(fetch.read_bytes(where, max_bytes=max_bytes))
    stated = record.get('count')
    if stated is not None and require_whole(stated, '%s count' % (channel,)) != len(found):
        raise ValueError('%s says it holds %s props and its table holds %d'
                         % (channel, stated, len(found)))
    return found
