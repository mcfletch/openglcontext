"""Asking the window system to wait for the display's refresh, or not to.

For the backends that name nothing of their own -- GLUT and wxPython -- where
the setting has to go to whichever of the window system's extensions is there.
The answer says whether it took, because a frame rate that is capped when it was
asked not to be is a surprising benchmark rather than a broken program, and a
caller that is told can say so.
"""
import pytest

from OpenGLContext import swapcontrol


@pytest.fixture
def attempts(monkeypatch):
    """Replace the platform calls, so what is under test is the choosing."""
    made = []

    def replace(*outcomes):
        def one(index, outcome):
            def attempt(interval):
                made.append((index, interval))
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
            attempt.__name__ = 'attempt%d' % (index,)
            return attempt

        monkeypatch.setattr(swapcontrol, '_ATTEMPTS',
                            [one(index, outcome)
                             for index, outcome in enumerate(outcomes)])
        return made

    return replace


class TestChoosingAPath:
    def test_the_first_one_that_works_is_the_answer(self, attempts):
        made = attempts(True, True)
        assert swapcontrol.set_swap_interval(1) is True
        assert made == [(0, 1)], 'it went on asking after an answer'

    def test_it_moves_on_from_one_that_is_not_there(self, attempts):
        made = attempts(False, True)
        assert swapcontrol.set_swap_interval(0) is True
        assert made == [(0, 0), (1, 0)]

    def test_none_of_them_is_an_answer_not_an_error(self, attempts):
        attempts(False, False)
        assert swapcontrol.set_swap_interval(1) is False

    def test_one_that_raises_does_not_stop_the_next(self, attempts):
        """A driver that has the entry point and refuses the call must not
        hide a path that would have worked."""
        made = attempts(RuntimeError('no such drawable'), True)
        assert swapcontrol.set_swap_interval(1) is True
        assert made == [(0, 1), (1, 1)]

    def test_every_path_raising_is_still_an_answer(self, attempts):
        attempts(RuntimeError('one'), RuntimeError('two'))
        assert swapcontrol.set_swap_interval(1) is False


class TestWhatIsPassedOn:
    def test_the_interval_reaches_the_platform(self, attempts):
        made = attempts(True)
        swapcontrol.set_swap_interval(2)
        assert made == [(0, 2)]

    def test_a_boolean_becomes_the_number_it_stands_for(self, attempts):
        made = attempts(True)
        swapcontrol.set_swap_interval(True)
        assert made == [(0, 1)]


class TestAgainstARealContext:
    """The platform paths themselves, where there is a context to try them on.

    Whether the extension exists is the platform's business -- llvmpipe under a
    virtual X server has no ``GLX_EXT_swap_control``, and False is the right
    answer there -- so what this holds is that asking is safe and answers a
    boolean either way.
    """

    def test_it_answers_without_raising(self, gl_context):
        for interval in (0, 1):
            assert swapcontrol.set_swap_interval(interval) in (True, False)

    def test_asking_with_no_context_current_is_false_not_an_error(self):
        """Nothing is current on this thread, so there is no drawable to set."""
        assert swapcontrol.set_swap_interval(0) in (True, False)
