# Backend parity: every window the engine opens behaves the same

Status: **In Progress** (2026-09-05)

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
| Window hidden for capture (`OPENGLCONTEXT_HIDDEN`) | yes | n/a | yes | yes | yes |

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
- `context.Context.applyVSync` / `setPointerCapture` — declared once, with the
  answer a backend that cannot do it gives.

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

- The same additions as glut. **Not verified by running**: wxPython has no wheel
  for this platform and will not build here, so the wx work is held to the
  static contract only and needs a run on a machine that has it.
