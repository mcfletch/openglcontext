"""Recording a session so a failure can be read back -- and run again.

A game fails on somebody else's machine, and what reaches the developer is a
sentence: "it froze in the tunnel", "it crashed after about ten minutes".
Everything that would identify it is gone -- which keys were down, where the
pointer was, how the frame times had been behaving, which map was loaded, what
the driver called itself.  The engine measures nearly all of it and keeps none
of it: the frame counter holds ninety frames, the loop trace a hundred and
twenty, the developer overlay describes the whole application to the screen and
to nowhere else, and input is not recorded anywhere at all.

This records a whole session to one file:

- every input the platform delivered -- keys, characters, buttons, the wheel,
  pointer motion, resizes -- against the frame that acted on it,
- every frame's wall-clock time, the time inside the draw, and the loop's phase
  breakdown where the backend measures one,
- every exception, from the main thread, from any other thread, and from
  anything that logged one, with its traceback,
- warnings and errors from :mod:`logging`,
- the developer overlay's own description of the application, sampled every few
  seconds, which is how a game's map, player and counters reach the file
  without a second description that can drift from the first,
- and whatever the game marks: ``context.telemetry.mark('level-loaded',
  map='ztn3dm1')``.

Switching it on::

    OPENGLCONTEXT_TELEMETRY=/tmp/session.jsonl python -m twig_bb

or from the application, which is what a "send a bug report" menu item calls::

    context.startTelemetry('/tmp/session.jsonl')

Reading it back::

    python -m OpenGLContext.telemetry /tmp/session.jsonl

**And running it again**, which is the point of recording input against frames::

    OPENGLCONTEXT_TELEMETRY_REPLAY=/tmp/session.jsonl python -m twig_bb

The same keys and the same clicks in the same places arrive on the same frames,
with the engine's clock (:mod:`OpenGLContext.events.systemtime`) driven from the
recorded frame times, so a session that is a function of its input and its clock
runs again as it ran.  A game that reads ``time.time()`` for itself or seeds
from the system random source replays approximately rather than exactly --
close enough to walk into the same wall, which is usually the whole of what is
wanted.

Nothing is recorded unless asked for, and the taps that do the recording are
installed only then, so a shipped game that nobody has switched this on for
pays nothing at all.

The pieces: :mod:`~OpenGLContext.telemetry.recorder` holds every rule about
what is worth writing down and touches no file; :mod:`~OpenGLContext.telemetry.journal`
is the file; :mod:`~OpenGLContext.telemetry.record` is the wiring;
:mod:`~OpenGLContext.telemetry.replay` reads a journal and runs it;
:mod:`~OpenGLContext.telemetry.report` prints one.  The vocabulary an input is
written down in is :mod:`OpenGLContext.events.synthetic`, shared with the test
event injector.
"""

from OpenGLContext.telemetry.journal import (DEFAULT_MAX_BYTES, SessionJournal,
                                             default_path)
from OpenGLContext.telemetry.record import (MAX_MB_ENV, REPLAY_ENV,
                                            ReplaySession, SessionRecording,
                                            TELEMETRY_ENV, Tap, install, start,
                                            start_replay)
from OpenGLContext.telemetry.recorder import SessionRecorder
from OpenGLContext.telemetry.replay import Recording, RecordedClock, Replay

__all__ = ['DEFAULT_MAX_BYTES', 'MAX_MB_ENV', 'REPLAY_ENV', 'Recording',
           'RecordedClock', 'Replay', 'ReplaySession', 'SessionJournal',
           'SessionRecorder', 'SessionRecording',
           'TELEMETRY_ENV', 'Tap', 'default_path', 'install', 'start',
           'start_replay']
