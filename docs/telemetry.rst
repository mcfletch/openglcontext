Session telemetry
=================

.. rst-class:: introduction

A whole session written to one file: every input the platform delivered, every
frame's time, every exception with its traceback, and the application's own
description of itself sampled as it ran. The file is read back with a command,
and it is **replayed** — the same keys and the same clicks in the same places
arrive on the same frames, against the clock the recording kept, so a failure
somebody else met can be run again here.

.. _switching-it-on:

Switching it on
---------------

From outside the application, which is what you ask a player to do:

.. code-block:: bash

   OPENGLCONTEXT_TELEMETRY=/tmp/session.jsonl python -m twig_bb

``1`` (or ``auto``) instead of a path writes a dated, process-stamped file
under the user's application-data directory, so successive runs accumulate
rather than overwriting each other:

.. code-block:: bash

   OPENGLCONTEXT_TELEMETRY=1 python -m twig_bb
   # ~/.config/OpenGLContext/telemetry/session-20260820-143011-4242.jsonl

From inside it, which is what a “report a problem” menu item calls. Recording
can begin at any point in a session; what it holds from then on is a complete
session record less the part before it was asked for:

.. code-block:: python

   self.startTelemetry('/tmp/session.jsonl')   # None for the dated default
   ...
   self.stopTelemetry()

Nothing is recorded unless one of those happens, and the machinery that does
the recording is not installed until then, so an application nobody has
switched it on for pays nothing at all.

.. _what-is-in-it:

What the file holds
-------------------

JSON lines, one record to a line, each on disk before the next is offered — so
a session killed outright, which is how a session being diagnosed usually
ends, keeps everything up to the moment it went.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - ``kind``
     - What it says
   * - ``header``
     - When the session started, the command that started it, the process, the Python
       and platform, the window that was asked for, and every rendering environment
       variable that was set.
   * - ``input``
     - One input the platform delivered — a key, a character, a button, a wheel
       notch, pointer motion, a resize — stamped with the time it arrived and **the
       frame that acted on it**.
   * - ``frames``
     - A block of frames: every frame's wall-clock time, the time inside the draw,
       the loop's phase breakdown where the backend measures one (see :doc:`the loop
       trace <hud>`), and how many crossed the stall threshold.
   * - ``entropy``
     - Where this session's randomness started: its :ref:`seed <randomness>`, and
       where the ordinary ``random`` and ``numpy.random`` generators had got to.
   * - ``exception``
     - An exception and its traceback, from the main thread, from any other thread,
       or from anything that logged one, with the frame the session had reached.
   * - ``log``
     - A warning or error somebody logged, with its logger.
   * - ``state``
     - Every section of the :doc:`developer overlay <hud>`, sampled every few
       seconds. The overlay already knows how to describe the application — the map,
       the player, the renderer's counts, whatever the game registered — so the
       recording gets all of it without a second description that can drift from the
       first.
   * - ``mark``
     - Something the application knows and the engine cannot; see below.
   * - ``end``
     - How the session finished. A file with no ``end`` is one that was killed or is
       still being written.

A session at sixty frames a second writes a few kilobytes a minute. Past a
ceiling — 128 MB by default, ``OPENGLCONTEXT_TELEMETRY_MAX_MB`` to change it —
input and frame times stop while exceptions, marks and the ending still get
through, and a ``truncated`` record says so. The ceiling is there to keep the
failure, not to lose it.

.. _marks:

Marking what the engine cannot know
-----------------------------------

The engine knows what was pressed and how long the frame took. It does not
know that a level finished loading, that a match started, or that the player
picked up the thing they were about to fall through the floor with. A mark is
the line a reader looks for first when the file is four minutes long and the
failure is at the end of it:

.. code-block:: python

   self.mark('level-loaded', map='ztn3dm1', bots=4)

Every context has it, and it is a call whatever the session is: nothing
recording, a recording, or a replay of one. Nothing to ask first, so nothing
to guard away — and the marks somebody guards away are exactly the ones that
would have explained the failure nobody could reproduce. With nothing
recording it costs an attribute read.

Fields are data: numbers, strings, and numpy’s numbers, which are written as
theirs. A field may be called anything the game calls it, ``name`` included,
since the mark’s own name is positional.

What to mark is whatever the engine cannot see for itself and a reader would
look for: the level, the match, the pickups, the shots, what the opponents
decided. ``twig_bb.telemetry`` is a whole game’s worth of it, made by reading
the match’s own event stream a second time rather than by calling out of the
rules.

.. _randomness:

Randomness
----------

A game whose world, loot, weapon spread or bot decisions come out of a random
number generator does not replay from its input alone: the same keys pressed
against a different sequence of numbers give a different game. So a session
has a **seed**, the engine owns it (``OpenGLContext.entropy``), and the
recording keeps it.

The session seed
~~~~~~~~~~~~~~~~

.. code-block:: python

   from OpenGLContext import entropy

   entropy.seed()          # this session's seed, chosen once
   entropy.reseed(4242)    # start again from a number of your own

Setting ``OPENGLCONTEXT_SEED=4242`` fixes a whole session, including the
ordinary ``random`` and ``numpy.random`` generators a game reaches for without
thinking about it. That is a reproducible run for a bug report, a regression
test, or a level everyone can compare notes on.

**Asking for a seed is what seeds those generators.** Left alone, the engine
chooses a session seed for its own streams and does not touch them at all: a
library that reseeded the process's generators behind its caller's back would
silently undo an application's own ``random.seed(...)``. So a recording
changes nothing about a session — it writes down *where those generators had
got to*, and a replay puts them back.

Named streams
~~~~~~~~~~~~~

Anything in the engine that would otherwise have drawn from nowhere in
particular draws from a stream derived from the seed, and so should a game:

.. code-block:: python

   entropy.generator('loot')        # a numpy Generator, kept, advancing
   entropy.randomizer('bot-chat')   # the same idea, random.Random flavour

Two subsystems drawing from differently-named streams cannot disturb each
other's sequence, so adding a third does not change what the first two produce
— which is what keeps a seeded world the same world as the engine grows.
Asking twice for one name gets the stream, not the start of it: a bot picking
somewhere to walk every few seconds would otherwise pick the same place for
ever.

Inside the engine, :doc:`particle emitters <particles>` with no ``seed`` of
their own, ambient audio's repeat jitter, and ``NavMesh.random_point()`` all
draw from session streams. Each still looks different every time the game is
played, and each repeats exactly when a recorded session is replayed.

.. _reading:

Reading a session back
----------------------

The file is not meant to be read by eye. The report answers the question
somebody actually has — what happened in this session — in the order they want
it:

.. code-block:: bash

   python -m OpenGLContext.telemetry /tmp/session.jsonl

.. code-block:: python

   2026-08-20T14:30:11+00:00  twig-bb ztn3dm1
     pid 4242, python 3.12.3, linux, 1280x720, core, seed 13097442885663472141
     ended: exception

   14,880 frames in 248.1s, 60.0 fps
     median 16.6ms, worst 812.4ms, 14 stalls
     where the time went: idle 187204ms, render 58911ms, poll 402ms

   1 exception(s):
     4:08.412  frame 14879  (fatal)
       Traceback (most recent call last):
         ...
       ValueError: no spawn point for team 2

   1 mark(s):
     0:03.204  frame 190  level-loaded map=ztn3dm1 bots=4

   input: 41,207 events -- pointer 38,110, keyboard 2,984, mousebutton 113

``--events`` lists every input in order rather than counting them by kind —
the question you ask once a frame number has given you somewhere to look, and
``--marks`` does the same for what the game said it was doing. ``--limit``
sets how many exceptions, marks and distinct warnings are shown; past it the
marks are counted by name and both ends of the list are printed, since a
session is diagnosed from its end.

.. _replaying:

Running it again
----------------

This is what recording input against frames is *for*. Point a build at the
journal and it takes its input from the file instead of from the player:

.. code-block:: bash

   OPENGLCONTEXT_TELEMETRY_REPLAY=/tmp/session.jsonl python -m twig_bb

Each frame is given the input that was recorded against it — handed over as
the frame before it ends, which is where the platform handed it over, so the
frame's own work finds it exactly as it did — and the engine's time source
(``OpenGLContext.events.systemtime``) reads the time the recording had reached
at that frame. Everything time-driven follows: TimeSensors, the animation they
drive, and any simulation that asks the engine what time it is. A frame that
took 800 ms during the recording advances the world by 800 ms on replay
however long it takes here.

**A recorded session reads one instant per frame**, which is what makes that
exact. A replay's clock is a step function — it holds the time the recording
reached at a frame for the whole of that frame — so a recording whose game
read the wall clock as it ran would have no matching shape: what it read would
depend on how far into the frame it happened to ask, and the two runs would
measure the same interval differently by however long a frame's work takes.
Milliseconds of it, which is a fire rate, a respawn or an animation landing
one frame out and everything after it out with them. So recording installs a
clock of the same shape, moving at the end of each frame by exactly the
duration the file records for it. It is still wall-clock time, read once a
frame.

A capture's clock has that shape already and is stricter about it — a fixed
step from a fixed start, so the run repeats exactly — so a recording started
while one is installed reads it and leaves it in place. Both are marked
``counts_frames``, which is how each recognises the other; without that the
two would take turns owning the world and a recorded capture would stop being
repeatable.

Combine it with the auto-exit switches to get a screenshot of the frame
something went wrong on:

.. code-block:: bash

   OPENGLCONTEXT_TELEMETRY_REPLAY=/tmp/session.jsonl \
   OPENGLCONTEXT_AUTO_EXIT_FRAMES=14879 \
   OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=/tmp/shots python -m twig_bb

Past the end of the recording the replay stops feeding input, says so once in
the log and on the overlay, and the session continues live.

Did it play out the same way?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The engine can say that it delivered the same input against the same clock. It
cannot say what the game made of that — but the game can, because it is
already :ref:`marking <marks>` what it did. So a replay answers each mark with
the one the journal holds in its place, comparing the name, the fields and the
frame, and says at the end how the two accounts compared:

.. code-block:: python

   WARNING OpenGLContext.telemetry.record: replay of session.jsonl: 199 marks, all as recorded

A session that parted from its recording says where, once, since everything
after the first difference follows from it:

.. code-block:: python

   WARNING OpenGLContext.telemetry.record: replay of session.jsonl: 74 of 199 marks as recorded,
     then death target=player by=bot2 where the recording has death target=bot2 by=player

The same line is on the :ref:`Session <overlay>` section of the developer
overlay while the replay runs, so a divergence can be watched for rather than
waited for. Nothing needs switching on: a game that marks is a game whose
replays are checked.

What replays exactly, and what does not
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A session replays exactly to the extent that it was a function of its input
and the engine's clock. Two things take an application outside that, and both
are worth knowing before a replay is trusted:

- **Reading the wall clock directly.** Code that calls ``time.time()`` for
  itself is not on the recorded clock. Reading
  ``OpenGLContext.events.systemtime.systemTime()`` instead puts it on the same
  clock as everything else in the scene, which is worth doing for :doc:`video
  recording <recording>` as well.

- **A generator the engine cannot reach.** The session's seed and the state of
  ``random`` and ``numpy.random`` are recorded and put back, and so are the
  :ref:`named streams <randomness>`. A generator an application makes for itself
  — its own ``numpy.random.default_rng()``, seeded from the clock — is not any
  of those; building it from ``entropy.generator('name')`` puts it on the
  recording.

- **The first frame.** A recording begins before the session draws anything —
  while a level loads, while a menu is up — and the file holds no duration for
  that gap. The interval a game measures across the very first recorded frame is
  therefore the recording's own, and not reproduced.

- **Anything else that differs between runs** — a thread whose scheduling
  decides an order. A resource that streams in at a different moment is *not* in
  this list any more: a scene loaded off the render thread (``AsyncSceneMixin``)
  is mounted on the frame the recording mounted it on, held back if it is early
  and waited for if it is late, since a level that appeared three frames sooner
  is a world the recorded input from then on was never given to. A replay of
  what is left is close rather than identical: close enough to walk into the
  same wall, which is usually what is wanted.

A replay makes no recording of its own, and reads the journal without changing
it, so the same file replays the same way as often as you like.

.. _telemetry-demo:

Seeing it work
--------------

.. figure:: images/demos/telemetry_demo.jpg
   :alt: Four coloured spheres on dotted rings around a yellow lamp, each ring carrying a pale gate post, on a dark square plinth

   ``python tests/telemetry_demo.py`` — a whole session recorded, read back and
   run again. Four bodies circle the lamp at different periods, and each pass of
   the pale gate post on its ring is a :ref:`mark <marks>` in the journal, so the
   file says what the application did as well as what the engine measured. The
   demo records itself: with no ``OPENGLCONTEXT_TELEMETRY`` set it calls
   ``startTelemetry()`` for a dated file of its own, and on exit it closes the
   journal, reads it back and prints the report. Press ``space`` to flare the
   lamp, ``p`` to pause the orbits and ``m`` to mark a checkpoint — each of them
   a mark to find in the file afterwards.

Recording a run of it with the auto-exit switches — so nobody was at the
keyboard, and the file holds frames and marks rather than input — and reading
that file back with the command:

.. code-block:: bash

   OPENGLCONTEXT_TELEMETRY=/tmp/orrery.jsonl OPENGLCONTEXT_AUTO_EXIT_FRAMES=450 \
   python tests/telemetry_demo.py
   python -m OpenGLContext.telemetry /tmp/orrery.jsonl

   2026-08-21T03:14:15.667877+00:00  tests/telemetry_demo.py
     pid 1401636, python 3.12.3, linux, 300x300, core, seed 15227938117083888771
     ended: quit

   449 frames in 6.1s, 74.0 fps
     median 12.2ms, worst 85.6ms, 0 stalls
     where the time went: render 5940ms, idle 47ms, draw 46ms, cascade 5ms, poll 4ms, wait 1ms, repeats 1ms

   14 mark(s):
     lap 13, scene-ready 1
      0:00.026  frame 0  scene-ready bodies=4
      0:00.933  frame 61  lap body=amber lap=1
      0:01.439  frame 98  lap body=jade lap=1
      0:01.831  frame 130  lap body=amber lap=2
      0:02.233  frame 162  lap body=azure lap=1
     ... and 4 more
      0:04.236  frame 303  lap body=jade lap=3
      0:04.428  frame 319  lap body=azure lap=2
      0:04.536  frame 328  lap body=amber lap=5
      0:05.431  frame 401  lap body=amber lap=6
      0:05.630  frame 418  lap body=jade lap=4

   no input was recorded

   the application at  0:05.114 (frame 374), 2 sample(s) in the file:
     Frame: fps=83.41, frame ms=11.38, frames=375, viewport=300x300
     Loop: loop fps=75.37, loop ms=12.16, worst ms=22.28, stalls=1, last stall=render 86ms, render=13.04, idle=0.11, draw=0.09, cascade=0.01, poll=0.01, wait=0.00, repeats=0.00
     Session: recording=orrery.jsonl, seed=15227938117083888771, frames=374, records=21, size=22.5kB
     Render: profile=core, shadows=yes, ibl=yes, bloom=no, transmission=yes, instancing=yes, vsync=yes, shapes=266, draws=11, instanced=256 in 1 groups
     View: position=0, 8.2, 10.8
     Audio: audio=idle

The bodies take their positions from the engine's clock, which a :ref:`replay
<replaying>` drives from the recorded frame times, so every lap falls on the
frame it fell on the first time and each mark answers the one the journal
holds in its place:

.. code-block:: bash

   OPENGLCONTEXT_TELEMETRY_REPLAY=/tmp/orrery.jsonl OPENGLCONTEXT_AUTO_EXIT_FRAMES=450 \
   python tests/telemetry_demo.py

   replayed /tmp/orrery.jsonl
     14 marks, all as recorded

What the demo does for itself is these few lines — switch recording on unless
the environment already asked for a session, and mark what the engine cannot
see:

.. code-block:: python

   class TestContext(BaseContext):
       def OnInit(self):
           # A session the environment asked for is already installed here,
           # recording or replaying, and starting a second one would write a
           # file nobody asked for and take a replay's input away from it.
           if self.telemetry is None:
               self.startTelemetry()       # a path, or None for the dated default
           print('session: %s' % (self.telemetry.path,))
           self.mark('scene-ready', bodies=len(self.bodies))

       def OnIdle(self, event=None):
           seconds = self.motionTime()
           for body in self.bodies:
               laps = body.completed(seconds)
               if laps > body.laps:
                   body.laps = laps
                   self.mark('lap', body=body.name, lap=laps)
           self.triggerRedraw(1)

.. _overlay:

On the developer overlay
------------------------

A **Session** section appears on the :doc:`developer overlay <hud>` while a
session is being recorded or replayed, and only then. Recording, it names the
file, the session's :ref:`seed <randomness>`, the frame reached, how many
records have been written and what the file weighs; replaying, it names the
file, says how far through the recording it is, and — once the game has marked
anything — whether what it is doing :ref:`matches what was recorded
<replaying>`. A player told to “switch recording on and reproduce it” can see
that it is on, and somebody watching a replay can see when it has run out.

.. _telemetry-testing:

The same vocabulary a test uses
-------------------------------

An input is written down in the vocabulary of
``OpenGLContext.events.synthetic``, which is also what
``OpenGLContext.testing.event_injector`` speaks. A recorded session can
therefore be driven by a test, and a script written by hand for a test is read
by the same report that reads a session:

.. code-block:: python

   {"type": "keyboard",    "key": "w", "state": 1, "modifiers": [0, 0, 0]}
   {"type": "mousebutton", "button": 0, "state": 1, "x": 100, "y": 200, "pick": true}
   {"type": "pointer",     "x": 100, "y": 200}
   {"type": "resize",      "width": 800, "height": 600}

``pick`` says the pointer event went through the selection pass, which is the
route a real click takes: it is delivered once the buffer has resolved what is
under the cursor, carrying the node paths with it.

.. _environment:

Environment
-----------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Effect
   * - ``OPENGLCONTEXT_TELEMETRY``
     - Record this session to the named file. ``1`` or ``auto`` writes a dated file
       under the user's application-data directory.
   * - ``OPENGLCONTEXT_TELEMETRY_REPLAY``
     - Replay the named journal into this session instead of taking live input.
   * - ``OPENGLCONTEXT_TELEMETRY_MAX_MB``
     - The journal's ceiling, in megabytes (default 128).
   * - ``OPENGLCONTEXT_SEED``
     - Fix this session's :ref:`randomness <randomness>`, the ordinary ``random`` and
       ``numpy.random`` generators included.

All four are in ``renderoptions.ENVIRONMENT``, so a subprocess capture does
not inherit them: a journal names one file for one session and a child process
that took the name over would overwrite its parent's; a replay drives the
camera; and a seed decides where the scattered vegetation stands. A capture
that wants a fixed sequence pins the seed itself.

A path that cannot be written is a warning and a session that is not recorded
— never a reason an application will not start. The same goes for a value that
is not a number, and for a replay file that holds no session.

.. _telemetry-modules:

Where it lives
--------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - What is in it
   * - ``telemetry.recorder``
     - ``SessionRecorder``: every rule about what is worth writing down and when,
       with no GL, no window and no file in it.
   * - ``telemetry.journal``
     - ``SessionJournal``: the file, its header, its ceiling, and what happens when
       it cannot be written.
   * - ``telemetry.record``
     - The wiring: the taps on a context's input entry points, the exception hooks,
       the logging relay, and switching it all on.
   * - ``telemetry.replay``
     - ``Recording``, ``RecordedClock`` and ``Replay``: a journal as data, the engine
       clock driven from it, and the input delivered a frame at a time.
   * - ``telemetry.report``
     - ``python -m OpenGLContext.telemetry``.
   * - ``entropy``
     - The session seed, the named streams derived from it, and capturing and
       restoring where the ordinary generators stand.
   * - ``events.synthetic``
     - An input event as a plain record and back again, shared with the test event
       injector.
   * - ``ui.debugoverlay``
     - ``telemetry_provider``: the Session section.

The design and its reasoning are in ``plans/SESSION-TELEMETRY.md``.
