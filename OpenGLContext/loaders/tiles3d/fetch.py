"""URI reading for the 3D Tiles runtime: local files and remote http(s).

A tileset's root, its external (nested) tilesets, and its tile content may live on
disk or behind http(s) URLs (a tileset served by a static host, or a Cesium sample
on raw GitHub). These helpers resolve a relative URI against its base and read the
bytes from either source, caching remote responses under the per-user cache dir so
each tile downloads once. `read_bytes` runs on the loader's worker threads.
"""
import hashlib
import os
import urllib.parse
import urllib.request
from typing import Optional

_USER_AGENT = "OpenGLContext-tiles3d"


def is_url(uri: str) -> bool:
    """True for an http/https URI (as opposed to a local filesystem path)."""
    return bool(uri) and urllib.parse.urlparse(uri).scheme in ("http", "https")


def resolve_uri(base: str, uri: str) -> str:
    """Resolve `uri` against `base`, which may be a URL or a local directory path.

    An absolute URI (its own scheme, or an absolute path) is returned unchanged.
    """
    if not base or is_url(uri) or os.path.isabs(uri):
        return uri
    if is_url(base):
        return urllib.parse.urljoin(base, uri)
    return os.path.join(base, uri)


def dir_of(uri: str) -> str:
    """The base (directory) of a URI, with a trailing separator, for child URIs.

    A bare filename (no directory) yields "" so its children resolve as siblings.
    """
    if is_url(uri):
        return uri.rsplit("/", 1)[0] + "/"
    head = os.path.dirname(uri)
    return head + os.sep if head else ""


def default_cache_dir() -> str:
    root = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(root, "openglcontext", "tiles3d")


def read_bytes(uri: str, cache_dir: Optional[str] = None) -> bytes:
    """Return the bytes at `uri` (local path or http/https URL).

    Remote responses are cached under `cache_dir` (default: the per-user cache dir)
    keyed by the full URL, so a tile is fetched from the network only once.
    """
    if not is_url(uri):
        with open(uri, "rb") as fh:
            return fh.read()
    cache_dir = cache_dir or default_cache_dir()
    key = hashlib.sha256(uri.encode("utf-8")).hexdigest()
    cached = os.path.join(cache_dir, key)
    if os.path.exists(cached):
        with open(cached, "rb") as fh:
            return fh.read()
    request = urllib.request.Request(uri, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    os.makedirs(cache_dir, exist_ok=True)
    tmp = cached + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, cached)   # atomic: a reader never sees a half-written cache file
    return data
