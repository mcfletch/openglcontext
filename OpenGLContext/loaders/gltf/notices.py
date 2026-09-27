"""The copyright and licence notices in a glTF document.

Three places in a glTF say who made it and on what terms:

``asset.copyright``
    The core specification's statement about the whole file.
``asset.extras``
    ``title``, ``author``, ``license`` and ``source``, as Sketchfab and other
    exporters write them.
``KHR_xmp_json_ld``
    XMP metadata as JSON-LD packets, held in the document's packet table and
    attached by index to the asset, or to a scene, node, mesh, material, image
    or animation -- which is how one part of a file states terms the rest does
    not share.

:func:`document_notices` reads all three into
:class:`~OpenGLContext.loaders.notices.Notice` records: first the whole file's,
then one per packet attached to parts, naming the parts it covers.
"""
import logging
import re
from typing import Any, Optional

from OpenGLContext.loaders.notices import Notice

__all__ = ['document_notices', 'xmp_text']

log = logging.getLogger(__name__)

XMP = 'KHR_xmp_json_ld'

#: The kinds of glTF object a packet may be attached to, and what each is
#: called when it has no name of its own.
_ATTACHABLE = (('scenes', 'scene'), ('nodes', 'node'), ('meshes', 'mesh'),
               ('materials', 'material'), ('images', 'image'),
               ('animations', 'animation'))

#: How many parts a notice names before it gives the count of the rest.
MAX_NAMED = 8

#: Which XMP properties fill which field of a notice, first present first.
_FROM_XMP = {
    'title': ('dc:title',),
    'creator': ('dc:creator',),
    'licence': ('dc:rights', 'xmpRights:UsageTerms', 'cc:license',
                'xmpRights:WebStatement'),
    'source': ('dc:source',),
}

#: Which exporter extras fill which field of the whole file's notice.
_FROM_EXTRAS = {'title': 'title', 'creator': 'author', 'licence': 'license',
                'source': 'source'}

_ITEM = re.compile(r'^rdf:_(\d+)$')


def xmp_text(value: Any) -> str:
    """An XMP property's value as plain text; empty when it holds none.

    A value is a string, a typed literal (``@value``), an ordered or unordered
    list (``@list``, ``@set``, a JSON array) or an RDF container whose items
    are ``rdf:_1``, ``rdf:_2`` and so on.  Lists and bags are joined with
    commas; a language alternative (``rdf:Alt``) is its first entry, which XMP
    reserves for the default language.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return ', '.join(text for text in map(xmp_text, value) if text)
    if not isinstance(value, dict):
        return ''
    if '@value' in value:
        return xmp_text(value['@value'])
    for key in ('@list', '@set'):
        if key in value:
            return xmp_text(value[key])
    items = sorted((int(match.group(1)), item) for key, item in value.items()
                   for match in [_ITEM.match(key)] if match)
    texts = [text for text in (xmp_text(item) for _, item in items) if text]
    if value.get('@type') == 'rdf:Alt':
        return texts[0] if texts else ''
    return ', '.join(texts)


def _from_packet(packet: Any) -> dict[str, str]:
    """The notice fields ``packet`` states."""
    if not isinstance(packet, dict):
        return {}
    found = {}
    for field, keys in _FROM_XMP.items():
        for key in keys:
            text = xmp_text(packet.get(key))
            if text:
                found[field] = text
                break
    return found


def _from_extras(extras: Any) -> dict[str, str]:
    """The notice fields an exporter's asset extras state."""
    if not isinstance(extras, dict):
        return {}
    return {field: extras[key].strip() for field, key in _FROM_EXTRAS.items()
            if isinstance(extras.get(key), str) and extras[key].strip()}


def _packet_index(owner: Any, packets: list, what: str) -> Optional[int]:
    """The packet ``owner`` is attached to, or None.

    An index that is not in the table is reported and treated as absent: the
    rest of the file's notices are still worth showing.
    """
    extensions = getattr(owner, 'extensions', None)
    block = extensions.get(XMP) if isinstance(extensions, dict) else None
    if not isinstance(block, dict) or 'packet' not in block:
        return None
    index = block['packet']
    if isinstance(index, int) and not isinstance(index, bool) \
            and 0 <= index < len(packets):
        return index
    log.warning('%s: %s packet %r is not in the table of %d packets',
                what, XMP, index, len(packets))
    return None


def _covering(names: list[str]) -> str:
    """``names`` as one line, the tail of a long list given as a count."""
    if len(names) <= MAX_NAMED:
        return ', '.join(names)
    return '%s and %d more' % (', '.join(names[:MAX_NAMED]),
                               len(names) - MAX_NAMED)


def document_notices(g: Any) -> list[Notice]:
    """Every notice in the pygltflib document ``g``, the whole file's first.

    The whole file's notice combines ``asset.copyright``, the asset's extras
    and a packet attached to the asset; where a packet and the extras both
    give a field, the packet's is used.  Each packet attached to parts is one
    notice covering every part it is attached to, in document order.
    """
    top = getattr(g, 'extensions', None)
    table = top.get(XMP) if isinstance(top, dict) else None
    packets = table.get('packets') if isinstance(table, dict) else None
    packets = packets if isinstance(packets, list) else []

    asset = getattr(g, 'asset', None)
    whole = _from_extras(getattr(asset, 'extras', None))
    index = _packet_index(asset, packets, 'asset')
    if index is not None:
        whole.update(_from_packet(packets[index]))
    copyright = getattr(asset, 'copyright', None)
    if isinstance(copyright, str) and copyright.strip():
        whole['copyright'] = copyright.strip()

    covered: dict[int, list[str]] = {}
    for attribute, kind in _ATTACHABLE:
        for position, owner in enumerate(getattr(g, attribute, None) or []):
            name = getattr(owner, 'name', None) or '%s %d' % (kind, position)
            index = _packet_index(owner, packets, name)
            if index is not None and name not in covered.setdefault(index, []):
                covered[index].append(name)

    notices = [Notice(**whole)]
    notices.extend(Notice(covers=_covering(names), **_from_packet(packets[index]))
                   for index, names in covered.items())
    return [notice for notice in notices if notice]
