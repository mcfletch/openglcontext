# The suite hangs on the cubemap skybox test

**Status: fixed, 2026-09-13.** The mechanism is understood and closed, and the
suite can no longer sit on a hang: what follows is the original evidence, what
it turned out to mean, and what landed.

A `tools/preflight.py --rebuild-env` run started on 2026-09-12 at 22:06 sat for
just under twenty-four hours without finishing. It was not slow; it was
deadlocked. Killed on 2026-09-13 at 22:00.

## What was seen

The run's `pytest -q`, with a working directory of `openglcontext`:

| | |
|---|---|
| Started | 22:06, last file activity **22:16** |
| Then | 23 h 45 m with no file activity at all |
| CPU | 74 minutes total, none of it after 22:16 |
| Threads | **91** |
| Where they were | the main thread and every worker in `futex_do_wait`; three in `ep_poll` |

Nothing was waiting on I/O, a driver or a display. Ninety-one threads were
waiting on each other.

**The open file descriptors name the test.** Still held at the end, all of them
already unlinked as pytest tore its temporary directory down:

```
faces_LF.jpg  faces_UP.jpg  faces_DN.jpg  faces_FR.jpg  faces_BK.jpg
```

That is `tests/unit/test_viewer_environment.py::TestTheSkyTheViewerPutsUp::test_a_complete_face_set_becomes_the_skybox`, whose `_faces()` helper writes a
one-pixel JPEG per cube face into `tmp_path` and hands the prefix to
`cube_background()`.

**Five of the six, and it is the right five.** `_CUBE_FACES` in
`OpenGLContext/passes/ibl.py` runs `RT, LF, UP, DN, FR, BK`, and RT is the one
*not* left open. So the first face was read to completion and the other five
were opened and never closed — a loader that got through one and then stopped,
rather than one that never started.

## What it was

Building a `CubeBackground` sets six `url` fields. `ImageURLField.__set__`
started **one thread per url**, and the thread's first acts were *imports*:
`OpenGLContext.loaders.loader` (and, underneath it, `urllib.request`, `http`,
`ssl`), and then, inside `Image.open`, PIL's per-format plugin modules. Six
threads therefore raced each other and the main thread through CPython's import
machinery.

That state reproduces on every run of that one test file. Armed with a
session-end thread dump, 25 of 25 runs of

```bash
pytest -q tests/unit/test_viewer_environment.py
```

ended with six threads still alive, each inside `PIL.Image.preinit`, each
blocked in `importlib._bootstrap` (`_get_module_lock`, `_lock_unlock_module`,
`_ImportLockContext.__enter__`) — and each holding the face file it had opened
and not yet decoded. That is the fingerprint the hang left behind, down to the
one face that got through while five did not.

**Why it could not be interrupted, and why the run sat for a day.** The global
import lock is taken with the GIL released, and `_PyImport_AcquireLock` does not
poll for signals. A Python signal handler runs only when the main thread next
executes bytecode, which a thread waiting there never does. So:

- `pytest-timeout` was already configured at `timeout = 300`, and could do
  nothing: its default *signal* method raises out of a `SIGALRM` handler;
- `SIGTERM` was ignored for the same reason, and `SIGKILL` was needed.

Both halves were checked directly, with a test that parks a worker inside a
meta-path finder so the main thread's next import blocks on the global import
lock: under `--timeout-method=signal` the run had to be killed from outside,
and under `--timeout-method=thread` it printed every thread's stack and exited
non-zero in ten seconds.

**Why a thread that imports is where the cycle closes.** A meta-path finder's
`find_spec` is called *holding* the global import lock, so a finder that itself
imports holds that lock while acquiring a module lock — and a second thread
holding that module lock needs the global lock to finish. PyOpenGL's
`OpenGL/_rawfinder._DeferredRawFinder.find_spec` is such a finder, and pytest's
assertion rewriter is on the same `sys.meta_path`. A thread that never enters
the import machinery cannot be one of the two sides.

The 91 threads and the leaked file descriptors were the same defect seen from
another angle: a thread per url, never joined, each holding a lazily-opened PIL
image — which keeps its file open until something asks for its pixels.

## What landed

**`OpenGLContext/loaders/background.py`** — the engine's loader pool, with the
rule stated in the module docstring:

- `load_in_background(description, work, *args, prepare=None)` runs `work` on a
  pool of `WORKERS` (4) daemon threads, started as work arrives. `LoadPool` is
  the class, for a caller wanting a pool of its own; `shutdown()` stops one.
- `prepare` runs **on the submitting thread**, once per pool, and is where a
  load's first-use imports are made.
- `wait_for_idle(timeout)` and `pending()` are how a test or a tool waits for a
  scene to be complete, instead of joining threads by name.
- Work that raises is logged against the url it was given; the worker lives on.

**Every url field that loads in the background goes through it**, each with a
`prepare` naming what its worker will reach:

| field | prepares |
|---|---|
| `imagetexture.ImageURLField` | the loader, and `PIL.Image.init()` |
| `inline.InlineURLField` | the loader and `Loader.loadHandlers()` (the format parsers) |
| `shaders.ShaderURLField` | the loader |
| `hdrbackground.HDRURLField` | `loaders.hdr`, `loaders.resolver`, `passes.ibl` |

**Two further defects the same evidence named:**

- `ImageTexture.loadBackground` now decodes the image (`image.load()`) and
  closes the stream, so a texture holds pixels rather than an open file — and
  the decode happens on the loader thread rather than on whichever thread first
  draws it.
- `ShaderURLField.loadBackground` read its url fragments on a thread apiece and
  joined them; it reads them in order on its one worker now. `subLoad` answers
  with the bytes rather than writing into a list by index.

**`pyproject.toml`: `timeout_method = "thread"`.** `timeout = 300` was already
there and was never the problem — the method was. The thread method ends the
session rather than failing one test, which is the right trade for a suite
whose hangs are of this kind. The value stays at 300: the slowest test that
runs to completion takes 24.4 s, and the subprocess script runner's own ceiling
is 120 s.

**Tests.** `tests/unit/test_background_loading.py`: the pool (bounded workers,
preparation on the submitting thread and once only, a failure that does not
take the worker down, waits that expire), plus the three rules —

- a background image load makes no import of its own (a meta-path watcher
  records which thread each first-use import came from; with the preparation
  blunted it names 16 modules, including `_ssl` and `urllib.request`);
- every url field loads on the shared pool rather than a thread of its own;
- a finished image load leaves no file open.

`tests/unit/test_background_load_threads.py` keeps its subject — a load never
holds the interpreter open — against the pool's daemons.

**Documentation.** `docs/structure.html` gains *Loading without stopping the
frame* (the pool, `wait_for_idle`, and why `prepare` runs where it does);
`docs/testing.html` gains *A test that stops answering* (the timeout and why
the method matters); `docs/vrml97.html`'s note about worker threads now points
at both.

## Still open

- **The same pattern lives in `loaders/tiles3d/loadmanager.py` and
  `viewer/asyncscene.py`**, whose workers also reach formats and parsers they
  may be the first to import. Neither was implicated by this hang and neither
  is converted; both would want a `prepare` of the same shape.
- **PyOpenGL's `_rawfinder`** imports from inside `find_spec`, which is the
  half of the cycle that lives below OpenGLContext. The window is the first
  `OpenGL.raw.*` import in a process, so closing our half closes the case for
  this suite, but it is a hazard in its own right for any program that loads on
  threads.
- **`ptrace_scope` is still 1** in this container and cannot be changed:
  `/proc/sys/kernel/yama/ptrace_scope` is on a read-only filesystem, so
  `sysctl` fails whether or not sudo is available, and `py-spy dump` and `gdb`
  still cannot attach to a live hang. The thread-method timeout is what stands
  in for it: it prints every thread's stack on the way out.
- **The full deadlock was not reproduced.** One full suite run before the
  change (610 s, 9997 passed) and part of a second found nothing; what was
  reproduced, 25 times out of 25, is the state it left behind.
