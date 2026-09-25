"""URI reading for the 3D Tiles runtime: local files and remote http(s).

A tileset's root, its external (nested) tilesets, and its tile content may live on
disk or behind http(s) URLs (a tileset served by a static host, or a Cesium sample
on raw GitHub). These helpers resolve a relative URI against its base and read the
bytes from either source, caching remote responses under the per-user cache dir so
each tile downloads once. `read_bytes` runs on the loader's worker threads.

**A URI named inside a tileset is untrusted.** A `tileset.json` from anywhere but
this machine chooses its own tile and sub-tileset URIs, so those go through the
same containment as a glTF document's external references
(:mod:`OpenGLContext.loaders.resolver`, which is where the policy lives):

* a tileset fetched over http(s) may pull only **same-origin** http(s) references,
  re-checked on every redirect hop, which is what keeps a tile URI from naming a
  link-local metadata endpoint or an absolute local path;
* a tileset loaded from a local path may read only files **under its own
  directory**; and
* every payload is **size-capped** (:data:`DEFAULT_MAX_TILE_BYTES`).

The root tileset is the exception: that URI came from the command line or
from application code, not from a document, so :func:`resolve_uri` with no base
checks only that it is a local path or an http(s) URL
(:func:`~OpenGLContext.loaders.resolver.checked_source`).

What these answer is a checked location
(:data:`~OpenGLContext.loaders.resolver.Located`): a
:class:`~OpenGLContext.loaders.resolver.ContainedPath` or a
:class:`~OpenGLContext.loaders.resolver.CheckedURL`, and :func:`local_copy` and
:func:`read_bytes` take nothing else.
"""
import os
import urllib.parse
from typing import Optional

from OpenGLContext import userpaths
from OpenGLContext.loaders import resolver
from OpenGLContext.loaders.resolver import CheckedURL, ContainedPath, Located

#: Ceiling on a single tile payload or sub-tileset. Generous enough for a dense
#: b3dm/glb tile, small enough that one hostile tile cannot exhaust memory;
#: override per call where a dataset genuinely ships larger tiles.
DEFAULT_MAX_TILE_BYTES = 256 * 1024 * 1024   # 256 MiB


def is_url(uri: str) -> bool:
    """True for an http/https URI (as opposed to a local filesystem path)."""
    return bool(uri) and urllib.parse.urlparse(uri).scheme in ("http", "https")


def resolve_uri(base: str, uri: str) -> Located:
    """Resolve `uri` against `base`, enforcing the untrusted-asset policy.

    `base` is the tileset the reference was found in -- a URL or a local
    directory -- and confines what the reference may reach: same-origin http(s)
    for a URL, the directory subtree for a local path. Performs no network or
    disk access, so a refused reference never touches the resource.

    An empty `base` means the caller named this URI itself rather than reading it
    out of a document; it is checked as a caller's source is.

    Raises:
        IOError: where the reference is outside what `base` permits.
    """
    if not base:
        return resolver.checked_source(uri)
    if is_url(base):
        return resolver.Resolver(base_url=base).resolve(uri)
    return resolver.Resolver(base_dir=base).resolve(uri)


def beside(base: str, name: str) -> Located:
    """Where a file named in a tileset's extras is, within what the tileset may reach.

    `base` is the tileset's directory or URL directory (:func:`dir_of`), and
    `name` a file a world names beside its tiles: a zones document, a tree's
    mesh, a cover species' clump or card. The containment is
    :func:`resolve_uri`'s: under `base` for a local world, same-origin http(s)
    for a served one. Unlike :func:`resolve_uri`, an empty `base` is an error,
    since every such name comes out of a document.

    Raises:
        ValueError: where `base` is empty.
        IOError: where `name` is outside what `base` permits.
    """
    if not base:
        raise ValueError(
            "%r is named by a tileset, and has no tileset to be resolved "
            "against" % (name,))
    return resolve_uri(base, name)


def local_copy(uri: Located, cache_dir: Optional[str] = None,
               max_bytes: Optional[int] = DEFAULT_MAX_TILE_BYTES) -> ContainedPath:
    """A path on this machine holding the file at `uri`.

    A local path is returned as it is. An http(s) URL is fetched into the
    per-user cache (once, size-capped, its redirects held to its origin) and
    the cached file's path is returned, for readers that open only paths:
    ``numpy.load``, ``PIL.Image.open``, a ``.glb`` clump.

    `uri` has been through :func:`beside` or :func:`resolve_uri`.
    """
    if isinstance(uri, ContainedPath):
        return uri
    return resolver.fetch_to_cache(uri, cache_dir or default_cache_dir(),
                                   max_bytes=max_bytes)


def dir_of(uri: str) -> str:
    """The base (directory) of a URI, with a trailing separator, for child URIs.

    A bare filename (no directory) yields "" so its children resolve as siblings.
    """
    if is_url(uri):
        return uri.rsplit("/", 1)[0] + "/"
    head = os.path.dirname(uri)
    return head + os.sep if head else ""


def default_cache_dir() -> str:
    """Where fetched tiles are cached: ``openglcontext/tiles3d`` in the user's cache."""
    return os.path.join(userpaths.cachedirectory(), "openglcontext", "tiles3d")


def read_bytes(uri: Located, cache_dir: Optional[str] = None,
               max_bytes: Optional[int] = DEFAULT_MAX_TILE_BYTES) -> bytes:
    """Return the bytes at `uri` (local path or http/https URL), size-capped.

    A remote payload goes through the resolver's on-disk cache, which keys by URL,
    coalesces concurrent fetches of the same tile, locks the redirect chain to the
    tile's own origin and writes the entry atomically -- so a tile is fetched once
    however many worker threads want it, and a reader never sees a partial file.

    `uri` has been through :func:`resolve_uri`, which is what decided the
    reference was one this tileset may reach. A local file's size is checked
    on disk before it is read.

    Raises:
        ValueError: where the payload exceeds `max_bytes`.
    """
    if isinstance(uri, CheckedURL):
        return resolver.fetch_url(uri, cache_dir or default_cache_dir(),
                                   max_bytes=max_bytes)
    return resolver.read_contained(uri, max_bytes)
