"""Attaching a session recorder to a context, and taking it off again.

Recording has to see what the *platform* delivered, before anything in the
engine has had a chance to sink it -- an event an overlay swallowed is still an
event the player produced, and a replay that never delivers it does not
reproduce the session.  So the taps sit above the whole class hierarchy, on the
instance, and these pin that they see everything and that removing them leaves
the context as it was.
"""

import json
import logging
import threading

import pytest

from OpenGLContext import telemetry
from OpenGLContext.telemetry import record as telemetry_record


class FakeContext:
    """The entry points a platform calls, and nothing else."""

    def __init__(self):
        self.drawn = 0
        self.processed = []
        self.picked = []
        self.pointer = []
        self.resized = []
        self.loopTrace = None
        self.telemetry = None

    def OnDraw(self, force=1):
        self.drawn += 1
        return 1

    def ProcessEvent(self, event):
        self.processed.append(event)

    def addPickEvent(self, event):
        self.picked.append(event)

    def triggerPick(self):
        pass

    def recordPointerMotion(self, x, y):
        self.pointer.append((x, y))

    def forgetPointerOrigin(self):
        pass

    def OnResize(self, width, height):
        self.resized.append((width, height))


def key(name, state=1):
    from OpenGLContext.events.keyboardevents import KeyboardEvent
    event = KeyboardEvent()
    event.name, event.state = name, state
    return event


def records(path, kind=None):
    found = [json.loads(line) for line in path.read_text().splitlines()
             if line.strip()]
    if kind is None:
        return found
    return [record for record in found if record['kind'] == kind]


@pytest.fixture
def context():
    return FakeContext()


@pytest.fixture
def target(tmp_path):
    return tmp_path / 'session.jsonl'


class TestTheTap:
    def test_a_tap_sees_the_call_without_changing_it(self, context):
        seen = []
        tap = telemetry_record.Tap(context, 'ProcessEvent', before=seen.append)
        try:
            context.ProcessEvent('an event')
            assert seen == ['an event']
            assert context.processed == ['an event']
        finally:
            tap.remove()

    def test_removing_it_leaves_the_method_the_class_defines(self, context):
        original = FakeContext.ProcessEvent
        tap = telemetry_record.Tap(context, 'ProcessEvent', before=lambda event: None)
        tap.remove()
        assert 'ProcessEvent' not in context.__dict__
        assert context.ProcessEvent.__func__ is original

    def test_a_tap_that_raises_costs_nothing(self, context):
        def explode(event):
            raise RuntimeError('no')
        tap = telemetry_record.Tap(context, 'ProcessEvent', before=explode)
        try:
            context.ProcessEvent('an event')
            assert context.processed == ['an event']
        finally:
            tap.remove()

    def test_a_missing_method_is_not_a_tap(self, context):
        tap = telemetry_record.Tap(context, 'noSuchMethod', before=lambda: None)
        assert not tap.installed
        tap.remove()


class TestWhatIsRecorded:
    def test_every_key_the_platform_delivered_is_in_the_file(self, context, target):
        session = telemetry.start(context, target)
        context.ProcessEvent(key('w', 1))
        context.OnDraw()
        context.ProcessEvent(key('w', 0))
        context.OnDraw()
        session.close()
        assert [(record['key'], record['state'])
                for record in records(target, 'input')] == [('w', 1), ('w', 0)]

    def test_a_click_is_recorded_as_having_gone_through_the_pick(
            self, context, target):
        from OpenGLContext.events.mouseevents import MouseButtonEvent
        session = telemetry.start(context, target)
        event = MouseButtonEvent()
        event.button, event.state = 0, 1
        event.pickPoint = (10.0, 20.0)
        context.addPickEvent(event)
        context.OnDraw()
        session.close()
        found = records(target, 'input')[0]
        assert found['pick'] is True
        assert (found['x'], found['y']) == (10.0, 20.0)

    def test_pointer_motion_is_recorded_where_the_sampler_hears_it(
            self, context, target):
        session = telemetry.start(context, target)
        context.recordPointerMotion(5, 6)
        context.OnDraw()
        session.close()
        assert records(target, 'input')[0]['type'] == 'pointer'

    def test_a_resize_is_part_of_the_session(self, context, target):
        session = telemetry.start(context, target)
        context.OnResize(320, 240)
        context.OnDraw()
        session.close()
        found = records(target, 'input')[0]
        assert (found['width'], found['height']) == (320, 240)

    def test_frames_are_timed_without_the_backend_having_to_help(
            self, context, target):
        session = telemetry.start(context, target)
        for _ in range(3):
            context.OnDraw()
        session.close()
        assert len(records(target, 'frames')[0]['ms']) == 3

    def test_the_header_says_what_was_running(self, context, target):
        session = telemetry.start(context, target)
        session.close()
        header = records(target, 'header')[0]
        assert header['pid']
        assert header['argv']
        assert header['python']


class TestExceptions:
    def test_one_escaping_the_draw_is_recorded_and_still_raised(
            self, context, target):
        def explode(force=1):
            raise ValueError('mid-frame')
        context.OnDraw = explode
        session = telemetry.start(context, target)
        with pytest.raises(ValueError):
            context.OnDraw()
        session.close()
        assert records(target, 'exception')[0]['message'] == 'mid-frame'

    def test_one_ending_the_session_is_recorded_as_the_session_closes(
            self, context, target):
        """A main loop closes its recording from a ``finally``, and every
        exception hook runs after every ``finally`` -- so a session that ended
        on an exception would have emptied its journal before anything could
        write the exception into it."""
        session = telemetry.start(context, target)
        try:
            raise ValueError('what ended it')
        except ValueError:
            session.close('mainloop-ended')
        assert records(target, 'exception')[0]['message'] == 'what ended it'

    def test_the_ending_says_the_session_failed(self, context, target):
        session = telemetry.start(context, target)
        try:
            raise ValueError('what ended it')
        except ValueError:
            session.close('mainloop-ended')
        assert records(target, 'end')[0]['reason'] == 'exception'

    def test_one_failure_reaching_it_twice_is_one_record(self, context, target):
        """It escapes the draw, then unwinds the loop: two routes, one bug."""
        error = ValueError('once only')

        def explode(force=1):
            raise error
        context.OnDraw = explode
        session = telemetry.start(context, target)
        try:
            context.OnDraw()
        except ValueError:
            session.close('mainloop-ended')
        assert len(records(target, 'exception')) == 1

    def test_one_logged_by_anybody_is_recorded(self, context, target):
        session = telemetry.start(context, target)
        log = logging.getLogger('test.telemetry.wiring')
        try:
            raise ValueError('logged, not raised')
        except ValueError:
            log.exception('something went wrong')
        session.close()
        found = records(target, 'exception')
        assert any(record['message'] == 'logged, not raised' for record in found)

    def test_a_warning_from_anybody_is_kept(self, context, target):
        session = telemetry.start(context, target)
        logging.getLogger('test.telemetry.wiring').warning('careful')
        session.close()
        assert any(record['message'] == 'careful'
                   for record in records(target, 'log'))

    def test_the_logging_handler_goes_away_when_the_session_does(
            self, context, target):
        before = len(logging.getLogger().handlers)
        telemetry.start(context, target).close()
        assert len(logging.getLogger().handlers) == before

    @pytest.mark.filterwarnings('ignore::pytest.PytestUnhandledThreadExceptionWarning')
    def test_one_raised_on_another_thread_is_recorded(self, context, target):
        session = telemetry.start(context, target)

        def explode():
            raise ValueError('on a thread')

        thread = threading.Thread(target=explode, name='loader')
        thread.start()
        thread.join()
        session.close()
        assert any(record['message'] == 'on a thread'
                   for record in records(target, 'exception'))

    def test_the_hooks_are_put_back_when_the_session_ends(self, context, target):
        import sys
        before = sys.excepthook
        telemetry.start(context, target).close()
        assert sys.excepthook is before


class TestSwitchingItOn:
    def test_nothing_happens_when_nobody_asked(self, context, monkeypatch):
        monkeypatch.delenv(telemetry.TELEMETRY_ENV, raising=False)
        monkeypatch.delenv(telemetry.REPLAY_ENV, raising=False)
        assert telemetry.install(context) is None

    def test_the_environment_names_the_file(self, context, target, monkeypatch):
        monkeypatch.setenv(telemetry.TELEMETRY_ENV, str(target))
        session = telemetry.install(context)
        try:
            assert session is not None
            assert target.exists()
        finally:
            session.close()

    def test_a_path_that_cannot_be_written_is_not_a_reason_not_to_start(
            self, context, tmp_path, monkeypatch):
        monkeypatch.setenv(telemetry.TELEMETRY_ENV,
                           str(tmp_path / 'file.jsonl' / 'nested.jsonl'))
        session = telemetry.install(context)
        context.OnDraw()                       # the game runs regardless
        if session is not None:
            session.close()

    def test_closing_twice_is_harmless(self, context, target):
        session = telemetry.start(context, target)
        session.close()
        session.close()

    def test_the_context_is_left_as_it_was_found(self, context, target):
        session = telemetry.start(context, target)
        session.close()
        assert 'OnDraw' not in context.__dict__
        assert 'ProcessEvent' not in context.__dict__


class TestReplayingIntoAContext:
    def test_the_recorded_input_arrives_for_the_frames_it_arrived_on(
            self, context, target):
        """A frame's input is there before the frame does its work.

        The platform delivers input *between* frames -- it is polled, and then
        the application does the frame's work on what was found -- so a replay
        hands each frame's input over as the frame before it ends. Delivered at
        the top of the draw instead it arrives after that frame's idle work and
        is acted on a frame late, which is a shot, a weapon change and a jump
        each landing a frame after it did.
        """
        session = telemetry.start(context, target)
        context.ProcessEvent(key('a', 1))
        context.OnDraw()
        context.OnDraw()
        context.ProcessEvent(key('b', 1))
        context.OnDraw()
        session.close()

        playing = FakeContext()
        driver = telemetry.start_replay(playing, target)
        try:
            assert [event.name for event in playing.processed] == []
            playing.OnDraw()                    # frame 0, and 'a' with it
            assert [event.name for event in playing.processed] == ['a']
            playing.OnDraw()                    # frame 1 drawn; 'b' is next
            assert [event.name for event in playing.processed] == ['a', 'b']
        finally:
            driver.close()

    def test_a_replay_puts_the_clock_back_when_it_finishes(self, context, target):
        from OpenGLContext.events import systemtime
        session = telemetry.start(context, target)
        context.OnDraw()
        session.close()
        before = systemtime.timeSource()
        driver = telemetry.start_replay(FakeContext(), target)
        driver.close()
        assert systemtime.timeSource() is before


class TestWhatTheGameCanSay:
    def test_it_marks_its_own_events(self, context, target):
        session = telemetry.start(context, target)
        session.mark('level-loaded', map='ztn3dm1')
        session.close()
        assert records(target, 'mark')[0]['fields'] == {'map': 'ztn3dm1'}

    def test_it_can_say_which_file_it_is_writing(self, context, target):
        session = telemetry.start(context, target)
        try:
            assert session.path == target
        finally:
            session.close()

    def test_a_backend_that_warps_the_pointer_says_so(self, context, target):
        """A warp arrives back as a movement that is the reverse of the one
        that provoked it; a replay that never heard the warp would turn."""
        session = telemetry.start(context, target)
        context.forgetPointerOrigin()
        context.OnDraw()
        session.close()
        assert records(target, 'input')[0]['type'] == 'pointer-origin'


def _intervals(readings):
    """What passed between one reading and the next, to the microsecond."""
    return [round(b - a, 6)
            for a, b in zip(readings, readings[1:], strict=False)]


class TestTheClockWhileRecording:
    """A recorded session reads one instant per frame, and that is what makes
    a replay exact.

    A replay's clock is a step function: it holds the time the recording had
    reached at that frame for the whole of the frame. A recording whose game
    read the wall clock as it ran is not on a step function at all -- what it
    read depended on how far into the frame it happened to ask -- so the two
    runs measure the same interval differently by however long the work inside
    a frame takes. Milliseconds of it, which is enough to put a weapon's fire
    rate, a respawn or an animation one frame out and everything after it out
    with them. So recording installs a clock of the same shape as the one a
    replay installs.
    """

    def readings(self, context, frames=4):
        """What the world's clock says at one fixed point in each frame."""
        from OpenGLContext.events import systemtime
        found = []
        for _each in range(frames):
            found.append(systemtime.systemTime())
            context.OnDraw()
        return found

    def test_it_stands_still_inside_one_frame(self, context, target):
        from OpenGLContext.events import systemtime
        session = telemetry.start(context, target)
        try:
            context.OnDraw()
            assert systemtime.systemTime() == systemtime.systemTime()
        finally:
            session.close()

    def test_it_moves_on_by_what_is_written_down_for_the_frame(self, context,
                                                               target):
        """The file's own numbers, so a replay adding them up arrives at the
        same instants rather than at a second measurement of them."""
        from OpenGLContext.events import systemtime
        session = telemetry.start(context, target)
        before = systemtime.systemTime()
        for _each in range(4):
            context.OnDraw()
        moved = systemtime.systemTime() - before
        session.close()
        written = sum(sum(record['ms']) for record in records(target, 'frames'))
        # To a microsecond: the world's clock is wall-clock-valued, and a
        # double at sixteen hundred million seconds has a quarter of one of
        # those between it and the next number it can hold.
        assert moved == pytest.approx(written / 1000.0, abs=1e-6)

    def test_the_wall_clock_is_given_back_when_the_recording_stops(
            self, context, target):
        from OpenGLContext.events import systemtime
        before = systemtime.timeSource()
        telemetry.start(context, target).close()
        assert systemtime.timeSource() is before

    def test_a_replay_reads_the_same_intervals_the_recording_read(
            self, context, target):
        """The property the whole thing rests on: what the game measured
        between one frame and the next is what it measures again."""
        session = telemetry.start(context, target)
        recorded = self.readings(context)
        session.close()

        playing = FakeContext()
        driver = telemetry.start_replay(playing, target)
        try:
            played = self.readings(playing)
        finally:
            driver.close()
        assert (_intervals(recorded) == _intervals(played))


class TestTheExceptionHook:
    def test_one_nothing_caught_is_recorded_and_still_reported(
            self, context, target, monkeypatch):
        import sys
        seen = []
        monkeypatch.setattr(sys, 'excepthook', lambda *args: seen.append(args))
        session = telemetry.start(context, target)
        try:
            raise ValueError('nothing caught this')
        except ValueError as error:
            sys.excepthook(type(error), error, error.__traceback__)
        session.close()
        assert records(target, 'exception')[0]['message'] == 'nothing caught this'
        assert seen, 'the hook that was there before must still be called'


class TestTheEnvironmentSwitches:
    def test_a_replay_is_what_the_replay_variable_asks_for(
            self, context, target, monkeypatch):
        telemetry.start(context, target)
        context.OnDraw()
        context.telemetry.close()
        monkeypatch.delenv(telemetry.TELEMETRY_ENV, raising=False)
        monkeypatch.setenv(telemetry.REPLAY_ENV, str(target))
        session = telemetry.install(FakeContext())
        try:
            assert isinstance(session, telemetry.ReplaySession)
        finally:
            session.close()

    def test_a_replay_of_a_file_holding_no_session_is_refused(
            self, tmp_path, monkeypatch):
        empty = tmp_path / 'empty.jsonl'
        empty.write_text('')
        monkeypatch.setenv(telemetry.REPLAY_ENV, str(empty))
        assert telemetry.install(FakeContext()) is None

    def test_the_ceiling_is_read_from_the_environment(self, context, target,
                                                      monkeypatch):
        monkeypatch.setenv(telemetry.TELEMETRY_ENV, str(target))
        monkeypatch.setenv(telemetry.MAX_MB_ENV, '2')
        session = telemetry.install(context)
        try:
            assert session.journal.max_bytes == 2 * 1024 * 1024
        finally:
            session.close()

    def test_a_ceiling_that_is_not_a_number_is_the_default(
            self, context, target, monkeypatch):
        """A mistyped diagnostic switch must not be why a game will not run."""
        from OpenGLContext.telemetry.journal import DEFAULT_MAX_BYTES
        monkeypatch.setenv(telemetry.TELEMETRY_ENV, str(target))
        monkeypatch.setenv(telemetry.MAX_MB_ENV, 'lots')
        session = telemetry.install(context)
        try:
            assert session.journal.max_bytes == DEFAULT_MAX_BYTES
        finally:
            session.close()


class TestTheHeader:
    def test_a_definition_whose_size_will_not_convert_costs_that_line_only(
            self, context, target):
        class Definition:
            size = 'not a size'
            profile = 'core'
            title = 'A Game'

        context.contextDefinition = Definition()
        telemetry.start(context, target).close()
        definition = records(target, 'header')[0]['definition']
        assert 'size' not in definition
        assert definition['profile'] == 'core'


class TestTakingTheTapOffAgain:
    def test_a_tap_whose_attribute_has_already_gone_still_restores(self, context):
        tap = telemetry_record.Tap(context, 'ProcessEvent', before=lambda e: None)
        del context.ProcessEvent
        tap.remove()
        context.ProcessEvent('an event')
        assert context.processed == ['an event']


class TestWhatCountsAsAStall:
    def test_a_slow_frame_is_counted_on_a_backend_that_times_no_loop(
            self, context, target, monkeypatch):
        """A stall is a stall whether or not anything was timing the iteration
        it happened in."""
        monkeypatch.setenv('OPENGLCONTEXT_STALL_MS', '5')
        clock = iter([0.0, 0.001, 0.002, 0.500])

        session = telemetry.start(context, target)
        session._clock = lambda: next(clock)
        context.OnDraw()
        context.OnDraw()
        session.close()
        assert records(target, 'frames')[0]['stalls'] == 1

    def test_the_loop_s_own_threshold_is_what_a_backend_that_has_one_uses(
            self, context, target):
        from OpenGLContext.looptrace import LoopTrace

        context.loopTrace = LoopTrace(stall_ms=200.0)
        clock = iter([0.0, 0.001, 0.002, 0.100, 0.101, 0.400])

        session = telemetry.start(context, target)
        session._clock = lambda: next(clock)
        for _ in range(3):
            context.OnDraw()
        session.close()
        # 99ms is not a stall at a 200ms threshold; 299ms is.
        assert records(target, 'frames')[0]['stalls'] == 1


class TestWhereTheRandomnessStarted:
    """A game whose world, loot or bots come out of a generator does not
    replay from its input alone."""

    def test_the_seed_is_in_the_journal(self, context, target):
        from OpenGLContext import entropy

        entropy.reseed(4242)
        telemetry.start(context, target).close()
        assert records(target, 'entropy')[0]['seed'] == 4242

    def test_the_header_names_it_too_so_the_first_line_says_it(
            self, context, target):
        from OpenGLContext import entropy

        entropy.reseed(4242)
        telemetry.start(context, target).close()
        assert records(target, 'header')[0]['seed'] == 4242

    def test_where_the_ordinary_generators_had_got_to_is_kept(
            self, context, target):
        """A game that seeded itself, or that has been drawing since before
        the recording began, is not described by a seed."""
        telemetry.start(context, target).close()
        found = records(target, 'entropy')[0]
        assert found['random']
        assert found['numpy']

    def test_a_replay_starts_from_the_same_numbers(self, context, target):
        import random

        from OpenGLContext import entropy

        session = telemetry.start(context, target)
        expected = [random.random() for _ in range(3)]
        context.OnDraw()
        session.close()

        random.seed(0)                      # somewhere else entirely
        entropy.forget()
        driver = telemetry.start_replay(FakeContext(), target)
        try:
            assert [random.random() for _ in range(3)] == expected
        finally:
            driver.close()

    def test_a_replay_takes_the_recorded_seed_for_its_own(self, context, target):
        from OpenGLContext import entropy

        entropy.reseed(4242)
        session = telemetry.start(context, target)
        context.OnDraw()
        session.close()

        entropy.reseed(1)
        driver = telemetry.start_replay(FakeContext(), target)
        try:
            assert entropy.seed() == 4242
        finally:
            driver.close()

    def test_a_journal_with_no_entropy_in_it_still_replays(self, tmp_path):
        """A file from before this was recorded, or one cut off early."""
        import json

        target = tmp_path / 'old.jsonl'
        target.write_text('\n'.join(json.dumps(record) for record in [
            {'kind': 'header', 'version': 1},
            {'kind': 'frames', 'frame': 0, 't': 0.0, 'ms': [16.0]}]))
        driver = telemetry.start_replay(FakeContext(), target)
        assert driver is not None
        driver.close()
