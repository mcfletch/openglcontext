# Continuous integration: two OpenGL implementations, on every push

**Status: landed (2026-09-04) for the Linux/llvmpipe and macOS jobs.**

## What this is for

The suite has been run on one machine, one driver. A driver difference is
therefore invisible until somebody with a different GPU reports it, and a
regression is invisible until the next person runs the suite by hand. What
closes that is a run on every push, against renderers that are not the one the
work was done on.

The constraint is money: GitHub's GPU runner is a *larger* runner, billed per
minute on Team and Enterprise plans, and the documentation says outright that
larger runners are not free for public repositories. There is no free GPU tier
for open source. So the two implementations CI uses are the two that are free:

| Job | Implementation | What it covers |
|---|---|---|
| `llvmpipe` (`ubuntu-latest`, under `xvfb-run`) | Mesa llvmpipe, GL 4.5 core and compatibility | Everything that is not about speed or about pixels matching a blessed image. The same renderer on every run, so a difference between runs means something. |
| `macos` (`macos-14`, `macos-15`) | Apple GL through **CGL** | A second vendor's implementation. Mesa is lenient; a call that survives on it because of that fails here. No compatibility profile above 2.1 there, so the fixed-function arms skip. |

`LIBGL_ALWAYS_SOFTWARE=1` reproduces the Linux job on a machine with a GPU,
which is how a failure seen in CI is chased locally.

## What is deliberately left out

**`visual`.** The reference images are blessed on one renderer. Measured on
llvmpipe against the GPU-blessed glTF baselines: 101 of 159 conformance views
exceed the 2% pixel gate, typically by 2–6% of pixels at a mean delta under
1.5/255. That is rasterisation precision, not a wrong render — but comparing
against them in CI would report a driver difference as a regression on every
push. Reference-image regression stays a job for a machine with the blessing
GPU in it.

*The durable fix is per-renderer baselines* — a baseline set keyed by
`describe_gl().renderer`, so each platform compares against images blessed on
it. The llvmpipe set can be blessed locally; the macOS sets can only be blessed
from a CI run's artifacts. Until those exist this job does not pretend to guard
rendering, and says so rather than raising the tolerance, which would blind the
GPU runs too.

**`performance`.** An assertion about how fast something draws is unanswerable
on a CPU rasteriser: `test_the_animation_half_leaves_the_frame_to_the_drawing`
would *pass* there, because drawing costs orders of magnitude more, having
measured nothing. The llvmpipe job deselects them outright. The macOS jobs do
not, but what answers there is Apple's CPU renderer as well (see below), so the
plugin skips them of its own accord and names the renderer in the reason. Timing
assertions belong on a machine with a GPU in it, which no free runner is.

## macOS has no window server, so GLFW cannot serve it

The first run of the macOS jobs failed before a test ran:

    GLFWError: (65545) NSGL: Failed to find a suitable pixel format

GLFW's `nsgl_context.m` asks for `NSOpenGLPFAAccelerated` unconditionally, and
those runners are virtual machines with no accelerated renderer for the runner's
session. No hint changes it; projects that need it patch GLFW's own source. So
**no GLFW context can be created on one at all** — which also corrects an
assumption in the table above: what answers there is Apple's CPU renderer, not a
GPU. That is still the point of the job, since what llvmpipe cannot cover is a
second *implementation*, not a second speed.

CGL is the layer NSGL and AGL are built on and the only one of the three that
hands out a context with no window server. `OpenGL.CGL` is the binding for it,
new in PyOpenGL and public: pixel-format attributes, the three profiles macOS
offers, renderer ids, error codes, `headless_context()` and `OffscreenTarget`.
Two things about it are not incidental — there is no framebuffer zero without a
drawable, so a framebuffer object is bound in its place; and a machine with no
accelerated renderer cannot be *asked* for one, so the pixel format is chosen by
trying acceleration, then no preference, then Apple's CPU renderer by id.

`hidden_window` falls back to it where GLFW will not open a window, so nothing a
test does has to change. `backend()` says which answered; `framebuffer_size()`
and `color_buffer_attachment()` are the two places a window and an offscreen
target differ, and answer for both.

## What it needed

Three defects stood between the suite and a software-rendered runner, and each
is a fault in its own right rather than a CI accommodation.

**A segfault reachable from three places.** Mesa refuses to force software
rasterisation onto a display built on a hardware EGL device
(`EGL_PLATFORM_DEVICE_EXT`), and having refused it dereferences the screen it
declined to build: `eglInitialize` takes the process down inside
`driCreateNewScreen3` rather than returning `EGL_FALSE`. Reproducible with raw
`ctypes` and no PyOpenGL in the stack, so nothing we pass reaches the fault —
but three of our callers chose exactly that pair. `eglcontext.chooseDevice` fell
back to a hardware device when software was demanded and none was on offer, and
honoured a pinned hardware index against the same demand; PyOpenGL's headless
test backend preferred hardware unconditionally; and PyOpenGL's own
`check_egl_device_enumeration` diagnostic initialised every device in turn. All
three now refuse the contradiction and name the two settings to choose between.
The fallback the other way round — wanting a GPU, finding a CPU rasteriser — is
slow rather than fatal, so it still runs.

**A test context that was not the shipped one.** `hidden_window` asked for a
core profile without `GLFW_OPENGL_FORWARD_COMPAT`, while `glfwcontext` asks for
both together for a real window. So a test exercised a context only a test ever
gets — and on macOS the driver refuses that request outright, which would have
left every GL test on the platform skipping and the job green without having
rendered. Core now implies forward-compatible, as it does for a real window.

**Window flags computed inside a window.** `pygameFlagsFromDefinition` mixed the
SDL attribute calls, which need an initialised display, with the flag arithmetic,
which needs nothing. The three tests over it failed wherever SDL had no display
to give. `pygameWindowFlags` is the flag half on its own.

## The marker

`performance` is new and ships with the engine, in
`OpenGLContext.testing.plugin`, so a game built on OpenGLContext gets the same
behaviour: a test asserting how fast something draws is skipped on a software
renderer, with the renderer named in the reason.
`OPENGLCONTEXT_PERFORMANCE_TESTS` overrules it in either direction, and a value
that is neither a yes nor a no is an error rather than a silently reversed pin.
`describe_gl()` is what it reads — vendor, renderer, version and `software`,
from the one probe window `gl_available()` already opened.

It joins `serial` (needs a quiet machine) and `visual` (compares against a
blessed image) rather than replacing either. Every `performance` test is also
`serial`; the reverse does not follow.

## A hazard this uncovered, and closed

`OpenGL/_dispatch/_tables.py` held `ARRAY_TYPES` as a **positional** list that
the compiled `OpenGL_accelerate.dispatch` indexed into. Adding an element type
shifted every index after it, so a tree whose Python was newer than its built
extension handed out the *wrong array class* — `GLubyteArray` came back as
`GLshortArray`, and a `glGetBufferSubData` of 64 bytes returned 128. No error,
no warning: ten skinning tests failed on a reshape, three call frames away from
the cause.

The name is what crosses now. The element table already carried the class name
beside the index, so the generated header emits those names in its own order and
`_configure` takes a *mapping* and fills its own table from it, index by
compiled index. The order is the extension's alone and no Python file has to
agree with it; a class it needs and cannot find is refused by name, telling the
reader to rebuild. `ARRAY_TYPES` is gone: a positional table nothing reads is a
trap for whoever reads it next.

## Still open

- **Per-renderer reference baselines**, so the `visual` tests can run in CI.
- **The three backends with no CI**: GLUT, wxPython and Qt. The support
  commitment in `docs/structure.html` covers five backends; two of them are
  under test here.
- **A Python version matrix.** Both jobs run 3.12. The floor is 3.10.
- **A GPU job**, if one is ever wanted: a self-hosted runner is the only free
  way to a real GPU, and needs the fork-PR precautions that go with one.
