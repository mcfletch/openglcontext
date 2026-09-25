"""What an application offers to download, read from a registry file.

The set of packs lives in a data file rather than in Python, so a pack can be
added, its size corrected or its URL moved without a code change -- and so what
a given build offers can be read off one file instead of out of a module.

    >>> from OpenGLContext.contentpacks import catalog
    >>> packs = catalog.merge(catalog.load('packs.json'))   # doctest: +SKIP

A registry is a JSON document naming its ``namespace`` and holding a list of
``packs``:

.. code-block:: json

    {"namespace": "glisteel",
     "packs": [{"key": "glisteel/ashdown", "title": "Ashdown", "...": "..."}]}

**Validation is strict on purpose.** A pack that fails to load is refused loudly
rather than skipped, and every field has to be one the schema declares. Both
rules answer the same failure: an entry with a mistyped key would otherwise be
accepted, ignored for ever, and never noticed. The one that matters most is
``copyright``, since a notices screen is generated from these entries and a pack
that cannot state its terms would be offered for download and left out of the
credits.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable, Sequence

from .pack import ContentPack

__all__ = ['ARCHIVE_KINDS', 'BadCatalog', 'MANIFEST', 'OPTIONAL',
           'PREVIEW_SUFFIXES', 'REGISTRY_LIMIT', 'REQUIRED', 'load',
           'load_bundle', 'merge', 'offered', 'pack_for_key', 'with_needed']

#: What the registry document is called, on its own or inside a bundle.
MANIFEST = 'packs.json'

#: Picture formats a chooser can be relied on to decode. A preview is a
#: thumbnail shown before anything is downloaded, so the list is short on
#: purpose: a registry is not a place to introduce a new image format.
PREVIEW_SUFFIXES = ('.png', '.jpg', '.jpeg')

#: Fields an entry must carry. Each is either shown to the user before they
#: consent to a download or needed to perform one.
REQUIRED = ('key', 'title', 'url', 'directory', 'archive',
            'approximate_bytes', 'copyright', 'marker')

#: Fields an entry may carry, and what it means to leave each one out.
OPTIONAL: dict[str, Any] = {
    'sha256': '',           # the publisher does not control the bytes
    'base': False,          # the application starts without it
    'family': None,         # which group of alternatives; None for any
    'needs': (),       # keys of packs it is incomplete without
    'requires': '',         # any version of the application reads it
    'notes': '',            # a sentence for a download or notices screen
    'url_page': '',         # where a human reads about it
    'preview': '',          # a chooser shows the pack's name and nothing else
}

#: Archive containers there is a reader for.
ARCHIVE_KINDS = ('zip', 'tar')

#: The most a registry bundle is fetched as, and the most it unpacks to. A
#: registry is a document and some thumbnails, and one arriving at the size of
#: the content it describes is not a registry; there is no size declared in
#: advance to judge it against, so the judgement is made here.
REGISTRY_LIMIT = 16 * 1024 * 1024

#: The file an unpacked bundle's directory holds its bundle's digest in.
BUNDLE_DIGEST = '.bundle-sha256'

_KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$')
_NAMESPACE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
_SEGMENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
_DIGEST = re.compile(r'^[0-9a-f]{64}$')


class BadCatalog(ValueError):
    """The registry could not be read, or an entry in it is not usable.

    Raised rather than skipping the entry: a pack silently dropped for a typo is
    a pack nobody can download and nobody can see the absence of.
    """


def load(path: str) -> list[ContentPack]:
    """Every pack the registry at ``path`` declares, in file order.

    The document's ``namespace`` is the only one its keys may sit under, so a
    registry added to a build cannot answer for a pack the build shipped.

    A ``preview`` is named relative to this file and comes back resolved against
    it, so a chooser has a picture of each pack before anything is downloaded.
    """
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            document = json.load(handle)
    except (OSError, ValueError) as error:
        raise BadCatalog('cannot read the content registry %s: %s'
                         % (path, error)) from error
    if not isinstance(document, dict):
        raise BadCatalog('%s is not a content registry' % (path,))
    namespace = document.get('namespace')
    if not isinstance(namespace, str) or not _NAMESPACE.match(namespace):
        raise BadCatalog(
            '%s names no namespace. A registry declares the namespace its keys '
            'sit under, so that what it adds cannot answer for a pack the '
            'application shipped.' % (path,))
    entries = document.get('packs')
    if not isinstance(entries, list):
        raise BadCatalog('%s has no "packs" list' % (path,))
    packs = [_pack(entry, path, namespace) for entry in entries]
    _refuse_repeats(packs, path)
    return packs


def load_bundle(path: str, into: str) -> list[ContentPack]:
    """A registry handed around as one file: its JSON and its pictures together.

    Previews are bundled with the content-pack index: a bundle is a document
    and some thumbnails, so fetching one gives a picture of every pack it
    declares before anything large is downloaded.

    Extracted through the same reader a content pack goes through, so a bundle
    from elsewhere is held to the same rule about where its entries may land,
    and under :data:`REGISTRY_LIMIT`, the cap it is fetched under. It is
    unpacked beside ``into`` and validated there, and replaces what ``into``
    held only when it loads: a bundle that does not is refused and the last
    good one stays. A bundle already unpacked in ``into`` -- the same bytes,
    by digest -- is read from there without unpacking it again.
    """
    from . import archive             # here: archive has no use for a catalogue
    from OpenGLContext import atomicfiles
    digest = archive.digest(path)
    recorded = os.path.join(into, BUNDLE_DIGEST)
    with atomicfiles.file_lock(into + '.lock'):
        if _read_text(recorded) != digest:
            with atomicfiles.staged_directory(into) as staging:
                archive.extract(path, staging, 'zip', max_bytes=REGISTRY_LIMIT)
                manifest = os.path.join(staging, MANIFEST)
                if not os.path.isfile(manifest):
                    raise BadCatalog('%s is not a registry bundle: it holds no '
                                     '%s at its top' % (path, MANIFEST))
                load(manifest)
                atomicfiles.write_text(os.path.join(staging, BUNDLE_DIGEST),
                                       digest)
    return load(os.path.join(into, MANIFEST))


def _read_text(path: str) -> str | None:
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()
    except OSError:
        return None


def merge(*groups: Sequence[ContentPack]) -> list[ContentPack]:
    """Every pack in ``groups``, in order, refusing a key declared twice.

    Also refuses a pack naming a need nothing declares: a pack fetched
    without what it is incomplete without is one that arrives and renders
    wrongly, which is what the field exists to prevent.
    """
    packs: list[ContentPack] = [pack for group in groups for pack in group]
    _refuse_repeats(packs, 'the merged registries')
    _refuse_shared_namespaces(groups)
    known = {pack.key for pack in packs}
    for pack in packs:
        for needed in pack.needs:
            if needed not in known:
                raise BadCatalog(
                    'pack %r is incomplete without %r, which no registry '
                    'declares' % (pack.key, needed))
    return packs


def pack_for_key(key: str, packs: Iterable[ContentPack]) -> ContentPack | None:
    """The pack with this key, or None."""
    for pack in packs:
        if pack.key == key:
            return pack
    return None


def offered(packs: Sequence[ContentPack]) -> list[ContentPack]:
    """Those packs a chooser puts in front of somebody, in the order given.

    A registry names two kinds of thing: content somebody chooses, and content
    that arrives because something else named it in ``needs``. The art four
    tracks share is the second kind -- it is not a thing to have on its own,
    and it unpacks under each track that needs it rather than into a place of
    its own, so offering it separately offers a download that would never read
    as arrived.
    """
    needed = {key for pack in packs for key in pack.needs}
    return [pack for pack in packs if pack.key not in needed]


def with_needed(pack: ContentPack,
                    packs: Sequence[ContentPack]) -> list[ContentPack]:
    """``pack`` and everything it is incomplete without, it first.

    What a user is asked to consent to, since fetching a map without the art it
    names leaves them looking at grey. A needed pack may name its own; a cycle
    is walked once.
    """
    wanted: list[ContentPack] = []
    seen: set[str] = set()
    pending = [pack]
    while pending:
        one = pending.pop(0)
        if one.key in seen:
            continue
        seen.add(one.key)
        wanted.append(one)
        for key in one.needs:
            needed = pack_for_key(key, packs)
            if needed is not None:
                pending.append(needed)
    return wanted


def _refuse_shared_namespaces(groups: Sequence[Sequence[ContentPack]]) -> None:
    """One namespace comes from one registry.

    Nothing proves who owns a namespace -- there is no registrar, and a registry
    states its own. What is enforceable is that everything under one namespace
    came from one file, which matters because content is partitioned by
    namespace on disk: two registries claiming a namespace would be two
    publishers writing into one tree. Refusing it makes trusting a second an
    explicit decision rather than something that happens quietly.
    """
    seen: dict[str, int] = {}
    for index, group in enumerate(groups):
        for namespace in {pack.namespace for pack in group}:
            first = seen.setdefault(namespace, index)
            if first != index:
                raise BadCatalog(
                    'two registries both declare the namespace %r, and content '
                    'under a namespace comes from one registry' % (namespace,))


def _refuse_repeats(packs: Sequence[ContentPack], where: str) -> None:
    seen: set[str] = set()
    for pack in packs:
        if pack.key in seen:
            raise BadCatalog('%s declares %r twice; a key names one pack'
                             % (where, pack.key))
        seen.add(pack.key)


def _pack(entry: Any, path: str, namespace: str) -> ContentPack:
    """One registry entry as a :class:`ContentPack`, or a clear complaint."""
    if not isinstance(entry, dict):
        raise BadCatalog('%s holds an entry that is not an object' % (path,))
    named = entry.get('key', '?')
    unknown = sorted(set(entry) - (set(REQUIRED) | set(OPTIONAL)))
    if unknown:
        raise BadCatalog('%s: pack %r declares %s, which no field is called'
                         % (path, named, ', '.join(unknown)))
    missing = [name for name in REQUIRED if name not in entry]
    if missing:
        raise BadCatalog('%s: pack %r is missing %s'
                         % (path, named, ', '.join(missing)))

    values: dict[str, Any] = {name: entry[name] for name in REQUIRED}
    for name, default in OPTIONAL.items():
        values[name] = entry.get(name, default)

    _check_key(values['key'], path, namespace)
    _check_where_it_lands(values, path)
    _check_what_the_user_is_told(values, path)
    _check_the_digest(values, path)

    values['preview'] = _resolve_preview(values, path)
    values['approximate_bytes'] = int(values['approximate_bytes'])
    values['needs'] = tuple(values['needs'] or ())
    values['base'] = bool(values['base'])
    values['sha256'] = str(values['sha256']).lower()
    return ContentPack(**values)


def _resolve_preview(values: dict[str, Any], path: str) -> str:
    """The pack's picture as a path on this machine, or ''.

    Named relative to the registry, so a registry and its pictures are one thing
    to move, copy or hand around. A name that resolved outside the registry's
    own directory is refused -- a registry may show a picture it carries and not
    an arbitrary file on the reader's disk.

    A picture that is *named and not there* gives a pack with no picture rather
    than a registry that will not load: a chooser missing a plate still lets
    somebody choose, and one that refuses to open does not.
    """
    named = values['preview']
    if not named:
        return ''
    if not isinstance(named, str):
        raise BadCatalog('%s: pack %r has %r as its preview'
                         % (path, values['key'], named))
    if not named.lower().endswith(PREVIEW_SUFFIXES):
        raise BadCatalog(
            '%s: pack %r has %r as its preview, and a chooser shows %s'
            % (path, values['key'], named, ' or '.join(PREVIEW_SUFFIXES)))
    root = os.path.abspath(os.path.dirname(path))
    where = os.path.abspath(os.path.join(root, named))
    if os.path.isabs(named) or not where.startswith(root + os.sep):
        raise BadCatalog(
            '%s: pack %r names %r as its preview, which is outside the '
            'registry' % (path, values['key'], named))
    return where if os.path.isfile(where) else ''


def _check_key(key: Any, path: str, namespace: str) -> None:
    if not isinstance(key, str) or not _KEY.match(key):
        raise BadCatalog(
            '%s: %r is not a pack key. A key is <namespace>/<name>.'
            % (path, key))
    if key.split('/', 1)[0] != namespace:
        raise BadCatalog(
            '%s: pack %r is outside this registry\'s namespace %r. A registry '
            'declares only its own packs, so that one added to a build cannot '
            'answer for a pack the build shipped.' % (path, key, namespace))


def _check_where_it_lands(values: dict[str, Any], path: str) -> None:
    """The two fields that decide what is fetched and where it is written."""
    url = values['url']
    if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        raise BadCatalog(
            '%s: pack %r names %r. A registry says what to fetch, so a URL is '
            'http or https.' % (path, values['key'], url))
    directory = values['directory']
    if not isinstance(directory, str) or not _SEGMENT.match(directory):
        raise BadCatalog(
            '%s: pack %r unpacks into %r. That is joined against the store, so '
            'it is one path segment and not a path.'
            % (path, values['key'], directory))
    if values['archive'] not in ARCHIVE_KINDS:
        raise BadCatalog(
            '%s: pack %r is a %r archive, and there is a reader for %s'
            % (path, values['key'], values['archive'],
               ' and '.join(ARCHIVE_KINDS)))
    marker = values['marker']
    if not isinstance(marker, str) or os.path.isabs(marker) or '..' in marker:
        raise BadCatalog('%s: pack %r has %r as its marker, which is not a '
                         'path inside it' % (path, values['key'], marker))


def _check_what_the_user_is_told(values: dict[str, Any], path: str) -> None:
    """The two fields a user reads before consenting to a download."""
    if not str(values['copyright']).strip():
        raise BadCatalog(
            '%s: pack %r states no copyright. A notices screen is generated '
            'from that field, so a pack without one would be offered for '
            'download and never credited.' % (path, values['key']))
    try:
        size = int(values['approximate_bytes'])
    except (TypeError, ValueError) as error:
        raise BadCatalog('%s: pack %r has %r as its size'
                         % (path, values['key'],
                            values['approximate_bytes'])) from error
    if size <= 0:
        raise BadCatalog('%s: pack %r states no size, and the user is asked to '
                         'consent to one' % (path, values['key']))


def _check_the_digest(values: dict[str, Any], path: str) -> None:
    """``sha256``, and the two things a ``base`` pack additionally owes."""
    digest = str(values['sha256'] or '')
    if digest and not _DIGEST.match(digest.lower()):
        raise BadCatalog('%s: pack %r has %r as its sha256, which is not 64 '
                         'hex digits' % (path, values['key'], digest))
    if not values['base']:
        return
    if not digest:
        raise BadCatalog(
            '%s: pack %r is a base pack and carries no sha256. A base pack is '
            'the application\'s own, so its bytes are known and are checked.'
            % (path, values['key']))
    if values['family']:
        raise BadCatalog(
            '%s: pack %r is a base pack in family %r. A family is a choice '
            'among alternatives, and what the application cannot start without '
            'is not a choice.' % (path, values['key'], values['family']))
