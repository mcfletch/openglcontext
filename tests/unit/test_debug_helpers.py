"""The developer aids in `OpenGLContext.debug`."""
import os

import pytest

from OpenGLContext.debug import leaks, logcontext, logs


def test_logcontext_writes_the_calling_frames(tmp_path, monkeypatch):
    """Each frame is one line naming the function, file, line and source."""
    monkeypatch.chdir(tmp_path)
    logcontext.close()

    def outer():
        logcontext.logContext()

    outer()
    logcontext.close()
    written = (tmp_path / logcontext.LOG_NAME).read_text()
    assert 'outer' in written
    assert __file__.split(os.sep)[-1] in written


def test_importing_logcontext_writes_no_file(tmp_path, monkeypatch):
    """The log opens when something logs to it, not when the module loads."""
    monkeypatch.chdir(tmp_path)
    logcontext.close()
    import importlib
    importlib.reload(logcontext)
    assert not (tmp_path / logcontext.LOG_NAME).exists()


def test_leaks_reports_objects_created_since_init():
    """`delta` answers the objects that were not there when `init` ran."""
    leaks.init()
    fresh = ['a marker list nothing else holds']
    new = leaks.delta()
    assert any(item is fresh for item in new)


def test_leaks_reports_nothing_twice():
    """An object `delta` has already reported is not reported again."""
    leaks.init()
    fresh = ['a marker list nothing else holds']
    assert any(item is fresh for item in leaks.delta())
    assert not any(item is fresh for item in leaks.delta())


def test_leaks_reports_an_object_where_a_forgotten_one_was():
    """CPython reuses a freed object's memory, so its id comes round again.

    An id remembered from an object that has since gone says nothing about
    whatever lives at that address now: a watch started after it went has to
    report the newcomer.  In a long-running program -- or a long test session
    -- most addresses have been used before, so a watcher that never forgets
    one misses most of what it is watching for.
    """
    # Made first: CPython hands a freed list's memory to the next list made,
    # and this one must not be it.
    held = []
    gone = ['alive when the first watch starts']
    address = id(gone)
    leaks.init()
    del gone
    leaks.init()
    for _ in range(10000):
        candidate = ['made after the second watch starts']
        if id(candidate) == address:
            break
        held.append(candidate)
    else:
        pytest.skip('the allocator did not reuse the freed address')
    assert any(item is candidate for item in leaks.delta(report=False))


def test_get_traceback_formats_the_current_exception():
    try:
        raise ValueError('the message')
    except ValueError as err:
        text = logs.getTraceback(err)
    assert 'ValueError' in text
    assert 'the message' in text


def test_get_traceback_outside_an_except_block():
    """With no exception in flight the error's own text is what comes back."""
    text = logs.getTraceback(ValueError('the message'))
    assert 'the message' in text
