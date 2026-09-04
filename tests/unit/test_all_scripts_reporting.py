"""What the script harness says when a script asks to be skipped.

A script exits with ``REQUIRED_EXTENSION_MISSING`` to say the driver has not got
the extension it exists to exercise.  The harness turns that into a skip, and
the skip message is what a reader has to work from.
"""

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tests'))
try:
    import test_all_scripts
finally:
    sys.path.pop(0)


class TestTheSkipMessage:
    @pytest.mark.parametrize(
        'stdout,expected',
        [
            pytest.param(
                'checking\nGL_ARB_imaging is not available\n',
                'GL_ARB_imaging is not available',
                id='the-last-line',
            ),
            pytest.param('only one line', 'only one line', id='one-line'),
            pytest.param('', 'extension missing', id='nothing-printed'),
            pytest.param('   \n  \n', 'extension missing', id='whitespace-only'),
        ],
    )
    def test_it_reads_as_a_sentence(self, stdout, expected):
        """Not as a Python list literal: ``splitlines()[-1:]`` is a slice, and
        formatting one gives the reader ``['...']`` with the quotes."""
        message = test_all_scripts.skip_reason('nehe6.py', stdout)
        assert message == 'nehe6.py: %s' % (expected,)
        assert '[' not in message and "'" not in message


class TestTheShaderCompileHarnessSkips:
    """``tests/helpers/_shader_compile_check.py`` reports 0 = compiled,
    77 = no GL context, 1 = a program failed.  A machine that cannot provide a
    context must reach 77, whatever shape its inability takes -- reporting it
    as 1 says a shader does not compile."""

    def _harness(self):
        import importlib.util

        path = os.path.join(ROOT, 'tests', 'helpers', '_shader_compile_check.py')
        spec = importlib.util.spec_from_file_location('_shader_compile_check', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @pytest.mark.parametrize(
        'raised',
        [
            pytest.param(ImportError('no EGL in this build'), id='import'),
            pytest.param(
                AttributeError('module has no attribute eglQueryDevicesEXT'),
                id='extension-absent',
            ),
            pytest.param(RuntimeError('the driver said no'), id='driver'),
        ],
    )
    def test_a_machine_without_a_context_is_a_skip(self, monkeypatch, raised):
        harness = self._harness()
        from OpenGLContext import eglcontext

        def refuses(*arguments, **named):
            raise raised

        monkeypatch.setattr(eglcontext, 'EGLContext', refuses)
        assert harness._make_context() is None

    def test_an_egl_error_is_a_skip_with_its_own_message(self, monkeypatch, capsys):
        harness = self._harness()
        from OpenGLContext import eglcontext

        def refuses(*arguments, **named):
            raise eglcontext.EGLContextError('no config matched')

        monkeypatch.setattr(eglcontext, 'EGLContext', refuses)
        assert harness._make_context() is None
        assert 'no config matched' in capsys.readouterr().out
