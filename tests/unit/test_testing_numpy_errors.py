"""The plugin's ``numpy_errors`` setting holds each test to one floating-point error action."""
import subprocess
import sys
import textwrap

import pytest

from OpenGLContext.testing.plugin import numpy_errors

DIVIDES = textwrap.dedent('''
    import numpy as np

    def test_divides_by_zero():
        assert np.isinf(np.array([1.0]) / np.array([0.0]))[0]
''')


class _Config:
    def __init__(self, option=None, ini=''):
        self.option, self.ini = option, ini

    def getoption(self, name, default=None):
        return self.option

    def getini(self, name):
        return self.ini


def test_the_command_line_outranks_the_ini_setting():
    assert numpy_errors(_Config('warn', 'raise')) == 'warn'
    assert numpy_errors(_Config(None, ' raise ')) == 'raise'
    assert numpy_errors(_Config(None, '')) is None


def test_an_action_numpy_has_not_is_refused():
    with pytest.raises(ValueError, match='explode'):
        numpy_errors(_Config(None, 'explode'))


def _run(tmp_path, *options):
    (tmp_path / 'test_divides.py').write_text(DIVIDES)
    return subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
         '-p', 'OpenGLContext.testing.plugin', '--rootdir', str(tmp_path),
         '-c', '/dev/null', *options, str(tmp_path)],
        capture_output=True, text=True, timeout=300)


def test_raise_makes_a_division_by_zero_fail_the_test(tmp_path):
    done = _run(tmp_path, '-o', 'numpy_errors=raise')
    assert done.returncode == 1, done.stdout[-2000:]
    assert 'FloatingPointError' in done.stdout


def test_unset_leaves_numpy_as_it_was(tmp_path):
    done = _run(tmp_path, '-W', 'ignore::RuntimeWarning')
    assert done.returncode == 0, done.stdout[-2000:]
