# Backend parity: every window the engine opens behaves the same

Status: **Landed** (2026-09-06)

## Why

OpenGLContext is meant to be the default choice for any thick-client project
that wants 3D, which means the toolkit a project already uses must not decide
what the engine can do. A team on Qt, on pygame or on wx should be choosing a
window system, not a subset of the engine.

That was not the case. The GLFW backend grew every window-level capability the
engine has, and the others kept whatever they had when it was written:

| | glfw | qt | pygame | glut | wx |
|---|---|---|---|---|---|
| Registered under all three plug-in kinds | yes | yes | **base kind named a class that does not exist** | yes | yes |
| Pointer capture (mouse-look) | yes | yes | **no** | **no** | **no** |
| Pointer motion reported to the sampler | yes | yes | **no** | **no** | **no** |
| Full-screen at run time | yes | **no** | **no** | yes | **no** |
| vsync from the definition | yes | at creation | **no** | **no** | **no** |
| Held keys released on focus loss | yes | yes | **no** | **no** | **no** |
| Loop phases timed (`looptrace`) | yes | yes | **no** | **no** | **no** |
| Input coalesced into one render (`deferRedraw`) | yes | yes | **no** | **no** | **no** |
| Telemetry and the stall journal closed with the loop | yes | **no** | **no** | **no** | **no** |
| GL objects released on the path a user takes to quit | **no** | yes | **no** | yes | **no** |
| Window hidden for capture (`OPENGLCONTEXT_HIDDEN`) | yes | n/a | yes | yes | yes |

A **tk** backend joined the list afterwards, built on PyOpenGL's own
`OpenGL.Tk.GLFrame`; it meets the whole contract from the start.  See
[TKINTER-BACKEND.md](TKINTER-BACKEND.md).

Two of those are not shortfalls but genuine platform limits, and are recorded as
such rather than papered over: Qt has no offscreen surface with a default
framebuffer on the common EGL platforms, so it cannot honour
`OPENGLCONTEXT_HIDDEN`; and neither Qt nor pygame can change the swap interval of
a live context, so a vsync change there takes effect in the next window.

## The contract

`tests/unit/test_backend_parity.py` states it once and holds every backend to
it, the way `test_backend_context_lifecycle.py` already does for context loss.
A backend that cannot do something says so by answering `False` from the method
rather than by not having it, so a caller can tell "not supported here" from
"not implemented anywhere" and offer the user something else.

## What was built

**Shared, so a backend inherits it rather than reimplements it**

- `events/eventhandlermixin.HeldKeyMixin` — the held-key map, the synthetic
  key-repeat for platforms that deliver none, and `clearHeldKeys()` for focus
  loss. This was GLFW-only; a key held when the window lost focus stayed held
  for the rest of the session everywhere else, and the camera kept moving with
  nobody touching the keyboard.
- `context.Context.applyVSync` / `setPointerCapture` / `pumpWindowEvents` /
  `releaseWindow` — declared once, with the answer a backend that cannot do it
  gives.  `setVSync(False)` is the one call an application makes to uncap its
  frame rate; before it, every benchmark and headless capture in this workspace
  reached for `glfw.swap_interval` directly, which does nothing on any other
  backend and warns that GLFW is not initialised on all of them.

**pygame**

- The `Context` plug-in named `PyGameContext`; the class is `PygameContext`, so
  `OPENGLCONTEXT_BACKEND=pygame` raised for anything asking for the base kind.
- Pointer capture through SDL's relative mouse mode, which is the one that
  reports unbounded motion, and `recordPointerMotion` from the motion event's
  own relative delta — so mouse-look works.
- A main loop of the same shape as GLFW's: events polled, then the animation
  hook, then one render per iteration, with the phases timed and the telemetry
  and stall journals closed as it ends.
- A resize no longer calls `set_mode` again. SDL rebuilds the GL context from
  that call, taking every texture, buffer and shader program in the engine's
  caches with it; a resizable SDL2 window needs only the new viewport.
- Full-screen at run time, and the window's own focus events releasing held
  keys.

**glut**

- Its own loop, built on `glutMainLoopEvent`, so the engine drives the frame
  as it does everywhere else: phases timed, input coalesced, and the loop's
  end is a place where the journals can be closed and the window destroyed.
- Pointer capture by hiding the cursor and warping it back to the middle of the
  window, with the warp's own motion event recognised and dropped.
- `recordPointerMotion`, and held keys released when the pointer leaves.

**qt**

- Full-screen at run time.
- The telemetry and stall journals closed with the loop.

**wx**

- The same additions as glut, plus the mouse wheel, which it had never reported
  at all. **Not verified by running**: wxPython has no wheel for this platform
  and will not build here, so the wx work is held to the static contract only
  and needs a run on a machine that has it.

## Found while doing it

**`Context.OnQuit` ends the process with `os._exit`**, so a backend that
released its GL caches after its main loop released nothing on the path a user
actually takes -- closing the window, or pressing Escape. Only GLUT did it in
`OnQuit`. Every backend now names its teardown `releaseWindow` and calls it
there; both paths out are exercised per backend.

**Two GL binding APIs in one process refuse each other.** A thread may have one
current context, and EGL and GLX do not know about each other: asking EGL for a
thread a GLX context holds is `EGL_BAD_ACCESS`, and the reverse is an X
`BadAccess` on `X_GLXMakeCurrent` -- which Xlib's default error handler turns
into a *process exit*, not an exception. That is what running this suite on the
Tk backend does, since several tests open a GLFW window whichever backend the
run is on. PyOpenGL grew `platform.PLATFORM.releaseCurrentContext()` for it, and
the backends let go of a foreign context before taking the thread.

**A GLUT context could only ever be built through `ContextMainLoop`.** That
was the one path that called `glutInit`, and `glutCreateWindow` without it makes
freeglut print a line and call `exit()` -- so a test, a view embedded in an
application with its own loop, or a benchmark stepping frames itself ended the
process instead of getting a window, with no exception to catch. Calling
`glutInit` defensively is no answer either: a second one exits as well.
`ensureGlutInitialised()` asks once, on every path that needs a window.

**A loader thread could keep the process alive for ever.** An `ImageTexture`
loads its URL on a thread that ends by asking each live context to redraw, and
`triggerRedraw` takes the context lock -- so a loader whose lock never comes
never finishes, and Python joins every non-daemon thread as it shuts down. The
suite met that as a seven-minute run followed by thirteen minutes of nothing,
with thirty threads stopped at the same line. The loaders are daemons now: an
image nobody is going to see is not a reason to refuse to exit, whatever is
holding the lock.

**Two GL binding APIs in one process refuse each other, in three places.** The
release goes wherever something is about to take the drawing thread, and each
place was found by a different failure: GLUT creating its window (an X
`BadAccess` that ends the process), the suite's own test window (a driver
refusing to make a 64x64 window, so three hundred tests skipped themselves as
"no GL available"), and Qt's `setCurrent` (`makeCurrent` refused, `setCurrent`
logging it and returning anyway, and every GL call afterwards answering for
whichever context *was* current -- which is how a compatibility context
reported itself as `4.6 CoreProfile`). Qt stops on a refused `makeCurrent` now
rather than letting a caller draw into somebody else's context.

**GLUT's context hints are process-global and sticky, and only ever set.** A
core context sets `GLUT_FORWARD_COMPATIBLE`; a compatibility context set the
profile back and left that flag where it was, so the second context arrived with
the fixed-function pipeline removed and every `glMatrixMode` in it raised
`GL_INVALID_OPERATION` -- a whole file of compatibility-profile tests failing in
a full run and passing on its own. Both hints are named on both paths now, and
`test_backend_parity.py` holds every backend to the profile it was asked for
whatever was built before it.

**The suite's own test window took the thread without asking.**
`testing.glcontext.hidden_window` opens a GLFW window whichever backend the run
is on, and this GLFW asks EGL for the thread: a GLX context already on it makes
that `EGL_BAD_ACCESS`, so on a GLUT run the driver refused a 64x64 window and
three hundred tests skipped themselves as "no GL available". It lets go first,
by the same `releaseCurrentContext` the backends use. The context released
belongs to whatever opened it, and that owner is done with it -- a test window
is made between tests, not during one.

**Destroying a GLUT window reported the wrong thing and then leaked the
window.** PyOpenGL's `glutDestroyWindow` drops the window's context data before
freeglut frees it; where that cleanup failed, the handler logged a variable the
failing line had never assigned, so the report was a `NameError` raised inside
the `except` -- which then stopped the destroy call itself. The cleanup is
`OpenGL.GLUT.special.cleanupWindowContext` now: it answers whether it ran,
raises nothing, and names the error it met, and the window is destroyed either
way.

**A Qt context could only ever be built through `ContextMainLoop`**, for the
same reason a GLUT one could: that was the one path that made the
`QGuiApplication`, and Qt ends the process with `qFatal` -- an abort, not an
exception -- when a window is made without one. `ensureApplication()` asks on
every path that builds a window, and whichever call made the application owns
it.

**GLUT cannot take the drawing thread back.** Every other backend re-makes its
context current whenever it is asked to; GLUT remembers which of its windows is
current and `glutSetWindow` on that one does nothing, so a context let go of
behind its back can never be taken again -- after an external release,
`glutSetWindow` leaves `glGetString(GL_VERSION)` answering None. So the release
that every other backend does in `setCurrent` is, for GLUT, done once before its
window is made, where GLUT is the thing about to take the thread; and the handle
is recorded there rather than at the first `setCurrent`, since GLUT's context is
current from the moment the window exists. A window whose thread something else
has taken says so in the log rather than drawing empty frames.

**A GLUT context did not know how big it was until the loop ran.** GLUT reports
a window's size through its reshape callback, which is delivered by the main
loop -- so anything sizing itself from the window before the first iteration
(the projection matrix, the overlay's scale, a picking ray, a screenshot) read a
zero viewport. The window itself knows, and is asked as it is made.
`getViewPort()` answering before any event has been pumped is part of the
contract now.

**`inContextThread()` raised where it should have answered.** It compares the
calling thread with the one a context claimed, and with no context yet in the
process there is nothing to compare against -- so a backend setting a window up
got an `AttributeError` from the assertion meant to protect it. Until a context
has claimed a thread there is no wrong thread to be on.

**Four tests pinned themselves to GLFW** to exercise something with nothing to
do with GLFW -- the physics demo's camera wiring. They drove input through
`glfwOnKey` and tore down with `glfw.destroy_window`, so a run on another
backend was four failures about a GL context two window systems were fighting
over. They now use the engine's own input records
(`events.synthetic`) and `releaseWindow`, and pass on every backend.
