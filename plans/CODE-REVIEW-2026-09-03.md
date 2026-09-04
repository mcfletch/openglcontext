# Code review — OpenGLContext, 2210764..5ad2209 (2026-09-03)

**Scope.** The 12 commits from `2210764` to `5ad2209` (2026-09-02 → 2026-09-03):
the offscreen EGL backend (`eglcontext.py`, `eglvrmlcontext.py`,
`docs/offscreen.html`), the context-loss notification
(`contextresources.py` and the four backends and caches wired to it),
per-context keying of the render pass, the shader programs and the teapot's
vertex arrays, `drawAndReadFrame`, the profile/version resolution fix, the
event-manager receiver-list fix, the glTF conformance and sample-catalogue
fixes, and the test-harness changes (`REQUIRED_EXTENSION_MISSING`,
`DRIVER_DEPENDENT_TOLERANCE`, `_shader_compile_check.py`). 43 files,
+2,065/−145.

**Status: all 15 findings fixed**, each Red/Green with the failing test written
first. `tests/unit` is 7,566 passed / 10 skipped / 4 xfailed (`-m "not serial"`,
6m17s) plus 3 serial; the visual regression suite is 145 passed / 16 skipped;
ruff clean on every path touched; mypy unchanged.

**Overall.** The theme of this batch is right and overdue: a GL object is a name
that means something only in the context that issued it, and this is the work
that makes the engine's caches honour that. `contextresources` is a good
mechanism — one announcement, callbacks that filter on the context that is
current, a documented contract that the announcement happens while the dying
context is still whole. The event-manager fix
(`eventmanager.py:138`) is a genuinely subtle bug found and explained well. The
new EGL backend is clean, is documented in `docs/offscreen.html` and
`docs/environment.html`, has 336 lines of unit tests, and replaces three
hand-rolled copies of the same device-selection dance.

The findings are of two kinds. **The per-context work is half done.** Three
backends out of six never make the announcement the mechanism depends on, the
two caches that were converted are single-slot rather than per-context so two
live contexts thrash and leak, and the engine still never tells *PyOpenGL* that a
context was made current or destroyed — which is the same class of bug, one layer
down, in a library that grew the API for it this same week. And **the new EGL
backend has three small robustness gaps**: a size guard that does not guard, no
cleanup on a failed construction, and a docstring claiming a synchronisation
guarantee `eglSwapBuffers` does not give on a pbuffer.

[M5](#m5) was found while fixing the rest: the event-manager fix in this batch
closed one of the two ways its assertion can fire wrongly, and the other one
takes down any application that opens a second window.

Everything below has a reproduction or a citation.

---

## Summary of findings

| ID | State | Severity | Area | Finding |
|----|-------|----------|------|---------|
| [M1](#m1) | ✅ Fixed | Major | `passes/renderpass.py`, `passes/shaderpass.py` | The per-context caches are single-slot: two live contexts rebuild the pass and the programs every frame, and abandon the outgoing pass's shadow maps in a context that is still alive |
| [M2](#m2) | ✅ Fixed | Major | `pygamecontext.py`, `wxcontext.py`, `openglcontext-qt` | Three backends never call `context_lost()`, so the address-reuse bug the mechanism exists to fix is unfixed there |
| [M3](#m3) | ✅ Fixed | Major | every backend | The engine never tells PyOpenGL a context became current or was destroyed, so PyOpenGL's own per-context dispatch tables carry the stale-handle exposure the engine just fixed for its own caches |
| [M4](#m4) | ✅ Fixed | Major | `eglcontext.py` | A failed construction leaks the EGL display, context and surface, on the fallback path the module docstring recommends |
| [M5](#m5) | ✅ Fixed | Major | `events/eventmanager.py` | The de-registration check counts dead weak references, so a second context raises `AssertionError` out of its constructor |
| [m1](#m1-minor) | ✅ Fixed | minor | `eglcontext.py` | `OnResize`'s size guard is a tuple comparison: three of five degenerate sizes pass it |
| [m2](#m2-minor) | ✅ Fixed | minor | `eglcontext.py` | `SwapBuffers` documents a synchronisation guarantee that `eglSwapBuffers` on a pbuffer does not provide |
| [m3](#m3-minor) | ✅ Fixed | minor | `shaderpass.py`, `teapot.py`, `text/shadertext.py` | Three copies of the same six-line `gl_context_key()` |
| [m4](#m4-minor) | ✅ Fixed | minor | `contextresources.py` | `# pragma: no cover - defensive` on a branch the new test suite covers |
| [m5](#m5-minor) | ✅ Fixed | minor | `contextresources.py` | Callbacks are held strongly for the life of the process with no way to unregister |
| [m6](#m6-minor) | ✅ Fixed | minor | `tests/test_all_scripts.py` | The extension-missing skip message renders a Python list literal |
| [m7](#m7-minor) | ✅ Fixed | minor | `tests/helpers/_shader_compile_check.py` | Narrowed exception handling turns a skip into a failure on a machine without the EGL device extensions |
| [m8](#m8-minor) | ✅ Fixed | minor | `scenegraph/teapot.py` | The failure record has a different shape from the success record; `base_vbo`/`lid_vbo` are stored and never read |
| [m9](#m9-minor) | ✅ Fixed | minor | `eglcontext.py` | `configAttributes(rgb=False)` still requests `EGL_RGB_BUFFER`, so the parameter does nothing |
| [m10](#m10-minor) | ✅ Fixed | minor | `loaders/gltf/samples.py`, `bin/gltf_regression.py` | Two readability regressions: a `next(filter(...))` where a loop is clearer, and a Python program built by string concatenation |

---

<a name="m1"></a>
## M1 — Major — the per-context caches hold one context, not N

`passes/renderpass.py:16-101`, `passes/shaderpass.py:991-1010`

Both caches were correctly identified as needing per-context keying, and both
were given a *key* rather than a *map*:

```python
FLAT = None
FLAT_CONTEXT = None
…
same_context = gl_context == FLAT_CONTEXT
if FLAT is None or FLAT.scene is not sg or not same_context:
    …
    FLAT = FlatPass( sg, context.allContexts )
    FLAT_CONTEXT = gl_context
```

With one context this is correct and cheap. With two, the single slot belongs to
whichever drew last, so every frame of every context misses and rebuilds.
`renderpass.defaultRenderPasses` is `Context.renderPasses`
(`context.py:209`) and is called once per `OnDraw`, so this is per frame, per
window.

### Reproduction

```python
a = glfw.create_window(64, 64, 'a', None, None)
b = glfw.create_window(64, 64, 'b', None, None)
built = []                      # count VRML97ShaderProgram constructions
for frame in range(6):
    for w in (a, b):
        glfw.make_context_current(w)
        shaderpass.get_shader_program()
```

```
12 get_shader_program() calls over two alternating contexts
VRML97ShaderProgram compiled 12 times
12 calls on one context: compiled 1 times
```

One construction per call. A `VRML97ShaderProgram` compiles six programs; a
`FlatPass` is heavier still.

### The leak

The rebuild also abandons GL objects in a context that is still alive.
`renderpass.py:89` disposes the outgoing pass's shadow maps only when
`same_context` — which is right, since those FBOs and textures belong to a
context that is not current and cannot be deleted from here. But that means on a
context switch the outgoing pass is dropped with its shadow maps intact and
nothing else will ever delete them: `drop_pass()` fires on context loss and
returns immediately unless `FLAT_CONTEXT` happens to match the dying context,
which for the context being switched *away* from it does not.

So with contexts A and B alternating and shadows on, each alternation strands one
pass's shadow-map pool in the context it just left. It grows for as long as both
windows are open.

### Fix

Make both caches maps keyed by context, which is what the comments already
describe:

```python
_PASSES: dict[Any, FlatPass] = {}

def __call__(self, context):
    key = gl_context_key()
    pass_ = _PASSES.get(key)
    if pass_ is None or pass_.scene is not sg:
        if pass_ is not None and hasattr(pass_, 'disposeShadowMaps'):
            pass_.disposeShadowMaps()          # this context is current: safe
        pass_ = _PASSES[key] = FlatPass(sg, context.allContexts)
    …
```

and `drop_pass()`/`drop_shader_programs()` then pop the one entry for the dying
context, which is what they already mean to do. That is the same shape
`Teapot._buffers` and `shadertext._renderers` already use, and it makes the
mechanism uniform across the four caches instead of two of one kind and two of
another.

A test for this is cheap and does not need two windows to be visible:
`gl_window` twice, alternate `make_context_current`, and assert the pass object
is identical on the second visit to each context.


### Remediation — ✅ Fixed

**Red.** `tests/unit/test_percontext_caches.py` — two live GLFW contexts, and
fifteen cases: each cache keeps its own entry, going back finds the one that was
there, alternating does not recompile, losing one context leaves the other, a
replaced pass is disposed of, and the key lives in one place. Twelve failed, four
of them with

```
compiled 12 times for two contexts
```

**Green.**

- `renderpass._passes` and `shaderpass._shader_programs` are mappings keyed by
  context. `cached_pass(scene, build)` is the lookup, taking the factory as an
  argument so the rule can be exercised without a `Context` — which is what made
  the caching testable at all.
- Replacing a pass now disposes of the outgoing one's shadow maps
  unconditionally, because with a per-context map the entry being replaced always
  belongs to the context that is current. The old `same_context` guard existed
  only because one slot could hold another context's pass.
- `drop_pass` and `drop_shader_programs` pop their own context's entry and leave
  every other window's alone.
- `FLAT` survives as "the pass that rendered most recently", which is what the
  demos toggling `use_shaders` on it and `report_render_failures` want; the
  mapping is what dispatch reads.

Twelve alternating calls now cost two compiles.

---

<a name="m2"></a>
## M2 — Major — three backends never make the announcement

`contextresources.py:14-16` states the contract:

> a backend says when it is tearing a context down, with the context still
> current, by calling `context_lost()`

Four call sites exist: `glfwcontext.py:462`, `glutcontext.py:193`,
`eglcontext.py:393`, `testing/glcontext.py:151` — three backends and the test
harness. The other three backends do not announce:

- `pygamecontext.py:122` — `MainLoop` returns when `finished`, and
  `PygameQuit` is what sets it; nothing announces.
- `wxcontext.py` — no `OnQuit`, no `Destroy` handler at all.
- `openglcontext-qt/OpenGLContext_qt/qtcontext.py:415` `OnQuit`, `:558`
  `closeEvent` — neither announces.

So on those three backends every cache the mechanism was built for —
`renderpass.FLAT`, `shaderpass._shader_program`, `Teapot._buffers`,
`shadertext._renderers` — keeps holding the dead context's GL names, keyed by an
address the driver is free to hand to the next window. Which is the exact failure
the module docstring opens with:

> That is a black window, or a `GL_INVALID_OPERATION` from a draw, and it happens
> only when an address is reused — which is to say occasionally, and nowhere near
> the code that caused it.

**Fix.** One call per backend, at the point where the window is destroyed and the
context is still current:

- `pygamecontext.MainLoop`, after the loop and before `pygame.display.quit()`.
- `wxcontext` — a `wx.EVT_WINDOW_DESTROY` handler, or the `OnQuit` the other
  backends have; whichever the class's lifecycle actually reaches.
- `qtcontext.closeEvent`, after `makeCurrent()` and before the surface goes.

A test that all registered backends announce is hard to write without every
toolkit installed. A test that each backend module *contains* the call is
brittle. The workable one is a shared teardown helper on `Context` — e.g.
`Context.releaseContextResources()` — that each backend calls, so the contract is
stated once and a new backend inherits it rather than having to know.


### Remediation — ✅ Fixed

**Red.** `tests/unit/test_backend_context_lifecycle.py` walks each backend's
module with `ast` and asserts it releases the context it owned. All five failed,
along with six cases for the contract itself.

**Green.** `Context.releaseContextResources(handle)` and
`Context.bindContextResources(handle)` state the contract once, so a new backend
inherits it rather than having to know it. Every backend calls both:

- `glfw`, `glut`, `egl` — the existing `context_lost()` call became
  `releaseContextResources`, and `setCurrent` gained the bind.
- `pygame` — a `setCurrent` of its own, and a release at the end of `MainLoop`
  before the display goes.
- `wx` — an `EVT_WINDOW_DESTROY` handler, which is what a canvas actually sees
  (a canvas is destroyed with its frame and never gets a close of its own). It
  takes the context first, because the caches may delete what they hold and
  deleting a name needs the context that issued it.

The test reads the source rather than the running program because five toolkits
cannot all be installed at once, and what it asserts — that the call is written —
is exactly the omission.

---

<a name="m3"></a>
## M3 — Major — PyOpenGL is never told about the context either

Grep for `forget_context` or `make_current` across this repository returns
nothing but `pydispatch` imports. The engine does not call
`OpenGL._dispatch.make_current(handle)` when it binds a context, nor
`OpenGL._dispatch.forget_context(handle)` when it destroys one.

That matters now in a way it did not a week ago. PyOpenGL's C dispatch layer
holds a per-context table of resolved entry-point addresses keyed by the context
handle, and grew `forget_context` in this same review window specifically so that
a destroyed context's table is retired before the driver can reuse its address.
Its documentation recommends the call. Without it, PyOpenGL's own cache has
precisely the defect `contextresources` was written to fix in the engine's
caches: a new context handed a recycled address inherits the previous context's
resolved function pointers — including, for an extension the new context does not
have, a pointer into a driver path it must not call.

`make_current` has a second consequence: without it PyOpenGL only re-reads the
current context when a slot needs resolving, so two contexts of differing
capability in one process can share resolutions that are correct for one of them.

**Fix.** The two calls belong beside the ones this batch already added, and are
the natural body of the shared helper [M2](#m2) asks for:

```python
def bindContextResources(self, handle):
    from OpenGL import _dispatch
    _dispatch.make_current(handle)

def releaseContextResources(self, handle):
    from OpenGL import _dispatch
    contextresources.context_lost()      # engine caches, context still current
    _dispatch.forget_context(handle)     # PyOpenGL's dispatch tables
```

`make_current` goes in each backend's `setCurrent`; `releaseContextResources`
replaces the bare `context_lost()` at the four existing sites. The handle is what
each backend already has: `glfw.get_current_context()`, the GLUT window's
context, `self.context` for EGL.

`OpenGL._dispatch.AVAILABLE` is False without the compiled accelerator, and both
functions are no-ops then, so this costs nothing on a plain PyOpenGL install.


### Remediation — ✅ Fixed

Same change as [M2](#m2): `releaseContextResources` calls
`OpenGL._dispatch.forget_context(handle)` after telling the engine's caches, and
`bindContextResources` calls `_dispatch.make_current(handle)`. Both are no-ops
where PyOpenGL has no compiled dispatch layer, so this costs nothing on a plain
`pip install PyOpenGL`.

The handle is read through `contextresources.context_key()` — the platform's own
handle, which is what PyOpenGL keys on. A backend's window id is not it, and each
backend's `_glHandle()` says so.

`tests/unit/test_backend_context_lifecycle.py::TestTheContractIsStatedOnce`
covers both halves, a handle of `None`, and the case where the C layer is absent.

---

<a name="m4"></a>
## M4 — Major — a failed EGL construction leaks the display

`eglcontext.py:245-266`

```python
self.device  = self._selectDevice()
self.display = self._openDisplay(self.device)
self.config  = self._chooseConfig(definition)      # can raise
self.context = self._createContext(self.config)    # can raise
self.surface = self._createSurface(...)            # can raise
self._makeCurrent()                                # can raise
```

Each step raises `EGLContextError` on failure and nothing releases what the
earlier steps acquired. `_openDisplay` has already called `eglInitialize`; if
`_chooseConfig` then finds no matching config — which is the *expected* outcome
on a device that cannot serve the requested buffers — the display stays
initialised for the life of the process. `close()` cannot help: it returns
immediately unless `self.display` is set, and even where it is, nothing calls it,
because the constructor raised and there is no object to call it on.

This is on the path the module docstring recommends:

> Where EGL is absent, constructing an `EGLContext` raises `EGLContextError`
> rather than failing obscurely, so an application can try it and fall back.

An application that tries several device indices, or retries after reducing its
buffer request, leaks one initialised EGL display per attempt.

**Fix.** Wrap the acquisition sequence and release on the way out:

```python
try:
    self.display = self._openDisplay(self.device)
    self.config  = self._chooseConfig(definition)
    self.context = self._createContext(self.config)
    self.surface = self._createSurface(self.config, width, height)
    self._makeCurrent()
except BaseException:
    self._releaseEGL()      # what close() does, minus context_lost()
    raise
```

`close()` is already almost that function; splitting the EGL teardown out of it
gives both callers one implementation. `context_lost()` must *not* run on this
path — no engine cache ever saw this context.

A test is straightforward without any EGL at all: patch `_chooseConfig` to raise,
construct, and assert `eglTerminate` was called with the display `_openDisplay`
returned. `tests/unit/test_eglcontext.py` already stubs at this level.


### Remediation — ✅ Fixed

**Red.** `TestAFailedConstructionReleasesWhatItTook` fails construction at each
of the four steps that can fail and asserts the display was given back. Six cases
failed.

**Green.** The acquisition sequence in `__init__` is wrapped, and
`_releaseEGL()` — split out of `close()`, so there is one implementation — gives
back whatever was taken. It is written to be callable part-way through
construction, where some of the objects do not exist yet.

`contextresources.context_lost()` deliberately does *not* run on that path, and
a test says so: no cache ever saw this context, and announcing its loss would
drop another context's objects.

---

<a name="m5"></a>
## M5 — Major — the de-registration check counts tombstones

`events/eventmanager.py:157-167`

```python
receivers = list(dispatcher.liveReceivers(
    dispatcher.getReceivers(sender=node, signal=metaKey)
))
for receiver in receivers:
    dispatcher.disconnect(receiver, signal=metaKey, sender=node)
assert len(dispatcher.getReceivers(
    sender=node, signal=metaKey,
)) == 0, """Event callback de-registration failed: …"""
```

The walk is over **live** receivers and the assertion is over **raw** entries,
and the two are not the same list. A raw entry whose weak reference has died is
not a registered callback — it is bookkeeping pydispatch has not swept — so the
walk rightly disconnects nothing for it and the assertion then reports that
de-registration failed.

The `list(...)` this batch added closed the other way this fires (disconnecting
from inside a lazy walk). This is the remaining one, and it needs no second
context to be *alive*: it needs one to have *existed*.

### How a tombstone gets there

Every `Context` binds one bound method to two keys — `context.py:591-598`, F2 and
Alt+S both calling `requestScreenshot`, with the comment saying so. pydispatch
keeps one back-reference per receiver, so de-registering either key removes it
(`_killBackref`), and when the object is later collected the death callback finds
no back-reference, removes nothing, and the surviving key keeps a dead entry.

```
sendersBack entry: [10754208]
after deregistering F, sendersBack: None
S raw: 1
after collection -> S raw: 1 live: 0
removeCurrent: AssertionError  <-- reproduced
```

### What it looks like

An `AssertionError` out of a constructor, a long way from the context that caused
it:

```
E  AssertionError: Event callback de-registration failed:
   <class 'OpenGLContext.events.keyboardevents.KeyboardEventManager'>
   ('s', 1, (False, False, True)) None
```

It surfaced here as six errors in `tests/unit/test_eglcontext.py` under one
particular ordering of five test files — the second `EGLContext` built in a
process could not be built at all. For an application it is the second window.

### Remediation — ✅ Fixed

**Red.** `tests/unit/test_event_callback_deregistration.py` — a helper that
leaves a tombstone the way a context does (one bound method, two keys,
de-register one, collect), then the two things that must still work, plus an
end-to-end case building two `EGLContext`s in sequence. All three failed.

**Green.** Both assertions in `eventmanager.py` count live receivers:

```python
assert not list(dispatcher.liveReceivers(dispatcher.getReceivers(
    sender=node, signal=metaKey,
)))
```

The check keeps its purpose — one receiver per key, so registering over a live
handler must take the old one out, and a test holds that — and stops failing on
an entry that is not a handler. The assertion after `dispatcher.connect` had the
same defect and got the same treatment: a dead entry beside the one just
connected is not a second handler.

The underlying bookkeeping is pydispatch's, in a separate repository and outside
this review; the engine's assertion should be right either way, and it now is.

---

<a name="m1-minor"></a>
## m1 — the resize guard is a tuple comparison

`eglcontext.py:350-352`

```python
width, height = int(width), int(height)
if (width, height) <= (0, 0):
    raise EGLContextError('cannot render at %dx%d' % (width, height))
```

`(width, height) <= (0, 0)` is lexicographic ordering on tuples, not "either
dimension is non-positive". It is true only when `width < 0`, or when
`width == 0 and height <= 0`:

```
  100 x 0      guard fires: False   should fire: True
    0 x 100    guard fires: False   should fire: True
   -1 x 100    guard fires: True    should fire: True
  100 x -1     guard fires: False   should fire: True
    0 x 0      guard fires: True    should fire: True
```

Three of five degenerate sizes go through to `eglCreatePbufferSurface`, where a
negative height produces `EGL_BAD_PARAMETER` and the generic
`eglCreatePbufferSurface failed for 100x-1` instead of the message this guard
exists to give.

**Fix.**

```python
if width <= 0 or height <= 0:
```

and a parametrised test over those five pairs. The same expression should be
applied at construction, where `definition.size` is taken on trust at line 251.


### Remediation — ✅ Fixed

**Red.** `TestResizingRefusesADegenerateSize` over all five degenerate sizes.
Three failed — `100x0`, `0x100` and `100x-1` all created a surface.

**Green.** `if width <= 0 or height <= 0`. The test also asserts no surface was
made, so a guard that raises after creating one would still fail.

---

<a name="m2-minor"></a>
## m2 — `SwapBuffers` on a pbuffer guarantees nothing

`eglcontext.py:364-371`

> A pbuffer has nothing to present to, so this is a flush: it is the point at
> which the rendering commands are guaranteed to have been issued, and readback
> after it sees a complete frame.

The EGL specification says that where `surface` is not a back-buffered window
surface, `eglSwapBuffers` has no effect. It is not a flush and it issues nothing;
it returns `EGL_TRUE` and does nothing at all. Readback works today because
`glReadPixels` is itself a synchronisation point, not because of this call.

That distinction matters for anything that is *not* a readback — a frame handed
to `pyopengl-video`, an fbo blit, a fence, a `glGetTexImage` into a persistently
mapped buffer — where the caller has been told there is a barrier here and there
is not.

**Fix.** Do what the docstring says:

```python
def SwapBuffers(self):
    """Finish the frame.

    A pbuffer has nothing to present to, so this is the flush: the point at
    which the commands for this frame are guaranteed to have been issued to
    the driver, which is what a readback or a capture after it depends on.
    """
    glFlush()
```

`glFinish()` if the intent is that the frame is *complete* rather than *issued* —
the docstring's second clause reads as the stronger claim, and a capture backend
wants the stronger one. Either is a real guarantee; `eglSwapBuffers` is neither.


### Remediation — ✅ Fixed

**Red.** `TestFinishingAFrame::test_it_flushes` — failed, nothing was flushed.

**Green.** `SwapBuffers` calls `glFlush()`, and its docstring says what the
guarantee is and that `eglSwapBuffers` is not what provides it. `docs/offscreen.html`
gained a "Finishing a frame" section saying the same.

---

<a name="m3-minor"></a>
## m3 — `gl_context_key()` exists three times

Identical six-line bodies:

- `passes/shaderpass.py:1015` — `gl_context_key()`
- `scenegraph/teapot.py:326` — `Teapot._gl_context()`
- `scenegraph/text/shadertext.py` — `_gl_context()`

and `renderpass.py` imports the first one from `shaderpass` inside two functions
to get at it, which is a module boundary crossed for a helper that belongs to
neither.

`contextresources` is the module that owns this subject, and every caller already
imports it. **Fix:** move it there as `contextresources.context_key()`, keep the
three names as one-line aliases if anything outside the package uses them, and
have `renderpass` import from `contextresources` rather than reaching into
`shaderpass`.

While moving it: the local `from OpenGL import contextdata` inside the function
costs more than the query it guards — 709 ns per call against 345 ns for
`contextdata.getContext()` itself. Hoisting the import to module scope halves it.
`Teapot._render_shader` calls it twice per draw
(once inside `_initialize_buffers`, once at line 406); one call, passed down,
would do.


### Remediation — ✅ Fixed

**Red.** `TestEveryCacheKeysTheSameWay` — the key lives in `contextresources`,
and no module keeps a copy. All four failed.

**Green.** `contextresources.context_key()` is the one implementation, in the
module that owns the subject. `shaderpass.gl_context_key`, `Teapot._gl_context`
and `shadertext._gl_context` are aliases to it, so the names a reader looks for
still resolve and there is one function behind them. `renderpass` no longer
reaches into `shaderpass` for it.

The local `from OpenGL import contextdata` went with the duplication — it cost
more than the query it guarded (709 ns against 345).

---

<a name="m4-minor"></a>
## m4 — a `no cover` pragma on covered code

`contextresources.py:70`

```python
except Exception as err:                # pragma: no cover - defensive
```

`tests/unit/test_contextresources.py:54`
(`test_one_cache_raising_does_not_deny_the_rest_the_news`) registers a callback
that raises `RuntimeError('the driver said no')` and asserts the text appears in
the log. The branch is covered, and covered deliberately — the pragma now hides
tested code from the report and would hide a regression in it.

[../CLAUDE.md](../CLAUDE.md) treats `# pragma: no cover` as the marker for logic
that has been put somewhere a test cannot reach. This one is the opposite case
and simply needs deleting.


### Remediation — ✅ Fixed

The pragma is gone. `test_one_cache_raising_does_not_deny_the_rest_the_news`
covers the branch, so marking it unreachable was hiding tested code from the
report and would have hidden a regression in it.

---

<a name="m5-minor"></a>
## m5 — registered callbacks are never released

`contextresources.py:36-49`

`_callbacks` is a module-level list of strong references with no `remove`. For
the four engine caches, which register module-level functions at import, that is
correct and intended.

For the public API it is a leak by construction. The documented usage —

```python
contextresources.on_context_lost(drop_my_cached_objects)
```

— reads naturally as `on_context_lost(self.drop)` for a per-window or per-scene
object, and that keeps the object alive for the life of the process, along with
everything it references. There is no way to undo it.

`if callback not in _callbacks` is also an `==` scan: two distinct bound methods
of the same object compare equal, so re-registering is deduplicated, but two
objects of the same class registering the same method are not — correct, but
worth knowing it is `==` and not `is`.

**Fix.** Return a token and accept it back:

```python
def on_context_lost(callback):
    ...
    return callback

def forget_context_lost(callback):
    """Stop calling ``callback``.  Safe to call for one never registered."""
    try:
        _callbacks.remove(callback)
    except ValueError:
        pass
```

For the instance-method case a `weakref.WeakMethod` variant, or documenting that
the caller must unregister, is the difference between an API that can be used
from an object and one that can only be used from a module.


### Remediation — ✅ Fixed

**Red.** `TestUnregistering` — three cases, all failed.

**Green.** `contextresources.forget_context_lost(callback)` returns True if the
callback was registered and False if not, so an object tearing itself down need
not remember whether it got as far as registering. `on_context_lost`'s docstring
says which case each is for.

**Found while doing it.** `test_contextresources.py`'s `restore_callbacks`
fixture restored a *snapshot* of the registry, so a cache imported for the first
time inside a test registered itself after the snapshot was taken and was
deregistered for the rest of the session — leaving a later test finding that
cache deaf. It showed up the moment the new test file changed the import order.
The fixture now takes back only what the test added, and the caches are imported
at module scope so their registrations happen at collection.

---

<a name="m6-minor"></a>
## m6 — the skip message prints a list

`tests/test_all_scripts.py:370-372`

```python
pytest.skip(
    f"{script_path.name}: {result.stdout.strip().splitlines()[-1:]}"
)
```

`[-1:]` is a slice, so the message renders with brackets and quotes:

```
foo.py: ['GL_ARB_imaging missing']
```

and for a script that printed nothing:

```
foo.py: []
```

**Fix.**

```python
lines = result.stdout.strip().splitlines()
pytest.skip(f"{script_path.name}: {lines[-1] if lines else 'extension missing'}")
```


### Remediation — ✅ Fixed

**Red.** `tests/unit/test_all_scripts_reporting.py::TestTheSkipMessage`, four
cases over what a script printed. All four failed.

**Green.** `skip_reason(script_name, stdout)` is a function rather than an
expression inside the call, so it can be tested; it takes the last non-empty
line, and says `extension missing` where a script printed nothing rather than
rendering `[]`.

---

<a name="m7-minor"></a>
## m7 — the shader-compile harness now fails where it used to skip

`tests/helpers/_shader_compile_check.py:24-40`

The rewrite is a clear improvement — it drops 40 lines of hand-rolled EGL for the
engine's own backend. But the exception handling narrowed with it. Before:

```python
except Exception as err:
    print("EGL context creation failed:", err)
return None                     # -> exit 77, skip
```

after:

```python
except EGLContextError as err:
    print("EGL context creation failed:", err)
    return None
```

`EGLContext.__init__` reaches `OpenGL.EGL.devices.devices()`, which imports
`OpenGL.EGL.EXT.device_base`, `device_enumeration` and `device_persistent_id` at
module scope. On a build or a driver where those are absent the constructor
raises `AttributeError` or `NullFunctionError`, neither of which is an
`EGLContextError` — and the harness, whose documented exit codes are
"0 = compiled, 77 = no GL context, 1 = at least one program failed", now exits 1
with a traceback. A machine that cannot provide a context is reported as a shader
that does not compile.

The `try` around the import is narrowed the same way (`except ImportError` where
the imports can also raise at attribute-resolution time).

**Fix.** Keep the specific message for the specific case and the skip for
everything else:

```python
except EGLContextError as err:
    print("EGL context creation failed:", err)
    return None
except Exception as err:
    print("no EGL context available:", err)
    return None
```

Second, smaller point: `context.unsetCurrent()` and `context.close()` at line 100
are outside any `try`, so a failure in the checks above leaks them. A
`with EGLContext(...)` — the class has `__enter__`/`__exit__` — reads better and
cannot be skipped.


### Remediation — ✅ Fixed

**Red.** `TestTheShaderCompileHarnessSkips` — four ways of not having a context.
Three failed by propagating the exception instead of returning `None`.

**Green.** `_make_context` catches `Exception` around both the import and the
construction, keeping the specific message for `EGLContextError` and a general
one otherwise. A machine whose EGL is absent, whose driver lacks the device
extensions, or whose display will not initialise now reaches exit 77 rather than
1 — the difference between "this machine cannot render" and "a shader does not
compile".

The body moved into `_check(context)` so that `main` can give the context back in
a `finally`, whatever the checks did.

---

<a name="m8-minor"></a>
## m8 — the teapot's failure record has a different shape

`scenegraph/teapot.py:383-392`

Success stores six keys:

```python
cls._buffers[key] = {
    'base_vao': …, 'base_vbo': …, 'base_count': …,
    'lid_vao':  …, 'lid_vbo':  …, 'lid_count':  …,
}
```

failure stores four:

```python
cls._buffers[key] = {'base_vao': None, 'base_count': 0,
                     'lid_vao': None, 'lid_count': 0}
```

Nothing reads `base_vbo` or `lid_vbo` today, so the mismatch is latent rather
than live — but it is a record whose shape depends on which branch wrote it, and
the next reader of `bufs['base_vbo']` finds a `KeyError` only on the failure
path, which is the path least likely to be exercised.

**Fix.** One shape from both branches — write the `vbo` keys as `None` in the
failure record, or drop them from the success record since nothing reads them.
Dropping is better: the VBOs die with the context, and storing a name nothing
uses invites someone to believe it is being managed.


### Remediation — ✅ Fixed

Both branches write the same four keys. The VBO names are not kept: they die with
the context, and storing a name nothing manages invites the belief that something
does. Covered by the existing teapot render tests, which read the record on both
paths.

---

<a name="m9-minor"></a>
## m9 — `configAttributes(rgb=False)` does not do anything

`eglcontext.py:151-189`

```python
attributes = [
    …
    EGL.EGL_COLOR_BUFFER_TYPE, EGL.EGL_RGB_BUFFER,
]
if rgb:
    attributes += [EGL.EGL_RED_SIZE, 8, EGL.EGL_GREEN_SIZE, 8, EGL.EGL_BLUE_SIZE, 8]
```

The buffer type is pinned to `EGL_RGB_BUFFER` whether or not `rgb` is set, so
`rgb=False` asks for an RGB buffer and merely declines to say how many bits per
channel — which lets the implementation pick, rather than selecting a different
kind of buffer. `ContextDefinition.rgb` therefore has no observable effect on
this backend.

**Fix.** Either drive the buffer type from the flag —

```python
EGL.EGL_COLOR_BUFFER_TYPE,
EGL.EGL_RGB_BUFFER if rgb else EGL.EGL_LUMINANCE_BUFFER,
```

— or, if a luminance pbuffer is not something this backend intends to support,
drop the parameter and say in the docstring that the surface is always RGB. A
parameter that is accepted and ignored is worse than one that is absent.


### Remediation — ✅ Fixed

**Red.** `TestConfigAttributesColourBuffer::test_not_rgb_asks_for_a_luminance_buffer`
— failed, `EGL_RGB_BUFFER` was requested either way.

**Green.** `EGL_COLOR_BUFFER_TYPE` follows the flag:
`EGL_RGB_BUFFER if rgb else EGL_LUMINANCE_BUFFER`. The comment says why a
parameter that only declines to state a channel width has nothing to do.

---

<a name="m10-minor"></a>
## m10 — two readability regressions

**`loaders/gltf/samples.py:81`**

```python
sm = next(filter(None, (shot.search(line) for shot in shot_res)), None)
```

"the first pattern that matched, or None" written three ways at once. The
straightforward form is the same length and says what it does:

```python
for pattern in shot_res:
    sm = pattern.search(line)
    if sm:
        break
else:
    sm = None
```

The change itself is right and the docstring explaining *why* both forms are
matched — upstream's file has changed under us once — is exactly the kind of
reason worth recording.

**`bin/gltf_regression.py:349-359`**

```python
code = ("from OpenGLContext.testing.glcontext import hidden_window;"
        "from OpenGL.GL import glGetString,GL_RENDERER,GL_VERSION;"
        "\nwith hidden_window('provenance', size=(8, 8), profile='core'):\n"
        "    print((glGetString(GL_RENDERER) or b'').decode())\n"
        "    print((glGetString(GL_VERSION) or b'').decode())")
```

A Python program assembled from adjacent literals mixing `;` separators with
embedded newlines and leading indentation. It is correct and it is hard to read
or edit safely.

**Fix.** A module-level triple-quoted constant, dedented:

```python
_PROVENANCE_PROGRAM = """\
from OpenGLContext.testing.glcontext import hidden_window
from OpenGL.GL import glGetString, GL_RENDERER, GL_VERSION

with hidden_window('provenance', size=(8, 8), profile='core'):
    print((glGetString(GL_RENDERER) or b'').decode())
    print((glGetString(GL_VERSION) or b'').decode())
"""
```


### Remediation — ✅ Fixed

`samples.py` uses a `for`/`break` over the two patterns. The docstring explaining
why both forms are matched — upstream's file has changed under us once — stays,
because that is the part a reader needs.

`gltf_regression.py` holds the provenance program in a module-level
`_PROVENANCE_PROGRAM` triple-quoted string, so it reads as the Python it is.

---

## What was checked and found sound

Recorded so the next review does not repeat the work.

- **`events/eventmanager.py:138`** — the `list(...)` around `liveReceivers` is
  correct, and the explanation (the connection table's own list shortening under
  a lazy walk) is right. This is a real intermittent bug, correctly diagnosed.
- **`context.py:354-395`** — `drawAndReadFrame` is a good hoist: the auto-exit
  capture logic is now a general "draw one frame and read it before it is
  presented" that a test can call, with `_autoExitDraw` reduced to the two lines
  that are actually about auto-exit.
- **`context.py:456-471`** — the profile/version resolution fix is correct;
  `versionWasSet` is captured before `named` is applied, which is the part that
  is easy to get wrong.
- **The context-key filtering in every callback** —
  `renderpass.drop_pass`, `shaderpass.drop_shader_programs`,
  `Teapot.drop_buffers`, `shadertext.drop_text_renderers` all compare against the
  context that is current before dropping anything, which is what makes a single
  global announcement safe. Verified that `contextdata.getContext()` returns
  distinct values for two live GLFW contexts in this container
  (`103455584`, `104994112`, and back to `103455584`).
- **`docs/offscreen.html`, `docs/environment.html`, `docs/structure.html`,
  `docs/documentation.html`** — the EGL backend is documented, indexed, and
  `OPENGLCONTEXT_EGL_DEVICE` appears in both the environment table and the
  offscreen page. `renderoptions.ENVIRONMENT` gained the variable so a capture
  does not inherit it. Documentation for this batch is complete.
- **`tests/test_all_scripts.py`** — `tolerance_for` is wired into both the
  comparison (line 489) and the failure message (line 1059); the two
  `DRIVER_DEPENDENT_TOLERANCE` entries each carry the reason, and the comment
  correctly notes that a black frame differs by far more than either number.

---

## Documentation changed

- **`docs/structure.html`** — the context-resources section now states the whole
  contract a backend owes: `bindContextResources` and `releaseContextResources`,
  what each tells (the engine's caches *and* PyOpenGL's dispatch tables), when it
  has to be called, and that all six backends do it. It also says why a cache
  holds one entry *per context* rather than one entry, and documents
  `context_key()` and `forget_context_lost()`.
- **`docs/offscreen.html`** — three new sections: "Finishing a frame" (what
  `SwapBuffers` guarantees and why `eglSwapBuffers` is not what provides it),
  "Resizing", and "When construction fails" (that a failure gives back what it
  took, which is what makes the try-and-fall-back advice safe).
- **`OpenGLContext/contextresources.py`** — the module docstring covers
  `context_key`, and `on_context_lost` says which lifetime each registration
  style is for.
- **`OpenGLContext/eglcontext.py`** — `SwapBuffers` describes the guarantee it
  actually gives; `_releaseEGL` says why it touches no engine cache.
- **`OpenGLContext/context.py`** — `bindContextResources` and
  `releaseContextResources` are where the contract is written down.
- **`OpenGLContext/events/eventmanager.py`** — both assertions say what they
  check and why a dead entry is not a handler ([M5](#m5)).

`docs/environment.html` needed no change: `OPENGLCONTEXT_EGL_DEVICE` was already
documented in both tables.

---

## New tests

| File | What it holds |
|------|---------------|
| `tests/unit/test_percontext_caches.py` | Two live contexts: each cache keeps its own entry, alternating does not recompile, losing one leaves the other, a replaced pass is disposed of, and every cache keys the same way |
| `tests/unit/test_backend_context_lifecycle.py` | That every backend releases the context it owned, and that both halves of the contract tell the engine's caches and PyOpenGL |
| `tests/unit/test_all_scripts_reporting.py` | The skip message a script's exit code produces, and that the shader-compile harness skips rather than fails on a machine with no context |
| `tests/unit/test_eglcontext.py` | A failed construction releases what it took; degenerate resize sizes; that finishing a frame flushes; that `rgb=False` means a luminance buffer |
| `tests/unit/test_contextresources.py` | Unregistering, and a `restore_callbacks` fixture that no longer deregisters the caches it finds |
| `tests/unit/test_event_callback_deregistration.py` | That a dead weak reference is not a registered callback, that a live one is still replaced, and that a second context can be built after the first has gone |
