# Native physics: pyjoltphysics

Status: **P0 to P3 landed 2026-10-30, P4a the same day, and P4 (`engine.py`: the service on
Jolt behind `PhysicsDefinition.engine='jolt'`, omi the default) 2026-10-31.** Decision taken
2026-10-26; design spiked the same day. The `pyjoltphysics` repository exists locally
(`develop`) with no GitHub remote yet; its workspace registration waits for the remote (see
"P0 as built" below). P4's engine suite is green on both engines and the 1,000-box frame is
under 2 ms; the game suites on Jolt are not yet green, and what they need is P5's list in
"P4 as built" below.

The decision (maintainer): the engine steps its rigid bodies with Jolt Physics through a wrapper
of our own. Jolt always runs on a background thread owned by the wrapper, never inline and never
in a child process. `omi_physics` checks Jolt's results during development and is deprecated once
Jolt carries the games. The reason: `omi_physics` measured 100 to 500 times slower than Jolt on
active worlds (table below), and the games already need compiled code to run it.

The design in one paragraph. `pyjoltphysics` is a nanobind module over Jolt 5.6 with double
precision positions. A native world thread owns the Jolt `PhysicsSystem` and steps it at a fixed
rate. Python submits command batches (arrays) that the world thread applies at the start of the
next tick. After each tick the world thread publishes a snapshot into a pool of reference-counted
buffers, which Python reads as read-only NumPy views without copying, and appends events to a
ring Python drains as one structured array. Python callbacks run on the world thread only when
registered, through one thread state the world thread keeps for its life. Queries run on the
caller's thread under the shared side of a world lock the world thread holds exclusively only
for apply and step. `OpenGLContext.physics.Physics` becomes a thin layer that turns handles into
rows and rows back into handles; no backend object reaches a game.

## Why Jolt (the 2026-10-26 investigation, condensed)

Checked on PyPI, GitHub and crates.io: Rapier 0.36 (Apache-2.0, Rust, official per-object
binding), Jolt 5.6.0 (MIT, C++17, no official binding), PhysX 5 (Python layer under the NVIDIA
Omniverse licence), Bullet 3 (no wheels for 3.12+), Box2D (2D), ODE (old design), MuJoCo
(robotics), Newton, Warp and Genesis (GPU robotics). Rapier and Jolt met the requirements; Jolt
was faster single-threaded and has the wider game feature set (ragdolls, wheeled, tracked and
motorcycle vehicles, soft bodies, state save and restore).

Spike scenes, mean ms per 60 Hz frame of two 120 Hz steps, AMD Ryzen AI MAX+ 395 (32 threads),
Python 3.14.7. Scripts and raw results are in
`/tmp/claude-1000/-workspaces-OpenGL-dev/cb190171-d05a-482b-9f96-5cc0d4e1e0b6/scratchpad/native/`.

| Case | omi_physics | Rapier, 1 thread | Jolt, 1 thread | Jolt, 8 threads |
|---|---|---|---|---|
| 1,000 boxes, active | 142.7 | 0.94 | 0.47 | 0.39 |
| 5,000 boxes, active | 2,533 | 5.82 | 2.71 | 1.20 |
| pile of 1,000 boxes | 173.8 | 8.10 | 6.76 | |
| 30 characters, 10,000 posts | 4.23 | 0.97 | 0.29 | |
| 30 characters, heightfield | 1.10 | 1.28 | 0.31 | |
| 100 chains of 12 links | 227.3 | 2.02 | 2.64 | 0.78 |
| 100,000 scattered rays | about 122,000 | 156 | 54.2 | |

That spike's own module (`native/jph/jphspike.cpp`) was compiled without optimisation: Jolt's
`Distribution` build type sets `-O3` for the Jolt target only, so the binding code ran at `-O0`.
Its Jolt times stand; its boundary numbers (pose reads, the ray and character loops) overstate
the binding's cost. This spike sets `CMAKE_CXX_FLAGS_DISTRIBUTION` for its own target, and the
project's CMake must do the same.

## Name

`pyjolt` is taken on PyPI and as an import name: an async web framework, 80 releases, last upload
2026-02-25, top-level package `pyjolt`. `pyjoltphysics`, `pyjolt-physics`, `joltphysics` and
`jolt-physics` are free (PyPI JSON API, 2026-10-26). The distribution and the import package are
both `pyjoltphysics`, so the two can be installed side by side.

## 1. Binding: nanobind, measured

One small C++ class wrapped four ways: tiny calls, a read-only (rows, 7) float32 view of a buffer
the object owns, a call that releases the GIL around native work, and a virtual `on_tick`
overridden in Python and called from a native thread. Sources:
`/tmp/claude-1000/-workspaces-OpenGL-dev/cb190171-d05a-482b-9f96-5cc0d4e1e0b6/scratchpad/pyjolt-design/bind/`
(`build_all.sh`, `bench.py`; results in `out314/` and `out314t/`). Same machine, CPython 3.14.7,
g++ 13.3. A plain Python function call costs 10.1 to 10.7 ns here.

| | nanobind 3.1.0 | SIP 6.17.1 | pybind11 3.1.0 | Cython 3.3.0 |
|---|---|---|---|---|
| Licence of tool and runtime | BSD-3 | BSD-2 | BSD-3 | Apache-2.0 |
| Clean build, s | 1.5 | 2.7 | 3.2 to 3.5 | 1.4 |
| Module, stripped | 144 KB | 165 KB | 238 KB | 79 KB |
| Lines written by hand | 34 | 80 | 36 | 129 |
| Lines generated | none | 3,082 C++ plus 15,624 C of embedded sip runtime | none | 12,139 |
| Import, ms | 1.03 | 1.69 | 0.94 | 0.74 |
| `w.noop()`, ns | 13.6 | 38.8 | 47.6 | 10.8 |
| `w.add(1, 2)`, ns | 19.4 | 62.7 | 61.0 | 14.0 |
| `np.asarray(w.poses())`, ns | 215 | 223 | 137 | 141 |
| Zero-copy view: read-only, follows native writes, outlives its owner's name | yes, one line (`nb::ndarray`, `reference_internal`) | yes, hand-written `%BIGetBufferCode` | yes, `py::array` with a base | yes, hand-written `__getbuffer__` |
| Python loop beside native work with the GIL released | 98.4% | 98.2% | 98.2% | 94.9% |
| Python override called on the same thread, ns | 30.4 | 82.1 | 113.9 | 66.1 |
| Python override from a native thread, `PyGILState_Ensure` per call, us | 2.0 | 2.3 | 2.2 | 2.2 |
| Python exception in an override on a native thread | C++ `python_error`, caught: 100 of 100 | `%VirtualErrorHandler`: 100 of 100 | C++ `error_already_set`: 100 of 100 | hand-written: 100 of 100 |
| Free-threaded 3.14t | GIL stays off (`FREE_THREADED`) | the import turns the GIL back on for the whole process | GIL stays off (`mod_gil_not_used`) | GIL stays off |
| Same, native-thread call with `PyGILState_Ensure` per call, us | 210 | 158 | 151 | 134 |
| Stub (`.pyi`) | `nanobind.stubgen`; `mypy --strict` clean, with ndarray dtype, shape and writability | generated; `mypy --strict` fails, 7 errors (`wrapper`, `simplewrapper` undefined in a standalone module) | `pybind11-stubgen` (third party); clean, dtype without shape | written by hand |
| Build system | CMake (`nanobind_add_module`) under scikit-build-core | its own backend (`sipbuild.api`) over setuptools; C++ compiled `-std=c++11` unless overridden | CMake | setuptools or CMake |
| Stable ABI | abi3 for 3.12+ | limited API option | not used | limited API option |
| C++ hierarchy with callbacks | trampoline class, two macros | generated from the `.sip` declaration | trampoline class, one macro | written by hand |

Findings:

- SIP's free-threading support is in its ABI 14, and `sipbuild/project.py` sets 3.15 as the
  floor for ABI 14. On 3.13t and 3.14t a SIP module re-enables the GIL for every thread of the
  process.
- SIP compiles through setuptools. Jolt's CMake target exports the `JPH_*` configuration
  defines (`JPH_DOUBLE_PRECISION`, `JPH_CROSS_PLATFORM_DETERMINISTIC`, the SIMD set) to its
  consumers; a SIP build copies those by hand or runs `sip-build --no-compile` from CMake, whose
  output file names follow the specification's contents. A define that differs between Jolt and
  the binding changes the layout of `RVec3` and `Body`.
- The virtual-override machinery that SIP generates covers a different case from ours: our
  callbacks are registered Python callables invoked from our own dispatch, at defined points,
  with arrays as arguments. Every tool needs hand-written dispatch for that.
- `PyGILState_Ensure` once per call is the expensive way for a native thread to run Python: 2 us
  on 3.14 and 130 to 210 us on 3.14t, where it creates and destroys a thread state each time.
  A thread state kept for the life of the world thread costs 0.12 to 0.15 us per callback on
  both builds (section 2).
- Cython is fastest per call and smallest, and needs hand-written trampolines, buffer exports
  and stubs; `opengl_basisu` takes that route for one function. A wrapper of a few hundred
  entry points with typed arrays is the case nanobind's `ndarray` and stub generator cover.

Recommendation: nanobind. SIP is within reason on speed (39 ns a call against 14) and size. It
fails two requirements before 3.15: free-threaded builds, and a mypy-clean stub. Its build path
duplicates Jolt's CMake configuration.

## 2. Threading and batching

### The model

```
render thread (Python)                     world thread (native, owns Jolt)
------------------------                   ---------------------------------------------
submit batch  --(short lock: append)-->    queue
                                           tick k:
                                             exclusive world lock
                                               drain batches due at k, apply, log (seq, k)
                                             shared lock: before-step callbacks (if any)
                                             exclusive world lock: PhysicsSystem::Update
                                             shared lock:
                                               sort the step's events, append to the ring
                                               publish snapshot k+1 into a free pooled buffer
                                               after-step and contact callbacks (if any),
                                                 one attach for both
snapshot()  <--(short lock: copy pointer)-- published buffer (shared_ptr)
drain_events() <--(short lock: swap)------- event ring
raycast(...)   (shared world lock, on the caller's thread)
run_ticks(n)   lockstep: n ticks unpaced, caller waits with the GIL released
```

Rules the spike holds to:

- Bodies are named by rows. A row is allocated when the add batch is submitted, so Python names
  the body at once; the Jolt body exists from the tick that applies the batch. The snapshot
  carries `applied_seq`, the highest batch sequence it includes.
- Lock order: the world thread takes the world lock, then attaches to Python. No thread waits
  for the world lock while attached, so every entry point that can wait releases the GIL first.
  The command, publish and event locks are held for a pointer swap or an append, and never while
  waiting for anything else.
- A world with no callback registered never attaches to Python. A world with no awake body, no
  pending batch and no step callback blocks on a condition variable: 0 ticks and 0.11 ms of
  process CPU in a second.
- A snapshot buffer is reused only when nothing else references it (pool `use_count() == 1`).
  Holding snapshots in Python grows the pool and never blocks the world thread. Each buffer
  records the tick it was written at; a reused buffer is brought up to date from a 16-tick
  history of changed rows, or rewritten whole when older.
- Events are plain 48-byte records: kind, phase, row a, row b, point, normal, depth, tick. Each
  step's events are sorted by (kind, a, b, phase), since Jolt's listeners run on job threads.
- The world object implements `tp_traverse` and `tp_clear`. Without them a callback closing over
  its world made a cycle the collector could not see; nanobind reported the leaked instance at
  exit.

Spike: `pjspike.cpp` (899 lines) with `pj.py` and `drive.py` in
`/tmp/claude-1000/-workspaces-OpenGL-dev/cb190171-d05a-482b-9f96-5cc0d4e1e0b6/scratchpad/pyjolt-design/thread/`;
`build.sh <python> <dir>` builds it against Jolt 5.6.0 in 6 s at 32 jobs; results in
`results_314.jsonl` and `results_314t.jsonl`. Module 2.36 MB stripped, 1.0 MB gzipped.

### Measured

CPython 3.14.7 with the GIL, and 3.14.7 free-threaded where it differs. Boxes 0.5 m, 1 kg.

| Measure | GIL build | Free-threaded |
|---|---|---|
| Callback cost, render thread waiting in a native call | 0.12 to 0.14 us | 0.15 us |
| Two callbacks a tick, render thread running pure Python, switch interval 5 ms | 10.1 ms a tick; world reached 93 of 120 ticks a second, 12 ticks dropped in 2 s | 0.002 ms a tick, 120 Hz |
| Same, switch interval 0.5 ms | 1.14 ms a tick, 120 Hz | 0.005 ms a tick |
| Same, render thread in GIL-releasing native calls (like PyOpenGL's ctypes calls) | 0.002 ms a tick | 0.003 to 0.005 ms a tick |
| Command to first snapshot that includes it, free-running 120 Hz, 1,000 boxes | mean 5.13 ms, p50 5.58, p99 9.92, max 10.06 | mean 5.22, p99 9.76 |
| Same at 240 Hz | mean 2.61 ms, p99 5.56 | mean 2.68, p99 5.89 |
| Lockstep `run_ticks(1)`, 1,000 boxes, including the tick | mean 0.35 ms, p99 1.82 | mean 0.38, p99 1.77 |
| Command to an idle world, wake to applied | 0.26 ms | 0.25 ms |
| Publish, 5,000 active boxes, 1 and 8 job threads | 0.18 and 0.20 ms a tick | 0.24 and 0.31 ms |
| Event sort and append, same scene | 0.003 ms a tick | 0.003 ms |
| `Update`, same scene, 1 and 8 job threads | 4.09 and 1.81 ms | 5.34 and 1.76 ms |
| Python read: `snapshot()`, three views, gather 5,000 changed rows | 50 us p50 | 46 to 76 us |
| Snapshot pool: steady, and with 3 snapshots held by Python | 2 buffers; 3, all still valid | same |
| One ray from the render thread during 120 Hz stepping, 5,000 active boxes, 8 job threads | 1.14 us p50, 2.2 p99 | 1.66 us p50, 3.6 p99 |
| 1,000 rays in one call, same | 0.21 ms p50, 2.28 p99 | 0.17 ms p50, 2.64 p99 |
| Wait for the world lock, same | mean 21 us, p99 0.98 ms, max 2.27 ms; 1.9% of calls waited over 20 us | mean 20 us, p99 0.91 ms, max 5.10 ms |
| Same with 1 job thread (`Update` 3.1 ms) | mean 73 us, p99 2.4 ms, max 7.6 ms | mean 261 us, p99 8.1 ms |
| Callback that raises every 10th tick, 100 ticks | 10 errors counted, last traceback kept, 100 ticks run | same |
| Command issued inside a before-step callback at tick 105 | applied at tick 106 | same |
| Event ring capped at 1,000, never drained, 2,000 boxes for 120 ticks | 1,000 held, 7,000 counted as dropped | same |
| Fork while stepping | child: every call raises `RuntimeError`, exit 0; parent: 12 ticks in the next 100 ms | same |
| Interpreter exit with the thread running and callbacks set; a collected callback cycle; `SystemExit(3)` | all exit, 0.30 to 0.35 s, codes 0, 0, 3 | same |

Sixteen repeats of the determinism, exception, event, fork and idle cases across both builds ran
with no failure and no crash.

### Callbacks

Physics-thread callbacks run at three points: before-step (after the tick's batches are applied),
after-step, and the contact batch of the bodies that registered for one. After-step and the
contact batch share one attach. A callback receives a step record and may submit batches; those
apply at the next tick, measured above. A callback that raises is counted and its traceback kept
for the render thread to log; the world keeps stepping.

On a GIL build the attach waits for the GIL. When the render thread runs Python without
releasing it, the world thread waits out the switch interval: 5 ms by default, 10.1 ms a tick for
two callbacks. Three measures follow from that:

- Handlers run on the render thread by default, from the event array drained once a frame. Only
  a handler marked `physics_callback` runs on the world thread, which is the rule the service
  already has.
- The service sets `sys.setswitchinterval(0.001)` while any physics-thread callback is
  registered and restores the previous value when the last is removed (open decision 7).
- A free-threaded build has no wait: 0.002 to 0.005 ms a tick with the render thread busy.

### Queries

Queries run synchronously on the calling thread, from the world as the last completed tick left
it, under the shared world lock. The world thread holds the lock exclusively only for apply and
`Update`, so a query waits at most one `Update`: p99 0.98 ms and max 2.27 ms at 5,000 active
boxes on 8 job threads, and 1.9% of calls waited more than 20 us. Gameplay rays need an answer in the call;
a batched query answered in the next snapshot waits a mean 5.13 ms at 120 Hz. Batched requests are
kept for large sets (AI sight lines, sensors of many agents), run by the world thread on Jolt's
job system after `Update`, and answered in the snapshot (phase 2). A world stepped by 1 job
thread waits longer (p99 2.4 ms); the service defaults to 4 job threads or the core count less
two, whichever is smaller (opinion).

A query from inside a callback runs on the world thread without taking the lock.

### Back-pressure

- Commands: every batch due is applied each tick, so the queue holds at most what arrived within
  one tick. A world that overruns its tick drops ticks (counted) once it is 4 ticks behind, so
  simulated time slows and the queue does not grow.
- Snapshots: the newest wins. Python never blocks the writer; a held snapshot costs memory.
- Events: the ring has a capacity (65,536 by default). Begin and end are what the service needs
  to keep pair state balanced; persist is a flag on a touching-pair table, read on demand, and is
  not queued. When the ring is full the newest records are dropped, counted, and an overflow
  event is set for the service to log. The service drains every frame, so an overflow means the
  render thread stalled for capacity / events-per-second.

### Shutdown and fork

- `pyjoltphysics` registers an `atexit` hook that stops every world. A world thread also checks
  `Py_IsFinalizing()` before each attach and skips the callback during finalisation. The
  destructor releases the GIL before joining.
- `os.register_at_fork`: before the fork every world is held between ticks with all its locks
  taken; the parent releases them and continues. In the child the world is marked forked: every
  call raises `RuntimeError`, and its destructor detaches its threads' objects without joining
  them. A child process makes its own world. Python 3.14 starts `multiprocessing` children with
  `forkserver` on Linux, which never forks a process holding a world.

### Free-threaded Python

Native state is guarded by C++ mutexes and atomics; nothing in the module relies on the GIL for
exclusion. The 3.14t build ran every case with the GIL off. Two consequences fall on Python code:
a physics-thread callback runs beside render-thread Python, so the service's tables touched from
both threads (handler table, body registry) take a lock; and nanobind's `FREE_THREADED` build is
a separate wheel per version (cp313t, cp314t).

### Determinism and replay

There is no inline mode. Lockstep is a mode of the same world thread: `run_ticks(n)` runs exactly
n ticks unpaced and returns. The world logs, for every batch, the tick that applied it
(`drain_applied()`), and a batch can name the tick it is for (`at_tick`).

Measured: a free-running world given 40 impulse batches at random wall-clock moments (500
bodies, 8 job threads), then a lockstep world given the same batches at the logged ticks, ended
with bitwise identical positions. Lockstep replays with 1 and with 8 job threads were bitwise
identical to each other. Repeated 16 times, both builds.

What is deterministic:

- Jolt's step, given the same bodies, batches and tick, on one machine and one build, with any
  number of job threads.
- Event order, since each step's events are sorted.
- Across machines and between x86-64 and ARM64, only with `CROSS_PLATFORM_DETERMINISTIC` and the
  same Jolt version and build options (open decision 5).

What is not:

- The tick a free-running command lands on. The applied log records it; telemetry stores
  (batch, tick) pairs, and a replay submits each batch with `at_tick`.
- A callback whose effect depends on wall-clock time or on when the render thread read a
  snapshot.
- Floating-point state changed by other code on the world thread. Jolt expects round-to-nearest;
  the world thread sets nothing else, and Python callbacks run on it.

Captures and replays use lockstep: a bounded run (`OPENGLCONTEXT_AUTO_EXIT_FRAMES`, the
`FixedStepClock`) calls `run_ticks` with the ticks each frame owes, so a capture renders the same
poses on every run. Interactive play free-runs.

## 3. Feature mapping

Jolt names are from the 5.6.0 headers. "P1" to "P6" are the phases in section 6.

| Engine feature (service, omi model) | Jolt | Gap and plan | Phase |
|---|---|---|---|
| Box, sphere, capsule, cylinder | `BoxShape`, `SphereShape`, `CapsuleShape`, `CylinderShape` | none; capsule height convention converted | P1 |
| Convex hull | `ConvexHullShape` | none | P1 |
| Trimesh | `MeshShape`, per-triangle material index | none | P1 |
| Heightfield grid | `HeightFieldShape` | sample count padded to a multiple of the block size; holes as `cNoCollisionValue` | P1 |
| Heightfield sample function (`add_ground(land)`) | `HeightFieldShape` tiles | the function stays Python: the service samples tiles around the foci (camera, characters, awake bodies) with NumPy on the render thread and submits add and remove batches; `SetHeights` for edits | P2 |
| Compound | `StaticCompoundShape`, `MutableCompoundShape` | none | P1 |
| Motion: static, dynamic, kinematic; mass, inertia, damping, gravity factor | `EMotionType`, `MassProperties`, `MotionProperties` | `centerOfMass` becomes honoured (`OffsetCenterOfMassShape`); omi carries it without using it, so the differential suite places it at the origin | P1 |
| `quadraticDrag` (omi extension) | none | applied as a force in a native step listener | P3 |
| Material friction, restitution, combine modes | per-body friction and restitution; `PhysicsSystem::SetCombineFriction` and `SetCombineRestitution` | one friction coefficient in Jolt against static and dynamic in omi: the contact listener sets `ContactSettings::mCombinedFriction` per contact from the pair's slip speed; combine modes average, minimum, maximum, multiply in the native combine function | P3 |
| Pair friction grid (marble-demo) | combine function reading a native (M, M) table by the bodies' material indices | none | P3 |
| `CollisionFilter` systems | `ObjectLayer` per distinct filter, `ObjectLayerPairFilterTable` from the (F, F) collides-with table | the table is built from the filters as today; Jolt allows 65,536 object layers | P3 |
| Contact filter, asked once per pair as it first touches | `ContactListener::OnContactValidate` on Jolt job threads | native rules first (filters, pass-through by mass); a Python filter is asked only for pairs where both bodies opted in, on the job thread that found the pair, with a per-thread state kept for that thread; the verdict is cached until the pair parts (open decision 9) | P3 |
| Trigger, sensor | `BodyCreationSettings::mIsSensor` | Jolt reports a contact removed when a body falls asleep (header comment, and 1,000 such removals in the event spike); the native layer keeps a body-pair table and holds sleeping pairs as touching. Sensors against sleeping and static bodies: a conformance test in P1 | P1 |
| Contact events begin, persist, end; approach, impulse, slip | `OnContactAdded`, `OnContactPersisted`, `OnContactRemoved`, `EstimateCollisionResponse` | events aggregated per body pair; approach from the relative velocity at add; impulse from `EstimateCollisionResponse`, since the solver has not run when listeners are called | P1 |
| Sleep and wake events | `BodyActivationListener` | none | P1 |
| Gravity zones (box, sphere, shape; directional, point; priority, replace) | `PhysicsStepListener` | native step listener: a body in a zone gets gravity factor 0 and the zone's acceleration as a force | P3 |
| Joints: hinge, ball, slider, distance, fixed; limits, motors | `HingeConstraint`, `PointConstraint`, `SliderConstraint`, `DistanceConstraint`, `FixedConstraint`; `MotorSettings` | none | P3 |
| Universal and two-axis hinge (X3D `UniversalJoint`, `DoubleAxisHingeJoint`), X3D `MotorJoint` | `SwingTwistConstraint`, `SixDOFConstraint` | none | P3 |
| Joint breaking by force | `Constraint` total lambda after a step | read natively after `Update`, event on break | P3 |
| Kinematic bodies, `Body.drive(pose_fn)` | `BodyInterface::MoveKinematic` | a sampled track (times, positions, rotations) is evaluated natively each tick; a Python pose function runs as a before-step callback | P3 |
| CCD | `EMotionQuality::LinearCast` | per-body option, on by default for bodies under 0.1 m (opinion) | P1 |
| Raycast, sweep, overlap, many at once | `NarrowPhaseQuery::CastRay`, `CastShape`, `CollideShape` | none | P2 |
| `CharacterController` | `CharacterVirtual` (move and slide, `WalkStairs`, `StickToFloor`, max slope, inner body, mass and maximum push strength, character against character) | the state machine is ported to C++ over `CharacterVirtual` (below) | P2 |
| Raycast vehicle (glisteel, `omi_physics.vehicle`) | `VehicleConstraint`, `WheeledVehicleController`, `VehicleCollisionTester` | glisteel's tuning (`VehicleTuning`: drive force curve, steer lock, drag) ported as a native `VehicleController`, or mapped onto Jolt's engine, gearbox and tyre curves after a differential comparison | P6 |
| Telemetry replay | lockstep, applied log, `at_tick` | measured above | P1 |

The character controller. `CharacterVirtual` gives collision, sliding, stairs, floor sticking,
slope limits and pushing. The omi controller's state machine (1,097 lines of our own MIT Python)
moves to C++ around it: walk, run, sprint, crouch (`SetShape` to the crouch capsule), fly, swim
with buoyancy and drag, the ballistic jump whose launch speed is `sqrt(2 * g * jumpHeight)` (exact
apex at hill-runner's gravity of 42 m/s2), coyote time, jump buffer, slide with rise and steer,
knock-down and get-up, landing speed, terminal velocity and hover over a void. The stand-in body
is not needed: `CharacterVirtual`'s inner body is the kinematic body rigid bodies meet, and
`mMass` with `mMaxStrength` give the push limit (`pushMass`). A body striking the inner body
knocks the character back through the contact listener. Inputs (move vector, mode, action bits)
are batches; state (position, velocity, ground state, normal and material, state, landing speed,
flags) is a section of the snapshot. Facing, locomotion, animation and footsteps stay on the
render thread and read that section.

The cost: character input reaches the character at the next tick, mean 5.13 ms and p99 9.92 ms
after submission at 120 Hz (2.61 and 5.56 ms at 240 Hz). The current service steps characters in
the render thread's frame with no added delay. Characters tick at the world rate; the camera
interpolates between the last two snapshots (open decision 8).

New capabilities Jolt adds, and when they are exposed:

| Capability | Phase |
|---|---|
| Character against character (`CharacterVsCharacterCollisionSimple`) | P2 |
| Kilometre-scale worlds (double precision) | P1 |
| State save and restore (`PhysicsSystem::SaveState`), for rollback and checkpoints | P4 |
| Wheeled vehicles, motorcycles, tracked vehicles | P6 |
| Ragdolls (`Ragdoll`, `RagdollSettings`), driven to an animation pose by motors | P6 |
| Soft bodies (`SoftBodyCreationSettings`), cloth | P6 |

Numerics. Every wheel is built with `JPH_DOUBLE_PRECISION`. Single precision resolves 0.98 mm
between 8 and 16 km from the origin, which glisteel's streamed worlds reach. The double build
measured the same as the single build within this machine's noise (5,000 boxes falling into a
pile, 8 job threads, best of 4: 0.99 ms double, 1.13 ms single; medians 1.60 and 1.45 ms); the
2026-10-26 spike measured 3%. One build serves every game and there is no origin shifting.
Snapshot positions are float64; orientations and velocities float32.

## 4. API

### pyjoltphysics

```
pyjoltphysics/
    __init__.py       World, Settings, Snapshot, EVENT dtype, enums, the at-fork and atexit hooks
    _core.*.so        the nanobind module
    _core.pyi         generated by nanobind.stubgen; CI fails when it differs from the build
    events.py         EVENT, EventKind, Phase
    settings.py       Settings (threads, tick_hz, max_bodies, max_pairs, event_cap, gravity)
    testing/          Scenario arrays shared by the unit, differential and benchmark suites
    py.typed
```

```python
import numpy as np
import pyjoltphysics as pj

world = pj.World(pj.Settings(tick_hz=120.0, threads=4, max_bodies=65536))
box = world.shapes.box((0.25, 0.25, 0.25))                  # a shape id
land = world.shapes.heightfield(heights, origin=(-128, 0, -128), spacing=1.0)
wood = world.materials.define(friction=0.5, restitution=0.2, combine='average')
world.materials.pair(wood, wood, friction=0.7)
world.filters.set_table(collides)                           # (F, F) bool

rows, seq = world.add_bodies(box, pj.DYNAMIC, positions, orientations=None,
                             masses=1.0, materials=wood, filters=0, flags=pj.REPORT)
world.start()                                               # paced at tick_hz

world.set_velocity(rows[:4], velocities)                    # applies at the next tick
snap = world.snapshot()                                     # read-only views, no copy
moved = snap.changed
positions_now = snap.position[moved]
events = world.drain_events()                               # structured array, dtype pj.EVENT
hits = world.raycast(origins, directions, 100.0, filters=0) # (N,) distance, row, point, normal

@world.after_step                                           # world thread; batches apply next tick
def push(step):
    world.add_impulse(step.rows_in(zone), up)

world.run_ticks(60)                                         # lockstep: exactly 60 ticks
world.close()
```

Every call takes or returns arrays for many bodies. Bodies, shapes, materials, joints and
characters are integers. No call hands Python a pointer into Jolt.

### OpenGLContext.physics on it

`Physics` keeps its public API: `add_static`, `add_dynamic`, `add_kinematic`, `add_trigger`,
`add_ground`, `add_static_instances`, `add_character`, the joint calls, `remove`, `body_for`,
`bodies_in`, `raycast`, `raycast_many`, `line_of_sight`, `sweep_sphere`, `overlap`,
`addEventHandler`, `set_contact_filter`, `materials`, `filters`, `gravity`, `enable`, `frame`,
`close`. Underneath it holds one `pyjoltphysics.World` and the table from body uid to row.

| Module today | With pyjoltphysics |
|---|---|
| `worker.py` (inline and thread workers, inbox, outbox) | deleted; the world thread is the worker and `run_ticks` is lockstep |
| `runtime.py` (`WorldRuntime`: commands, stepping, snapshot assembly, event conversion) | deleted; replaced by `engine.py`, about 300 lines (opinion) turning service calls into batches and event rows into `PhysicsEvent` |
| `replica.py` (render-thread copy of the world for queries) | deleted; queries go to the world under its shared lock |
| `queries.py` (sweep and overlap over omi worlds) | deleted |
| `character.py` controller stepping, stand-in placement, the deferred stand-in machinery in `service.py` | deleted; `Character` keeps facing, locomotion, animation, footsteps and handlers over a native character row |
| `records.py` | `Snapshot` and `Command` go; `PhysicsEvent`, `Step` and `BodySpec` (with neutral types) stay |
| `body.py`, `joints.py` (`Joint` handle), `events.py`, `handlers.py`, `callbacks.py`, `filters.py`, `materials.py`, `zones.py`, `colliders.py` (scenery tracker), `proxy.py` (cooking), `sources.py`, `x3drigid.py`, `x3dcollision.py`, `gltf_world.py`, `debugdraw.py`, `landscape.py`, `road.py`, `props.py` | stay, with the omi types replaced as below; `JointTable` is deleted |
| `PhysicsDefinition.mode` (`inline`, `thread`, `process`) | removed; `engine` (`'omi'` or `'jolt'`) during P4, removed after P5 |

What reaches omi_physics through the public API today, and the neutral replacement:

| Leak | Replacement |
|---|---|
| `physics.world`, the live `PhysicsWorld` | removed; reads through handles (`body.position`) and `physics.poses(bodies)`, which returns (n, 3) positions and (n, 4) rotations |
| `physics.backend` and `BACKENDS` (omi compute backends) | removed; `physics.engine` is a read-only description such as `'jolt 5.6.0 double'` |
| `slot_of`, `body_at`, `index_of` | removed; `Body.uid` is the stable id, and the array calls take lists of bodies |
| `run(fn)`, calling `fn(world)` with the raw world | removed; named features cover joints, filters and materials, and `physics.on_step(fn)` gives tick-exact code a `StepView` (queries, batch submission, the step record) |
| `post(fn, *args)` | kept, defined as "call on the world thread before the next step" through the same `StepView` path |
| `Character.controller` | removed; `Character` already exposes position, eye, velocity, grounded, swimming, crouching, state, landing, heading and the actions |
| `CharacterState` from `omi_physics.character` | `OpenGLContext.physics.CharacterState`, same members |
| `CharacterCapabilities`, `Material`, `CollisionFilter` re-exported from omi | dataclasses of the same names and fields in `OpenGLContext.physics`; the OMI field names stay, since they are the glTF vocabulary; `gltf_world` converts to and from the omi model for reading and writing files |
| `Proxy.shape`, an omi `model.Shape` | `Proxy.kind` and `Proxy.params` (arrays); the omi conversion moves to `gltf_world` |
| `overlap(proxy=)` accepting an omi `Shape` | `Proxy` only |
| `zones.Box` and `zones.Sphere` subclassing omi `BoxRegion` and `SphereRegion` | own region classes |
| `add_dynamic(material=)` accepting an omi `Material` | a material name or `OpenGLContext.physics.Material` |

Games today: marble-demo imports `omi_physics` directly in 10 modules (`level.py`, `game.py`,
`materials.py` and seven mechanisms) and reads `scene.world` arrays. Its move to the service API
is a precondition of P5. twig-bb, glisteel, the forest and hill-runner use none of the escape
hatches above.

### omi_physics after the switch

Recommendation: drop the fallback. From P5 `pyjoltphysics` is a hard dependency of OpenGLContext's
physics service, with wheels for every platform OpenGLContext publishes for and an sdist that
builds with CMake and a C++17 compiler, as `opengl_basisu` does. A Python fallback would be a
second engine with an inline or Python-thread loop, against the decision that Jolt always runs on
its own thread, and every feature would be built twice. `omi_physics` stays as the oracle in two
forms: live in the differential suite until P5, then as golden results recorded from it (per
scenario: rest poses, contact pair sets, trigger occupancy, character tracks), so the oracle
survives omi's retirement.

## 5. The pyjoltphysics project

Set up by the workspace's rules for new projects, with `opengl_basisu` (vendored C++, wheels)
and `opengl_extrusions` (CI and release templates) as the models. The next agent creates it after
the maintainer reads this plan.

```
pyjoltphysics/
    pyproject.toml        scikit-build-core, nanobind; ruff, mypy, pytest, cibuildwheel;
                          [tool.openglcontext-checks]; license "MIT AND BSD-3-Clause"
    CMakeLists.txt        Jolt options (double precision, SIMD floor, determinism), -O3 for the
                          binding target, nanobind_add_module(... NB_STATIC STABLE_ABI FREE_THREADED)
    src/native/           world.cpp, commands.cpp, snapshot.cpp, events.cpp, queries.cpp,
                          characters.cpp, joints.cpp, zones.cpp, bindings.cpp, *.hpp
    src/pyjoltphysics/    the package above
    vendor/JoltPhysics/   Jolt/ and Build/ from tag v5.6.0, unmodified, with LICENSE (6.2 MB)
    NOTICE                Jolt (MIT, Jorrit Rouwe) and nanobind (BSD-3, Wenzel Jakob)
    tests/unit/           per feature, against the native module
    tests/differential/   scenarios against omi_physics, then against golden results
    tests/stress/         long runs, fork, shutdown, free-threaded races
    benchmarks/           the spike's scenes
    tox.ini               lint, typecheck, stubs (regenerate and compare), asan, oldest-numpy
    .github/workflows/    test.yml, release.yml
```

Decisions inside it:

- Vendoring: a copied tree, as `opengl_basisu` vendors basis_universal. The sdist builds offline
  and contains every source. A git submodule needs recursive checkouts and does not enter an sdist
  through `git ls-files`; `FetchContent` needs the network at build time. Updating Jolt is a
  commit that replaces `vendor/JoltPhysics` and changes the tag in `NOTICE`.
- Workspace: a submodule at `pyjoltphysics/`, a `[tool.uv.sources]` editable entry and a
  `[dev]` requirement in the root `pyproject.toml`, entries in `tools/preflight.toml` and
  `tools/release.toml`, and listed under `[tool.opengl-dev.pre-release]` until P1 is done.
- Python: `requires-python = ">=3.10"`, OpenGLContext's floor.
- Wheels, cibuildwheel 3.1+: cp310 and cp311, cp312-abi3 (covers 3.12 and later), cp313t and
  cp314t. Runners: `ubuntu-latest` and `ubuntu-24.04-arm` (manylinux_2_28 and musllinux),
  `macos-latest` (arm64) and `macos-15-intel` (x86_64), `windows-latest` (x64) and
  `windows-11-arm` (arm64). macOS gets two wheels: Jolt's CMake applies the x86 SIMD flags to
  the whole build, so a universal2 build would compile `-mavx2` for the arm64 slice. About 1.5 MB
  a wheel compressed (spike 1.0 MB; opinion for the full module).
- x86-64 SIMD floor: SSE4.2 (`USE_AVX=OFF USE_AVX2=OFF USE_F16C=OFF USE_FMADD=OFF USE_LZCNT=OFF
  USE_TZCNT=OFF`). Measured against AVX2 on the pile scene, best of 4: 3.83 against 3.83 ms with
  1 job thread, 1.21 against 1.13 ms with 8 (open decision 6).
- CI: the test job runs on every wheel platform for 3.12, plus 3.10 to 3.14 and 3.14t on Linux;
  `lint` (ruff), `typecheck` (mypy over the package and the generated stub), `stubs` (the stub
  regenerated from the build equals the committed one), `asan` (ASan and UBSan build of the
  module, unit and stress suites on Linux). Release on push to main when the version is not on
  PyPI, trusted publishing, as in `opengl_basisu/.github/workflows/release.yml`.
- Type stubs: `_core.pyi` from `nanobind.stubgen`, committed, with ndarray dtype and shape in the
  annotations; the pure-Python layer is annotated and mypy-strict.

The differential suite. Each scenario is arrays (from the spike's `scenes.py`) run through a thin
runner per engine, and compared on behaviour, since two solvers never agree to the bit:

| Scenario | Compared | Tolerance |
|---|---|---|
| Box dropped on a plane | rest height; ticks to sleep | 1 mm; 25% |
| Stack of 10, pile of 1,000 | sideways drift after 2 s | 5 cm |
| Sphere rolling on an incline, per friction | distance at 2 s | 10% |
| Restitution bounce | second apex over first | 0.05 |
| Pair friction grid (marble) | slide distance order; distances | exact order; 15% |
| Collision filters | sets of pairs that touched | exact |
| Triggers, slow bodies | enter and exit pairs and ticks | exact pairs; 2 ticks |
| Sleep | set of bodies awake after 5 s | exact |
| Hinge pendulum, chain, limits, motors | period; link distance; limit angle; motor speed | 2%; 1 cm; 1 degree; 2% |
| Slider and distance joints | travel at the limits | 1 mm |
| Gravity zones | position at 2 s | 1% |
| Kinematic track | pose at each tick | 1e-6 m |
| Thin wall at 50 m/s (CCD) | tunnelled bodies | none |
| Heightfield function ground | rest height against the function | 1 cm |
| Characters: walk, stairs, slopes, jump, crouch, slide | arrival; ground-state sequence; apex against jumpHeight; step and slope verdicts | 5 cm; exact; 2%; exact |
| Rays, sweeps, overlaps | hit row; distance; overlap sets | exact; 1 mm; exact |

The benchmark suite re-runs the spike's cases (`native/scenes.py`: active and settled boxes,
piles, characters among posts and on a heightfield, chains, scattered rays and sweeps) and the
service frame costs of `framecost/bench.py`, writes JSON, and gates only coarse regressions under
the `serial` marker.

### P0 as built (2026-10-30)

Where the repository departs from the layout above:

- Jolt v5.6.0 (commit e77f1755) is a git submodule at `extern/JoltPhysics`. The sdist carries
  `Jolt/`, `Build/CMakeLists.txt`, `LICENSE` and `README.md` from it (scikit-build-core
  `sdist.include`; it walks the tree rather than `git ls-files`), 938 KB, and builds offline.
- The module is `pyjoltphysics._native`, from `src/_native.cpp`; its stub is `_native.pyi`.
- Workflows are `test.yml` (tox suite on 3.10 to 3.14 with lint, typecheck and stubs on 3.12;
  cibuildwheel on six runners; sdist installed and tested from the unpacked archive) and
  `release.yml` (calls `test.yml` and publishes its artifacts). No `asan` job yet.
- cibuildwheel is pinned at 3.4.1: the 4.x series builds no cp313t.
- Jolt's `INTERPROCEDURAL_OPTIMIZATION` is off: a static archive of LTO objects hands LTO to
  whichever linker reads it.
- Wheel, Linux x86_64, gcc 13.3: 857 KB, module 1.88 MB, one exported symbol.
- `tools/release.py` reads only setuptools' `attr` version; the root patch teaches it
  scikit-build-core's regex provider, with two tests.
- The root registration (submodule, uv source, preflight and release entries,
  `verify-everything.py`, CLAUDE.md) is a patch waiting for the GitHub remote. It does not list
  the project under `[tool.opengl-dev.pre-release]`, since a pre-release checkout has no
  preflight gates and P0 is done when preflight runs them.

## 6. Phases

Effort in engineer-weeks (opinion), re-estimated from the spike: the world thread, command
queue, snapshot pool, event ring, callbacks, lockstep, fork and shutdown handling took 900 lines
of C++ and ran correctly in both builds.

| Phase | Delivered | Tested by | Done when | Weeks |
|---|---|---|---|---|
| P0 | Repository, vendored Jolt, CMake, empty module exposing the version and build options, CI and wheels on every platform and tag above, stub check, workspace registration | CI on all runners; a wheel installs and imports from outside the checkout | every wheel builds, installs and passes an import test; preflight runs ruff, mypy, OGC rules and the suite | 1 to 1.5 |
| P1 | World thread, settings, command batches, snapshot pool, event ring with pair aggregation, sleep events, shapes (primitives, hull, mesh, heightfield grid, compound), bodies in bulk, materials without pair grid, CCD, lockstep, applied log, `at_tick`, fork and atexit hooks, double precision | unit suite; the differential scenarios for bodies, shapes, sleep, triggers and CCD against omi; ASan run; the free-threaded wheel through the same suite | differential tolerances met; determinism and fork tests green on both builds; 5,000 active boxes within 10% of the spike's times | 3 to 4; done 2026-10-30 (P1a and P1b below) |
| P2 | Queries (synchronous and batched), the character controller port over `CharacterVirtual`, character against character, heightfield tiles from a sample function | differential character and query scenarios; the omi character tests (the behaviour-level ones) ported as conformance | every character scenario within tolerance; a 300-character heightfield world steps under 4 ms on 8 threads | 4 to 5; done 2026-10-30 (P2 below) |
| P3 | Joints with limits, motors and breaking; materials with combine modes and the pair grid; collision filters; Python contact filter; gravity zones; kinematic tracks; `quadraticDrag` | differential joint, material, filter and zone scenarios; the X3D rigid body tutorials rendered against omi | tolerances met; X3D RigidBodyPhysics tutorials match their omi captures within the visual tolerance | 2 to 3; done 2026-10-30 but for the tutorials, which wait for P4 (P3 below) |
| P4 | `engine.py` in OpenGLContext behind `PhysicsDefinition.engine='jolt'`; neutral replacements for every leak; service tests parametrised over both engines; telemetry replay through lockstep; state save and restore | OpenGLContext unit suite on both engines; each game's suite with `engine='jolt'`; benchmarks against `framecost/final.txt` | every engine test and every game suite green on both engines; the service frame cost at 1,000 active boxes under 2 ms (174 ms today on omi) | 3 to 4; P4a (the neutral API) done 2026-10-30, P4 2026-10-31 but for the game suites on Jolt, below |
| P5 | Default `engine='jolt'`; `pyjoltphysics` a hard dependency; omi fallback, `worker.py`, `runtime.py`, `replica.py`, `queries.py` deleted; golden results recorded from omi; docs (`docs/physics.rst`, a page on the world thread, callbacks and determinism); omi_physics marked deprecated | full workspace `verify-everything.py`; preflight for openglcontext and pyjoltphysics | the games run on Jolt with no `engine` setting; marble-demo off direct omi imports; docs merged | 1 to 2 |
| P6 | Vehicles (glisteel parity, then motorcycles and tracked), ragdolls driven by animation, soft bodies | differential vehicle scenarios against omi's `RaycastVehicle`; glisteel lap times; new tutorials | glisteel drives on Jolt within its handling tests; a ragdoll and a cloth tutorial ship | 4 to 8 |

P0 to P5: 14 to 19.5 weeks. The games stay on omi until P5: P4 runs them on both engines in CI,
and a program selects Jolt with one definition field.

### P1a as built (2026-10-30)

P1 is split: P1a is the engine core with primitive shapes, P1b the other shapes and the fuller
differential suite. P1a is commits 4f9a0ac to 6b62d0c on `pyjoltphysics` `develop`.

- C++ in `src/native/`, a file per concern: `world` (thread, tick, free-run, lockstep, idle wait,
  registry, fork and atexit hooks), `commands` and `apply` (one `std::variant` alternative and one
  `apply` overload per command), `snapshot` (pool and 16-tick changed-row history), `events`
  (listeners, per-pair folding, ring), `callbacks` (kept thread state, callable set), `layers`
  (group and mask over 16-bit object layers), `shapes` (`ShapeLibrary`, one case per kind: P1b adds
  hull, mesh, heightfield and compound there), `bind_world` (nanobind `World`, `Snapshot`,
  `tp_traverse`/`tp_clear`). No warnings under `-Wall -Wextra` (gcc 13.3).
- Python: `World`, `WorldSettings`, `BodyBatch`, `Snapshot`, `EVENT_DTYPE`, the enums, `WorldError`,
  and `pyjoltphysics.testing` (floor, grid, pose digest). mypy strict, ruff, `oglc-check` clean;
  `_native.pyi` regenerated. numpy became a runtime dependency.
- Uids are assigned at submission, from 1, never reused; snapshot rows are dense (removal moves
  the last row into the gap, both rows in `changed`), with `uid` per row and `rows` as a dict.
- `applied_seq` is the highest contiguous sequence applied: a batch held by `at_tick` holds it
  back until its tick.
- Event record (48 bytes): kind, phase, reason (end: parted or removed), tick, a, b, point,
  normal, approach, impulse. There is no time field: 48 bytes do not hold one beside the rest,
  and time is exactly `tick / tick_hz` (`event_times`).
- Sleep: a pair whose contacts go while neither body is awake is held as touching (no end, and no
  begin when it wakes touching); if a woken body has parted, its end comes in the tick after the
  wake. A body asleep inside a sensor stays inside. Removing a body ends its pairs at once with
  reason `REMOVED`; Jolt's later removal reports are ignored by body-and-sequence key.
- Ring back-pressure: past capacity, persist records go first, oldest first, then sleep and wake;
  begin and end are never dropped and the ring grows past capacity for them.
- A callback exception is stored (`world.error`), logged once to the `pyjoltphysics` logger, and
  stops the world; waits and later `run_ticks`/`start` raise `WorldError` from it. This departs
  from the spike, which counted errors and kept stepping.
- A world dropped or collected on its own thread detaches its thread, which owns a reference to the
  world core and ends after the tick. The stable ABI of 3.12 has no `Py_IsFinalizing`; the atexit
  hook sets a flag that stops every attach.

Tests (112, plus 4 doctests), written against the module and seen failing against P0's (the
package fails to import its world): GIL build (3.14, and tox on 3.10, 3.11, 3.13, 3.14) all
green; free-threaded 3.14t 108 passed, 3 skipped (no omi_physics in that environment, NEON, the
GIL-wait case); ASan and UBSan build (`tox -e asan`, `tools/asan.sh`; a CI job) 108 passed, no
sanitizer report. Lockstep replay of a free-running run with 40 impulse batches: per-tick pose
hashes over 1,000 ticks identical to the free run with 1 and 8 job threads, 16 repeats, both
builds. Differential smoke against omi: sphere rest height within 1 cm (Jolt 0.500, omi 0.495),
stack of 10 drift under 5 cm and top within 5 cm (9.497, 9.470), rebound ratios within 0.05 at
restitution 0.5 and 0.8.

`benchmarks/boxes5000.py`, the spike's 5,000-active-box scene with a static box for the ground
(the spike's ground was a 20,000-triangle mesh, which is P1b), ms per 60 Hz frame of two ticks,
measured by the caller of `run_ticks(2)`, machine otherwise idle, best and worst of 3:

| | Spike | GIL build | Free-threaded |
|---|---|---|---|
| 1 job thread | 2.71 | 2.34 to 2.36 (one cold run 3.40) | 2.26 to 2.34 |
| 8 job threads | 1.20 | 1.00 to 1.17 | 1.32 to 1.57 |
| Snapshot publish, 5,000 boxes | 0.18 to 0.31 a tick | 0.05 to 0.06 a tick | 0.06 to 0.07 a tick |
| Event folding | 0.003 a tick | 0.002 a tick | 0.002 a tick |

The P1 criterion (within 10% of the spike) holds on the GIL build; the free-threaded 8-thread run
is 10 to 30% over the spike's GIL figure. P1b re-runs the scene with the mesh ground.

### P1b as built (2026-10-30)

P1b is commits b6a7cab to fd2ab92 on `pyjoltphysics` `develop`.

- Shapes: `Shape.convex` (Jolt `ConvexHullShape`; fewer than 4 points or points enclosing no volume
  raise `ValueError` before Jolt sees them), `Shape.mesh` (`MeshShape`, sanitised, active edges on),
  `Shape.heightfield` (`HeightFieldShape`; any rectangular grid is padded on +x and +z to Jolt's
  square block grid with no-collision samples; NaN or a mask makes holes; block size, bits per
  sample and height range exposed), `Shape.compound` (static or mutable; no height field child).
  `World.add_shape` builds on the calling thread with the GIL released and returns an id; bodies
  share the one Jolt shape. Scale, shape offset and rotation, and centre-of-mass offset are body
  fields (`ScaledShape`, `RotatedTranslatedShape`, `OffsetCenterOfMassShape`), cached per shape and
  decoration. Shapes are resolved when a batch is submitted, so the world thread only creates
  bodies.
- Jolt limits met: meshes, height fields, planes and compounds holding them refuse dynamic bodies
  (Jolt computes no mass for them); a kinematic one takes a unit box's mass and inertia. Mesh
  triangles collide on their front face only. A sphere landing beside an inner diagonal edge of a
  flat mesh is pushed sideways (0.48 m in one case); Jolt's enhanced internal edge removal
  (`BodyFlag.SMOOTH_EDGES`) removes it and is off by default, a choice the service may revisit.
  A ball rolling at 6 m/s rides up to 5 mm off a flat mesh or height field at cell edges.
- `heightfield_tiles`: one static body a tile, tiles sharing edge samples, each body at its tile's
  corner. A ball crossing seams rides no higher than on one field. Enhanced edge removal works
  within a body, so it does not reach across tile seams.
- Bulk adds already used `AddBodiesPrepare`/`AddBodiesFinalize`; the world thread now caches the
  collision layer across rows and optimises the broad phase once after a tick adding 256 or more
  statics, when it next has no tick due.
- Events: one begin and end per body pair for compounds (tested with a four-legged table). A sensor
  added or moved wakes the moving bodies its bounds meet, so it reports sleeping bodies; a
  kinematic sensor sets `mCollideKinematicVsNonDynamic` and reports static bodies; two statics
  never meet. CCD tested against a 5 cm box and a mesh quad at 300 to 400 m/s.
- Open problems: (i) the event point is float64; the record grew to 64 bytes (a point relative to
  body `a` would be relative to a ground body far from the contact whenever the ground has the
  lower uid). (ii) Jolt's listeners run before the solver, so `impulse` is begin-only (the
  estimate) and 0 in persist records, documented. (iii) a future `at_tick` leaves a free-running
  world idle; it runs when work or `run_ticks` reaches its tick. (iv) `stats()['bodies']` is
  applied bodies, `queued_bodies` the rest.

Differential suite (`tests/differential/`, marker `differential`, 38 tests, all within tolerance):

| Scenario | Jolt | omi | Tolerance |
|---|---|---|---|
| Rest height, 5 shapes on box, mesh and height field | 4.8 mm below the geometry (sphere on mesh 2.7 mm) | 4.8 to 5.4 mm below | 1 cm of geometry and of each other |
| Box down a 20 degree slope in 1 s, mu 0, 0.3, 0.8 (mesh and height field) | 2.028, 0.356, 0.000 m | 2.027, 0.356, 0.000 m | 10% or 3 cm of the analytic slide |
| First rebound over drop, e = 0.6, three grounds | 0.365 | 0.373 to 0.376 | 0.05 of e2 and of each other |
| Stack of 5: top, drift, asleep | 4.4997 m, 0.2 mm, yes | 4.4939 m, 2.8 mm, yes | 2 cm |
| Pyramid 4-3-2-1: worst box from its place, asleep | 3.0 mm, yes | 6.9 mm | 1 cm Jolt, 5 cm omi |
| Ball down 5 stairs, end x | 5.32 m | 5.00 m | both in 3 to 12 m, within 1.5 m |
| Sensor fall-through enter/exit ticks | 83, 105 | 83, 105 | 1 tick |
| Body asleep in a sensor | one enter, no exit | same | exact |
| Kinematic sensor over a static box | enter and exit | none | Jolt right: omi's triggers report moving bodies only |
| 5 cm ball at 300 m/s, 5 cm wall | stops at -0.06 m | passes to 13 m | Jolt right: omi has no CCD |
| 1,000 boxes in a 10 m bin, rest height mean and spread | 1.266 m, 0.717 m | 1.296 m, 0.740 m | 3% and 10% |
| Dumbbell compound rest | 0.5 m, level | same | 1 cm, 1 degree |

Benchmarks (this machine, best of 3, the machine carrying other load during the 5,000-box runs):

| | Spike | P1b GIL build |
|---|---|---|
| 5,000 active boxes, 20,000-triangle mesh ground, ms per frame, 1 job thread | 2.71 | 3.04 (3.04 to 4.13) |
| same, 8 job threads | 1.20 | 1.27 (1.27 to 2.37) |
| same scene on a box ground, for the machine's state then | | 2.45 and 1.16 (P1a measured 2.34 and 1.00 idle) |
| 10,000 static posts added among 1,000 falling boxes: `add_bodies` call; create and add in the tick; the whole tick | | 3.7 to 4.5 ms; 3.5 to 4.6 ms; 4.2 to 5.8 ms (8.5 to 12 ms in 2 of 5 suite runs on the loaded machine) |
| frames after the add, 1 / 8 threads | | 0.63 / 0.39 ms |
| 300 spheres on a 257 x 257 height field, 1 / 8 threads | | 1.03 / 0.28 ms; field built in 2.2 ms |
| Snapshot publish a tick | 0.18 to 0.31 | 0.06 to 0.10 (5,000 boxes), 0.01 (posts) |

The 8-thread mesh-ground figure is within 10% of the spike; the 1-thread one is 12% over, measured
while the machine was loaded (load average 2.8); a quiet-machine rerun is left for the preflight
pass.

Tests: 194 on the GIL build (3.14, plus 2 skipped for NEON and the free-threaded check), written
first and seen failing against P1a's module (shape API absent, `queued_bodies` missing, a future
`at_tick` keeping the world busy). Free-threaded 3.14t: 151 passed, 3 skipped (no omi_physics in
that environment). ASan and UBSan (`tools/asan.sh`): 150 passed, 3 skipped, no sanitizer report;
the one failure was the 10,000-post tick bound (26.7 ms under the sanitizers), which now scales by
10 under `tools/asan.sh` and bounds the add's own time, and passes there.

P2 starts from: shape ids for character and query shapes, `heightfield_tiles` for the sample-function
ground (tiles sampled around the foci, added and removed as batches), the world lock's shared side
for queries, and `SMOOTH_EDGES` to decide on for characters' inner bodies.

### P2 as built (2026-10-30)

P2 is commits e77bb63 to 41f95cf on `pyjoltphysics` `develop`.

- Queries (`src/native/queries.*`, `pyjoltphysics.queries`): `World.raycast`, `raycast_batch`,
  `sweep` with `sweep_sphere`, `sweep_capsule`, `sweep_box` (first hit, or every body's first hit
  in order), `overlap` (ascending uids). `QueryFilter`: group and mask as bodies meet, `exclude`
  uids, `triggers` for sensors, `characters` for proxies. Synchronous on the caller's thread under
  the world lock's shared side, GIL released; on the world thread inside a callback, no lock.
  `closest_point` is not built (Jolt has no cheap closest-point query; a `CollideShape` with a
  growing sphere would answer it). The batched queries answered in the snapshot are not built:
  `raycast_batch` is synchronous.
- The world lock is `WorldLock`, a shared mutex whose gate holds new readers behind a waiting
  writer. With `std::shared_mutex` (reader-preferring on glibc) six querying threads held a
  free-threaded world to 10 of 120 ticks in half a second.
- Characters (`src/native/characters.*`, `pyjoltphysics.characters`): omi's controller ported over
  `CharacterVirtual`: walk, run, sprint, crouch speeds and a speed override, acceleration (inf by
  default, as omi), air control, the exact ballistic vertical motion (`v dt - g dt^2/2` handed to
  Jolt as the velocity that covers it in Jolt's float step) with per-character gravity and
  terminal velocity, jump with coyote time and buffer, `jumpFollowsSlope`, stairs and floor
  sticking (Jolt's `ExtendedUpdate` walk-stairs; the stick is our own, see below), slope limit and
  sliding down steep ground, slide with rise and steer and `slide_progress`, knock-down, get-up,
  crouch, fly, swim, knockback, `apply_impulse`, teleport with a floor search, ignore sets, pass
  groups, push mass and push force, push speed, mutual push between characters by mass, kinematic
  platforms carrying a grounded character. Inputs are `CharacterOps` batches applied at the next
  tick; state is `Snapshot.characters` (id, centre, velocity, state, grounded, ground uid and
  normal, slide progress, last landing speed and tick, height); events are kind `CHARACTER`, phases
  `BEGIN`/`END` (touches), `LAND`, `JUMP`, `SLIDE`, `DOWN`, `UP`.
- Characters move on the world thread inside the tick, under the exclusive lock, before `Update`.
  Characters whose reach shares no other character and no dynamic body are islands moved by
  separate jobs on Jolt's job system, each job with its own temp allocator; within an island in id
  order, with a `CharacterVsCharacterCollision` that sees only the island. The result does not
  depend on the job count.
- The proxy is a kinematic capsule (not a sensor) under the character's id on a collision layer
  role that meets sensors only: rays and overlaps meet it, static and moving sensors report it,
  no body is solved against it. Layers carry a role (body, sensor, proxy).
- `World.swap_bodies(remove, batch)`: one batch, one tick, for tiles streamed around foci.
- `SMOOTH_EDGES` is on by default for static meshes and height fields; `BodyFlag.NO_SMOOTH_EDGES`
  turns it off. Cost not measurable: 5,000 boxes on the 20,000-triangle mesh, 1 job thread, 3.12
  ms a frame with it and 3.24 without (8 threads 1.20 to 1.95 against 1.68 to 1.98, noisy); 300
  characters 1.49 against 1.51 ms, 30 among posts 0.19 against 0.21 ms. A ball rolls flat
  across one field; seams between tile bodies still lift it up to 6 mm.
- Found and fixed by the differential suite: Jolt's own stick-to-floor passes over a walker
  climbing past a crest (it is moving up), so a runner on a height field left the ground for a
  tick at most cell edges (12 ticks in 10 s, 0.74 m short of omi). The controller now sticks a
  grounded walker that did not jump whatever its vertical motion: 2 cm from omi after 10 s.
- Found by the determinism test: a character standing on another reported the other's record
  address as its ground uid. It reports the other's id.

Conformance (`tests/test_characters.py`, 46 tests after omi's character tests) and differential
(`tests/differential/test_characters.py`, 7 scenes against omi's controller), 60 Hz:

| Behaviour | omi | Jolt | Tolerance |
|---|---|---|---|
| Walk 1 s at 3 m/s | 3.000 m | 3.000 m | 2% |
| Speed override 2.5 m/s, 1 s | 2.5 m | 2.500 m | 1 mm |
| 0.3 m step, stepHeight 0.4 | onto it, feet 0.300 | onto it, feet 0.300 | 5 cm |
| 0.6 m ledge, stepHeight 0.35, running | climbs it (feet 0.6) | stopped at the face | divergence, Jolt right |
| 30 degree ramp, 3 s walk | 7.43, 3.17 m | 7.96, 3.49 m (analytic 8.06, 3.50) | Jolt 15 cm of analytic; omi 0.7 m |
| 60 degree ramp, maxSlope 50 | refused | refused | |
| Jump, g 42, jumpHeight 1.5, 60/120/240 Hz | on the parabola to 6e-15 | to 2e-8 / 9e-9 / 4e-9 | 1e-6 |
| Flight ticks, same jump | 31 / 63 / 127 | 32 / 64 / 128 | 1 tick: Jolt stops at its contact and reports ground the tick after |
| Landing speed, 5 m fall (closed form 9.905) | 9.974 | 9.974 | 3% |
| 10 s run across a height field | end (7.336, 0.036, 17.204) | (7.317, 0.038, 17.212) | 10 cm, 2 cm in height |
| Stairs, 6 x 0.2 m | top, 1.2 m | top, 1.2 m | 5 cm; x within 0.6 m |
| Knock-down, get-up | DOWN, 1.0 m; STANDING, 1.8 m next update | same, next tick | exact |
| Push a 20 kg crate walking | 3.0 m/s (15%) | 2.86 m/s | 15% |
| 200 kg crate, pushMass 100 | not moved | moved 1e-6 m, walker held at 0.78 | 2 cm |
| Kinematic platform 1 m/s | carried | 1.000 m/s | 3 cm |
| Steep slope 60 degrees | slides | slides, AIRBORNE | |
| Pass-group peers / non-peers | pass / block | pass / block | |

Divergences beyond the table: a thrown crate shoves a Jolt character while they overlap (Jolt's
character contact) and leaves it no momentum, where omi's service applies a knockback of the
momentum the crate lost; omi zeroes nothing at a ceiling, the port stops the rise there.

Lockstep with characters: 24 characters among posts and crates at 960 Hz, 60 inputs (moves,
jumps, slides, knockbacks) at wall-clock moments while free-running on 8 job threads, replayed in
lockstep with `at_tick` on 1 and 8 job threads: digests of poses and character state over 1,000
ticks identical, 16 repeats, GIL and free-threaded builds.

Benchmarks (`benchmarks/characters.py`; the machine carried other users' processes, load 3.5 for
the rows from the final run, up to 19 for the others):

| | Spike | P2, 1 job thread | P2, 8 job threads |
|---|---|---|---|
| 300 characters on a 256 x 256 height field, ms per 60 Hz frame, 1 tick a frame | 3.08 (1 thread) | 1.48 | 0.60 |
| same, 120 Hz (2 ticks a frame) | | 2.62 | 1.10 |
| 30 characters among 10,000 posts, 60 / 120 Hz | | 0.17 / 0.30 | 0.09 / 0.19 |
| 300 proxies in `Update` | | 0.08 ms a tick | |
| 100,000 scattered rays, one call | 54 ms (0.54 us a ray) | 55 ms (0.55 us) | same |
| one `raycast` from Python, idle world | 1.14 us (native) | 2.3 us | |
| single rays beside a free-running 5,000-box world: p50, p99, max | 1.14 us, 2.2 us; lock wait p99 0.98 ms, max 2.27 | 3.2 us, 2.5 ms, 9.1 ms | 3.2 us, 1.1 ms, 2.8 ms |
| tile swap frame / quiet frame (10 sprinting characters, 32-cell tiles) | | 0.19 / 0.13 ms | 0.23 / 0.13 ms |

Tests: GIL build (3.14) 285 passed, 2 skipped (NEON, free-threaded check); free-threaded 3.14t
233 passed, 3 skipped (no omi_physics there, NEON, the GIL wait); ASan and UBSan (`tools/asan.sh`)
233 passed, 3 skipped, no sanitizer report. Written first and seen failing against P1b's
module (no query, character or swap API); the knock-down, trigger, character-on-character and
many-thread query tests were each seen failing against an earlier P2 build before the fix.

What P4's service layer needs that this API does not give:

1. Previous-tick character rows: the camera interpolates between the last two snapshots
   (decision 8); the service holds the previous `Snapshot` itself.
2. Input latency: an input reaches the character at the next tick (up to one tick plus the
   publish); `Character.frame` hooks (facing, locomotion, footsteps) read the snapshot, so they lag
   the input by that much. Per-tick inputs (path following, `run_along`, `hop_to`) can only be set
   at frame rate unless the service sends them with `at_tick` or a native path track is added.
3. Knockback from struck bodies: the service decides it from the character's `BEGIN` records
   (body uid and closing speed) and the body's mass, as omi's service does.
4. Character-against-character touches are not records; only `ground_uid` names a character
   stood on.
5. Ground material: the snapshot has the ground uid and normal, not the sub-shape (mesh triangle
   material) footsteps would read.
6. `eye` is not published (centre, height and `eyeHeight` give it); a stuck flag from a failed
   teleport is not reported.
7. Gravity direction: a character's gravity is a magnitude along -Y; gravity zones (P3) need a
   direction per character.
8. Water volumes: `set_swim` is a command; detecting water stays with the service.
9. Moving frames: characters ride kinematic bodies through ground velocity; a character framed in
   a moving vehicle's local frame is not modelled.
10. State save and restore must include the controller's state beside `CharacterVirtual`'s.
11. The sample-function landscape: the service samples tiles and calls `swap_bodies`.
12. The capability names beyond OMI (`acceleration`, `pushForce`, `stickToFloor`,
    `smoothEdges`) need a place in the service's `CharacterCapabilities` and glTF extras.

Open problems: (i) push speed is approximate: a character that touched a pushable body last tick
is held to `pushSpeed`. (ii) Jolt lands a falling character a tick later than omi (it stops at the
contact and reports ground the next update). (iii) `query_wait_max_ms` and the p99 were measured
with other users' processes on the machine; a quiet rerun is left for the preflight pass. (iv) `closest_point` and
snapshot-answered batched queries are not built.

### P3 as built (2026-10-30)

P3 is commits ec87fec to 004f7a5 on `pyjoltphysics` `develop`.

- Joints (`src/native/joints.*`, `pyjoltphysics.joints`): `Joint` builders `fixed`, `ball`, `hinge`,
  `slider`, `distance`, `six_dof` (Jolt's `FixedConstraint`, `PointConstraint`, `HingeConstraint`,
  `SliderConstraint`, `DistanceConstraint`, `SixDOFConstraint`), `universal` and `two_axis_hinge`
  (X3D's UniversalJoint and DoubleAxisHingeJoint as six-axis joints; the two-axis hinge's
  `suspension` is a spring on the anchor along the steering axis) and `motor` (X3D's MotorJoint:
  torques about up to three axes, applied in the step listener, no constraint). Limits, limit
  springs, friction, `Motor` (velocity or position, force or torque limit, spring). Joints are
  batches with ids from their own counter, assigned at submission. `set_joint_motors`,
  `set_joints_enabled`, `remove_joints`; removing a body ends its joints (`JOINT` `END`, reason
  `REMOVED`). Force and torque are each constraint's total lambda over the step, read after
  `Update` under the exclusive lock; a joint past `break_force` or `break_torque` is removed and
  reported (`EventKind.JOINT`, `EventPhase.BREAK`). `Snapshot.joints`: id, kind, state, value
  (angle, position or length), value2, force, torque. Jointed bodies do not collide unless
  `collide`: a Jolt `GroupFilter` holding the pairs, set on the bodies of such joints only. There
  is no separate wheel joint: Jolt's wheels belong to `VehicleConstraint` (P6), and the service's
  `add_wheel` maps onto `two_axis_hinge` with `suspension`.
- Materials (`src/native/materials.*`, `pyjoltphysics.materials`): the material index is the top 16
  bits of Jolt's body user data; a mesh triangle carries its own (`Shape.mesh(materials=)`, an
  `IndexedMaterial` in the mesh's material list). Index 0 is the body's own coefficients with
  Jolt's combine. Otherwise the contact listener sets `mCombinedFriction` and
  `mCombinedRestitution` on every contact added or persisting: the higher of the two combine modes
  (average < minimum < multiply < maximum, the OMI modes; omi uses the first body's mode), a
  pair entry of the (M, M) table over that, static friction below
  `WorldSettings.static_friction_speed` (0.05 m/s, opinion) of slip at the contact, dynamic
  above. Records carry `material_a` and `material_b` in the former reserved word; characters
  publish `ground_material`.
- Collision filters: a `filter` index per body is part of its object layer key; the (F, F) table
  is read by `ObjectLayerPairFilter::ShouldCollide`. `set_filter_table` applies at the next tick
  and wakes every dynamic body; an index outside the table meets every filter.
- Contact filter: `Collector::OnContactValidate` asks `WorldCore::solve_pair` for solid pairs whose
  bodies both carry `BodyFlag.FILTER_CONTACTS`, after the layer and group filters. A verdict cache
  (mutex, keyed by body pair) answers repeats; a refused pair's verdict expires at the first tick
  the pair is not validated again, a solved pair's when the pair tracker ends it. Each job thread
  makes one `PyThreadState` on first use, kept in a per-world map and deleted by the world thread
  (attached) when its loop ends. No deadlock: the world thread holds the world lock exclusively
  and is detached during `Update`, and every call that waits for the world lock releases the GIL
  first. A query from the filter raises (a thread-local flag); an exception stops the world after
  the step. Decision 9 as recommended.
- Fields (`src/native/fields.*`, `pyjoltphysics.fields`): gravity zones (box, sphere, registered
  shape by `CollidePoint`; directional and point; priority, replace, stop) and quadratic drag in
  one `PhysicsStepListener`, so they apply before every collision step; the zone acceleration is
  added as a force of `m gf (g_zone - g_world)`. Characters take the vertical part of the zone
  gravity at their centre. Kinematic tracks (sampled, linear and slerp, loop or hold) and
  `World.drive(uid, pose_fn)` (a native `drivers` callback after `before_step`, moving bodies in
  the same tick through `move_kinematic`) move kinematic bodies with `MoveKinematic` before the
  characters and `Update`.
- From P2's list: 1 (`CharacterRows.previous`), 3 (a dynamic body's momentum at the closing speed
  as the character begin record's `impulse`), 4 (character touches of characters as `CHARACTER`
  `BEGIN`/`END` with `b` the other's id), 6 (`eye`; `stuck` after a teleport left the capsule more
  than 1 cm inside a body) are built.

Differential suite (`tests/differential/test_p3.py`, 12 scenes, 120 Hz):

| Scenario | omi | Jolt | Tolerance |
|---|---|---|---|
| Hinge pendulum, 1 m, 0.15 rad, period | 2.008 s | 2.008 s (analytic 2.006) | 2% |
| Chain of 6 ball links after 2 s, worst gap at a joint | under 1 cm | under 1 cm | 1 cm |
| Hinge stop at -0.5 rad, rest angle | -28.65 degrees (0.4 m box) | -28.69 / -28.90 / -29.44 degrees (0.4, 0.2, 0.1 m boxes) | 1 degree |
| Hinge velocity motor 3 rad/s | 3.000 | 3.000 | 2% |
| Slider stopped at -1 m, height | 1.0000 m | 0.99999993 m | 1 mm |
| Rigid distance 2 m after 2 s | 2.0007 m | 2.0003 m | 1 mm |
| Pair friction grid, 4 pairs on a 20 degree ramp, 1 s | 1.459, 0.995, 0.530, 0.205 m | 1.459, 0.995, 0.530, 0.205 m | same order; 15% |
| Average of 0.4 and 0.1, 1 s slide (analytic 0.525) | 0.530 m | 0.530 m | 10% or 3 cm |
| Material restitution 0.7, second apex over first | 0.564 | 0.540 | 0.05 |
| Filters: ball and shard systems, pairs that touched | same set | same set | exact |
| Gravity zones (box, point, replacing sphere), position at 2 s | | within 1.4e-6 of omi relative to the distance travelled | 1% |
| Kinematic pose function, 2 s on a helix, worst error a tick | under 1e-6 m | under 1e-6 m | 1e-6 m |
| Sampled track against linear interpolation | | under 1e-6 m | 1e-6 m |

Divergences: omi's hinge stops throw a 0.2 m box (inertia 0.0067 kg m2) past the stop to +0.69
rad and fling a 0.1 m box away (381 km in 5 s); Jolt holds all three within 0.8 degrees. The
differential compares the 0.4 m box. omi takes the first body's combine mode; the port takes the
higher. Jolt uses static friction until the slip passes 0.05 m/s, omi uses the dynamic
coefficient throughout, so the grid scenes give each pair one coefficient.

Unit tests: `test_joints.py` (22), `test_materials.py` (12), `test_fields.py` (17),
`test_contact_filter.py` (8), `test_characters_p3.py` (6). `test_joints.py` was written before
the Python layer and seen failing (no `Joint` in the package); the others were written after the
code they test and then run against P2's package in a clean environment, where each fails to
collect (the API it calls is absent). `test_p3_lockstep.py`:
a free-running 480 Hz world on 8 job threads with 200 boxes in three materials and three
filters, the contact filter, a chain of hinge and breakable ball joints, a motor joint, a motorised
wheel, a looping kinematic track, two gravity zones and drag, given 30 impulse batches at
wall-clock moments, replayed in lockstep with `at_tick` on 1 and on 8 job threads: digests of
poses and joint rows over 600 ticks identical, 4 repeats.

Builds: GIL build (3.14) 369 passed (doctests included), 2 skipped (NEON, the free-threaded check); free-threaded 3.14t 303 passed, 3 skipped (no omi_physics there,
NEON, the GIL wait); ASan and UBSan (`tools/asan.sh`) 303 passed, 3 skipped, no sanitizer report. ruff, ruff format, mypy strict and `oglc-check` clean; `_native.pyi` regenerated.

Benchmarks (`benchmarks/boxes5000.py`, `benchmarks/characters.py`; P2 commit 41f95cf and P3 built the
same way and run back to back, best of 3, ms per 60 Hz frame):

| | P2 | P3 |
|---|---|---|
| 5,000 active boxes, mesh ground, 1 job thread | 1.959 to 1.985 | 1.961 to 1.979 |
| same, 8 job threads | 0.959 to 1.034 | 0.961 to 1.071 |
| 300 characters on a height field, 60 Hz, 1 job thread | 1.41 to 1.44 | 1.45 to 1.46 |
| same, 8 job threads, 960 frames, 4 runs each | 0.600 to 0.708 | 0.640 to 0.744 |
| same, 120 Hz, 1 / 8 job threads | 2.67 to 2.73 / 1.05 to 1.18 | 2.67 to 2.68 / 1.07 to 1.20 |
| 30 characters among 10,000 posts, 60 Hz, 1 / 8 | 0.164 to 0.199 / 0.132 to 0.136 | 0.181 to 0.227 / 0.124 to 0.133 |

The ranges overlap in every row (load average 2.5 to 3.0 from other users' processes). The P3
paths a P2 scene meets are the material lookup on each contact (where neither
body has a material: a virtual `GetMaterial` and a user-data read per side), the empty step
listener and the character rows' ground material.

What P4 still needs from this list and from P2's:

- P2 item 7, gravity direction: characters take the vertical part of zone gravity. A character
  pulled sideways or upwards (walking on a planetoid) needs `CharacterVirtual::SetUp` and an up
  vector through the controller's state machine, which assumes +Y throughout (`kUp`); that is a
  controller change for P6 or a game that needs it.
- P2 item 8, water volumes: a sensor flag that sets swimming needs a per-character overlap each
  tick and the service's water depth rules; the service keeps detecting water and calls
  `set_swim`.
- P2 item 10, controller state in save and restore: belongs with `PhysicsSystem::SaveState` (P4),
  so the two are saved together.
- P2 item 12, capability names: the service's `CharacterCapabilities` (P4a) and glTF extras.
- The service's mapping: `add_hinge`/`add_ball`/`add_slider`/`add_distance`/`add_universal`/
  `add_wheel`/`add_motor` onto `Joint`; `Materials` onto `World.materials`; `CollisionFilter`
  systems onto the (F, F) table, computed by the service from its filters; the contact filter's
  `Approach` from `(a, b, point, normal, approach)`, with `impulse` from the bodies' masses;
  gravity zones from `zones.py`; `Body.drive` onto `World.drive`.
- The X3D RigidBodyPhysics tutorials against their omi captures: they render through the service,
  which reaches Jolt only with P4's `engine.py`, so the comparison is P4's.

Decisions taken in P3 where the plan left them open: the combine mode of two materials is the
higher of the two (the OMI order), the static friction speed defaults to 0.05 m/s, a filter index
outside the table meets every filter, the contact filter follows decision 9, and a slider's anchor
defaults to its body's origin.

### P4a as built (2026-10-30)

P4a is the neutral public API of `OpenGLContext.physics`, still on omi_physics: commits 142c81d2,
6b4d3d5c and 65d75a56 on `openglcontext` branch `neutral-api` (off `develop` fcef17af).

- `physics/types.py`: `Material`, `CollisionFilter`, `CharacterCapabilities` (OMI field names and
  defaults), `CharacterState`, `EngineInfo`, `Poses`, `GravityZone`, `Hit`. An object with the
  same fields (an omi instance) is accepted at the boundary; `Material`, `CollisionFilter` and
  `CharacterState` compare equal to omi's of the same values.
- `physics/omi_adapter.py` holds the conversions: materials, presets, filters, capabilities, state,
  proxy to omi `Shape` (made once a proxy), cooking, hull volume, gravity, gravity volumes, motion,
  the contact filter. `runtime.py` holds `JointTable` and `build_joint`.
- New calls: `physics.poses(bodies, interpolated=)`, `physics.engine`, `physics.on_step(fn)` with a
  `StepView` (`physics/stepview.py`), `add_universal`, `add_wheel`, `add_motor`, `Joint.angles`,
  `angle`, `position`, `drive(torques=)`, `Body.gravity_factor`, `set_gravity_factor`,
  `step_position`, the `gravity_factor` add option, `Character.vertical_speed`, `height`, `radius`,
  `stuck`, `motion_state`. `Proxy` is `kind` and `params`; `overlap` takes a `Proxy` only;
  `zones.Box` and `zones.Sphere` are own classes; `set_config` applies a changed `backend` and
  `engine.compute` names it. `BodySpec` carries a neutral `records.Motion`.
- Deprecated aliases, each warning once a process, kept while the games use them: `physics.world`,
  `backend`, `slot_of`, `body_at`, `index_of`, `run`, `Character.controller`, `Proxy.shape`.
  `Character.state` answers omi's member (equal to `CharacterState`) because hill-runner compares it
  with `is`; it becomes the `CharacterState` member when the games migrate. The commit after the
  migration removes the aliases.
- `OpenGLContext.testing.physics` (`inspect`, `slot_of`, `body_at`, `run`) reads the omi world for
  tests; the engine suite's tests that read omi arrays use it.
- Still importing omi_physics in `OpenGLContext/physics/`: `omi_adapter`, `runtime`, `worker`,
  `replica`, `queries`, `character` (the controller), `colliders` and `gltf_world` (glTF
  documents), `props` and `debugdraw` (plain omi worlds), `x3drigid` (X3D's own world). Outside it:
  `move/physicswalk.py`, `move/physicsplatform.py`, `move/terrainwalk.py`,
  `loaders/tiles3d/physics_colliders.py`, `loaders/gltf/scene.py`, `passes/zonelayers.py`,
  `bin/physics_cook.py`, `bin/terrain_view.py`. No public signature or value names an omi type
  (`tests/unit/test_physics_neutral_types.py` walks the API).
- The games on `develop` pass against the branch unchanged. Their migration list is in the P4a
  report; marble-demo's mechanisms move to `poses`, `on_step` and `set_gravity_factor`, glisteel's
  car keeps the raw world until vehicles (P6).

### P4 as built (2026-10-31)

P4 is branch `jolt-engine` on `openglcontext` (commits e37da864 to the merge) and commits
7b255f5 to 5969b84 on `pyjoltphysics` `develop`.

- `physics/engine.py`: `Engine`, the interface the service drives (commands, collect and step,
  live reads, joint readings, queries, characters, contact filter, counts, state), `make_engine`,
  `EngineUnavailable`. `PhysicsDefinition.engine` (`'omi'`, `'jolt'`; env
  `OPENGLCONTEXT_PHYSICS_ENGINE`, read once, inherited by captures). A definition naming Jolt
  without pyjoltphysics raises `EngineUnavailable`; nothing falls back.
- `physics/omiengine.py` holds the omi worker, runtime, replica queries, the omi contact filter
  and the omi character controller; `physics/joltengine.py` the Jolt world (1,900 lines with
  `JoltController` and `GroundTiles`). Commands keep the service's vocabulary; the Jolt engine
  turns each into pyjoltphysics batches and keeps the service's uids, mapping event and query
  uids back. The stand-in machinery stays in the service for the omi engine only.
- Threads. The Jolt world runs on pyjoltphysics' world thread. Lockstep (`run_ticks` for the
  ticks a frame owes) for `inline`, a world held by `pin_inline` (captures, recordings,
  replays) and any world with framed characters; free-running in `thread` mode otherwise.
  World-thread callbacks are registered only while a step handler, `on_step` hook, physics-thread
  event handler, standing force or posted call needs them, with the switch interval at 1 ms then
  (decision 7).
- Character input latency (P2 item 2). Chosen: the plan's at-tick delivery taken to lockstep.
  A world with framed characters runs the frame's ticks one at a time; before each, every framed
  character's code runs (`before-step` handlers, knocks, `run_along`/`hop_to` steering) and its
  input batches apply at that tick; after it, `after-step` handlers and landings. An input set in
  a frame drives the frame's first tick, and per-tick steering runs at the world rate, as on omi.
  Inputs that change a character's state (jump, slide, crouch, fly, swim, knock-down, impulse)
  read back at once and hold until the world reports the tick that applied them.
- Characters: `JoltController` over `pyjoltphysics.Character`; eye, previous-tick rows, stuck,
  ground material (footsteps), pass groups by name, ignore sets, knockback from the begin record's
  momentum (only for a body moving toward the character), teleports that stand on the floor under
  them (a ray down the axis), new characters seated on the ground, capsules kept at least their
  diameter tall, characters lifted onto a sampled ground they are below. Owner-stepped
  characters (`framed=False`) advance the world: `step(dt)` runs the ticks `dt` owes.
- Ground: a sample-function ground is height field tiles, 32 cells a side at half the
  `feature` (0.25 to 2 m), kept around characters, awake dynamic bodies, named foci and each
  query's path, swapped with `swap_bodies`.
- Queries apply waiting batches first (`World.flush`, which publishes); `Hit.triangle` is the
  mesh triangle's row (`World.triangle_of`); a sweep starting inside a body answers 0.
- Joints: hinge, ball, slider, distance, universal, wheel (`two_axis_hinge`, suspension from
  stiffness and damping by the wheel's mass) and motor; motors and torques; readings from the
  joint rows, a motor joint's angles from the bodies' relative turn; a removed body's joints
  forgotten.
- Materials, pair grid (`MaterialTable.pairing`), collision filters (the (F, F) table from the
  filters), contact filter (asked where either body has a handler, refusals as unsolved `hit`s),
  gravity zones (box, sphere, zone shapes by box or sphere), drag, `Body.drive`, standing forces
  and torques (resubmitted before each tick), `post`, `Physics.counts`, `physics.engine`,
  `Physics.save_state`/`restore_state` (bodies and joints; omi raises `NotImplementedError`).
- `poses.write_poses` writes a frame's poses in bulk (float32 rows stored once where the
  fields store as the base field does), for both engines.
- `OpenGLContext.physics.x3djolt.JoltRigidSystem`: X3D's RigidBodyPhysics on a pyjoltphysics
  world, chosen by `OPENGLCONTEXT_PHYSICS_ENGINE`: centre of mass, the inertia diagonal omi uses,
  rest only under `autoDisable` (by Jolt's sleep rules), contacts with the world as per-frame
  surfaces, the six joints and every joint output. `RigidSystem.joint_values` gives either
  engine's joint outputs; the X3D rigid body suites run on both engines.
- pyjoltphysics additions, each test first: `set_motion` (mass, damping, gravity factor,
  inertia tensor),
  `set_flags` (REPORT, NO_SLEEP, FILTER_CONTACTS), `save_state`/`restore_state`,
  `WorldSettings.penetration_slop` (the service uses 5 mm), `World.flush` (publishing),
  `Shape.mesh(ids=)` and `triangle_of`, `MaterialTable.pairing`,
  `set_contact_filter(either=, recheck=)`, commands from `before_step`/`at_tick`/`drive` code
  applied in the same tick, `World.bodies_state`, the event record's `depth` (72 bytes),
  `Shape.box(rounding=)`, snapshot history by publish rather than tick.

Tests. The service suites are parametrised by the `engines` marker (`tests/unit/conftest.py`):
a module or test marked `engines('omi', 'jolt')` runs once per engine with
`OPENGLCONTEXT_PHYSICS_ENGINE` set; one marked `engines('omi', reason=...)` reads omi's own
objects (the runtime, the replica, the worker threads, the stand-in, the omi colliders for roads,
props and height field chunks) and runs on omi only. Expectations that differ per engine are
written per engine in the test, each with its reason (step length fixed by `tickHz`, float32
positions, pushing between pass groups, owner-stepped characters advancing the world).
`OpenGLContext.testing.physics` gained engine-neutral helpers (`settle`, `wait_ticks`, `idle`,
`ticks`, `holds`, `shape_kind`, `mass`, `material`, `pair_friction`, `joint_count`,
`world_position` and others) for what tests used to read from the omi world.

| Suite | omi | Jolt |
|---|---|---|
| openglcontext `tests/unit` (not serial), engine default | 19,128 passed | 19,128 passed |
| tests parametrised by engine within it | 1,069 (361 omi only) | 708 |
| openglcontext `tests/unit -m serial` | 29 passed | 29 passed |
| hill-runner | 652 passed | 648 passed, 4 failed |
| twig-bb | 2,407 passed | 2,384 passed, 23 failed |
| marble-demo | 941 passed | 914 passed, 27 failed |
| marble-editor | 165 passed | 165 passed |
| glisteel | 1,669 passed | 1,283 passed, 386 failed (the vehicle reads the omi world); with `engine='omi'` in its definition, 1,659 passed, 10 failed |
| openglcontext-forest | 86 passed | 86 passed |

The game failures on Jolt, by cause:

- Reading the omi world (`physics.world` and the other deprecated aliases, which raise on
  Jolt): marble-demo 18, twig-bb 3, glisteel 10 (`test_traffic`, through `testing.inspect`) and
  all 386 of glisteel's without the hook (its car is omi's `RaycastVehicle`).
- Float32 precision: hill-runner's two lattice tests ask for the ground's height to 1e-6 and
  1e-9 m and get it within 4e-6 and 7e-6 (heights near 45 m, Jolt's float32 shapes and ray
  fractions).
- Rays tangent to a capsule: twig-bb's combat and hit-box tests (about 18) fire along y = 0 at
  capsules whose lowest point is at y = 0; Jolt misses, omi hits.
- Numbers tuned on omi: hill-runner's knocked-down runner (0.0203 m drift against a 0.02
  tolerance) and its 240 Hz jump arc (a 120 Hz world repeats a pose); marble-demo's lip bounce
  (0.32 m at 28 m/s), rockfall spreads and crash rule, the gauntlet's timings, banked turns,
  narrows, pegs, the updraft gap and the destruction thresholds.

Benchmarks: `scratchpad/framecost/bench.py` cases, the service's frame in ms (mean over the
measured frames; `T_` cases are threaded with a frame handler, `s` cases settled, `k` characters):

| Case | omi | Jolt |
|---|---|---|
| twig | 1.227 | 0.33 |
| d100 | 16.440 | 0.358 |
| d1000 | 159.765 | 1.60 to 1.72 |
| d100s | 0.014 | 0.142 |
| d1000s | 0.046 | 0.317 |
| d1000s_10k | 0.046 | 0.638 |
| k5 | 1.137 | 0.303 |
| k30 | 4.988 | 1.038 |
| k30_10k | 10.610 | 1.486 |
| d100k30 | 21.938 | 1.223 |
| d1000sk30 | 47.505 | 2.302 |
| T_d1000s | 0.992 | 2.078 |
| T_d100k5 | 4.113 | 2.507 |
| T_d1000k30 | 129.174 | 6.460 |

Hill-runner `Session.step`: omi 0.570 ms (`Physics.frame` 0.439), Jolt 0.287 ms (0.192), over
the same 117 m. Settled worlds cost more on Jolt (0.14 to 0.64 ms against 0.01 to 0.05): a
lockstep world ticks every owed step whether or not anything is awake, and omi's settled-world
shortcut skips the step.

X3D RigidBodyPhysics: `tests/unit/test_x3d_rigidbody_demo.py` passes on both engines. The demo's
frames, Jolt against omi at 320x180 (channel delta over 5): 1.8% of pixels at 0.5 s, 3.5% at
1 s, 4.9% at 2 s, 7.0% at 4 s. The door's stop bounce, the ball's bounce phase and the settled
heap differ; the 2% visual tolerance is met by neither capture after the first contacts, so the
tutorials do not yet compare Jolt against omi captures.

Behaviour that differs on Jolt:

- The tick rate is `tickHz` and fixed; a frame stepping at 240 Hz against a 120 Hz world repeats
  poses between ticks.
- Gravity zones turn a character's vertical axis only; sideways gravity on a character is not
  modelled (bodies follow any direction).
- Commands sent from `after-step` code apply at the next tick.
- A ray exactly tangent to a capsule's pole misses; omi reports a hit at distance 0 (twig-bb
  aims rays from y=0 at bots whose capsule pole is at y=0).
- Positions, velocities and shapes are float32 in Jolt: test tolerances of 1e-6 fail
  (0.4999997 for 0.5). Height field heights are quantised by Jolt's height field compression
  (a few mm).
- Characters push dynamic bodies through `CharacterVirtual`'s contact impulse; characters in
  different pass groups do not push each other.
- An owner-stepped character (`framed=False`) advances the world by its `step(dt)`.
- A pair the contact filter refuses reaches handlers as an unsolved `hit`, with no `separate`.
- `save_state` holds bodies and joints; characters and the tick count are not saved.
- Bounces and stacking settle differently (Jolt's solver, restitution threshold and sleep
  rules): marble-demo's lip bounce, rockfall crash count, and the updraft gap are numbers tuned
  on omi.

What P5 needs:

- marble-demo off direct omi imports (18 of its Jolt failures read `physics.world`), and
  hill-runner's and twig-bb's tests that read the omi world moved to `testing.physics`'s neutral
  helpers.
- The game tests tuned on omi numbers (above) retuned against Jolt, with the tolerances the
  float32 world allows.
- glisteel's vehicle stays on omi until P6: `engine='omi'` in `glisteel.world.physics_definition`
  (one line, not committed, as it needs a released engine with the `engine` field), and
  `test_traffic` off `testing.inspect`.
- The omi-only engine tests (`engines('omi')`) rewritten against the neutral helpers or deleted
  with `worker.py`, `runtime.py`, `replica.py` and `queries.py`.
- The X3D rigid body tutorials compared against their own Jolt captures rather than omi's.
- `pyjoltphysics` registration (GitHub remote, wheels) before it becomes a hard dependency.

### P5: marble-demo on Jolt (2026-10-31)

marble-demo's suite passes on both engines (941 tests each); marble-editor's 165 do.

- Tests that read the omi world: contacts through the marble's `hit`/`touching` handlers
  (`tests/contactlog.py` in marble-demo), body counts through `physics.counts`, materials and
  pair friction through `testing.physics`, the contact log through the new
  `testing.physics.event_backlog` (pyjoltphysics `stats()['events_held']`), the engine's
  inertia through the spin an angular impulse gives.
- Seams. A marble rolling across the seam between two static tile bodies was kicked up on
  Jolt (3.2 m/s at 28 m/s, 0.5 at 10): the speculative contact with the next tile's edge.
  Jolt's enhanced internal edge removal works within one body pair. pyjoltphysics' `seams.cpp`
  collides a moving `SMOOTH_EDGES` body with a static body together with the static bodies
  beside it through one `InternalEdgeRemovingCollector`, keeps the pair's own hits, and turns
  an edge hit lying on a seam with a coplanar face of another body to that face's normal; the
  Jolt engine gives every dynamic body `SMOOTH_EDGES`. Through the service the kick is under
  0.01 m/s at 10 to 28 m/s. This was the lip bounce, the updraft gap and the rockfall spreads
  and crash rule. A floor of one mesh per surface also removed the kick on Jolt, but scattered
  the marble on omi (its triangles' own edges); a compound per surface was slow on omi.
- Persist impulses. pyjoltphysics' persist records carried impulse 0, so the controller's crash
  rule never fired while a sweeping arm kept pushing the marble; they now carry the impulse
  `EstimateCollisionResponse` gives for the tick.
- Numbers: the gauntlet's best moment is found at 0.1 s steps (2.2 s on Jolt, 0.5 s on omi,
  each within 1.3 times the clear lane); the pegs chute is tested with the arrival speed
  applied a frame before the chute reads it (Jolt applies a step's commands after its
  callbacks return); a driven body's velocity within float32's 1e-6.

### Follow-ups as built (2026-10-31)

Branch `jolt-followups` on `openglcontext`; `pyjoltphysics` `develop` d178674 to 72ed82f; the
workspace root b1e4c65.

- Settled worlds. pyjoltphysics counts lockstep ticks without stepping once a world is quiet: no
  awake body, character, kinematic track or target, motor torque or step callback, and two
  stepped ticks in a row that applied no batch and made no contact report (the tick after bodies
  fall asleep reports their contacts' removal, so the third is the first quiet one).
  `run_ticks(n)` then advances the tick count and time and publishes once on the calling thread;
  `stats()['quiet_ticks']` counts them. A woken world matches one stepped through every tick
  bitwise (pyjoltphysics and engine tests). `Snapshot.rows_of` looks uids up in an array indexed
  by uid (the dict built per snapshot cost 0.5 ms at 11,000 bodies). `JoltEngine._publish`
  republishes the last snapshot with the new tick where nothing was live, nothing applied and the
  tick wrote no row. `bench.py` frame cost in ms (Jolt before is this branch's base with
  pyjoltphysics 5969b84; the machine was shared, so the active cases are the lowest of four
  runs):

  | Case | omi | Jolt before | Jolt after |
  |---|---|---|---|
  | d100s (100 settled boxes) | 0.014 | 0.136 | 0.013 |
  | d1000s | 0.045 | 0.328 | 0.023 |
  | d1000s_10k | 0.046 | 0.753 | 0.023 |
  | d100 (100 boxes awake) | 16.95 | 0.380 | 0.286 |
  | d1000 | 174.1 | 2.233 | 1.013 |
  | k30 (30 characters) | 7.31 | 1.054 | 0.920 |
- Tick rate. Chosen: interpolate. A Jolt frame that owes no tick draws moving bodies between the
  tick before the newest and the newest at the frame's alpha, as omi's inline worker does; four
  frames a tick move a body a quarter tick each on both engines. `tickHz` stays the simulation
  rate; `poses(interpolated=False)`, `step_position` and owner-stepped characters advance by
  whole ticks (documented on `PhysicsDefinition.tickHz` and in docs/physics.rst).
- Aliases removed: `Physics.world`, `backend`, `BACKENDS`, `slot_of`, `body_at`, `index_of`,
  `run`, `Character.controller`, `Proxy.shape`; `Character.state` is a `CharacterState` on both
  engines, and `omi_adapter.engine_character_state` is gone. A workspace search (games, editors,
  forest, qt, downstream; working trees included) found no remaining use. The private forms stay
  for `OpenGLContext.testing.physics`.
- pyjoltphysics: `ruff format` over four files; `tox -e typecheck` installs the `test` extra.
  Preflight's typecheck environment installed projects without extras, so pyjoltphysics' typecheck
  of its tests found no pytest. A typecheck run in `tools/preflight.toml` now names `extras`
  (`["test"]` for pyjoltphysics) and the environment installs the project with them; verified in a
  private environment (`mypy src/pyjoltphysics tests`: no issues in 43 files). The shared
  `.preflight-venv` needs `tools/preflight.py --rebuild-env --only typecheck` once.
- X3D rigid bodies. No tutorial in `tests/tutorials` and no reference image holds a
  RigidBodyPhysics scene; the frames measured at P4 are `oglc-x3d-rigidbody`'s, which its unit
  test checks by numbers on both engines. Per part of that scene, the divergence of a 1 mm nudge
  to every body against the omi-Jolt difference, at 4 s:

  | Part | nudge, omi | nudge, Jolt | omi against Jolt | Verdict |
  |---|---|---|---|---|
  | crate heap (5) | 1.32 m | 0.32 m | 0.80 m | chaotic |
  | dumbbell | 0.23 m | 0.29 m | 0.27 m | chaotic (balanced on its middle) |
  | ball bounce | 0.6 mm | 0.7 mm | 0.77 m | deterministic |
  | door and stop | 2.8 mm | 2.2 mm | 0.70 m | deterministic |
  | chain (3 links) | 4.0 mm | 3.2 mm | 35 mm at 2 s | deterministic |
  | piston slider | 1.0 mm | 1.0 mm | 24 mm | deterministic |
  | cardan shaft | 1.0 mm | 1.0 mm | 0.6 mm | agree |
  | wheel, statics | equal | equal | 0 | agree |

  The deterministic differences, looked into: the ball meets the floor at 7.84 m/s with the
  sensor's bounce 0.85; Jolt sends it back at 6.72 m/s (0.857), omi at 5.94 m/s (0.758), so
  omi's contact restitution under-bounces. The door hits its stop (`stopBounce` 0.4) at about
  2.5 rad/s; omi returns it at 0.49 rad/s and Jolt at 0.12 rad/s, because `x3djolt` does not
  apply `stopBounce` (documented in docs/x3d.rst). The chain and piston differences follow
  the solvers' joint softness and were not traced further. No Jolt reference image was added: a
  capture of the whole scene holds two chaotic parts, and the deterministic parts are checked by
  numbers.

- pyjoltphysics `test_a_dropped_world_joins_its_threads` (72ed82f). Reproduced in most parallel
  runs (`-n 16`, GIL and free-threaded builds). The world joins its threads; the test counted
  `/proc/self/task`, which lists a joined thread until the kernel removes the task, and an
  earlier test's world freed by the collector mid-test joined its threads then. The test now
  collects first and waits up to 5 s for the count. Loops under doubled load then turned up three
  more timing tests (the broad phase rebuild read before the world thread made it, ten thousand
  posts applied within a tick, ticks counted beside queries); fixed the same way or marked
  `serial`. 80 runs of both builds under doubled load, and the lifecycle and query modules under
  ASan, passed.

Left:

- `stopBounce` on Jolt joints (hinge, slider, double-axis hinge): a per-tick velocity reversal
  at the limit in `x3djolt`.
- omi's contact restitution at bounce 0.85 (0.758 measured).
- Free-running (`thread`) settled worlds: T_d1000s is unchanged by this work.

## 7. Decisions

Decided 2026-10-30: each recommendation below was accepted as written. On 5 the answer was to
turn the deterministic build on, and on 10 to ship both free-threaded and ordinary wheels.

1. Binding. Recommended: nanobind (14 ns a call, free-threaded wheels, mypy-clean stubs, CMake).
   SIP costs 39 ns a call, re-enables the GIL on 3.13t and 3.14t, and its stub fails mypy strict.
2. Name. Recommended: `pyjoltphysics` for the distribution and the import; `pyjolt` is a web
   framework on PyPI.
3. The omi fallback. Recommended: dropped at P5; omi survives as golden results for the
   differential suite.
4. Precision. Recommended: double precision in every wheel; within noise of single here, 3% in
   the first spike, 0.98 mm resolution at 8 to 16 km in single.
5. Cross-platform determinism (`CROSS_PLATFORM_DETERMINISTIC`). Recommended: on, if replays or
   networking must match across machines; best of 4 measured 1.05 ms against 1.13 ms (noise),
   Jolt's documentation states about 8%.
6. x86-64 SIMD floor. Recommended: SSE4.2; 1.21 against 1.13 ms (8 job threads), equal with 1.
7. Switch interval while a physics-thread callback is registered (GIL builds). Recommended: the
   service sets 1 ms; at the 5 ms default, two callbacks cost 10.1 ms a tick when the render
   thread runs pure Python, and 1.14 ms at 0.5 ms.
8. Character input latency. Recommended: characters on the world thread, input applied at the
   next tick (mean 5.13 ms at 120 Hz, 2.61 ms at 240 Hz). The alternative steps characters on the
   render thread under the exclusive world lock, which stalls the world thread for the step.
9. Python contact filter. Recommended: asked synchronously on Jolt's job thread, only for pairs
   whose bodies both opted in, verdict cached until they part. A deferred verdict lets the pair
   interpenetrate or collide for one tick.
10. Free-threaded wheels (cp313t, cp314t). Recommended: yes; measured working with the GIL off.
11. Queries during a step. Recommended: wait for the step (p99 0.98 ms, max 2.27 ms at 8 job
    threads); a non-waiting variant that returns nothing mid-step can follow if a game needs it.
12. Default job threads. Recommended: 4, or the core count less two where smaller (opinion);
    1 job thread doubles `Update` and the query waits.
