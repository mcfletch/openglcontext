"""``OpenGLContext.bin.profile_view`` profiles with PyOpenGL's error checking off.

Error checking is read from PyOpenGL's flags module the first time an API
namespace imports it, so the switch has to be thrown before that; each case
runs in a fresh interpreter, as ``python -m`` runs the module.
"""
import os
import subprocess
import sys


def run(code):
    environment = dict(os.environ)
    environment.pop('PYOPENGL_ERROR_CHECKING', None)
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True, text=True, env=environment, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    # PyOpenGL's report of a setting made after it was read.
    assert 'ConfigurationHasBeenRead' not in result.stderr, result.stderr
    return result.stdout


def test_the_profiled_context_has_error_checking_off():
    out = run(
        'from OpenGLContext.bin import profile_view\n'
        'profile_view.profiled_context()\n'
        'from OpenGL import _configflags\n'
        'print("checking", _configflags.ERROR_CHECKING)\n'
    )
    assert 'checking False' in out


def test_importing_the_module_configures_nothing():
    """The documentation build imports it into a process using PyOpenGL."""
    out = run(
        'from OpenGL import GL\n'
        'import OpenGLContext.bin.profile_view\n'
        'from OpenGL import _configflags\n'
        'print("checking", _configflags.ERROR_CHECKING)\n'
    )
    assert 'checking True' in out
