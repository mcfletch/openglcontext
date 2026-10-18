"""The GPU timer: the reading it hands back, and the GL it does without.

No window: the entry points a measurement needs are stood in for, which is also
how the case for a context that does not resolve them is written.
"""
from OpenGL import GL as gl

from OpenGLContext.passes.gputimer import GpuTimer


class _Unresolved:
    """An entry point this context has not got, as PyOpenGL presents one."""

    def __bool__(self):
        return False

    def __call__(self, *args, **named):
        raise gl.error.NullFunctionError('Attempt to call an undefined function')


def _timeable(monkeypatch, nanoseconds=2_500_000, ready=1):
    """Stand in for the query family, and answer `nanoseconds` when `ready`."""
    issued = []
    monkeypatch.setattr(gl, 'glGenQueries', lambda depth: list(range(1, depth + 1)))
    monkeypatch.setattr(gl, 'glBeginQuery', lambda target, name: issued.append(name))
    monkeypatch.setattr(gl, 'glEndQuery', lambda target: None)
    monkeypatch.setattr(gl, 'glGetQueryObjectuiv', lambda name, what: ready)
    monkeypatch.setattr(gl, 'glGetQueryObjectui64v', lambda name, what: nanoseconds)
    monkeypatch.setattr(gl, 'glDeleteQueries', lambda count, names: None)
    return issued


def test_a_reading_comes_back_in_milliseconds_with_the_tag_it_was_begun_with(monkeypatch):
    issued = _timeable(monkeypatch)
    timer = GpuTimer()
    timer.begin(tag='half')
    timer.end()
    timer.begin(tag='full')          # the frame that reads the one before it
    timer.end()
    assert (timer.milliseconds, timer.tag, timer.reading) == (2.5, 'half', 1)
    assert issued == [1, 2]          # the next slot of the ring each time


def test_a_context_without_timer_queries_measures_nothing_and_draws_anyway(monkeypatch):
    """A measurement is not the work. Timer queries are GL 3.3 or an extension,
    and an entry point resolves only through a current context on some
    platforms, so a timer that cannot measure reports nothing and the stretch
    it brackets is drawn as it was."""
    monkeypatch.setattr(gl, 'glGenQueries', _Unresolved())
    timer = GpuTimer()

    timer.begin(tag='half')
    timer.end()
    timer.release()

    assert timer.milliseconds is None
    assert timer.reading == 0
    assert timer.tag is None


def test_the_gl_is_asked_once_whether_it_can_measure(monkeypatch):
    """Per frame would be a `glGetString` in every frame that draws."""
    asked = []

    class _Counted(_Unresolved):
        def __bool__(self):
            asked.append(1)
            return False

    monkeypatch.setattr(gl, 'glGenQueries', _Counted())
    timer = GpuTimer()
    for _frame in range(5):
        timer.begin()
        timer.end()
    assert len(asked) == 1


def test_a_half_of_the_family_the_context_lacks_is_enough_to_stand_down(monkeypatch):
    """`GL_TIME_ELAPSED` and the 64-bit read-back are not the same extension as
    the queries themselves, and a nanosecond count does not fit in 32 bits."""
    issued = _timeable(monkeypatch)
    monkeypatch.setattr(gl, 'glGetQueryObjectui64v', _Unresolved())
    timer = GpuTimer()

    timer.begin(tag='half')
    timer.end()

    assert issued == []              # no query issued whose answer cannot be read
    assert timer.milliseconds is None and timer.reading == 0
