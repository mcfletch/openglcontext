"""What a game says about itself, and whether a replay says it again.

A mark is the application's own account of what it did -- a level loaded, a
match started, somebody picked something up -- and it is the line a reader looks
for first when a journal is four minutes long.  Two things follow from that, and
both are here:

- **A game marks unconditionally.**  ``context.mark(...)`` is a call whether or
  not anything is recording and whether or not this session is itself a replay,
  because a mark guarded behind ``if self.telemetry is not None`` is a mark
  somebody will guard away, and those are exactly the ones that would have
  explained the failure nobody could reproduce.
- **A replay is worth what it reproduces.**  The marks a replay makes are the
  game saying what it did *this* time, so matching them against the ones in the
  journal is the session answering the only question a replay raises: did it
  play out again the way it played out then, and if not, where did the two part?
"""

import json
import threading

import numpy as np
import pytest

from OpenGLContext import context as context_module
from OpenGLContext import telemetry
from OpenGLContext.telemetry.replay import MarkComparison


class _Context(context_module.Context):
    """A context with the GL and the window taken out."""

    def __init__(self):
        self.drawn = 0
        self.processed = []
        self.redrawRequest = threading.Event()
        self.loopTrace = None
        self.telemetry = None

    def OnDraw(self, force=1):
        self.drawn += 1
        return 1

    def ProcessEvent(self, event):
        self.processed.append(event)

    def addPickEvent(self, event):
        pass

    def recordPointerMotion(self, x, y):
        pass

    def forgetPointerOrigin(self):
        pass

    def OnResize(self, width, height):
        pass


@pytest.fixture
def context():
    return _Context()


@pytest.fixture
def target(tmp_path):
    return tmp_path / 'session.jsonl'


def marks(path):
    return [json.loads(line) for line in path.read_text().splitlines()
            if json.loads(line).get('kind') == 'mark']


def recorded(frame, name, **fields):
    return {'kind': 'mark', 'frame': frame, 't': 0.0, 'name': name,
            'fields': fields}


class TestMarkingFromTheContext:
    def test_a_mark_reaches_the_recording(self, context, target):
        session = telemetry.start(context, target)
        context.mark('level-loaded', map='ztn3dm1', bots=4)
        session.close()
        assert marks(target)[0]['name'] == 'level-loaded'
        assert marks(target)[0]['fields'] == {'map': 'ztn3dm1', 'bots': 4}

    def test_marking_a_session_nobody_is_recording_is_a_call_and_nothing_else(
            self, context):
        assert context.telemetry is None
        context.mark('level-loaded', map='ztn3dm1')

    def test_a_field_may_be_called_anything_the_game_calls_it(self, context,
                                                              target):
        """Including ``name``, which is what a game calls the map, the
        weapon and the player."""
        session = telemetry.start(context, target)
        context.mark('level-loaded', name='ztn3dm1')
        session.close()
        assert marks(target)[0]['fields'] == {'name': 'ztn3dm1'}

    def test_a_mark_carrying_numbers_from_numpy_is_kept(self, context, target):
        """A game marks where somebody was, and where somebody is is an array."""
        session = telemetry.start(context, target)
        context.mark('spawned', at=np.zeros(3), health=np.float32(100.0))
        session.close()
        assert marks(target)[0]['fields'] == {'at': [0.0, 0.0, 0.0],
                                              'health': 100.0}


class TestMarkingWhileReplaying:
    def test_it_is_a_call_rather_than_an_error(self, context, target):
        """A replay writes nothing, and a game does not know it is one."""
        session = telemetry.start(context, target)
        context.OnDraw()
        session.close()
        playing = _Context()
        driver = telemetry.start_replay(playing, target)
        try:
            playing.mark('level-loaded', map='ztn3dm1')
        finally:
            driver.close()

    def test_the_marks_are_compared_with_the_ones_recorded(self, context,
                                                           target):
        session = telemetry.start(context, target)
        context.OnDraw()
        context.mark('level-loaded', map='ztn3dm1')
        session.close()

        playing = _Context()
        driver = telemetry.start_replay(playing, target)
        try:
            playing.OnDraw()
            playing.mark('level-loaded', map='ztn3dm1')
            assert driver.marks.matched == 1
            assert driver.marks.diverged == 0
        finally:
            driver.close()

    def test_a_replay_that_did_something_else_says_so(self, context, target):
        session = telemetry.start(context, target)
        context.OnDraw()
        context.mark('level-loaded', map='ztn3dm1')
        session.close()

        playing = _Context()
        driver = telemetry.start_replay(playing, target)
        try:
            playing.OnDraw()
            playing.mark('level-loaded', map='somewhere-else')
            assert driver.marks.diverged == 1
            assert 'somewhere-else' in driver.marks.first
        finally:
            driver.close()


class TestComparingWhatWasSaidWithWhatIsSaid:
    def test_the_same_marks_in_the_same_order_agree(self):
        found = MarkComparison([recorded(1, 'fired', weapon='rifle'),
                                recorded(2, 'hit', target='bot-1')])
        assert found.mark(1, 'fired', {'weapon': 'rifle'})
        assert found.mark(2, 'hit', {'target': 'bot-1'})
        assert found.matched == 2
        assert found.first is None

    def test_a_number_that_moved_a_little_is_the_same_number(self):
        """Two runs of the same arithmetic agree; the last bit of a float
        is not what a replay is being asked about."""
        found = MarkComparison([recorded(1, 'spawned', at=[1.0, 2.0, 3.0])])
        assert found.mark(1, 'spawned', {'at': [1.0, 2.0, 3.0 + 1e-12]})

    def test_a_mark_on_another_frame_is_a_divergence(self):
        found = MarkComparison([recorded(10, 'level-loaded', map='a')])
        assert not found.mark(12, 'level-loaded', {'map': 'a'})
        assert 'frame' in found.first

    def test_something_else_happening_instead_is_a_divergence(self):
        found = MarkComparison([recorded(1, 'fired', weapon='rifle')])
        assert not found.mark(1, 'died', {})
        assert 'died' in found.first

    def test_only_the_first_parting_is_described_and_the_rest_are_counted(self):
        found = MarkComparison([recorded(1, 'a'), recorded(2, 'b')])
        found.mark(1, 'x', {})
        found.mark(2, 'y', {})
        assert found.diverged == 2
        assert 'x' in found.first and 'y' not in found.first

    def test_a_mark_the_recording_never_held_is_a_divergence(self):
        found = MarkComparison([])
        assert not found.mark(1, 'fired', {'weapon': 'rifle'})
        assert found.diverged == 1

    def test_what_the_replay_never_got_round_to_saying_is_missing(self):
        found = MarkComparison([recorded(1, 'a'), recorded(2, 'b')])
        found.mark(1, 'a', {})
        assert [record['name'] for record in found.missing] == ['b']

    def test_the_verdict_is_one_line_a_person_reads(self):
        found = MarkComparison([recorded(1, 'a'), recorded(2, 'b')])
        found.mark(1, 'a', {})
        found.mark(2, 'b', {})
        assert '2' in found.verdict()

    def test_a_session_with_nothing_to_compare_says_so_rather_than_agreeing(self):
        assert 'no marks' in MarkComparison([]).verdict()

    def test_the_summary_is_the_numbers_on_their_own(self):
        found = MarkComparison([recorded(1, 'a'), recorded(2, 'b')])
        found.mark(1, 'a', {})
        found.mark(2, 'c', {})
        assert found.summary() == {'recorded': 2, 'made': 2, 'matched': 1,
                                   'diverged': 1, 'missing': 0,
                                   'first': found.first}
