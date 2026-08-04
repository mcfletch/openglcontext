#!/usr/bin/env python
"""Refuse a release artifact that carries files the source tree no longer has.

``setuptools`` stages a build under ``build/lib`` and copies that directory into
the wheel. It never prunes it, so a module deleted from the source stays in the
staging directory and is published anyway -- and no import-level test can see it,
because the source tree is correct and only the artifact is wrong. A package
removed for a security reason can be shipped by a tree that no longer contains it.

This compares an artifact against the tree it was built from: every packaged file
must still exist in that tree. Run it on the built wheel *and* sdist before
uploading.

Usage:
    python scripts/check_release_artifact.py dist/*.whl dist/*.tar.gz
    python scripts/check_release_artifact.py --source-root . dist/OpenGLContext-3.0.0a1-py3-none-any.whl

Exits non-zero, listing the offending members, when anything is stale.
"""
from __future__ import annotations

import argparse
import os
import sys
import tarfile
import zipfile
from typing import List

#: Artifact members that legitimately have no counterpart in the source tree.
#: Wheel metadata is generated at build time; an sdist's root files are the
#: project's own (readme, licence, PKG-INFO), not packaged modules.
_GENERATED_DIR_SUFFIXES = ('.dist-info', '.egg-info')


def _members(artifact: str) -> List[str]:
    """Every file in a wheel or sdist, as paths relative to the package root.

    An sdist wraps everything in one ``name-version/`` directory; a wheel does
    not. Stripping that prefix puts both in the same terms as the source tree.
    """
    if artifact.endswith('.whl') or artifact.endswith('.zip'):
        with zipfile.ZipFile(artifact) as z:
            return [n for n in z.namelist() if not n.endswith('/')]
    with tarfile.open(artifact) as t:
        names = [m.name for m in t.getmembers() if m.isfile()]
    return [n.split('/', 1)[1] for n in names if '/' in n]


def _is_generated(name: str) -> bool:
    head = name.split('/', 1)[0]
    return any(head.endswith(suffix) for suffix in _GENERATED_DIR_SUFFIXES)


def stale_members(artifact: str, source_root: str) -> List[str]:
    """Artifact members with no counterpart in ``source_root``, sorted.

    Only files inside a top-level directory that exists in the tree are judged --
    a package. Anything at the artifact's own root (``readme.txt``, ``PKG-INFO``)
    and any generated metadata directory is left alone, since neither is a
    packaged module and neither can go stale in this way.
    """
    stale = []
    for name in _members(artifact):
        if _is_generated(name) or '/' not in name:
            continue
        package = name.split('/', 1)[0]
        if not os.path.isdir(os.path.join(source_root, package)):
            continue
        if not os.path.exists(os.path.join(source_root, name)):
            stale.append(name)
    return sorted(stale)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('artifacts', nargs='+',
                        help='wheel and/or sdist paths to check')
    parser.add_argument('--source-root', default='.',
                        help='the tree the artifacts were built from (default: .)')
    args = parser.parse_args(argv)

    failed = False
    for artifact in args.artifacts:
        stale = stale_members(artifact, args.source_root)
        if stale:
            failed = True
            print('%s carries %d file(s) the source tree no longer has:'
                  % (artifact, len(stale)))
            for name in stale:
                print('    %s' % (name,))
        else:
            print('%s: clean' % (artifact,))
    if failed:
        print('\nA stale build/ staging directory is the usual cause. '
              'Remove build/ and *.egg-info and rebuild.')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
