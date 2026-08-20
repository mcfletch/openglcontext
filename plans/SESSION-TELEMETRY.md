# Session telemetry: recording a session so a failure can be read back and re-run

## The problem

A game fails on somebody else's machine. What reaches the developer is a
sentence -- "it froze in the tunnel", "it crashed after about ten minutes", "the
car went through the wall when I braked" -- and a traceback if they were lucky
enough to be running from a terminal. Everything that would identify it is gone:
which keys were down, where the pointer was, how the frame times were behaving
just before, which map was loaded, what the driver reported itself as.

The engine already measures most of it and throws all of it away.
[`framecounter`](../OpenGLContext/framecounter.py) keeps ninety frames,
[`looptrace`](../OpenGLContext/looptrace.py) keeps a hundred and twenty, the
developer overlay describes the whole application to the screen and to nowhere
else, and [`stalltrace`](../OpenGLContext/stalltrace.py) writes a file -- but
only about slow periods, and only about the stacks inside them. Input is not
recorded anywhere at all, which is the half a developer cannot reconstruct by
reasoning: a bug that needs a particular key held while a particular button is
clicked at a particular place is not going to be found by staring at a
traceback.

And a recording that can only be *read* still leaves the developer trying to
reproduce by hand. What is wanted is a file that can be **run again**.

## What this builds

**One journal per session**, switched on with an environment variable or one
call, holding everything the engine already knows:

- every input the platform delivered -- keys, characters, buttons, wheel,
  pointer motion, resizes -- in the order and at the frame it arrived,
- every frame's wall-clock time, the time inside `OnDraw`, and the loop-phase
  breakdown where the backend measures one,
- every exception, from the main thread, from any other thread, and from
  anything that logged one, with its traceback,
- warnings and errors from `logging`,
- the developer overlay's own description of the application, sampled
  periodically -- which is how a game gets its map name, its player position and
  its own counters into the file without writing a second description that can
  drift from the first,
- application marks: `context.telemetry.mark('level-loaded', map='ztn3dm1')`,
- and **where the randomness started** -- the session's seed, and where the
  ordinary `random` and `numpy.random` generators stood.

**And it replays.** Pointed at a journal, a game re-delivers the recorded input
on the frame it originally arrived on, with the engine's time source driven from
the recorded frame times and its generators put back where they were, so a
session that is a function of its input, its clock and its luck runs again
exactly as it ran. That is the difference between a bug report and a test
case.

## The shape

### `OpenGLContext/events/synthetic.py` -- an input event as a plain record

One vocabulary for "an input event as data", used by three things that had been
inventing their own: the recorder writing them down, the replay putting them
back, and
[`testing/event_injector.py`](../OpenGLContext/testing/event_injector.py), which
already had a JSON spelling for exactly this and now shares it rather than
duplicating it.

`describe(event)` turns an engine event into a record; `build(record)` turns it
back into an engine event; `dispatch(context, record)` delivers it the way the
platform would have -- a pointer event through `addPickEvent` and the selection
pass, a key through `ProcessEvent`, pointer motion through
`recordPointerMotion`.

### `OpenGLContext/entropy.py` -- where the randomness starts

A game whose world, loot, weapon spread or bot decisions come out of a random
number generator does not replay from its input alone: the same keys pressed
against a different sequence of numbers give a different game. So a session has
a **seed**, this module owns it, and everything in the engine that would
otherwise have drawn from nowhere in particular draws from a **named stream**
derived from it -- `entropy.generator('trees')`, `entropy.randomizer('bots')`.
Streams are the point rather than a convenience: two subsystems drawing from
differently-named ones cannot disturb each other's sequence, so adding a third
does not change what the first two produce, and a seeded world stays the same
world as the engine grows.

`OPENGLCONTEXT_SEED` fixes a whole session, the ordinary `random` and
`numpy.random` generators included -- which matters well beyond a replay: a
reference image of a scene that scatters vegetation or throws sparks is
deterministic under a pinned seed.

**Asking for a seed is what seeds those generators.** Left alone the module
chooses a session seed for its own streams and touches neither: a library that
reseeded the process's generators behind its caller's back would silently undo
an application's own `random.seed(...)`, and it would make recording change the
session it records. A recording writes down *where those generators had got to*
instead, which also covers the game that seeded itself before the recording
began; a replay puts the seed and both states back before the context builds
anything, because a world generated from different numbers is a different world
for the recorded input to arrive in.

Three unseeded generators in the engine now draw from session streams:
`ParticlePool` with no `seed` field of its own, ambient audio's repeat jitter,
and `NavMesh.random_point()`. Each still looks different every time the game is
played and repeats exactly when a session is replayed.

### `OpenGLContext/telemetry/` -- the journal

- `recorder.py` -- `SessionRecorder`: **the whole of the logic, with no GL, no
  window and no file in it.** What is worth writing down, how a frame's records
  are grouped, which of them collapse (a hundred pointer positions inside one
  frame are one position), when a block of frame times is closed. It is handed a
  `write` callable and a clock, which is what lets every rule in it be tested
  against exact numbers rather than sampled ones.
- `journal.py` -- `SessionJournal`: JSON-lines to a file, a header naming the
  session, a size ceiling past which the ordinary traffic stops and exceptions
  and marks keep going, and a failed write disabling the journal rather than the
  game.
- `record.py` -- the wiring: taps on the context's input entry points, the
  exception hooks, the logging handler, and `close()`.
- `replay.py` -- `Recording` (a journal read back), `RecordedClock` (the engine
  time source driven from recorded frame times) and `Replay` (delivering each
  frame's input before that frame is drawn).
- `report.py` -- `python -m OpenGLContext.telemetry <file>`.

### Why the taps are instance-level

Recording has to see **what the platform delivered**, before anything in the
engine has had a chance to sink it: an event an overlay swallowed is still an
event the player produced, and a replay that never delivers it does not
reproduce the session. The entry points -- `ProcessEvent`, `addPickEvent`,
`recordPointerMotion`, `OnResize`, `OnDraw` -- are each overridden by a mixin
somewhere, so "before anything in the engine" is above the whole class
hierarchy, which is exactly what an attribute on the instance is. A tap is
installed only when telemetry is on, so a game that is not recording pays
nothing at all.

## Configuration

| Variable | Effect |
| --- | --- |
| `OPENGLCONTEXT_TELEMETRY` | Record this session to the named file. `1` (or `auto`) writes to a dated file under the user's application-data directory. |
| `OPENGLCONTEXT_TELEMETRY_REPLAY` | Replay the named journal into this session instead of taking live input. |
| `OPENGLCONTEXT_TELEMETRY_MAX_MB` | Ceiling on the journal, in megabytes (default 128). |
| `OPENGLCONTEXT_SEED` | Fix this session's randomness, the ordinary `random` and `numpy.random` generators included. |

A game switches it on for itself with `context.startTelemetry(path)`, which is
what a "send a bug report" menu item would call.

All four are in `renderoptions.ENVIRONMENT`, so a subprocess capture does not
inherit them: a journal names one file for one session, and a child process that
took the name over would overwrite its parent's; a replay drives the camera and
would make a reference image depend on a recording; and a seed decides where the
vegetation stands, so a capture that wants a fixed sequence pins it.

## Status

**✅ Complete.**

Modules: `OpenGLContext/telemetry/` (`recorder.py`, `journal.py`, `record.py`,
`replay.py`, `report.py`, `__main__.py`), `OpenGLContext/entropy.py` and
`OpenGLContext/events/synthetic.py`.
`Context.setupEntropy` (before `DoInit`, so a pinned seed is in force by the
time the first world is built), `Context.setupTelemetry` / `startTelemetry` /
`stopTelemetry`, closing on `OnQuit` and on the GLFW main loop's exit. `LoopTrace.last` — the most recently
*completed* iteration, since a caller inside an open one cannot be told about
that one. `telemetry_provider` and the **Session** section on the developer
overlay. `renderoptions.ENVIRONMENT` gained the four variables. `ParticlePool`,
`AudioEmitter`'s repeat jitter and `NavMesh.random_point` draw from session
streams where they drew from nowhere.
`testing/event_injector.py` now speaks `synthetic` rather than its own dialect,
and an injected key reaches `ProcessEvent` — so it passes the overlay and the
movement sampler on the way in, as a real key does.

Docs: [docs/telemetry.html](../docs/telemetry.html), indexed from
`documentation.html` and cross-linked from `hud.html`; the environment section
of [CLAUDE.md](../CLAUDE.md).

Tests, Red/Green throughout, 195 of them at 99% of the new code: 35 for the
recorder against an injected clock (frame stamping, the collapse of a run of
pointer positions and what stops it, block arithmetic, marks, exceptions, the
ending), 14 for the journal (its ceiling, an unwritable path, a record that
will not serialise, a file that goes away mid-session), 19 for the replay
reader and clock, 44 for the wiring (the taps, the exception hooks, the logging
relay, the environment switches, the stall threshold, the recorded randomness,
and a context left as it was found), 30 for the seed and its streams --
including a whole context short of its window, to pin that a seed named in the
environment is in force before the application builds a world -- 21 for
the input vocabulary's round trip and delivery, 25 for the report and the
overlay section, and 7 driving a session through the real movement mixin and
replaying it into a second context -- including one whose every frame draws a
random number, with the paired test that shows those numbers do differ without
the recording.

Verified on real GLFW as well: a scripted session recorded and replayed hit the
same frames, and a session that raised part-way through kept the traceback, the
mark, the logged warning and the frame times, with the ending recorded as
`exception`. That last one is what `close()` consulting `sys.exc_info()` is
for: a main loop closes its recording from a `finally`, and every exception
hook runs after every `finally` has already emptied the journal.

**Limits, and where they would be lifted.** A replay is exact to the extent
that the session was a function of its input, the engine's clock and the
recorded randomness. What is left outside: an application reading `time.time()`
for itself rather than `systemtime.systemTime()`, and a generator it builds for
itself rather than asking `entropy.generator()` for -- its own
`numpy.random.default_rng()` seeded from the clock is on neither the recorded
seed nor the recorded states. Both are a matter of an application using the
engine's own source, which is what the documentation asks for. The phase
breakdown recorded with a block comes from the most recently completed loop
iteration, so within a block it lags by one frame; blocks are summed over sixty
frames, where that is immaterial.
