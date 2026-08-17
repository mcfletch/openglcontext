# Loop instrumentation: measuring the thing the frame rate is not

## The problem

A game reports 50 fps on the developer overlay while movement advances about
once a second. Nothing on the screen contradicts anything else, and every number
shown is correct. The frame rate is not lying — it is answering a narrower
question than it appears to.

`FrameCounter` has three properties that are each right on their own and
together make it blind to a stutter:

1. **It times the inside of `OnDraw`.** `Context.OnDraw` stamps `perf()` on
   entry and calls `addFrame` after `renderPasses` returns. `SwapBuffers`
   happens inside the render pass, so vsync blocking *is* captured — but
   `glfw.poll_events()`, `pumpKeyRepeats()`, `OnIdle()` and the
   `redrawRequest.wait(drawPollTimeout)` in `GLFWContext.MainLoop` are all
   outside it. **An application whose simulation lives in `OnIdle` has its
   entire update invisible to the frame counter.**
2. **Only frames that changed something are counted.** `addFrame` is called
   under `if visibleChange:`. An `OnDraw` that does the full event cascade and
   render and concludes nothing changed costs wall clock and never enters the
   window. The window is a sample of the good frames.
3. **The published rate is a median.** `recentFps` sorts a 90-frame window and
   takes the middle sample, deliberately, so a first-frame shader compile or a
   synchronous model load does not drag the number down for ever. If 60 of 90
   frames run at 20 ms and 30 take 300 ms, the median still reports 50 fps.

Downstream, a consumer clamps its timestep so a slow frame cannot tunnel a
character through a wall — twig-bb's was `dt = min(now - last, 0.05)`. That is
also correct, and it is why a stalling game reads as **slow motion** rather than
as a freeze: the world advances by the clamp while the wall clock advances by
the whole frame. Nothing recorded the ratio.

Every layer behaving correctly, and the failure invisible at every one.

## What was built

### `OpenGLContext/looptrace.py` — `LoopTrace`

Wall-clock time per **loop iteration**, divided among named phases, keeping what
a median throws away.

```python
with trace.iteration():
    with trace.phase('poll'):
        glfw.poll_events()
    with trace.phase('idle'):
        self.OnIdle()
    with trace.phase('draw'):
        self.OnDraw(force=1)
```

**Phases divide the iteration rather than overlapping it.** A phase is charged
only its *own* time; time inside a nested phase belongs to the child. So every
phase of an iteration sums to that iteration's wall clock, and the largest is
the culprit by construction rather than by comparison. That is what lets `draw`
be subdivided into `cascade` and `render` from inside `OnDraw` without either
being counted twice.

Reported: `rate` (iterations per second of wall clock), `median_ms`, `worst_ms`,
`stalls` (crossings of the threshold, counted since the loop started so the
count outlives the window it happened in), `phases_ms` (mean per phase over the
window, worst first) and `worst_phase` (where the most recent stall's time
went).

A phase opened outside an iteration — `drawPoll`, or a test calling `OnDraw`
directly — is measured and discarded rather than refused. `iteration()` clears
the phase stack on entry, so a backend that forgets to close a phase costs one
iteration's numbers and never wedges the loop: this is diagnostic equipment, and
a diagnostic that breaks the thing it measures is worse than none.

### Wiring

- `Context.setupLoopTrace` gives every context a `loopTrace`, alongside
  `setupFrameRateCounter`.
- `Context.tracePhase(name)` answers a do-nothing context manager when nothing
  is measuring, so callers write the `with` and not the branch.
- `Context.OnDraw` opens `cascade` around `DoEventCascade` and `render` around
  `renderPasses`.
- `GLFWContext.MainLoop` opens the iteration and the `poll` / `repeats` /
  `idle` / `wait` / `draw` phases. Other backends run their own loops and are
  not yet taught to; their iteration count stays zero and the overlay section is
  left out rather than showing rows of zeroes, which would read as a loop doing
  nothing at all.

### `loop_provider` — the Loop section

Registered by default at order 15, directly under Frame, because the two are
read *against each other*: a healthy `fps` over a poor `loop fps` is the whole
diagnosis, and a reader who has to hunt the panel for the second number will not
compare it.

Rows: `loop fps`, `loop ms`, `worst ms`, `stalls`, `last stall` (as
`idle 812ms`, only once there has been one) and one row per phase.

### `simulation_provider` — is the physics thread getting its turns?

`ThreadedSimulation` asks for a tick rate and silently settles for what it gets:
an overrunning tick resets the schedule instead of running the missed ones back
to back, because catching up on a machine already behind is how a simulation
spirals. Right, and invisible — a starved simulation differs from a healthy one
only in that everything in the world moves slowly, which reads as a physics bug.

Added `ThreadedSimulation.rate()` (ticks per second achieved over a bounded
window of tick timestamps) and `.dropped` (ticks abandoned to stay out of the
spiral), passed through `ThreadedPhysicsManager` and laid out by
`simulation_provider` as `sim hz` against `asked`. Not registered by default: a
context does not necessarily have a threaded simulation.

### `twig_bb/frameclock.py` — `FrameClock`

The clamp, and the accounting the clamp destroys: `real` (the frame's true
duration), `dt` (what the simulation was given), `lost` (world time discarded
this frame), `debt` (discarded since the map loaded) and `pace` (`dt / real` —
1.0 is real time, 0.05 is a world running at a twentieth of speed).

`describe()` puts `dt ms` on twig-bb's Player section always, and `real ms` plus
`behind` (`5% speed, 0.9s lost`) only on a frame the clamp actually bit — on a
healthy frame `behind` says what `dt ms` already said, and a panel has better
uses for the line.

`reset()` is called when a map finishes loading, so the seconds of a level load
— which the player did not experience as a stall — do not open every session
with a debt nothing can explain.

### `OpenGLContext/stalltrace.py` — the recording

A phase name is as far as a log line can go. The stack that would say *which
code* has already unwound by the time the iteration closes, and the overlay has
the same limit from the other end: it shows the present, and a stutter is
something you want to look at afterwards.

`OPENGLCONTEXT_STALL_TRACE=<path>` puts a watcher thread on the main thread's
Python stack and writes a JSON-lines file.

**Sampling is gated on the stall itself.** `LoopTrace.overrunning()` — an open
iteration that has already outstayed the threshold — is asked before every
sample, so a healthy loop is never sampled. A profiler that runs during the
frames that are fine is spending the one currency the question is about. Stacks
are walked by hand into `(file, line, function)` triples rather than through
`traceback`, because this runs on a sampler's clock and does not want the source
read off disk for every frame of every sample.

**The unit is an episode, not a frame.** Consecutive slow iterations are one
record, with a tolerance of a few good frames, because "the game went unplayable
for four seconds" is one thing that happened and a file with a line per frame is
a log rather than a diagnosis. An episode is also cut and written every
`max_seconds` while it continues, and flushed on every path out of the main loop
including `OnQuit`'s `os._exit` — a session that ends *while* it is struggling is
the commonest way for one to end, and that last episode is the one worth having.

**Reported per function, not per stack.** This was the difference between a
trace that found something and a trace that looked empty. One expensive function
is reached by a dozen routes from a dozen lines; grouping only by whole stack
splits it across all of them, so a function holding 60% of a stall reads as a
dozen entries at 5% each:

```
    5.2% of 2772 samples:  ...collide.py:379 ... character.py:799 _update_grounded ...
    4.8% of 2772 samples:  ...collide.py:379 ... character.py:524 _step ...
    4.1% of 2772 samples:  ...collide.py:379 ... character.py:569 _step ...
```

`hot_functions` tallies by `file function` with the line dropped, giving `self`
(the sample was *in* this function) and `cumulative` (it was anywhere on the
stack) as any profiler does. The same data then reads:

```
        self    cum  function
       53.6%  53.6%  collide.py _closest_point_on_triangle
       10.7%  75.0%  collide.py capsule_triangle
```

`hot` keeps the whole stacks as the evidence and the route; `functions` is the
answer.

Each record also carries every section of the developer overlay as it stood when
the episode opened — the overlay already knows how to describe the application,
so a trace gets all of it without a second description that can drift from the
first.

Read back with `python -m OpenGLContext.stalltrace <file>`, which ranks episodes
by worst, length or time. The file is not meant to be read by eye.

## Configuration

| Variable | Effect |
| --- | --- |
| `OPENGLCONTEXT_STALL_MS` | What counts as a stall, in ms; default 50 (twenty frames a second). Setting it also switches logging on: asking for a threshold is asking to be told when it is crossed. A value that is not a number is a warning and the default, never a failure to start. |
| `OPENGLCONTEXT_TRACE_STALLS` | Log each stall's phase breakdown at `WARNING`, keeping the default threshold. |
| `OPENGLCONTEXT_STALL_TRACE` | Record each slow period to this file, with sampled stacks. Read with `python -m OpenGLContext.stalltrace <file>`. |

```
OPENGLCONTEXT_STALL_MS=40 python -m twig_bb
WARNING OpenGLContext.looptrace: main loop stalled 912ms: idle 901ms, render 9ms, poll 1ms
```

Counting is unconditional and costs a few `perf_counter` calls per iteration;
logging is off unless asked for, so a shipped game is silent. Neither variable
changes what a frame looks like, so both are in the *allowed* set of
`test_every_variable_the_package_reads_is_listed` rather than in
`renderoptions.ENVIRONMENT`: a subprocess capture inherits them, because a
diagnostic a subprocess silently dropped is no diagnostic.

## Testing

Red/Green throughout. 26 tests for `LoopTrace` against an injected clock, so the
timings are exact rather than sampled: iteration timing, the bounded window,
phase self-time under nesting, the same phase twice in one iteration, a phase
outside an iteration, an exception not wedging the stack, stall counting and its
survival past the window, the logged breakdown, and the environment reading.

13 for the two new overlay providers, 9 for `ThreadedSimulation`'s rate and
dropped counters (arithmetic over hand-supplied timestamps, plus real-thread
tests with a deliberately slow world), 14 for `FrameClock` and 3 more on
twig-bb's Player section.

The one that matters is
`test_the_worst_iteration_survives_a_median_that_looks_healthy`: 30 frames at
20 ms, one at a second, 30 more at 20 ms — median 20 ms, worst 1000 ms. That is
the bug this exists for, written down as an assertion.

## What it found on its first run

twig-bb, `ztn3dm1` with four bots, `OPENGLCONTEXT_STALL_MS=40`. 1074 stalls in
200 frames, and **1066 of them named `idle`** — the renderer holding a steady
11–13 ms while the game update took 28–77 ms. The frame counter reported the
11 ms.

`idle` is the whole game, so twig-bb's `OnIdle` was subdivided in turn —
`animate`, `weapons`, `liquids`, `navigation`, `character`, `match`, nesting
inside the backend's phases and so dividing `idle` rather than adding to it.
The next run named it outright:

```
main loop stalled 67ms: match 54ms, render 12ms, character 1ms, animate 0ms,
  draw 0ms, idle 0ms, navigation 0ms, liquids 0ms, weapons 0ms, cascade 0ms,
  poll 0ms, wait 0ms, repeats 0ms
```

`_stepMatch` — bots, projectiles, combat — takes 31–54 ms per frame; everything
else in the update is under a millisecond.

A recorded trace then named the code inside it. Over a 17.9-second episode
(worst iteration 849 ms, against a 54 ms baseline) with 2772 samples:

```
        self    cum  function
       53.6%  53.6%  collide.py _closest_point_on_triangle
       10.7%  75.0%  collide.py capsule_triangle
       10.7%  10.7%  collide.py _closest_segment_segment
```

reached by

```
  collide.py _closest_point_on_triangle <- capsule_triangle <- _collide_mesh
    <- collide <- character.py _push_out <- _update_grounded <- _step
    <- update <- walkers.py walk <- game.py _apply <- step_bots <- rules.py advance
```

Every bot's character controller runs capsule-versus-triangle collision against
the map mesh — 51k triangles on `ztn3dm1`, 81k on `oa_minia` — once per bot per
frame, through `_push_out`. **This is a finding, not a fix**: nothing in the
collision path has been changed.

## Status

**✅ Complete.** Modules: `looptrace.py`, `loop_provider` and
`simulation_provider` in `ui/debugoverlay.py`, `setupLoopTrace`/`tracePhase` on
`Context`, phases in `GLFWContext.MainLoop`, `rate`/`dropped` on
`omi_physics.threaded.ThreadedSimulation` and `ThreadedPhysicsManager`, and
`twig_bb/frameclock.py`. Docs: [docs/hud.html](../docs/hud.html) §"When the
frame rate says everything is fine and it is not".

Not yet done: the other backends' main loops (GLUT, pygame, wx) do not open an
iteration, so they get no Loop section. And the `match` cost this found is
reported, not fixed.

**A phase is worth opening wherever a subsystem could plausibly own a frame.**
The engine's phases can only ever say `idle`, because `OnIdle` is where an
application lives; an application that wants a usable answer subdivides it with
`context.tracePhase()`, as twig-bb does. A phase that is always under a
millisecond costs one clock read and earns its place the first time it is not.
