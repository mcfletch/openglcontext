"""The viewer's running commentary on what it is doing.

The scene viewer narrates its work as it goes -- the file it is opening, the
cameras and lights it found in it, the animation it is playing -- and reports
what went wrong when something does. Those lines carry text from outside the
program: a path someone typed, a URL, a name an author wrote into a glTF file.
All of it is arbitrary Unicode.

The streams they go to are not. On Windows ``sys.stdout`` encodes to the
console's codepage, which holds a couple of hundred characters and raises
``UnicodeEncodeError`` on anything else -- so a model in a directory with an
accent in its name, or one of the Khronos samples named with a heart and a
recycling symbol, would end a render with a traceback from the progress message
rather than from the rendering. On the error path it is worse: the message most
likely to be about an unencodable path is ``file not found``, and a traceback
is a poor way to say it.

:func:`say` and :func:`warn` are the two ways this package writes to a console,
and neither can do that. A character the stream has no room for is escaped; the
reader loses the character, which is what a line of commentary is worth, rather
than the render or the error report, which are not.
"""
import sys

__all__ = ['say', 'warn']


def say(text: str) -> None:
    """Write one piece of the viewer's commentary to ``sys.stdout``."""
    _write(sys.stdout, text)


def warn(text: str) -> None:
    """Report to ``sys.stderr`` something the person running this should know."""
    _write(sys.stderr, text)


def _write(stream, text: str) -> None:
    """*text* to *stream*, escaping whatever that stream has no encoding for.

    The stream is passed in by the caller each time rather than held here, so
    output redirected after import -- a test capturing it, an application
    showing it in a window -- is redirected with it. A bundle built with no
    console has no stream at all, and then there is nobody to tell.

    Each line is flushed as it is written: this is progress, and a load that
    takes a minute should say so during the minute rather than after it.
    """
    if stream is None:
        return
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, 'encoding', None) or 'ascii'
        # Round-tripped through the stream's own encoding, so what comes back
        # is by construction something that stream can write.
        stream.write(text.encode(encoding, 'backslashreplace').decode(encoding))
    stream.flush()
