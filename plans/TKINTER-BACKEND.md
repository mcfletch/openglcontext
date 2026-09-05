# A Tkinter backend

Status: **Planned** (assessed 2026-09-05)

## Why it is worth having

Tkinter ships with CPython. A team writing a small tool -- a viewer, a
calibration screen, an instrument panel -- reaches for it because it is already
there, and today that team cannot use this engine without adding GLFW, Qt, wx or
SDL to their dependency list. For a project that wants to be the default choice
for thick-client 3D, the toolkit already in the standard library is the one
whose absence is hardest to explain.

`OpenGLContext/events/tkevents.py` has existed for years: the event translation
is written, keyed by Tk's own `keysym` names and modifier flags. What has never
existed is a `tkcontext.py` -- something to create a GL context and give
`tkevents` a window to be mixed into.

## What is missing, and it is only one thing

**Tkinter has no GL canvas.** Every other backend here is built on a toolkit
that creates the context itself; Tk has no equivalent of `glcanvas.GLCanvas`,
`QOpenGLContext` or `pygame.display.set_mode`. What Tk does give is a native
window handle (`winfo_id()`), and a GL context can be made against that
directly -- GLX on X11, WGL on Windows, NSOpenGL on macOS.

## What was measured

Tk **can** host a working GL context on this machine. Through
[pyopengltk](https://github.com/jonwright/pyopengltk) (MIT, ~11 KB, pure Python
over `ctypes`), a Tk frame rendered and reported:

```
GL_VERSION  4.5 (Compatibility Profile) Mesa 25.2.8
GL_RENDERER llvmpipe (LLVM 20.1.2, 256 bits)
PROFILE     core=False  mask=2
```

So the question is not whether Tk can render. It is what the glue should be.

## The two routes

**Depend on `pyopengltk`.** It covers X11, Win32 and Darwin, it is MIT, and it
is small enough to read in an afternoon. Against it, for a backend that is to be
called *fully supported*:

- **No core profile.** It creates the context with `glXCreateContext` /
  `glXCreateNewContext` and no attribute list, so a driver gives it a
  compatibility context. The engine's default is core
  (`plans/CORE-PROFILE-DEFAULT.md`). The `#version 330 core` shaders and the
  VAO/VBO paths all run in a 4.5 compatibility context, so the *rendering* is
  unaffected -- but a backend that cannot honour `profile='core'` cannot be held
  to the contract every other backend meets, and a driver bug that only shows in
  a compatibility context would be ours to explain.
- **It writes to stdout.** `print("GLX version: %d.%d")` and four more lines on
  every context creation. A library that prints is a library an application has
  to work around.
- **Its extension points are not where we need them.** `tkResize` calls
  `initgl()` on every window resize, which for this engine would mean running
  `OnInit` -- rebuilding textures, shaders and the scenegraph -- each time
  somebody dragged a corner. The context and display handles are name-mangled
  private attributes, so a subclass cannot reach them to do better.

Each is workable around by rebinding Tk events and ignoring the frame's own
draw loop, but the total is a backend defined by what it has to avoid.

**Write the glue.** Roughly 150 lines per platform: `XOpenDisplay` +
`glXChooseFBConfig` + `glXCreateContextAttribsARB` on X11 (which is where the
core profile comes from), `GetDC` + `wglCreateContextAttribsARB` on Windows,
`NSOpenGLContext` on macOS. PyOpenGL already binds all of GLX and WGL, so the
X11 and Windows paths are ctypes calls rather than new native code; macOS needs
`pyobjc` or a `ctypes` shim over the Cocoa class.

## Recommendation

Write the glue, and take the platforms one at a time rather than shipping a
backend that is registered everywhere and works in one place. X11 first: it is
what can be verified here, it is where the core-profile request is a single
extra call, and it gives the backend an honest first claim -- *supported on
X11* -- rather than a footnote about which profile you get.

The order of work:

1. `OpenGLContext/tk/glx.py` -- a context on a Tk window's `winfo_id()`, with
   the profile, version and buffer sizes the `ContextDefinition` asks for, and
   `swapcontrol` for the swap interval.
2. `OpenGLContext/tkcontext.py` -- `TkContext` on that, with the loop every
   other backend now has (`root.update()` in place of `glutMainLoopEvent`), and
   the window capabilities `plans/BACKEND-PARITY.md` states: pointer capture by
   warping (Tk has `event_generate('<Motion>', warp=True)`), full screen through
   `wm_attributes('-fullscreen')`, held keys released on `<FocusOut>`, and the
   wheel from `<Button-4>`/`<Button-5>` on X11 and `<MouseWheel>` elsewhere.
3. `tkevents.py` brought to the same contract: it imports `OpenGL.Tk`, which is
   the Togl-based canvas nothing ships any more, where plain `tkinter` is what
   it actually needs; and it reports no pointer motion to the movement sampler,
   so mouse-look would not turn the view.
4. Registration in `OpenGLContext/__init__.py`, an interactive and a VRML
   subclass, and `test_backend_parity.py` extended to cover it.
5. Then WGL, then Cocoa.

Until step 1 exists there is nothing to register, so nothing here is half
shipped: `tkevents.py` is a module with no consumer, as it has been.
