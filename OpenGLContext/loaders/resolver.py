"""Secure resolution and fetching of untrusted external assets for loaders.

Shared by OpenGLContext's asset loaders: any loader that follows external
references constructs a :class:`Resolver` with the document's base URL or
directory and asks it to resolve each referenced URI. That is glTF's buffers,
images and audio (:mod:`OpenGLContext.loaders.gltf`) and a 3D Tiles tileset's
content and nested tilesets (:mod:`OpenGLContext.loaders.tiles3d.fetch`, which
resolves through here rather than keeping a policy of its own). Those references
are attacker-controlled for any document from an untrusted source, so this is the
containment core, kept in one auditable place. It enforces:

* a document fetched over HTTP(S) may only pull same-origin http(s) URIs
  (blocks ``file://`` reads and ``169.254.169.254`` metadata SSRF), re-checked on
  every redirect hop by a :class:`RedirectPolicy` -- :data:`SAME_ORIGIN` for a
  document, :data:`PUBLIC_HOSTS` for content a trusted registry named,
  :class:`AllowedHosts` for a service that publishes from hosts named in
  advance;
* :func:`fetch_url` fetches http(s) and nothing else;
* a document loaded from a local path may only read files under its own directory
  (blocks ``../../etc/passwd`` traversal and absolute paths);
* every fetched or decoded resource is size-capped; and
* the disk cache lives under the per-user app-data directory, not world-writable
  system temp.

:func:`safe_url`, :func:`fetch_url` and :func:`decode_data_uri` are the
fetch/decode primitives; :class:`Resolver` ties them to one document's origin.

These names are public. A loader in another distribution --
``OpenGLContext_editor`` reading a baked level's sidecar, an application
reading its own format -- imports them to be held to the same policy rather
than implementing containment again.
"""

__all__ = [
    'Resolver', 'FetchCancelled', 'ResourceTooLarge', 'Progress', 'Cancel',
    'RedirectPolicy', 'SameOrigin', 'PublicHosts', 'AllowedHosts',
    'SAME_ORIGIN', 'PUBLIC_HOSTS', 'open_url',
    'DEFAULT_MAX_RESOURCE_BYTES', 'DEFAULT_MAX_IMAGE_PIXELS', 'DOWNLOAD_CHUNK_BYTES',
    'safe_url', 'is_url', 'is_local', 'require_host', 'user_agent', 'check_size', 'check_pixels', 'decode_data_uri', 'resolver_max',
    'fetch_url', 'fetch_to_cache', 'stream_capped', 'stream_to', 'cached_path',
    'default_cache_dir', 'purge_cache',
]

import base64
import ipaddress
import logging
import os
import socket
import threading
import urllib.parse
import urllib.request
import urllib.error
from typing import Any, Callable, List, Optional, Sequence, Tuple

from OpenGLContext import atomicfiles

log = logging.getLogger(__name__)


def safe_url(url: str) -> str:
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

#: Ceiling on the pixels an image may declare before anything is allocated for
#: it. Pillow's own decompression-bomb threshold, so a picture is judged the
#: same way whichever decoder reads it.
DEFAULT_MAX_IMAGE_PIXELS = 178_956_970

#: How much of a download is read at a time.  Small enough that a progress bar
#: moves and a cancel is acted on promptly, large enough that a big transfer is
#: not one syscall per screenful.
DOWNLOAD_CHUNK_BYTES = 256 * 1024

#: What a caller is told as a download runs: bytes so far, and the total the
#: server declared -- or None, since plenty of servers declare none and a bar
#: with no total should show motion rather than a false 100%.
Progress = Callable[[int, Optional[int]], None]

#: Asked between chunks; returning true abandons the download.
Cancel = Callable[[], bool]


class FetchCancelled(Exception):
    """A download was abandoned because its caller asked for it to be.

    Distinct from a failure: nothing went wrong, so a caller that asked for the
    cancellation should not report an error about it.
    """
_ALLOWED_URL_SCHEMES = ('http', 'https')


def _origin(url: str) -> Tuple[str, str]:
    """(scheme, netloc) security origin of a URL.

    ``netloc`` keeps host, port and any userinfo verbatim, so two virtual hosts on
    one IP -- or one host on two ports -- are distinct origins, as intended.
    """
    parts = urllib.parse.urlsplit(url)
    return (parts.scheme.lower(), parts.netloc.lower())


def require_host(url: str, allowed: Sequence[str]) -> str:
    """``url`` unchanged, or ``IOError`` unless it is https on an allowed host.

    For a URL a *service* handed back rather than one a person typed: a
    catalogue is asked where an asset lives and answers with a link, and that
    answer is data like any other. A service that is compromised,
    misconfigured or simply wrong can answer ``file:///etc/passwd``,
    ``http://169.254.169.254/`` or a plaintext link to the right name, and a
    client that fetches whatever it is told has handed the decision over.

    So the caller names the hosts its provider publishes from in advance --
    they are a fact about the provider, not about the response -- and the
    comparison is on the parsed host, exactly and case-insensitively. A
    hostname *ending* in an allowed one is a different host
    (``polyhaven.com.example``), userinfo before the host names a different
    host (``dl.polyhaven.org@example``), and a non-default port is a different
    service.

    Plaintext ``http`` is refused rather than upgraded: what comes back is
    written to a cache and read as content, so a connection anyone on the path
    can rewrite is not one to take it over.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() != 'https':
        raise IOError("%r must be an https URL to be fetched" % (url,))
    host = (parts.hostname or '').lower()
    if host not in {name.lower() for name in allowed}:
        raise IOError(
            "%r is not on a host this asset may come from (%s)"
            % (url, ', '.join(sorted(allowed))))
    try:
        port = parts.port
    except ValueError as err:
        raise IOError("%r does not name a usable port" % (url,)) from err
    if port not in (None, 443):
        raise IOError("%r names port %s rather than the https port" % (url, port))
    return url


def check_pixels(width: int, height: int,
                 max_pixels: int = DEFAULT_MAX_IMAGE_PIXELS,
                 what: str = 'image') -> None:
    """Refuse a picture whose declared size is not a picture.

    An image format states its dimensions in a header, and a decoder allocates
    against that statement before it has read a pixel -- so a hundred bytes can
    ask for forty gigabytes. Pillow refuses that arithmetic for the formats it
    decodes; a decoder written here asks this instead, so one rule covers both.

    The default is Pillow's own threshold, which keeps the two answers the same
    whichever decoder a file happens to reach.
    """
    if width <= 0 or height <= 0:
        raise ValueError("%s has non-positive dimensions %dx%d" % (what, width, height))
    if width * height > max_pixels:
        raise ValueError(
            "%s declares %dx%d = %d pixels, over the %d-pixel limit"
            % (what, width, height, width * height, max_pixels))


def is_url(source: Optional[str]) -> bool:
    """Whether ``source`` names something to fetch rather than a path to open.

    True only for the schemes this module will actually fetch, so a caller that
    branches on it cannot hand a ``file:`` or ``data:`` URI to the network path.
    """
    if not source:
        return False
    return _origin(source)[0] in _ALLOWED_URL_SCHEMES


def _same_origin(a: str, b: str) -> bool:
    return _origin(a) == _origin(b)


def _without_query(url: str) -> str:
    """``url`` with its query and fragment removed, for a message or a log.

    A CDN's redirect target is signed in its query string, and a signature
    written into an exception reaches logs and telemetry journals.
    """
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path,
                                    '', ''))


def _addresses(host: str) -> List[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """The addresses ``host`` names: itself when it is a literal, else DNS's.

    An IPv4 address carried inside an IPv6 one (``::ffff:10.0.0.1``) is
    answered as the IPv4 address, since that is where a connection goes.
    Empty when the name does not resolve.
    """
    try:
        found = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        except (OSError, UnicodeError):
            return []
        found = [ipaddress.ip_address(str(info[4][0]).split('%', 1)[0])
                 for info in infos]
    return [address.ipv4_mapped
            if isinstance(address, ipaddress.IPv6Address)
            and address.ipv4_mapped is not None else address
            for address in found]


class RedirectPolicy:
    """Which redirect targets a fetch follows.

    ``urllib`` follows a 3xx without looking at where it goes, so each hop is
    put to :meth:`refusal` before it is followed. ``original`` is the URL the
    caller asked for, and ``target`` the one the server answered with.
    """

    def refusal(self, original: str, target: str) -> Optional[str]:
        """Why ``target`` is not followed, or None when it is."""
        raise NotImplementedError


class SameOrigin(RedirectPolicy):
    """A redirect keeps the scheme family and the exact origin.

    The policy for a document and every reference it makes: a same-origin URL
    that answers 302 with a link-local address (``169.254.169.254``) is
    refused here as the reference itself would have been.
    """

    def refusal(self, original: str, target: str) -> Optional[str]:
        if _origin(target)[0] not in _ALLOWED_URL_SCHEMES:
            return 'it is not an http(s) URL'
        if not _same_origin(original, target):
            return 'it leaves the origin of %s' % (_without_query(original),)
        return None


class PublicHosts(RedirectPolicy):
    """A redirect may reach any public host over https.

    The policy for content whose URL a trusted party named and whose bytes are
    checked by digest -- a content pack, or an archive the user typed. Release
    hosts answer every download with a redirect to a CDN on another host, so
    the origin lock is the wrong control for these. What stays refused:

    * anything but http(s);
    * plaintext, except between two loopback addresses, where no network is
      crossed;
    * a private, loopback, link-local or otherwise non-global address, unless
      the URL asked for was itself on loopback and the target is too -- a local
      mirror or a test server redirecting to itself.

    A host name is resolved here to judge it, and resolved again when the
    connection is made, so a name whose DNS answer changes between the two is
    judged on the first answer.
    """

    def refusal(self, original: str, target: str) -> Optional[str]:
        scheme = _origin(target)[0]
        if scheme not in _ALLOWED_URL_SCHEMES:
            return 'it is not an http(s) URL'
        host = urllib.parse.urlsplit(target).hostname or ''
        addresses = _addresses(host)
        if not addresses:
            return 'its host %r does not resolve' % (host,)
        from_loopback = _is_loopback(original)
        for address in addresses:
            if address.is_loopback and from_loopback:
                continue
            if not address.is_global:
                return 'its host %r is at %s, which is not a public address' % (
                    host, address)
        if scheme != 'https' and not (from_loopback and all(
                address.is_loopback for address in addresses)):
            return 'it is plaintext http'
        return None


class AllowedHosts(RedirectPolicy):
    """A redirect stays on hosts named in advance, over https.

    The policy for a service that publishes from a known set of hosts: every
    hop is put to :func:`require_host` against ``hosts``, the same test the
    first URL is given, so a redirect cannot carry a download somewhere the
    URL itself would have been refused.
    """

    def __init__(self, hosts: Sequence[str]) -> None:
        self.hosts = tuple(hosts)

    def refusal(self, original: str, target: str) -> Optional[str]:
        try:
            require_host(target, self.hosts)
        except IOError as err:
            return str(err)
        return None


def is_local(url: str) -> bool:
    """Whether ``url`` names this machine: ``localhost`` or a loopback address.

    Read off the URL alone, without asking DNS, for a check made where content
    is declared rather than fetched: plaintext to this machine crosses no
    network anyone could be on.
    """
    host = (urllib.parse.urlsplit(url).hostname or '').lower()
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_loopback(url: str) -> bool:
    """Whether every address ``url``'s host names is on this machine."""
    addresses = _addresses(urllib.parse.urlsplit(url).hostname or '')
    return bool(addresses) and all(address.is_loopback for address in addresses)


#: The redirect policy for a document and its references: the default.
SAME_ORIGIN: RedirectPolicy = SameOrigin()

#: The redirect policy for content named by a trusted registry and checked by
#: digest, or opened by the user: any public https host.
PUBLIC_HOSTS: RedirectPolicy = PublicHosts()


class _PolicyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Put every redirect hop to a :class:`RedirectPolicy` before following it."""

    def __init__(self, original: str, policy: RedirectPolicy) -> None:
        self._original = original
        self._policy = policy

    def redirect_request(self, req: urllib.request.Request, fp: Any, code: int,
                         msg: Any, headers: Any,
                         newurl: str) -> Optional[urllib.request.Request]:
        refused = self._policy.refusal(self._original, newurl)
        if refused is not None:
            shown = _without_query(newurl)
            raise urllib.error.HTTPError(
                shown, code,
                "fetch refused the redirect to %r: %s" % (shown, refused),
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _OriginLockedRedirectHandler(_PolicyRedirectHandler):
    """Re-apply the same-origin policy on every redirect hop."""

    def __init__(self, base_url: str) -> None:
        super().__init__(base_url, SAME_ORIGIN)


def user_agent() -> str:
    """How this fetcher identifies itself to a server.

    A number of asset hosts reject Python's default ``Python-urllib/x.y``
    outright with a 403, so a fetch that would otherwise succeed fails for a
    reason nothing in the response explains. Naming the project (and a contact
    URL, as the convention asks) is also simply the polite thing for a client
    that pulls other people's files.
    """
    from OpenGLContext import __version__
    return ('OpenGLContext/%s (+https://github.com/mcfletch/openglcontext)'
            % (__version__,))


def open_url(url: str, redirects: RedirectPolicy = SAME_ORIGIN,
             timeout: int = 30, agent: Optional[str] = None) -> Any:
    """The open response for ``url``, having followed only the redirects
    ``redirects`` allows.

    ``agent`` is the ``User-Agent`` sent, :func:`user_agent` when None. The
    response is a context manager; read it with :func:`stream_capped` or
    :func:`stream_to` to bound what arrives.
    """
    opener = urllib.request.build_opener(_PolicyRedirectHandler(url, redirects))
    request = urllib.request.Request(
        safe_url(url), headers={'User-Agent': agent or user_agent()})
    return opener.open(request, timeout=timeout)


def _open_url(url: str, redirects: RedirectPolicy = SAME_ORIGIN,
              timeout: int = 30) -> Any:
    """:func:`open_url` as this module's fetches call it, one name to replace
    in a test that serves them."""
    return open_url(url, redirects, timeout)


def _resolve_local(base_dir: str, uri: str) -> str:
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


class ResourceTooLarge(ValueError):
    """A resource is larger than the cap it was fetched or decoded under.

    A ``ValueError``, as a limit on a value is; its own class so a caller that
    reports the ways one fetch can fail catches this and nothing else.
    """


def check_size(nbytes: int, max_bytes: Optional[int], what: str) -> None:
    """Raise :class:`ResourceTooLarge` where ``nbytes`` is over ``max_bytes``."""
    if max_bytes is not None and nbytes > max_bytes:
        raise ResourceTooLarge(
            "resource %s is %d bytes, over the %d-byte limit"
            % (what, nbytes, max_bytes))


def decode_data_uri(uri: str, max_bytes: Optional[int] = None) -> bytes:
    """Decode a ``data:`` URI to bytes.

    Handles ``data:[<mediatype>][;base64],<payload>`` -- base64 or percent-encoded
    -- and raises a clear error on a malformed URI rather than an opaque
    ``IndexError``.
    """
    if ',' not in uri:
        raise ValueError("malformed data: URI (no comma): %r" % uri[:64])
    header, _, payload = uri.partition(',')
    if ';base64' in header.lower():
        # Four characters of the alphabet decode to three bytes, so the size
        # is known, and checked, before the bytes are allocated.
        ignored = sum(payload.count(char) for char in '= \t\r\n')
        check_size((len(payload) - ignored) * 3 // 4, max_bytes, 'data: URI')
        data = base64.b64decode(payload)
    else:
        data = urllib.parse.unquote_to_bytes(payload)
    check_size(len(data), max_bytes, 'data: URI')
    return data


def resolver_max(resolver: Optional["Resolver"]) -> Optional[int]:
    return getattr(resolver, 'max_resource_bytes', None) if resolver is not None else None


class Resolver:
    """Resolves a document's external asset URIs against its base URL or directory.

    Enforces the untrusted-asset policy: a URL-loaded document may
    only pull same-origin http(s) references; a file-loaded document may only read
    files under its own directory. Each resource is size-capped.
    """

    def __init__(self, base_url: Optional[str] = None, base_dir: Optional[str] = None,
                 max_resource_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES) -> None:
        self.base_url = base_url
        self.base_dir = base_dir
        self.max_resource_bytes = max_resource_bytes
        self._cache: dict[str, bytes] = {}
        self._buffers: dict[int, bytes] = {}   # decoded buffer bytes, keyed by buffer index
        self._resolved: dict[str, str] = {}    # resolved absolute location, keyed by raw uri
        self._draco_warned = False   # the "install DracoPy" warning fired once

    def resolve(self, uri: str) -> str:
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

    def _resolve(self, uri: str) -> str:
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

    def fetch(self, uri: str) -> bytes:
        """Return the bytes of an external reference, enforcing the policy.

        Resolves ``uri`` against the document's base URL (same-origin http(s)
        only) or base directory (confined to it), size-caps the result, and
        memoises it. Raises ``IOError`` when the reference is out of bounds or no
        base was given, and ``ValueError`` when it exceeds the size cap.

        A remote reference goes through the **on-disk** cache rather than
        straight to the network.  This memo is per-``Resolver`` and a fresh one
        is built for every load, so without it re-opening a multi-file ``.gltf``
        re-downloaded every buffer and every texture -- seventy-odd of them for
        a scene like Sponza, which is what made opening a model twice feel like
        there was no cache at all.  :func:`resolve` has already refused anything
        off the document's origin by this point, so locking the redirect chain
        to the reference's own origin is the same policy it always was.
        """
        if uri in self._cache:
            return self._cache[uri]
        target = self.resolve(uri)
        if self.base_url is not None:
            data = fetch_url(target, max_bytes=self.max_resource_bytes)
        else:
            # Size-check the file's size on disk before reading it, so a confined
            # but huge local sibling cannot be slurped past the cap into RAM first.
            if self.max_resource_bytes is not None:
                check_size(os.path.getsize(target), self.max_resource_bytes, uri)
            with open(target, 'rb') as f:
                data = f.read()
        self._cache[uri] = data
        return data


def default_cache_dir() -> str:
    """Per-user cache directory for fetched remote assets.

    Cache under the per-user app-data location the rest of OpenGLContext uses
    (font metadata, preferences), not world-writable system temp, so no other
    account can pre-seed a cache entry this user then loads. Falls back to system
    temp only when the app-data location can't be determined.
    """
    from OpenGLContext import userpaths
    try:
        base = userpaths.appdatadirectory()
    except OSError:
        import tempfile
        base = tempfile.gettempdir()
    return os.path.join(base, 'OpenGLContext', 'asset_cache')


def cached_path(url: str, cache_dir: Optional[str] = None) -> str:
    """Local cache path a fetch of ``url`` uses, whether or not it is cached yet.

    The single definition of the on-disk key (a sha1 of the URL, keeping the URL's
    extension); :func:`fetch_url` and :func:`fetch_to_cache` both route through it
    so no caller re-derives the path.
    """
    import hashlib
    cache_dir = cache_dir or default_cache_dir()
    key = hashlib.sha1(url.encode('utf-8')).hexdigest() + os.path.splitext(url)[1]
    return os.path.join(cache_dir, key)


def _touch(path: str) -> bool:
    """Mark a cached file as used now, answering whether it is there.

    An atomic write means the path exists only when it is complete, so a file
    found here is whole. Its mtime is what :func:`purge_cache` reads as the last
    use; a filesystem that refuses the touch still serves the file.
    """
    if not os.path.exists(path):
        return False
    try:
        os.utime(path, None)
    except OSError:
        pass
    return True


# In-process single-flight: one lock per cache key (URL hash), so concurrent
# callers for the same asset -- the IBL probe and an HDR background node both
# loading one panorama -- share a single download instead of each fetching it.
# Guarded by _INFLIGHT_LOCK; each entry is [lock, waiter_count] and is dropped
# once the last waiter leaves, so the map does not grow unbounded.
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: dict[str, list] = {}


def _acquire_download_slot(path: str) -> Any:
    with _INFLIGHT_LOCK:
        entry = _INFLIGHT.get(path)
        if entry is None:
            entry = [threading.Lock(), 0]
            _INFLIGHT[path] = entry
        entry[1] += 1
        return entry[0]


def _release_download_slot(path: str) -> None:
    with _INFLIGHT_LOCK:
        entry = _INFLIGHT.get(path)
        if entry is not None:
            entry[1] -= 1
            if entry[1] <= 0:
                del _INFLIGHT[path]


def fetch_url(url: str, cache_dir: Optional[str] = None,
               max_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES,
               progress: Optional[Progress] = None,
               cancel: Optional[Cancel] = None,
               redirects: RedirectPolicy = SAME_ORIGIN) -> bytes:
    """Fetch ``url`` into the on-disk cache (keyed by URL hash) and return its bytes.

    A cache hit is touched so its mtime tracks last-use, letting
    :func:`purge_cache` evict assets that have gone stale by disuse. Concurrent
    in-process fetches of the same asset are coalesced: only the first downloads,
    the rest wait and then read the cached file. The fetch is size-capped, and
    each redirect is put to ``redirects``: :data:`SAME_ORIGIN` unless the
    caller names :data:`PUBLIC_HOSTS`.

    Only http(s) is fetched; any other scheme is an ``IOError``, so a
    ``file://`` URL cannot copy a local file into the cache.

    ``progress`` and ``cancel`` are for an asset large enough to be worth
    watching -- see :func:`fetch_to_cache`, which this reads the result of.
    """
    path = fetch_to_cache(url, cache_dir, max_bytes, progress=progress,
                          cancel=cancel, redirects=redirects)
    with open(path, 'rb') as handle:
        return handle.read()


def _content_length(response: Any) -> Optional[int]:
    """How many bytes the server says are coming, or None if it did not say."""
    headers = getattr(response, 'headers', None)
    if headers is None:
        return None
    getter = getattr(headers, 'get', None)
    raw = getter('Content-Length') if getter is not None else None
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _report(progress: Optional[Progress], done: int,
            total: Optional[int]) -> None:
    """Tell a watcher how far along we are, and survive it if it falls over.

    An exception from ``progress`` is logged and the download goes on: a
    progress display that fails does not end a fetch.
    """
    if progress is None:
        return
    try:
        progress(done, total)
    except Exception:                           # noqa: BLE001 - never lose a fetch
        log.warning('a download progress callback raised', exc_info=True)


def stream_to(response: Any, target: Any, max_bytes: Optional[int],
              progress: Optional[Progress] = None,
              cancel: Optional[Cancel] = None) -> int:
    """Copy a response into ``target`` a chunk at a time; the bytes copied.

    Chunked for three reasons that arrive together: a content pack is hundreds
    of megabytes and reading one whole holds all of it in memory before a byte
    reaches the disk; a caller cannot draw a progress bar for a call that
    reports nothing until it returns; and a download that has begun cannot
    otherwise be abandoned. The cap is checked as the bytes arrive, and
    ``cancel`` is asked before each chunk.
    """
    total = _content_length(response)
    read = 0
    while True:
        if cancel is not None and cancel():
            raise FetchCancelled('the download was cancelled after %d bytes' % (read,))
        chunk = response.read(DOWNLOAD_CHUNK_BYTES)
        if not chunk:
            break
        read += len(chunk)
        check_size(read, max_bytes, 'remote resource')
        target.write(chunk)
        _report(progress, read, total)
    if not read:
        _report(progress, 0, total)
    return read


def stream_capped(response: Any, max_bytes: Optional[int],
            progress: Optional[Progress] = None,
            cancel: Optional[Cancel] = None) -> bytes:
    """Read a response a chunk at a time, watching the cap, the caller and the size.

    :func:`stream_to` into memory, for a caller that wants the bytes rather
    than a file: a response from an API rather than an asset.
    """
    import io
    held = io.BytesIO()
    stream_to(response, held, max_bytes, progress, cancel)
    return held.getvalue()


def fetch_to_cache(url: str, cache_dir: Optional[str] = None,
                   max_bytes: Optional[int] = DEFAULT_MAX_RESOURCE_BYTES,
                   progress: Optional[Progress] = None,
                   cancel: Optional[Cancel] = None,
                   redirects: RedirectPolicy = SAME_ORIGIN) -> str:
    """Fetch ``url`` into the cache (once) and return its local file path.

    The body is streamed into a temporary file beside its cache entry and
    renamed into place when complete, so a reader never finds a partial file
    and the download is never all in memory; a cache hit is touched and not
    read. Concurrent in-process fetches of one URL are coalesced into one
    download. Only http(s) is fetched, and each redirect is put to
    ``redirects`` as for :func:`fetch_url`.

    ``progress(done, total)`` is called as the bytes arrive, with ``total``
    None where the server declared no length; it is also called once on a cache
    hit, so a caller drawing a bar sees it finish whether or not anything was
    downloaded.  ``cancel()`` is asked between chunks and abandons the fetch
    with :class:`FetchCancelled` when it returns true.  Neither leaves a
    partial file in the cache.
    """
    if not is_url(url):
        raise IOError('%r is not an http(s) URL, and only those are fetched'
                      % (_without_query(url),))
    cache_dir = cache_dir or default_cache_dir()
    os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    path = cached_path(url, cache_dir)
    if _touch(path):
        size = os.path.getsize(path)
        _report(progress, size, size)
        return path
    # Serialize concurrent fetches of this exact asset on a per-key lock; a second
    # caller waits here rather than launching a duplicate download.
    lock = _acquire_download_slot(path)
    try:
        with lock:
            if _touch(path):      # the winner may have finished while we waited
                size = os.path.getsize(path)
                _report(progress, size, size)
                return path
            resp = _open_url(url, redirects, timeout=30)
            try:
                with atomicfiles.staged_file(path, 'wb') as target:
                    stream_to(resp, target, max_bytes, progress, cancel)
            finally:
                resp.close()
            return path
    finally:
        _release_download_slot(path)


def purge_cache(cache_dir: Optional[str] = None, max_age_days: int = 30) -> int:
    """Delete cached assets not used within ``max_age_days``, returning the count.

    :func:`fetch_url` touches an entry on every hit, so its mtime is its
    last-use time; anything older than the cutoff is a working-set miss and is
    removed. A missing cache directory is a no-op.
    """
    import time
    cache_dir = cache_dir or default_cache_dir()
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
