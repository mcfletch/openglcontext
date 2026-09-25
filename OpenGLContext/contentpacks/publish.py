"""Getting a content pack from a build directory to where it can be fetched.

The reading side of this package asks "is it here, and if not, fetch it". This
is the other end of the same story, for whoever builds the content: install
what was just built into this machine's own store so the application can be
driven against it, and attach the same files to the release the registry's URLs
already name.

:func:`install` is what makes a content release testable before it is a
release. It leaves exactly what a download would leave -- the digest checked,
the unpacking bounded, the content in the directory a first run looks in -- with
only the transfer left out, because the file is already on this disk.

    >>> from OpenGLContext.contentpacks import publish
    >>> publish.install(pack, store, 'dist/content')        # doctest: +SKIP
    >>> publish.push('mcfletch/glisteel', 'content-v1',     # doctest: +SKIP
    ...              ['dist/content/glisteel-ashdown.tar.gz'])

An application's own ``release-assets.py`` says what to build and what the
registry should say about it, as a :class:`Release`, and hands the command
line to :func:`main`; the options, the registry, the install and the push are
the same in all of them::

    def declare(build):
        built = build.archive(ART, 'forest-art')
        return [build.entry('art', built, title='Forest demo art',
                            marker='forest_height.png', base=True,
                            copyright=CREDIT)]

    RELEASE = publish.Release(
        namespace='openglcontext-forest', declare=declare,
        url='https://github.com/mcfletch/openglcontext-forest/releases/'
            'download/%s/%s',
        catalog=CATALOG, into=os.path.join(HERE, 'dist', 'content'))

    raise SystemExit(publish.main(RELEASE))
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import urllib.parse
import zipfile
from dataclasses import dataclass
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

from OpenGLContext import atomicfiles
from OpenGLContext.loaders.documentvalues import (
    JSONObject, parse_object, require_array, require_object,
)

from . import archive, catalog
from .pack import ContentPack
from .store import CONTENT_OVERRIDE, ContentStore

log = logging.getLogger(__name__)

__all__ = ['Build', 'Built', 'GITHUB', 'Release', 'built', 'bundle_registry',
           'fresh_directory', 'install', 'main', 'push', 'repository']

#: The command a release is attached with. GitHub's own, which knows where the
#: credentials are kept; nothing here handles a token.
GITHUB = 'gh'

#: What ``run`` is: a command line, run to completion, its exit status back.
Runner = Callable[[Sequence[str]], int]

#: What ``ask`` is: a command line, run to completion, its exit status and
#: everything it printed back.
Asker = Callable[[Sequence[str]], tuple[int, str]]


def built(pack: ContentPack, archives: str) -> str:
    """Where ``pack``'s archive is in ``archives``.

    The file name is the registry's own -- the last segment of the URL it will
    be fetched from -- so what is installed here is what will be served there,
    and a pack whose archive was never built is a missing file rather than
    something quietly skipped.
    """
    return os.path.join(archives,
                        urllib.parse.urlparse(pack.url).path.rsplit('/', 1)[-1])


def fresh_directory(path: str) -> str:
    """An empty directory at ``path`` to stage a pack in; returns ``path``.

    Whatever an earlier build left there is removed first, since an archive is
    made of everything in the tree and a file the new build did not write
    would otherwise be packed, and digested, with it.
    """
    atomicfiles.remove_directory(path)
    os.makedirs(path)
    return path


def install(pack: ContentPack, store: ContentStore, archives: str,
            within: ContentPack | None = None, replace: bool = False) -> str:
    """Install a locally built pack into ``store``; its content root.

    What a fetch would have left, without the fetch: a game with this in its
    store cannot tell that no release carries it. ``within`` puts content
    another pack is incomplete without under that pack, exactly as
    :func:`~OpenGLContext.contentpacks.fetch.fetch_pack` does. A pack already
    installed is left where it is, so a run of this over a store is not a way to
    lose whatever is in one.

    ``replace`` is for the author of a world they are still building: it
    installs the build over what is installed under this key, so the next run
    of the game shows the world that was just made rather than the one before
    it. A pack of its own replaces its whole directory, including anything put
    there by hand; one installed ``within`` another replaces its own files and
    leaves the rest of that pack alone. A pack found in a directory
    ``OPENGLCONTEXT_CONTENT`` names is refused for ``replace``, since that copy
    is read before the store and a rebuilt one in the store would never open.
    """
    existing = store.root_for(pack, within)
    if existing is not None:
        if not replace:
            return existing
        if existing != store.directory_for(pack, within):
            raise IOError(
                '%s is found in %s, a directory searched before the store, so '
                'a rebuilt copy in the store would never be opened; remove it '
                'there or unset %s' % (pack.key, existing, CONTENT_OVERRIDE))
    path = built(pack, archives)
    if not os.path.isfile(path):
        raise IOError('%s: no archive for %s in %s'
                      % (os.path.basename(path), pack.key, archives))
    archive.check_digest(path, pack.sha256)
    return store.install(pack, path, within, replace=replace)


def repository(url: str) -> str:
    """The ``owner/name`` a release-asset URL belongs to.

    Read off the registry's own URL rather than named a second time: a pack
    fetched from a repository is published to that repository, and two places
    saying so is one place to be wrong.
    """
    parts = urllib.parse.urlparse(url)
    path = parts.path.strip('/').split('/')
    if parts.netloc.lower() not in ('github.com', 'www.github.com') \
            or len(path) < 3 or path[2] != 'releases':
        raise ValueError('%s is not a GitHub release asset, so there is no '
                         'repository to attach one to' % (url,))
    return '%s/%s' % (path[0], path[1])


def push(repository: str, tag: str, paths: Sequence[str],
         title: str | None = None, notes: str | None = None,
         run: Runner | None = None, ask: Asker | None = None) -> None:
    """Attach ``paths`` to ``repository``'s release at ``tag``.

    The tag carries content and nothing else, so the first push creates the
    release and every later one replaces the assets on it -- a rebuilt pack
    takes the name the registry fetches, rather than arriving beside it as a
    second file nothing looks at.

    Whether the release exists is asked first, and only ``gh``'s own "release
    not found" is taken for no: any other failure to ask (credentials, the
    network) is raised with what ``gh`` said. The tag and the paths follow a
    ``--``, and the paths are made absolute, so neither is read as an option.
    ``run`` runs a command for its status and ``ask`` for its status and
    output; both default to running ``gh`` itself.
    """
    runner = run if run is not None else _run
    asker = ask if ask is not None else _ask
    where = ['--repo', repository]
    files = [os.path.abspath(path) for path in paths]
    try:
        # --json so an existing release answers with one line rather than with
        # its whole body: this asks whether the tag is there, not what is on it.
        found, said = asker([GITHUB, 'release', 'view', *where, '--json', 'id',
                             '--', tag])
        if found == 0:
            log.info('uploading %d files to %s', len(files), tag)
            status = runner([GITHUB, 'release', 'upload', *where, '--clobber',
                             '--', tag, *files])
        elif _NOT_FOUND in said.lower():
            log.info('creating the release at %s', tag)
            status = runner([GITHUB, 'release', 'create', *where,
                             '--title', title or tag,
                             '--notes', notes or 'Content for %s.' % (tag,),
                             '--', tag, *files])
        else:
            raise IOError('%s could not say whether %s has a release at %s '
                          '(exit %d): %s' % (GITHUB, repository, tag, found,
                                             said.strip()))
    except FileNotFoundError as error:
        raise IOError('%s is not installed, and it is what a release is '
                      'attached with: see https://cli.github.com/'
                      % (GITHUB,)) from error
    if status != 0:
        raise IOError('%s exited %d; nothing was attached to %s'
                      % (GITHUB, status, tag))


class Built(NamedTuple):
    """One archive a build wrote: its path, its size in bytes, its digest."""
    path: str
    size: int
    sha256: str


@dataclass
class Release:
    """What one application publishes, as its ``release-assets.py`` states it.

    ``declare`` builds the archives and returns the registry's entries for
    them; it is handed a :class:`Build` and may raise ``SystemExit`` with a
    message to refuse (the command then exits 2 with the message). ``url`` is
    the release-asset URL with ``%s`` for the tag and ``%s`` for the file name.
    ``catalog`` is the registry the application ships, which a build writes
    only when asked to (``--write-registry``) or when it pushes; every build
    writes its registry beside the archives in ``into``, and ``--install``
    reads that one.

    ``keep_unbuilt`` keeps the shipped registry's other entries -- packs this
    command does not build, such as other people's packages -- and replaces
    only those it built. ``bundle`` also writes the registry and its preview
    pictures as one zip, attached with the archives. ``store`` opens the store
    ``--install`` writes into, ``ContentStore(namespace)`` if not given.
    ``arguments`` adds options of the application's own to the parser.
    """
    namespace: str
    url: str
    catalog: str
    declare: Callable[['Build'], list[dict[str, Any]]]
    into: str
    tag: str = 'content-v1'
    title: str = ''
    notes: str = ''
    description: str = ''
    keep_unbuilt: bool = False
    bundle: bool = False
    store: Callable[[], ContentStore] | None = None
    arguments: Callable[[argparse.ArgumentParser], None] | None = None

    def open_store(self) -> ContentStore:
        """The store ``--install`` writes into."""
        return self.store() if self.store is not None \
            else ContentStore(self.namespace)


class Build:
    """One run of a release command: where it writes and what it wrote.

    Handed to :attr:`Release.declare`. ``options`` is the parsed command line,
    including anything :attr:`Release.arguments` added.
    """

    def __init__(self, release: Release, tag: str, into: str,
                 options: argparse.Namespace) -> None:
        self.release = release
        self.tag = tag
        self.into = into
        self.options = options
        #: Every archive written so far, in order.
        self.archives: list[Built] = []

    def staging(self, name: str) -> str:
        """An empty directory under ``into`` to assemble a pack in."""
        return fresh_directory(os.path.join(self.into, name))

    def archive(self, directory: str, name: str) -> Built:
        """Archive ``directory`` as ``<name>.tar.gz`` in ``into``."""
        path = archive.write(directory,
                             os.path.join(self.into, '%s.tar.gz' % (name,)))
        made = Built(path, os.path.getsize(path), archive.digest(path))
        self.archives.append(made)
        return made

    def entry(self, name: str, built: Built, *, title: str, copyright: str,
              marker: str, directory: str | None = None,
              **optional: Any) -> dict[str, Any]:
        """The registry entry for an archive this build wrote.

        The key is ``<namespace>/<name>``, the directory ``name`` unless
        given, and the URL, size and digest are the archive's own. Anything
        in ``optional`` that is empty or false is left out, as the registry
        leaves out a default.
        """
        entry: dict[str, Any] = {
            'key': '%s/%s' % (self.release.namespace, name),
            'title': title,
            'url': self.release.url % (self.tag, os.path.basename(built.path)),
            'directory': directory or name,
            'archive': 'tar',
            'approximate_bytes': built.size,
            'sha256': built.sha256,
            'copyright': copyright,
            'marker': marker,
        }
        entry.update((key, value) for key, value in optional.items() if value)
        return entry


def main(release: Release, argv: Sequence[str] | None = None,
         run: Runner | None = None, ask: Asker | None = None) -> int:
    """Run a release command; its exit status.

    Builds what ``release.declare`` builds and writes the registry beside it;
    ``--write-registry`` also writes the shipped one, ``--install`` or
    ``--reinstall`` puts what was built into this machine's store, and
    ``--push`` attaches it to the release at ``--tag`` and writes the shipped
    registry, since the release then serves what it describes. ``run`` and
    ``ask`` are handed to :func:`push`.
    """
    options = _parser(release).parse_args(argv)
    into = os.path.abspath(options.into)
    os.makedirs(into, exist_ok=True)
    build = Build(release, options.tag, into, options)
    try:
        entries = release.declare(build)
    except SystemExit as refused:
        print(refused, file=sys.stderr)
        return 2
    document = _document(release, entries)
    local = os.path.join(into, catalog.MANIFEST)
    atomicfiles.write_text(local, json.dumps(document, indent=1) + '\n')
    catalog.load(local)
    shipped = options.push or options.write_registry
    if shipped:
        atomicfiles.write_text(release.catalog,
                               json.dumps(document, indent=1) + '\n')
    for one in entries:
        print('  %-28s %6.1f MB  %s' % (one['key'],
                                        one['approximate_bytes'] / 1048576,
                                        one['sha256'][:12]))
    print('registry written to %s%s' % (
        local, ' and %s' % (release.catalog,) if shipped else ''))
    attached = [one.path for one in build.archives]
    if release.bundle:
        bundle = bundle_registry(
            local, os.path.join(into, '%s-registry.zip' % (release.namespace,)),
            pictures=os.path.dirname(os.path.abspath(release.catalog)))
        print('registry bundle: %s (%.0f KB)' % (
            os.path.basename(bundle), os.path.getsize(bundle) / 1024))
        attached.append(bundle)
    if options.install or options.reinstall:
        _install_built(release, local, entries, into, options.reinstall)
    if options.push:
        push(repository(release.url % (options.tag, 'x')), options.tag,
             attached, title='%s %s' % (release.title or release.namespace,
                                        options.tag),
             notes=release.notes or None, run=run, ask=ask)
        print('attached %d files to %s' % (len(attached), options.tag))
    return 0


def bundle_registry(manifest: str, path: str, pictures: str | None = None
                    ) -> str:
    """The registry at ``manifest`` and its preview pictures as one zip at
    ``path``; returns ``path``.

    The form :func:`~OpenGLContext.contentpacks.catalog.load_bundle` reads and
    :func:`~OpenGLContext.contentpacks.fetch.fetch_registry` fetches: the
    document at the top as ``packs.json``, and each pack's ``preview`` under
    the name the entry gives it, read from ``pictures`` (the manifest's own
    directory if not given). A preview that is not there is left out.
    """
    beside = pictures or os.path.dirname(os.path.abspath(manifest))
    with open(manifest, 'rb') as handle:
        declared = parse_object(handle.read(), manifest)
    with atomicfiles.staged_file(path, 'wb') as raw:
        with zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(manifest, catalog.MANIFEST)
            for entry in _entries(declared, manifest):
                named = entry.get('preview')
                if named and os.path.isfile(os.path.join(beside, str(named))):
                    bundle.write(os.path.join(beside, str(named)), str(named))
    return path


def _parser(release: Release) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=release.description or None)
    parser.add_argument('--tag', default=release.tag,
                        help='the release tag the archives are attached to '
                             '(default: %(default)s)')
    parser.add_argument('--into', default=release.into,
                        help='where to write the archives and the registry '
                             'that describes them (default: %(default)s)')
    parser.add_argument('--write-registry', action='store_true',
                        help='also write the registry the application ships '
                             '(%s); --push does this too' % (release.catalog,))
    parser.add_argument('--install', action='store_true',
                        help="install what was built into this machine's own "
                             'store, so the application runs against it with '
                             'nothing published; a pack already installed is '
                             'kept')
    parser.add_argument('--reinstall', action='store_true',
                        help='install what was built, replacing what the store '
                             'already holds under each key')
    parser.add_argument('--push', action='store_true',
                        help='attach the archives to the release at --tag, '
                             'creating it if it is not there yet, and write '
                             'the shipped registry (needs the GitHub CLI and '
                             'an account that may write to the repository)')
    if release.arguments is not None:
        release.arguments(parser)
    return parser


def _document(release: Release,
              entries: list[dict[str, Any]]) -> dict[str, Any]:
    """The registry document for ``entries``: those alone, or with the
    shipped registry's other entries where the release keeps them."""
    if not release.keep_unbuilt or not os.path.isfile(release.catalog):
        return {'namespace': release.namespace, 'packs': list(entries)}
    with open(release.catalog, 'rb') as handle:
        document = dict(parse_object(handle.read(), release.catalog))
    built: dict[object, JSONObject] = {one['key']: one for one in entries}
    packs = [built.pop(one.get('key'), one)
             for one in _entries(document, release.catalog)]
    document['packs'] = [one for one in entries if one['key'] in built] + packs
    return document


def _entries(document: JSONObject, where: str) -> list[JSONObject]:
    """The pack entries a registry document lists."""
    return [require_object(entry, '%s pack entry' % (where,))
            for entry in require_array(document.get('packs') or [],
                                       '%s packs' % (where,))]


def _install_built(release: Release, registry: str,
                   entries: list[dict[str, Any]], into: str,
                   replace: bool) -> None:
    """Install every pack this build wrote, as a download would place it.

    Each pack a chooser offers goes in with what it needs, within it, as
    :func:`~OpenGLContext.contentpacks.fetch.wanted_for` fetches it; a pack
    only some other pack needs is installed with that pack.
    """
    store = release.open_store()
    packs = catalog.merge(catalog.load(registry))
    ours = {one['key'] for one in entries}
    print('store: %s' % (store.root,))
    for chosen in catalog.offered(packs):
        if chosen.key not in ours:
            continue
        for pack in catalog.with_needed(chosen, packs):
            where = install(pack, store, into, within=chosen, replace=replace)
            print('  %-28s %s' % (pack.key, os.path.relpath(where, store.root)))


#: What ``gh release view`` prints, lower-cased, for a tag with no release.
_NOT_FOUND = 'release not found'


def _run(argv: Sequence[str]) -> int:
    """Run ``argv`` to completion, its output going where ours does."""
    return subprocess.call(list(argv))


def _ask(argv: Sequence[str]) -> tuple[int, str]:
    """Run ``argv`` to completion; its status, and its output and errors."""
    done = subprocess.run(list(argv), capture_output=True, text=True,
                          check=False)
    return done.returncode, (done.stdout or '') + (done.stderr or '')
