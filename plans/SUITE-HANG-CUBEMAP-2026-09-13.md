# The suite hangs on the cubemap skybox test

**Status: open. Evidence gathered from a live hang and written down here
because the process has been killed and cannot be re-examined.**

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

## What it points at

Building the background node sets six URL fields, and a texture field setter
hands the load to OpenGLContext's image loading. Ninety-one threads on a suite
that should need none says a thread pool, and five files open mid-read says the
pool stopped while holding them. The question to answer first is which lock the
main thread is waiting on and who holds it — a pool worker waiting for the main
thread to do something is the shape that fits.

## What could not be done, and what would fix that

No Python traceback was obtainable from the live process:

- `/proc/sys/kernel/yama/ptrace_scope` is `1` in this container, so **py-spy and
  gdb both refuse to attach** from anything that is not the process's parent,
  and passwordless sudo is not available.
- `SIGABRT` would have made pytest's faulthandler dump all 91 stacks, but the
  process's stderr ran into a pipe owned by the session that started it, whose
  output had already gone.
- It ignored `SIGTERM` — a deadlocked interpreter cannot run a Python signal
  handler — and needed `SIGKILL`.

Two things would make the next one cost minutes instead of a day, and both are
worth doing before chasing the defect itself:

- [ ] `ptrace_scope=0` in the dev container, so `py-spy dump` answers a live
      hang.
- [ ] A timeout on this suite, so a hang is a red test rather than a run that
      sits. `pytest-timeout` is already a dependency of several projects here,
      and glisteel sets `timeout = 300` in its `pyproject.toml`.

## Reproducing it

It has been seen once, which per [CLAUDE.md](../../CLAUDE.md) is a reason to
chase it now rather than to wait for it again:

```bash
cd openglcontext
while ./.venv/bin/python -m pytest -q tests/unit/test_viewer_environment.py; do :; done
```

with `faulthandler.dump_traceback_later(120)` armed, which is what found the
`glfw.swap_buffers` hang in glisteel's `--capture`.
