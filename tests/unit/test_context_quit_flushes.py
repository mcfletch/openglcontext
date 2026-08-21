"""Quitting does not throw away what the program printed
(:meth:`OpenGLContext.context.Context.OnQuit`).

``OnQuit`` ends the process with ``os._exit``, deliberately: a forcible exit
runs no ``finally`` block and no ``atexit`` hook, which is what keeps a GL
teardown from hanging on the way out.  The cost is that anything Python still
holds in a buffer is discarded, and ``sys.stdout`` is block-buffered whenever
it is a pipe rather than a terminal.

That is how every demo in ``tests/`` is run by the visual-regression harness
and by anything reading a script's output.  So a demo that prints what it is
demonstrating -- its counts, its LOD transitions, which preset is on screen --
printed into a buffer that was thrown away, and only ever looked right when a
person ran it by hand at a terminal.
"""
import subprocess
import sys
import textwrap


SCRIPT = textwrap.dedent('''
    import sys
    from OpenGLContext import context as context_module

    class Quiet(context_module.Context):
        def __init__(self):
            pass
        def suppressRedraw(self):
            pass

    held = Quiet()
    held.stallJournal = None
    print('buffered stdout line')
    sys.stderr.write('buffered stderr line\\n')
    held.OnQuit()
''')


def _run():
    """Run the script with both streams as pipes, which is what buffers them."""
    return subprocess.run(
        [sys.executable, '-c', SCRIPT],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)


class TestWhatWasPrintedSurvives:
    def test_stdout_reaches_a_pipe(self):
        assert b'buffered stdout line' in _run().stdout

    def test_stderr_reaches_a_pipe(self):
        assert b'buffered stderr line' in _run().stderr

    def test_it_still_exits_zero(self):
        assert _run().returncode == 0
