# Offscreen EGL context

*Landed 2026-09-03. User documentation: [docs/offscreen.html](../docs/offscreen.html).*

## What was missing

Every backend the engine had owned a window. A user who wanted a frame without
one had no supported way to get it: the only EGL context creation in the whole
stack was scaffolding inside test helpers — `tests/helpers/_shader_compile_check.py`
here, `glcontext_egl.py` and `os_egl.py` in PyOpenGL's own suite — each a
separate hand-rolled copy of the same three extensions.

That is the wrong shape for a capability a build machine, a rendering service or
a batch thumbnailer wants, and it is the capability pyrender exists to provide,
so it belongs in the engine as an owned API rather than in a test.

## What landed

**`OpenGLContext/eglcontext.py`** — `EGLContext`, a context like any other.
Registered as the `egl` backend in all three plugin registries, so
`OPENGLCONTEXT_BACKEND=egl` selects it, and `eglvrmlcontext.py` gives it the
VRML97 form every other backend has.

It renders to a **pbuffer** rather than a surfaceless context on purpose: a
pbuffer is a real default framebuffer, so every pass that draws to framebuffer
zero, reads it back or takes a screenshot behaves exactly as it does on a window
and nothing has to know it is offscreen. Surfaceless would have required every
draw path to bind an FBO first. A pbuffer cannot be resized, so `OnResize` builds
a replacement and drops the old one; the GL context survives it, and the
textures, buffers and programs in it survive with it.

Unlike the windowed backends there is no separate interactive class. A window can
be useful without navigation; an offscreen frame cannot, because it needs a
viewpoint and there is no user to steer one. So the camera is in the one class.

**`OpenGL/EGL/devices.py`** (PyOpenGL) — enumerating EGL devices and saying what
each one is: its extensions, its driver name, and whether it rasterises on the
CPU. Facts only. Which device to *use* is policy and stayed here, in
`chooseDevice`.

## Why the device choice is load-bearing

Not a preference. Asking Mesa for a display on a **hardware** EGL device while
`LIBGL_ALWAYS_SOFTWARE` demands software rendering is a contradiction it detects,
warns about, and then **segfaults** on rather than refusing cleanly:

    libEGL warning: Not allowed to force software rendering when API
    explicitly selects a hardware device.
    Fatal Python error: Segmentation fault

The faulting frame is `driCreateNewScreen3` in Mesa's libgallium, four frames
below `libEGL_mesa`; it reproduces with no PyOpenGL in the process at all, using
nothing but `ctypes.CDLL("libEGL.so.1")`, and `PyOpenGL 3.1.10` crashes
identically. Not ours, and not fixable by us — but reachable through our code,
and it was: this helper and PyOpenGL's own EGL test backend both dumped core
under `LIBGL_ALWAYS_SOFTWARE=1` on a machine that has a GPU, because both took
device 0 regardless. `chooseDevice` honours the request, which is what keeps the
process alive. Found by the workspace's
[downstream client harness](../../downstream/README.md) while measuring what
its roster could do without a GPU.

## Where it works

EGL is the GL binding on Linux and Android. Windows has no EGL of its own —
ANGLE or Mesa supply one, but ANGLE is GL ES, so the
`eglBindAPI(EGL_OPENGL_API)` this backend needs fails there — and macOS has none
at all. PyOpenGL says as much in its own structure: `OpenGL/platform/egl.py` is a
shim aliasing `LinuxPlatform`.

Elsewhere, a hidden window (`OPENGLCONTEXT_HIDDEN=1`) renders and reads back
identically and is what the suite uses. What it cannot do is run with no display
server at all, which is the thing this backend is for. Where EGL is absent,
construction raises `EGLContextError` rather than failing obscurely, so an
application can try and fall back.

## Driving it

Nothing outside an offscreen context will ever deliver a keystroke. It needs no
new machinery for that: `OpenGLContext.events.synthetic` already turns an input
record into an event and delivers it by the route the platform would have used,
and is already shared by telemetry replay and the out-of-process event injector.
A test drives an offscreen scene with the same records, so a script written for
one drives the others.

## A flaky suite interaction, fixed on the way

The GL render tests were a coin toss, which showed as `test_shadow_bias_gl.py`
failing after the IBL tests had run: one failure, then none, then two on three
consecutive runs of `pytest tests/unit -k "shadow or ibl"`. Unrelated to this
work -- that selection contains none of it -- but found by it, and until now it
appeared only in the six-minute full run, where an intermittent failure has no
handle on it.

`IBLController` starts at the mode the GPU supports and degrades when the recent
frame rate sags below 45. A test that renders a handful of frames has almost no
frame rate to report, so it drops to `analytic`; the same test after a warmed-up
neighbour sometimes reports enough to stay at `full`, and the two render
differently. Every measured render in the family was judging whichever picture
it happened to get.

`_base_env` now pins `OPENGLCONTEXT_IBL=analytic`, which is what these renders
have always effectively had -- no assertion changed -- and
`test_the_render_environment_does_not_adapt` holds it there. The reproduction
that failed on every one of four runs beforehand passed on five afterwards.

Worth knowing: pinning `full` instead fails six of these tests. The family has
never actually rendered at full IBL, so what those assertions would be against
it is an open question rather than a regression.

## Still open

- **`pickAsync=False` never delivers a synthetic click** — 0 after two draws,
  where the default async path delivers after one. The synchronous pick route
  appears not to dispatch in this context. Not investigated; not introduced here.
- **mypy** reports two signature conflicts on `addEventHandler` and
  `initializeEventManagers` between `PhysicsWalkMixin`, `EventHandlerMixin` and
  `Context`. `glfwinteractivecontext.py` and `glfwvrmlcontext.py` report the
  identical two, so this is the existing backlog named in
  [LINT-AND-TYPING.md](LINT-AND-TYPING.md) rather than anything new; the new
  files inherit it by composing the same mixins.
