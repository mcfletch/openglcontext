"""Reference renders of X3D documents from X_ITE, Web3D's JavaScript X3D browser

X_ITE (https://create3000.github.io/x_ite/, MIT) is the browser Web3D
publishes beside each of its examples. :class:`ReferenceRenderer` draws a
document in it, in a headless Chromium, and keeps a screenshot: a current X3D
browser's view of the document, beside which ``oglc-x3d-regression`` shows
ours.

- :func:`distribution` downloads the X_ITE release :data:`VERSION` from npm
  once, checks it against :data:`TARBALL_SHA256`, and unpacks its ``dist``
  folder into the resolver's cache.
- :class:`SceneServer` serves a harness page, X_ITE and a folder of documents
  from 127.0.0.1, since a browser reads a document's textures and Inlines by
  URL. Nothing outside those two folders is served.
- :class:`ReferenceRenderer` opens Chromium through Playwright (the
  ``x3d-reference`` extra) with WebGL drawn by SwiftShader, in software, so a
  reference does not depend on the machine's GPU.

Animated documents are captured once their load has finished and half a
second has passed, so a reference of a moving scene shows one moment of it.
"""
from __future__ import annotations

import functools
import hashlib
import http.server
import mimetypes
import os
import tarfile
import threading
import time
import urllib.parse
from types import TracebackType
from typing import Any, Optional

from OpenGLContext.loaders import resolver

__all__ = [
    'VERSION', 'TARBALL_URL', 'TARBALL_SHA256', 'distribution', 'unpack', 'harness_page',
    'reference_path', 'SceneServer', 'ReferenceRenderer', 'browser_available',
]

#: The X_ITE release references are made with.
VERSION = '16.4.3'
TARBALL_URL = 'https://registry.npmjs.org/x_ite/-/x_ite-%s.tgz' % VERSION
TARBALL_SHA256 = 'f3a2814098624fda1a635139d0659da409fd17502aa92d84a704b7581ccd4981'
#: Seconds a document has to load in X_ITE.
LOAD_TIMEOUT = 30.0
#: Milliseconds drawn after the load before the screenshot.
SETTLE_MS = 500
#: Chromium's switches: WebGL drawn by SwiftShader, whatever the GPU.
CHROMIUM_ARGS = ('--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                 '--ignore-gpu-blocklist')

_TYPES = {'.x3d': 'model/x3d+xml', '.x3dv': 'model/x3d-vrml', '.x3dj': 'model/x3d+json',
          '.wrl': 'model/vrml', '.js': 'text/javascript', '.mjs': 'text/javascript',
          '.wasm': 'application/wasm', '.json': 'application/json'}


def unpack(source: str, destination: str) -> str:
    """Unpack the ``package/dist`` folder of an X_ITE tarball; its path

    A member that would land outside `destination` is refused (ValueError).
    """
    root = os.path.realpath(destination)
    with tarfile.open(source, 'r:gz') as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.startswith('package/dist/'):
                continue
            target = os.path.realpath(os.path.join(root, member.name[len('package/'):]))
            if not target.startswith(root + os.sep):
                raise ValueError('Tarball member %r leaves %s' % (member.name, root))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            with extracted, open(target + '.part', 'wb') as stream:
                stream.write(extracted.read())
            os.replace(target + '.part', target)
    return os.path.join(root, 'dist')


def distribution(cache: Optional[str] = None) -> str:
    """The folder of X_ITE's ``dist`` files, downloaded and checked once"""
    where = os.path.join(cache or resolver.default_cache_dir(), 'x_ite', VERSION)
    dist = os.path.join(where, 'dist')
    if os.path.exists(os.path.join(dist, 'x_ite.min.js')):
        return dist
    tarball = resolver.fetch_to_cache(resolver.checked_url(TARBALL_URL),
                                      resolver.default_cache_dir())
    digest = hashlib.sha256()
    with open(tarball, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    if digest.hexdigest() != TARBALL_SHA256:
        raise IOError('X_ITE %s has SHA-256 %s, not %s'
                      % (VERSION, digest.hexdigest(), TARBALL_SHA256))
    return unpack(tarball, where)


def harness_page(size: tuple[int, int]) -> str:
    """The page that loads the document its ``scene`` query names into X_ITE

    ``window.done`` becomes true once X_ITE has loaded it, ``'error'`` where
    it could not.
    """
    width, height = size
    return '''<!doctype html>
<html><head><meta charset="utf-8">
<script src="x_ite/x_ite.min.js"></script>
<style>html,body{margin:0;background:#000} x3d-canvas{width:%dpx;height:%dpx;display:block}</style>
</head><body>
<x3d-canvas id="canvas" contextMenu="false" notifications="false" timings="false"></x3d-canvas>
<script>
const canvas = document.getElementById('canvas');
window.done = false;
canvas.addEventListener('load', () => { window.done = true; });
canvas.addEventListener('error', () => { window.done = 'error'; });
canvas.setAttribute('src', new URLSearchParams(location.search).get('scene'));
</script></body></html>
''' % (width, height)


def reference_path(root: str, slug: str) -> str:
    """Where the reference of the document `slug` is kept, under `root`"""
    return os.path.join(root, '_x_ite', VERSION, slug + '.png')


class _Handler(http.server.BaseHTTPRequestHandler):
    """Answers the harness page, X_ITE's files and the documents; nothing else"""

    def __init__(self, *args: Any, documents: str, dist: str, page: bytes, **named: Any) -> None:
        self.documents, self.dist, self.page = documents, dist, page
        super().__init__(*args, **named)

    def log_message(self, format: str, *args: Any) -> None:
        """Quiet: a run asks for thousands of files"""

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path.lstrip('/')
        if path == 'harness.html':
            self._send(self.page, 'text/html')
            return
        base, _, rest = path.partition('/')
        folder = {'x_ite': self.dist, 'scene': self.documents}.get(base)
        try:
            if folder is None or not rest:
                raise IOError(path)
            found = resolver.contain(folder, rest)
            with open(found, 'rb') as stream:
                data = stream.read()
        except OSError:
            self.send_error(404)
            return
        suffix = os.path.splitext(found)[1].lower()
        self._send(data, _TYPES.get(suffix) or mimetypes.guess_type(found)[0]
                   or 'application/octet-stream')

    def _send(self, data: bytes, kind: str) -> None:
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class SceneServer:
    """Serves the harness page, X_ITE and a folder of documents from 127.0.0.1

    A context manager; ``url`` is the server's root while it runs.
    """

    def __init__(self, documents: str, dist: str, size: tuple[int, int]) -> None:
        handler = functools.partial(_Handler, documents=documents, dist=dist,
                                    page=harness_page(size).encode('utf-8'))
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.server.daemon_threads = True
        self.url = 'http://127.0.0.1:%d' % self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, name='x_ite-server',
                                        daemon=True)

    def __enter__(self) -> 'SceneServer':
        self._thread.start()
        return self

    def __exit__(self, kind: Optional[type[BaseException]], value: Optional[BaseException],
                 trace: Optional[TracebackType]) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join()


def browser_available() -> bool:
    """Whether Playwright can start Chromium on this machine"""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 the optional extra
        with sync_playwright() as playwright:
            playwright.chromium.launch(args=list(CHROMIUM_ARGS)).close()
        return True
    except Exception:
        return False


class ReferenceRenderer:
    """Draws documents of one folder in X_ITE, in a headless Chromium

    A context manager holding the server, the browser and one page.
    """

    def __init__(self, documents: str, dist: str, size: tuple[int, int]) -> None:
        self.size = size
        self.server = SceneServer(documents, dist, size)

    def __enter__(self) -> 'ReferenceRenderer':
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 the optional extra
        self.server.__enter__()
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(args=list(CHROMIUM_ARGS))
        width, height = self.size
        self._page = self._browser.new_page(viewport={'width': width, 'height': height})
        self._errors: list[str] = []
        self._page.on('console', lambda message: self._errors.append(message.text)
                      if message.type == 'error' else None)
        self._page.on('pageerror', lambda error: self._errors.append(str(error)))
        return self

    def __exit__(self, kind: Optional[type[BaseException]], value: Optional[BaseException],
                 trace: Optional[TracebackType]) -> None:
        self._browser.close()
        self._playwright.stop()
        self.server.__exit__(kind, value, trace)

    def render(self, relative: str, out: str) -> dict[str, Any]:
        """Draw the document at `relative` in the folder into the PNG `out`

        ``ok`` says whether it was written; ``errors`` holds what the page
        reported, and ``seconds`` the time taken.
        """
        self._errors.clear()
        start = time.monotonic()
        scene = 'scene/' + urllib.parse.quote(relative.replace(os.sep, '/'))
        try:
            self._page.goto('%s/harness.html?scene=%s' % (self.server.url, scene))
            self._page.wait_for_function('window.done', timeout=LOAD_TIMEOUT * 1000)
            loaded = self._page.evaluate('window.done')
            self._page.wait_for_timeout(SETTLE_MS)
            os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
            self._page.locator('#canvas').screenshot(path=out)
        except Exception as error:
            return {'ok': False, 'errors': list(self._errors) + [str(error).splitlines()[0]],
                    'seconds': time.monotonic() - start}
        errors = list(self._errors)
        if loaded == 'error':
            errors.append('X_ITE could not load the document')
        return {'ok': os.path.exists(out), 'errors': errors[:20],
                'seconds': time.monotonic() - start}
