"""A blocking pick resolve reads its buffers only once the fence has signalled.

`_resolveBatch(block=True)` waits for the GPU: a fence still running when one
wait slice expires is waited on again, because on a loaded machine the readback
can take longer than any one slice and the click is still owed. A wait that
fails, or a fence that never signals within the limit, drops the batch rather
than dispatching the zero ids an unwritten buffer holds. The GL wait and
readback are stubbed so no context is needed.
"""
import pytest
from OpenGL.GL import GL_ALREADY_SIGNALED, GL_TIMEOUT_EXPIRED, GL_WAIT_FAILED

from OpenGLContext.passes import asyncpick
from OpenGLContext.passes.selection import SelectionMixin


def _bare():
    return SelectionMixin.__new__(SelectionMixin)


def _statuses(monkeypatch, *statuses):
    """Have each fence wait answer the next of ``statuses``, the last repeating."""
    calls = []

    def wait(*_a, **_k):
        calls.append(1)
        return statuses[min(len(calls), len(statuses)) - 1]
    monkeypatch.setattr(asyncpick, 'glClientWaitSync', wait, raising=False)
    return calls


def _counting_reads(sel):
    read = {'n': 0}
    sel._readPBO = lambda *_a, **_k: read.__setitem__('n', read['n'] + 1)  # noqa: SLF001 counts the buffer reads a fence status allows
    return read


def _reaching_reads(sel):
    reached = {'hit': False}

    def fake_read(*_a, **_k):
        reached['hit'] = True
        raise RuntimeError("stop after reaching the read")   # short-circuit
    sel._readPBO = fake_read  # noqa: SLF001 counts the buffer reads a fence status allows
    return reached


def _batch():
    return {'fence': object(), 'n': 1, 'events': [], 'id_map': {},
            'id_pid': 1, 'dz_pid': 2}


class TestFenceStatus:
    def test_signalled_batch_is_read(self, monkeypatch):
        _statuses(monkeypatch, GL_ALREADY_SIGNALED)
        sel = _bare()
        reached = _reaching_reads(sel)
        with pytest.raises(RuntimeError):
            sel._resolveBatch(mode=None, b=_batch(), block=True)  # noqa: SLF001 the batch resolve under each fence status is this test's subject
        assert reached['hit'], "a signalled fence must proceed to read the PBO"

    def test_a_fence_still_running_is_waited_for(self, monkeypatch):
        """A slice expiring is a busy GPU, not a lost readback."""
        calls = _statuses(monkeypatch, GL_TIMEOUT_EXPIRED, GL_TIMEOUT_EXPIRED,
                          GL_ALREADY_SIGNALED)
        sel = _bare()
        reached = _reaching_reads(sel)
        with pytest.raises(RuntimeError):
            sel._resolveBatch(mode=None, b=_batch(), block=True)  # noqa: SLF001 the batch resolve under each fence status is this test's subject
        assert reached['hit'], "the click is read once the fence signals"
        assert len(calls) == 3

    def test_a_failed_wait_drops_batch_without_reading(self, monkeypatch):
        calls = _statuses(monkeypatch, GL_WAIT_FAILED)
        sel = _bare()
        read = _counting_reads(sel)
        sel._resolveBatch(mode=None, b=_batch(), block=True)  # noqa: SLF001 the batch resolve under each fence status is this test's subject
        assert read['n'] == 0, "must not read the PBO when the wait failed"
        assert len(calls) == 1, "a failed wait is not retried"

    def test_a_fence_that_never_signals_is_dropped_at_the_limit(self, monkeypatch):
        calls = _statuses(monkeypatch, GL_TIMEOUT_EXPIRED)
        sel = _bare()
        monkeypatch.setattr(sel, '_FENCE_WAIT_SLICES', 3)
        read = _counting_reads(sel)
        sel._resolveBatch(mode=None, b=_batch(), block=True)  # noqa: SLF001 the batch resolve under each fence status is this test's subject
        assert read['n'] == 0, "must not read the PBO of a fence that never signalled"
        assert len(calls) == 3
