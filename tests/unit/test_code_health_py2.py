"""Code-health guards.

The Python-2 spellings below are not merely untidy.  Some raise the moment
their line runs -- `.iteritems()` is an AttributeError on a dict, `xrange` and
`basestring` are NameErrors -- so they are latent crashes sitting on paths
nothing has exercised.  Others are quieter and worse: `__getslice__` is never
called on Python 3, so a class that defines one to keep its own type across a
slice silently hands back a plain list instead, losing every method on it.

A bare `except:` swallows KeyboardInterrupt and SystemExit, so a hung frame
cannot be interrupted.

These are source-level guards, so a remnant cannot creep back in.
"""
import os
import re

import pytest

from OpenGLContext.testing.paths import tests_root
ROOT = str(tests_root(__file__).parent)
PKG = os.path.join(ROOT, 'OpenGLContext')


def _py_files():
    for dirpath, _dirs, files in os.walk(PKG):
        if '__pycache__' in dirpath:
            continue
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(dirpath, f)


def _offenders(pattern):
    """``(relative path, line number, line)`` per match of *pattern*."""
    found = []
    expression = re.compile(pattern)
    for path in _py_files():
        with open(path, encoding='utf-8', errors='replace') as handle:
            for number, line in enumerate(handle, 1):
                if expression.search(line):
                    found.append((os.path.relpath(path, ROOT), number, line.strip()))
    return found


def test_no_iteritems_itervalues_iterkeys_in_library():
    offenders = []
    for path in _py_files():
        src = open(path, encoding='utf-8', errors='replace').read()
        for token in ('.iteritems()', '.itervalues()', '.iterkeys()'):
            if token in src:
                offenders.append((os.path.relpath(path, ROOT), token))
    assert not offenders, "Python-2 dict iterators remain: %s" % offenders


#: Spellings that are Python 2's and nothing else, as ``(name, pattern)``.
#: A slice protocol method is the quiet one: Python 3 never calls it, so a
#: class defining `__getslice__` to keep its own type across `path[1:]` gets a
#: plain list back instead and every method on it is gone.
PY2_SPELLINGS = [
    ('__getslice__', r'\b__getslice__\b'),
    ('__setslice__', r'\b__setslice__\b'),
    ('__delslice__', r'\b__delslice__\b'),
    ('__nonzero__', r'\bdef __nonzero__\b'),
    ('__div__', r'\bdef __div__\b'),
    ('__metaclass__', r'^\s*__metaclass__\s*='),
    ('xrange', r'\bxrange\b'),
    ('basestring', r'\bbasestring\b'),
    ('has_key', r'\.has_key\s*\('),
    ('cStringIO', r'\bcStringIO\b'),
    ('Queue (the Python-2 module name)', r'^\s*import Queue\b'),
    ('time.clock', r'\btime\.clock\s*\('),
    ('string.letters', r'\bstring\.letters\b'),
    ('itertools.izip', r'\bitertools\.izip'),
    # `unicode` is `str`, and importing the alias shadows a builtin with it.
    ('the unicode alias', r'from OpenGL\._bytes import .*\bunicode\b'),
    # A version test whose answer has been settled since the 3.x floor.
    ('a Python-2 version branch', r'version_info\s*\[\s*0\s*\]\s*[=<>!]=?\s*2\b'),
]


@pytest.mark.parametrize('name,pattern', PY2_SPELLINGS,
                         ids=[name for name, _pattern in PY2_SPELLINGS])
def test_no_python_2_spellings_in_library(name, pattern):
    offenders = _offenders(pattern)
    assert not offenders, '%s remains:\n%s' % (
        name, '\n'.join('  %s:%s  %s' % row for row in offenders))


NARROWED = [
    'OpenGLContext/visitor.py',
    'OpenGLContext/scenegraph/text/wglfont.py',
    'OpenGLContext/scenegraph/text/pygamefont.py',
    'OpenGLContext/glfwinteractivecontext.py',
    'OpenGLContext/scenegraph/text/font.py',
]


@pytest.mark.parametrize('rel', NARROWED)
def test_no_bare_except_in_narrowed_files(rel):
    import re
    src = open(os.path.join(ROOT, rel)).read()
    bare = re.findall(r'^[ \t]*except:[ \t]*$', src, re.MULTILINE)
    assert not bare, "%s still has a bare except:" % rel
