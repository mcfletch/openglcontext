# Free-threaded CPython support

Status: surveyed 2026-10-23, nothing implemented. Target interpreter is CPython 3.14t
(free-threaded, supported since 3.14). 3.13t is checked once per project and not gated.

Scope: the engine (openglcontext and its Qt and editor backends), the extensions it
loads (omi_physics, omi_audio, opengl_extrusions, opengl_decimate, opengl_basisu,
simpleparse, pyvrml97 and its accelerators, PyOpenGL and its accelerators) and the pure
Python packages under them (pydispatcher, ttfquery). The C dispatch layer inside
PyOpenGL has its own design note,
[pyopengl/plans/FREE-THREADING.md](../../pyopengl/plans/FREE-THREADING.md), which this
plan orders and corrects (see "Corrections").

## What "free-threading capable" means

A project reaches a level only after the one below it.

| Level | Meaning | Checked by |
|---|---|---|
| 0 | Every module imports on 3.14t with the GIL still off | import gate, session gate |
| 1 | The project's existing suite passes on 3.14t, serially | the suite in a `py314t` cell |
| 2 | Each documented sharing rule holds under concurrent calls | thread tests, run-parallel pass |
| 3 | Independent instances scale across cores; C code is TSan-clean | scaling tests, TSan run |

The engine is level 2 when its loader threads, physics thread and audio thread run
beside the render thread with the GIL off. Level 3 is the goal for the extensions that
already release the GIL (omi_physics, opengl_decimate, opengl_basisu).

## Survey

### GIL state of every extension today

Built on 3.14t from a copy of the tracked sources, each module imported alone in a
fresh interpreter with `PYTHON_GIL` unset.

| Module | GIL after import | Cause |
|---|---|---|
| numpy, Pillow, glfw, fontTools, pygltflib, DracoPy, scipy, miniaudio, opuslib | off | upstream wheels declare it |
| omi_audio, ttfquery, bare `OpenGL` | off | pure Python |
| `OpenGL_accelerate.dispatch` | declares compatible | `Py_MOD_GIL_NOT_USED` in `pygl_runtime.c:3058` |
| `OpenGL_accelerate` wrapper, formathandler, arraydatatype, errorchecker, vbo, nones_formathandler, latebind, buffers_formathandler, numpy_formathandler | ON | Cython default is `Py_MOD_GIL_USED` |
| `OpenGL.GL` | ON | imports the nine above |
| simpleparse `mxTextTools` | ON | single-phase init, no slot |
| pyvrml97 `fieldaccel2`, `frustcullaccel`, `tmatrixaccel` | ON | Cython default |
| omi_physics `_solver_native`, `_collide_native` | ON | Cython default |
| opengl_extrusions `_predicates_native` | ON | Cython default |
| opengl_decimate `_reduce_native` | ON | Cython default |
| opengl_basisu `_transcoder` | ON | Cython default |

Importing `OpenGLContext` therefore turns the GIL on today through four independent
routes. Fixing one leaves the others in place, so the import gate runs per module and
names the offender.

Measured on omi_physics: `# cython: freethreading_compatible=True` at the top of a
`.pyx` keeps the GIL off, and the existing suite then passes on 3.14t with
`PYTHON_GIL=0` (1033 passed, 3 xfailed, 160 s). The directive needs Cython 3.1 or
newer: 3.0.12 rejects it as an unknown directive, 3.1.0 accepts it. All four small
native projects pin `Cython>=3.0` and the accelerate builds allow `>=0.28`.

### Third-party wheels on 3.14t

| Package | 3.14t | Effect |
|---|---|---|
| numpy, Pillow, glfw, fonttools, pygltflib, DracoPy, opuslib-next-bundled, hypothesis, pytest, pytest-timeout, pytest-xdist, pytest-run-parallel, psutil, scipy, cython, mypy, ruff | wheel | none |
| miniaudio | builds from source, GIL stays off | none |
| pygame-ce, OpenEXR, xatlas | no wheel found | each degrades cleanly when absent (window backend skipped, `.exr` raises naming the extra, rewrap tool skips) |
| PySide6-Essentials, shiboken6 | no cp314t wheel, no sdist | openglcontext-qt cannot be installed; the root environment leaves it out through a dependency group (phase 0) |
| wxPython, tkinter | not checked | wx and Tk backends unverified |

The supported free-threaded configuration is the GLFW backend (the one the test suite
drives). Other backends work where their toolkit ships a free-threaded build.

### Behaviour that differs on 3.14t

Measured with `sys.flags`:

- `thread_inherit_context` is 1, so a thread started inside a ContextVar scope sees
  that scope's values. On the GIL build it sees defaults. pyvrml97's event cascade
  (`vrml/event.py`) is a ContextVar, so a loader thread started during a cascade
  inherits that cascade's visited-node table. numpy's error state is also
  context-local.
- `context_aware_warnings` is 1, so `warnings.catch_warnings` and `filterwarnings`
  apply per context. pytest's `filterwarnings = error` in several projects interacts
  with threads started by tests.

### Shared-state hazards

Each item came from reading the code and is a candidate until a failing test shows it.
Tags: H is a hazard on its own terms, S is a hazard only if the sharing rule below is
broken by the caller, B is a fix needed for correctness on every build.

omi_physics
- H `ThreadedSimulation.start()` checks `_thread` without a lock, so two starts spawn two threads (`threaded.py:106`).
- H `cookery._CACHE` keyed by `id(points)`, get then set (`cookery.py:14,29,48`).
- H `character._STATIC_PROXIES` is a `WeakKeyDictionary` of dicts with get, build, set (`character.py:43,51,410`).
- H `DEFAULT_MATERIAL`, `DEFAULT_FILTER` are non-frozen dataclasses returned to every world (`model.py:295`).
- S native kernels write the world's own arrays in place (`solver.py:419`); two threads stepping one world race.
- The three `nogil` blocks already run concurrently across worlds under the GIL build.

omi_audio (pure Python)
- H `Voice.release()` from the audio thread can release a slot the control thread has already re-claimed and reset (`mixer.py:143,376,489`).
- H `backend()` and `_libopus()` set `_attempted` before the import finishes, so a second thread gets `None` and the engine falls back to a silent device (`_backend.py:31`, `_opus.py:99`).
- S `Mixer.mix` writes scratch arrays held on `self`; two threads inside `mix` corrupt each other.
- S `Graph.compile` detaches removed nodes while the audio thread may still render the old plan.

opengl_extrusions
- Stateless native functions. Only `Triangulation` objects hold mutable state (S).

opengl_decimate
- S one `Reducer` per reduction, built inside `reduce_mesh`, so the public API cannot share one. Its `run` releases the GIL.
- H `native.ACCELERATED` is rewritten by tests at run time and read per call.

opengl_basisu
- B `basisu_transcoder_init` guards its table build with a plain `bool` (`basisu_transcoder.cpp:2108`). It runs once at import under the import lock, so it is fine unless a second interpreter or direct caller reaches it.
- H `KTX2File` and `BasisFile` keep decode state per object (`m_def_transcoder_state`, `m_def_state`), written during `transcode` with the GIL released. `Texture` holds a lock, but `_transcoder.KTX2File` is exported and unlocked.

pydispatcher
- H `connect` is check-then-act on five structures (`dispatcher.py:185-222`), and its presence index is updated in a second step.
- H `send` iterates the stored receiver list while receivers connect and disconnect (`dispatcher.py:286-354`). This happens on one thread too.
- H weakref callbacks `_removeReceiver` and `_removeSender` run on any thread and delete from the same dicts (`:426-492`).
- H `BoundMethodWeakref.__new__` registers an instance before `__init__` runs, and `__init__` runs again on every `safeRef` of a shared instance (`saferef.py:97`).

ttfquery
- H `get_registry()` publishes an empty `Registry` before the scan fills it (`scriptregistry.py:34`).
- H `Registry.register`, `matchName` and `load(clearFirst=1)` use five dicts with no lock (`ttffiles.py:80,141,251,325`).
- H `save` writes a fixed temp name (`ttffiles.py:315`).

simpleparse
- H one `Parser` is not safe for concurrent `parse`: `Generator.buildParser` reassigns `parserList`, `terminalParserCache` and `methodSource` on every call (`generator.py:141`). Measured on the GIL build: 8 threads, 200 parses each, `IndexError`.
- H constructing parsers races on the module singleton `SPGenerator`. Measured on the GIL build: 110 errors in 400 constructions across 8 threads.
- H `common.*` library generators are mutated by every parse that uses them (`objectgenerator.py:602`), and `Group.terminal` and `Name.terminal` store an in-progress marker that another thread reads as the answer.
- H TagTable cache: `GetItem` returns a borrowed `PyDict_GetItem` result and drops the lock before the caller increments it, while `SetItem` can `PyDict_Clear` (`mxTextTools.c:115-160,2698`). Use-after-free without the GIL.
- H `Parser.parse` builds a new definition tuple per call and the cache key is its address, so the cache fills to 100 entries and clears. The cache also never hits.
- H `PyList_GetItem` and `PyList_GET_ITEM` borrow from the generator's live `parserList` (`recursecommands.h:49`).
- B `PyInit_mxTextTools` uses single-phase init with `m_size = -1`; the GIL slot needs `PyUnstable_Module_SetGIL` or a move to multi-phase init (`mxTextTools.c:5104`).
- H `Py_AtExit` cleanup frees the cache lock without taking it.
- Build: no free-threaded cibuildwheel selector and no test job in the workflow.

PyOpenGL (pure Python and accelerate)
- H `contextdata.setValue` get-or-create: two threads storing under one context lose a container, and a lost client-array reference is a dangling pointer in the driver (`contextdata.py:44-78`; `retain` calls it on every `glVertexPointer`-family call).
- H `_dispatch.install()` sets `ACTIVE` last, so a second thread double-wraps `wrapper.wrapper` and configures twice (`_dispatch/__init__.py:268-333`). `platform._c_dispatch` and `_declarations._c_source` have the same shape.
- H `lazy_property` can load `PLATFORM.GL` twice, and `wrapContextCheck` then compares against the other `CDLL` (`baseplatform.py:166`).
- H `FormatHandler.loadPlugin` sets `loaded = True` before registering the handler (`formathandler.py:46`).
- H `numbers.registerEquivalent` rebinds `TARGET_TYPE_TUPLE` (`arrays/numbers.py:86`).
- H `vbo.pyx` mixes `Py_XDECREF` and `Py_XINCREF` with Cython's own reference handling in `c_set_array` and `VBOOffset`; two `set_array` calls on one VBO double-decrement (`vbo.pyx:121`).
- H `_Alternate.finalise` caches the winner for the first caller's context (`extensions.py:379`); `LateBind` finalises twice on a race, which is idempotent for `Wrapper` only.
- H ctypes path: `_ctypes_current_context` and `LinuxPlatform._active_api` are process-wide where the C path is per thread; `_ErrorChecker.suspended` is shared (the C layer made it thread-local).
- S `numpy_formathandler.array_descr` loads a borrowed descr before incrementing it; `buffers_formathandler.c_dataPointer` keeps a pointer past its memoryview.
- `Wrapper.__call__`, `HandlerRegistry.c_lookup` and the format handlers hold no state beyond what is listed. Whether registration is import-time by contract is not stated anywhere in the repo.

pyvrml97
- H `cache.CACHE` is a process-wide dict keyed by `id(client)`, mutated at run time by every path-matrix request (`cache.py:83,141`, `vrml97/nodepath.py:84-126`); holder creation, `builtOn` weak lists and weakref cleaners are unlocked.
- H `dispatcher.connect` runs at render time through `Cache.depend`, and again for every `_MFNode` assignment (`node.py:659`).
- H `protofunctions._declarations += 1` and `getFields` iterate a class `__dict__` while `addField` writes it (`protofunctions.py:120`).
- H `x3d/readers/classic.py:98` holds one module-wide `Parser`; the engine's loader pool reaches it through `Inline` (`loaders/x3d.py:124`).
- H `RootScenegraphNode.fset` registers DEF names into a per-scene dict while another thread may call `getDEF`.
- H `fieldaccel2.getDefault` writes the node's `__dict__` on read, so two readers of an unset field build two defaults. The pure Python field has the same shape (`field.py:107`).
- The three accelerators hold no module state; `frustcullaccel` returns a view into the caller's array.

openglcontext
- H loader-pool workers mutate scenegraph nodes after construction: `ImageTexture.setImage`, `Inline`, `InlineGeometry`, shader `source`, `X3DShader` (`imagetexture.py:407`, `inline.py:199`, `inlinegeometry.py:110`, `shaders.py:421`). Those assignments fire observers on the worker.
- H `SGObserver` handlers connect with `sender=Any` and mutate `paths` and `nodePaths` on whichever thread sends; only `CHILDREN_CHANGE_SIGNAL` is queued to the render thread (`passes/_flat.py:222-405`).
- H `RenderQueue.before_run` appends without the lock that guards `_calls` (`events/renderqueue.py:60`).
- H the font registry scan is an unlocked check, so two first callers each scan (`contextconfig.py:75`).
- S one `contextThread`, one `contextLock` and `Context.currentContext` as class attributes (`context.py:134,135,325`): the engine has one render thread per process.
- S `triggerRedraw` takes `contextLock`, so a loader worker blocks for the length of a frame (`context.py:1821`). A stall, not corruption.
- S `functools.cache` over a mutable return: `x3dparticles._still`, `viewer/library.screenshot_urls`. `pillowtext._font` shares a `FreeTypeFont` between callers; whether FreeType tolerates that is unchecked.
- B 150 modules hold module-level containers. About 40 were read; the rest are unread. A scan (phase 10) classifies all of them.

## Rules

1. Sharing contract. Independent instances may be used from different threads at the
   same time. Module-level registries, caches and lazily initialised singletons are safe
   to race. One mutable object (a `PhysicsWorld`, a `Parser`, a `Reducer`, a `VBO`, a
   `Mixer`) has one owner at a time unless its docstring says otherwise. numpy makes the
   same promise. Each project states its rules in its documentation and the thread tests
   hold them.
2. Locks are paid for only where a lock is needed. Process-wide structures that
   unrelated callers reach (the dispatcher tables, `vrml.cache.CACHE`, the font
   registry, the format-handler registry) get a lock. A hot path takes no lock where a
   copy-on-write snapshot or an idempotent publish does the job.
3. Locking only on free-threaded builds. A GIL build keeps today's code path, so users
   of 3.10 to 3.14 pay nothing and see no change. Section "Locks only when needed"
   gives the mechanism.
4. The engine confines scenegraph mutation to one thread. Loader and scene-load threads
   build detached data and hand it to the render thread with `RenderQueue.call`.
   Making the dispatcher, cache and `SGObserver` safe for any thread to mutate an
   attached graph would put a lock on every field set in the engine. `Inline`,
   `ImageTexture`, `InlineGeometry` and the shader nodes move to the handoff. A
   receiver that must run on one thread (`SGObserver`'s handlers) says so when it
   connects, and the dispatcher delivers to it across threads (see "Cross-thread
   sends").
5. GL stays on the thread that owns the context. Free threading changes what the other
   threads can do while it draws, and does not change that.
6. A module that declares itself free-threaded has an owner for each piece of state it
   holds. The declaration (`Py_MOD_GIL_NOT_USED`) goes in last, after the tests for the
   state in that module pass.

### Locks only when needed

Whether the GIL is on is decided once, at import:

```python
def locking_needed():
    gil_enabled = getattr(sys, '_is_gil_enabled', None)
    return gil_enabled is not None and not gil_enabled()
```

On a GIL build `_is_gil_enabled` is absent or true, so the answer is no. On a
free-threaded build the answer is yes while the GIL is off. If an extension that does
not declare itself compatible later turns the GIL on, the process keeps the locks it
already chose, which cost a little and break nothing. If the GIL is already on at
import, nothing in CPython turns it off again, so skipping the locks matches what the
code does today.

pydispatcher applies it as follows, and the other packages copy the three-line check
rather than import a shared one (pydispatcher has no dependencies and stays that way):

- GIL path: the current in-place list edits, no lock objects touched.
- Free-threaded path: one `RLock` around the mutation of `connections`, `senders`,
  `sendersBack` and `_receiverIndex`; receiver lists are replaced, not edited, so `send`
  iterates a snapshot and takes no lock.
- `send` costs the same on both paths: one attribute read of the current list.
- A test hook `use_locking(flag)` forces either path before the first `connect`, so the
  locked path runs on every interpreter in the matrix and the unlocked path runs on
  3.14t as well. Environment variables are not read at import.
- GIL builds keep their present check-then-act windows. These are rare there because
  the GIL switches threads on a 5 ms interval, and they are unchanged.

### Cross-thread sends

A signal crosses threads in two ways, and pydispatcher handles each.

Structural safety. A receiver connected on one thread, a send on a second and a weakref
callback on a third all touch the same tables. The free-threaded path above covers it:
mutation under the lock, `send` over a snapshot.

Delivery on a chosen thread. A receiver that touches state one thread owns cannot run
inline on whichever thread sent. `SGObserver`'s handlers mutate the render thread's
path tables, and a loader thread's `Inline` fires them today. The engine handles one
signal by hand: `onChildrenChange` queues under `_pendingLock` and `walkPending`
drains the queue on the render thread (`passes/_flat.py:346,384-405`). The dispatcher
takes over the general form:

- A receiver connects with a delivery:
  `dispatcher.connect(receiver, signal, sender, deliver=render_queue.call)`. `deliver`
  is any callable that takes a function and arguments and arranges to run it on the
  receiver's thread. pydispatcher knows nothing else about threads and stays free of
  dependencies. OpenGLContext passes `RenderQueue.call`.
- The connection records the connecting thread (`threading.get_ident()`). A `send`
  from that thread calls the receiver inline, as now. A `send` from any other thread
  calls `deliver(receiver, signal=..., sender=..., **named)`. A single-threaded
  program always takes the inline branch.
- A receiver connected without `deliver` is called inline on the sending thread, as
  now. The feature costs one comparison per connection that has a delivery and nothing
  for the rest. It applies on every build, because a loader thread's send reaches a
  render-thread receiver on a GIL build as well.
- A deferred receiver adds nothing to the list `send` returns. A deferred call has no
  result to give.
- Deliveries from one thread to one target run in send order, because the queue is
  first in, first out. A send from the owning thread runs inline, so it can overtake
  earlier deferred calls still queued; the plan treats that as a documented rule.
- The receiver is held weakly until it runs, so one collected before delivery is
  dropped.
- An exception in a deferred receiver is logged on the target thread and does not
  reach the sender. An inline receiver's exception behaves as it does today.
- A deferred call runs in the target thread's ContextVar context. On 3.14t, where a
  new thread inherits its starter's context, this keeps a loader thread's event
  cascade out of the receiver.

Tests, in pydispatcher's suite with a hand-written queue as `deliver`: the receiver
runs on the target thread's identity; a send from the owning thread is inline and
synchronous; order within one sender thread is kept across 1000 sends; a collected
receiver is skipped; a raising receiver leaves the sender's call intact and is logged;
`send` returns only the inline results; connect, disconnect and send from three threads
together leave the tables consistent on both locking paths.

## Validation

### a) Free threading is enabled

Four checks, each independent, because `PYTHON_GIL=0` hides the failure being looked
for: with it set, importing a non-declaring extension leaves the GIL off with no
warning.

1. Interpreter. `sysconfig.get_config_var('Py_GIL_DISABLED') == 1` and
   `sys._is_gil_enabled() is False` at test start. A session fixture asserts both and
   fails the run when `PYTHON_GIL` or `-X gil` is set in the environment of a
   free-threaded cell.
2. Import gate, per extension. A test discovers every compiled module in the installed
   package (glob for `*.so`, `*.pyd`), imports each in a fresh subprocess with
   `-W error::RuntimeWarning` and `PYTHON_GIL` removed from the environment, and
   asserts the GIL is off afterwards. The warning text names the module and
   `-W error` turns it into an `ImportError`. Discovery means a new extension cannot be
   forgotten.
3. Session gate. `pytest_sessionfinish` asserts the GIL is still off, so a lazy import
   during the run that re-enables it fails the run.
4. Wheel gate. The cibuildwheel `test-command` for `cp313t` and `cp314t` wheels runs
   the import gate against the built wheel, and the release workflow asserts the wheel
   tag.

Red first: each project's import gate is committed failing, on the unmodified
extension, before the directive is added. That run is recorded in the commit message.

### b) The code is correct with it enabled

1. Serial suite on 3.14t passes with no test changed (level 1). Skips and xfails stay
   as they are, and a test that cannot run on 3.14t is a defect to fix.
2. Parity. Results on 3.14t equal results on 3.14 for the numerical suites. The
   existing digest tests in omi_physics and opengl_extrusions, the golden transcodes in
   opengl_basisu and the decimation sequences compare bit for bit.
3. Thread tests, one per hazard above, written to fail first. The harness:
   - start N threads on a `threading.Barrier` so they enter the call together;
   - set `sys.setswitchinterval(1e-6)`;
   - run M iterations each and compare every result to the single-thread result;
   - for first-use races (lazy singletons, registries, `install()`), run the body in a
     fresh subprocess, 20 times, because the race exists once per process.
4. Run-parallel pass. `pytest-run-parallel` (0.10, wheel exists) runs each test of the
   pure-compute suites in several threads at once. Tests that use fixtures,
   `monkeypatch` or process-wide switches carry `thread_unsafe` with a reason. GL tests
   are excluded; they share one window.
5. Repeat runs. The stress env runs the thread tests 20 times, and one failure is a
   failure. A race that passes 19 of 20 runs is not fixed.
6. Scaling (marker `serial`, since it measures wall time): 4 independent instances on 4
   threads reach at least 2.5 times the single-thread throughput on a machine with 4 or
   more cores, and the test skips below that. The figure is a starting value to adjust
   after the first measurement (opinion). A kernel that holds a hidden per-object or
   global lock fails here.
7. Thread Sanitizer, for code in C and C++: `pygl_runtime.c`, `mxTextTools.c`, the
   generated Cython code and the vendored basis_universal. It needs a CPython 3.14t
   built with `--disable-gil --with-thread-sanitizer` and numpy built against it. One
   build is cached under the workspace and used by phases 5, 7 and 8. This closes item
   13 of the dispatch review.
8. Engine checks (phase 10): a scene with an `Inline` and an `ImageTexture` loads on
   workers while frames render; every field set on an attached node happens on the
   render thread, asserted through `inContextThread`; physics on `ThreadedSimulation`
   and the audio device callback run for 10 s beside rendering with no exception, and
   the existing visual baselines match.
9. Overhead record (no gate): single-thread time on 3.14 and 3.14t for each project's
   benchmark, written into that project's CHANGELOG. 3.14t is slower on one thread and
   the user decides whether that matters.

## Procedure for each project

1. Environment. A `py314t` factor in `tox.ini` beside the existing ones, `{accel,fallback}`
   where both exist, and a row in the GitHub test workflow (`python-version: "3.14t"`).
   Interpreter missing is a failure, not a skip.
2. Baseline. Run the suite in the cell. Record failures and fix them first.
3. Red. Commit the import gate and the thread tests for the project's hazards, failing.
   Per the workspace rule, red is shown by stashing only the implementation files.
4. Green. Fix the hazards one by one, smallest first. Add `freethreading_compatible`
   (Cython) or the module slot (C) last, with `Cython>=3.1` in `[build-system]`.
5. Documentation. The sharing rules for the project's public classes go in its docs
   page, and the free-threaded status in its README and CHANGELOG.
6. Packaging. Add `cp313t-*` and `cp314t-*` to the wheel selectors, with the `enable`
   key the pinned cibuildwheel needs. The version it needs is checked against the
   cibuildwheel documentation at that point. Add the classifier
   `Programming Language :: Python :: Free Threading :: 3 - Stable`.
7. Gate. A `freethreaded` tox env (import gate, thread tests, run-parallel pass) listed
   under `checks` for the project in `tools/preflight.toml`, so
   `tools/preflight.py <project>` runs it. Where the interpreter is missing,
   preflight installs it with `uv python install 3.14t` or fails with that command.
8. Commit in the project's own repository. The version commit and the sibling floors
   stay with `tools/release.py`.

## Phases

Order follows the request (small extensions first) and the dependency graph. A phase
ends with its project at level 2 and its commit made.

0. Harness, with omi_physics as the pilot.
   - `.venv-ft`: a 3.14t environment from the root project. No environment marker can
     select it: `packaging.markers.default_environment()` returns the same values on
     3.14 and 3.14t, so PEP 508 cannot say "free-threaded". The root `pyproject.toml`
     instead moves `OpenGLContext-qt[dev]` into `[dependency-groups] qt`, with
     `[tool.uv] default-groups = ["qt"]` so a plain `uv sync` installs what it does
     now, and the free-threaded environment is
     `UV_PROJECT_ENVIRONMENT=.venv-ft uv sync --python 3.14t --no-group qt`.
     Checked on a copy of the root project: the lock resolves 142 packages, the 3.14t
     dry run installs 122, and the default dry run still installs PySide6. Without the
     group the dry run stops on `pyside6-essentials` and then `shiboken6`, the only two
     packages with neither a 3.14t wheel nor an sdist. `xatlas`, `pygame-ce` and
     `OpenEXR` have an sdist and build from source on install; one that fails to build
     joins the group.
   - The three gate helpers (interpreter check, import gate, barrier harness) written
     in `omi_physics/tests/`. Moved into `openglcontext-checks` as an opt-in pytest
     plugin when omi_audio needs them, since that package is standard library only and
     already in every project's story. Revisit if that package's scope argues against it.
   - `tools/preflight.py` learns to provision 3.14t.
1. omi_physics. Directive in both `.pyx`; lock `start()`; freeze `DEFAULT_MATERIAL`
   and `DEFAULT_FILTER`; make the two caches safe; state the one-owner rule for a
   world. Scaling test on 4 worlds. Cibuildwheel selectors.
2. omi_audio (pure Python). Fix the `release()` versus `mix()` race, the lazy backend
   singletons and `Graph.compile` detach. Test with the NullDevice calling `mix` on one
   thread while another plays and stops voices. Check miniaudio's callback thread under
   the free-threaded build.
3. opengl_extrusions. Directive; sharing rule for `Triangulation`; run-parallel pass
   (the suite is pure compute).
4. opengl_decimate. Directive; replace the `ACCELERATED` toggle with an argument the
   tests pass; scaling test across independent meshes.
5. opengl_basisu. Directive; make initialisation a `call_once` in the shim and call it
   at import under the import lock; take the per-object lock inside the Cython classes
   so `_transcoder.KTX2File` is safe to share; TSan run over the vendored C++.
6. pydispatcher and ttfquery. Locking per "Locks only when needed"; `saferef`
   construction made atomic; the `deliver` argument for cross-thread sends, with its
   tests; ttfquery registry published after the scan with a lock on writes and a unique
   temp file name.
7. simpleparse. Multi-phase init with the GIL slot; tag table cache returns a new
   reference under the lock (or is removed, since it never hits); build state moves out
   of the shared `Generator` into the call, or the build is serialised by a lock on
   free-threaded builds only; `SPGenerator` and the `common` generators locked at
   construction; add a test job to its workflow. TSan run.
8. PyOpenGL and its accelerate. Directive in the nine `.pyx` headers (not in
   `setup.py`, see "Corrections"). Then the dispatch-table items in the pyopengl note,
   `contextdata` with a lock on the write path, `install()` and `_load_c_dispatch`
   made once-only, `lazy_property` publishing under a lock, `loadPlugin` ordering,
   `vbo.pyx` reference counting, and the ctypes-path context state made thread-local
   to match the C layer. The `_Alternate` cache keys on context. TSan run over
   `pygl_runtime.c`. This is the largest phase and gets its own sub-plan on the
   first day.
9. pyvrml97 and its accelerators. Directive in the three `.pyx`; `CACHE` and holder
   structures locked on free-threaded builds; `protofunctions` declaration stamp under a
   lock; per-parse parser instances in the X3D reader; `getDefault` publish with
   `setdefault`; `dispatcher` use follows phase 6. Test that a loader thread started
   inside an event cascade does not see the cascade.
10. openglcontext, openglcontext-qt, openglcontext-editor, pyopengl-video. The
    confinement rule: move `Inline`, `ImageTexture`, `InlineGeometry` and shader loading
    to the `RenderQueue` handoff; `SGObserver` connects its handlers with render-thread
    delivery, which replaces the `_pendingLock` queue for `CHILDREN_CHANGE_SIGNAL`;
    lock `before_run`; the font registry scan; scan of
    the 150 module-level containers (a new OGC rule flags module state written from a
    function without a lock, in the style of the existing rules); the engine checks
    under validation b8. Qt remains outside the supported set until PySide6 ships a
    free-threaded wheel.
11. Release readiness. `tools/preflight.py` over every project on 3.14t, a
    `regression_check.py` pass in `.venv-ft`, and a documentation page for the engine's
    threading model linked from `documentation.html` and `structure.html`.

## Corrections to existing documents

- `pyopengl/plans/FREE-THREADING.md` step 4 puts `freethreading_compatible` in
  `compiler_directives` at `accelerate/setup.py:230`. That argument goes to setuptools'
  `Extension`, which warns and drops it; `Cython.Distutils.build_ext` reads only
  `ext.cython_directives`. The directive goes in each `.pyx` header, where
  `language_level=3` already lives. The comment at `pyopengl/pyproject.toml:173` says
  the keyword is honoured and is wrong for the same reason.
- That plan's status line says nothing has landed. The dispatch module's
  `Py_MOD_GIL_NOT_USED` landed in `118c1ca9`. The nine Cython modules did not.
- The same plan covers four dispatch-layer questions and none of the pure Python
  items in the survey above. Phase 8 adds them.
- `plans/2026-09-01-pyopengl-c-dispatch-review.md` 14.6 counts six accelerate modules
  that re-enable the GIL. The count is nine.

## Open decisions

- Where the shared test helpers live (phase 0 default: `openglcontext-checks`).
- Whether 3.13t gets a cell. It costs one tox factor per project and records what
  breaks; 3.14t is the only gated version.
- cibuildwheel's default for `cp314t` in the pinned versions (3.1 in three projects,
  3.4.1 in PyOpenGL, 2.23 in simpleparse, 4.2.0 in pyvrml97, 2.22 in omi_physics) is
  unverified. A project that builds `cp314t` wheels by default today ships a wheel that
  re-enables the GIL. Check the built artifact lists of the latest releases first.
- Cross-thread delivery: who decides inline or queued. The plan has the dispatcher
  record the connecting thread and call inline from it. The alternative is to call
  `deliver` for every send and let `RenderQueue.call` run inline on the render thread,
  which keeps threads out of pydispatcher and removes the overtaking rule.
- Cross-thread delivery: whether `send` reports deferred receivers (a count, or a
  sentinel per receiver) or says nothing.
- simpleparse state: move build state into the call, or serialise builds. The first
  changes a public class's internals; the second is a lock on free-threaded builds only.
- The scaling threshold in validation b6.
