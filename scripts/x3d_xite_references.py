#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.40"]
# ///
"""Render Web3D's X3D examples in X_ITE, as reference images for oglc-x3d-regression

X_ITE (https://create3000.github.io/x_ite/, MIT) is the JavaScript X3D browser
Web3D publishes its examples with. This draws each ``.x3d`` document of the
corpus in it, in Playwright's headless Chromium with WebGL drawn by
SwiftShader in software, and writes ``<slug>.png`` and a ``<slug>.json``
record into ``tests/reference_images/x3d_xite``, which is committed to the
reference images repository. ``oglc-x3d-regression`` shows each beside our
render of the same document.

    uv run scripts/x3d_xite_references.py                 # every document not yet drawn
    uv run scripts/x3d_xite_references.py --only Background --refresh
    uv run scripts/x3d_xite_references.py --corpus DIR --out DIR --jobs 8

``uv run`` gives the script Playwright in an environment of its own; the
engine never imports it. The script installs Playwright's headless Chromium
where it is missing; Chromium itself needs the system libraries Playwright's
``install-deps`` names (NSS, NSPR, ATK, AT-SPI, Xdamage on Ubuntu). X_ITE is
downloaded from npm once, at :data:`VERSION`, and checked against
:data:`TARBALL_SHA256`. Each document and X_ITE are served from 127.0.0.1;
nothing else is fetched.

The script reads only the standard library and Playwright, so the corpus's
layout and the slug a document's files are named by are written out here as
well as in ``OpenGLContext.bin.x3d_regression``;
``tests/unit/test_x3d_xite_tool.py`` holds the two to the same answers.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import functools
import hashlib
import http.server
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from types import TracebackType
from typing import Any, NamedTuple, Optional

#: The X_ITE release references are drawn with.
VERSION = '16.4.3'
TARBALL_URL = 'https://registry.npmjs.org/x_ite/-/x_ite-%s.tgz' % VERSION
TARBALL_SHA256 = 'f3a2814098624fda1a635139d0659da409fd17502aa92d84a704b7581ccd4981'
#: The size of Web3D's own renders, and of oglc-x3d-regression's.
DEFAULT_SIZE = (792, 465)
DEFAULT_ARCHIVES = ('ConformanceNist', 'Vrml2Sourcebook')
#: Seconds a document has to load in X_ITE.
LOAD_TIMEOUT = 30.0
#: Milliseconds drawn after the load before the screenshot.
SETTLE_MS = 500
#: Chromium's switches: WebGL drawn by SwiftShader, whatever the GPU.
CHROMIUM_ARGS = ('--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                 '--ignore-gpu-blocklist')
HERE = os.path.dirname(os.path.abspath(__file__))

_TYPES = {'.x3d': 'model/x3d+xml', '.x3dv': 'model/x3d-vrml', '.x3dj': 'model/x3d+json',
          '.wrl': 'model/vrml', '.js': 'text/javascript', '.mjs': 'text/javascript',
          '.wasm': 'application/wasm', '.json': 'application/json'}


class Document(NamedTuple):
    """One document of the corpus: its name (archive and path, no suffix), its
    file, and the folder of every archive's examples, which is served"""

    name: str
    path: str
    root: str

    @property
    def slug(self) -> str:
        return self.name.replace('/', '.')


def _cache_directory() -> str:
    base = os.environ.get('XDG_CACHE_HOME') or os.environ.get('LOCALAPPDATA')
    return base or os.path.join(os.path.expanduser('~'), '.cache')


def corpus_directory() -> str:
    """Where pyvrml97 keeps the corpus: ``PYVRML97_X3D_CORPUS``, else its cache"""
    return os.environ.get('PYVRML97_X3D_CORPUS') or os.path.join(
        _cache_directory(), 'pyvrml97', 'x3d-corpus')


def examples(root: str, archive: str) -> str:
    """The folder of an archive's examples, in the tree every archive is extracted into"""
    return os.path.join(root, 'www.web3d.org', 'x3d', 'content', 'examples', archive)


def find_documents(root: str, archives: Sequence[str],
                   only: Optional[Sequence[str]] = None) -> list[Document]:
    """The non-empty ``.x3d`` documents of `archives`, by name; with `only`,
    those whose name contains one of its strings"""
    found = []
    for archive in archives:
        folder_root = examples(root, archive)
        for folder, _dirs, names in os.walk(folder_root):
            for name in names:
                path = os.path.join(folder, name)
                if not name.endswith('.x3d') or os.path.getsize(path) == 0:
                    continue
                relative = os.path.relpath(path, folder_root)[:-len('.x3d')].replace(os.sep, '/')
                document = Document('%s/%s' % (archive, relative), path,
                                    os.path.dirname(folder_root))
                if not only or any(part in document.name for part in only):
                    found.append(document)
    return sorted(found, key=lambda document: document.name)


def contain(base: str, name: str) -> str:
    """`name` under `base`, by real path; OSError where it leads out"""
    rel = urllib.parse.unquote(name)
    if os.path.isabs(rel) or urllib.parse.urlsplit(rel).scheme:
        raise OSError('Not a relative path: %r' % (name,))
    real_base = os.path.realpath(base)
    full = os.path.realpath(os.path.join(real_base, rel))
    if full != real_base and not full.startswith(real_base + os.sep):
        raise OSError('%r leaves %s' % (name, base))
    return full


def is_local(url: str, base: str) -> bool:
    """Whether `url` is on the server at `base`; the browser reaches nothing else"""
    split, home = urllib.parse.urlsplit(url), urllib.parse.urlsplit(base)
    return (split.scheme, split.netloc) == (home.scheme, home.netloc)


def write_file(path: str, data: bytes) -> None:
    """Write `data` beside `path` and rename it into place, so a run cut short
    leaves no partial file to be taken for a reference"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path + '.part', 'wb') as stream:  # noqa: OGC121 this is the staging write
        stream.write(data)
    os.replace(path + '.part', path)


def unpack(source: str, destination: str) -> str:
    """Unpack the ``package/dist`` folder of an X_ITE tarball into `destination`;
    its path

    The folder is unpacked beside its place and renamed into it whole, so an
    unpack cut short leaves no ``dist`` to be taken for a complete one.
    """
    os.makedirs(destination, exist_ok=True)
    final = os.path.join(os.path.realpath(destination), 'dist')
    staging = tempfile.mkdtemp(prefix='.dist-', dir=destination)
    try:
        root = os.path.realpath(staging)
        with tarfile.open(source, 'r:gz') as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.startswith('package/dist/'):
                    continue
                target = os.path.realpath(os.path.join(root, member.name[len('package/'):]))
                if not target.startswith(root + os.sep):
                    raise ValueError('Tarball member %r leaves %s' % (member.name, destination))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                with extracted, open(target, 'wb') as stream:  # noqa: OGC121 inside the staging folder
                    stream.write(extracted.read())
        if os.path.isdir(final):
            shutil.rmtree(final)
        os.replace(os.path.join(root, 'dist'), final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return final


def _distribution_directory(cache: Optional[str] = None) -> str:
    return os.path.join(cache or _cache_directory(), 'openglcontext-tools', 'x_ite', VERSION)


def cached_distribution(cache: Optional[str] = None) -> Optional[str]:
    """The folder of X_ITE's ``dist`` files where they were downloaded before; else None"""
    dist = os.path.join(_distribution_directory(cache), 'dist')
    return dist if os.path.exists(os.path.join(dist, 'x_ite.min.js')) else None


def distribution(cache: Optional[str] = None) -> str:
    """The folder of X_ITE's ``dist`` files, downloaded and checked once"""
    found = cached_distribution(cache)
    if found is not None:
        return found
    where = _distribution_directory(cache)
    tarball = os.path.join(where, 'x_ite.tgz')
    with urllib.request.urlopen(TARBALL_URL, timeout=300) as response:  # noqa: S310 the https constant above
        data = response.read()
    if hashlib.sha256(data).hexdigest() != TARBALL_SHA256:
        raise OSError('X_ITE %s has SHA-256 %s, not %s'
                      % (VERSION, hashlib.sha256(data).hexdigest(), TARBALL_SHA256))
    write_file(tarball, data)
    return unpack(tarball, where)


def harness_page(size: tuple[int, int]) -> str:
    """The page that loads the document its ``scene`` query names into X_ITE;
    ``window.done`` is true once loaded, ``'error'`` where it could not be"""
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


class _Handler(http.server.BaseHTTPRequestHandler):
    """Answers the harness page, X_ITE's files and the documents; nothing else"""

    def __init__(self, *args: Any, documents: str, dist: str, page: bytes, **named: Any) -> None:
        self.documents, self.dist, self.page = documents, dist, page
        super().__init__(*args, **named)

    def log_message(self, format: str, *args: Any) -> None:
        """Quiet: a run asks for thousands of files"""

    def do_GET(self) -> None:
        if self.headers.get('Host') != '%s:%d' % self.connection.getsockname()[:2]:
            # A page elsewhere that rebinds a name to 127.0.0.1 reads nothing.
            self.send_error(403)
            return
        path = urllib.parse.urlsplit(self.path).path.lstrip('/')
        if path == 'harness.html':
            self._send(self.page, 'text/html')
            return
        base, _, rest = path.partition('/')
        folder = {'x_ite': self.dist, 'scene': self.documents}.get(base)
        try:
            if folder is None or not rest:
                raise OSError(path)
            found = contain(folder, rest)
            with open(found, 'rb') as stream:
                data = stream.read()
        except (OSError, ValueError):     # ValueError: a NUL byte in the path
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
    """Serves the harness page, X_ITE and a folder of documents from 127.0.0.1"""

    def __init__(self, documents: str, dist: str, size: tuple[int, int]) -> None:
        handler = functools.partial(_Handler, documents=documents, dist=dist,
                                    page=harness_page(size).encode('utf-8'))
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.server.daemon_threads = True
        self.url = 'http://127.0.0.1:%d' % self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, name='x_ite-server',
                                        daemon=True)

    def __enter__(self) -> SceneServer:
        self._thread.start()
        return self

    def __exit__(self, kind: Optional[type[BaseException]], value: Optional[BaseException],
                 trace: Optional[TracebackType]) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join()


class Renderer:
    """Draws documents of one folder in X_ITE, in a headless Chromium"""

    def __init__(self, documents: str, dist: str, size: tuple[int, int]) -> None:
        self.size = size
        self.server = SceneServer(documents, dist, size)

    def __enter__(self) -> Renderer:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415 uv run supplies it
        self.server.__enter__()
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(args=list(CHROMIUM_ARGS))
        width, height = self.size
        self._page = self._browser.new_page(viewport={'width': width, 'height': height})
        self._page.route(lambda url: not is_local(url, self.server.url),
                         lambda route: route.abort())
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

    @property
    def version(self) -> str:
        return str(self._browser.version)

    def render(self, relative: str, out: str) -> dict[str, Any]:
        """Draw the document at `relative` in the folder into the PNG `out`:
        ``ok``, the ``errors`` the page reported, and ``seconds``"""
        self._errors.clear()
        start = time.monotonic()
        scene = 'scene/' + urllib.parse.quote(relative.replace(os.sep, '/'))
        try:
            self._page.goto('%s/harness.html?scene=%s' % (self.server.url, scene))
            self._page.wait_for_function('window.done', timeout=LOAD_TIMEOUT * 1000)
            loaded = self._page.evaluate('window.done')
            self._page.wait_for_timeout(SETTLE_MS)
            write_file(out, self._page.locator('#canvas').screenshot())
        except Exception as error:
            return {'ok': False, 'errors': list(self._errors) + [str(error).splitlines()[0]],
                    'seconds': time.monotonic() - start}
        errors = list(self._errors)
        if loaded == 'error':
            errors.append('X_ITE could not load the document')
        return {'ok': os.path.exists(out), 'errors': errors[:20],
                'seconds': time.monotonic() - start}


def ensure_browser() -> None:
    """Install Playwright's headless Chromium where it is missing"""
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium-headless-shell'],
                   check=True)


class Outcome(NamedTuple):
    """What a run drew: how many documents, and the names of those that failed"""

    drawn: int
    failed: list[str]


def default_jobs() -> int:
    """Browsers at a time: a quarter of the processors, as SwiftShader draws
    each browser's frames on threads of its own"""
    return max(1, (os.cpu_count() or 1) // 4)


def render_all(documents: Sequence[Document], out_dir: str, size: tuple[int, int],
               jobs: int, refresh: bool = False) -> Outcome:
    """Draw each document without a reference in `out_dir` (each, with `refresh`),
    `jobs` browsers at a time, installing the browser where something is to
    be drawn"""
    wanted = [document for document in documents
              if refresh or not os.path.exists(os.path.join(out_dir, document.slug + '.png'))]
    if not wanted:
        return Outcome(0, [])
    ensure_browser()
    dist = distribution()
    os.makedirs(out_dir, exist_ok=True)
    by_root: dict[str, list[Document]] = {}
    for document in wanted:
        by_root.setdefault(document.root, []).append(document)
    failed: list[str] = []

    def draw(root: str, share: Sequence[Document]) -> None:
        with Renderer(root, dist, size) as renderer:
            for document in share:
                out = os.path.join(out_dir, document.slug + '.png')
                report = renderer.render(os.path.relpath(document.path, root), out)
                record = dict(report, scene=document.name, x_ite=VERSION,
                              chromium=renderer.version, size=list(size),
                              rendered_at=datetime.datetime.now().isoformat(timespec='seconds'))
                write_file(os.path.join(out_dir, document.slug + '.json'),
                           json.dumps(record, indent=2).encode('utf-8'))
                if not report['ok']:
                    failed.append(document.name)
                print('  %-5s %s' % ('OK' if report['ok'] else 'FAIL', document.name), flush=True)

    workers = max(1, jobs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(draw, root, share[index::workers])
                   for root, share in by_root.items() for index in range(workers)
                   if share[index::workers]]
        for future in futures:
            future.result()
    return Outcome(len(wanted), sorted(failed))


def default_out_dir() -> str:
    return os.path.join(os.path.dirname(HERE), 'tests', 'reference_images', 'x3d_xite')


def _parse_size(text: str) -> tuple[int, int]:
    width, _, height = text.lower().partition('x')
    return (int(width), int(height))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--corpus', default=None, metavar='DIR',
                        help="the corpus directory (default: pyvrml97's, "
                        '$PYVRML97_X3D_CORPUS or its cache)')
    parser.add_argument('--archive', action='append', metavar='NAME',
                        help='an archive under the corpus to draw (repeatable; default %s)'
                        % ' and '.join(DEFAULT_ARCHIVES))
    parser.add_argument('--only', action='append', metavar='PART',
                        help='draw only the documents whose name contains PART (repeatable)')
    parser.add_argument('--out', default=None, metavar='DIR',
                        help='where the references are written '
                        '(default: tests/reference_images/x3d_xite)')
    parser.add_argument('--refresh', action='store_true',
                        help='draw again the documents that already have a reference')
    parser.add_argument('--jobs', type=int, default=default_jobs(), metavar='N',
                        help='browsers at a time (default: a quarter of the processors, %(default)s)')
    parser.add_argument('--size', type=_parse_size, default=DEFAULT_SIZE, metavar='WxH',
                        help='the size of each render (default: %dx%d, as Web3D renders)'
                        % DEFAULT_SIZE)
    options = parser.parse_args(argv)
    root = options.corpus or corpus_directory()
    documents = find_documents(root, options.archive or DEFAULT_ARCHIVES, options.only)
    if not documents:
        print('No X3D documents in %s; oglc-x3d-regression --fetch downloads the corpus' % root)
        return 2
    out_dir = options.out or default_out_dir()
    outcome = render_all(documents, out_dir, options.size, options.jobs, options.refresh)
    print('%d of %d documents drawn into %s' % (outcome.drawn, len(documents), out_dir))
    if outcome.failed:
        print('%d of %d documents failed' % (len(outcome.failed), outcome.drawn))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
