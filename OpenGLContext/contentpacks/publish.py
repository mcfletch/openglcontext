"""Getting a content pack from a build directory to where it can be fetched.

The reading side of this package asks "is it here, and if not, fetch it". This
is the other end of the same story, for whoever builds the content: install
what was just built into this machine's own store so the application can be
driven against it, and attach the same files to the release the registry's URLs
already name.

Every archive is released under a tag of its own, ``content-<archive>-v<N>``
(:mod:`~OpenGLContext.contentpacks.bundletags`), so an application's bundles
are published on separate schedules. An archive whose digest is the shipped
registry's keeps that registry's tag; one that differs takes the next number.
When the shipped registry is written the new tags are made in the
application's git repository, annotated, on the commit the archives were built
from; ``--push`` sends them to the remote before it makes the releases.

:func:`install` is what makes a content release testable before it is a
release. It leaves exactly what a download would leave -- the digest checked,
the unpacking bounded, the content in the directory a first run looks in -- with
only the transfer left out, because the file is already on this disk.

    >>> from OpenGLContext.contentpacks import publish
    >>> publish.install(pack, store, 'dist/content')        # doctest: +SKIP
    >>> publish.push('mcfletch/glisteel',                   # doctest: +SKIP
    ...              'content-glisteel-ashdown-v1',
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
import shlex
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

from . import archive, bundletags, catalog
from .pack import ContentPack
from .store import CONTENT_OVERRIDE, ContentStore

log = logging.getLogger(__name__)

__all__ = ['Build', 'Built', 'GITHUB', 'Release', 'built', 'bundle_registry',
           'fresh_directory', 'install', 'main', 'missing_assets', 'push',
           'release_tag', 'repository']

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


def _release_asset(url: str) -> list[str]:
    """The path segments of a GitHub release-asset URL."""
    parts = urllib.parse.urlparse(url)
    path = parts.path.strip('/').split('/')
    if parts.netloc.lower() not in ('github.com', 'www.github.com') \
            or len(path) < 6 or path[2] != 'releases' or path[3] != 'download':
        raise ValueError('%s is not a GitHub release asset, so there is no '
                         'repository to attach one to' % (url,))
    return path


def repository(url: str) -> str:
    """The ``owner/name`` a release-asset URL belongs to.

    Read off the registry's own URL rather than named a second time: a pack
    fetched from a repository is published to that repository, and two places
    saying so is one place to be wrong.
    """
    path = _release_asset(url)
    return '%s/%s' % (path[0], path[1])


def release_tag(url: str) -> str:
    """The tag a release-asset URL is served from."""
    return urllib.parse.unquote(_release_asset(url)[4])


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
        raise IOError(_NO_GITHUB_CLI) from error
    if status != 0:
        raise IOError('%s exited %d; nothing was attached to %s'
                      % (GITHUB, status, tag))


def missing_assets(repository: str, tag: str, paths: Sequence[str],
                   ask: Asker | None = None) -> list[str]:
    """The ``paths`` whose file names ``repository``'s release at ``tag`` lacks.

    All of them where the tag has no release. Only the names are compared; the
    digest of a file already attached is the registry's to vouch for, which
    ``tools/publish-content.py`` checks.
    """
    asker = ask if ask is not None else _ask
    try:
        found, said = asker([GITHUB, 'release', 'view', '--repo', repository,
                             '--json', 'assets', '--', tag])
    except FileNotFoundError as error:
        raise IOError(_NO_GITHUB_CLI) from error
    if found != 0:
        if _NOT_FOUND in said.lower():
            return list(paths)
        raise IOError('%s could not say what %s carries at %s (exit %d): %s'
                      % (GITHUB, repository, tag, found, said.strip()))
    document = parse_object(said.encode('utf-8'), 'gh release view')
    attached = {require_object(one, 'gh release asset').get('name')
                for one in require_array(document.get('assets') or [],
                                         'gh release assets')}
    return [path for path in paths if os.path.basename(path) not in attached]


class Built(NamedTuple):
    """One archive a build wrote: its path, its size in bytes, its digest."""
    path: str
    size: int
    sha256: str

    @property
    def name(self) -> str:
        """The archive's file name without its extension, which names its tag."""
        return os.path.basename(self.path).removesuffix('.tar.gz')


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

    The tag in each entry's URL is the archive's own
    (:mod:`~OpenGLContext.contentpacks.bundletags`). ``remote`` is the git
    remote the tags are pushed to.

    ``keep_unbuilt`` keeps the shipped registry's other entries -- packs this
    command does not build, such as other people's packages -- and replaces
    only those it built. ``bundle`` also writes the registry and its preview
    pictures as one zip, released under a tag of its own. ``store`` opens the
    store ``--install`` writes into, ``ContentStore(namespace)`` if not given.
    ``arguments`` adds options of the application's own to the parser.
    """
    namespace: str
    url: str
    catalog: str
    declare: Callable[['Build'], list[dict[str, Any]]]
    into: str
    title: str = ''
    notes: str = ''
    description: str = ''
    remote: str = 'origin'
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
    including anything :attr:`Release.arguments` added. ``repository`` is the
    git repository the application is in, None where it is in none.
    """

    def __init__(self, release: Release, into: str,
                 options: argparse.Namespace,
                 repository: bundletags.BundleRepository | None = None
                 ) -> None:
        self.release = release
        self.into = into
        self.options = options
        self.repository = repository
        #: Every archive written so far, in order.
        self.archives: list[Built] = []
        self._tags: dict[str, str] = {}
        self._shipped = _shipped_tags(release.catalog)

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

    def tag_for(self, built: Built) -> str:
        """The tag ``built`` is released under.

        The tag the shipped registry names for this file when its digest is
        the registry's, since those are the bytes already released; otherwise
        the number after the highest this bundle has in the repository and in
        the registry.
        """
        if built.path not in self._tags:
            shipped = self._shipped.get(os.path.basename(built.path))
            if shipped is not None and shipped[1] == built.sha256:
                tag = shipped[0]
            else:
                taken = [tag for tag, _digest in self._shipped.values()]
                if self.repository is not None:
                    taken.extend(self.repository.tags())
                tag = bundletags.next_tag(built.name, taken)
            self._tags[built.path] = tag
        return self._tags[built.path]

    def untagged(self) -> list[tuple[Built, str]]:
        """The archives built so far whose tag is not yet in the repository."""
        if self.repository is None:
            return []
        existing = set(self.repository.tags())
        return [(made, self.tag_for(made)) for made in self.archives
                if bundletags.is_bundle_tag(self.tag_for(made))
                and self.tag_for(made) not in existing]

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
            'url': self.release.url % (self.tag_for(built),
                                       os.path.basename(built.path)),
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
    ``--push`` attaches each archive to the release at its own tag and writes
    the shipped registry, since the releases then serve what it describes.
    Writing the shipped registry makes the annotated git tags of the archives
    that are new and needs the application's tracked files committed, since a
    tag names the commit its archive is rebuilt from; a command that cannot
    tag exits 2 before it builds anything. ``run`` and ``ask`` are handed to
    :func:`push`.
    """
    options = _parser(release).parse_args(argv)
    into = os.path.abspath(options.into)
    shipped = options.push or options.write_registry
    clone = bundletags.BundleRepository.containing(
        os.path.dirname(os.path.abspath(release.catalog)), release.remote)
    if shipped:
        refused = bundletags.refusal(
            clone, os.path.dirname(os.path.abspath(release.catalog)),
            ignoring=[release.catalog])
        if refused is not None:
            print(refused, file=sys.stderr)
            return 2
    os.makedirs(into, exist_ok=True)
    build = Build(release, into, options, clone)
    try:
        entries = release.declare(build)
    except SystemExit as refused_build:
        print(refused_build, file=sys.stderr)
        return 2
    document = _document(release, entries)
    text = json.dumps(document, indent=1) + '\n'
    local = os.path.join(into, catalog.MANIFEST)
    atomicfiles.write_text(local, text)
    catalog.load(local)
    pending = build.untagged()
    registry_tag = _registry_tag(
        release, clone, fresh=bool(pending) or _differs(release.catalog, text))
    command = shlex.join([os.path.basename(sys.argv[0]), *(
        argv if argv is not None else sys.argv[1:])])
    if shipped and clone is not None:
        _tag_bundles(clone, pending, command, registry_tag)
        atomicfiles.write_text(release.catalog, text)
    for one in entries:
        print('  %-28s %6.1f MB  %s' % (one['key'],
                                        one['approximate_bytes'] / 1048576,
                                        one['sha256'][:12]))
    print('registry written to %s%s' % (
        local, ' and %s' % (release.catalog,) if shipped else ''))
    attached: dict[str, list[str]] = {}
    for made in build.archives:
        attached.setdefault(build.tag_for(made), []).append(made.path)
    if registry_tag is not None:
        bundle = bundle_registry(
            local, os.path.join(into, '%s-registry.zip' % (release.namespace,)),
            pictures=os.path.dirname(os.path.abspath(release.catalog)))
        print('registry bundle: %s (%.0f KB)' % (
            os.path.basename(bundle), os.path.getsize(bundle) / 1024))
        attached.setdefault(registry_tag, []).append(bundle)
    if options.install or options.reinstall:
        _install_built(release, local, entries, into, options.reinstall)
    if options.push and clone is not None:
        _publish(release, clone, attached, run, ask)
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
    parser.add_argument('--into', default=release.into,
                        help='where to write the archives and the registry '
                             'that describes them (default: %(default)s)')
    parser.add_argument('--write-registry', action='store_true',
                        help='also write the registry the application ships '
                             '(%s) and tag the archives that are new; --push '
                             'does this too' % (release.catalog,))
    parser.add_argument('--install', action='store_true',
                        help="install what was built into this machine's own "
                             'store, so the application runs against it with '
                             'nothing published; a pack already installed is '
                             'kept')
    parser.add_argument('--reinstall', action='store_true',
                        help='install what was built, replacing what the store '
                             'already holds under each key')
    parser.add_argument('--push', action='store_true',
                        help='attach each archive to the release at its own '
                             'tag, creating it if it is not there yet, and '
                             'write the shipped registry (needs the GitHub '
                             'CLI and an account that may write to the '
                             'repository)')
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

_NO_GITHUB_CLI = ('%s is not installed, and it is what a release is attached '
                  'with: see https://cli.github.com/' % (GITHUB,))


def _shipped_tags(path: str) -> dict[str, tuple[str, str]]:
    """The tag and digest the registry at ``path`` gives each archive file.

    Entries that are not GitHub release assets, such as other people's
    packages, are left out. A registry that is not there gives nothing.
    """
    if not os.path.isfile(path):
        return {}
    with open(path, 'rb') as handle:
        document = parse_object(handle.read(), path)
    found: dict[str, tuple[str, str]] = {}
    for one in _entries(document, path):
        url, digest = one.get('url'), one.get('sha256')
        if not isinstance(url, str) or not isinstance(digest, str):
            continue
        try:
            tag = release_tag(url)
        except ValueError:
            continue
        found[urllib.parse.urlparse(url).path.rsplit('/', 1)[-1]] = (tag,
                                                                     digest)
    return found


def _differs(path: str, text: str) -> bool:
    """Whether the file at ``path`` is not ``text``; true where it is not there."""
    if not os.path.isfile(path):
        return True
    with open(path, encoding='utf-8') as handle:
        return handle.read() != text


def _registry_tag(release: Release, clone: bundletags.BundleRepository | None,
                  fresh: bool) -> str | None:
    """The tag the registry bundle is released under; None where there is none.

    A registry that differs from the shipped one, or that describes a new
    archive, is a new bundle. Otherwise the newest tag is the one it is
    already released under.
    """
    if not release.bundle:
        return None
    name = '%s-registry' % (release.namespace,)
    taken = clone.tags() if clone is not None else []
    newest = bundletags.latest_tag(name, taken)
    if newest is not None and not fresh:
        return newest
    return bundletags.next_tag(name, taken)


def _message(subject: str, filename: str, command: str,
             built: Built | None = None) -> str:
    """The note an annotated tag carries: what was built, and how to build it again."""
    lines = [subject, '', '- archive: %s' % (filename,)]
    if built is not None:
        lines += ['- sha256: %s' % (built.sha256,), '- bytes: %d' % (built.size,)]
    lines.append('- built with: %s' % (command,))
    return '\n'.join(lines)


def _tag_bundles(clone: bundletags.BundleRepository,
                 pending: list[tuple[Built, str]], command: str,
                 registry_tag: str | None) -> None:
    """Make the annotated tag of each archive in ``pending``, and the registry's.

    The tag is on the commit the archives were built from, which is the last
    commit: the tracked files were committed before the build started.
    """
    for made, tag in pending:
        clone.annotate(tag, _message('%s content bundle' % (made.name,),
                                     os.path.basename(made.path), command, made))
        print('tagged %s' % (tag,))
    if registry_tag is not None and registry_tag not in clone.tags():
        clone.annotate(registry_tag, _message(
            'registry bundle', registry_tag.rsplit('-v', 1)[0] + '.zip', command))
        print('tagged %s' % (registry_tag,))


def _publish(release: Release, clone: bundletags.BundleRepository,
             attached: dict[str, list[str]], run: Runner | None,
             ask: Asker | None) -> None:
    """Send the tags to the remote, then attach each tag's files to its release.

    The tags go first: ``gh release create`` makes a tag that is not on the
    remote as a plain one at the head of the default branch. Files a release
    already carries are not sent again.
    """
    held = set(clone.tags())
    clone.push([tag for tag in attached if tag in held])
    for tag, paths in attached.items():
        where = repository(release.url % (tag, 'x'))
        absent = missing_assets(where, tag, paths, ask=ask)
        if not absent:
            print('%s already carries %d files' % (tag, len(paths)))
            continue
        push(where, tag, absent,
             title='%s %s' % (release.title or release.namespace, tag),
             notes=release.notes or None, run=run, ask=ask)
        print('attached %d files to %s' % (len(absent), tag))


def _run(argv: Sequence[str]) -> int:
    """Run ``argv`` to completion, its output going where ours does."""
    return subprocess.call(list(argv))


def _ask(argv: Sequence[str]) -> tuple[int, str]:
    """Run ``argv`` to completion; its status, and its output and errors."""
    done = subprocess.run(list(argv), capture_output=True, text=True,
                          check=False)
    return done.returncode, (done.stdout or '') + (done.stderr or '')
