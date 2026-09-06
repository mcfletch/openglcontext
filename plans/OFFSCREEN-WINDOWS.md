# Rendering offscreen on Windows

Status: **Landed** (2026-09-05)

`OpenGLContext.eglcontext.EGLContext` renders with no window and no display
server on Linux, and there was no counterpart on Windows: an application that
wanted a frame without a window opened a hidden one, which needs GLFW and a
session with a desktop showing. `OpenGLContext.wglcontext.WGLContext` is that
counterpart, and the machinery under it is
[`OpenGL.WGL.offscreen`](../../pyopengl/OpenGL/WGL/offscreen.py) in PyOpenGL,
beside `OpenGL.CGL` and `OpenGL.EGL.devices`.

Documentation: [docs/offscreen.html](../docs/offscreen.html) covers both
backends; [docs/testing.html](../docs/testing.html) covers the windowless test
mode; PyOpenGL's is `documentation/wgl-offscreen.html`.

## What Windows gives, and what it does not

WGL binds a context to a *device context*, and Windows hands those out for
things it can draw on. There is no "give me a context on this adapter" call as
EGL has, and no windowless context as CGL has. What there is is the **pbuffer**:
a drawable the display driver allocates out of its own memory, with a device
context of its own belonging to no window.

A pbuffer is a real default framebuffer, which is the property that makes the
rest free -- every pass that draws to framebuffer zero, reads it back, takes a
screenshot or encodes a frame behaves as it does on a window. CGL's headless
context has no default framebuffer at all and needs a framebuffer object bound
in its place; this needs nothing.

**One window is created and never shown.** `wglChoosePixelFormatARB`,
`wglCreatePbufferARB` and `wglCreateContextAttribsARB` are extensions, and an
extension entry point resolves through `wglGetProcAddress`, which answers only
while a context is current. `OpenGL.WGL.offscreen.bootstrap()` makes one 1x1
`WS_POPUP` window per process for that and nothing else; the pbuffer outlives
it. The cost is a window station and a desktop, which a service in session 0
has. Nothing on screen, no compositor, no logged-in session, and no
remote-desktop connection that has to stay open.

## What it took beyond the backend itself

Three defects were found by writing it, each fixed where it belonged:

**PyOpenGL's compiled dispatch could not call WGL at all.** WGL declares `HDC`,
`HGLRC` and the pbuffer handles as pointer-sized *simple* types rather than
pointer classes -- deliberately, since ctypes shares every reference to
`c_void_p` and a shared one disables the array machinery. `support.as_pointer`
recognised only pointer classes, so a handle fell through to `ctypes.addressof`
and every WGL call under `PYOPENGL_DISPATCH=c` (the default) was handed the
address of the Python wrapper: `wglCreateContext` answered NULL with
ERROR_INVALID_HANDLE, and nothing raised. `support.opaque` had the return half
of it -- `_OPAQUE_MODULES` listed GL and EGL only, so a returned handle came
back as a fabricated `HDC_pointer` class the ctypes bindings then rejected,
where ctypes gives a plain integer. Both fixed;
`tests/cdispatch/test_pointer_conversion.py` holds the pair to what ctypes
does, on any platform.

**The capture path assumed a back buffer, in three places.** A pbuffer is
single-buffered -- nothing presents it, so a second colour buffer would be
memory spent on nothing -- and `glReadBuffer(GL_BACK)` against a framebuffer
that has no back buffer is `GL_INVALID_OPERATION` rather than a quiet fallback.
`capture.presented_buffer()` asks `GL_DOUBLEBUFFER` and answers `GL_BACK` or
`GL_FRONT`; `capture.read_back_buffer`, `video.recorder.copy_frame` and
`passes.transmission.TransmissionBuffer.capture` all go through it now. The
third was found only by running the whole suite windowless, which is the
argument for having that mode at all: it is the one that decides what a
transmissive material refracts, so glass would have taken the frame down rather
than the screenshot. A latent defect for any single-buffered context, not only
this one. The remaining `GL_BACK` in the package are `glCullFace(GL_BACK)`,
which is a different question.

**A stale conformance baseline had nothing naming it.** `CommercialRefrigerator`
was blessed with no `anim_time`, and `0465a91` later pinned the roster entry to
4.0 -- so the committed image is of the door swung open and the test renders it
shut, differing across 12% of the frame with only a pixel count to say why.
`test_baseline_was_rendered_for_this_view` reads the parameters back out of the
sidecar JSON each `--bless` already writes and fails in a second with the
reason and the command to fix it. One baseline of 157 is stale; re-blessing it
belongs on the machine the corpus was blessed on, as
[CAPTURE-CLOCK-FOR-SETTLE-CAPTURES.md](CAPTURE-CLOCK-FOR-SETTLE-CAPTURES.md)
already says of the same corpus.

## Running the suite with no window

`OPENGLCONTEXT_TEST_WINDOWING=offscreen` gives every test a context on a
pbuffer instead of a hidden window, so the suite runs where there is no
windowing toolkit to open one with. `testing.glcontext` gained
`make_current`, `release_current` and `framebuffer_size`, which work under both
modes; the handful of tests that hand-rolled GLFW calls go through them now, and
the ones that genuinely ask GLFW about a *window* -- whether it is mapped,
whether a hint reached it -- skip on `glcontext.windowing() != 'glfw'`.

Running the suite both ways is worth more than either run alone, because the
two modes leave different state between tests and that is exactly where an
isolation bug hides. One surfaced immediately:
`test_ui_screen.py::test_the_hud_is_drawn_under_the_screens` builds a `Panel`,
whose tree is made through the text renderer and so wants a font texture, in a
module whose docstring says none of it needs a window. It passed only where an
earlier test in the run had left a context current -- and failed whenever it
ran first, in *either* mode. It asks for `gl_context` now.

PyOpenGL's own harness gained the same: `TEST_WINDOWING=wgl` selects
`tests/glcontext_wgl.py`, and `backends.headless_for()` answers which of `egl`,
`cgl` and `wgl` a platform has, so a test meaning "run without a window" asks
rather than naming one. Naming `egl` on Windows selected the Linux platform
module, found no GL library, skipped all twenty-eight cases of `test_core.py`
and read as green; they run and pass now, and so does the whole suite --
2,598 cases, the same count as the windowed run.

That backend asks for a *double-buffered* pbuffer, which is the one place it
departs from what a renderer wants. Nothing presents it and `_swap` does
nothing, but the suite is written against a window and a window has a back
buffer: `glDrawBuffer(GL_BACK)` and `glDrawBuffers([GL_BACK])` are
GL_INVALID_OPERATION where there is none, and the GL 1.x and 2.0 state cases
make both. Asking for one is what makes this the same shape as the windowed
backends rather than a second kind of target every case has to know about.

## Still open

- **macOS.** `OpenGL.CGL.headless_context` exists and PyOpenGL's harness uses
  it, but there is no OpenGLContext backend on it, because CGL gives no default
  framebuffer: a `CGLContext` would have to bind a framebuffer object and make
  every pass that reads framebuffer zero read that instead. Worth doing, and a
  larger change than this one.
- **A windowless mode for the Linux suite.** `OPENGLCONTEXT_TEST_WINDOWING`
  has a provider for Windows only; the Linux one would build on `eglcontext`'s
  pbuffer path. The suite there already runs headless through
  `PYOPENGL_PLATFORM=egl` with a hidden GLFW window, so this buys a run with no
  windowing library installed rather than a run with no display.
- **`CommercialRefrigerator` needs one `--bless`** on the machine the baseline
  corpus was blessed on (NVIDIA; the sidecar records which).
