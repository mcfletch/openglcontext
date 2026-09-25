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
registry should say about it; everything below is the same in all of them.
"""

from __future__ import annotations

import logging
import os
import subprocess
import urllib.parse
from typing import Callable, Sequence

from . import archive
from .pack import ContentPack
from .store import CONTENT_OVERRIDE, ContentStore

log = logging.getLogger(__name__)

__all__ = ['GITHUB', 'built', 'install', 'push', 'repository']

#: The command a release is attached with. GitHub's own, which knows where the
#: credentials are kept; nothing here handles a token.
GITHUB = 'gh'

#: What ``run`` is: a command line, run to completion, its exit status back.
Runner = Callable[[Sequence[str]], int]


def built(pack: ContentPack, archives: str) -> str:
    """Where ``pack``'s archive is in ``archives``.

    The file name is the registry's own -- the last segment of the URL it will
    be fetched from -- so what is installed here is what will be served there,
    and a pack whose archive was never built is a missing file rather than
    something quietly skipped.
    """
    return os.path.join(archives,
                        urllib.parse.urlparse(pack.url).path.rsplit('/', 1)[-1])


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
         run: Runner | None = None) -> None:
    """Attach ``paths`` to ``repository``'s release at ``tag``.

    The tag carries content and nothing else, so the first push creates the
    release and every later one replaces the assets on it -- a rebuilt pack
    takes the name the registry fetches, rather than arriving beside it as a
    second file nothing looks at.
    """
    runner = run if run is not None else _run
    where = ['--repo', repository]
    try:
        # --json so an existing release answers with one line rather than with
        # its whole body: this asks whether the tag is there, not what is on it.
        if runner([GITHUB, 'release', 'view', tag, *where, '--json', 'id']) != 0:
            log.info('creating the release at %s', tag)
            status = runner([GITHUB, 'release', 'create', tag, *paths, *where,
                             '--title', title or tag,
                             '--notes', notes or 'Content for %s.' % (tag,)])
        else:
            log.info('uploading %d files to %s', len(paths), tag)
            status = runner([GITHUB, 'release', 'upload', tag, *paths, *where,
                             '--clobber'])
    except FileNotFoundError as error:
        raise IOError('%s is not installed, and it is what a release is '
                      'attached with: see https://cli.github.com/'
                      % (GITHUB,)) from error
    if status != 0:
        raise IOError('%s exited %d; nothing was attached to %s'
                      % (GITHUB, status, tag))


def _run(argv: Sequence[str]) -> int:
    """Run ``argv`` to completion, its output going where ours does."""
    return subprocess.call(list(argv))
