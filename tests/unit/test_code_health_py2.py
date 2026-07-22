"""Code-health guards.

7b: the Python-2 dict-iterator methods `.iteritems()`/`.itervalues()` raise
    AttributeError on Python 3 (a latent crash whenever the code path runs).
7a: bare `except:` swallows KeyboardInterrupt/SystemExit; the narrowed sites now
    use `except Exception:`.

These are source-level guards so a remnant can't creep back in.
"""
import os

import pytest

from OpenGLContext.testing.paths import tests_root
ROOT = str(tests_root(__file__).parent)
PKG = os.path.join(ROOT, 'OpenGLContext')


def _py_files():
    for dirpath, _dirs, files in os.walk(PKG):
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(dirpath, f)


def test_no_iteritems_itervalues_iterkeys_in_library():
    offenders = []
    for path in _py_files():
        src = open(path, encoding='utf-8', errors='replace').read()
        for token in ('.iteritems()', '.itervalues()', '.iterkeys()'):
            if token in src:
                offenders.append((os.path.relpath(path, ROOT), token))
    assert not offenders, "Python-2 dict iterators remain: %s" % offenders


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
