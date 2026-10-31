The Physics World Thread
========================

.. rst-class:: introduction

A Jolt world steps on a native thread that ``pyjoltphysics`` owns, never on the
render thread. The render thread sends commands, reads published snapshots and
asks queries. Handlers run on the render thread unless they are marked to run
on the world thread. A world run in lockstep with the frame gives the same
poses on every run, which is how captures and replays are made. This page
covers that model; :doc:`physics` covers the service's calls.

.. _physicsthread-commands:

Commands and ticks
------------------

Every write to the world (``add_dynamic``, ``remove``, ``set_velocity``,
``apply_impulse``, a joint's motor, a character's move) is a command. The
service hands each command to the engine at once, and
``OpenGLContext.physics.joltengine.JoltEngine`` turns it into one or more
pyjoltphysics batches. A batch is arrays for many bodies. The world thread
applies every batch waiting at the start of the next tick, so a command takes
effect at the tick after it was made. The service's own command numbers are
counted applied once the world reports the batch sequence that holds them
(``Snapshot.applied_seq``).

A body is named as soon as its add is submitted: the service keeps its uid,
and the Jolt body exists from the tick that applies the batch. A body added,
removed or moved takes effect at the next tick. Queries apply the waiting
batches first (``World.flush``), so a ray meets a body added a moment ago.

The queue is pyjoltphysics' own: a submitted batch is appended under a short
lock and the world thread takes every batch due at its tick. The deprecated
omi engine queues the same commands in an ``OpenGLContext.events.handoff.Inbox``
that its worker thread drains before each step. The submission lock is held
for an append. The world lock is held exclusively
only while the world thread applies batches and runs ``PhysicsSystem::Update``.

Measured on one machine (CPython 3.14, 1,000 boxes): a command reaches the
first snapshot that includes it in a mean 5.1 ms at 120 ticks a second and
2.6 ms at 240, when the world runs free. In lockstep a command made in a frame
drives that frame's first tick.

.. _physicsthread-snapshots:

Snapshots
---------

After each tick the world thread publishes a snapshot into a pool of
reference-counted buffers. Python reads positions (float64), orientations and
velocities (float32) as read-only NumPy views without copying. A held snapshot
stays valid; it costs memory and never blocks the world thread. The frame
writes the poses of the bodies that changed onto their ``Transform`` nodes
(``OpenGLContext.physics.poses.write_poses``).

A frame shorter than a tick draws each moving body between the last two ticks,
at the frame's point in the next one. ``physics.poses(bodies,
interpolated=False)`` and ``body.step_position`` change once a tick.

Changes the world thread makes to the scene (a node removed by a handler, a
call that must run on the render thread) go through
``OpenGLContext.events.handoff.Updates``, applied once a frame before the
frame is drawn.

.. _physicsthread-modes:

Free-running and lockstep
-------------------------

The world thread runs one of two ways:

- Lockstep. Each frame runs exactly the ticks it owes (``tickHz`` a second,
  capped by ``maxCatchUp``), with ``World.run_ticks``, while the render
  thread waits with the GIL released. A world in ``inline`` mode, a world held
  there by ``physics.pin_inline(True)``, and any world with framed characters
  run this way. A bounded capture (``OPENGLCONTEXT_AUTO_EXIT_FRAMES``), a
  recorded session and a telemetry replay pin the world inline.
- Free-running. In ``thread`` mode with no framed character the world thread
  ticks at ``tickHz`` on its own. A world with no awake body, no waiting batch
  and no step callback waits on a condition variable and uses no CPU. The
  frame reads the newest snapshot.

A world with framed characters runs the frame's ticks one at a time. Before
each tick every framed character's code runs on the render thread
(``before-step`` handlers, knocks, the steering of ``run_along`` and
``hop_to``) and its input batches apply at that tick; after it run the
``after-step`` handlers and landings. A per-tick steering input therefore runs
at the world rate.

A lockstep world that has settled (no awake body, character, kinematic track,
motor torque or step callback, and two stepped ticks that applied nothing and
reported no contact) counts the ticks a frame owes without stepping them. The
tick count stays exact, so a woken world plays out as one stepped through
every tick.

.. _physicsthread-callbacks:

Handlers and callbacks
----------------------

Handlers run on the render thread by default. The world thread appends each
tick's contact, trigger, sleep and character records to an event ring; the
frame drains it once and calls the handlers in order. A handler there may
touch the scenegraph and the service freely.

Three kinds of code run on the world thread instead:

- A handler marked with ``OpenGLContext.physics.callbacks.physics_callback``.
- A function given to ``physics.on_step(fn)``, called each tick with a
  ``StepView`` (``OpenGLContext.physics.stepview``): the step's ``dt`` and
  ``time``, ``poses``, the queries without the lock, and ``post``.
- A call queued with ``physics.post(fn, *args)``, made before the next step.

Commands made from world-thread code apply at the next tick. Queries from
world-thread code run without taking the world lock. World-thread code must
not touch the scenegraph; it hands scene changes to the render thread through
``physics.render`` (an ``Updates``).

The engine registers its world-thread callbacks only while a step handler, an
``on_step`` hook, a physics-thread handler, a standing force or a posted call
needs them. A world with none never takes the GIL. While any is registered
on a GIL build, the service sets ``sys.setswitchinterval`` to 1 ms and puts
the previous value back when the last one goes. At the default 5 ms, two
callbacks a tick cost 10.1 ms a tick when the render thread runs pure Python;
at 1 ms the wait is at most 1 ms. A render thread inside a GIL-releasing call,
as PyOpenGL's ctypes calls are, costs the callbacks 0.002 ms a tick.

A callback that raises is logged once to the ``pyjoltphysics`` logger, kept as
``World.error``, and stops the world. The next lockstep run raises
``pyjoltphysics.WorldError``, and the service turns it into a
``RuntimeError`` from ``physics.frame`` whose cause is the original exception.

.. _physicsthread-queries:

Queries
-------

``raycast``, ``raycast_many``, ``line_of_sight``, ``sweep_sphere`` and
``overlap`` run on the calling thread, from the world as the last completed
tick left it, under the shared side of the world lock with the GIL released.
A query waits at most for one ``Update``. Measured beside a free-running world
of 5,000 active boxes on 8 job threads, a single ray from Python took 3.2 us at
the median and 1.1 ms at the 99th percentile; 100,000 rays in one call took
55 ms. A world stepped by one job thread holds its lock longer: 2.5 ms at the
99th percentile.

.. _physicsthread-determinism:

Determinism and replay
----------------------

Jolt's step is deterministic for the same bodies, batches and tick, on one
machine and one build, with any number of job threads. Each step's event
records are sorted by kind, bodies and phase, so their order is deterministic
too. The wheels are built with Jolt's cross-platform determinism option, so the
same holds between machines and between x86-64 and ARM64 for one Jolt version
and set of build options.

Lockstep is how the service reproduces a run: a capture, a recording and a
replay step the frame's owed ticks with the frame times they were given, so
every run renders the same poses. pyjoltphysics also replays a free-running
run. ``World.drain_applied`` gives the tick that applied each batch, and a
batch submitted with ``at_tick`` applies at that tick. Replayed in lockstep
with each batch at its logged tick, a run of 40 impulse batches on 500 bodies
ended bitwise identical to the free run, with 1 and with 8 job threads.

What is not deterministic:

- The tick a command lands on in a free-running world. Record (batch, tick)
  pairs to replay it.
- A callback whose effect depends on wall-clock time, or on when the render
  thread read a snapshot.
- Floating-point state changed by other code on the world thread. Jolt expects
  round-to-nearest.

.. _physicsthread-free-threaded:

Free-threaded Python
--------------------

pyjoltphysics ships wheels for the free-threaded builds (cp313t and cp314t)
beside the ordinary ones, and its native state is guarded by C++ mutexes and
atomics. On those builds the GIL stays off: a world-thread callback runs
beside render-thread Python with no wait, 0.002 to 0.005 ms a tick with the
render thread busy. The service's tables touched from both threads, such as
the handler table (``OpenGLContext.physics.handlers.HandlerTable``), take a
lock.

.. _physicsthread-shutdown:

Shutdown and fork
-----------------

pyjoltphysics stops every world at interpreter exit and skips callbacks during
finalisation. A process forked while a world steps holds the world between
ticks for the fork; in the child every call on that world raises
``RuntimeError``, and the child makes its own world.
