"""Where a model comes from, and getting it.

A viewer opens a filesystem path, an http(s) URL, or a member of an archive
named with a fragment::

    oglc-view model.glb
    oglc-view https://example.com/model.glb
    oglc-view world.tar.gz#gallery.glb
    oglc-view https://example.com/world.tar.gz#gallery.glb

The difference matters further than the fetch: a multi-file ``.gltf`` names its
``.bin`` and its images by URI *relative to the document*, so whatever fetches
it has to keep hold of where it came from -- which is also why an archive is
unpacked whole rather than one member at a time.
"""
import hashlib
import os
from typing import TYPE_CHECKING, Optional

from OpenGLContext import atomicfiles, userpaths
from OpenGLContext.contentpacks import ContentPack, ContentStore
from OpenGLContext.contentpacks import archive, catalog, fetch
from OpenGLContext.loaders import resolver
from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.resolver import is_url
from OpenGLContext.viewer.commentary import say

if TYPE_CHECKING:
    from OpenGLContext.loaders.gltf.scene import GLTFScene

__all__ = ['ARCHIVE_SUFFIXES', 'ENGINE_REGISTRY', 'SCENE_SUFFIXES',
           'UnknownMember', 'is_archive', 'is_url', 'load_gltf_source',
           'open_archive', 'open_pack', 'pack_named', 'resolve_source',
           'split_member']

#: What is taken to be an archive, and which extractor reads it.
ARCHIVE_SUFFIXES = {
    '.zip': 'zip',
    '.tar': 'tar', '.tar.gz': 'tar', '.tgz': 'tar',
    '.tar.bz2': 'tar', '.tbz2': 'tar', '.tar.xz': 'tar', '.txz': 'tar',
}

#: What counts as a scene to open, when an archive is not told which member.
SCENE_SUFFIXES = ('.glb', '.gltf', '.wrl', '.wrz', '.vrml', '.x3d', '.obj')

#: Ceiling on an archive fetched from a URL. A world is tens of megabytes; this
#: is the same order as a content pack and far below what would exhaust memory.
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024


#: The content packs the engine itself publishes: the demo worlds.
ENGINE_REGISTRY = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'packs.json')

#: The application name the engine's own packs are stored under.
ENGINE_STORE = 'openglcontext'


class UnknownMember(ValueError):
    """The archive does not say, or does not hold, which scene to open."""


def split_member(source: str) -> tuple[str, Optional[str]]:
    """``('world.tar.gz', 'gallery.glb')`` for ``'world.tar.gz#gallery.glb'``.

    Only the last ``#`` counts, and only where something follows it. A Windows
    path has no fragment to find, and a bare ``#`` is not naming a member.
    """
    head, marker, member = source.rpartition('#')
    if not marker or not member:
        return source, None
    return head, member


def is_archive(source: str) -> bool:
    """Whether ``source`` names an archive rather than a scene."""
    return _extractor(split_member(source)[0]) is not None


def _extractor(path: str) -> Optional[str]:
    lowered = path.lower().split('?')[0].split('#')[0].rstrip('/')
    for suffix, kind in ARCHIVE_SUFFIXES.items():
        if lowered.endswith(suffix):
            return kind
    return None


def archive_cache_dir() -> str:
    """Where archives are unpacked: per user, not in shared temp.

    The same reasoning as every other download this engine keeps -- no other
    account can pre-seed a world this user then opens. Each archive is kept
    under its own digest until somebody removes it; deleting the directory at
    any time costs only the next opening's extraction.
    """
    where = os.path.join(userpaths.appdatadirectory(), 'OpenGLContext',
                         'archives')
    os.makedirs(where, mode=0o700, exist_ok=True)
    return where


def open_archive(source: str, cache_dir: Optional[str] = None,
                 max_bytes: int = MAX_ARCHIVE_BYTES) -> str:
    """Unpack the archive ``source`` names and return the member to open.

    ``source`` is a path or a URL, optionally with ``#member`` naming what to
    open inside. Without one, an archive holding exactly one scene file opens
    that; anything else is a choice only the caller can make, and it is asked
    for by name.

    The whole archive is unpacked, not the one member: a ``.gltf`` names its
    buffers and its images relative to itself, and a level-of-detail chain names
    its sidecars the same way. It is unpacked once and kept, so opening the same
    world twice costs one extraction.

    An archive is somebody else's file, so it goes through the extraction the
    content packs use: bounded, and refusing a member that is absolute or climbs
    out of the directory.
    """
    path, member = split_member(source)
    kind = _extractor(path)
    if kind is None:
        raise UnknownMember('%s is not an archive this viewer reads' % (path,))
    where = _unpack(path, kind, cache_dir, max_bytes)
    return _member_in(where, member, path)


#: The file an unpacked archive's directory holds once the extraction is whole.
UNPACKED = '.unpacked'


def _unpack(path: str, kind: str, into: Optional[str],
            max_bytes: int) -> str:
    """The directory ``path`` is unpacked into, unpacking it if it is not.

    Unpacked beside that directory and renamed into place when whole, under a
    lock so two viewers opening one archive take turns, so an extraction that
    stopped part way is never opened as the world. A directory without the
    completion file is unpacked again.
    """
    # An archive the user named follows redirects to any public host, as a
    # content pack does: release hosts serve every asset through a CDN.
    local = (resolver.fetch_to_cache(resolver.checked_url(path), max_bytes=max_bytes,
                                     redirects=resolver.PUBLIC_HOSTS)
             if is_url(path) else path)
    root = into if into is not None else archive_cache_dir()
    # Named for what it holds rather than for where it came from, so the same
    # archive fetched twice is one directory and a changed archive is another.
    where = os.path.join(root, _digest(local))
    with atomicfiles.file_lock(where + '.lock'):
        if not os.path.exists(os.path.join(where, UNPACKED)):
            with atomicfiles.staged_directory(where) as staging:
                archive.extract(local, staging, kind, max_bytes=max_bytes)
                atomicfiles.write_text(os.path.join(staging, UNPACKED), '')
    return where


def _digest(path: str) -> str:
    found = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            found.update(block)
    return found.hexdigest()[:24]


def _member_in(where: str, member: Optional[str], named: str) -> str:
    """The file to open under ``where``: the one asked for, or the only one."""
    if member is not None:
        # Through the resolver, so a member naming its way out of the unpacked
        # directory is refused here as it would be in a document.
        found: str = resolver.Resolver(base_dir=where).resolve(member)
        if not os.path.exists(found):
            raise UnknownMember(
                '%s holds no %r. It holds: %s'
                % (named, member, _listing(where)))
        return found
    scenes = _scenes(where)
    if len(scenes) == 1:
        return scenes[0]
    if not scenes:
        raise UnknownMember(
            '%s holds nothing this viewer opens. It holds: %s'
            % (named, _listing(where)))
    raise UnknownMember(
        '%s holds more than one scene; name one with #, as in "%s#%s". It '
        'holds: %s'
        % (named, named, os.path.relpath(scenes[0], where), _listing(where)))


def _scenes(where: str) -> list[str]:
    """Every file under ``where`` this viewer would open, shallowest first."""
    found: list[str] = []
    for root, _directories, files in os.walk(where):
        for leaf in files:
            if leaf.lower().endswith(SCENE_SUFFIXES):
                found.append(os.path.join(root, leaf))
    return sorted(found, key=lambda path: (path.count(os.sep), path))


def _listing(where: str, most: int = 12) -> str:
    names = sorted(os.path.relpath(os.path.join(root, leaf), where)
                   for root, _directories, files in os.walk(where)
                   for leaf in files if leaf != UNPACKED or root != where)
    shown = ', '.join(names[:most])
    return shown + (', ...' if len(names) > most else '') if names else '(nothing)'


def pack_named(key: str, registry: str = ENGINE_REGISTRY) -> ContentPack:
    """The pack ``key`` in ``registry``; :class:`UnknownMember` if none."""
    packs = catalog.merge(catalog.load(registry))
    found = catalog.pack_for_key(key, packs)
    if found is None:
        raise UnknownMember('there is no content pack %r; there are: %s'
                            % (key, ', '.join(pack.key for pack in packs)))
    return found


def open_pack(key: str, registry: str = ENGINE_REGISTRY,
              store: Optional[ContentStore] = None) -> str:
    """The scene a content pack holds, fetching the pack if it is not here.

    ``key`` names a pack in ``registry`` -- the engine's own demo worlds by
    default -- and the pack is found in, or fetched into, ``store`` (the
    engine's own store by default) through
    :func:`~OpenGLContext.contentpacks.fetch.fetch_pack`: its digest checked,
    its unpacking bounded, and a second run finding it without a download.
    Naming the key is the consent; what is fetched, how large it is and whose
    it is are printed before the download. The pack's marker is the scene.
    """
    pack = pack_named(key, registry)
    where = store if store is not None else ContentStore(ENGINE_STORE)
    root = where.root_for(pack)
    if root is None:
        say('Fetching %s (%s) -- %s\n' % (pack.title, pack.human_size(),
                                          pack.copyright))
        root = fetch.fetch_pack(pack, where)
    return os.path.join(root, pack.marker)


def resolve_source(source: Optional[str],
                   cache_dir: Optional[str] = None) -> Optional[str]:
    """``source`` if it names something openable, else None.

    A local path must exist, so a typo is answered before a window opens rather
    than as an empty scene.  A URL is returned unchanged for
    :func:`load_gltf_source` to fetch, since whether it resolves is not knowable
    without asking.  An archive is unpacked and the member inside it returned,
    because everything downstream wants a file it can open.

    Answering rather than exiting, because what to do about a source that is not
    there depends on who asked: a viewer starting up has nothing else to do and
    exits, while one already showing a scene keeps showing it and says so. A
    local archive that is not there is None as well.

    An archive that *is* there but does not say which scene to open -- it holds
    several, or none, or not the member named -- raises :class:`UnknownMember`,
    whose message lists what the archive holds, since that listing is what the
    person needs to name one.
    """
    if source is None:
        return None
    if is_archive(source):
        if not is_url(source) and not os.path.exists(split_member(source)[0]):
            return None
        return open_archive(source, cache_dir=cache_dir)
    if is_url(source):
        return source
    return source if os.path.exists(source) else None


def load_gltf_source(source: str) -> "GLTFScene":
    """Load a :class:`GLTFScene` from a path or an http(s) URL.

    A URL goes through the security-hardened resolver -- same-origin,
    size-capped, disk-cached -- keeping the document URL to resolve a multi-file
    ``.gltf``'s external ``.bin`` and image references against.  Fetching the
    document by itself cannot: the base URL is gone by then and those relative
    references have nowhere to resolve from.  A self-contained ``.glb`` loads
    either way.

    A **Khronos sample** URL falls back through the other variants it may have
    been published as.  Not every sample ships a ``.glb`` -- Sponza, SciFiHelmet
    and Suzanne publish only ``glTF/`` -- so naming the binary one, which is the
    one to prefer, answered 404 for those and they could not be opened at all.
    """
    if is_url(source):
        return gltf.load_sample_url(source)
    return gltf.load_gltf(source)
