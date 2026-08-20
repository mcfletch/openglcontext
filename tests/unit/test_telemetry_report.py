"""Reading a session journal as a report.

A journal is not meant to be read by eye: it is a line per frame block and a
line per input.  The report is what answers "what happened in this session" --
how long it ran, how it ended, what went wrong and what the player was doing
when it did.
"""


from OpenGLContext.telemetry import report
from OpenGLContext.telemetry.replay import Recording


def session(*records):
    return Recording([
        {'kind': 'header', 'version': 1, 'started': '2026-08-20T10:00:00+00:00',
         'argv': ['twig-bb', 'ztn3dm1'], 'pid': 4242,
         'python': '3.12.3', 'platform': 'linux'},
    ] + list(records))


FRAMES = {'kind': 'frames', 'frame': 0, 't': 0.0,
          'ms': [16.0, 16.0, 800.0, 16.0], 'stalls': 1,
          'phases_ms': {'idle': 780.0, 'render': 60.0}}


class TestTheSummary:
    def test_it_says_what_was_running(self):
        found = report.describe(session(FRAMES))
        assert 'twig-bb ztn3dm1' in found

    def test_it_says_how_long_and_how_fast(self):
        found = report.describe(session(FRAMES))
        assert '4 frames' in found
        assert '0.8s' in found

    def test_the_worst_frame_is_named_beside_the_median(self):
        """A healthy median next to a tenfold worst is the whole diagnosis."""
        found = report.describe(session(FRAMES))
        assert '16.0ms' in found
        assert '800.0ms' in found

    def test_where_the_worst_time_went(self):
        assert 'idle' in report.describe(session(FRAMES))

    def test_a_session_with_no_frames_is_still_readable(self):
        assert report.describe(session())


class TestTheSeed:
    """A seed is the one number that says which of the possible sessions this
    was, and the first thing somebody re-running it needs."""

    def test_it_is_on_the_first_lines_where_a_reader_looks(self):
        found = report.describe(Recording([
            {'kind': 'header', 'version': 1, 'argv': ['twig-bb'],
             'seed': 4242},
            {'kind': 'entropy', 'seed': 4242, 'random': [3, [1, 2], None]},
        ]))
        assert 'seed 4242' in found

    def test_a_session_that_recorded_none_says_nothing_about_it(self):
        assert 'seed' not in report.describe(session(FRAMES))


class TestWhatWentWrong:
    def test_an_exception_is_shown_with_its_traceback(self):
        found = report.describe(session(
            {'kind': 'exception', 't': 12.5, 'frame': 700,
             'type': 'ValueError', 'message': 'the wheels came off',
             'fatal': True,
             'traceback': ['Traceback (most recent call last):',
                           '  File "game.py", line 4, in step',
                           'ValueError: the wheels came off']}))
        assert 'ValueError: the wheels came off' in found
        assert 'game.py' in found

    def test_it_says_when_and_on_which_frame(self):
        found = report.describe(session(
            {'kind': 'exception', 't': 12.5, 'frame': 700, 'type': 'ValueError',
             'message': 'boom', 'traceback': []}))
        assert 'frame 700' in found

    def test_warnings_are_gathered_rather_than_listed_one_by_one(self):
        found = report.describe(session(*[
            {'kind': 'log', 't': index, 'frame': index, 'level': 'WARNING',
             'logger': 'twig_bb.game', 'message': 'no spawn point'}
            for index in range(40)]))
        assert '40' in found
        assert found.count('no spawn point') == 1


class TestWhatThePlayerWasDoing:
    def test_the_input_is_counted_by_kind(self):
        found = report.describe(session(
            {'kind': 'input', 't': 0.1, 'frame': 0, 'type': 'keyboard',
             'key': 'w', 'state': 1},
            {'kind': 'input', 't': 0.2, 'frame': 1, 'type': 'pointer',
             'x': 1, 'y': 2},
            {'kind': 'input', 't': 0.3, 'frame': 2, 'type': 'pointer',
             'x': 3, 'y': 4}))
        assert 'keyboard 1' in found
        assert 'pointer 2' in found

    def test_the_timeline_is_left_out_unless_it_is_asked_for(self):
        records = session({'kind': 'input', 't': 0.1, 'frame': 0,
                           'type': 'keyboard', 'key': 'w', 'state': 1})
        assert "key 'w'" not in report.describe(records)
        assert "key 'w'" in report.describe(records, events=True)

    def test_marks_are_the_line_a_reader_looks_for_first(self):
        found = report.describe(session(
            {'kind': 'mark', 't': 3.2, 'frame': 190, 'name': 'level-loaded',
             'fields': {'map': 'ztn3dm1'}}))
        assert 'level-loaded' in found
        assert 'ztn3dm1' in found

    def test_the_application_s_own_description_is_shown_at_the_end(self):
        found = report.describe(session(
            {'kind': 'state', 't': 5.0, 'frame': 300,
             'sections': {'Player': {'health': '100', 'position': '1 2 3'}}}))
        assert 'health' in found

    def test_a_truncated_journal_says_so(self):
        found = report.describe(session({'kind': 'truncated', 'bytes': 1024}))
        assert 'truncated' in found.lower()


class TestTheCommand:
    def test_it_reads_a_file_and_prints_it(self, tmp_path, capsys):
        import json
        target = tmp_path / 'session.jsonl'
        target.write_text('\n'.join(json.dumps(record) for record in [
            {'kind': 'header', 'version': 1, 'argv': ['twig-bb']}, FRAMES]))
        assert report.main([str(target)]) == 0
        assert 'twig-bb' in capsys.readouterr().out

    def test_a_file_that_is_not_there_is_reported_rather_than_traced(
            self, tmp_path, capsys):
        assert report.main([str(tmp_path / 'nothing.jsonl')]) == 1


class TestTheOverlaySection:
    """A session being recorded says so on the developer overlay: a player
    told to "turn recording on and reproduce it" needs to see that it is."""

    def test_there_is_no_section_when_nothing_is_being_recorded(self):
        from OpenGLContext.ui.debugoverlay import telemetry_provider

        class Context:
            telemetry = None

        assert telemetry_provider(Context())() == []

    def test_a_recording_shows_its_file_and_how_far_it_has_got(self, tmp_path):
        from OpenGLContext import telemetry
        from OpenGLContext.ui.debugoverlay import telemetry_provider

        class Context:
            telemetry = None

            def OnDraw(self, force=1):
                return 1

        context = Context()
        session = telemetry.start(context, tmp_path / 'session.jsonl')
        try:
            context.OnDraw()
            rows = dict(telemetry_provider(context)())
            assert rows['recording'] == 'session.jsonl'
            assert rows['frames'] == 1
        finally:
            session.close()

    def test_a_recording_shows_the_seed_it_can_be_run_again_from(self, tmp_path):
        from OpenGLContext import entropy, telemetry
        from OpenGLContext.ui.debugoverlay import telemetry_provider

        class Context:
            telemetry = None

        entropy.reseed(4242)
        context = Context()
        session = telemetry.start(context, tmp_path / 'session.jsonl')
        try:
            assert dict(telemetry_provider(context)())['seed'] == 4242
        finally:
            session.close()

    def test_a_replay_shows_how_far_through_the_recording_it_is(self, tmp_path):
        from OpenGLContext import telemetry
        from OpenGLContext.ui.debugoverlay import telemetry_provider

        class Context:
            telemetry = None

            def OnDraw(self, force=1):
                return 1

        recorded = Context()
        session = telemetry.start(recorded, tmp_path / 'session.jsonl')
        for _ in range(4):
            recorded.OnDraw()
        session.close()

        playing = Context()
        driver = telemetry.start_replay(playing, tmp_path / 'session.jsonl')
        try:
            playing.OnDraw()
            rows = dict(telemetry_provider(playing)())
            assert rows['replaying'] == 'session.jsonl'
            assert rows['frame'] == '1/4'
        finally:
            driver.close()


class TestWhenThereIsTooMuchToShow:
    def test_the_exceptions_beyond_the_limit_are_counted(self):
        found = report.describe(session(*[
            {'kind': 'exception', 't': index, 'frame': index,
             'type': 'ValueError', 'message': 'boom', 'traceback': []}
            for index in range(5)]), limit=2)
        assert 'and 3 more' in found

    def test_the_marks_beyond_the_limit_are_counted(self):
        found = report.describe(session(*[
            {'kind': 'mark', 't': index, 'frame': index, 'name': 'tick'}
            for index in range(5)]), limit=2)
        assert 'and 3 more' in found


class TestTheEventTimeline:
    def test_a_resize_reads_as_a_size(self):
        found = report.describe(session(
            {'kind': 'input', 't': 0.0, 'frame': 0, 'type': 'resize',
             'width': 800, 'height': 600}), events=True)
        assert '800x600' in found

    def test_an_input_the_report_has_no_shape_for_still_appears(self):
        found = report.describe(session(
            {'kind': 'input', 't': 0.0, 'frame': 0, 'type': 'pointer-origin'}),
            events=True)
        assert 'pointer-origin' in found
