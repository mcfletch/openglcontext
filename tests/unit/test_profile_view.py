"""``OpenGLContext.bin.profile_view`` profiles with PyOpenGL's error checking off.

Error checking is read from PyOpenGL's flags module the first time an API
namespace imports it, so the switch has to be thrown before that; the module is
imported in a fresh interpreter, as ``python -m`` runs it.
"""
import os
import subprocess
import sys


def test_error_checking_is_off_once_the_module_is_imported():
    environment = dict(os.environ)
    environment.pop('PYOPENGL_ERROR_CHECKING', None)
    result = subprocess.run(
        [sys.executable, '-c',
         'import OpenGLContext.bin.profile_view\n'
         'from OpenGL import _configflags\n'
         'print("checking", _configflags.ERROR_CHECKING)\n'],
        capture_output=True, text=True, env=environment, timeout=120)
    assert 'checking False' in result.stdout, result.stdout + result.stderr
