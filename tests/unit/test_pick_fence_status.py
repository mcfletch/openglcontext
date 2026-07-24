"""Async-pick fence status is honoured.

`_resolveBatch(block=True)` waited on the pick fence but ignored the return
status, so on `GL_TIMEOUT_EXPIRED` / `GL_WAIT_FAILED` it read the PBO and
dispatched (stale/zero) ids as if the GPU write had completed. It now drops the
batch instead. The GL wait/readback are stubbed so no context is needed.
"""
import pytest
from OpenGL.GL import GL_TIMEOUT_EXPIRED, GL_ALREADY_SIGNALED

from OpenGLContext.passes import asyncpick
from OpenGLContext.passes.selection import SelectionMixin


def _bare():
    return SelectionMixin.__new__(SelectionMixin)


class TestFenceStatus:
    def test_timeout_drops_batch_without_reading(self, monkeypatch):
        monkeypatch.setattr(asyncpick, 'glClientWaitSync',
                            lambda *a, **k: GL_TIMEOUT_EXPIRED, raising=False)
        read = {'n': 0}
        sel = _bare()
        sel._readPBO = lambda *a, **k: read.__setitem__('n', read['n'] + 1)
        # A batch that, if read, would raise (proving it is not read on timeout).
        b = {'fence': object(), 'n': 2, 'events': ['e'], 'id_map': {}}
        sel._resolveBatch(mode=None, b=b, block=True)
        assert read['n'] == 0, "must not read the PBO when the fence timed out"

    def test_signalled_batch_is_read(self, monkeypatch):
        monkeypatch.setattr(asyncpick, 'glClientWaitSync',
                            lambda *a, **k: GL_ALREADY_SIGNALED, raising=False)
        reached = {'hit': False}

        def fake_read(*a, **k):
            reached['hit'] = True
            raise RuntimeError("stop after reaching the read")   # short-circuit
        sel = _bare()
        sel._readPBO = fake_read
        b = {'fence': object(), 'n': 1, 'events': [], 'id_map': {},
             'id_pid': 1, 'dz_pid': 2}
        with pytest.raises(RuntimeError):
            sel._resolveBatch(mode=None, b=b, block=True)
        assert reached['hit'], "a signalled fence must proceed to read the PBO"
