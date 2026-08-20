"""Reading a session journal back, and running it again.

The point of a recording is that it can be *run*: a bug that needed a key held
while a button was clicked in a particular place is reproduced by delivering
the same input on the same frames, against a clock driven by the frame times
that were recorded rather than by however fast this machine happens to be.
"""

import json

import pytest

from OpenGLContext.events import systemtime
from OpenGLContext.telemetry.replay import Recording, RecordedClock, Replay


@pytest.fixture(autouse=True)
def restore_the_wall_clock():
    original = systemtime.timeSource()
    yield
    systemtime.setTimeSource(original)


def journal(*records):
    return Recording([{'kind': 'header', 'version': 1, 'started': 'now'}]
                     + list(records))


def keypress(frame, key, t=0.0):
    return {'kind': 'input', 'frame': frame, 't': t,
            'type': 'keyboard', 'key': key, 'state': 1}


class TestReadingItBack:
    def test_a_partial_last_line_does_not_lose_what_came_before(self, tmp_path):
        """A session killed mid-write is exactly the session worth reading."""
        target = tmp_path / 'session.jsonl'
        target.write_text(
            json.dumps({'kind': 'header', 'version': 1}) + '\n'
            + json.dumps(keypress(0, 'w')) + '\n'
            + '{"kind": "input", "fra')
        found = Recording.read(target)
        assert len(found.inputs) == 1

    def test_the_header_is_kept_apart_from_the_records(self):
        found = journal(keypress(0, 'w'))
        assert found.header['version'] == 1

    def test_input_is_grouped_by_the_frame_that_will_deliver_it(self):
        found = journal(keypress(0, 'a'), keypress(2, 'b'), keypress(2, 'c'))
        grouped = found.inputs_by_frame()
        assert list(grouped) == [0, 2]
        assert [record['key'] for record in grouped[2]] == ['b', 'c']

    def test_frame_times_are_recovered_frame_by_frame(self):
        found = journal({'kind': 'frames', 'frame': 0, 't': 0.0,
                         'ms': [16.0, 16.0, 32.0]},
                        {'kind': 'frames', 'frame': 3, 't': 0.064,
                         'ms': [16.0]})
        assert found.frame_times() == pytest.approx([0.0, 0.016, 0.032, 0.064])

    def test_how_many_frames_the_session_lasted(self):
        found = journal({'kind': 'frames', 'frame': 0, 't': 0.0,
                         'ms': [16.0, 16.0]})
        assert found.frames == 2

    def test_the_exceptions_are_reachable_without_walking_the_file(self):
        found = journal({'kind': 'exception', 'frame': 4, 'type': 'ValueError',
                         'message': 'boom', 'traceback': []})
        assert [record['type'] for record in found.exceptions] == ['ValueError']

    def test_a_summary_says_what_the_session_was(self):
        found = journal({'kind': 'frames', 'frame': 0, 't': 0.0,
                         'ms': [16.0, 16.0, 100.0], 'stalls': 1},
                        keypress(1, 'w'),
                        {'kind': 'exception', 'type': 'ValueError',
                         'message': 'boom', 'traceback': []})
        summary = found.summary()
        assert summary['frames'] == 3
        assert summary['worst_ms'] == pytest.approx(100.0)
        assert summary['median_ms'] == pytest.approx(16.0)
        assert summary['inputs'] == 1
        assert summary['exceptions'] == 1


class TestTheRecordedClock:
    def test_time_is_where_the_recording_had_got_to(self):
        clock = RecordedClock([0.0, 0.016, 0.032], start=1000.0)
        clock.frame(0)
        assert clock() == pytest.approx(1000.0)
        clock.frame(2)
        assert clock() == pytest.approx(1000.032)

    def test_it_does_not_move_between_frames(self):
        clock = RecordedClock([0.0, 0.5], start=0.0)
        clock.frame(1)
        assert clock() == clock()

    def test_a_frame_past_the_end_holds_the_last_recorded_time(self):
        """A replay outliving its recording must not travel backwards."""
        clock = RecordedClock([0.0, 0.25], start=0.0)
        clock.frame(99)
        assert clock() == pytest.approx(0.25)

    def test_installing_it_takes_over_the_engine_clock_and_gives_it_back(self):
        before = systemtime.timeSource()
        with RecordedClock([0.0, 1.0], start=5.0) as clock:
            clock.frame(1)
            assert systemtime.systemTime() == pytest.approx(6.0)
        assert systemtime.timeSource() is before


class TestReplaying:
    def test_each_frame_delivers_the_input_recorded_against_it(self):
        delivered = []
        replay = Replay(journal(keypress(0, 'a'), keypress(1, 'b')),
                        delivered.append)
        replay.frame()
        assert [record['key'] for record in delivered] == ['a']
        replay.frame()
        assert [record['key'] for record in delivered] == ['a', 'b']

    def test_a_frame_with_no_input_recorded_delivers_nothing(self):
        delivered = []
        replay = Replay(journal(keypress(2, 'a')), delivered.append)
        replay.frame()
        replay.frame()
        assert delivered == []
        replay.frame()
        assert len(delivered) == 1

    def test_it_knows_when_the_recording_has_run_out(self):
        replay = Replay(journal(keypress(0, 'a'),
                                {'kind': 'frames', 'frame': 0, 't': 0.0,
                                 'ms': [16.0]}), lambda record: None)
        assert not replay.finished
        replay.frame()
        assert replay.finished

    def test_the_clock_follows_the_frame_being_replayed(self):
        replay = Replay(journal({'kind': 'frames', 'frame': 0, 't': 0.0,
                                 'ms': [16.0, 500.0]}),
                        lambda record: None, start=100.0)
        replay.install()
        try:
            replay.frame()
            assert systemtime.systemTime() == pytest.approx(100.0)
            replay.frame()
            assert systemtime.systemTime() == pytest.approx(100.016)
        finally:
            replay.remove()

    def test_a_delivery_that_fails_costs_the_event_and_not_the_replay(self):
        seen = []

        def awkward(record):
            seen.append(record)
            raise RuntimeError('no')

        replay = Replay(journal(keypress(0, 'a'), keypress(0, 'b')), awkward)
        replay.frame()
        assert len(seen) == 2


class TestAJournalThatWillNotRead:
    def test_a_file_that_is_not_there_is_an_empty_recording(self, tmp_path):
        found = Recording.read(tmp_path / 'never-written.jsonl')
        assert found.frames == 0
        assert found.inputs == []

    def test_blank_lines_are_passed_over(self, tmp_path):
        target = tmp_path / 'session.jsonl'
        target.write_text('\n\n' + json.dumps(keypress(0, 'w')) + '\n\n')
        assert len(Recording.read(target).inputs) == 1


class TestSayingWhereARecordedClockIs:
    def test_it_describes_itself_by_the_frame_it_is_on(self):
        clock = RecordedClock([0.0, 0.5], start=0.0)
        clock.frame(1)
        assert '1 of 2' in repr(clock)
