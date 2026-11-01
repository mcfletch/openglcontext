# Native physics: pyjoltphysics

Status: **P0 to P3 and P4a landed 2026-10-30. P4 (`engine.py`), P5 (Jolt the default,
pyjoltphysics a requirement), P6a to P6e (vehicles, ragdolls, soft bodies, deaths as ragdolls),
P5b (walking and X3D rigid bodies), Character falls and P5c (the omi engine deleted) landed
2026-10-31.** Decision taken 2026-10-26; design spiked the same day. The `pyjoltphysics`
repository is on GitHub (`mcfletch/pyjoltphysics`, branch `develop`), and root commit ccdb196
registers it in the workspace. It is not on PyPI yet, so OpenGLContext's CI builds it from that
repository. OpenGLContext steps its physics with Jolt only: `engine='omi'` raises ValueError,
and no game or editor depends on omi_physics. The 2026-10-31 review's findings and their fixes
are under "Review follow-ups".

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
| 100,000 scattered rays | about 122,000 (estimated; no run recorded) | 156 | 54.2 | |

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
both threads take a lock (the handler table its own; the Jolt engine's body, mover, joint, force
and vehicle tables `JoltEngine.lock`, held by every command, the frame's publish and the world
thread's standing forces, never across a call that waits for the world thread); and nanobind's
`FREE_THREADED` build is a separate wheel per version (cp313t, cp314t).

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
| `records.py` | `Snapshot` and `Command` go; `PhysicsEvent`, `Step` and `BodySpec` (with neutral types) stay. As built, all five stay: `engine.py` and `joltengine.py` take `Command` records and publish `Snapshot`s |
| `body.py`, `joints.py` (`Joint` handle), `events.py`, `handlers.py`, `callbacks.py`, `filters.py`, `materials.py`, `zones.py`, `colliders.py` (scenery tracker), `proxy.py` (cooking), `sources.py`, `x3drigid.py`, `x3dcollision.py`, `gltf_world.py`, `debugdraw.py`, `landscape.py`, `road.py`, `props.py` | stay, with the omi types replaced as below; `JointTable` is deleted |
| `PhysicsDefinition.mode` (`inline`, `thread`, `process`) | removed; `engine` (`'omi'` or `'jolt'`) during P4, removed after P5. As built, `mode` stays with `MODES = ('thread', 'inline')`, and `engine` stays with `ENGINES = ('jolt',)` |

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
  `verify-everything.py`, CLAUDE.md) is a patch waiting for the GitHub remote (landed as root
  commit ccdb196 once the remote existed). It does not list
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
| P6 | Vehicles (glisteel parity, then motorcycles and tracked), ragdolls driven by animation, soft bodies | differential vehicle scenarios against omi's `RaycastVehicle`; glisteel lap times; new tutorials | glisteel drives on Jolt within its handling tests; a ragdoll and a cloth tutorial ship | 4 to 8; P6a (vehicles in pyjoltphysics) and P6c (ragdolls and soft bodies in pyjoltphysics) done 2026-10-31, below; P6b (vehicles through the service) done 2026-10-31; P6d (ragdolls and soft bodies through the service) done 2026-10-31, below |

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
sanitizer report (over that suite, which reached none of the review's C1 to C6; see Review
follow-ups). Lockstep replay of a free-running run with 40 impulse batches: per-tick pose
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

The omi column records what the run printed. `test_scenes.py` asserts only part of it: for the
stack it checks omi's top height and not that omi's stack is asleep, and for the kinematic sensor
it accepts omi reporting no events or an enter and an exit.

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
that environment). ASan and UBSan (`tools/asan.sh`): 150 passed, 3 skipped, no sanitizer report
over that suite;
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
233 passed, 3 skipped, no sanitizer report over that suite. Written first and seen failing against P1b's
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
  (attached) when its loop ends. No GIL deadlock: the world thread holds the world lock
  exclusively and is detached during `Update`, and every call that waits for the world lock
  releases the GIL first. A call that waits for the step it runs inside raises: a query,
  `save_state`, `flush`, `wait_tick` and `run_ticks` from the filter (a thread-local naming the
  world whose filter the thread runs), `wait_tick` and `run_ticks` from a step callback; `stop`
  from either asks for the stop and joins nothing. An exception stops the world after the step.
  Decision 9 as recommended. (Until the review follow-ups, H2 below, those calls hung.)
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
NEON, the GIL wait); ASan and UBSan (`tools/asan.sh`) 303 passed, 3 skipped, no sanitizer report over that suite. ruff, ruff format, mypy strict and `oglc-check` clean; `_native.pyi` regenerated.

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
  The remote and the registration landed (root ccdb196); PyPI wheels wait for its first release.

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

### P5 as built (2026-10-31)

Branch `jolt-default` on `openglcontext` (ec03d475 to the plan commits); `pyjoltphysics`
3842fbc and 6972715 (recorded omi answers) and 715e893; `omi_physics` 1bbfb1b (deprecation note);
`hill-runner` 0816176.

- Default. `PhysicsDefinition.engine` and `OPENGLCONTEXT_PHYSICS_ENGINE` default to `jolt`.
  `pyjoltphysics` is a requirement of OpenGLContext, with no version floor (it is not on PyPI;
  `tools/release.py` raises only floors that exist, so the floor is written when pyjoltphysics
  is first released). `omi_physics>=0.4.0` is the `omi-physics` extra and is not in `all`.
- `engine.require_omi(feature)` raises `EngineUnavailable` naming `pip install
  OpenGLContext[omi-physics]`; `make_engine` raises it for `engine='omi'` without omi_physics.
- Moved off omi_physics (the service path on Jolt imports none of it):
  - `physics/cooking.py`: the hull, concavity, convex decomposition and hull volume
    `Proxy.from_mesh` cooks with (omi's `hull` and `cookery`, MIT, same author), with a
    differential test against `omi_physics.cookery` while it is installed.
  - `physics/omigltf.py`: the `OMI_physics_*` reader, into `Proxy`, `Material`,
    `CollisionFilter` and `records.Motion`; the glTF loader and the scenery tracker use it. A
    `convex` or `trimesh` shape names a glTF mesh; the tracker builds it from the triangles of
    the node that carries the body.
  - `materials.PRESETS` (wood, metal, rubber, ice) in place of omi's presets.
  - `passes/zonelayers.py`: zones near a box by one vectorised overlap test in place of omi's
    `DynamicAABBTree`.
  - `character.py` and `service.py` reach the stand-in machinery through the engine
    (`Engine.build_replica`, `proxy_bounds`, `push_reach`); `bin/physics_cook.py`,
    `bin/terrain_view.py`, `move/terrainwalk.py` and `PhysicsWalkMixin.characterCapabilities`
    use the engine's `CharacterCapabilities`.
- Isolated (import omi_physics on use, and say which extra to install):
  `gltf_world.collision_world_from_scene` and `collision_groups`, `props.PropColliders`,
  `loaders/tiles3d/physics_colliders.TerrainColliders`, `PhysicsViewPlatform(world)` (raise
  `EngineUnavailable`); `PhysicsWalkMixin.ensurePhysicsWorld` (logs, returns False, the
  camera stays in free flight); `scenegraph/x3drigidbody.py` (`RigidBodyCollection` and
  `CollisionSensor` log once and stay still); `debugdraw.PhysicsDebugDraw` (raises).
  `nav.navmesh.from_world` reads an omi world's arrays and needs one to be handed it.
- `show_proxies` draws on either engine: `debugdraw.ProxyOverlay` places a unit box or sphere
  wireframe per box and sphere body from the service's shapes and `physics.poses`.
- `tests/unit/test_physics_without_omi.py` runs child interpreters in which importing
  omi_physics raises: the default engine, the `EngineUnavailable` message, a world with a
  floor, a crate, a walking character and a ray, the 23 engine modules a program on Jolt
  imports, and the isolated features naming the extra. The `engines` marker skips an engine
  whose package is absent, naming it; omi_physics is installed in this workspace, so the omi
  engine's tests run here. The tests of omi-world parts skip without omi_physics, with the
  reason: `tests/unit/omi.requires_omi` on tests and modules (the walk mixin, viewpoint
  walking, X3D rigid bodies and Collision outputs, the collision world, a landscape's omi
  shape, baked props on a world, the nav mesh from a world), module `importorskip` where omi
  is the module's reference or subject (`test_physicsplatform`, `test_road_colliders`,
  `test_heightfield_colliders`, `test_prop_colliders`, `test_physics_debugdraw`,
  `test_physics_backend`, `test_safe_bind`, `test_physics_spawn_where_you_are`,
  `test_swim_platform`, the tile collider tests, `test_physics_neutral_types`,
  `test_physics_worker`, `test_x3d_rigid_body`), and `collect_ignore` for the three modules
  that import the omi engine's own modules (`test_physics_runtime`, `test_physics_frame_cost`,
  `test_physics_sweep_steps`). With omi_physics blocked the unit suite passes: 17,129 passed and 972 skipped, and the one failure then (the resting X3D rigid bodies of `test_still_frames`) is marked.
- Golden results. pyjoltphysics' `tests/differential/omi_golden.json` holds omi_physics'
  answers to 55 comparisons, recorded from omi_physics 0.4 with `PYJOLTPHYSICS_RECORD_OMI`:
  `test_scenes.py` (rest heights on three grounds, slides, rebounds, stack, pyramid, stairs,
  sensors, the bullet, the 1,000-box bin, the dumbbell), `test_smoke.py`, `test_characters.py`
  (each scene's whole track: feet and grounded per tick) and `test_p3.py` (pendulum, chain,
  hinge stop, motor, slider and distance, the pair friction grid, averaged friction,
  restitution, filter pairs, gravity zones, the kinematic pose function). The recorded values
  are the ones in the tables of "P1b", "P2" and "P3 as built". `engines.reference` returns the
  recorded answer and, where omi_physics is installed, checks it against a live run (0.1% or
  0.1 mm; trigger ticks and pair sets exactly); `test_reference.py` tests that. With
  omi_physics blocked 57 differential tests pass; only the vehicle scenarios (P6a) still run
  omi live and are not collected without it.
- marble-demo imports no omi_physics (one comment names it). glisteel depends on omi_physics
  itself and names `engine='omi'` in `world.physics_definition`.

| Suite (no engine setting) | omi_physics installed | omi_physics blocked |
|---|---|---|
| openglcontext `tests/unit -m "not serial"` | 18,574 passed, 56 skipped | 17,129 passed, 972 skipped (before the last mark) |
| openglcontext `tests/unit -m serial` | 29 passed | |
| openglcontext `tests/test_all_scripts.py -k physics` | 20 passed | |
| openglcontext script tests of characters, physics, walking, terrain, X3D | 37 passed, 1 skipped after `character_camera`'s baseline was re-blessed for Jolt (the fox stood 28% of pixels away; the capture is the same on every run); reference-images 514a14c | |
| hill-runner | 652 passed, 1 skipped (no VP9 encoder) | 651 passed, 1 failed: `test_spill`'s coin height, which missed one scatter seed in five; hill-runner 0816176 asserts the rise for every seed |
| twig-bb | 2,407 passed, 1 skipped | 2,407 passed, 1 skipped |
| marble-demo | 941 passed, 6 xfailed (the game's own design notes) | same |
| marble-editor | 165 passed | 165 passed |
| glisteel | 1,670 passed, 1 xfailed | needs omi_physics (its car) |
| openglcontext-forest | 86 passed | 86 passed |
| pyjoltphysics `tests/differential` | 67 passed (with the vehicle scenarios) | 57 passed |
| verify-everything (`verify-logs/verify-2026-10-31-054918.log`) | 24 projects; 23 green, openglcontext 19,611 passed and 1 failed (`character_camera`'s baseline, re-blessed above), serial 29 passed; the script suite then 189 passed, 16 skipped | |

Static gates (`tools/preflight.py openglcontext pyjoltphysics --only lint --only oglc-check
--only typecheck`): all six pass. The typecheck against `.preflight-venv` found 20 errors in
`joltengine.py` and `x3djolt.py` from P4 (ndarrays where pyjoltphysics declares
`Sequence[float]`, unguarded `Snapshot | None`), fixed with `joltengine._vec3`; pyjoltphysics'
lint read another agent's `.claude/worktrees/`, now in its `.gitignore` (715e893).

What blocks deleting the omi engine, and what the deletion then is:

1. glisteel's car (`glisteel/omi_vehicle.py`, `car.py`) is omi's `RaycastVehicle`: P6. Done in P6b.
2. `PhysicsWalkMixin` (every `Context`) walks an omi world of its own: `buildPhysicsWorld`
   returns `collision_world_from_scene`, `spawnAvatar` scores spots with the omi controller's
   `_push_out`, `watchCollisionGroups` listens to the omi world's contacts for X3D Collision
   groups, and `GravityZones` writes the omi world's gravity volumes. Moving it onto the
   service is `TerrainWalkMixin`'s pattern (a service `Character` and
   `PhysicsViewPlatform.over`) plus three neutral pieces: a spawn clearance test by
   `physics.overlap` of the capsule, X3D Collision groups' `collideTime` from the character's
   touch handlers, and the zone gravity the service already places. Not started in P5 (time).
3. X3D RigidBodyPhysics: `x3drigid.py` builds shapes as omi `model.Shape`, contact rules as
   `model.ContactParameters`, a body's default inertia with `omi_physics.massprops.
   inertia_diagonal`, bounds with `body.world_aabb`, and finds `CollisionSensor` touches with
   omi's narrow phase (`collide`); `x3djolt.JoltRigidSystem` subclasses `RigidSystem` and
   converts those shapes. Before omi goes: shapes as `Proxy` (with a `Proxy` bounds and
   inertia), the contact rule as the engine's own record, the module's omi imports moved into
   the omi `RigidSystem`, and the sensor's touches from a pyjoltphysics world
   (`World.overlap` or contact records).
4. Tests that use omi_physics as their reference (the collider modules above that ray-cast
   an omi world or drive omi's `RaycastVehicle` over the colliders) are rewritten onto the
   service's queries on Jolt, or their omi answers recorded as pyjoltphysics' are.
5. pyjoltphysics' vehicle scenarios (`test_vehicles.py`, `vehicles.py`) compare live with
   omi's `RaycastVehicle`; their answers are recorded the way the others' are.

The deletion, once 1 to 5 are done, removes: `physics/omiengine.py`, `omi_adapter.py`,
`runtime.py`, `worker.py`, `replica.py`, `queries.py`, `x3drigid.py`'s omi `RigidSystem` (the
shape building moves to `Proxy`), `debugdraw.PhysicsDebugDraw`, `nav.navmesh.from_world`, `gltf_world.collision_world_from_scene`
and `collision_groups`, `props.PropColliders`, `loaders/tiles3d/physics_colliders.py`,
`zones.gravity_volumes` and `GravityZones`, `PhysicsViewPlatform.__init__`'s world path,
`engine.require_omi`, `OMI_EXTRA` and the `omi-physics` extra, `'omi'` from `settings.ENGINES` and
`PhysicsDefinition.backend` with `BACKENDS` and `default_backend`, the stand-in machinery in
`service.py` and `character.py` (`_replica`, `_character_replica`, `_settle_stand_ins`,
`_bring_up*`, `stand_in_proxy`, `Engine.build_replica`, `proxy_bounds`, `push_reach`,
`stand_ins`), `OpenGLContext.testing.physics`'s omi readers (`inspect`, `run`, `slot_of`,
`body_at`), every test marked `engines('omi', ...)` and the `omi` parameter of the others,
`tests/unit/omi.py` with the tests it marks, the guarded modules and `collect_ignore` above,
the omi live check in pyjoltphysics' `engines.reference`, and the docs' "The omi engine
(deprecated)" section.

### P6a as built (2026-10-31): vehicles in pyjoltphysics

pyjoltphysics `develop` dd6f219 to 2a22a25. The library half of P6; the service layer
(P6b) is not started.

Chosen: Jolt's `VehicleConstraint` with its own controllers, and glisteel's tuning mapped onto
them (section 3's second option). A native port of the raycast vehicle as a custom
`VehicleController` was not needed: the mapping reaches every behaviour below within its
tolerance.

- `src/native/vehicles.*`: a `VehicleSystem` on the world thread. A vehicle is a
  `VehicleConstraint` over a dynamic rigid chassis (not a soft body) with a `WheeledVehicleController`,
  `MotorcycleController` or `TrackedVehicleController`, added to the system as a constraint and
  a step listener; Jolt runs the listeners on its job system, each touching only its own
  chassis, so replays do not depend on the job count. Batches: `AddVehicle` (ids from 1 at
  submission, never reused), `RemoveVehicles`, `VehicleInputs` (throttle, steer, brake,
  handbrake, held until changed; `at_tick` as every batch), `SetVehicleSurfaces` (grip and
  rolling per wheel or vehicle) and `SetSurfaceTable` (by material index). Removing a chassis
  removes its vehicle, by `remove_bodies` or with its ragdoll; a second vehicle on a chassis is
  rejected; vehicles are removed before bodies at teardown.
- Before each `Update`, natively per vehicle: the steering lock falls as
  `max_steer / (1 + (v / falloff)^2)` and the angle moves at `steer_rate`; an idle vehicle that
  comes down to `holding_speed` brakes with `holding` until it is driven again (a latch: without
  it the landing bounce lifted the speed over 0.5 m/s and the car rolled away); `drag` against
  the velocity, `downforce` while a wheel is grounded, and rolling resistance from the last
  step's suspension load at each contact. omi's model applies the same three; drag is applied in
  the air as well (omi applies it only through grounded wheels).
- Wheel casts use the chassis's object layer, so groups, masks and the filter table decide what
  a wheel stands on; a `BodyFilter` skips sensors, character proxies and the chassis. Ray,
  sphere and cylinder casts. A wheel's grip is its own surface, else the surface table's entry
  for the material index of the body under it; Jolt's combine function multiplies the tyre
  curves by it, and by `sqrt(curve * body friction)` only where `body_friction` is set.
- Snapshot: per vehicle id, chassis, kind, rpm, gear, forward speed, steer angle, inputs and the
  tick's heaviest blow (closing speed, impulse, uid); per wheel the centre and orientation
  (a model with axle X and up Y to the world), suspension length and compression, steer, angle,
  spin, load (N), longitudinal and lateral slip, contact, ground uid, material index, mesh
  triangle number, grip, contact point and normal.
- Blows (omi's `impact_on`): after the events are folded, the largest `approach` among the
  tick's contact `BEGIN` and `PERSIST` records naming a chassis. At `impact_speed` or more it is
  also a record of kind `VEHICLE` (5), phase `IMPACT` (11), or `CRASH` (12) at `crash_speed`.
- Quiet lockstep ticks are off in a world with a vehicle: an asleep vehicle's engine rpm still
  decays each tick, so counted ticks would not match stepped ones bitwise. A parked vehicle
  falls asleep: the chassis drag, downforce and rolling resistance never wake it.
- Python: `pyjoltphysics.vehicles`: `VehicleSettings` (with `WheelSettings`, `Engine`,
  `Transmission`, `Differential`, `AntiRollBar`, `VehicleTrack`, `Lean`, `VehicleKind`,
  `WheelCast`), plain data in SI units with `as_dict`/`from_dict` for files and services;
  `VehicleSettings.from_raycast(tuning, wheels, mass, gravity)`, the documented mapping of
  omi's `VehicleTuning` and `WheelSpec` (duck-typed, no omi import); `Vehicle`, `VehicleRows`,
  `WheelRows`; `World.add_vehicle`, `remove_vehicles`, `vehicle_inputs`,
  `set_vehicle_surfaces`, `set_surface_table`; `testing.vehicle_digest`.

The mapping (`from_raycast`), as glisteel's car uses it:

| omi | Jolt |
|---|---|
| `suspension_stiffness` s (car weights per metre) | `stiffness = s m g` N/m, `ESpringMode::StiffnessAndDamping` |
| `suspension_damping` z (fraction of critical) | `damping = z 2 sqrt(stiffness m / wheels)` N s/m |
| `suspension_travel` | `suspension_min` 0, `suspension_max` travel, no preload |
| `engine_force` F, `base_speed` vb | one gear of ratio 1, differential ratio 1, `max_torque = F r`, torque curve flat to vb and `vb / v` above (constant power), `max_rpm` at 3 times the speed power meets drag (232 m/s for glisteel), `min_rpm` 0, clutch strength 5000, engine inertia 0.05 |
| `reverse_fraction` | reverse gear ratio `-reverse_fraction` |
| equal force to each driven wheel | open differentials (limited slip inf), one per driven axle |
| `brake_force` B | `brake_torque = B / braked wheels * r`; the unsteered braked wheels take as much again as a handbrake |
| `grip` 1.9, `Surface.grip` | wheel `grip` multiplies tyre curves saturating at 1 from slip ratio 0.05 and slip angle 0.1 degrees; the surface multiplies again |
| `maximum_steer`, `steer_falloff_speed`, `steer_speed` | `max_steer`, the same falloff, `steer_rate = steer_speed * maximum_steer` |
| `drag`, `downforce`, `rolling_resistance`, `Surface.rolling` | the same, natively each tick |
| `holding` H N | brake input `H / B` (0.375) from 0.5 m/s, latched |
| `ground_recovery`, `recovery_speed` | none: Jolt casts from the mount; its suspension hard stop at `suspension_min` holds a bottomed wheel |

Differential suite (`tests/differential/test_vehicles.py`, glisteel's `CarSpec` on both engines
at 120 Hz). Tolerances are what glisteel's handling tests read: its feel tests bound lateral g,
heading change and line keeping, its power tests speed bands, its settle tests ride height.

| Scenario | omi | Jolt | Tolerance |
|---|---|---|---|
| Standing: ride height | 0.5604 m | 0.5604 m | 1 mm |
| Launch, speed after 2 / 4 / 8 s of throttle | 30.2 / 45.8 / 61.0 m/s | 28.3 / 44.1 / 59.6 m/s | 12% |
| Launch: off the line after 8 s (300 m) | 0.00 m | 0.03 m | 0.5 m |
| Braking from 39 m/s (omi) / 37 m/s (Jolt): distance over v^2 | 0.0362 s2/m | 0.0372 s2/m | 8% |
| Cornering, steer 0.5 at 15 m/s: lateral g, yaw rate | 0.720 g, 0.464 rad/s | 0.728 g, 0.490 rad/s | 6%, 10% |
| steer 0.3 at 27 m/s | 0.546 g, 0.190 | 0.550 g, 0.203 | 6%, 10% |
| steer 1.0 at 27 m/s | 1.837 g, 0.648 | 1.860 g, 0.692 | 6%, 10% |
| Jump off a 15 degree ramp: apex, flight, landing distance | 4.31 m, 1.52 s, 62.3 m | 4.31 m, 1.38 s, 59.2 m | 0.15 m, 12%, 8% |
| Wall at 40 m: impact, against the speed before | 32.4 at 32.2 m/s | 31.0 at 30.9 m/s | 5% of own speed; 8% between |
| 10 degree bank, standing: creep in 3 s | 0.21 m | 0.17 m | 0.25 m |
| 10 degree bank, driven 6 s: speed, off line, heading | 40.3 m/s, 0.51 m, 0.002 | 38.3 m/s, 0.04 m, 0.005 | 8%; 0.6 m; 0.01 rad |
| Bumps (4 cm, 3 m): vertical speed rms, speed, off line | 0.120 m/s, 31.7 m/s, 0.77 m | 0.126, 29.7, 1.56 m | 15%, 10%, 2 m |

Divergences, with numbers and what would bridge them:

- Launch. Off the line both are grip-limited (20 kN asked of about 19 kN of rear grip once the
  weight has moved back); Jolt reaches 28.3 m/s at 2 s against omi's 30.2 (6%), and the gap
  holds at about 1.5 m/s after. Jolt's force is at its friction budget (0.97 of it measured), but
  the driven wheels spin up to 30 times the ground speed in the first 0.1 s and stay over it to
  15 m/s, and the engine's constant-power curve is read at the wheel speed, so the torque falls
  away early. omi has no wheel speed and reads the curve at the chassis's speed. Clutch strength
  mattered most: at 200 the clutch slipped and the 2 s speed was 25.6 m/s. A traction control
  easing the throttle while a driven wheel slipped was tried and dropped: the engine and clutch
  keep the wheels spinning after the throttle falls, so it held the car to 10 m/s at 2 s.
  `engine_force` about 6% higher in the mapping, or a knee in the torque curve 6% further out,
  would close the gap; neither is applied, so the mapping stays the stated one.
- Bank and crown. The slip-curve tyre needs a slip angle to hold the slope's sideways pull. With
  the lateral curve full at 2 degrees a car driven straight on a 10 degree bank drifted 9.5 m
  downhill in 200 m, at 0.5 degrees 2.8 m, at 0.25 degrees 1.2 m; at 0.1 degrees it holds within
  0.04 m (omi 0.5 m). The yaw rate at 1.7 m/s and full lock varies by 0.020 to 0.022 rad/s at
  every one of those peaks, so the stiff curve adds no jitter at walking speed.
- Speed-dependent numbers (braking, cornering radius, jump distance) follow from the launch
  deficit: per-speed measures (distance over v^2, lateral g) agree within 3%. Yaw rates run 5 to
  7% above omi's at the same steer: Jolt's car is 5% slower there, and the lock eases off with
  speed.
- The landing blow: the heaviest contact on Jolt's chassis over the jump was 8.8 m/s against
  omi's 3.6; both land upright on four wheels.
- `ground_recovery` (omi casts from 1 m above the hub to find ground that rose through a wheel)
  has no counterpart; a wheel buried in streamed ground loses contact until the chassis rises.
  A custom `VehicleCollisionTester` casting from above the mount would give it.
- Top speed: 71.5 m/s after 20 s on Jolt and still rising 0.3 m/s a second (257 km/h). glisteel's
  power tests read the tuning rather than a drive (279 km/h from power and drag alone), so they
  hold on either engine.

Motorcycle and tracked smoke tests (`tests/test_vehicles.py`): a 240 kg bike on two wheels with
the lean controller rides at over 5 m/s within 18 degrees of upright and leans into a steer 0.5
turn (0.2 rad of heading in 1.5 s, leaning less than 53 degrees); a 4 t tank on ten
wheels in two tracks settles with every wheel down, drives at over 1 m/s, turns 0.2 rad in 1 s at
full steer and stays within 12 degrees of level. Tracked steering slows the inside track and runs
it backwards past half a turn.

Determinism: ten cars and ten crates, 60 inputs at random ticks through `at_tick`, 600 ticks in
lockstep: the `vehicle_digest` of 40 snapshots is identical on 1 and 8 job threads and on a
second 1-thread run, GIL and free-threaded builds.

Tests: GIL build (3.14, the workspace venv) 467 passed, 2 skipped, and the `serial` pass 1 passed;
free-threaded 3.14t 434 passed, 2 skipped (no omi_physics there, NEON); ASan and UBSan
(`tools/asan.sh`) 387 passed, 3 skipped on the full suite before the free-running replay test
was added, then 43 passed, 1 skipped on `-k vehicle` with it; no sanitizer report. `tests/test_vehicles.py` was
seen failing at collection against the develop module before the implementation (no vehicle
API); within it the holding test failed before the latch, the top-speed test before its floor
was long enough, and the tracked turn before its duration was short enough to stay inside one
revolution. ruff, ruff format, mypy (strict, 47 files) and oglc-check clean; `_native.pyi`
regenerated.

Benchmarks (the machine carried other users' processes, load 11 to 31). `benchmarks/vehicles.py`:
cars on a 256 x 256 height field at 120 Hz, throttle 0.6, steer changed every 60 ticks; ms a tick
from the world's own timings.

| | 1 job thread | 8 job threads |
|---|---|---|
| 10 cars, `Update` / whole tick | 0.048 / 0.054 ms | 0.061 / 0.068 ms (target 0.3 ms) |
| 100 cars | 0.79 / 0.85 ms | 0.24 / 0.33 ms |

The existing benchmarks, develop before P6a against P6a, both built with the same flags, four
interleaved runs each, ms a frame (lowest, median):

| | before | after |
|---|---|---|
| boxes5000 (1,000 active), 1 thread | 3.22, 3.65 | 3.22, 3.86 |
| same, 8 threads | 1.31, 1.74 | 1.33, 1.79 |
| 300 characters on a height field, 60 Hz, 1 thread | 1.49, 1.57 | 1.44, 1.60 |
| same, 8 threads | 0.59, 0.72 | 0.60, 0.91 |

The lowest of each pair agree within 3%; the medians spread with the load. A world without
vehicles pays an empty loop before and after each step and a resize of the snapshot's vehicle
arrays to 0 at each publish.

What P6b's service layer needs:

1. `engine.py`: a `Physics.add_vehicle(chassis, settings)` returning a handle over `Vehicle`,
   inputs sent once a frame with `vehicle_inputs` (or per tick with `at_tick` for scripted
   drivers), wheel poses from `Snapshot.vehicles.wheels` for drawing, and interpolation between
   the last two snapshots as for bodies.
2. glisteel's seam (`omi_vehicle.ServiceVehicle`) replaced: `control()` becomes `set_input`;
   `update(dt)` goes (the world thread applies the forces); `wheels[i].compression`,
   `steer_angle`, `grounded` and `slip` read `WheelRows`; `struck(among, above)` reads
   `impact()` or the `VEHICLE` records and filters by uid; `place()` is `set_transforms` plus
   zero velocities (and a fresh input to clear the latch); `Surface` per wheel is
   `set_surface`, or the surface table keyed by the road and verge materials.
3. glisteel's tests that drive omi directly (`test_feel.py`'s `TestItSlidesRatherThanRolls`
   through `standalone_physics`) need the Jolt path as well. Car feel to re-verify in glisteel's
   own suites on Jolt: the 7% launch deficit (power tests),
   the line keeping on the crown (0.5 m allowed), the steering falloff (shared code), and the
   settle budget (`test_settling.py`; not measured on Jolt).
4. glisteel steps inline and reads the vehicle between steps; on Jolt, forces are the world
   thread's, so a car's update is one input batch a frame and the race reads the snapshot.
5. Not built: `ground_recovery`; per-wheel `braked` beyond brake torque 0; anti-roll bars are
   exposed but glisteel's car has none; vehicle state beyond Jolt's (steer angle, holding latch)
   is not in `save_state`.
6. glTF: `VehicleSettings.as_dict` is the shape for an extension or extras on the chassis node;
   OMI has no vehicle extension yet.

### P6b as built (2026-10-31): vehicles through the service, glisteel off omi

Branch `p6b-vehicles` on `openglcontext`; `pyjoltphysics` 44da300; glisteel branch
`p6b-jolt-car`.

- `physics/vehicles.py`: the engine's own types. `VehicleSettings` (with `Wheel`,
  `VehicleEngine`, `Transmission`, `Differential`, `AntiRollBar`, `Track`, `Lean`) has
  pyjoltphysics' field names, `kind` and `cast` as strings, `as_dict`/`from_dict`,
  `wheelbase`, `steer_lock`; a test holds the field sets equal. `CarTuning`, `CarWheel`,
  `car_wheels` and `Surface` state a car in the raycast vocabulary;
  `VehicleSettings.from_tuning` maps it through pyjoltphysics' `from_raycast`.
  `VehicleState`, `WheelState` and `Impact` are the reads.
- `Physics.add_vehicle(chassis, settings)` returns a `Vehicle`: `set_input(throttle, steer,
  brake, handbrake)` (clamped; reverse by negative throttle), `set_surface` (sent only when
  it changes), `place(position, heading)`, `state()`, `forward_speed`, `speed`, `rpm`,
  `gear`, `steer_angle`, `wheels`, `grounded`, `impact(among, above)`,
  `addEventHandler('impact' | 'crash')`, `remove()`. Removing the chassis removes the
  vehicle; `Physics.vehicles` lists them. The events are `PhysicsEvent(kind='vehicle',
  phase='impact' | 'crash')` naming the chassis and the body struck, filtered by `other=`
  and `above=` as contacts are.
- `physics/joltvehicles.py` (`JoltVehicles`, one per `JoltEngine`): vehicle ids, the input
  batch, states built once a vehicle a published tick, VEHICLE records converted. The
  chassis is flagged REPORT, so a car held against a wall reports its persist blows.
- Input latency. Chosen: the characters' at-tick delivery. Every vehicle's inputs given
  in a frame go to the world as one `vehicle_inputs` batch before the frame's lockstep
  ticks (they drive its first tick), once a frame for a free-running world, and after the
  `before-step` handlers of each tick, so inputs given there drive that tick. glisteel
  gives its inputs in `before-step`, as it did on omi.
- The omi engine: no vehicles. `Engine.add_vehicle` raises NotImplementedError naming the
  jolt engine (as `save_state` does); the omi engine is to be deleted, and its raycast
  vehicle needed a per-step Python update the service does not have.
- pyjoltphysics 44da300: `from_raycast`'s tyre curves are friction 1 from no slip
  (longitudinal and lateral). A curve rising from 0 gave a tyre no grip while it was not
  slipping: on a crowned road mesh the car rocked in yaw by up to 0.028 rad/s from tick
  to tick (glisteel's cockpit camera test, 0.026 rad/s against 0.02); now under 0.002.
  The launch is within 4% of omi's raycast car at 2, 4 and 8 s (6% before), so
  `engine_force` is unchanged.
- The neutral-types guard covers pyjoltphysics as well as omi_physics, and `Vehicle`,
  the settings and the states.

glisteel:

- `glisteel/vehicle.py` (`CarVehicle`) replaces `omi_vehicle.py`: the car's tuning on the
  engine's vehicle, answering what the race asks (pose, speeds, wheels with
  compression, steer angle, grounded and slip, `struck` from `Vehicle.impact`,
  `wheelbase`, `turning_radius`, `surface`). `Car.update` is gone: the world thread
  applies the forces.
- `CarSpec.lateral_friction` is 0.9 at every slip angle. At full grip, full lock from
  17.5 to 22.5 m/s rolled the car (`TestItSlidesRatherThanRolls`); at 0.9 it rolls at
  most 1 degree from 12.5 to 60 m/s.
- `physics_definition` names no engine; the pin test became
  `test_the_service_is_the_engine_s_default`. `omi_physics` is out of glisteel's
  dependencies and `packaging/requirements-stack.txt`.
- Tests ported: the standalone loops call `Physics.frame` (reads are the published
  snapshot, which `step` does not publish); `test_feel.py`'s roll-over tests run on
  the Jolt service unchanged; the omi-world reads became `physics.counts`,
  `physics.gravity`, `Body.velocity`, `testing.physics.shape_kind` and contact handlers.
- Tolerances moved, each with its reason in the test: a mired car on the brake on rough
  ground stops in 2.7 s from 37.5 m/s (bound 3 s lowered to 2 s; brake and rolling
  resistance both scale with a load downforce raises 73%); a placed car's position is
  read two ticks on (atol 0.01 m). The put-back test removes the car hit first: the car is
  put back on its roof, and Jolt's wheels stand on it.
- glisteel suite, no engine setting: 1,670 passed, 1 xfailed.

Not done, for a later pass:

- glisteel's tyre-scrub band (0.25 to 3.5 m/s of slip) was measured on omi; on Jolt full
  lock from 30 m/s slips 0.15 m/s, under the band.
- `Body.set_velocity` is not read back before the world applies it (positions are).
- Jolt's tyres limit braking and cornering friction separately (its default tyre impulse
  callback); omi's shared one budget. A friction circle is a pyjoltphysics callback.
- Wheel poses are the newest tick's, not interpolated between ticks; `save_state` leaves
  out the steer angle and holding latch (P6a).

The omi engine's deletion list (P5 as built) loses its first blocker: glisteel imports no
omi_physics. What still blocks it is items 2 to 5 there (`PhysicsWalkMixin`, X3D
RigidBodyPhysics, the omi-reference collider tests, pyjoltphysics' live vehicle
scenarios); with them done the deletion is the list there.

### P6c as built (2026-10-31): ragdolls and soft bodies in pyjoltphysics

pyjoltphysics `develop` fbe3d97 to 7673332. The library half of the ragdoll and soft-body part of P6;
the engine layer (P6d) is not started. Soft bodies are Jolt's own soft-body simulation only
(maintainer's decision: no external cloth, hair or fluid library).

Ragdolls (`src/native/ragdolls.*`, `pyjoltphysics.ragdolls`):

- Jolt's `Ragdoll` from a `RagdollSettings`: bones parents first, each with a rest translation and
  rotation in its parent joint's frame (the layout of `OpenGLContext.character.Rig` poses:
  translation (N, 3), rotation (N, 4) xyzw), a shape placed in the joint's frame, a mass, a
  swing-twist limit (twist about the bone, a swing cone of two half angles), a motor strength (N m)
  and joint friction. A bone's body frame is its joint's frame, so the snapshot's bone poses are
  the joint matrices skinning reads. `from_skeleton` builds capsule bones from a skeleton (joint to
  first child; mass shared by volume); `humanoid()` is an 11-bone figure.
- Each bone is a body row with a uid assigned at submission, so impulses (now also at a world
  point: `add_impulses(points=)`, `Ragdoll.hit(bone, impulse, point)`), velocities, events,
  queries and user joints name bones as bodies. `remove_bodies` refuses a bone;
  `remove_ragdolls` removes the bodies, ending their pairs with `REMOVED`.
- Modes: kinematic (bones kinematic, `MoveKinematic` to the target at the end of each tick),
  powered (swing and twist motors per joint towards the target rotation relative to the parent,
  torque limited per bone; the root bone pulled to its target by a spring of `root_frequency`
  carrying the whole ragdoll's mass and weight, limited by `root_force` and `root_torque`), limp
  (motors off). `set_mode(mode, blend)`: into powered or limp the motors' strength ramps to 1 or 0
  over the blend; leaving kinematic keeps velocities at full strength (so kinematic to limp with a
  blend is a death that crumples over the blend); into kinematic the targets move from the bones'
  current poses to the target over the blend (a get-up).
- The pose target is a held pose (`set_pose`, `place`) or a clip (`play(times, rotations,
  translations, loop)`) the world thread evaluates at the end of every tick (slerp and lerp), so
  no Python runs in the tick. A ragdoll drives its bones only while its target moves; at a still
  target its bones sleep and a world of still ragdolls idles and counts quiet ticks.
- Collisions: bone pairs that do not collide are parent and child and those whose shapes overlap
  in the rest pose (Jolt's `DisableParentChildCollisions` test), or every pair with
  `self_collision=False`, kept apart by the world's `JointPairFilter`; groups, masks and the
  filter table decide the rest. `RagdollSettings::Stabilize` is not called: the masses stay as
  given.
- Snapshot `ragdolls` (`RagdollRows`): id, mode, strength, self collision, first bone, bone count;
  per bone uid, float64 position and orientation, one slice a ragdoll.

Soft bodies (`src/native/softbodies.*`, `pyjoltphysics.softbodies`):

- `SoftBodySettings` is vertices with masses (0: fixed), faces, explicit edges with compliances,
  tetrahedra, and Jolt's material: edge, shear and bend compliance (bend distance or dihedral),
  volume compliance, pressure, long-range attachments (Euclidean or geodesic, with a stretch
  allowance), iterations, damping, maximum velocity, friction, restitution, gravity factor,
  vertex radius, sleeping, double-sided faces, and a body's group, mask, filter, material and
  flags. Bend constraints default to distance constraints of compliance 0.01 and iterations to
  `iterations_for(shortest edge)`; without them a fine cloth tears apart in Jolt at 60 Hz
  (benchmarks, below). Builders: `cloth`, `rope` (edges along a polyline; a finite `bend_compliance` adds bend edges across every second
  vertex, and the default `math.inf` adds none),
  `ball` (an icosphere with pressure), `from_mesh`. The shared settings are built and checked on
  the calling thread at submission.
- A soft body is a body row (uid at submission; `remove_bodies`, `activate`, sleep); it meets rigid
  bodies by the world's filters both ways (cloth carries a dropped box).
- Pins: a pinned vertex has no mass and is given each tick the velocity that brings it to its
  target by the end of the step: a world point, or a point in another body's frame at that
  body's end-of-step pose. Pins change at run time (`SoftBody.pin`, `unpin`); a pin does not pull
  on its body.
- Wind: a force per body applied with `AddForce` before every step, which Jolt shares among the
  free vertices.
- Snapshot `soft_bodies` (`SoftBodyRows`): uid, float64 origin (the centre of mass, also the body
  row's position), first vertex, vertex count, version; float32 vertex positions relative to the
  origin and area-weighted normals. After a tick the soft bodies Jolt moved copy their vertices
  and normals into a per-body cache stamped with the tick; a snapshot buffer copies a body only
  when its stamp differs from the one it holds, and rewrites every row when bodies were added or
  removed. An asleep cloth costs nothing to publish; a renderer uploads a body when `version`
  changes, straight from the view.
- Ropes are edges. Jolt 5.6's Cosserat rods (`RodStretchShear`, `RodBendTwist`) give each segment
  an orientation, for geometry hung on a rod (leaves, a chain's links); not exposed yet.

Tests. omi_physics has no ragdoll, cloth or soft body, so there is no differential scenario; the
tests hold the behaviour to analytic expectations:

| Test | Expectation |
|---|---|
| Limp humanoid tipped onto the floor | at rest (every bone under 0.05 m/s) after 6 s, above the floor, every joint's twist within its limits and swing within its bend plus its larger cone half angle, 0.05 rad slack |
| Kinematic humanoid playing a 3-key looping clip, placed off the origin | every joint within 1 mm of `forward_kinematics` of the clip at the snapshot's time, five times over two loops |
| Kinematic held pose and placement | joints within 0.1 mm, orientations within 1e-5 |
| Powered humanoid struck on an arm and above the head (root spring 4000 N, 1500 N m) | deviation from the pose over 0.15 rad after 0.1 s, under 0.1 rad after 2 s; the limp one struck the same stays over 0.3 rad; the root stays over 0.9 m |
| Blends | kinematic to limp falls at once at strength 0; powered to limp over 0.5 s reads strength 0.3 to 0.7 at 0.25 s and 0 after; kinematic over 1 s from the lying pose is away from both at 0.5 s and within 1 mm of the target after |
| Strength per bone | an arm of strength 0 swings free after a blow; every other joint holds within 0.1 rad |
| Groups and masks | a ragdoll masked off the floor's group falls through it; the other rests on it |
| Still ragdolls | a powered and a kinematic ragdoll at still targets sleep in 4 s and the world counts quiet ticks; a new head pose wakes both and is reached within 0.05 rad |
| Cloth 1 m, 11 x 11, pinned at two corners | pins within 0.1 mm; the free edge more than 0.8 m below them; free corners within 1.1 m of their pins; unit normals |
| Cloth 2 m, 21 x 21, dropped on a 0.5 m sphere, vertex radius 1 cm | no vertex closer to the centre than 0.5 m less the vertex radius; the centre vertex at the top of the sphere plus the radius, within 3 cm; the edges below 0.3 m |
| Cloths of 32, 40, 60 and 80 vertices a side dropped on a sphere at 60 Hz, default settings | within 3 m of the sphere and every face edge under twice its rest length after 1 s |
| Pressure ball | its bottom reaches the floor, its centre rises 0.2 m after, it is off the floor 0.2 to 0.5 s after, volume above 60% of rest |
| Rope 1 m, 20 segments, pinned at one end, released level | swings below 0.9 m under the pin, through to the far side and back; length within 5% |
| Cloth pinned at four corners | holds a dropped 0.3 m box between 0.3 and 1.0 m |
| Wind 2 N across a hanging cloth | its mean displacement 0.1 m more than a still one's |
| Pin to a kinematic body on a track | the pinned vertex within 1 mm of the body; unpinned, it falls |
| Snapshot versions | a reader's held snapshot keeps its vertices; an asleep cloth's version stops; wind wakes it and the version moves |

Determinism: `tests/test_p6c_lockstep.py`: three ragdolls (limp, powered, kinematic with a clip),
a cloth on a sphere, a pinned rope and a pressure ball; 30 hits, wind changes and mode blends at
random wall-clock moments in a free-running 8-thread world at 240 Hz for 600 ticks, replayed with
`at_tick` in lockstep: the ragdoll and soft-body digests of every tick are identical on 1 and 8 job
threads, two seeds, GIL and free-threaded builds.

Builds, on the final commit: GIL (3.14.7, the workspace's interpreter with omi_physics on the
path) 507 passed, 2 skipped, and the `serial` pass 1 passed; free-threaded 3.14t 497 passed, 2
skipped (no omi_physics there: the vehicle differential scenarios are not collected), `serial`
1 passed; ASan and UBSan (`tools/asan.sh`) 497 passed, 2 skipped, no sanitizer report over that
suite. Both test
files were seen failing at collection against develop before the implementation; within them
the still-ragdoll, bend, point-impulse and fine-cloth tests were each seen failing before their
change. ruff, ruff format, mypy (strict, 53 files) and oglc-check clean; `_native.pyi`
regenerated.

Benchmarks (`benchmarks/ragdolls_cloth.py`, 60 Hz, 3 s after 0.5 s; ten powered ragdolls playing a
looping clip, ten limp ones falling onto boxes, five 2 m cloths of 32 x 32 vertices draped on
spheres under wind; the world's own timings, ms a tick, four runs, load average 3 to 4 from other users):

| | 1 job thread | 8 job threads (target 1.5 ms a 60 Hz frame) |
|---|---|---|
| 20 ragdolls and 5 cloths of 1,024 vertices, whole tick (lowest, median) | 1.36, 1.36 | 0.42, 0.46 |
| 20 ragdolls alone | 0.29 | 0.14 |
| 5 cloths alone | 1.13 | 0.23 |

The first measurement read 0.92 to 1.27 ms at 8 threads, and the cloths' cost rose with the number
of bodies anywhere in the world (0.16 ms alone, 0.31 ms beside 110 static boxes 1 km away). The
cause was the cloths blowing apart: a 2 m cloth of 32 to 80 vertices a side, compliance 0 edges and
no bend constraints, dropped on a sphere at 60 Hz, stretched its edges to 2.6 times their length
within three ticks of meeting the sphere and reached 1e11 m by 3 s; its bounds then took in every
body. A 60-line program against Jolt alone (a static sphere, the cloth, `PhysicsSystem::Update`; single
precision with asserts and the wheel's double-precision deterministic build alike) reproduces it with no
pyjoltphysics code in the loop: no assert fires, edge compliance up to 1e-3 and dihedral bend
constraints do not help, distance bend constraints of any compliance up to 0.1 do, and finer
cloths also need more iterations (40 a side stable at 5, 60 at 10, 80 at 20). pyjoltphysics now
defaults `bend_compliance` to 0.01 and `iterations` to `iterations_for(shortest edge)`
(`5 * (0.05 m / edge)^2`, at least 5); the cost no longer depends on the other bodies. Reporting
it upstream to Jolt is a step for the maintainer.

The existing benchmarks, develop before P6c against P6c, four interleaved runs each, ms a frame
(`boxes5000`, `characters.py --case chars300_hf` at 60 Hz) or a tick (`vehicles.py`, ten cars),
(lowest, median):

| | before | after |
|---|---|---|
| boxes5000 (1,000 active), 1 thread | 3.05, 3.32 | 3.09, 3.16 |
| same, 8 threads | 1.58, 1.99 | 1.44, 1.97 |
| 300 characters on a height field, 1 thread | 1.43, 1.46 | 1.43, 1.43 |
| same, 8 threads | 0.79, 1.02 | 0.68, 0.73 |
| 10 cars, 1 thread | 0.039, 0.044 | 0.040, 0.047 |
| same, 8 threads | 0.057, 0.061 | 0.051, 0.060 |

Within noise. A world without ragdolls or soft bodies pays two empty loops a tick and the
resize of their snapshot arrays to 0 at each publish.

Limits, as built:

- No differential: omi_physics has neither feature.
- A powered ragdoll stays up by its root spring; nothing computes balance from the feet.
- Soft bodies do not collide with each other (Jolt), and their contacts with rigid bodies make no
  event records. A pin moves its vertex and does not pull on its body.
- `save_state` holds bodies, constraints and soft-body vertices; ragdoll modes, strengths, pose
  targets and clips, and soft-body pins and wind, are the world thread's and are not saved.
- A free-running world keeps ticking while any ragdoll's target moves (a clip plays).

What P6d (the engine layer) needs:

1. `engine.py` and `Physics`: `add_ragdoll(character, settings=None)` returning a handle over
   `Ragdoll` (mode, blend, hit at a world point from a ray's hit, strength); bone handles as
   `Body` objects for handlers and joints; `add_soft_body(node or mesh, settings, pins)` returning
   a handle over `SoftBody` (pin to a `Body`, unpin, wind); removal with the node.
2. Skeleton to ragdoll builder from a character rig (`OpenGLContext.character.Rig`): choose the
   bones (a humanoid's pelvis, spine, chest, neck, head, upper and lower limbs, hands and feet as
   `hanimnames` names them; fingers, twist and helper joints ride their nearest chosen ancestor at
   their rest offset), radii from the skin (the vertices weighted to each bone, their distance from
   the bone axis), masses from the capsule volumes and a total, limits from `character.hanim`'s
   joint limits where the document has them and `RagdollSettings.humanoid`'s otherwise; the result
   is a `RagdollSettings` via `from_skeleton` plus the bone-to-slot map.
3. Animation to ragdoll: each frame, the mixer's pose for the chosen slots as `set_pose` (one batch),
   or a clip sampled once into `play(times, rotations, translations)` for scripted motion; the
   character's placement as `place`. Hit reaction: `POWERED`, `hit`, then back to the animation.
   Death: `set_mode(LIMP, blend)`. Get up: `set_mode(KINEMATIC, blend)` to the first frame of the
   get-up clip, then the mixer resumes from the ragdoll's pose.
4. Ragdoll to rendering: `RagdollRows.bone_position` and `bone_orientation` for the ragdoll's
   slice, interpolated between the last two snapshots as bodies are, written as world matrices for
   the chosen slots (`Rig.world_matrices` takes over for the riding joints) and fed to the skin's
   joint matrices.
5. Soft bodies to rendering: a mesh node welded by position for the simulation (glTF splits
   vertices at UV seams; keep the render-vertex to particle index map), each frame where
   `version` changed the particles gathered through that map into the vertex buffer with their
   normals, the node placed at `origin`. Pins to scene bodies through `Body` uids; a wind source
   (a zone or a scene node) sets `set_wind` per body.
6. X3D: RigidBodyPhysics and HAnim have no ragdoll or cloth node, so both are engine extension
   nodes (`Ragdoll` over an `HAnimHumanoid`, `Cloth` over a geometry), read and written.
7. Tutorials: a ragdoll (a humanoid struck, falling, getting up) and a cloth (a flag in the wind,
   and a sheet dropped on furniture).

### P5b as built (2026-10-31): walking and X3D rigid bodies off omi_physics

Branch `p5b-walk-x3d` on `openglcontext`, from "PhysicsWalkMixin on the physics service" to
this section, with the X3D rigid body work of branch `p5b-x3drigid` ("physics.massprops: a
proxy's bounds and inertia" to "docs/x3d.rst: where a joint on Jolt turns back off its stop")
rebased onto it. pyjoltphysics is unchanged. Blockers 2 and 3 of "P5 as built" are done;
blocker 1 went with P6b.

Walking (`PhysicsWalkMixin`, every `Context`). The plan's three pieces, taken as recommended:

- The avatar is a `Character` of `context.physics` and the camera a
  `PhysicsViewPlatform.over(character)`, `TerrainWalkMixin`'s pattern, now the base mixin's.
  `buildPhysicsWorld()` puts what the avatar walks on into the service and returns its bounds
  `(lo, hi)` or None (it returned an omi world and the bounds): the default feeds `sg` to the
  scenery tracker (`scenery_changed`), waits up to `physicsCookWait` (30 s) for the cooking,
  places the scene's gravity zones (`zones_changed(scene_zones(sg))`), switches the service on
  and turns `colliders='none'` into `'scene'`. `physicsAvatar()` makes the character (gravity
  `physicsGravity` times the scale, owner-stepped until walking). `gltf_world.scene_bounds`
  is the bounds.
- The frame. A host with a render queue: the movement mode's input runs first in the frame,
  the service steps the framed avatar, the camera goes to its eye after
  (`_walkHook`, `_walkInput`, `_walkCamera`, moved up from `TerrainWalkMixin`); `framed`
  follows walking. A host without one calls `stepPhysics(dt)`, which steps the
  owner-stepped avatar (advancing the world) as before; in a context `stepPhysics()` asks
  for a frame.
- Spawn. A candidate counts where `floors_below` (rays straight down from above the bounds,
  continued below each surface, at most 16) finds a floor no steeper than `maxSlope` whose
  standing capsule, lifted half a step, overlaps nothing (`physics.overlap`) and has 1.25
  standing heights clear above (`HEADROOM`): the lowest such floor, so the ground floor of a
  building. `clearance` counts the four directions where the capsule an arm's length out
  overlaps nothing (its reach now scales with the avatar). Rays meet a closed mesh's underside
  as a floor, with the normal turned to the ray, on both engines; the headroom test tells them
  apart for solids thinner than 1.25 standing heights. Whether an avatar placed at a viewpoint
  flies is `physicsHasFloor()` (a floor within a standing height below its feet), since a Jolt
  character's `grounded` is known only after a tick.
- X3D Collision groups' `collideTime`. A Jolt character's capsule against static bodies makes
  no contact event (measured: no `hit` on either the character or the wall), so the character's
  touch handlers cannot carry it. `x3dcollision.collision_group_bodies` finds the scenery bodies
  inside enabled groups; `CollisionReporter.update` overlaps the capsule, a tenth of its radius
  and 3 cm (`SKIN`; Jolt stops a character 0.02 m short) wider, with them once a step, and sends
  `isActive TRUE` and `collideTime` for a body begun, `isActive FALSE` when a group has no
  touched body left.
- Zone gravity: the service's own (`Physics.zones_changed`, fed by the render pass each frame);
  the mixin's `gravityZones` and `followZoneGravity` are gone.
- `forgetPhysicsWorld()` removes the avatar; the scene viewer calls it on a new scene (it set
  `physicsPlatform = None` and left the omi world to the collector).
- Feel: the same `CharacterCapabilities` (speeds, jump 1.2, step 0.4, stand 1.8, radius 0.3 at
  scale 1; NavigationInfo avatarSize as before), gravity 9.81 times the scale, the same
  `physicsMaxStep` clamp and movement modes. Stepping, sliding and slope limits are the engine's
  character (Jolt's `CharacterVirtual` port on the default engine). The walker now meets the
  service's dynamic bodies and pushes them.

Contract changes the 13 test modules follow: hosts give `physics`; `buildPhysicsWorld` returns
bounds; `_clearance(character, radius)` is `clearance(physics, centre, capabilities, skip)`;
`watchCollisionGroups()` takes no arguments; `CollisionReporter(groups, walker)` is keyed by
`Body` and driven by `update(now)` (`heard(event, now)` is gone); `onPhysicsModeChanged` does
the framing, so an override calls up. `test_physicswalk`, `test_physics_spawn_where_you_are`,
`test_x3d_collision_outputs` and `test_viewpoint_walking` run on both engines with omi_physics
optional; `test_physics_without_omi.py` walks a scene with omi_physics blocked.

X3D RigidBodyPhysics (from the rigid branch's report):

- `x3drigid.py` holds no omi code: shapes are `Proxy` in a `ShapePart`, contact parameters a
  `ContactRule`, `RigidSystem` the base both engines share. `physics/massprops.py` gives a
  `Proxy`'s volume, centroid, inertia and bounds, with differential tests against omi's
  `inertia_diagonal` and `world_aabb` (9 shape cases; since the review follow-ups the capsule's
  inertia is held by a slice-by-slice integration instead, since omi weighs a capsule as its cylinder). The omi engine's rigid system is
  `physics/x3domi.py` (`OmiRigidSystem`, `OmiSensing`); `x3djolt.make_rigid_system` and
  `make_sensing` choose by engine.
- `CollisionSensor` on Jolt (`JoltSensing`): the collidables are bodies in an unstepped
  pyjoltphysics world; each collidable's shape is swept 0.1 mm where it stands
  (`World.sweep`); one `Contact` per touching pair, at the deepest point; two triangle-mesh
  collidables are not tested against each other.
- `stopBounce`: Jolt 5.6 has no restitution on hinge or slider limits. `x3djolt` reverses the
  velocity: a joint about to pass its stop within the next step, or just stopped by it, leaves
  at bounce times its speed, from 0.1 rad/s (m/s), split between the bodies by how hard each
  is to move along the axis (`stopBounce` on hinge and slider, `stop1Bounce` on the
  double-axis hinge). The demo's door returns at 0.99 rad/s from 2.47 (bounce 0.4; it was
  0.12; omi 0.49), turning back at 1.586 rad against a stop at 1.6.
- `minBounceSpeed` is the world's least bounce speed (Jolt holds one per world); the
  collection's `disableLinearSpeed` and `disableTime` set Jolt's sleep speed and time.
- Fixed on the way: a double-axis hinge motor with `maxTorque` 0 held at infinite torque; a
  joint whose body2 is NULL read body2 against body1 with the sign flipped on Jolt;
  `omi_adapter.omi_shape` hung on a compound (its lock is reentrant).
- Kept and not read on Jolt (listed in docs/x3d.rst): iterations, errorCorrection,
  constantForceMix, maxCorrectionSpeed, contactSurfaceThickness, the softness fields, the
  second friction coefficient, frictionDirection, surfaceSpeed, slipFactors,
  stopErrorCorrection, stop1ConstantForceMix, useFiniteRotation, disableAngularSpeed.

| Suite (no engine setting, omi_physics installed) | Result |
|---|---|
| openglcontext `tests/unit -m "not serial"`, `-n 16` | 19,345 passed, 65 skipped, 6 xfailed; 1 failed, `test_pbr_performance::test_cached_is_not_slower` (cached 43.7 ms against 31.9 uncached in a run with the machine's load average near 40; passes alone three times), which compares wall-clock medians and is now `serial` |
| openglcontext `tests/unit -m serial` | 30 passed |
| `tests/test_all_scripts.py -k` physics, walk, terrain, character, x3d, rigid, forest, heightfield, navigation, viewpoint, tiles, collision, view, gltf (worktree on `PYTHONPATH`) | 40 passed, 1 skipped; `x3d_demo` and `x3d_geospatial` reached the 30 s script timeout at load average 41 and pass alone (2 passed, 50 s); neither walks nor holds rigid bodies |
| hill-runner | 652 passed, 1 skipped (no VP9 encoder) |
| twig-bb | 2,407 passed, 1 skipped |
| marble-demo | 941 passed, 6 xfailed |
| marble-editor | 165 passed |
| openglcontext-forest | 86 passed |
| openglcontext `tests/unit`, main checkout after the merge (with P6d) | 19,500 passed, 50 skipped, 6 xfailed; serial 30 passed |
| `verify-everything.py --only openglcontext` (`verify-logs/verify-2026-10-31-133607.log`) | the bulk pass hit its 3,600 s limit at load average 30 to 40 from three other agents' suites; serial 29 passed and 1 failed (`test_x3d_sound_stress`'s mix against the clock); `test_docbuild`'s named-scripts test failed while P6d's tutorials were half merged and passes now. The two `-n 16` runs above stand in for it |

`test_gltf_view_physics_toggle` drives a viewer in a subprocess from `tests/`, which imports
the main checkout, so the worktree run tested the old walk; after the merge its driver had to
run the frame hooks the walker is now stepped in (32de3e58, from the P6d work).

A context walking a 40 m floor from a camera 10 m up (GLFW, hidden window): the avatar falls
and lands with its feet at 0.0 and the camera at 1.6 within 90 frames.

Static gates on every changed file, by hand (`tools/editcheck.py` checks nothing outside
the main checkouts): ruff, oglc-check, mypy against `.preflight-venv`, all clean.

What imports omi_physics in OpenGLContext now (import statements; mentions in docstrings
left out):

| Module | Why | Leaves with |
|---|---|---|
| `physics/omiengine.py`, `omi_adapter.py`, `runtime.py`, `worker.py`, `replica.py`, `queries.py` | the omi engine | the omi engine |
| `physics/x3domi.py` | X3D RigidBodyPhysics on the omi engine (`x3djolt` imports it only for `engine='omi'`) | the omi engine |
| `physics/engine.py` | `require_omi` and `make_engine` probe for it | the omi engine |
| `physics/debugdraw.py` | `PhysicsDebugDraw` over an omi world | the omi engine |
| `physics/gltf_world.py` | `collision_world_from_scene` (no engine caller left: tests only) | the omi engine |
| `physics/props.py` | `PropColliders` over an omi world | the omi engine |
| `loaders/tiles3d/physics_colliders.py` | `TerrainColliders` over an omi world (`tests/tiles_walk.py`, `tests/tiles3d/test_navigation.py`) | the omi engine |
| `move/physicsplatform.py` | `PhysicsViewPlatform(world)`, the omi world path (the same two tile tests) | the omi engine |

With P6b, glisteel imports no omi_physics and names no engine, so no game needs any of these.
The deletion list of "P5 as built" now reads: `physics/omiengine.py`, `omi_adapter.py`,
`runtime.py`, `worker.py`, `replica.py`, `queries.py`, `x3domi.py` (`x3djolt`'s
`engine == 'omi'` branches with it), `debugdraw.PhysicsDebugDraw`, `nav.navmesh.from_world`,
`gltf_world.collision_world_from_scene` and `collision_groups`, `props.PropColliders`,
`loaders/tiles3d/physics_colliders.py`, `zones.gravity_volumes` and `GravityZones`,
`PhysicsViewPlatform.__init__`'s world path, and the rest of that list as written. Blockers
4 (tests with omi as their reference) and 5 (pyjoltphysics' vehicle scenarios against omi live)
remain.

### P6d as built (2026-10-31): ragdolls and soft bodies through the service

openglcontext 74b9a599 to 3474d538 (branch `p6d-ragdoll-cloth`); pyjoltphysics
893e48c and 3321231; pyopengl 070eeda3.

Service and engine:

- `physics.ragdolls`: `RagdollSpec` and `RagdollBone` (capsule bones by radius, length and axis;
  twist, swing, bend, strength, friction; `from_skeleton`, `humanoid`, `as_dict`/`from_dict`),
  `RagdollMode`, `HUMANOID_LIMITS` by role, `forward_kinematics`, and the `Ragdoll` handle:
  `set_mode(mode, blend)`, `set_pose`, `place`, `play`/`stop`, `set_strength`, `hit(bone,
  impulse, point)`, `poses()`, `remove()`. `Physics.add_ragdoll(spec, position, rotation, mode,
  collision_filter)`, `Physics.ragdolls`, `Physics.ragdoll_of(body)`. Bones are `Body` handles
  and movers, so their poses come through the service's snapshot interpolated with the other
  bodies, and handlers, joints and rays name them. `Physics.remove(bone)` raises; a bone goes
  with its ragdoll.
- `physics.softbodies`: `SoftBodySpec` (pyjoltphysics' fields; enums as strings; `cloth`, `rope`,
  `ball`, `from_mesh`), `SoftBody` (`pin` to world points or `Body` frames, `unpin`, `set_wind`,
  `frame()`, `vertices()`, `remove()`), `SoftBodyFrame` (version, tick, origin, float32 positions
  and normals as views). `Physics.add_soft_body`.
- `physics.softmesh`: `weld` (vertices by position; glTF seams), `SoftMesh`;
  `Physics.add_soft_mesh(mesh or Shape, ...)` writes the particles and their normals into the
  mesh by version each `frame()`. `PBRMesh.set_vertices` writes in place; `_MeshGPU.update_dynamic`
  writes a buffer of unchanged size with `glBufferSubData` (also the CPU skinning path's uploads).
  Frames are read through one uid-to-row table a snapshot (`check_scaling` holds it).
- `physics.joltsoft.JoltRagdollsAndSoftBodies`, a base of `JoltEngine`: the `ragdoll*`,
  `soft_body`, `soft_pins` and `wind` commands; `Engine.ragdolls` and `Engine.soft_bodies`
  flags, so the omi engine raises `EngineUnavailable` naming the jolt engine.
- The Jolt engine's impulse at a point uses pyjoltphysics' `points` instead of a torque for a tick.
- Frame cost: `Physics.deformable_costs()` (counts; world-thread `ragdolls ms` and `soft bodies
  ms` a tick from pyjoltphysics' new `stats()` keys; render-thread `draw ms` a frame from
  `note_render_cost`), shown by `debugoverlay.physics_provider` under the physics section.

Characters (`character.ragdoll`): `RagdollRig.build(mixer, bones)` / `from_model(model)` chooses
`DEFAULT_BONES` from the humanoid map, bridges a rig joint of 0.12 m or more between two chosen
bones (Cesium Man's left upper arm, which the bone map misses), orders limb chains by depth (its
left arm is numbered from the hand), runs capsules to the first chosen child or along the skin,
reads radii from the skin (60th percentile of vertex distances from the axis), shares mass by
Dempster's segment fractions, takes limits by role turned into each joint's frame by the
figure's left, or HAnim Euler limits (`limits_from_hanim`). The arithmetic is in the world
(`placement`), so centimetre and Z-up documents give metre ragdolls. `RagdollFigure.update`
sends `AnimationMixer.blended_pose` as the target (one batch) while `following`; `draw` reads
all bones in one `poses` call and writes `AnimationMixer.reskin_from`. New mixer API:
`advance`, `blended_pose`, `reskin_from`, `joint_matrices_from`.

Documents: `scenegraph.softnodes.Cloth` and `Ragdoll` in the `OpenGLContext` component, read and
written in every X3D encoding (round trip tested); the glTF `OGLC_hook` kind `cloth` (no KHR or
OMI extension exists for cloth or ragdolls) with schema, the Blender tag's kinds and the hook
page. `Ragdoll` takes a glTF character by `url`; it reads no `HAnimHumanoid`.

Demos: `oglc-ragdoll` (`bin/ragdoll_demo.py`, `RagdollYard`: Cesium Man walking powered, struck,
knocked limp over 0.3 s, kinematic get-up over 1 s back to powered) and `oglc-cloth`
(`bin/cloth_demo.py`, `ClothYard`: a banner on a bronze pole in gusting wind, a drape on a
sandstone ball, a canvas sheet pinned to a beam and struck by thrown steel balls); tutorials
`physics_ragdoll` and `physics_cloth` in the Physics path; captures are identical between runs.

Defects found and fixed where they belong:

- pyjoltphysics: an impulse or force on a body still awake in the half second before it sleeps
  was lost: Jolt put it to sleep in that step. A push now resets the body's sleep timer
  (3321231, test over 15 push ticks; it surfaced as `test_a_shot_pushes_the_crate_it_hits` once
  impulses at points went through `points`).
- pyopengl accelerate: `VBO.data` and `VBOOffset.vbo` were refcounted by hand on top of
  Cython's own references, so an array assigned to `vbo.data` was released once too often at
  collection: segfaults during GC in `test_hanim_nodes` and `test_pbrmesh_gl` once
  `update_dynamic` assigned it. Fixed in `accelerate/src/vbo.pyx` (070eeda3, test of reference
  counts); `update_dynamic` uses `set_array` and `copied` so a released accelerate is safe too.

Limits and what is left:

- `Ragdoll` over an `HAnimHumanoid`: HAnim joints are not yet a `Rig` the builder takes.
- A ragdoll in a glTF document: no hook kind; the character's root would need the scene's rig.
- Joint `Transform`s are not written while a ragdoll drives a figure, so attachments stay at the
  animated pose.
- A pinned cloth never sleeps, so a world holding one keeps stepping.
- `Cloth` places its vertices in world coordinates: it sits in no `Transform`.
- Humanoid detection maps Cesium Man's left arm wrongly (`humanoid.py`); the builder's chain
  ordering and bridging correct it for ragdolls only.

Tests: the new unit modules (`test_physics_ragdolls`, `test_physics_softbodies`,
`test_physics_softmesh`, `test_character_ragdoll`, `test_softnodes`, `test_softbody_demos`) were
written against the new modules, which did not exist before (red at collection); the
`deformable_costs` row-table scaling test fails against a linear search per body. openglcontext
`tests/unit -m "not serial"` 19,317 passed, 65 skipped, 6 xfailed; `-m serial` 29 passed;
`tests/test_all_scripts.py -k physics` 22 passed. pyjoltphysics 501 passed, 2 skipped, serial 1,
doctests 12 (scratch venv without omi_physics). pyopengl `tests/gl` and `accelerate/tests` 573
passed, 301 skipped.
Game suites against the branch (`-m "not serial"`): twig-bb 2,407 passed, 1 skipped;
hill-runner 652 passed, 1 skipped; marble-demo 941 passed, 6 xfailed; marble-editor 165 passed;
openglcontext-forest 86 passed; glisteel 1,670 passed, 1 xfailed (against develop after the merge). The walk toggle test (`test_gltf_view_physics_toggle[walk]`) failed on develop after P5b: its driver called `OnIdle` and not `runFrameHooks`, which steps the physics service; the driver now runs the frame hooks as the main loop does. Tutorial baselines blessed in reference-images 665815d.

### P6e as built (2026-10-31): deaths as ragdolls, and twig-bb's corpses

openglcontext branch `corpse-ragdolls`; twig-bb `develop`.

twig-bb's figures are skeletal glTF with VRM humanoid bones (`CHARACTER-RIG.md`, two builds,
19-bone ragdolls with the bridged neck and shoulders); the game has no MD3 or other
tag-segmented model, so a segmented ragdoll has no user and was not built. `RagdollRig` takes
the figures as they are.

Engine:

- `Physics.add_ragdoll(pose=, queryable=)`: bones start at rest in the pose (teleported before
  the first tick; the limits stay the spec's rest pose's); `Body.queryable`: rays, sweeps and
  overlaps pass through a body that still collides (`Physics._skipped` adds them).
- `Ragdoll.push(velocity)` (each bone's mass times it), `Ragdoll.nearest_bone(point)` (nearest
  capsule surface), `ragdolls.pose_rows`.
- `RagdollFigure` starts in the animation's pose; `knock_down(impulse, point, velocity, blend,
  bone)`: powered at once, the push and the hit, limp over the blend while following, then not
  following; `settled`; a settled or removed figure keeps its last pose and draws nothing new;
  `update` does nothing while not following. `draw` writes the clip-driven joints
  (`AnimationMixer.write_joints_from`), so attachments follow: the P6d limit is gone for joints a
  clip drives (an undriven joint's rest is read back from its Transform, so it is not written).
- `RagdollRig.placed(matrix)`: one rig per build, shared. `RagdollRig.worlds` composes each
  rider's offset from its bone once per pose object.
- `RagdollBudget(limit)`: `admit` freezes the oldest past the limit (removed, last pose held).
- `Crowd.remove` ends a compute shader's palette claim (`PBRMesh.release_skin_palette`): a figure
  taken out of a crowd drew the palette range the shader last wrote, whatever was set on it.
- `rig.matrix_quaternions`, vectorised (Shepperd); `character.ragdoll` re-exports it.
- Found on the way: `x3dshaders._compile` left the GL_INVALID_ENUM of a refused stage pending
  when error checking was off, and the next checked call (`glUniform1i`) raised it
  (`test_a_context_with_no_tessellation_draws_the_material` under `-n 8`); the flags are read now.

twig-bb (`twig_bb.corpses`): a bot's `Death` makes its figure a `RagdollFigure` out of its crowd at
the rules' position and the body's facing, not queryable, its walker removed (a respawn places a
new one). `killing_blow` reads the tick's events: hitscan rounds from the killer give the weapon's
new `impulse` field (pistol 45, shotgun 18 a pellet, rifle 110 N s) each along the `Fired`
direction at the last round's point; a burst throws the body as it throws the living (projectile
`knockback` times falloff, away from the centre); lava and falls give nothing. The walker's
velocity is added. `MatchSetup.ragdolls` (default 6, play screen "Ragdoll bodies", saved) and
`--ragdolls N` set the budget; 0, a figure without a humanoid and an engine without ragdolls play
the death clip. A corpse lasts while its owner is dead (1.5 s for a bot; the figure is the
combatant's own) and a respawn ends it and returns the figure to its crowd. The player has no
drawn body, so no player ragdoll. Hit detection is unchanged: the dead are not staged, and corpse
bones are not queryable.

Frame cost, ten corpses struck at once on a floor (twig-bb figures, inline 60 Hz, meshes skinned
on the GPU side, load average 24 to 29 from other users): the overlay's `ragdolls ms` (world
thread) 0.014 ms a tick in the first 0.5 s, 0.002 to 0.007 after; physics step 0.35 to 0.79 ms a
frame; `ragdolls draw ms` 5.9 ms a frame during the 0.25 s blend, 0.8 to 1.2 ms after (10.7 and
4 to 6.6 ms before the rider-offset cache and the idle `update`).

Limits: a corpse ends at its owner's respawn; corpses outliving it need a second figure per
combatant. Lying ragdolls take several seconds to sleep (4 of 10 asleep at 4 s).

Tests: engine `test_physics_ragdolls` (posed start, queryable, nearest bone, push),
`test_character_ragdoll` (posed start with a shared rig, knock-down, momentum, settle and
removal, joints, budget), `test_character_crowd` (palette claim), `test_x3d_shaders` (refused
stage); each seen failing first. twig-bb `tests/test_corpses.py` (13) and a GL test that the
fallen body is drawn lying where it stood.

The `physics_ragdoll` baseline (2026-10-31): the posed start changes the opening's fall. Cesium
Man now falls straight along the blow (-Z) and lies with his head toward the bench (hips 0.17 m,
head 0.23 m up, still rolling slowly at the capture); the tutorial's camera sees him
foreshortened, feet first, which reads as a crouch but is the lying body (a view from above
shows it). The skin is drawn where the bones lie: `tests/unit/test_ragdoll_draw.py` settles a
skinned figure (`_character_assets.ragdoll_figure_glb`) on a floor and holds every vertex to its
bone's body within 1 mm, with the shader and the CPU deform drawing the same frame, in a hidden
GLFW window and offscreen (`tests/helpers/_ragdoll_draw_harness.py`); seen failing with the
settled-figure rule made to skip every draw. The capture is byte-identical over five runs; the
baseline was re-blessed.
### Character falls as built (2026-10-31): a character's body as a ragdoll from a fall to its get-up

openglcontext branch `character-tumble`, rebased onto P6e; hill-runner branch `ragdoll-trip`.
pyjoltphysics is unchanged. P6e's `RagdollFigure.knock_down` is a death for a figure the game
poses itself; `CharacterRagdoll` is the fall of a physics character, which gets up again.

Engine:

- `Physics.add_ragdoll(..., velocity=, angular_velocity=, blocks_characters=)` beside P6e's
  `pose=`: the bones start moving from the first tick, and with `blocks_characters=False` the
  characters' controllers pass through them, in one ignore-set update for all the bones
  (`_IgnoreSet.update` and `difference_update` send once). A posed or moving start travels with
  the `ragdoll` command and the Jolt engine applies it as one `set_transforms` and one
  `set_velocities` after the add, in place of a `place` command for each bone.
  `Physics.passable` lists the bodies characters walk through.
- The Jolt engine keeps the pyjoltphysics settings of the last eight specs made, each with a copy
  of the spec, and makes them again only for a spec that has changed (0.3 ms a ragdoll).
- `character.ragdoll.CharacterRagdoll` and `RagdollRest`; `Character.ragdoll`;
  `Physics.add_character(ragdoll=True or a RagdollRig)`. Contract: the capsule is the gameplay
  authority. `fall(impulse, bone, point, velocity)` knocks it down and starts a powered ragdoll in
  the last drawn pose (the bones placed against the capsule's last step, since the world's bodies
  are drawn a part step behind it), each bone at the capsule's velocity; limp after `powered`
  (0.12 s) over `limp_blend` (0.2 s). `rest()` gives the ground under the pelvis (ignoring
  passable bodies), the heading and the speed. `recover(blend, place)` removes the ragdoll, stands
  the capsule at the rest point and blends the figure from the body's last pose to the animation's
  over `blend` seconds (world-space lerp and slerp by bone, smoothstep); it does not end the
  knocked-down state. While active, `Character.animate` calls `draw` in place of the model's
  update and the node follows the body; `Character.remove` parks the ragdoll.
- `Character._frame` sets the part step before `animate`, and the facing turns before the figure
  is drawn, so a figure posed in the world is posed against the node where the frame draws it.
- Defect fixed: `Character._lag` interpolated the capsule's centre, so a change of height (getting
  up, being knocked down) was drawn for one frame as the feet moving by half the change: the hill
  runner's node dropped 0.55 m on the frame it rose (on develop, without ragdolls). The drawn place
  now interpolates the feet (`controller.base()`).
- `_relative` (pose targets from world poses) is vectorised: 0.46 to 0.04 ms for 19 bones, which
  `RagdollFigure.update` also pays each frame.

hill-runner: a runner wearing the humanoid model falls as a ragdoll at every hit and crash.
`game.BLOWS` gives each kind of obstacle a blow (log: 45 N s up the hill on the left shin and
3 m/s up; crevice: half that on the shin; bough: 35 N s on the head; wall: 70 N s on the chest;
ceiling as a bough). While tumbling, the rules' distance and lane follow the pelvis (the camera
and the hill's bodies follow); with `GET_UP_TIME` = 0.68 s of `STUMBLE_TIME` left the runner
`stand_up`s where the body lies, or short of an obstacle it lies in, and the blend meets the
`Roll` clip at its lowest point (0.70 s of its 1.47 s at the down role's rate). The rig is built
by the first `World.spawn` and carried from session to session. A log is a 1 m box, taller than the
pelvis, so a body tripped by a log comes to rest against or on it; a crevice, which has no body,
lets it tumble 3.5 to 4 m down the hill at 10.5 m/s.

Costs (hill-runner session with the model, main-thread `thread_time`, other agents running):
without a trip, `Session.step` median 1.07 ms on develop and 1.08 ms on the branch over four
600-frame demo runs each, twice. The trip frame: 3.4 to 3.6 ms against 1.0 to 1.4 ms for the
same frame without a trip; `fall()` itself 1.1 to 2.0 ms (median about 1.3 ms: blended pose
0.17, bone poses 0.10, `add_ragdoll` 0.4 with the settings kept, the rest commands), and the
world's first ticks with the new ragdoll about 0.4 ms more. Tumbling frames 0.9 ms, blending
frames 1.1 to 1.2 ms.

Tests: engine `test_physics_ragdolls` (start pose and velocity, per-bone velocities, characters
through bones, settings kept), `test_character_ragdoll` (no ragdoll until a fall and no ragdoll
work, hand-off continuity within 3 cm of a frame's travel, velocity carried, a blow's direction,
powered then limp, recovery placement and blend continuity within 3 cm at the start and 1 mm at
the end, passable ground, removal, falling twice), `test_physics_character_steps` (a change of
height is not drawn as a move); hill-runner `tests/test_ragdoll.py` (state sequence, tumble and
blend lengths, pelvis continuity at all four changes within a frame's travel plus 0.1 m for each
kind of obstacle, down the hill on open ground, getting up short of a log, crash, no ragdoll
work while running, a model-less runner as before). Each was seen failing before its change.
The hill runner has no image baselines, so there is no capture.

Limits: the hit's blow is the rules' (`game.BLOWS`), not a contact's impulse; the bones take the
capsule's velocity and not each limb's animated velocity; joint transforms (attachments) stay at
the animated pose while a ragdoll or a blend draws the figure.

### P5c as built (2026-10-31): the omi engine deleted

openglcontext branch `p5c-omi-removal`; pyjoltphysics c929894; twig-bb 527eeba;
openglcontext-editor 0613426; glisteel 00ad36a; glisteel-editor ddfdeac; marble-demo 231f815.
The root `uv.lock` is not regenerated (it still lists the `omi-physics` extra). It was
regenerated later the same day, and no longer lists the extra.

Deleted from OpenGLContext: `physics/omiengine.py`, `omi_adapter.py`, `runtime.py`,
`worker.py`, `replica.py`, `queries.py`, `x3domi.py`; `engine.require_omi`, `OMI_EXTRA`, the
stand-in machinery (`Engine.stand_ins`, `push_reach`, `build_replica`, `proxy_bounds`,
`Engine.replica`, the service's replica, `_settle_stand_ins`, `_bring_up*`, `_seen_in_step`,
`_defers_stand_ins`, the character clock, `Physics.worker`, `_run`, `_engine_world`,
`_slot_of`, `_body_at`; the character's stand-in writes; `stand_in_proxy` is
`character.capsule_proxy`); the Jolt engine's `backend`, `standin` and `run` commands;
`PhysicsDefinition.backend`, `BACKENDS`, `default_backend`, `OPENGLCONTEXT_PHYSICS_BACKEND`
and `EngineInfo.compute`; `gltf_world.collision_world_from_scene` and `collision_groups`;
`props.PropColliders`; `zones.gravity_volumes` and `GravityZones`; `debugdraw.PhysicsDebugDraw`
with the omi proxy helpers (`ProxyOverlay` stays); `nav.navmesh.from_world`;
`OpenGLContext.testing.physics`'s `inspect`, `slot_of`, `body_at`, `run` and every omi branch;
the `omi-physics` extra; `tests/unit/omi.py`, the `engines` marker and the `physics_engine`
fixture.

Ported:

- `PhysicsDefinition.engine` stays, with `ENGINES = ('jolt',)`, as the field another engine
  would be named in. `settings.check_engine` refuses `'omi'` with a ValueError naming the
  engine and the migration note (docs/physics.rst, "Programs that named the omi engine");
  `OPENGLCONTEXT_PHYSICS_ENGINE=omi` is reported and ignored by `env_choice`.
- `TerrainColliders(physics)` holds a static triangle-mesh body of the service per drawn
  tile; `TilesTerrain(physics=)` replaces `physics_world=`.
- `PhysicsViewPlatform(character, yaw)` takes a service character (`over` is the same).
- `navmesh.from_scene(group)` builds from `gltf_world.extract_trimesh`, the triangles the
  scenery's static bodies are made of.
- The tile, prop, road, height-field and landscape collider tests use the service's
  queries on Jolt, and drive the engine's vehicle where they drove omi's raycast vehicle;
  `tests/tiles_walk.py` and `tests/tiles3d/test_navigation.py` walk a service character on
  streamed tile colliders.
- Recorded omi answers in place of live ones: `test_physics_massprops` (inertia and bounds of
  nine shapes), `test_physics_neutral_types` (OMI field names and defaults, character states,
  material presets). The tests of conversions to omi types went with the adapter.
- `omi_physics` stays in OpenGLContext's `dev` extra only, for
  `test_physics_cooking::test_the_same_pieces_as_omi_physics` (live, skipped without it);
  `test_physics_without_omi.py` still runs the engine in child interpreters that cannot
  import omi_physics.

Found and fixed on Jolt (the omi-only tests that guarded it ran on omi alone):

- A teleport did not move a capsule out of what it overlapped, so the free-fly camera
  (`TerrainWalkMixin.collide_and_clamp`) stood inside trunks and rocks
  (`test_terrainwalk_colliders`, 11 tests). `JoltController.safe_bind` now asks
  `JoltEngine.push_out`: an overlap test of the capsule 5 cm above its seat, then the
  capsule swept back towards its place from 2 m out in 32 level directions and from above,
  the nearest clear place taken, at most six pushes, each reseated; False where none is
  clear. Jolt's shape cast from a start inside a body missed 8 to 22 of 41 heights in a
  measured case, so the escape is found by sweeps that start outside. `floor_under` passes
  through a body the capsule's top is inside rather than taking its inside as a floor.
  Tests: `test_physics_character` (into a post, into a gap with no clear place).

Tests deleted with what they tested (each read omi internals): the worker, runtime, frame
cost, sweep steps, backend, quiet-character, stand-in, inline-access modules; the replica and
slot tests in `test_physics_service`, `test_physics_world_api`, `test_physics_neutral_api`,
`test_physics_service_events`, `test_physics_joints`, `test_physics_filters`,
`test_physics_queries`; the X3D collection's world and body-settings memo tests (they read
omi world arrays; `test_a_jolt_world_is_made_again_for_its_settings` covers the rebuild);
`test_the_finer_step_is_taken_at_the_rate_asked_for` (a Jolt world keeps the tick it was
made with); the `PhysicsDebugDraw` tests; a vehicle-less engine's vehicle test.

| Suite (main checkout after the merge, no engine setting) | Result |
|---|---|
| openglcontext `tests/unit tests/tiles3d -m "not serial"`, `-n 16` (worktree) | 18,496 passed, 56 skipped |
| openglcontext `-m serial` (worktree) | 29 passed, 1 skipped (no glTF baselines in the worktree's reference images) |
| `tests/test_all_scripts.py -k "physics or walk or x3d or tiles or navmesh or terrain"` | 36 passed |
| hill-runner | 662 passed, 1 skipped |
| twig-bb | 2,421 passed, 1 skipped |
| marble-demo | 941 passed, 6 xfailed |
| marble-editor | 165 passed |
| glisteel | 1,670 passed, 1 xfailed |
| openglcontext-forest | 86 passed |
| openglcontext-editor | 1,492 passed |
| omi_physics (unchanged) | 1,822 passed, 3 xfailed |
| pyjoltphysics `-m "not serial"` / `-m serial` | 525 passed, 2 skipped / 1 passed; differential 75 passed, 74 and 1 skipped with omi_physics blocked |
| `tools/preflight.py openglcontext pyjoltphysics omi_physics --rebuild-env`, lint, oglc-check, typecheck | 9 of 9 |

Left:

- `Character.stuck` stays set until the next teleport (pyjoltphysics sets it only there).
- Crouched with `set_move(speed=9)`, `JoltController.speed()` answers 9 while the body moves at
  `crouchSpeed`.
- `tickHz` given to `enable` or `set_config` is kept until the world is made again; the
  `physics_stairs_tuning` tutorial's finer step changes nothing on Jolt.
- The root `uv.lock` needs `uv lock` for the removed extra (done 2026-10-31; it is gitignored,
  so each checkout regenerates its own).
- `tests/tutorials/core_context/navmesh_demo.py`'s comment still names `from_world()`: the
  file holds another agent's uncommitted edit, so it was left; the comment should name
  `from_scene(scene)`.

## 7. Decisions

Decided 2026-10-30: each recommendation below was accepted as written. On 5 the answer was to
turn the deterministic build on, and on 10 to ship both free-threaded and ordinary wheels.

1. Binding. Recommended: nanobind (14 ns a call, free-threaded wheels, mypy-clean stubs, CMake).
   SIP costs 39 ns a call, re-enables the GIL on 3.13t and 3.14t, and its stub fails mypy strict.
2. Name. Recommended: `pyjoltphysics` for the distribution and the import; `pyjolt` is a web
   framework on PyPI.
3. The omi fallback. Recommended: dropped at P5; omi survives as golden results for the
   differential suite. As taken at P5 (2026-10-31): Jolt is the default and pyjoltphysics a
   requirement, and the omi engine stays as the `omi-physics` extra (`OpenGLContext[omi-physics]`), selected
   only by a program that names `engine='omi'`, because glisteel's race drives omi's
   `RaycastVehicle` until P6 and deleting the engine first would break it. Nothing falls back:
   naming `omi` without omi_physics raises `EngineUnavailable` naming the extra. The engine and
   the parts still built on an omi world are isolated behind `engine.py` and `require_omi`;
   "P5 as built" lists what blocks the deletion and exactly what it removes. As taken at
   P5c (2026-10-31): the omi engine is deleted and `engine='omi'` is refused.
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

## Review follow-ups

The 2026-10-31 critical review's findings, as handled. Each entry names the finding, then the
commit.

- H11 (a mass change rebuilt the X3D world, moving hinge stops by the angle turned): mass and
  inertia go to the body in place with `set_motion`; every rebuild makes each joint again where
  it stands, keeping its first frames and its readings. Test: `TestChangesMidRun` in
  `test_x3d_rigid_body.py` (mass twice, centre of mass, a world setting, a motor joint).
  7a7ba350.
- M8 (run-time stops and collider bounce and friction ignored): a joint whose stops or
  suspension change is made again where it stands, its readings carried on; the collider's
  bounce and friction redefine the bodies' materials through the new
  `MaterialTable.redefine` (pyjoltphysics ffbf53b). docs/x3d.rst says what is read every
  frame. A stop moved past where its joint stands holds the joint there, as Jolt clamps a new
  joint's limits to bracket its starting place. 7a7ba350.
- H12 (a Cloth bound again was transformed twice): `softmesh.rest_pose` records the authored
  vertices before the first write, and every soft body and the Cloth's pins are made from
  them. cd4ebb1b, docs 63d5f352.
- H13 (the glTF cloth hook placed the body by the local matrix under moved parents): the
  Cloth takes the node's world matrix in its document, inside a `MatrixTransform` undoing the
  parents; the test compares the drawn vertices, through the renderer's own path matrix, with
  the simulated ones. A scale on the node is not applied, and a glTF loaded under an outer
  Transform is outside the Cloth's contract as an X3D Cloth in a Transform is. cd4ebb1b, docs 63d5f352.
- M10 (soft-mesh tangents left at the rest pose): `softmesh.transport_tangents` turns each
  tangent by its normal's least rotation on each write, square to the normal; `PBRMesh.set_vertices`
  takes tangents. cd4ebb1b, docs 63d5f352.
- M9 (a floor inside a Collision group read as a collision): the probe capsule is wider than
  the walker and no taller, and the walker's ground (`Character.ground`, new) is left out.
  4fb1a08b.
- L23 (capsule mass properties as a cylinder): the half spheres' volume and inertia; a
  capsule(1.5, 0.4) at 3 kg now has volume 1.022 m3 and axial inertia 0.2274 kg m2, from 0.754 and
  0.240. `test_physics_massprops` integrates the capsule and the frustum slice by slice;
  omi_physics' own `massprops` keeps the cylinder (its table no longer holds the capsule's
  inertia here). 2b319a7b.
- L20 (ground-following tolerances widened to 0.02 and 2e-3): measured at 1e-9, the flat
  cases miss by at most 4.1e-6 m (single-precision positions), so they hold to 1e-5. The slope
  case adds the capsule's lift on a slope, r (1/cos - 1) = 1.25e-3 m, and holds to 3e-4 of it
  (1.05e-4 measured, the height field's quantisation). The rock cases hold to 1e-3 (7.4e-4
  measured, flat triangles under a round top) and 1e-4 (2.8e-5). fe4c1cc7.
- L21 (importorskip of hard dependencies and of a game): 95 importorskip calls of pygltflib,
  pillow, numpy and pyjoltphysics in 73 test files are plain imports; the hill-runner clip
  check moved to hill-runner's `test_cues` (hill-runner 41b2290). `tomllib` keeps its importorskip,
  since Python 3.10 is supported and has none. 26e9138c.
- L5 (two ragdoll tests failed when run alone): `tests/unit/_ragdoll_assets.py`, imported
  relatively; `test_display_check_shared` no longer puts tests/unit on `sys.path`. 7ec6243a.
- L24 (pyopengl's VBO reference test passed with the accelerators off): it asserts the VBO is
  `OpenGL_accelerate.vbo`'s and skips where the accelerators are switched off; it fails where
  the accelerated module does not load. pyopengl 9f7f9aed.
- L30 (no test pinned pyopengl-video's DeprecationWarning-free import): every packed
  structure in the package names `_layout_`, and `vpl.api` imports under
  `-W error::DeprecationWarning`; both fail with one `_layout_` removed. pyopengl-video d5129e3.
- Suspicion, `test_physics_filters.py` handlers collected at once: verified with a mutant.
  Without the `addEventHandler` calls three contact-filter tests fail, so the registration
  takes effect, but it worked through a lambda collected at once. The handler is now a
  module function. 6e8d9a29.

- H15 (pyjoltphysics required with no floor and not on PyPI): CI builds it from the develop
  branch of its repository, with a comment to remove the step once it is on PyPI, in
  openglcontext's `test.yml` and `documentation.yml` (db18fc5f) and in marble-demo (9d92721) and
  marble-editor (6209b27), which install OpenGLContext from git. twig-bb, glisteel,
  glisteel-editor, hill-runner, the forest and openglcontext-editor install OpenGLContext
  3.0.0a8 from PyPI, which requires omi_physics and not pyjoltphysics, so their workflows are
  unchanged; release.py releases pyjoltphysics before any OpenGLContext that requires it. The
  floor is not written here. `release.floor_problems` reports a sibling required with no floor
  (an extras requirement takes the floor another requirement of the project names), checked
  against every workspace project, and `--apply` refuses it. On the workspace today it reports
  openglcontext's `pyjoltphysics`, pyvrml97's `PyDispatcher`, glisteel-editor's
  `OpenGLContext-editor` and `glisteel`, and marble-editor's `openglcontext-marble-demo`.
  Root 1b04342.
- M18 (the reference_images gitlink is on no remote branch): `release.check_ready` refuses a
  project whose HEAD records a submodule commit no remote-tracking branch of that submodule's
  checkout contains (`unpushed_gitlinks`). It reports openglcontext's `tests/reference_images`
  at 63c8194, so reference_images has to be pushed before openglcontext can be released.
  Root 1b04342.
- M22 (the radeonsi NGG workaround reaches test sessions only): the maintainer's decision is to
  document it for applications. docs/backends.rst, "Known driver defects", gives the symptom,
  the stack, `AMD_DEBUG=nonggc` and the Mesa report; docs/testing.rst and the drivercull
  docstring say the switch is for test sessions. c6ba48dc.
- M23 (a dry run fetches every repository): `--no-fetch` skips `git fetch origin` in the
  repositories and submodules; the module docstring, the help text and the root CLAUDE.md say a
  run fetches and writes, commits and pushes nothing without `--apply`. Root 1b04342.
- M25 (`TilesTerrain(physics_world=)` in the docs): tiles3d.rst and loading.rst name
  `physics=context.physics`. No other deleted physics name is left in docs, docstrings or
  tutorials; settings.default_engine's docstring no longer speaks of several engines. a05199ab.
- M26 (Ctrl-C ended the main loop as a closed window): `WindowSystem.mainLoop` lets
  KeyboardInterrupt propagate after the journals close and the window is released, and
  `Context.ContextMainLoop` turns it into exit status 130 with no traceback. Test:
  `tests/unit/test_mainloop_interrupt.py`; docs/embedding.rst. A KeyboardInterrupt inside a
  draw still goes to `OnQuit` (context.py), which ends the process with status 0, since a draw
  run from a toolkit's C callback cannot raise to the loop. a4e48ad5.
- M27 and L34 (plan claims the code contradicts): the status summary states the state after
  P5c; the registration bullets of P0 and P4 say it landed (root ccdb196); the spike's omi ray
  figure is marked as an estimate; the P1b table says which omi cells `test_scenes.py` asserts;
  section 4's rows for `records.py` and `PhysicsDefinition.mode` say what stayed; the rope
  builder adds bend edges only with a finite `bend_compliance`; the limp humanoid's swing bound
  is its bend plus its larger cone half angle, as `test_ragdolls.py` asserts; the uv.lock lines
  say it was regenerated.
- L28 (drivercull narrated past failures and a disproved second-context cause): the docstring,
  docs/testing.rst and the `OPENGLCONTEXT_NGG_CULLING` comment in test_render_options.py state
  the clip w = 0 fault and its rate in the present. c6ba48dc.
- L31 (release.py read only `__version__`): a version file's `VERSION = '...'`, which
  scikit-build-core's default regex reads, is read and rewritten where no `__version__` is.
  Root 1b04342.
- L32 (physics=/audio= coercion unlike navigation's): `contextdefinition.settings_node` takes a
  mapping for all three fields and a bool for physics and audio; `navigation=True` raises
  ValueError naming `navigation=None`. docs/physics.rst. f95ed556.
- L26 licence half: license.txt lists cooking.py and massprops.py, copied from omi_physics (MIT,
  same author), among its exceptions, and cooking.py's docstring names hull.py and cookery.py.
  1a1f7548, ba1484c6.
- L36 (prose on added lines, openglcontext's share): the perception verbs in locomotion.py,
  physics_stairs_thread.py, character_camera.py and character_footsteps.py name the mechanism,
  and the em dashes in gltf.rst and instancing.rst are gone. `scan.py --base origin/develop`
  reports nothing on openglcontext. f9eaf160.
- L35 (commit messages): not rewritten, since history is not rewritten. Ten openglcontext
  commits carry `Co-Authored-By` trailers (ae89ba96, c9a7259a, 67f551f2, 5bf1b012, 21da4787,
  5b76b5d3, 76c218e8, fe492c85, c47dfaf1, bb7193e4); 67 subjects run over 72 characters; 24
  openglcontext and 11 pyjoltphysics commits have no bullets; 79d2bf50 mixes the
  ContextDefinition coercion (L32), the main-loop change (M26) and tutorial edits.

The findings that touch the Jolt engine layer (`joltengine.py`, `service.py`, `handlers.py`,
`joints.py`, `body.py`, `stepview.py`) landed in dd23bb5c, with the free-threaded locks and the emptied rows in the commit after it.

- C7, C8: `JoltEngine.lock`, an `RLock` held by `submit` around each command, by the frame's
  publish, by `_push_forces` and by the vehicle table. A posted function runs outside it. A
  ragdoll or vehicle removed on the world thread leaves the render thread's tables in the next
  frame; `StaticInstances.remove` leaves the specs to the command. The proxy overlay no longer
  treats a static-instance batch as a body. `JoltVehicles.send` raced the render thread (the
  review's unverified suspicion): ids and rows came from two passes over a table the other thread
  changed, and `test_vehicles_removed_on_the_world_thread_leave_the_frame_whole` failed on it.
  Tests: `tests/unit/test_physics_thread_safety.py`, five patterns of 5 s each.
- H9, M7: shapes are counted per (proxy uid, dynamic) by the bodies and static-instance batches
  using them, and `world.remove_shape` runs when the count reaches 0. One path,
  `JoltEngine._forget_body`, lets go of a body's kind, pose, mass, standing forces, joints,
  vehicles and shape, for `remove`, for each bone of `ragdoll_remove`, and `remove_many` pops the
  kinds of its instances. A removed body's kind is kept with its retired uid for its last
  character records. Ragdoll settings dropped from the eight kept have their bone shapes removed
  once no live ragdoll uses them. A ragdoll's removal takes out a vehicle on one of its bones
  first, natively, so the vehicle never steps a freed bone (the engine-side half of C3), and the
  service marks that vehicle dead. Tests: `tests/unit/test_physics_engine_tables.py`.
- H7: `_op_place` and `restore_state` record the sequence of their batch; a frame whose older
  snapshot predates it draws that body (every body, for a restore) at the new place, unblended.
  The records go once the snapshot frames draw from includes them. Tests:
  `tests/unit/test_physics_interpolation.py`.
- H8: a free-running world is interpolated. `JoltEngine._free_running` keeps the two newest
  snapshots the frames read and a frame clock held between the newest snapshot's time and a
  tick after it; the frame is drawn a tick behind that clock. The thread-mode repro repeats a
  pose on 3 of 240 frames (it repeated on 180; inline repeats on 1). The test is serial: it paces frames by the wall
  clock against a world thread paced the same way.
- H10: `HandlerTable` indexes its handlers by (kind, phase, thread) and by body, built again on
  the first read after a change, and `audience` looks at the handlers on the event's two bodies
  and on every body, in registration order. `_dispatch` finds the render-thread audience once
  an event. Test: `tests/unit/test_physics_handler_table.py`, `check_scaling` on the count of
  `hears` calls (1.0 times from 250 to 1,000 handlers; it was 4.0).
- H14: a Jolt world cannot change its step, and pyjoltphysics has no call that would.
  `Physics.enable(tick_frequency=)` and `set_config` with another `tickHz` raise `ValueError`
  and change nothing (the same rate is accepted). The test is
  `test_a_tick_frequency_other_than_the_worlds_is_refused_changing_nothing`; docs/physics.rst
  and the `physics_stairs_tuning` tutorial (its `f` key is gone) say the step is chosen in the
  definition. marble-demo's `test_a_lethal_blow_in_an_early_step_of_a_slow_frame_still_destroys`
  asked a 60 Hz world for 120 Hz and ran at 60 Hz; it now makes its world at 120 Hz.
- M2: snapshot rows are stable within a layout. A removed body's row is emptied, a new body takes
  a row at the end, and the rows are packed (a new `Snapshot.layout`) once more than half of them
  and at least `PACK_AFTER` (1,024) are empty. `changed` is counted across adds and removals, and
  the service extends its pose table from the new entries alone. `scaling.py` at 10,000 still
  bodies with one spawn and one removal a frame: 1.7 ms a frame (it was 47 ms). Test:
  `check_scaling` on the nodes written (1.0 times from 500 to 2,000 bodies; it was 3.98).
- M3: the switch interval is one process-wide count (`joltengine._SwitchInterval`): the first
  engine with a world callback keeps the interval it found and sets 1 ms, the last to let go
  puts it back. Test: `test_the_switch_interval_is_short_while_any_service_has_a_world_callback`.
- M4: `PhysicsDefinition.maxBodies` (65,536) reaches `WorldSettings.max_bodies`. Every `add_*`
  checks `Engine.held_bodies()` plus its count against it on the calling thread and raises
  `ValueError`. A command the engine refuses calls `Engine.refused`, and the service marks the
  body (or the ragdoll and its bones) dead and lets go of it. A removal makes room once the world
  applies it, as pyjoltphysics counts a body until then.
- M5: `add_*` of a node whose body is alive and not scenery raises `ValueError`; scenery bodies
  are still claimed.
- M6: `Physics.frame` and `step` raise `ValueError` for a NaN `dt`; `FixedSteps.owed` adds no time
  for one. Negative time adds none and infinite time is clamped, as before.
- M11: joint numbers go through `checks.number`: motor speeds and forces (the force not below
  zero), torques, suspension and a distance's length. `drive(speed, 0)` switches the motor off
  (`MotorMode.OFF`); it set an unlimited force.
- M16: `PhysicsDefinition.handlerErrors` (`log` or `raise`, env
  `OPENGLCONTEXT_PHYSICS_HANDLER_ERRORS`). With `raise`, the first exception a handler, step
  code, an engine hook or a posted function raised since the last frame is raised from `frame`
  (and `step`) once the frame's work is done. The testing plugin sets the variable to `raise`
  where it is unset, so marble-demo's suite needs no change. glisteel and hill-runner keep their
  own re-raises; they still work and are left as they are.
- M24: `stepview.py` imports `Hit` from `physics.types`. `ignore_missing_imports` is false, and
  an override names the packages that ship no types (optional toolkits and loaders, ttfquery,
  pyopengl-video). The scoped check found `windowsystem/glut.py` importing the missing
  `OpenGLContext.tests.resources`: `createWorldMenu(directory, urls)` now reads the worlds and
  the URL list from paths it is given. `tools/preflight.py` installs again, in place, each project
  whose source changed since the typecheck environment installed it (workspace root, 7dbb48e),
  which removes the files the checkout deleted.
- M28: `_settle_markers`, `_op_settle` and `_markers` had no caller and are gone. Tests cover the
  `_svc` eviction (`RETIRED_KEPT`), engine hooks, listeners and posted functions that raise, step
  code that raises or is cancelled, and `_raise_worker_error`.
- L4: the service mounts its proxy overlay again each frame, `Context._mountOverlay` moves it
  into the scene drawn now (once), and `close()` takes it out. The overlay leaves out
  static-instance batches, which `poses()` could not answer for.
- L6: `Character.set_move` and `set_fly_move` raise `ValueError` for a direction that is not
  finite, leaving the move as it was.
- L7: `Ragdoll.step` answers whether the figure changed mode, follows its animation or is not
  settled; a LIMP node's figure follows no animation from its start, as after a change to LIMP.
- L22: `testing.physics.mass()` measures Jolt's mass: an impulse of about the asked mass times
  1 m/s, the change of velocity read back between ticks, then undone. A given mass forced to
  1 kg no longer passes `test_mass_given_is_the_mass`.
- Unverified suspicions: `JoltVehicles.send` raced (C7, above). `Physics.close()` from the world
  thread left a free-running world ticking for good (the test saw the tick go from 23 to 83 after
  close); `JoltEngine.close` now always calls `world.stop()`, which on the world thread stops
  after the tick in progress, and a lockstep run that close ends runs no more ticks.
  `write_poses` announced only translation, so a ROUTE from a physics-driven rotation never
  fired; the rotation is now announced where something listens for it (one `getReceivers`
  lookup a node otherwise). `testing.physics.settle()` returned silently when `wait_tick` timed
  out or the world was stopped; it raises `AssertionError`.
- Free-threaded 3.14t: there is no engine suite environment for it, so one was built in the
  scratch area (pyjoltphysics develop ffbf53b as a cp314t wheel, the workspace's pure-Python
  siblings on the path, simpleparse built for it). The thread-safety, table, interpolation,
  handler, service, event, vehicle, joint, ragdoll, character, query and body-change tests pass
  there with the GIL off. The first run found `tuple(dict.values())` is not atomic without the
  GIL: the service's vehicle table takes `_vehicles_lock`, and the engine copies its tables under
  its lock (`JoltEngine._copied`).
- The engine unit suite on the rebased branch: 18,409 passed, 56 skipped, both serial passes
  (30 passed). One failure, `test_x3d_picking.py::test_a_group_that_is_not_pickable_hides_its_shapes`,
  was GLFW failing to make a window ("EGL failed to allocate resources") at load 35; the file
  passed 3 of 3 runs alone.

Games (M14 to M17, L15 to L19, L36's game files):

- M14 (a dead bot's body kept turning toward its last aim): `move_bodies` gives the dead no
  facing, so the body keeps the rotation the corpse was placed with. twig-bb bb8d294.
- M15 (a corpse out of sight stayed at y=-10000): a dead bot's body is written back to where
  it fell when it is in sight again, and only when it differs. twig-bb bb8d294.
- M16 (marble-demo swallowed step errors): marble-demo loads the testing plugin, and
  `test_step_errors` makes `advance` raise (marble-demo f51be4c, another agent). Verified: the
  marble-demo suite passes with it, 946 passed.
- M17 (glisteel's scrub band tuned on omi): measured on the Jolt car as the soundtrack reads it
  (mean of the four wheels' slip): a clean lap peaks at 0.137 m/s, an autopilot at 1.8 times
  its grip at 0.197, turning in at full lock from 30 m/s at 0.585, lock to lock at 30 m/s runs
  at 0.426 (90th percentile). A held full lock at 30 m/s settles at 0.15 with a slip angle of
  0.005 rad: the lock is 0.052 rad there and the tyres hold. The band is 0.2 to 0.8;
  `TestADrivenCarIsHeard` drives a `Car` and reads the `Soundtrack`, and failed on the old band
  (0.188 against 0.30). glisteel 122c581. Found while measuring: brake 1 with full lock from
  25 m/s lifts the inside wheels within 0.3 s and rolls the car at 1.3 s on flat tarmac; not
  handled here.
- M17's rollover (brake or handbrake with the lock rolled glisteel's Jolt car): the tyres'
  sideways grip, 0.9 of `grip` (1.71 g), was above the 1.52 g the car tips at, and full lock
  from 20 to 27.5 m/s asks about 1.4 g of the car's weight with downforce counted. Inputs
  at once rolled it in that band in 29 of 1,350 drives (10 to 60 m/s, brake 0 to 1, lock 0.5
  to 1, handbrake on and off, at once or wound on); omi_physics' car leant at most 1.5
  degrees. `CarSpec.lateral_friction` is 0.75 (1.43 g): most lean 1.4 degrees over the
  same grid; 0.8 rolls, and at 0.7 the autopilot put 6 m off the line does not settle.
  Launch and braking are unchanged; cornering at steer 0.5, 0.3 and 1.0 is 0.691, 0.548
  and 1.800 g against omi's 0.720, 0.546 and 1.837. Anti-roll bars made it worse and a
  0.15 m lower centre of mass cost the launch 10%; no pyjoltphysics change (the outside
  wheels brake with 4 kN of 19 kN of grip, so a shared tyre budget leaves 98% of their
  sideways grip). glisteel's `plans/CAR-ROLLS-OVER.md` has the table. glisteel a102fca.
- L15 (hill-runner's chase tolerance widened with no reason): the wander test measures
  0.0055 m at most over all 2,400 frames, first 2 s included, so the original 0.05 bound over
  every frame is restored. The look point's distance holds to 0.1 m, with the 0.08 m lead the
  follow camera's glide leaves at 10 m/s stated in the test. hill-runner 798db19.
- L16 (twig-bb "nothing is dynamic", corpse cost): the docstrings and README say the corpses'
  ragdolls are the dynamic bodies, with the cost measured at load 0.2: six corpses 2.8 to
  3.3 ms a frame in the first quarter second, 0.9 ms to 1 s, 0.6 ms from 1 to 5 s. The bones do
  sleep, 2 to 4.5 s after the fall, and the physics then costs what the empty world does. The
  1.37 ms suspicion was the settling time plus `RagdollFigure.draw` polling 19 bones' sleep each
  frame (20 to 35 us a corpse). The figure now listens for its bones' `wake` events after
  `knock_down`, so six settled corpses cost 0.02 ms a frame against 0.12 before. 2c49d4a8,
  twig-bb aa3fa3f. Inline stays: the characters step in the frame for determinism, and half the
  falling cost is the skinning on the render thread, which a worker thread would not move.
- L17 (stale omi references): marble-demo 0f14fab, hill-runner 798db19, glisteel 122c581,
  twig-bb aa3fa3f. The twig-bb step lurch was measured on the Jolt character: walking onto an
  18-unit step no frame moves more than the 12.7 cm due, so the README item is removed and
  PROJECT-PLAN B1 is closed with the numbers.
- L18 (marble-demo pose reads per mechanism): `BoardScene.shared_poses`, entered by
  `BuildResult.before_step`, makes one `physics.poses` read for all of a step's mechanisms; a
  `check_scaling` count test holds it (2 against 8 mechanisms read 1 and 1). Outside it every
  call reads the world, since a teleport with the clock standing must be seen. marble-demo
  f1159fe, 41c0365.
- L19 (no orientation or matrix on Body): `Body.orientation` (x, y, z, w) and `Body.matrix`
  (4x4 row-vector), docs/physics.rst. c685ba6e. glisteel's `CarVehicle` reads them (d01b40c).
  twig-bb's corpse placement converts a scene Transform's values, not a Body's, and now uses
  pyvrml97's `transformMatrix` (3646c6d).
- L36 (twig-bb prose): projectiles' bold leaders and "wants", the listener test's perception,
  test_viewer's history and "can honestly do" are rewritten. twig-bb 4b73ee0. The ai-isms scan
  over twig-bb, hill-runner, marble-demo and glisteel against origin/develop finds 0.
- Suites with deprecation warnings as errors: twig-bb 2,424 passed, 1 skipped (Crunch samples
  absent); glisteel 1,672 passed, 1 xfailed; hill-runner 662 passed, 1 skipped (no VP9 encoder);
  marble-demo 946 passed, 6 xfailed; marble-editor 165 passed; openglcontext-forest 86 passed.
  Engine unit suite on the branch: 18,356 passed, 56 skipped; serial 29 passed, 1 skipped.
- C1 (restore_state of a damaged state overflowed a stack array in Jolt): `save_state` writes a
  32-byte header (`PJST`, format 1, `JPH_VERSION_ID`, payload length, FNV-1a 64 of the payload)
  and `restore_state` raises `ValueError` before Jolt reads bytes that do not match it; a
  state Jolt reads short or with bytes left over is rejected and the state before it put back.
  The review's fuzzer is `test_saved_state.py`, 300 corruptions on each of seeds 1 to 3, all
  refused. pyjoltphysics 9621779.
- C2 (two vehicles on one chassis): the second is rejected, so removing the chassis removes the
  one vehicle it carries. pyjoltphysics 9621779.
- C3, H5 (remove_ragdolls left vehicles, drag, tracks and pins on the bones): `remove_bodies` and
  `remove_ragdolls` share `WorldCore::leave`, which takes vehicles, soft bodies and pins, joints,
  drag, tracks, pairs and layer uses with the bodies. Tests in `test_body_removal.py`, with new
  bodies stepped on the freed slots. pyjoltphysics 9621779.
- C4 (a soft body as chassis broke Jolt's island builder): a chassis is a dynamic rigid body,
  and a joint to a soft body is rejected too. pyjoltphysics 9621779.
- C5 (the 65536th collision layer threw on the world thread and aborted the process): layers
  are counted by their users (bodies, character proxies, vehicle wheel casters) and freed with
  the last; an add whose new keys do not fit raises `ValueError` on the caller's thread, and a
  row or change left with no layer is rejected. Each batch's apply is wrapped (a throw rejects
  the batch, `World.last_rejection`), and the world thread's tick (a throw stops the world with
  a `WorldError`). The review's 70 batches of 1000 masks run with 1000 layers held at once.
  pyjoltphysics 9621779.
- C6 (a World dropped its Python objects with no thread state): `~World` clears them, stops the
  thread, then clears them again attached; once cleared, a callback's exception is logged and
  not kept. The MaterialTable holds its world through a `WeakMethod`, so `del world` frees it
  on the spot (gc disabled in the test). The review's `gc_on_world_thread` runs in the suite as
  a subprocess, under both sanitizer builds. Run 6 at a time on the free-threaded ASan build
  it still faulted (SEGV in `LOAD_GLOBAL_BUILTIN`, after "missing 1 required positional
  argument" errors): the free-threaded collector finds the cycle with every thread stopped,
  restarts them, then clears it, and the world thread called a callable already cleared. The
  World's `tp_finalize` (`WorldCore::retire_python`) runs before anything is cleared and
  admits no further callback call, waiting for those running on other threads; 150 runs then
  clean, and the test asserts no cleared callable is called. pyjoltphysics 9621779, 4da21ac.
- H1 (stop racing run_ticks deadlocked): `stop` sets the flag and joins under the join lock,
  and `run_ticks` sets lockstep after it joins a thread, so a callback of the joined thread
  calling `start` cannot leave it waiting. A third case of the same kind was found by the new
  contact-filter test hanging 1 run in 8 at the end of the suite, and fixed so. 20000 stops
  against a run_ticks loop in a subprocess. pyjoltphysics 9621779.
- H2 (blocking calls from callbacks hung): a thread-local names the world whose contact filter
  a thread runs; `save_state`, `flush`, `wait_tick`, `run_ticks` and queries from it raise
  `RuntimeError`, `stop` and `start` from it join nothing. `save_state` from a step callback
  reads under the shared lock the tick holds. pyjoltphysics 9621779.
- H3 (start while run_ticks waited): `start` ends the lockstep wait and `run_ticks` raises
  `WorldStopped`. pyjoltphysics 9621779.
- H4, M1, L1, L3 (unbounded or narrowing values): values stored as floats are checked against
  the float range, masses and inertias against a finite inverse, `tick_hz` is 1 to 10000, `threads` 1 to
  256 (100000 job threads crashed an ASan worker; 4da21ac),
  `temp_allocator_mb` 0 to 4095 (the size is computed in 64 bits), soft body iterations 1 to
  1000, and group, mask, filter, material, flag, kind and wheel-index doubles are checked whole
  and in range before any conversion. A body whose pose or velocity stops being finite in a
  step stops the world naming it. The sanitizer build adds `-fsanitize=float-cast-overflow`,
  under which the suite runs clean. `test_hostile_inputs.py` holds 79 of the review's fuzz
  cases and 6 extreme world settings, each refused or leaving every pose finite. pyjoltphysics 9621779.
- H6 (a world collected on its own thread during the atexit join deadlocked exit): `shutdown`
  from one of the world's callbacks asks for the stop and returns without the join lock, and
  the logger is looked up when the module loads. pyjoltphysics 9621779.
- M12 (downforce kept a parked car awake): the chassis forces pass `EActivation::DontActivate`
  and downforce stops below 1 mm/s. `test_a_parked_car_with_downforce_falls_asleep`.
  pyjoltphysics 9621779.
- Left: `test_a_forked_child_cannot_use_its_parents_world` timed out (60 s) twice in about 450
  runs of the lifecycle, thread-safety and callback files repeated 8 times on 8 workers on the
  free-threaded ASan build: the forked child wrote nothing and the parent waited in `waitpid`.
  The same script with progress lines ran clean 520 times, 8 at a time, with and without other
  ASan suites beside it; the GIL and free-threaded release builds and the GIL ASan build never
  showed it. ptrace is blocked in this container, so the child's native stack could not be
  read. The likely place is a lock held by another parent thread at the fork (the sanitizer
  runtime's thread registry when the child starts Jolt's job threads); unconfirmed. Next: a
  core of the hung child on a machine that allows ptrace.
- L2 (uids wrapped silently): `_uids` and `BodyBatch`'s integer columns raise `ValueError` for a
  value their type cannot hold. pyjoltphysics 9621779.
