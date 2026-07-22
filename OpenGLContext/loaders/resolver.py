"""Secure resolution and fetching of untrusted external assets for loaders.

Shared by OpenGLContext's asset loaders: any loader that follows external
references (glTF buffers/images, and other formats' sub-resources) constructs a
:class:`Resolver` with the document's base URL or directory and asks it to
resolve each referenced URI. Those references are attacker-controlled for any
document from an untrusted source, so this is the containment core, kept in one
auditable place. It enforces:

* a document fetched over HTTP(S) may only pull same-origin http(s) URIs
  (blocks ``file://`` reads and ``169.254.169.254`` metadata SSRF), re-checked on
  every redirect hop;
* a document loaded from a local path may only read files under its own directory
  (blocks ``../../etc/passwd`` traversal and absolute paths);
* every fetched or decoded resource is size-capped; and
* the disk cache lives under the per-user app-data directory, not world-writable
  system temp.

:func:`safe_url`, :func:`_fetch_url` and :func:`_decode_data_uri` are the
fetch/decode primitives; :class:`Resolver` ties them to one document's origin.
"""

import base64
import os
import threading
import urllib.parse
import urllib.request
import urllib.error


def safe_url(url):
    """Percent-encode the path of a URL so non-ASCII names (e.g. Unicode model
    directories) can be fetched; existing %-escapes and '/' are preserved."""
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%")
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, path, parts.query, parts.fragment))


# --- untrusted-asset guards --------------------------------------------------
# A document may reference external resources by URI. Those references are
# attacker-controlled for any document from an untrusted source, so:
#   * a document fetched over HTTP(S) may only pull same-origin http(s) URIs
#     (blocks file:// reads and http://169.254.169.254 metadata SSRF), and
#   * a document loaded from a local path may only read files under its own
#     directory (blocks ../../etc/passwd traversal and absolute paths).
# Each fetched/decoded resource is also size-capped to bound memory use.

# Ceiling on a single fetched/decoded external resource; override per-load via the
# ``max_resource_bytes`` argument on the load entry points.
DEFAULT_MAX_RESOURCE_BYTES = 256 * 1024 * 1024   # 256 MiB
_ALLOWED_URL_SCHEMES = ('http', 'https')


def _origin(url):
    """(scheme, netloc) security origin of a URL.

    ``netloc`` keeps host, port and any userinfo verbatim, so two virtual hosts on
    one IP -- or one host on two ports -- are distinct origins, as intended.
    """
    parts = urllib.parse.urlsplit(url)
    return (parts.scheme.lower(), parts.netloc.lower())


def _same_origin(a, b):
    return _origin(a) == _origin(b)


class _OriginLockedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-apply the same-origin policy on every redirect hop.

    ``urllib.request.urlopen`` follows 3xx redirects without re-validating the
    destination, so a same-origin URL that 302s to a link-local address (e.g.
    ``169.254.169.254``) would otherwise defeat the pre-request origin check.
    Each redirect target must keep an allowed scheme and the original origin, or
    the request is refused.
    """

    def __init__(self, base_url):
        self._base_url = base_url

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if (_origin(newurl)[0] not in _ALLOWED_URL_SCHEMES
                or not _same_origin(self._base_url, newurl)):
            raise urllib.error.HTTPError(
                newurl, code,
                "fetch refused cross-origin redirect to %r" % (newurl,),
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _urlopen_same_origin(url, base_url, timeout=30):
    """Open ``url`` refusing any redirect that leaves ``base_url``'s origin."""
    opener = urllib.request.build_opener(_OriginLockedRedirectHandler(base_url))
    return opener.open(safe_url(url), timeout=timeout)


def _resolve_local(base_dir, uri):
    """Resolve a relative ``uri`` under ``base_dir``, refusing to escape it.

    A ``uri`` like ``../../../etc/passwd``, an absolute path, or one carrying a URL
    scheme would otherwise let a local document read arbitrary files.
    The realpath of the result must stay within the realpath of ``base_dir``.
    """
    parsed = urllib.parse.urlsplit(uri)
    if parsed.scheme or parsed.netloc:
        raise IOError("local load may only reference local files, not %r" % uri)
    rel = urllib.parse.unquote(parsed.path)
    if os.path.isabs(rel):
        raise IOError("uri must be a relative path, not %r" % uri)
    base_real = os.path.realpath(base_dir)
    full = os.path.realpath(os.path.join(base_real, rel))
    if full != base_real and not full.startswith(base_real + os.sep):
        raise IOError("uri %r escapes the base directory" % uri)
    return full


def _check_size(nbytes, max_bytes, what):
    if max_bytes is not None and nbytes > max_bytes:
        raise ValueError(
            "resource %s is %d bytes, over the %d-byte limit"
            % (what, nbytes, max_bytes))


def _read_capped(response, max_bytes):
    """Read a URL response, rejecting a body larger than ``max_bytes``."""
    if max_bytes is None:
        return response.read()
    data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("remote resource exceeds the %d-byte limit" % max_bytes)
    return data


def _decode_data_uri(uri, max_bytes=None):
    """Decode a ``data:`` URI to bytes.

    Handles ``data:[<mediatype>][;base64],<payload>`` -- base64 or percent-encoded
    -- and raises a clear error on a malformed URI rather than an opaque
    ``IndexError``.
    """
    if ',' not in uri:
        raise ValueError("malformed data: URI (no comma): %r" % uri[:64])
    header, _, payload = uri.partition(',')
    if ';base64' in header.lower():
        data = base64.b64decode(payload)
    else:
        data = urllib.parse.unquote_to_bytes(payload)
    _check_size(len(data), max_bytes, 'data: URI')
    return data


def _resolver_max(resolver):
    return getattr(resolver, 'max_resource_bytes', None) if resolver is not None else None


class Resolver:
    """Resolves a document's external asset URIs against its base URL or directory.

    Enforces the untrusted-asset policy: a URL-loaded document may
    only pull same-origin http(s) references; a file-loaded document may only read
    files under its own directory. Each resource is size-capped.
    """

    def __init__(self, base_url=None, base_dir=None,
                 max_resource_bytes=DEFAULT_MAX_RESOURCE_BYTES):
        self.base_url = base_url
        self.base_dir = base_dir
        self.max_resource_bytes = max_resource_bytes
        self._cache = {}
        self._buffers = {}   # decoded buffer bytes, keyed by buffer index
        self._resolved = {}  # resolved absolute location, keyed by raw uri
        self._draco_warned = False   # the "install DracoPy" warning fired once

    def resolve(self, uri):
        """Return the absolute location ``uri`` resolves to under the policy.

        For a URL-based document this is the same-origin absolute http(s) URL; for
        a file-based document it is the absolute filesystem path, confined to the
        base directory. Enforces the untrusted-asset policy but performs no network
        or disk access, so a rejected reference never reaches the resource. Raises
        ``IOError`` when the reference is out of bounds or no base was given.

        The result is memoised per raw ``uri``: a caller that resolves then fetches
        the same reference (:meth:`fetch` resolves internally) does the policy work
        once rather than twice.
        """
        if uri in self._resolved:
            return self._resolved[uri]
        target = self._resolve(uri)
        self._resolved[uri] = target
        return target

    def _resolve(self, uri):
        if self.base_url is not None:
            full = urllib.parse.urljoin(self.base_url, uri)
            # Same-origin http(s) only: an external ref must share the exact origin
            # (scheme + host + port) the document loaded from. Blocks file://,
            # cross-host fetches and link-local metadata SSRF.
            if _origin(full)[0] not in _ALLOWED_URL_SCHEMES or \
                    not _same_origin(self.base_url, full):
                raise IOError(
                    "external reference %r is not same-origin as %r"
                    % (full, self.base_url))
            return full
        if self.base_dir is not None:
            return _resolve_local(self.base_dir, uri)
        raise IOError("Cannot resolve external resource %r" % uri)

    def fetch(self, uri):
        """Return the bytes of an external reference, enforcing the policy.

        Resolves ``uri`` against the document's base URL (same-origin http(s)
        only) or base directory (confined to it), size-caps the result, and
        memoises it. Raises ``IOError`` when the reference is out of bounds or no
        base was given, and ``ValueError`` when it exceeds the size cap.
        """
        if uri in self._cache:
            return self._cache[uri]
        target = self.resolve(uri)
        if self.base_url is not None:
            resp = _urlopen_same_origin(target, self.base_url, timeout=30)
            try:
                data = _read_capped(resp, self.max_resource_bytes)
            finally:
                resp.close()
        else:
            # Size-check the file's size on disk before reading it, so a confined
            # but huge local sibling cannot be slurped past the cap into RAM first.
            if self.max_resource_bytes is not None:
                _check_size(os.path.getsize(target), self.max_resource_bytes, uri)
            with open(target, 'rb') as f:
                data = f.read()
        self._cache[uri] = data
        return data


def _default_cache_dir():
    """Per-user cache directory for fetched remote assets.

    Cache under the per-user app-data location the rest of OpenGLContext uses
    (font metadata, preferences), not world-writable system temp, so no other
    account can pre-seed a cache entry this user then loads. Falls back to system
    temp only when the app-data location can't be determined.
    """
    from OpenGLContext.browser import homedirectory
    try:
        base = homedirectory.appdatadirectory()
    except OSError:
        import tempfile
        base = tempfile.gettempdir()
    return os.path.join(base, 'OpenGLContext', 'asset_cache')


def cached_path(url, cache_dir=None):
    """Local cache path a fetch of ``url`` uses, whether or not it is cached yet.

    The single definition of the on-disk key (a sha1 of the URL, keeping the URL's
    extension); :func:`_fetch_url` and :func:`fetch_to_cache` both route through it
    so no caller re-derives the path.
    """
    import hashlib
    cache_dir = cache_dir or _default_cache_dir()
    key = hashlib.sha1(url.encode('utf-8')).hexdigest() + os.path.splitext(url)[1]
    return os.path.join(cache_dir, key)


def _read_cached(path):
    """Return the bytes of a cached file (touching its mtime), or None if absent.

    An atomic write (:func:`_atomic_write`) means the path exists only when it is
    complete, so a successful read is never partial.
    """
    if os.path.exists(path):
        # Mark the entry as used so purge_cache treats mtime as last-access time.
        try:
            os.utime(path, None)
        except OSError:
            pass
        with open(path, 'rb') as f:
            return f.read()
    return None


# In-process single-flight: one lock per cache key (URL hash), so concurrent
# callers for the same asset -- the IBL probe and an HDR background node both
# loading one panorama -- share a single download instead of each fetching it.
# Guarded by _INFLIGHT_LOCK; each entry is [lock, waiter_count] and is dropped
# once the last waiter leaves, so the map does not grow unbounded.
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT = {}


def _acquire_download_slot(path):
    with _INFLIGHT_LOCK:
        entry = _INFLIGHT.get(path)
        if entry is None:
            entry = [threading.Lock(), 0]
            _INFLIGHT[path] = entry
        entry[1] += 1
        return entry[0]


def _release_download_slot(path):
    with _INFLIGHT_LOCK:
        entry = _INFLIGHT.get(path)
        if entry is not None:
            entry[1] -= 1
            if entry[1] <= 0:
                del _INFLIGHT[path]


def _fetch_url(url, cache_dir=None, max_bytes=DEFAULT_MAX_RESOURCE_BYTES):
    """Fetch ``url`` into the on-disk cache (keyed by URL hash) and return its bytes.

    A cache hit is touched so its mtime tracks last-use, letting
    :func:`purge_cache` evict assets that have gone stale by disuse. Concurrent
    in-process fetches of the same asset are coalesced: only the first downloads,
    the rest wait and then read the cached file. The fetch itself is origin-locked
    (:func:`_urlopen_same_origin`) and size-capped.
    """
    cache_dir = cache_dir or _default_cache_dir()
    os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    path = cached_path(url, cache_dir)
    data = _read_cached(path)
    if data is not None:
        return data
    # Serialize concurrent fetches of this exact asset on a per-key lock; a second
    # caller waits here rather than launching a duplicate download.
    lock = _acquire_download_slot(path)
    try:
        with lock:
            data = _read_cached(path)      # the winner may have finished while we waited
            if data is not None:
                return data
            # The top-level document fetch is user-initiated, but a redirect that
            # leaves the requested URL's origin is still refused (defence in depth)
            # so a hostile server can't bounce the fetch to a link-local metadata
            # endpoint.
            resp = _urlopen_same_origin(url, url, timeout=30)
            try:
                data = _read_capped(resp, max_bytes)
            finally:
                resp.close()
            _atomic_write(path, data, cache_dir)
            return data
    finally:
        _release_download_slot(path)


def _atomic_write(path, data, cache_dir):
    """Write ``data`` to ``path`` atomically, so ``path`` never appears partial.

    Two callers can fetch the same URL concurrently (e.g. the IBL probe and an HDR
    background node both loading one panorama). A plain ``open(path, 'wb')``
    truncates the file first, so a second caller that finds the path present would
    read a half-written file. Writing to a unique temp file in the same directory
    and ``os.replace``-ing it into place makes the cache entry appear all-at-once,
    and a reader holding the old inode keeps reading a complete file."""
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=cache_dir, prefix='.dl-')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fetch_to_cache(url, cache_dir=None, max_bytes=DEFAULT_MAX_RESOURCE_BYTES):
    """Fetch ``url`` into the cache (once) and return its local file path.

    The path variant of :func:`_fetch_url`, for callers that want the cached file
    on disk (e.g. an image to embed) rather than its bytes.
    """
    _fetch_url(url, cache_dir, max_bytes)
    return cached_path(url, cache_dir)


def purge_cache(cache_dir=None, max_age_days=30):
    """Delete cached assets not used within ``max_age_days``, returning the count.

    :func:`_fetch_url` touches an entry on every hit, so its mtime is its
    last-use time; anything older than the cutoff is a working-set miss and is
    removed. A missing cache directory is a no-op.
    """
    import time
    cache_dir = cache_dir or _default_cache_dir()
    if not os.path.isdir(cache_dir):
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed
