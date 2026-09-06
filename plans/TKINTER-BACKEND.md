# A Tkinter backend

Status: **Landed** (2026-09-06). X11 verified; Windows rests on PyOpenGL's WGL
implementation and is unverified here; macOS raises with what it needs.

## Why

Tkinter ships with CPython. A team writing a small tool -- a viewer, a
calibration screen, an instrument panel -- reaches for it because it is already
there, and until now that team could not use this engine without adding GLFW,
Qt, wx or SDL to their dependency list. For a project that wants to be the
default choice for thick-client 3D, the toolkit already in the standard library
is the one whose absence is hardest to explain.

`OpenGLContext/events/tkevents.py` had the event translation written and nothing
to mix it into.

## What was missing, and where it was fixed

**Tkinter has no GL canvas**, and that was the whole of it. The fix belongs in
PyOpenGL, not here: Tk hands out the platform's window handle and every platform
has a documented way to make a context against one. `OpenGL.Tk.GLFrame` is that
widget now -- see `plans/TK-WIDGET.md` in the PyOpenGL distribution -- and this
backend is a thin layer on it.

`OpenGL.Tk` previously wrapped **Togl**, a Tcl C extension that has to be
installed separately, whose last release was 2005, and which could only make a
fixed-function context. Importing it opened a window. None of that is so any
more, and `Togl`, `RawOpengl` and `Opengl` keep their names and their methods.

## What is here

- **`OpenGLContext/tkcontext.py`** -- `TkContext`, with the window capabilities
  `plans/BACKEND-PARITY.md` demands of every backend: pointer capture by
  warping, full screen, vsync, held keys released on focus loss, the loop's
  phases timed, and the GL caches released before the process ends.
- **`tkinteractivecontext.py`**, **`tkvrmlcontext.py`**,
  **`tktestingcontext.py`** -- the interactive, scene-loading and testing forms
  every backend has, registered as the `tk` plug-in name.
- **`OpenGLContext/events/tkevents.py`** -- brought to the same contract:
  pointer motion reported to the movement sampler as it happens, the wheel
  (buttons 4 and 5 on X11, `<MouseWheel>` elsewhere), held keys, and the
  modifier and key-name translation the older module had.

**The view can sit inside somebody else's window**, which is the reason to
reach for Tk at all:

```python
context = TkInteractiveContext(parent=someFrame)
context.frame.pack(fill='both', expand=True)
someFrame.after(16, context.loopIteration)      # driven by the host's loop
```

`TkContext.MainLoop` owns the loop where the context *is* the application; a
host that owns its own calls `loopIteration` from it.

## What it costs

**A hidden window is a window that appeared and then went.** A Tk window has no
native handle until the window system has mapped it, so there is nothing to make
a context against before then: `OPENGLCONTEXT_HIDDEN` is honoured by
withdrawing the toplevel once the context exists. Rendering and reading back are
unaffected -- both happen in the back buffer -- and it is verified by the suite,
which captures a frame from a withdrawn window.

**Tk needs an X display.** It has no Wayland backend, so on a Wayland-only
session it runs through XWayland, and a headless machine needs `xvfb-run`. The
same is true of the GLUT and pygame backends here.

**No accumulation buffer.** The widget asks the window system for a modern
context; the buffer is absent from a core profile. A definition asking for one
is told rather than quietly ignored.

## Running everything on it

```bash
OPENGLCONTEXT_BACKEND=tk xvfb-run -a python -m pytest tests/unit
OPENGLCONTEXT_BACKEND=tk xvfb-run -a python -m pytest tests/test_all_scripts.py
OPENGLCONTEXT_BACKEND=tk xvfb-run -a python -m openglcontext_forest_demo.run
```

Every application in this workspace reads `OPENGLCONTEXT_BACKEND` through
`os.environ.setdefault`, so naming one on the command line is all it takes;
none of them pins a backend against the caller's wishes. Where an application
wanted something a toolkit had -- uncapping the frame rate for a benchmark or a
headless capture -- it now asks the engine (`Context.setVSync`,
`Context.pumpWindowEvents`) rather than calling into GLFW, which did nothing on
any other backend and warned that GLFW was not initialised on all of them.
