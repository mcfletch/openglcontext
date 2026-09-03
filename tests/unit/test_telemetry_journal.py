"""The file a session recorder writes into, and what happens when it cannot.

A journal is diagnostic equipment: a disk that fills, a directory that is not
writable or a path that was never valid must cost the recording and never the
game that is being recorded.
"""

import sys
import json


from OpenGLContext.telemetry.journal import SessionJournal


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestTheFile:
    def test_the_first_line_names_the_session(self, tmp_path):
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target, header={'application': 'twig-bb'})
        journal.close()
        first = lines(target)[0]
        assert first['kind'] == 'header'
        assert first['application'] == 'twig-bb'
        assert first['started']

    def test_a_record_is_one_line_of_json(self, tmp_path):
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target)
        journal({'kind': 'mark', 'name': 'hello'})
        journal.close()
        assert lines(target)[-1] == {'kind': 'mark', 'name': 'hello'}

    def test_each_record_is_on_disk_before_the_next_one_is_offered(self, tmp_path):
        """A game killed with -9 keeps everything written up to the moment."""
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target)
        journal({'kind': 'mark', 'name': 'first'})
        assert len(lines(target)) == 2
        journal.close()

    def test_the_directory_is_made_if_it_is_missing(self, tmp_path):
        target = tmp_path / 'deep' / 'down' / 'session.jsonl'
        SessionJournal(target).close()
        assert target.exists()


class TestWhenItCannotWrite:
    def test_an_unwritable_path_disables_the_journal_rather_than_raising(
            self, tmp_path):
        blocked = tmp_path / 'not-a-directory.jsonl'
        blocked.write_text('this is a file, not a directory')
        journal = SessionJournal(blocked / 'session.jsonl')
        assert journal.disabled
        journal({'kind': 'mark', 'name': 'ignored'})       # must not raise
        journal.close()

    def test_a_value_json_does_not_know_is_written_as_its_text(self, tmp_path):
        """A mark carrying a live object still says which mark it was."""
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target)
        journal({'kind': 'mark', 'name': 'held', 'fields': {'by': object()}})
        journal.close()
        assert lines(target)[1]['fields']['by'].startswith('<object object')

    def test_a_record_that_will_not_serialise_at_all_costs_that_record_only(
            self, tmp_path):
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target)
        circular: dict = {'kind': 'mark', 'name': 'round'}
        circular['fields'] = circular
        journal(circular)
        journal({'kind': 'mark', 'name': 'after'})
        journal.close()
        assert [record.get('name') for record in lines(target)[1:]] == ['after']


class TestTheCeiling:
    """A session that runs all day must not fill the disk, and the records
    that matter must be the ones that survive."""

    def test_ordinary_traffic_stops_once_the_ceiling_is_reached(self, tmp_path):
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target, max_bytes=200)
        for index in range(200):
            journal({'kind': 'frames', 'frame': index, 'ms': [16.0] * 4})
        journal.close()
        assert target.stat().st_size < 4000

    def test_it_says_in_the_file_that_it_stopped(self, tmp_path):
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target, max_bytes=100)
        for index in range(50):
            journal({'kind': 'frames', 'frame': index, 'ms': [16.0] * 4})
        journal.close()
        assert any(record['kind'] == 'truncated' for record in lines(target))

    def test_exceptions_and_marks_still_get_through(self, tmp_path):
        """The ceiling exists to keep the failure, not to lose it."""
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target, max_bytes=100)
        for index in range(50):
            journal({'kind': 'frames', 'frame': index, 'ms': [16.0] * 4})
        journal({'kind': 'exception', 'type': 'ValueError', 'message': 'boom'})
        journal.close()
        assert any(record['kind'] == 'exception' for record in lines(target))

    def test_the_ending_is_written_however_full_the_file_is(self, tmp_path):
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target, max_bytes=100)
        for index in range(50):
            journal({'kind': 'frames', 'frame': index})
        journal({'kind': 'end', 'frames': 50})
        journal.close()
        assert any(record['kind'] == 'end' for record in lines(target))


#: The variable naming the user's application-data directory on this platform.
#: userpaths follows each platform's own convention -- %APPDATA% on Windows,
#: $XDG_CONFIG_HOME elsewhere -- so a test that redirects it has to say which.
APPDATA_VARIABLE = 'APPDATA' if sys.platform == 'win32' else 'XDG_CONFIG_HOME'


class TestWhereAJournalGoesByDefault:
    def test_it_lands_under_the_user_s_application_data(self, tmp_path,
                                                        monkeypatch):
        from OpenGLContext.telemetry.journal import default_path
        monkeypatch.setenv(APPDATA_VARIABLE, str(tmp_path))
        found = default_path()
        assert found.parent == tmp_path / 'OpenGLContext' / 'telemetry'
        assert found.suffix == '.jsonl'

    def test_two_runs_do_not_write_the_same_file(self, tmp_path, monkeypatch):
        """The interesting session is rarely the one that has just finished."""
        from OpenGLContext.telemetry.journal import default_path
        monkeypatch.setenv(APPDATA_VARIABLE, str(tmp_path))
        assert str(default_path()) != str(default_path('other'))

    def test_nowhere_to_put_it_falls_back_rather_than_failing(self, monkeypatch):
        from OpenGLContext.telemetry import journal as journal_module
        from OpenGLContext import userpaths

        def refuse():
            raise OSError('no home directory')
        monkeypatch.setattr(userpaths, 'appdatadirectory', refuse)
        assert journal_module.default_path().name.endswith('.jsonl')


class TestWhenTheFileGoesAwayMidSession:
    def test_a_failed_write_stops_the_journal_and_not_the_game(self, tmp_path):
        target = tmp_path / 'session.jsonl'
        journal = SessionJournal(target)
        journal._handle.close()                 # as a full disk or a lost mount
        journal({'kind': 'mark', 'name': 'after'})
        assert journal.disabled
        journal({'kind': 'mark', 'name': 'later'})      # must not raise
        journal.close()
