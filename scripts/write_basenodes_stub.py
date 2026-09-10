#! /usr/bin/env python
"""Write ``OpenGLContext/scenegraph/basenodes.pyi`` from the node registry.

Run this after registering a node in ``OpenGLContext/__init__.py``, so that a
checker can see the new name where callers reach it::

    python scripts/write_basenodes_stub.py

``tests/unit/test_basenodes_stub.py`` fails while the file on disk disagrees
with the registrations, which is what makes running this a step rather than a
habit.  ``--check`` reports without writing, for a shell that wants the exit
status.
"""
import argparse
import sys

from OpenGLContext.scenegraph import _basenodes_stub


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        '--check', action='store_true',
        help='exit non-zero if the file is out of date, rather than writing it',
    )
    options = parser.parse_args(argv)

    path, text = _basenodes_stub.expected(_basenodes_stub.__file__)
    try:
        with open(path, encoding='utf-8') as handle:
            current = handle.read()
    except OSError:
        current = None
    if current == text:
        print('%s is up to date' % (path,))
        return 0
    if options.check:
        print('%s is out of date; run scripts/write_basenodes_stub.py' % (path,))
        return 1
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(text)
    print('wrote %s' % (path,))
    return 0


if __name__ == '__main__':
    sys.exit(main())
