"""A session journal as a report.

A journal is not meant to be read by eye: a line per block of frame times and a
line per input, several thousand of them for a few minutes of play.  This
answers the question somebody actually has -- *what happened in this session* --
in the order they want it: what was running, how long it lasted and how it
ended, what went wrong, and what the player was doing when it did.

    python -m OpenGLContext.telemetry /tmp/session.jsonl
    python -m OpenGLContext.telemetry /tmp/session.jsonl --events
"""

from __future__ import annotations

import collections
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from OpenGLContext.telemetry.replay import Recording

__all__ = ['describe', 'main']


def describe(recording: Recording, events: bool = False,
             limit: int = 10) -> str:
    """One session as text, for a terminal.

    events -- list every input in order, rather than counting them by kind. A
        few minutes of play is a few thousand of them, so it is off by default:
        the counts say whether the player was moving, and the timeline says
        what they did, which is a question you ask once you have a frame to ask
        it about.
    limit -- how many exceptions, marks and distinct warnings to show.
    """
    lines: List[str] = []
    lines.extend(_session(recording))
    lines.extend(_frames(recording))
    lines.extend(_failures(recording, limit))
    lines.extend(_marks(recording, limit))
    lines.extend(_input(recording, events))
    lines.extend(_state(recording))
    return '\n'.join(lines)


def _session(recording: Recording) -> List[str]:
    header = recording.header
    summary = recording.summary()
    argv = ' '.join(str(word) for word in header.get('argv', ())) or '-'
    lines = ['%s  %s' % (header.get('started', '-'), argv)]
    where = ['pid %s' % (header.get('pid', '-'),),
             'python %s' % (header.get('python', '-'),),
             str(header.get('platform', '-'))]
    definition = header.get('definition') or {}
    if definition.get('size'):
        where.append('%sx%s' % tuple(definition['size'][:2]))
    if definition.get('profile'):
        where.append(str(definition['profile']))
    if header.get('seed') is not None:
        # The one number that says which of the possible sessions this was, and
        # the first thing somebody re-running it wants: OPENGLCONTEXT_SEED.
        where.append('seed %s' % (header['seed'],))
    lines.append('  ' + ', '.join(where))
    if summary.get('reason'):
        lines.append('  ended: %s' % (summary['reason'],))
    else:
        lines.append('  ended: no ending was written -- the session was killed '
                     'or is still running')
    if recording.truncated:
        lines.append('  NOTE: the journal was truncated at its ceiling; input '
                     'and frame times stop part-way through')
    return lines


def _frames(recording: Recording) -> List[str]:
    summary = recording.summary()
    if not summary['frames']:
        return ['', 'no frames were recorded']
    lines = [
        '',
        '%d frames in %.1fs, %.1f fps' % (
            summary['frames'], summary['seconds'], summary['fps']),
        '  median %.1fms, worst %.1fms, %d stalls' % (
            summary['median_ms'], summary['worst_ms'], summary['stalls']),
    ]
    phases: Dict[str, float] = collections.defaultdict(float)
    for block in recording.blocks:
        for name, milliseconds in (block.get('phases_ms') or {}).items():
            phases[name] += float(milliseconds)
    if phases:
        lines.append('  where the time went: ' + ', '.join(
            '%s %.0fms' % (name, total) for name, total
            in sorted(phases.items(), key=lambda pair: -pair[1])))
    return lines


def _failures(recording: Recording, limit: int) -> List[str]:
    lines: List[str] = []
    if recording.exceptions:
        lines.append('')
        lines.append('%d exception(s):' % (len(recording.exceptions),))
        for record in recording.exceptions[:limit]:
            lines.append('  %s  frame %s%s' % (
                _stamp(record), record.get('frame', '-'),
                '  (fatal)' if record.get('fatal') else ''))
            for line in record.get('traceback') or ['%s: %s' % (
                    record.get('type'), record.get('message'))]:
                lines.append('    ' + line)
        if len(recording.exceptions) > limit:
            lines.append('  ... and %d more'
                         % (len(recording.exceptions) - limit,))
    if recording.messages:
        # Gathered by what was logged rather than listed: one warning repeated
        # every frame is one thing wrong, and a page of it hides the others.
        counted = collections.Counter(
            (record.get('level'), record.get('logger'), record.get('message'))
            for record in recording.messages)
        lines.append('')
        lines.append('%d logged warning(s) and error(s), %d distinct:' % (
            len(recording.messages), len(counted)))
        for (level, logger, message), count in counted.most_common(limit):
            lines.append('  %sx %s %s: %s' % (count, level, logger, message))
    return lines


def _marks(recording: Recording, limit: int) -> List[str]:
    if not recording.marks:
        return []
    lines = ['', '%d mark(s):' % (len(recording.marks),)]
    for record in recording.marks[:limit]:
        fields = ' '.join('%s=%s' % pair
                          for pair in (record.get('fields') or {}).items())
        lines.append(('  %s  frame %s  %s %s' % (
            _stamp(record), record.get('frame', '-'),
            record.get('name', '-'), fields)).rstrip())
    if len(recording.marks) > limit:
        lines.append('  ... and %d more' % (len(recording.marks) - limit,))
    return lines


def _input(recording: Recording, events: bool) -> List[str]:
    if not recording.inputs:
        return ['', 'no input was recorded']
    counted = collections.Counter(record.get('type')
                                  for record in recording.inputs)
    lines = ['', 'input: %d events -- %s' % (
        len(recording.inputs),
        ', '.join('%s %d' % (name, count)
                  for name, count in counted.most_common()))]
    if events:
        for record in recording.inputs:
            lines.append('  %s  frame %-6s %s' % (
                _stamp(record), record.get('frame', '-'), _oneEvent(record)))
    return lines


def _oneEvent(record: Dict[str, Any]) -> str:
    kind = record.get('type')
    if kind in ('keyboard', 'keypress'):
        return '%-11s key %r%s' % (
            kind, record.get('key'),
            '' if kind == 'keypress'
            else (' down' if record.get('state') else ' up'))
    if kind == 'mousebutton':
        return '%-11s button %s %s at %s,%s' % (
            kind, record.get('button'),
            'down' if record.get('state') else 'up',
            record.get('x'), record.get('y'))
    if kind in ('pointer', 'mousemove'):
        return '%-11s %s,%s' % (kind, record.get('x'), record.get('y'))
    if kind == 'resize':
        return '%-11s %sx%s' % (kind, record.get('width'), record.get('height'))
    return str(kind)


def _state(recording: Recording) -> List[str]:
    """The last description the application gave of itself.

    Last rather than every one: a session samples it every few seconds, and
    what is wanted from a report is where things had got to.  The earlier
    samples are in the file for anyone following a value over time.
    """
    if not recording.states:
        return []
    record = recording.states[-1]
    lines = ['', 'the application at %s (frame %s), %d sample(s) in the file:'
             % (_stamp(record), record.get('frame', '-'),
                len(recording.states))]
    for title, rows in (record.get('sections') or {}).items():
        lines.append('  %s: %s' % (title, ', '.join(
            '%s=%s' % pair for pair in rows.items())))
    return lines


def _stamp(record: Dict[str, Any]) -> str:
    """A record's time as minutes and seconds into the session."""
    seconds = float(record.get('t', 0.0))
    return '%2d:%06.3f' % (int(seconds // 60), seconds % 60)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Print a session journal as a report."""
    import argparse

    parser = argparse.ArgumentParser(
        prog='python -m OpenGLContext.telemetry',
        description='Report what happened in a recorded session.')
    parser.add_argument('path', help='a file written by OPENGLCONTEXT_TELEMETRY')
    parser.add_argument('--events', action='store_true',
                        help='list every input in order, not just the counts')
    parser.add_argument('--limit', type=int, default=10,
                        help='how many exceptions, marks and distinct warnings '
                             'to show (default: 10)')
    options = parser.parse_args(argv)

    if not Path(options.path).exists():
        sys.stderr.write('no such session journal: %s\n' % (options.path,))
        return 1
    recording = Recording.read(options.path)
    sys.stdout.write(describe(recording, events=options.events,
                              limit=options.limit) + '\n')
    return 0
