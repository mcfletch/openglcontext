"""The git tags that record what each content bundle was built from.

A bundle is one archive a release command builds. Each is published under a
tag of its own, ``content-<archive>-v<N>``, so the bundles of one application
are released on separate schedules and a rebuilt bundle takes the next number
rather than replacing a file somebody has already downloaded. The tag is an
annotated git tag on the commit the bundle was built from, and its message
records the archive's name, digest and size and the command that built it:
checking out the tag and running that command rebuilds the bundle.

    >>> from OpenGLContext.contentpacks import bundletags
    >>> bundletags.next_tag('textures', ['content-textures-v1'])
    'content-textures-v2'
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable, Sequence

__all__ = ['BundleRepository', 'PREFIX', 'is_bundle_tag', 'latest_tag',
           'next_tag', 'refusal', 'tag_prefix']

#: What every bundle tag starts with, which keeps them apart from the tags
#: that release the code.
PREFIX = 'content-'

#: The most uncommitted files a refusal names.
_SHOWN = 5

_BUNDLE_TAG = re.compile(re.escape(PREFIX) + r'.+-v[0-9]+')


def tag_prefix(bundle: str) -> str:
    """What the tags of ``bundle`` start with: ``content-<bundle>-v``."""
    return '%s%s-v' % (PREFIX, bundle)


def is_bundle_tag(tag: str) -> bool:
    """Whether ``tag`` is named the way a bundle's tag is.

    A tag that is not -- the single ``content-v1`` every bundle of an
    application once shared -- names a release that already exists, and is
    kept as it is.
    """
    return _BUNDLE_TAG.fullmatch(tag) is not None


def _version(tag: str, bundle: str) -> int | None:
    """The number in ``bundle``'s ``tag``; None for any other tag."""
    prefix = tag_prefix(bundle)
    if not tag.startswith(prefix):
        return None
    number = tag[len(prefix):]
    return int(number) if re.fullmatch(r'[0-9]+', number) else None


def latest_tag(bundle: str, taken: Iterable[str]) -> str | None:
    """The highest-numbered tag of ``bundle`` among ``taken``; None if it has none."""
    versions = [version for tag in taken
                if (version := _version(tag, bundle)) is not None]
    return '%s%d' % (tag_prefix(bundle), max(versions)) if versions else None


def next_tag(bundle: str, taken: Iterable[str]) -> str:
    """The tag after the highest of ``bundle``'s among ``taken``; ``-v1`` if it has none."""
    versions = [version for tag in taken
                if (version := _version(tag, bundle)) is not None]
    return '%s%d' % (tag_prefix(bundle), max(versions, default=0) + 1)


class BundleRepository:
    """The git repository a release command's application lives in.

    Every operation runs ``git`` in that repository and raises ``IOError``
    with what ``git`` said when it fails. ``remote`` is where :meth:`push`
    sends tags.
    """

    def __init__(self, root: str, remote: str = 'origin') -> None:
        self.root = root
        self.remote = remote

    @classmethod
    def containing(cls, directory: str,
                   remote: str = 'origin') -> BundleRepository | None:
        """The repository ``directory`` is in; None if it is in none."""
        try:
            found = subprocess.run(
                ['git', '-C', directory, 'rev-parse', '--show-toplevel'],
                capture_output=True, text=True, check=False)
        except (FileNotFoundError, NotADirectoryError):
            return None
        root = found.stdout.strip()
        if found.returncode != 0 or not root:
            return None
        return cls(os.path.realpath(root), remote)

    def tags(self) -> list[str]:
        """Every bundle tag this clone has."""
        return self._git('tag', '--list', PREFIX + '*').split()

    def uncommitted(self, ignoring: Iterable[str] = ()) -> list[str]:
        """The tracked files that differ from the last commit, as absolute paths.

        ``ignoring`` names files that are outputs of the release command, such
        as the registry it writes, which do not count.
        """
        skipped = {os.path.realpath(path) for path in ignoring}
        listed = self._git('diff', '--name-only', '-z', 'HEAD', '--')
        paths = (os.path.join(self.root, name)
                 for name in listed.split('\0') if name)
        return [path for path in paths if os.path.realpath(path) not in skipped]

    def annotate(self, tag: str, message: str) -> None:
        """Make ``tag`` an annotated tag at the last commit, saying ``message``."""
        self._git('tag', '--annotate', '--message', message, tag)

    def push(self, tags: Sequence[str]) -> None:
        """Send ``tags`` to the remote; a tag it already holds is left as it is."""
        if tags:
            self._git('push', self.remote,
                      *('refs/tags/%s' % (tag,) for tag in tags))

    def _git(self, *arguments: str) -> str:
        try:
            done = subprocess.run(['git', '-C', self.root, *arguments],
                                  capture_output=True, text=True, check=False)
        except FileNotFoundError as error:
            raise IOError('git is not installed, and the tags that record a '
                          'bundle are made with it') from error
        if done.returncode != 0:
            raise IOError('git %s failed (exit %d): %s'
                          % (arguments[0], done.returncode,
                             (done.stderr or done.stdout).strip()))
        return done.stdout


def refusal(repository: BundleRepository | None, directory: str,
            ignoring: Iterable[str] = ()) -> str | None:
    """Why a bundle built here cannot be tagged; None when it can.

    The tag records the commit a bundle is rebuilt from, so the tracked files
    must be the commit's own.
    """
    if repository is None:
        return ('%s is not in a git repository, so the bundles built from it '
                'cannot be tagged' % (directory,))
    changed = repository.uncommitted(ignoring)
    if not changed:
        return None
    names = ', '.join(os.path.relpath(path, repository.root)
                      for path in changed[:_SHOWN])
    more = len(changed) - _SHOWN
    return ('%s has uncommitted changes (%s%s); a bundle tag records the '
            'commit it is rebuilt from, so commit them first'
            % (repository.root, names, ', and %d more' % more if more > 0 else ''))
