# Code review: the workspace since the 2026-09-25 review (2026-09-27)

## Summary

Priority: P1 fix before the next release; P2 fix in the ordinary course of
work; P3 a small defect, a nit or a documentation fix. Status is the
remediation state: `Open`, or `Fixed` with the commit (in openglcontext
unless another project is named). The work log at the end records progress
between sessions. A finding
marked "Investigate" in its comment needs a decision on whether the behaviour
is intended before it is fixed.

| § | Priority | Summary | Status | Comments |
|---|---|---|---|---|
| 1.1 | P1 | A failure in `Context.__init__` leaves the native window and GL context of six backends open | Fixed 1cb5d7f5, af7f41c (openglcontext-qt) | `open()` is outside the `try`; only EGL and WGL implement `abandon()` |
| 1.2 | P2 | Qt `release()` leaves `window` set after the window is gone | Fixed af7f41c (openglcontext-qt) | Every other backend clears it; the README promises `None` |
| 1.3 | P2 | wx `mainLoop()` and `run()` never call `release()` | Fixed 3e18fc36 | Teardown depends on `EVT_WINDOW_DESTROY` having fired |
| 1.4 | P2 | EGL and WGL main loops close telemetry but not the stall journal | Fixed 3e18fc36 | One-line change to `closeJournals` |
| 1.5 | P2 | Pointer-warp mouse-look emulation is copied into GLUT, Tk and wx | Fixed 1ccda3b7 | Maintainability: hoist into `windowsystem/base.py` |
| 1.6 | P3 | Qt `release()` tells the caches the context is lost when `makeCurrent` failed | Open (confirmed) | Investigate: names may be deleted in another current context |
| 1.7 | P3 | Smaller window-system and `Context` points | Part fixed 3e18fc36, 45535af1 | wx import hint, GLUT non-freeglut path, `ContextMainLoop` positional argument, registry pointing at shim modules |
| 2.1 | P1 | `Grid.spacing` from scene content is unbounded, so a tiny value builds billions of lines | Fixed 8fe5b051 | Untrusted-input denial of service; clamp the step or the count |
| 2.2 | P2 | Declared scene views never fit their orbit limits, and two quad-view builders differ | Fixed 8e489308 | `_viewFor` skips `fit_limits`; heading 0 versus 330 degrees |
| 2.3 | P3 | `MultiviewPass.disposeResources` logs every delete failure at debug | Not a defect | |
| 3.1 | P2 | `TilesTerrain.shutdown()` disposes no ground, vegetation or cover GL objects | Fixed ad2114b4, ec2de9b (glisteel) | Leaks per world swap in a live context |
| 3.2 | P2 | Zone capture sets the clear colour and does not restore it | Fixed 14c7c38e | `ReflectionAtlas` already saves and restores it |
| 3.3 | P2 | `passes/glstate.py` is used by nothing, and OGC151, which its docstring cites, is not selected | Part fixed 14c7c38e | Maintainability: adopt it in the draw code or remove the claim |
| 3.4 | P3 | `bake_zone_lights` lists the zones once, before a streamed world has loaded them | Fixed 63b10cda | Zones outside the first view are silently never baked |
| 3.5 | P3 | `applyZones` duplicates `_applyZoneState` | Fixed 0c5554b7 | Maintainability |
| 3.6 | P3 | `ReflectionAtlas.ensure_size` leaks GL names if an allocation call raises | Fixed b2edf1bc | |
| 3.7 | P3 | `GroundCover._scatter` keys a persistent dict on `id(rung)` | Fixed 0e9938d5 | Safe today; OGC131 does not report an `id()` inside a tuple key (see 5.3) |
| 3.8 | P3 | `docs/vegetation.rst` says `canopy_spread` offsets towards the sun | Fixed c6b7c89b | The code offsets away from the sun |
| 4.1 | P2 | `LODAsset.open` reads a JSON chunk of whatever length the header claims | Fixed b061fb1b | Up to 4 GiB allocated before `max_resource_bytes` applies |
| 4.2 | P2 | A killed "within" content-pack install leaves a staging directory nothing removes | Fixed 12bd1065 | `_install_within` bypasses `atomicfiles`' leftover sweep; also shadows `name` |
| 4.3 | P3 | `oglc-view --pack` with a bad registry ends in a traceback | Fixed b6e079a9 | `BadCatalog` is a `ValueError` and is not caught |
| 4.4 | P3 | Viewer source and adapter tidiness | Open | Lock files never removed, `source.py` mixes two jobs, `PROTO` string test beside `isinstance` |
| 4.5 | P3 | Docs say pack names compare "in lower case"; the code uses `casefold` | Fixed c6b7c89b | Documentation |
| 5.1 | P2 | OGC101, OGC102 and OGC111 miss the `doc.get(k) or default` form | Fixed c5396b0 (openglcontext-checks) | Reproduced; a gate with a common false negative |
| 5.2 | P2 | OGC121 misses `pathlib.Path(...).open('w')` | Fixed 58cc800 (openglcontext-checks) | Reproduced by the reviewer |
| 5.3 | P3 | OGC131 does not report `id()` inside a tuple key | Open | Found through 3.7 |
| 5.4 | P2 | `editcheck` drops mypy messages for Windows paths | Fixed 9464a3d (workspace) | `partition(':')` splits at the drive letter |
| 5.5 | P3 | `preflight` and `editcheck` raise a traceback when a gate's executable is missing | Fixed 9464a3d (workspace) | The `--hook` exit status is then wrong |
| 5.6 | P3 | `--jobs` is ignored under 48 files; the README does not say so | Fixed 1b8dc73 (openglcontext-checks) | Documentation |
| 6.1 | P2 | `check_failing_layer` writes an inherited method onto the class it patched | Fixed fa4131ba | Order-dependent test pollution through the documented example |
| 6.2 | P3 | Display and network probes cache a transient failure for the whole run | Fixed f361b1e8 | Later tests skip for no current reason |
| 6.3 | P3 | Testing helpers reach into production globals and patch GL process-wide | Fixed e978d97a | `renderpass.FLAT = None`; `counting_gl` has no lock |
| 7.1 | P2 | Atomic file writes are hand-written in five projects beside `OpenGLContext.atomicfiles` | Fixed 760a2a8 (glisteel-editor), c8630b9 (marble-demo), 60f1cd7 (pyopengl-glut-binaries) | Maintainability; glisteel-editor and marble-demo can call the engine |
| 7.2 | P2 | A malformed route point in a glisteel-editor project raises `IndexError` | Fixed be815f16, 760a2a8 (glisteel-editor) | Contradicts `Project.open`'s documented `ValueError` |
| 7.3 | P2 | An openglcontext-editor settings test cannot fail for string choices | Fixed 5b1fe5c (openglcontext-editor) | The `or` clause is always true |
| 7.4 | P2 | Forest `profile_breakdown.py` reads scene attributes that no longer exist | Fixed 1be51fd (openglcontext-forest) | `PB_DISABLE=grass` and `clumps` raise `AttributeError` |
| 7.5 | P3 | Forest smoke test errors rather than skips when the art is not installed | Needs input | `art_directory()` raises `NotInstalled` outside the `try` |
| 7.6 | P3 | glisteel's `Stretch`/`Held` journal is generic and belongs in the engine | Open | Engine placement |
| 7.7 | P3 | Game and editor nits | Part fixed 1be51fd (forest), 01127de, bd20dba (glisteel-editor), 63e3e45 (twig-bb) | Blanket `tests/*` TID251 ignore, `split_art` without a lock, dead `COVER` alias, twig-bb README sentence, glisteel duplicates |
| 8.1 | P3 | A UV-seam vertex on the mesh border can never collapse | Fixed a02af9c (opengl_decimate) | Investigate: likely intended; needs a test that says so |
| 8.2 | P3 | Decimation and small-library nits | Part fixed e0dcf87 (opengl_decimate) | Duplicate bounds check, unguarded native call, `on_edge` invariant, simpleparse exception change, GLUT partial file |
| 9 | - | Withdrawn during validation | - | Three reported findings were not defects |

Not reviewed: omi_physics, omi_audio, marble-demo and marble-editor. Their
reviews did not complete, so this report has no findings for them; their
ranges (below) are the starting point for the next review. marble-demo
appears in 7.1 only because a glisteel-editor reviewer read its level file.

## Scope and method

The previous review (`CODE-REVIEW-2026-09-25.md`) was written against the
trees as they stood at 2026-09-25 04:49 UTC. This one covers every commit made
after that time, through these heads:

| Project | Base | Head | Commits |
|---|---|---|---|
| openglcontext | 0db17ef3 | d69e2d7a | 340 |
| openglcontext-checks | (new) | 52244e2f | 35 |
| openglcontext-qt | 805142c1 | d212a77a | 16 |
| openglcontext-editor | 5d405263 | 9dd261ce | 35 |
| opengl_decimate | cf1f72d9 | ae986d1a | 28 |
| omi_physics | cd4b762e | 8f4d88c5 | 16 |
| omi_audio | fbb7c10e | 5a84b17e | 12 |
| pyvrml97 | 0d0fe982 | 63613ab2 | 12 |
| simpleparse | 429f3dc6 | 5b1c5bb1 | 11 |
| opengl_extrusions | 40baea7c | 4ade8e51 | 8 |
| pyopengl-video | 363ec9b8 | b033af57 | 9 |
| pydispatcher | 1fb9fa0f | 7e805c8b | 6 |
| ttfquery | ac8f540e | df52dfa3 | 6 |
| pyopengl-glut-binaries | eb4786dc | 10bae027 | 4 |
| openglcontext-forest | de3821cb | d41001d7 | 14 |
| twig-bb | 8d7df607 | 8185133a | 22 |
| glisteel | 4a2137f0 | 2b63a20b | 35 |
| glisteel-editor | e4e71efb | 7b1476df | 18 |
| marble-demo | 7edc0341 | 4520f9d7 | 14 |
| marble-editor | 599c671d | a4c52ae6 | 10 |
| workspace `tools/` | | fd665d6 | 19 |

pyopengl is out of scope; it has its own review. omi_physics, omi_audio,
marble-demo and marble-editor are listed for their ranges but were not
reviewed. Uncommitted edits in the
working trees are not reviewed.

Most of openglcontext's 62,000 inserted lines are the fixes for the previous
review, the window-system composition (`windowsystem/`), the multi-view
rework and tests. Reviewers were assigned by area and read the diffs; every
P1 and P2 finding above was then checked against the code at the head
commit, and the checker findings were reproduced with `oglc-check`. The
declared gates (`tools/preflight.py`) were not run for this review.

## Overall

The window-system composition is the largest structural change, and it does
what it set out to do: the ten `*interactivecontext.py`/`*vrmlcontext.py`
modules are one-line aliases, each backend implements one `WindowSystem`
protocol, and openglcontext-qt is a thin package on the same protocol. The
multi-view layout, gestures and grid are plain objects with no GL, and their
tests reach them without a window. Several game capabilities moved into the
engine in this range (content screens, publishing, vehicle audio, document
values), and the libraries' changes are mostly narrowed exception handling,
typing and atomic writes.

What the new structure has not yet carried through is lifetime handling at
the protocol's edges (1.1 to 1.4). The protocol has an `abandon()` hook, but
four of the six windowed backends implement none, and the caller does not
cover the call that most needs it. The second theme is duplication that the
engine already has an answer for: atomic writes in five places (7.1), the
pointer warp in three backends (1.5), and zone-state application twice in one
file (3.5). The third is the checker: `openglcontext-checks` is now a release
gate, so its false negatives (5.1 to 5.3) are defects in the gate.

## 1. Window systems and `Context`

### 1.1 A failed `Context.__init__` leaks the window (P1)

`OpenGLContext/context.py:455` calls `self.windowsystem.open(definition,
parent)` on the line before the `try:` whose `except BaseException` calls
`self.windowsystem.abandon()`. An exception from `open()` after it made a
native window (for example GLFW's `make_context_current` or `applyVSync`,
`windowsystem/glfw.py:185-196`) skips `abandon()`. An exception later in
`__init__` does reach `abandon()`, but `abandon()` is the base class's no-op
(`windowsystem/base.py:114`) for GLFW, GLUT, Tk, wx, pygame and Qt; only
`egl.py:723` and `wgl.py:263` implement it. For Qt that leaves a visible
top-level `QWindow` and a `QOpenGLContext` for the collector to destroy, the
order `release()`'s own docstring says crashes.

Remediation: move the `open()` call inside the `try`, and implement
`abandon()` in each windowed backend to destroy what `open()` made without
touching the engine's caches. Add one test per backend that raises from
`setupCallbacks` and asserts the window is gone.

### 1.2 Qt `release()` keeps `window` (P2)

`openglcontext-qt/OpenGLContext_qt/windowsystem.py:462-485` drops `glContext`
but never sets `self.window = None` or destroys the `QWindow`. `context.window`
therefore stays a closed window after release, and `container()` can wrap it
again. Remediation: `window, self.window = self.window, None` and destroy it
after the GL context goes, as `glfw.py` does.

### 1.3 wx main loop never releases (P2)

`windowsystem/wx.py:358-401`: both `finally` blocks close the journals and
nothing else, while `base.py:303-304`, `tk.py:411-412`, `egl.py` and `wgl.py`
also call `self.release()`. A main loop ended by `wx.Exit()` or an embedding
host's `ExitMainLoop()` without destroying the canvas never frees the context
or the engine's GL objects. `release()` is idempotent, so adding it is safe.

### 1.4 EGL and WGL leave the stall journal open (P2)

`egl.py:700` and `wgl.py:241` call `context.stopTelemetry('mainloop-ended')`
where every other backend calls `closeJournals`, which also closes
`stallJournal`. An offscreen batch run with `OPENGLCONTEXT_STALL_TRACE` set is
left with an unfinished trace.

### 1.5 Pointer-warp emulation in three copies (P2, maintainability)

`glut.py:339-384`, `tk.py:275-326` and `wx.py:266-319` each hold
`pointerGrabbed`, `pointerWarpedTo`, `recentrePointer`, `pointerWarpEcho` and
the matching part of `setPointerCapture`, with near-identical docstrings. Move
the state machine into a mixin in `windowsystem/base.py` that takes the
toolkit's warp call, and test it there without a window.

### 1.6 Qt releases caches with no current context (P3, investigate)

`openglcontext-qt/.../windowsystem.py:475-481`: when `makeCurrent` fails,
`releaseContextResources(None)` still runs, and
`contextresources.context_lost()` deletes names in whatever context is
current. Confirm what is current at that point; if another context can be,
drop the caches' names without deleting them.

### 1.7 Smaller points (P3)

- `wx.py:26-27` imports `wx` with no install hint, unlike glfw, pygame and tk.
- `glut.py:429-432`: the non-freeglut path returns `glutMainLoop()` without
  the `closeJournals`/`release` the freeglut path runs.
- `Context.ContextMainLoop` (`context.py:1315-1327`) reads a positional first
  argument as the definition; `wxContext.__init__` takes `parent` first. No
  caller does this today; say so in the docstring or reject it.
- The `InteractiveContext` plugin registry (`OpenGLContext/__init__.py:77-83`)
  names the compatibility modules rather than the `*context.*Context`
  classes, which keeps those modules in use.

## 2. Multi-view

### 2.1 Unbounded grid from scene content (P1)

`Grid.spacing` is an `SFFloat` a loaded scene sets (`multiview/grid.py:174`).
`linesFor` passes `float(self.spacing) or None` to `lines_for`, which computes
`count = ceil(reach / step)` and loops `range(-count, count + 1)` twice
(`grid.py:125-156`). Zero falls back to the automatic step; `1e-9` does not,
and one `Render()` builds a list sized by `reach / 1e-9`. Clamp `step` to a
fraction of `spacing_for(shown, height)` (or cap `count` at a few thousand)
and add a test with a tiny spacing.

### 2.2 Scene views never fit their limits; two quad builders (P2)

`multiview/mixin.py:100-108` builds each `scene` or gestured perspective view
as `OrbitView(nearest=1e-6, lowest=-OrbitView.HIGHEST)` and never calls
`fit_limits`, while `QuadView.frame` (`quad.py:141`) and `point_view`
(`cameras.py:356`) do. Framing a scene larger than `OrbitView.FURTHEST`
clamps the distance. `QuadView.__init__` and `_viewFor` also build the same
four-view set independently, one with `OPENING_HEADING` and one with heading
0. Build the framed orbit camera in one function both call, and have
`frameViews` fit limits.

The lazy `OrbitView` import inside `_viewFor` (and `viewchrome._ownCamera`)
has no stated reason; give it one or hoist it.

### 2.3 Debug-level catch-all on delete (P3)

`passes/multiviewpass.py:154-162` logs any `glDeleteBuffers` failure at
debug. Narrow it to the context-lost case `contextresources` already detects.

## 3. Render passes and scenegraph

### 3.1 `TilesTerrain.shutdown` disposes nothing drawn (P2)

`scenegraph/tilesterrain.py:379-383` stops the loaders and the scatter thread.
`SplatTerrain.dispose` (`terrain/splat.py:238`) and the vegetation nodes'
`dispose` methods (`billboards.py:122`, `nearmesh.py:176`, `clumps.py:305`)
are never reached, and neither `VegetationField` nor `GroundCover` has a
`dispose` to forward to them. A game that swaps worlds in one context leaks
every terrain and vegetation buffer, texture and program. Add `dispose` to
both containers and call it from `shutdown`, with a test counting live GL
names across two worlds.

### 3.2 Zone capture changes the clear colour (P2)

`passes/zoneprobes.py:299-311`: `face()` sets `glClearColor(0, 0, 0, 1)` and
`end()` does not restore it. `ReflectionAtlas.clear` saves and restores
`GL_COLOR_CLEAR_VALUE` for the same kind of clear; do the same here, or use a
`glstate` manager (3.3).

### 3.3 `glstate.py` is unused, and its rule is not selected (P2)

`passes/glstate.py` provides state save/restore managers and says OGC151
holds the engine's draw code to them. Nothing outside its unit test imports
it, and openglcontext's `[tool.openglcontext-checks] select`
(`pyproject.toml:443`) omits OGC151, though the file configures OGC151's
scope. Either adopt the managers at the raw `glEnable`/`glBindFramebuffer`
sites this range added (3.2 is one) and select OGC151, or remove the claim.

### 3.4 Zone bake misses zones that stream in later (P3)

`passes/zonebake.py:150-153` builds the `ZoneBakePlan` from `flat.zones` after
one draw at the starting camera. A zone whose tile has not streamed in at
that point is never captured and is not in `plan.missed`. Re-scan after
`before_frame`, or state in `docs/zones.rst` that the caller loads the world
first.

### 3.5 Zone state applied twice (P3, maintainability)

`passes/zonepass.py:561-592` repeats `_applyZoneState` (`633-645`) with a
redundant `is not ... and !=` test. End `applyZones` with a call to
`_applyZoneState`.

### 3.6 Atlas allocation leaks on error (P3)

`passes/reflectionatlas.py:100-129` releases only when the framebuffer is
incomplete. An exception from `glTexStorage2D` or `glRenderbufferStorage`
leaks the names already generated; release in an `except` and re-raise.

### 3.7 `id(rung)` as a key (P3)

`scenegraph/vegetation/cover.py:685` keys `self._blocks` on `(id(rung),
role)`. `rung` is held elsewhere for the dict's life, so it is safe today;
key on `rung` itself. OGC131 did not report it (5.3).

### 3.8 `canopy_spread` direction (P3, documentation)

`docs/vegetation.rst:342` says the shadow is offset towards the sun;
`terrain/splat.py:30` and `:59` say away from it, along the light. Correct
the page.

## 4. Loaders, content packs and the viewer

### 4.1 Unbounded GLB JSON chunk (P2)

`loaders/gltf/lodasset.py:125-128` calls `handle.read(json_length)` with the
32-bit length from the file header. A buffered `read(n)` allocates `n`
bytes before reading, so a corrupt or crafted file asks for up to 4 GiB before
`max_resource_bytes`, which every other read in the class honours, is
consulted. Check `json_length` against the file size and `max_resource_bytes`
first, with a test using a short file that claims a large chunk.

### 4.2 "Within" installs leave staging directories (P2)

`contentpacks/store.py:184-202`: `_install_within` makes its own
`.<name>.partial-*` directory with `tempfile.mkdtemp` and removes it in a
`finally`. A killed process leaves it for good, because only
`atomicfiles.staged_directory` calls `_remove_leftovers`. Sweep leftovers at
the start of `_install_within` (make `_remove_leftovers` public in
`atomicfiles`). The loop `for name in files` also reuses `name` from the
`os.path.split` above it; rename one.

### 4.3 `oglc-view --pack` traceback (P3)

`bin/view.py:370-371` catches `(IOError, UnknownMember)`; a missing or
malformed registry raises `catalog.BadCatalog` (a `ValueError`). Catch it and
report through `parser.error`.

### 4.4 Viewer tidiness (P3)

- `viewer/source.py:150-155` leaves one `.lock` file per archive ever opened
  in the cache directory.
- `viewer/source.py` now resolves archive members and fetches content packs;
  the module docstring describes only the first. Split `pack_named`/`open_pack`
  into their own module or update the docstring.
- `viewer/adapters/scenegraph.py:62-79` identifies `WorldInfo` by its `PROTO`
  string while the next method uses `isinstance`.

### 4.5 Case folding (P3, documentation)

`docs/contentpacks.rst` says names are compared in lower case; `store.py:322`
uses `casefold()`. Say "case-folded".

## 5. openglcontext-checks and the workspace tools

### 5.1 `get(...) or default` passes three rules (P2)

`rules/ogc101_bare_document_conversion.py:102-121` (`named_field`, shared by
OGC102 and OGC111) recognises a subscript or a `.get()` call, not a `BoolOp`.
In the `loader` scope, `float(extras.get('rate'))` is reported and
`float(extras.get('rate') or 1.0)` is not; the same holds for
`open(spec.get('card') or 'x.png')`. Unwrap `BoolOp` and `IfExp` operands
before testing, and add both forms to the rule tests.

### 5.2 `Path.open('w')` passes OGC121 (P2)

`rules/ogc121_write_in_place.py:194-221` knows the stream functions and
`write_text`/`write_bytes`, but not `Path(...).open('w')`. Add it, reading the
mode as for `open`.

### 5.3 OGC131 misses `id()` inside a tuple key (P3)

The rule did not report `slot = (id(rung), role)` used as a dict key (3.7).
Extend it to `id()` calls inside a tuple that is used as a key.

### 5.4 `editcheck` loses Windows mypy messages (P2)

`tools/editcheck.py:343` takes the path as everything before the first colon,
so `C:\...` becomes `C`, fails `_inside`, and the message is dropped for
projects with `follow_imports = "silent"`. Match mypy's
`^(.+?):(\d+):` prefix instead, and add a drive-letter test.

### 5.5 Missing executable (P3)

`tools/editcheck.py:352-358` and `tools/preflight.py:413-423` let
`FileNotFoundError` from `subprocess.run` escape. Report it the way an
unbuilt typecheck environment is reported, with the documented exit status.

### 5.6 `--jobs` threshold (P3, documentation)

`runner.py:150-153` runs sequentially under `PARALLEL_THRESHOLD` (48) files
whatever `--jobs` says. Say so in the README and the help text, or let an
explicit `--jobs` override it.

## 6. Test support (`OpenGLContext/testing`)

### 6.1 `check_failing_layer` leaves an inherited method on the class (P2)

`testing/layers.py:117-130`: when `owner` is a class and `name` is inherited
(`held` is `None`), the `finally` does `setattr(owner, name, original)`,
copying the base's method onto `owner`. The module's own example patches
`type(context.renderPass)._renderReflections`, which is defined on
`ReflectionsMixin`, so after one use a later patch of the mixin no longer
reaches `FlatPass`. When `held` is `None`, `delattr` in both cases. The same
function deletes `context.triggerRedraw` unconditionally rather than
restoring an existing instance attribute.

### 6.2 Probes cache transient failures (P3)

`testing/glcontext.py:163-173` (`_client_opens`, `lru_cache`) and
`testing/network.py:32-63` (`_HOSTS`) remember a failed probe for the whole
process, so one timeout under load skips every later test for that display or
host. Cache successes only.

### 6.3 Helpers reaching past public APIs (P3)

`testing/scenes.py:103-108` sets `renderpass.FLAT = None` directly; give
`renderpass` a reset function, or rely on the context-lost hook and fix it if
it does not fire. `testing/stillframe.py:94-152` (`counting_gl`) replaces GL
entry points in every loaded module with no lock; document that it is
single-threaded or take a lock.

## 7. Games, editors and cross-project duplication

### 7.1 Atomic writes written five times (P2, maintainability)

`glisteel-editor/glisteel_editor/project.py:332-368` and
`marble-demo/src/openglcontext_marble_demo/levelfile.py:256-278` hand-write
the `mkstemp`/`os.replace` sequence that `OpenGLContext.atomicfiles.write_text`
implements, and glisteel-editor's `bake.py` already uses `atomicfiles` in the
same commit. Both should call the engine. ttfquery (`ttffiles.py`),
opengl_extrusions (`mesh.py:661`) and pyopengl-glut-binaries
(`tools/buildgledll.py`, which also leaves the `.partial` file on a failed
write) sit below OpenGLContext and cannot import it; each of those copies is
small, but they should share one shape, and the glut-binaries one needs its
cleanup.

### 7.2 Malformed route point in a project file (P2)

`glisteel-editor/glisteel_editor/project.py:225`:
`points=[(float(p[0]), float(p[1])) for p in document.get('points', ())]` was
not moved to `DocumentValues` with the other fields, so `[[1, 2], [3]]`
raises `IndexError` out of `Project.open`, whose docstring promises a
`ValueError` naming the file. The file is in the loader scope, but the
comprehension's subscript is by a number, so OGC101 does not report it. Read
points through `DocumentValues`.

### 7.3 A settings test that cannot fail (P2)

`openglcontext-editor/tests/test_world_settings.py:28-30` asserts
`set(choices) == set(get_args(hint)) or all(isinstance(c, str) for c in
choices)`. Every setting with choices has string choices, so the comparison is
never needed. Drop the `or` branch. OGC221 to OGC223 do not catch an
always-true `or` inside an assertion; worth a rule.

### 7.4 Forest profiler reads removed attributes (P2)

`openglcontext-forest/tools/profile_breakdown.py:36-39` calls
`kill(sc.grass)`, `sc.grass_far`, `sc.clumps_near` and `sc.clumps_far`;
`ForestScene` now has one `cover` field. `PB_DISABLE=grass` or `clumps`
raises `AttributeError` in `OnInit`. This range edited the same function.
Route through `sc.cover` and update the docstring's list.

### 7.5 Forest smoke test (P3)

`openglcontext-forest/tests/test_config.py:102` calls `art_directory()` before
the `try`; with neither the pack nor the checkout's assets present it raises
`NotInstalled` and the test errors. Decide what the test needs (the pack, or
LFS assets in CI) and make the suite provide it rather than adding a skip.

### 7.6 `Stretch`/`Held` belong in the engine (P3)

`glisteel/glisteel/driver.py:239-278` folds a changing reason into named
stretches for a journal, with no glisteel coupling. It sits naturally beside
the `Keeping`/`Tee` journal helpers that moved to the engine in this range.

### 7.7 Game and editor nits (P3)

- `glisteel-editor/pyproject.toml:127` exempts all of `tests/` from TID251,
  though no test uses a banned call; use per-line `noqa` with reasons.
- `glisteel-editor/glisteel_editor/bake.py:157-190` (`split_art`) stages a
  shared directory without the `file_lock` `staged_directory` asks for.
- `openglcontext-forest/.../scene.py:53`: `COVER = COVER_MANIFEST` is unused.
- `twig-bb/README.md:580` runs two sentences together ("this says which The
  switch is read once").
- glisteel: `StandIn.refused` passes a dummy `at=0.0` to `Stretch.hold`
  (`driver.py:1570`); `_baked_props` and `_baked_stones` (`world.py:485-515`)
  differ only in a key; `reflections.py:178` overruns the file's wrap width.
- openglcontext-editor: `ZonesLayer._writer` (`bake/zones.py:186-190`) calls
  `_played()` only for its exception; `_portal_funnel` (`world/road.py:519-544`)
  is quadratic in portals without saying it assumes few.

## 8. Libraries

### 8.1 Seam vertices on the border (P3, investigate)

`opengl_decimate/src/opengl_decimate/collapse.py:90` refuses a collapse from a
vertex with UV copies unless `along_a_seam` holds, and `along_a_seam`
(`topology.py:364-370`) needs two faces on the edge. A seam vertex on the
mesh border therefore never moves along the border, in every mode. That is
probably right (it is where a seam meets the outline), but no test says so;
add one that pins the behaviour, or allow the collapse when both ends share
the chart.

### 8.2 Decimation and small-library nits (P3)

- opengl_decimate: the locked-index bounds check is in both
  `reduction.py:484-488` and `topology.py:430-436` with different wording;
  `native.ends_given_up` (`native.py:117-133`) raises `AttributeError` rather
  than `DecimateError` without the accelerator; the Cython seam check reads
  `on_edge` several calls after filling it, with no comment at the read.
- simpleparse: `dispatch()` (`dispatchprocessor.py:52`) now lets a custom
  mapping's own exception propagate instead of wrapping it; note it in the
  changelog.
- pyvrml97, pydispatcher, ttfquery, opengl_extrusions and pyopengl-video:
  no defects found. Exception handling was narrowed correctly, and no test
  assertion was weakened.

## 9. Withdrawn during validation

- Shadow caster cache keyed on `id()` without an identity check
  (`passes/shadowmixin.py:957`): each entry holds the transform and volume it
  was derived from, so those objects cannot be collected and their ids reused
  while the entry exists. Not a defect.
- `ProceduralWorld.SETTINGS` has no reader: glisteel-editor's `recipe.py`
  reads it.
- Viewer tile priming without a view-projection
  (`viewer/adapters/tiles.py:266`): the code predates this range.

## Work log

- 2026-09-27: 1.1 fixed. `Context.__init__` opens the window system inside
  the `try` that abandons it; GLFW, GLUT, pygame, Tk, wx and Qt implement
  `abandon()`, and each `release()` is the cache announcement followed by
  `abandon()`. The contract is in `docs/backends.rst`. wx's `abandon` is
  checked statically only (wx is not installed here). An embedded Tk or wx
  view's widget stays with its host on abandon; only a top-level window this
  made is destroyed.
- 2026-09-27: 1.2 fixed with 1.1. Qt's `release()` clears `window` and holds
  the `QWindow` in `closing` until `quit()` closes it, because release runs
  inside the window's own close event.
- 2026-09-27: 2.1 fixed. `lines_for` coarsens a pinned step by decades to at
  most `MAXIMUM_LINES` (200) each side of the middle, keeping the lines on
  multiples of the spacing; a non-positive or non-finite spacing is the
  automatic step. `docs/multiview.rst` states the bound.
- 2026-09-27: 1.3 and 1.4 fixed: wx's mainLoop and run release in their finally; EGL and WGL call closeJournals. From 1.7, GLUT's non-freeglut loop closes the journals and releases. A static test holds every backend's mainLoop (and a run that drives the toolkit's loop) to both. 1.5 fixed: `WarpedPointer` in `windowsystem/base.py` is the one pointer warp; GLUT, Tk and wx supply the middle and the warp call. Documented in `docs/backends.rst`. Rest of 1.7 open: wx import hint, ContextMainLoop positional argument, plugin registry names.
- 2026-09-27: 2.2 fixed: `fit_view` fits an orbit camera's limits to the box on every framing, covering QuadView, the mixin and any other caller. The second half of the finding is not a defect: `startViews`' perspective view draws through the window's own camera by design, and the mixin's orbit cameras are for declared `scene` or gestured views, not a copy of QuadView's set. The lazy OrbitView import is hoisted.
- 2026-09-27: 3.1 fixed: `GLLayer` declares `dispose()` (ParticleEmitter's `delete` renamed to it); `instancedgl.dispose_subtree` walks children and geometry; `TilesTerrain.dispose()` gives back ground, trees and cover. glisteel's `RaceWorld.shutdown` now stops the cover's thread too (it stopped only the tile runtime) and closing a world disposes it. Documented in `docs/loading.rst`.
- 2026-09-27: 3.2 fixed: CaptureTarget saves and restores the clear colour with the framebuffer and viewport, held by a GL test. 3.3 in part: glstate's docstring now says what OGC151 does. Open: openglcontext has 176 OGC151 findings (15 in selectionbuffers.py, 15 in bloom.py, 12 in spherebackground.py, 11 in reflectionatlas.py, ...); moving them onto the glstate managers and selecting OGC151 is the ratchet in DEFECT-PREVENTION.md, not a single fix.
- 2026-09-27: 4.1 fixed: the declared JSON length is checked against the file size before the read (not against max_resource_bytes, which is per buffer or data URI and which existing tests set to 8 bytes). 4.2 fixed: `atomicfiles.scratch_directory` sweeps leftovers and always removes its directory; `staged_directory` and `_install_within` use it, and the shadowed `name` is gone.
- 2026-09-27: 5.1 fixed: `named_field` looks through `or`/`and` and conditional expressions, so OGC101 and OGC111 report `x.get(k) or default`; OGC102 already walked inner expressions. No project that selects these rules gained a finding. 5.2 fixed: OGC121 reports `<path>.open(mode)` with a literal write mode (letters limited to `rwxabt+`, so a member name is not taken for a mode). It found three journals written in place on purpose, the stall trace and telemetry journal (openglcontext db459d85) and the MP4 recorder (pyopengl-video aa2e40e), which now carry reasoned noqa comments.
- 2026-09-27: 5.4 and 5.5 fixed in the workspace root: editcheck matches mypy's message prefix with a regex that allows a drive letter; a missing gate executable is a note in editcheck and a status-127 failure in preflight.
- 2026-09-27: 6.1 fixed: the stand-in is removed unless the owner held the attribute itself, and an existing triggerRedraw override is restored.
- 2026-09-27: 7.1 fixed where the engine can be used: glisteel-editor's Project.save and marble-demo's levelfile.save call `atomicfiles.write_text`; pyopengl-glut-binaries' build script writes through one `whole()` helper that removes a partial file on failure. ttfquery and opengl_extrusions sit below OpenGLContext and keep their own few lines, which already clean up. 7.2 fixed: `DocumentValues.vectors` (new, in `docs/untrusted.rst`) reads a list of points, leaving out and reporting a bad one; glisteel-editor's Route.from_json uses it. The preflight run started earlier failed on tests caught mid-edit (a wx import before WarpedPointer existed, two tests before their fixes); those tests pass now, and a fresh preflight run is still to do.
- 2026-09-27: 7.3 fixed: the choices are compared with the Literal alone. 7.4 fixed: `subsystem_nodes` in the profiler reads grass and clumps from `ForestScene.cover`'s rungs, is tested without a window, and an unknown PB_DISABLE name stops the run. From 7.7, the dead COVER alias is removed. 7.5 needs input: the smoke test passes here because the art is installed. On a machine without it, `art_directory()` raises NotInstalled and the test errors. Should such a machine skip it (which the workspace rules discourage) or fail it, as it does now? Or should CI fetch the pack first?
- 2026-09-27: 3.7, 3.8, 4.3, 4.5 and 5.6 fixed. 5.3 stays open, and the gap is wider than tuples: OGC131 follows no local name at all, so `key = id(x); table.get(key)` passes as `slot = (id(x), r); table[slot] = v` does. Every exemption the rule makes (the entry holds the object, the table is temporary, the lookup compares identity) is judged from where the `id()` call sits, so following a name means judging them at each use of it instead. That is a rework of the rule, not a one-line fix.
- 2026-09-27: 3.5, 3.6 and 6.2 fixed. 2.3 is not a defect: logging a failed teardown delete at debug with its traceback is the disposal convention `passes.disposal.let_go` states, since nothing can act on it then. 1.7: the wx install hint is fixed (45535af1). Question for the maintainer on the rest of 1.7: `ContextMainLoop` reads a positional first argument as the definition, while `wxContext.__init__` takes `parent` first. Should the definition become keyword-only there? And should the `InteractiveContext` plugin registry name the `*context.*Context` classes rather than the compatibility modules? Both change a public entry point.
- 2026-09-27: 1.6 confirmed and wider than Qt: Qt, Tk and wx each call `releaseContextResources(None)` when they cannot make their own context current, and `contextresources.context_lost()` then runs every cache's callback against whatever context is current, dropping (and deleting) a live context's names. Skipping the call would leave the dead context's entries under a key the driver can hand out again. The fix is a `context_lost` told which context is going, so a cache forgets that context's names without deleting them. The callbacks take no argument today, so this changes the registration API in `contextresources` and every cache registered with it.
- 2026-09-27: 3.4 fixed: `ZoneBakePlan.extend` and a rescan after every frame. 8.2 in part: decimate's compiled entry points raise DecimateError without the accelerator. 7.7 in part: glisteel-editor's tests are no longer exempt from TID251 (none needed it), and `split_art` locks each directory from check to copy; twig-bb's README sentence is fixed; the forest's dead alias is gone.
- 2026-09-27: Preflight over every project this work touched: 50 of 52 gates passed. The two failures came from this work and are fixed. The wx install hint raised a plain ImportError, which `pytest.importorskip` does not skip; it now raises ModuleNotFoundError (ae854cb5). OGC121's wider rule found verify-everything's run log, which now carries a reasoned noqa (workspace 902ce9c). Both gates pass on a rerun, and the oglc-check gate passes in every other project that declares it.
- 2026-09-27: 6.3 fixed: `counting_gl` raises rather than nesting or racing, and the scene helper leaves the pass to the context's teardown (a new test holds that the pass goes with the context). 8.1 settled as intended and pinned by tests. The review's reading was partly wrong: what keeps a seam's end on the outline is the equal-copies rule, since its outline neighbours are drawn once; the seam rule only matters between two seam points. A mutation check showed the test fails once both rules are removed.
