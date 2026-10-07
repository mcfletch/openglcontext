"""A bounded run waits for loads before it counts frames, up to a limit.

``OpenGLContext.events.loadwait.LoadWait`` is told whether anything is loading
and the time; ``Context.loadsPending`` asks it about the scene loader's
requests and the loader pool's loads.
"""
import threading

from OpenGLContext.events.loadwait import LoadWait


def test_nothing_loading_is_no_wait():
    assert not LoadWait(10).pending(False, 100.0)


def test_loads_are_waited_for_up_to_the_limit():
    wait = LoadWait(10)
    assert wait.pending(True, 100.0)
    assert wait.pending(True, 109.0)
    assert not wait.pending(True, 110.0)
    assert wait.waited


def test_once_the_limit_is_reached_it_waits_no_more():
    wait = LoadWait(10)
    wait.pending(True, 0.0)
    wait.pending(True, 20.0)
    assert not wait.pending(True, 21.0)


def test_the_limit_runs_from_the_first_question():
    wait = LoadWait(10)
    assert not wait.pending(False, 0.0)
    assert not wait.pending(True, 15.0)
    assert wait.waited


def test_a_context_waits_for_the_pools_loads():
    from OpenGLContext.context import Context  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders import background  # noqa: PLC0415 kept with its use
    context = Context.__new__(Context)
    release = threading.Event()
    background.load_in_background('a texture', release.wait, 10)
    try:
        assert context.loadsPending()
    finally:
        release.set()
    assert background.wait_for_idle(10)
    assert not context.loadsPending()
