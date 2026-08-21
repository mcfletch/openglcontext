"""What a session recorder decides to write down.

The recorder holds every rule and no GL, no window and no file: it is handed a
``write`` callable and a clock, so each rule is pinned against exact numbers
rather than sampled ones.  What it produces is what a replay reads back, so the
frame an input is stamped with is as much a part of the contract as the fields.
"""

import logging

import pytest

from OpenGLContext.telemetry.recorder import SessionRecorder


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def written():
    return []


@pytest.fixture
def recorder(written, clock):
    return SessionRecorder(written.append, clock=clock, block=4)


def kinds(written, kind):
    return [record for record in written if record['kind'] == kind]


class TestStampingInput:
    def test_an_input_is_stamped_with_the_frame_that_will_process_it(
            self, recorder, written, clock):
        """Input arrives while the platform is polled, and is acted on by the
        frame that follows: that is the frame a replay must deliver it on."""
        recorder.input({'type': 'keyboard', 'key': 'w', 'state': 1})
        clock.advance(0.016)
        recorder.frame(0.016)
        recorder.input({'type': 'keyboard', 'key': 'w', 'state': 0})
        clock.advance(0.016)
        recorder.frame(0.016)
        assert [record['frame'] for record in kinds(written, 'input')] == [0, 1]

    def test_an_input_carries_the_time_it_arrived(self, recorder, written, clock):
        clock.advance(2.5)
        recorder.input({'type': 'keyboard', 'key': 'w', 'state': 1})
        recorder.frame(0.016)
        assert kinds(written, 'input')[0]['t'] == pytest.approx(2.5)

    def test_input_is_written_in_the_order_it_arrived(self, recorder, written):
        for name in 'abc':
            recorder.input({'type': 'keyboard', 'key': name, 'state': 1})
        recorder.frame(0.016)
        assert [record['key'] for record in kinds(written, 'input')] == list('abc')

    def test_nothing_is_written_before_the_frame_that_owns_it_ends(
            self, recorder, written):
        recorder.input({'type': 'keyboard', 'key': 'w', 'state': 1})
        assert written == []


class TestCollapsingPointerMotion:
    """A mouse reports far faster than frames are drawn, and only where it
    ended up is observable by the time the frame runs."""

    def test_only_the_last_pointer_position_of_a_frame_is_kept(
            self, recorder, written):
        for x in range(10):
            recorder.input({'type': 'pointer', 'x': x, 'y': 0})
        recorder.frame(0.016)
        found = kinds(written, 'input')
        assert len(found) == 1
        assert found[0]['x'] == 9

    def test_each_frame_keeps_its_own_last_position(self, recorder, written):
        recorder.input({'type': 'pointer', 'x': 1, 'y': 0})
        recorder.input({'type': 'pointer', 'x': 2, 'y': 0})
        recorder.frame(0.016)
        recorder.input({'type': 'pointer', 'x': 3, 'y': 0})
        recorder.frame(0.016)
        assert [record['x'] for record in kinds(written, 'input')] == [2, 3]

    def test_a_move_event_collapses_the_same_way(self, recorder, written):
        for x in range(5):
            recorder.input({'type': 'mousemove', 'x': x, 'y': 0})
        recorder.frame(0.016)
        assert len(kinds(written, 'input')) == 1

    def test_a_key_between_two_positions_keeps_them_apart(self, recorder, written):
        """Collapsing must not reorder input past a key: where the pointer was
        when a button went down is the whole of some bugs."""
        recorder.input({'type': 'pointer', 'x': 1, 'y': 0})
        recorder.input({'type': 'mousebutton', 'button': 0, 'state': 1})
        recorder.input({'type': 'pointer', 'x': 2, 'y': 0})
        recorder.frame(0.016)
        assert [record['type'] for record in kinds(written, 'input')] == [
            'pointer', 'mousebutton', 'pointer']

    def test_a_button_is_never_collapsed(self, recorder, written):
        for state in (1, 0, 1, 0):
            recorder.input({'type': 'mousebutton', 'button': 3, 'state': state})
        recorder.frame(0.016)
        assert len(kinds(written, 'input')) == 4


class TestFrameTimes:
    def test_a_block_holds_every_frame_time_in_it(self, recorder, written):
        for _ in range(4):
            recorder.frame(0.016)
        blocks = kinds(written, 'frames')
        assert len(blocks) == 1
        assert blocks[0]['ms'] == [16.0, 16.0, 16.0, 16.0]

    def test_a_block_says_which_frame_it_starts_at(self, recorder, written):
        for _ in range(8):
            recorder.frame(0.016)
        assert [block['frame'] for block in kinds(written, 'frames')] == [0, 4]

    def test_a_block_says_when_its_first_frame_started(
            self, recorder, written, clock):
        for _ in range(4):
            clock.advance(0.016)
            recorder.frame(0.016)
        clock.advance(0.016)
        recorder.frame(0.016)
        recorder.close()
        blocks = kinds(written, 'frames')
        assert blocks[0]['t'] == pytest.approx(0.0)
        assert blocks[1]['t'] == pytest.approx(0.064)

    def test_the_worst_frame_survives_a_healthy_median(self, recorder, written):
        """The reason this exists rather than a frame-rate number: a median of
        a hundred good frames says nothing about the one that took a second."""
        for _ in range(3):
            recorder.frame(0.016)
        recorder.frame(1.0)
        assert max(kinds(written, 'frames')[0]['ms']) == pytest.approx(1000.0)

    def test_the_time_inside_the_draw_is_kept_beside_the_whole_frame(
            self, recorder, written):
        for _ in range(4):
            recorder.frame(0.050, draw=0.010)
        block = kinds(written, 'frames')[0]
        assert block['ms'][0] == pytest.approx(50.0)
        assert block['draw_ms'][0] == pytest.approx(10.0)

    def test_the_phase_breakdown_is_summed_over_the_block(self, recorder, written):
        for _ in range(4):
            recorder.frame(0.020, phases={'idle': 0.015, 'render': 0.005})
        assert kinds(written, 'frames')[0]['phases_ms'] == {
            'idle': pytest.approx(60.0), 'render': pytest.approx(20.0)}

    def test_stalls_are_counted_for_the_block(self, recorder, written):
        recorder.frame(0.016)
        recorder.frame(1.0, stalled=True)
        recorder.frame(0.016)
        recorder.frame(0.9, stalled=True)
        assert kinds(written, 'frames')[0]['stalls'] == 2

    def test_a_part_block_is_not_lost_at_the_end_of_the_session(
            self, recorder, written):
        recorder.frame(0.016)
        recorder.frame(0.016)
        recorder.close()
        assert kinds(written, 'frames')[0]['ms'] == [16.0, 16.0]

    def test_the_first_frame_has_no_predecessor_to_be_measured_against(
            self, recorder, written):
        recorder.frame(None, draw=0.030)
        recorder.close()
        assert kinds(written, 'frames')[0]['ms'] == [30.0]


class TestMarksAndState:
    def test_a_mark_carries_whatever_the_game_said(self, recorder, written):
        recorder.mark('level-loaded', map='ztn3dm1', bots=4)
        found = kinds(written, 'mark')[0]
        assert found['name'] == 'level-loaded'
        assert found['fields'] == {'map': 'ztn3dm1', 'bots': 4}

    def test_a_mark_is_written_at_once_rather_than_held_for_the_frame(
            self, recorder, written):
        """It may be the last thing the process manages to say."""
        recorder.mark('about-to-do-something-rash')
        assert kinds(written, 'mark')

    def test_the_application_description_is_sampled_rather_than_written_every_frame(
            self, written, clock):
        recorder = SessionRecorder(written.append, clock=clock, block=1000,
                                   state_seconds=1.0,
                                   state=lambda: {'Player': {'health': 100}})
        for _ in range(10):
            clock.advance(0.1)
            recorder.frame(0.1)
        assert len(kinds(written, 'state')) == 1

    def test_the_description_is_the_overlay_s_own_sections(self, written, clock):
        recorder = SessionRecorder(written.append, clock=clock,
                                   state_seconds=0.0,
                                   state=lambda: {'Map': {'name': 'ztn3dm1'}})
        recorder.frame(0.016)
        assert kinds(written, 'state')[0]['sections'] == {'Map': {'name': 'ztn3dm1'}}

    def test_a_description_that_fails_costs_the_row_and_not_the_frame(
            self, written, clock):
        def broken():
            raise RuntimeError('no')
        recorder = SessionRecorder(written.append, clock=clock,
                                   state_seconds=0.0, state=broken)
        recorder.frame(0.016)
        assert not kinds(written, 'state')


class TestExceptions:
    def test_an_exception_is_written_with_its_traceback(self, recorder, written):
        try:
            raise ValueError('the wheels came off')
        except ValueError as error:
            recorder.exception(error)
        found = kinds(written, 'exception')[0]
        assert found['type'] == 'ValueError'
        assert found['message'] == 'the wheels came off'
        assert any('the wheels came off' in line for line in found['traceback'])

    def test_it_says_which_frame_the_session_had_reached(self, recorder, written):
        recorder.frame(0.016)
        recorder.frame(0.016)
        recorder.exception(ValueError('later'))
        assert kinds(written, 'exception')[0]['frame'] == 2

    def test_a_fatal_one_is_marked_as_such(self, recorder, written):
        recorder.exception(ValueError('the end'), fatal=True)
        assert kinds(written, 'exception')[0]['fatal'] is True

    def test_the_thread_it_happened_on_is_named(self, recorder, written):
        recorder.exception(ValueError('elsewhere'), thread='loader')
        assert kinds(written, 'exception')[0]['thread'] == 'loader'

    def test_it_is_written_at_once_because_the_process_may_not_survive_it(
            self, recorder, written):
        recorder.exception(ValueError('the end'), fatal=True)
        assert kinds(written, 'exception')


class TestMessages:
    def test_a_warning_is_kept_with_its_logger(self, recorder, written):
        recorder.message(logging.WARNING, 'twig_bb.game', 'no spawn point')
        found = kinds(written, 'log')[0]
        assert (found['level'], found['logger']) == ('WARNING', 'twig_bb.game')
        assert found['message'] == 'no spawn point'


class TestClosing:
    def test_the_end_says_how_much_of_a_session_this_was(self, recorder,
                                                         written, clock):
        for _ in range(3):
            clock.advance(0.016)
            recorder.frame(0.016)
        recorder.close(reason='quit')
        end = kinds(written, 'end')[0]
        assert end['frames'] == 3
        assert end['reason'] == 'quit'
        assert end['t'] == pytest.approx(0.048)

    def test_closing_twice_writes_one_ending(self, recorder, written):
        recorder.close()
        recorder.close()
        assert len(kinds(written, 'end')) == 1

    def test_nothing_is_written_after_it_is_closed(self, recorder, written):
        recorder.close()
        before = len(written)
        recorder.input({'type': 'keyboard', 'key': 'w', 'state': 1})
        recorder.frame(0.016)
        assert len(written) == before

    def test_a_write_that_fails_costs_the_record_and_not_the_game(
            self, clock):
        def explode(record):
            raise OSError('disk full')
        recorder = SessionRecorder(explode, clock=clock)
        recorder.mark('still running')          # must not raise
        recorder.frame(0.016)


class TestAfterItIsClosed:
    def test_a_mark_made_afterwards_is_dropped(self, recorder, written):
        recorder.close()
        before = len(written)
        recorder.mark('too late')
        assert len(written) == before


class TestMessagesWithAStack:
    def test_a_logged_exception_keeps_its_traceback(self, recorder, written):
        recorder.message(logging.ERROR, 'twig_bb.game', 'it went wrong',
                         traceback=['Traceback (most recent call last):',
                                    'ValueError: it went wrong'])
        assert kinds(written, 'log')[0]['traceback'][-1].endswith('it went wrong')


class TestMarkingWhenNobodyIsRecording:
    """A game marks what it does whether or not anyone asked for a file.

    :func:`~OpenGLContext.telemetry.install` answers None when the environment
    asked for nothing, so a caller that marks unconditionally would have to
    guard every call -- and the calls that get guarded away are the ones that
    explain the failure nobody could reproduce.
    """

    def test_it_takes_a_mark_and_keeps_nothing(self) -> None:
        from OpenGLContext.telemetry import NOT_RECORDING
        assert NOT_RECORDING.mark('drive-ended', why='hit a car') is None

    def test_it_says_it_is_not_recording(self) -> None:
        from OpenGLContext.telemetry import NOT_RECORDING
        assert not NOT_RECORDING

    def test_and_a_real_recording_says_it_is(self, tmp_path) -> None:
        from OpenGLContext.telemetry import SessionRecorder
        assert SessionRecorder(_Written())

    def test_one_stands_in_for_the_other(self) -> None:
        """Same call, so a caller written for one runs against the other."""
        from OpenGLContext.telemetry import NOT_RECORDING, SessionRecorder
        for recorder in (NOT_RECORDING, SessionRecorder(_Written())):
            recorder.mark('pass-begun', gap=40.0, sight=260.0)


class _Written:
    """A journal that keeps its records in a list."""

    def __init__(self) -> None:
        self.records: list = []

    def write(self, record) -> None:
        self.records.append(record)

    def close(self, reason=None) -> None:
        pass
