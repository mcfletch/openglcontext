"""Load-manager for downloading multi-value URLs

The Singleton "Loader" should be used for most interactions.

Resolution and fetching of untrusted sub-resources -- ImageTexture urls, OBJ
``mtllib``/``map_Kd``, ``Inline`` scenes, shader fragments -- is delegated to
:class:`OpenGLContext.loaders.resolver.Resolver`, so the same-origin /
directory-containment policy for attacker-controlled references lives in one
auditable place. References are resolved against the *currently-parsing file's*
absolute URL (a local document's references are confined to its directory; a
remote document's to its origin).
"""

import os
import urllib.parse
from urllib.request import url2pathname
from io import BytesIO
from OpenGL._bytes import bytes, unicode, as_8_bit
from OpenGLContext.loaders.resolver import (
    Resolver,
    _fetch_url,
    _ALLOWED_URL_SCHEMES,
    DEFAULT_MAX_RESOURCE_BYTES,
)


def as_unicode(u):
    if isinstance(u, bytes):
        return unicode(u, "utf-8")
    return u


import logging

log = logging.getLogger(__name__)


def url_scheme(url):
    """The scheme of ``url``, or ``''`` where it is a filesystem path.

    ``urlsplit`` reads the drive letter of a Windows path as a scheme --
    ``C:\\scenes\\room.wrl`` comes back as the scheme ``c`` -- and every
    absolute path on that platform is written that way. No registered URL
    scheme is a single character, so a one-character scheme is a drive letter.
    """
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    return "" if len(scheme) < 2 else scheme


def local_path(url):
    """Filesystem path for a local (no-scheme or ``file://``) URL.

    The one place that rule lives, so a ``file:`` URL means the same thing to
    every part of the system that is handed one -- a scene's ``baseURI``, a
    texture, a skin's artwork.
    """
    if url_scheme(url) == "file":
        return url2pathname(urllib.parse.urlsplit(url).path)
    if os.path.splitdrive(url)[0]:
        # A path with a drive on it is a path, and splitting it as a URL would
        # take the drive off. splitdrive answers '' on platforms with no drives,
        # so this is the Windows case and nothing else.
        return url
    parts = urllib.parse.urlsplit(url)
    # plain path (possibly percent-encoded); keep the raw string when there is no
    # path component so relative paths survive unchanged.
    return url2pathname(parts.path) if parts.path else url


def join_reference(baseURL, ref):
    """Resolve a document's reference against where the document itself is.

    ``urljoin`` resolves a reference against a *URL*, and a filesystem path is
    not one: an absolute Windows path parses as a one-character scheme, and
    urljoin hands the reference straight back unresolved -- so a model opened by
    absolute path would find none of its textures.

    The result is separated by ``/``, which every platform reads as a path and
    which a URL needs.
    """
    if url_scheme(baseURL):
        return urllib.parse.urljoin(baseURL, ref)
    if url_scheme(ref) or os.path.isabs(ref) or ref.startswith("/"):
        return ref
    directory = os.path.dirname(local_path(baseURL))
    if not directory:
        return ref
    return "%s/%s" % (directory.replace(os.sep, "/").rstrip("/"), ref)


def _resolver_for(baseURL, max_bytes=DEFAULT_MAX_RESOURCE_BYTES):
    """Build a :class:`Resolver` confining references to ``baseURL``'s scope.

    A remote (http(s)) base yields a same-origin resolver; a local base yields a
    resolver confined to the base file's directory. Raises ``IOError`` for a base
    whose scheme we cannot resolve references against.
    """
    scheme = url_scheme(baseURL)
    if scheme in _ALLOWED_URL_SCHEMES:
        return Resolver(base_url=baseURL, max_resource_bytes=max_bytes)
    if scheme in ("", "file"):
        base_dir = os.path.dirname(local_path(baseURL))
        return Resolver(base_dir=base_dir, max_resource_bytes=max_bytes)
    raise IOError("cannot resolve references against base url %r" % (baseURL,))


class _Loader(object):
    """(Singleton) Manager for downloading resources

    Is a generic class which provides download services
    which follow VRML97 semantics (multiple-URL definitions,
    with chaining to the first successful URL).
    """

    def __init__(
        self,
    ):
        """Initialize the Loader"""
        # One Resolver per base URL, so a document's repeated references (a marble
        # texture used by many shapes) are fetched and memoised once.
        self._resolvers = {}

    def __call__(self, url, baseURL=None):
        """Load the given multi-value url and call callbacks

        url -- vrml97-style url (multi-value string)
        baseURL -- optional base url from which items in url will
            be resolved.  protofunctions.root(node).baseURI will
            give you the baseURL normally used for the given node.

        raises IOError on failure
        returns (resolvedURL, filename, open_file, headers) on success

        headers is always None (kept for call-site compatibility).
        """
        log.info("Loading: %s, %s", url, baseURL)
        url = as_unicode(url)
        if isinstance(url, unicode):
            url = [url]
        else:
            url = [as_unicode(u) for u in url]
        for u in url:
            try:
                if baseURL:
                    resolvedURL, file, filename, headers = self.get_reference(u, baseURL)
                else:
                    resolvedURL, file, filename, headers = self.get(u)
            except IOError as err:
                log.warning("Failing url %s (base %s): %s", u, baseURL, err)
                continue
            if file is not None:
                return (resolvedURL, filename, file, headers)
        raise IOError("""Unable to download url %s""" % (url,))

    def _resolver(self, baseURL):
        resolver = self._resolvers.get(baseURL)
        if resolver is None:
            resolver = _resolver_for(baseURL)
            self._resolvers[baseURL] = resolver
        return resolver

    def get_reference(self, ref, baseURL):
        """Resolve and fetch an untrusted reference under ``baseURL``'s policy.

        ``ref`` is a raw (relative) reference from the document; the resolver
        joins it against ``baseURL`` and enforces same-origin / directory
        containment before any network or disk access. Returns
        ``(resolvedURL, file, filename, None)`` where ``file`` is an in-memory
        ``BytesIO`` of the fetched bytes. Raises ``IOError`` on a disallowed or
        unreachable reference.
        """
        resolver = self._resolver(baseURL)
        # `fetch` resolves `ref` internally too; `resolve` memoises its result, so
        # this second resolution is a cache hit rather than repeated policy work.
        target = resolver.resolve(ref)
        data = resolver.fetch(ref)
        return (target, BytesIO(data), target, None)

    def get(self, url):
        """Retrieve the given top-level (user-chosen) single-value URL

        Unlike a reference (see :meth:`get_reference`), the top-level document is
        user-initiated and so is not confined to a base directory. Local files,
        ``res://`` virtual resources, and http(s) downloads are supported.

        url -- single-value URL, which may be a local filename
            or any URL type supported by urllib

        returns (baseURL, file, filename, headers)
        """
        if url.startswith("res://"):
            module = url[6:]
            if "." in module:
                raise ValueError("Invalid character in resource url: %s" % (url,))
            name = "OpenGLContext.resources.%s" % (module,)
            module = __import__(name, {}, {}, name.split("."))
            return (url, BytesIO(as_8_bit(module.data)), module.source, None)
        scheme = url_scheme(url)
        if scheme in _ALLOWED_URL_SCHEMES:
            log.debug("download: %s", url)
            data = _fetch_url(url)
            return (url, BytesIO(data), url, None)
        # Local file: resolve to an absolute path so the scenegraph's baseURI is
        # the file's own location, not a path relative to the process's cwd.
        path = os.path.abspath(local_path(url))
        file = open(path, "rb")
        return (path, file, path, None)

    loadedHandlers = {}

    def loadHandlers(self):
        """Load all registered handlers"""
        from OpenGLContext import plugins

        entrypoints = plugins.Loader.all()
        for entrypoint in entrypoints:
            name = entrypoint.name
            try:
                creator = entrypoint.load()
            except ImportError as err:
                log.warning(
                    """Unable to load loader implementation for %s: %s""", name, err
                )
            else:
                try:
                    loader = creator()
                except Exception as err:
                    log.warning(
                        """Unable to initialize loader implementation for %s: %s""",
                        name,
                        err,
                    )
                else:
                    for extension in entrypoint.check:
                        self.loadedHandlers[extension] = loader
                    log.info(
                        """Loaded loader implementation for %s: %s""", name, loader
                    )

    def findHandler(self, url):
        """Find registered handler for the url's apparent suffix

        TODO: allow for content-type operations after downloading the URL
        """
        if not self.loadedHandlers:
            self.loadHandlers()
        for extension in self.loadedHandlers.keys():
            if url.endswith(extension):
                return self.loadedHandlers[extension]
        return None

    def load(self, url, baseURL=None):
        """Load the given URL as a scenegraph

        url -- the URL (or list of URLs) from which to load
        baseURL -- optional base URL from which to determine
            relative URL values
        """
        handler = self.findHandler(url)
        if not handler:
            raise ValueError(
                """We do not have a registered handler for url %r, registered handlers: %r"""
                % (
                    url,
                    list(Loader.loadedHandlers.keys()),
                )
            )
        result = self(url, baseURL=baseURL)
        if not result:
            return result
        # now parse/convert to scenegraph...
        return handler(*result)

    def loads(self, data, baseURL="resource.wrl"):
        """Load given raw data as a scenegraph

        data -- bytes to parse
        baseURL -- raw data from which to determine
            relative URL values
        """
        handler = self.findHandler(baseURL)
        if not handler:
            raise ValueError(
                """We do not have a registered handler for url %r, registered handlers: %r"""
                % (
                    baseURL,
                    Loader.loadedHandlers.keys(),
                )
            )
        return handler.parse(data, baseURL, filename="", file=None)[1]


Loader = _Loader()
