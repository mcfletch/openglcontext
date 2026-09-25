"""Whether the display a machine names is one a client can open.

A test that needs an X server -- the Tk and GLUT demos do -- has to know
whether there is one. ``DISPLAY`` naming a server is not the same as a server
being there: a machine often carries a socket left behind by a server that has
gone, or another one listening where a server used to, and a test reading only
the name then fails for want of an X server rather than saying it cannot be
run here.

Headless: sockets, a subprocess and a string.
"""
import os
import socket
import subprocess
import sys

import pytest

from OpenGLContext.testing import glcontext
from OpenGLContext.testing.glcontext import X_CLIENT, display_answers

#: A display number nothing is expected to be serving. X servers are numbered
#: from zero upwards and a machine with eighty of them is not one these tests
#: run on.
NOBODY = 79


def _listening_unix(path):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.bind(str(path))
    connection.listen(1)
    return connection


class TestWhatItAnswers:
    def test_no_display_named_is_no_display(self):
        assert not display_answers('')
        assert not display_answers('   ')

    def test_a_display_nothing_listens_on(self):
        assert not display_answers(':%d' % NOBODY)

    def test_a_socket_left_behind_by_a_server_that_has_gone(self, tmp_path):
        path = tmp_path / ('X%d' % NOBODY)
        closed = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        closed.bind(str(path))
        closed.close()
        assert path.exists()
        assert not display_answers(':%d' % NOBODY, directory=str(tmp_path))

    def test_something_listening_that_is_not_a_server_we_may_use(self, tmp_path):
        """A connection is accepted and a client still cannot open a window."""
        pytest.importorskip('tkinter')
        listening = _listening_unix(tmp_path / ('X%d' % NOBODY))
        try:
            assert not display_answers(':%d' % NOBODY, directory=str(tmp_path))
        finally:
            listening.close()

    def test_a_network_display_nothing_listens_on(self):
        assert not display_answers('127.0.0.1:%d' % NOBODY)

    def test_a_name_that_is_not_a_display(self):
        assert not display_answers('nonsense')
        assert not display_answers(':what')

    def test_the_environment_is_what_it_reads_by_default(self, monkeypatch):
        monkeypatch.delenv('DISPLAY', raising=False)
        assert not display_answers()
        monkeypatch.setenv('DISPLAY', ':%d' % NOBODY)
        assert not display_answers()


class TestAgainstARealClient:
    """Its answer is the answer a client gets, whatever this machine has."""

    def _client_opens(self, display):
        opened = subprocess.run([sys.executable, '-c', X_CLIENT],
                                capture_output=True, timeout=60,
                                env=dict(os.environ, DISPLAY=display))
        return opened.returncode == 0

    @pytest.mark.parametrize('display', [':0', ':1', ':%d' % NOBODY])
    def test_it_says_what_a_client_finds(self, display):
        pytest.importorskip('tkinter')
        assert display_answers(display) == self._client_opens(display)

    def test_this_machines_own_display(self):
        pytest.importorskip('tkinter')
        display = os.environ.get('DISPLAY', '').strip()
        if not display:
            pytest.skip('this machine names no display')
        assert display_answers() == self._client_opens(display)


class TestAskedOnce:
    """Three test modules ask at import time; the client runs once per display."""

    def test_the_client_is_run_once_for_a_display(self, monkeypatch):
        pytest.importorskip('tkinter')
        ran = []

        class Opened:
            returncode = 0

        def run(*_args, **named):
            ran.append(named['env']['DISPLAY'])
            return Opened()

        monkeypatch.setattr(glcontext, '_display_listens', lambda *_args: True)
        monkeypatch.setattr(subprocess, 'run', run)
        glcontext._client_opens.cache_clear()
        try:
            assert display_answers(':%d' % NOBODY)
            assert display_answers(':%d' % NOBODY)
            assert display_answers(':%d' % (NOBODY - 1))
        finally:
            glcontext._client_opens.cache_clear()
        assert ran == [':%d' % NOBODY, ':%d' % (NOBODY - 1)]
