"""The viewer's running commentary, and the characters a console cannot hold.

The viewer narrates what it is doing -- which file it is loading, how many
cameras it found, which animation is playing. Every one of those lines carries
text that came from somewhere else: a path someone typed, a URL, a name an
author put in a glTF file. All of it is arbitrary Unicode.

A console is not. On Windows ``sys.stdout`` encodes to the console's codepage,
which holds a couple of hundred characters, and writing anything else to it
raises. These pin that a character the console cannot hold costs the reader
that character and nothing else.
"""
import io
import sys

from OpenGLContext.viewer import commentary


def _console(encoding='cp1252'):
    """A stdout that encodes the way a Windows console does."""
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding, newline='')


def _written(stream, encoding='cp1252'):
    stream.flush()
    return stream.buffer.getvalue().decode(encoding)


class TestSay:
    def test_text_the_console_holds_is_written_as_it_is(self, monkeypatch):
        stream = _console()
        monkeypatch.setattr(sys, 'stdout', stream)
        commentary.say('Found 3 camera(s); PageUp/PageDown to cycle.\n')
        assert _written(stream) == 'Found 3 camera(s); PageUp/PageDown to cycle.\n'

    def test_a_character_it_cannot_hold_is_escaped_rather_than_raised(self, monkeypatch):
        """The Khronos sample named with a heart and a recycling symbol: the
        line is worth losing two characters over, and the render is not worth
        losing at all."""
        stream = _console()
        monkeypatch.setattr(sys, 'stdout', stream)
        commentary.say('Loading Unicode❤♻Test.glb ...\n')
        written = _written(stream)
        assert written.startswith('Loading Unicode')
        assert written.endswith('Test.glb ...\n')
        assert '\\u2764' in written and '\\u267b' in written

    def test_a_console_that_holds_everything_gets_the_characters_themselves(
            self, monkeypatch):
        stream = _console('utf-8')
        monkeypatch.setattr(sys, 'stdout', stream)
        commentary.say('Loading Unicode❤♻Test.glb ...\n')
        assert _written(stream, 'utf-8') == 'Loading Unicode❤♻Test.glb ...\n'

    def test_it_reaches_the_reader_before_the_next_thing_happens(self, monkeypatch):
        """Progress said after the load it describes is not progress."""
        stream = _console()
        monkeypatch.setattr(sys, 'stdout', stream)
        commentary.say('Loading a model that takes a minute ...\n')
        assert stream.buffer.getvalue()          # without a flush of our own

    def test_no_stdout_at_all_is_not_an_error(self, monkeypatch):
        """A frozen bundle built without a console has ``sys.stdout`` of None."""
        monkeypatch.setattr(sys, 'stdout', None)
        commentary.say('Loading something ...\n')

    def test_it_is_written_to_whatever_stdout_is_at_the_time(self, monkeypatch):
        """Captured output, a log window, a pipe -- the stream is looked up per
        call rather than bound once, so redirecting stdout redirects this."""
        first, second = _console(), _console()
        monkeypatch.setattr(sys, 'stdout', first)
        commentary.say('one\n')
        monkeypatch.setattr(sys, 'stdout', second)
        commentary.say('two\n')
        assert _written(first) == 'one\n'
        assert _written(second) == 'two\n'


class TestWarn:
    """The same for what goes to stderr, where it matters more.

    A path someone typed is exactly the text most likely to hold a character
    the console lacks, and "file not found" is exactly the message that has to
    survive being about one.
    """

    def test_it_goes_to_stderr(self, monkeypatch):
        out, err = _console(), _console()
        monkeypatch.setattr(sys, 'stdout', out)
        monkeypatch.setattr(sys, 'stderr', err)
        commentary.warn('ERROR: file not found: model.glb\n')
        assert _written(out) == ''
        assert _written(err) == 'ERROR: file not found: model.glb\n'

    def test_a_path_it_cannot_hold_still_reports_the_error(self, monkeypatch):
        stream = _console()
        monkeypatch.setattr(sys, 'stderr', stream)
        commentary.warn('ERROR: file not found: C:\\models\\Ünicode❤.glb\n')
        written = _written(stream)
        assert written.startswith('ERROR: file not found: ')
        assert written.endswith('.glb\n')
        assert 'Ü' in written              # cp1252 has this one
        assert '\\u2764' in written        # and not this one

    def test_no_stderr_at_all_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(sys, 'stderr', None)
        commentary.warn('ERROR: something\n')


class TestTheViewerSaysThingsThroughIt:
    """A bare write to a console stream is the defect this module exists to end."""

    def test_the_scene_viewer_writes_to_neither_stream_directly(self):
        from OpenGLContext.viewer import sceneviewer
        with open(sceneviewer.__file__, encoding='utf-8') as handle:
            source = handle.read()
        assert 'sys.stdout.write' not in source
        assert 'sys.stderr.write' not in source
