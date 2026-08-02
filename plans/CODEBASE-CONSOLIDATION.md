# Codebase Consolidation — shrinking OpenGLContext

**Status:** 🟡 Partially executed — Tier A, B1, B2, B3, B4 and B5a landed
(2026-08-01) and B6 (2026-08-02). B5b declined by design; C1 still open.

| Item | State |
|---|---|
| A — dead modules | 🟡 Partial — `nurbsshader`, `move/fps`, `passes/flat` removed; `tkevents`/`fxevents` and the dead `resources/*` blobs still to go |
| B1 — `browser/` + `oglc-visual` | ✅ Done; `appdatadirectory` → `OpenGLContext/userpaths.py` |
| B2 — `shadow/` stencil volumes | ✅ Done |
| B3 — `scenegraph/tree/` | ✅ Done |
| B4 — visiting render passes | ✅ Done; `docs/renderprocess.html` retired |
| B5a — `DisplayListCompiler` | ✅ Done |
| B5b — legacy scenegraph renderer | ⛔ Declined — supported backends reach their font providers through it |
| B6 — `oglc-view` consolidation | ✅ Done — one viewer, four formats, a library and a menu ([ONE-VIEWER.md](ONE-VIEWER.md)); `oglc-terrain` still its own |
| C1 — housekeeping | 📋 Open |

**Measured result so far:** the package went from **75,045 to 68,923 lines
(−6,122, −8.2%)** — net of the 48-line `userpaths.py` added — plus 386 lines of
demos and a 543-line documentation page. Verified at each step: full unit suite
**3,825 passed / 0 failed**, ruff clean on every file touched, and both profiles
rendering live (`nurbsobject`, `molehill`, `transparentsorted`, `point_and_click`
through the compatibility pass; `shadow_demo`, `teapot_ceramic`, `lod_demo`
through core/PBR).

---

The package was **75,045 lines** of Python across 20 sub-packages when this was
written, with a further **74,998 lines** under `tests/`. A material fraction of
that served code paths nothing reached any more, or that duplicated a newer path
better in every respect. This document records what to remove, states precisely
**what would be lost** in each case, records **what depended on it**, and orders
the work so each step is independently shippable.

Nothing here is a bug fix. Every item is a deliberate reduction in what the project
promises, so each one names the promise being withdrawn.

## Constraint: the supported platforms are not on the table

**GLFW, GLUT, Pygame, wxPython and Qt/PySide (via the separate `OpenGLContext_qt`
project) are first-class targets.** Breaking one is a regression, not a cleanup.
Platform-specific code is supported on the platform it targets whether or not this
machine can run it — `text/wglfont.py` is Windows font support and is expected to
work on Windows.

This is now stated in `readme.txt` ("Supported GUI backends") and
[docs/structure.html](../docs/structure.html), so the question does not have to be
re-answered from inference next time. Verified while writing this: **all four
in-tree backends already request a core profile** when asked
(`glfwcontext.py:160`, `glutcontext.py:44`, `pygamecontext.py:76`,
`wxcontext.py:163`), so no backend stands in the way of making `core` the default
profile — which is what B5 turns into once the platform commitment is applied.

The rule this imposes on everything below: *low usage in this checkout is not
evidence of deadness for anything platform-specific.* Several candidates in an
earlier draft of this document failed that test and have been withdrawn — see
[Withdrawn candidates](#withdrawn-candidates).

## Method

Findings come from an AST import graph over all 858 Python modules in
`OpenGLContext/` and `tests/`, cross-checked against the string-keyed plugin
registries in `OpenGLContext/__init__.py` (which the import graph cannot see), the
console-script table in `pyproject.toml`, and the HTML under `docs/`. Where a
module is reached only by a string name or an entry point, that is stated.

## Summary of the proposal

| # | Item | Lines | Risk | What is withdrawn |
|---|------|-------|------|-------------------|
| A | Dead modules (no reference of any kind) | ~915 | none | nothing |
| B1 | `browser/` + `oglc-visual` | ~1,520 | low | unfinished VPython API, wx demo shell |
| B2 | `shadow/` (stencil shadow volumes) | ~1,150 | low | stencil-volume shadow example |
| B3 | `scenegraph/tree/` (volumetric tree) | ~1,254 | low | procedural tree generator |
| B4 | Visiting render passes | ~1,710 | low\* | pluggable multi-pass architecture |
| B5a | `DisplayListCompiler` — unreachable by weighting | ~110 | none | nothing |
| B5b | Legacy scenegraph renderer — **decision required** | ~1,900 | **high** | compatibility-profile scenegraph rendering |
| B6 | Viewer consolidation into `oglc-view` | ~700 net | medium | four CLI names (aliasable) |
| C1 | `bin/` non-tools, second test root, packaging leftovers | ~700 | none | nothing |

\* low **only if sequenced after B1 and B2** — they are its last two consumers.

Realistic total: **~8,060 package lines (10.7%)** if B5b is declined — which is the
recommendation — or **~9,960 (13.3%)** if it is taken. Plus 386 lines of demos, one
documentation page retired, and four console scripts folded into one.

An earlier draft claimed 10–12 k by also proposing to remove WGL fonts, `glutfont`,
`wxfont` and the wxPython backend. Those are supported-platform code and have been
withdrawn; the difference between the two figures is the cost of the platform
commitment, and it is worth paying.

---

## Tier A — dead code, nothing lost

Each of these has **zero** importers, zero plugin registrations, zero entry points
and zero documentation references. They are deletions, not decisions.

| Module | Lines | Note |
|--------|-------|------|
| `scenegraph/nurbsshader.py` | 387 | Superseded by [scenegraph/nurbstess.py](../OpenGLContext/scenegraph/nurbstess.py), which does the same job (GLU tessellator callbacks → VBO) and *is* wired into `nurbs.py`. Two implementations of one idea; only one is reachable — **verified four ways, see below.** |
| [events/tkevents.py](../OpenGLContext/events/tkevents.py) | 171 | Tk event translation. There is no `tkcontext.py` and no Tk entry in the `Context` plugin registry, so it can never be constructed. |
| [events/fxevents.py](../OpenGLContext/events/fxevents.py) | 89 | Same, for the FOX toolkit. |
| `move/fps.py` | 13 | Superseded by `move/modes.py`'s declared `WalkMode`/`FlyMode`. |
| `passes/flat.py` | 5 | A shim that imports `flatcore` and `flatcompat` for side effects nobody needs. |
| `resources/{disk_icon,disk_icon_hi,green_arrow_right,red_arrow_right,pygame_icon}_png.py`, `resources/{available_contexts,simpleshader_vert,simpleshader_frag,lights_vert,legacy_lighting_vert}_txt.py` | ~250 | `resourcepackage`-generated base64 blobs. Only `context_icon*_png` (wx window icon) and `phongprecalc_vert`/`phongweights_frag` (shader tutorials) are live. Delete the dead modules *and* their source `.png`/`.svg`/`.txt` files. |

**How:** straight `git rm`. The only follow-up is deleting the `resourcepackage`
scan block in [resources/\_\_init\_\_.py](../OpenGLContext/resources/__init__.py),
which references a build-time tool that is not a declared dependency.

#### Evidence for `nurbsshader.py`, since it is the largest Tier A item

A module-name grep is weak evidence — a name can be reached by string, by
`import *`, or from a `.wrl`. So this one was checked four ways, and all four agree:

1. **By every name it defines, workspace-wide.** `NURBSTessellator`,
   `NURBSShaderGeometry`, `get_tessellator`, `tessellate_and_cache`, `_tessellator`
   — searched across `.py`, `.wrl`, `.html`, `.md`, `.txt`, `.toml`, `.json` in
   every sibling project too. **Zero hits** outside the file. (`NURBSTessellator`
   appears to match `nurbstess.NURBSTessellatorCallback`, which is a *different
   name* the substring catches — the live class, not this one.)
2. **Whole-repo, all file types including binaries** — `nurbsshader` appears in no
   file in the repository other than these two plan documents.
3. **Not reachable dynamically.** The package has exactly three dynamic-import
   sites, and none can name it: `extensionmanager.py:127` (GL extension modules),
   `text/fonts/__init__.py:51` (font atlases), `loaders/loader.py:158`
   (`OpenGLContext.resources.%s`). The `Node()` registry lists five NURBS nodes,
   all `scenegraph.nurbs.*`.
4. **Runtime.** Importing `OpenGLContext` plus `basenodes`, `nurbs`, `nurbstess`,
   `nurbssampling`, `nurbstrim`, `teapot_nurbs`, `flatcore`, `pbrpass`,
   `shaderpass`, `vrmlcontext` and `testingcontext` loads 779 modules;
   `nurbsshader` is not one of them. Then **rendering `tests/nurbsobject.py` for
   real** (GLFW, trimmed multi-coloured NURBS surface) loads exactly
   `nurbs`, `nurbssampling`, `nurbstess`, `nurbstrim` — and not `nurbsshader`.
   The 78 NURBS unit tests pass without it.

The two modules were written for the same purpose — the docstrings both describe
"GLU tessellator callbacks → VBO for core profile" — and `nurbstess.py` is the one
that got wired into `nurbs.py`. `nurbsshader.py` was last touched by commit
`034a34e` ("CLEANUP Pre-release cleanup started") and has never been imported since.

---

## Tier B — the named candidates

### B1. `browser/` — the wx VRML browser and the VPython emulation

**What it is.** 1,226 lines plus 213 lines of `browser/tests/`. Two unrelated
things share the directory: a wxPython VRML "browser" shell
(`browsercontext.py`, `passes.py`, `defaultbindings.py`, `interactivity.py`,
`nodes.py`, `proxy.py`), and an unfinished re-implementation of the VPython
`visual` API (`visual.py`, `vector.py`, `vpcurve.py`, `geometry.py`,
`crayola.py`). `readme.txt:92` already describes the latter as partial work.

**What depends on it today.**

| Consumer | What it takes |
|---|---|
| `bin/visualshell.py` (`oglc-visual`) | `browser.browsercontext` |
| [contextconfig.py](../OpenGLContext/contextconfig.py) | `browser.homedirectory.appdatadirectory` **only** |
| [loaders/resolver.py](../OpenGLContext/loaders/resolver.py) | same |
| `tests/unit/test_gltf_loader.py`, `tests/unit/test_resolver_extra.py` | same |

So the entire package is held in place by one 76-line helper that answers "where
is this user's config directory". `browser/passes.py` is also one of the two last
consumers of the visiting render passes (B4).

**What would be lost.** `oglc-visual`, a wxPython demo-launcher shell, and the
VPython-compatible API, which was never finished and which no demo, test or
document uses.

**This is not a reduction in wx support**, and the distinction matters given the
platform commitment above. wxPython coverage lives in the backend itself
(`wxcontext.py`, `wxinteractivecontext.py`, `events/wxevents.py`,
`text/wxfont.py`) and in `tests/wx_with_controls.py`, `tests/wx_multiple_contexts.py`
and `tests/wx_font.py` — none of which touch `browser/`. What goes is one
application built *on* wx, not wx itself.

`browser/passes.py` is also built on the visiting render passes, so keeping the
package keeps B4 blocked.

**How.**
1. Move `appdatadirectory()` — minus its Win9x `_winreg` fallbacks — into a new
   `OpenGLContext/userpaths.py`, or straight into `contextconfig.py`, its natural
   home. Update `loaders/resolver.py` and the two unit tests.
2. Delete `OpenGLContext/browser/` and `bin/visualshell.py`.
3. Drop `oglc-visual` from `[project.scripts]`; remove the mention at
   `docs/documentation.html:59`.

**If `oglc-visual` is wanted as the wx showcase**, rebuild it on
`wxinteractivecontext` directly — it is a list control, a hosted canvas and a shell
namespace, perhaps 80 lines — rather than keeping 1,439 lines of browser package to
host it. That would be a *better* wx demonstration than the current one, which
routes through a legacy pass-set no other backend uses.

### B2. `shadow/` — stencil shadow volumes

**What it is.** 1,127 lines: Lengyel-style stencil shadow volumes
(`volume.py`, `edgeset.py`, `passes.py`) plus an infinite-perspective projection
(`pinfperspective.py`) and the `ShadowContext` mix-in that swaps in a shadow-aware
`PassSet`.

**What depends on it today.** `bin/vrml_view_shadow.py`
(24 lines) — which is **not** a console entry point. Nothing else. Zero tests
(`tests/shadow_1.py` and `shadow_2.py` are unrelated raw-GL `ARB_shadow`
tutorials), and zero documentation: [docs/shadows.html](../docs/shadows.html) is
about shadow *mapping* end to end.

The package is structurally incompatible with where the renderer went: it needs
the fixed-function pipeline, an infinite perspective matrix imposed on the view
platform, and the visiting pass-set. The shipped shadows are cascaded shadow maps
(`passes/shadowmap.py`, `shadowmixin.py`, `shadowpool.py`, `shadowmath.py`,
`shadowcaps.py`, `shaderpass_shadow.py`) with PCSS soft shadows.

**What would be lost.** A worked stencil-shadow-volume implementation as teaching
material, and its two reusable pieces: silhouette edge extraction (`edgeset.py`)
and the infinite perspective matrix (`pinfperspective.py`, name-dropped in a
comment in [move/viewplatform.py](../OpenGLContext/move/viewplatform.py)).
Neither has another caller.

**How.** Delete `OpenGLContext/shadow/` and `bin/vrml_view_shadow.py`; remove the
`pinfperspective` comment in `viewplatform.py`; check `docs/renderprocess.html`
for the stencil mention (it goes with B4 anyway).

### B3. `scenegraph/tree/` — the volumetric tree

**What it is.** 1,254 lines: space-colonization branch growth
(`colonization.py`, 384), a voxelizer (`voxelizer.py`, 278), a volumetric
renderer (`volumetrictree.py`, 374) and its shaders (`shaders.py`, 181).

**What depends on it today.** `tests/volumetric_tree.py` (99) and
`tests/volumetric_forest.py` (287). Nothing else.

**What would be lost.** The procedural tree generator. Note that
[TERRAIN-SYSTEM.md](TERRAIN-SYSTEM.md) already records the decision:
*"VolumetricTree rejected as too slow"*. Shipped vegetation is instanced glTF
with octahedral impostors (`scenegraph/vegetation/`,
`loaders/tiles3d/foliage.py`, `loaders/tiles3d/vegetation.py`), which is what the
terrain and forest demos actually use.

**How.** Delete the package and both demos. **One judgement call:**
`colonization.py` is pure numpy with no GL in it and is the only
procedural-geometry generator of its kind here — if it is wanted later, recover it
from git history or lift it into `scenegraph/vegetation/` as a generator. My
recommendation is to delete it with the rest and record the commit hash in
`TERRAIN-SYSTEM.md` beside the existing rejection note, so the trail is explicit.

### B4. The old visiting render passes

**What it is.** Three modules totalling 1,839 lines implementing a visitor-pattern
multi-pass renderer that predates `FlatPass`:

| Module | Live | Dead |
|---|---|---|
| [passes/renderpass.py](../OpenGLContext/passes/renderpass.py) (936) | `_core_flatpass_class` + `_defaultRenderPasses`, lines 877–936 | `RenderPass`, `VisitingRenderPass`, `OpaqueRenderPass`, `TransparentRenderPass`, `SelectRenderPass`, `OverallPass`, `PassSet`, `visitingDefaultRenderPasses` — lines 23–872 |
| [passes/rendervisitor.py](../OpenGLContext/passes/rendervisitor.py) (514) | `bind_scene_viewpoint`, lines 27–71 | `RenderVisitor`, lines 74–514 |
| [visitor.py](../OpenGLContext/visitor.py) (389) | `find()` + `_Finder` + `Visitor.children` | the whole `Visitor` dispatch machinery (`buildVMethods`/`vmethods`/`visit`, both instrumented and plain) |

The decisive fact: **`_flat.FlatPass` does not inherit from `renderpass.RenderPass`
at all.** Its bases are `_FlatEffectsMixin`, `SelectionMixin` and `SGObserver`.
The visiting classes are reachable only from `browser/passes.py` and
`shadow/passes.py` — i.e. from B1 and B2. `_Finder.visit` likewise overrides the
entire dispatch algorithm and needs only `Visitor.children()`.

**What would be lost.** The documented ability to substitute a different
multi-pass rendering strategy by assigning `Context.renderPasses` a different
`PassSet`. Nothing in the tree ships one any more, and the two that did are being
removed. Also lost: the architectural story in
`docs/renderprocess.html` (543 lines), which is
entirely about the visitor pattern and would become a description of code that no
longer exists.

**How — after B1 and B2 land, not before.**
1. `renderpass.py` → delete lines 23–872. What is left (~70 lines: profile
   dispatch, PBR-guarded import, the cached-`FLAT` lifecycle) is a pass
   *dispatcher*, so rename the module `passes/dispatch.py` and keep
   `renderpass.py` as a one-line re-export for a release.
2. `rendervisitor.py` → collapse to `bind_scene_viewpoint` alone; the name no
   longer fits, so `passes/viewpointbinding.py`.
3. `visitor.py` → collapse to `find()` + `_Finder` (~60 lines) and move it beside
   what it searches: `scenegraph/find.py`.
4. Comment-only fixes in [events/event.py](../OpenGLContext/events/event.py) and
   [events/keyboardevents.py](../OpenGLContext/events/keyboardevents.py), whose
   docstrings still describe `renderingPass` as an
   `OpenGLContext.renderpass.RenderPass`; and in
   [context.py](../OpenGLContext/context.py):88, :708, :805.
5. **Docs:** retire `docs/renderprocess.html`, replacing it with a short section in
   [docs/renderpasses.html](../docs/renderpasses.html) / [docs/flat.html](../docs/flat.html)
   that describes the pass the renderer actually runs. Update the index in
   `docs/documentation.html` and the architecture note in `docs/structure.html`.

`tests/unit/test_renderpass_robustness.py` and
`tests/unit/test_transparent_depth_sort.py` test only the removed classes and go
with them.

### B5. Display lists and the legacy scenegraph pass

This item **shrinks a great deal** under the platform commitment, and the part that
survives is a decision rather than a cleanup. Splitting it in two:

#### B5a. `DisplayListCompiler` — dead by weighting, remove it

`IndexedFaceSet.compile` picks a compiler by weight
([indexedfaceset.py:186](../OpenGLContext/scenegraph/indexedfaceset.py)):

```python
set = [(cc.weight(self), cc) for cc in COMPILER_CLASSES]
set.sort()
return set[-1][1](self)(...)
```

`ArrayGeometryCompiler` does not override `weight` and so inherits the base's
**1.0**; `DisplayListCompiler.weight` returns a constant **0.9**
([ifscompiler.py:480](../OpenGLContext/scenegraph/ifscompiler.py)). 0.9 never wins
a max. **`DisplayListCompiler` has been unreachable in both profiles**, and its own
docstring says so: *"this implementation is basically without real purpose, the
arraygeometry version should be much faster on all modern hardware"*.

~110 lines (`DisplayListCompiler` + `DisplayListRenderer`) plus their entries in
`COMPILER_CLASSES` and in `tests/unit/test_ifscompiler.py`. **Nothing is
withdrawn** — this code cannot execute today.

Note this does **not** remove [displaylist.py](../OpenGLContext/displaylist.py)
itself; see B5b.

#### B5b. The legacy scenegraph renderer — a decision, and my recommendation is *no*

**The distinction that makes the question tractable.** Two separate things get
called "legacy", and only one is a *renderer*:

* **A compatibility GL context** — `ContextDefinition(profile='compatibility')`, a
  context-creation flag. **66 of the 146 demo scripts in `tests/` are raw-GL
  tutorials** (`nehe1`–`nehe8`, `redbook_*`, `gl*` introspection, `glu_tess`,
  `feedback_mode`, `line_stipple`, …) that call fixed-function OpenGL **directly in
  their own `Render` method** and never touch a `FlatPass`. They need a
  compatibility context and nothing else. **This is not in question and is not
  going anywhere** — all five backends can create one.
* **The legacy scenegraph renderer** — [passes/flatcompat.py](../OpenGLContext/passes/flatcompat.py)
  plus the `use_shaders=False` branches in `_flat.py` and the second render path in
  each geometry node. *This* is what B5b would remove, ~1,900 lines.

**What blocks it — and this is the finding that changed my recommendation.**

The display-list-backed **font providers are scenegraph `Text` rendering**, and
three of the five supported backends supply one:

| Provider | Backend | Renders via |
|---|---|---|
| [text/glutfont.py](../OpenGLContext/scenegraph/text/glutfont.py) | GLUT | `glNewList` + `glutBitmapCharacter` |
| [text/wxfont.py](../OpenGLContext/scenegraph/text/wxfont.py) | wxPython | `glNewList` + `glBitmap` |
| [text/wglfont.py](../OpenGLContext/scenegraph/text/wglfont.py) | Win32/WGL | `wglUseFontOutlines` + display lists |
| [text/pygamefont.py](../OpenGLContext/scenegraph/text/pygamefont.py) | Pygame | texture, via the same base |

All four descend from [text/font.py](../OpenGLContext/scenegraph/text/font.py),
which renders with `glCallLists` and `doinchildmatrix.doInChildMatrix`. They are
registered by `vrmlcontext.setupFontProviders`, and
`fontprovider.getProviderFont` already routes around them under core profile via a
`shader_compatible` flag — which is exactly the point: **they are the
compatibility-profile Text path.** Deleting `flatcompat` deletes the pass that
drives them, and deleting `displaylist.py`/`doinchildmatrix.py` deletes what they
render with.

So B5b is not "remove some dead fixed-function code". It is: **withdraw
compatibility-profile scenegraph rendering, and with it three of the four
platform-native font providers.** That is a different and much larger proposition
than it appeared before the platform list was settled.

**What would additionally be lost.**
1. **The compat-vs-core cross-check.** `tests/conftest.py`'s
   `visual_regression_runner` records its baseline at
   `record_profile='compatibility'` and compares the core render against it;
   `tests/regression_output_compat/` holds the diffs. Fixed-function output is
   serving as ground truth for validating the shader path. Lose it and the
   baselines become "whatever core rendered the day we blessed them".
2. **Scenegraph content on GL < 3.3**, or on any driver whose core profile is
   broken — which is precisely the long-tail hardware the GLUT and Pygame backends
   tend to be reached on.
3. Display-list `IndexedFaceSet` compilation as teaching material — though B5a
   already establishes that this has not actually executed for some time.

**Recommendation: decline B5b.** The saving (~1,900 lines, 2.5% of the package) does
not buy back what it costs against a five-backend commitment, and it is the only
item on this list where a mistake produces a wrong image rather than an import
error.

**What to do instead — the part that is worth doing regardless.**

1. **Flip the default profile to `core`.** `_get_default_profile()` in
   [contextdefinition.py](../OpenGLContext/contextdefinition.py) currently returns
   `'compatibility'`, so **74 scenegraph demos take the legacy path by default**
   and the modern renderer is not what a new user sees first. Flip it, run the
   script suite, triage and re-bless what legitimately changes. This is the real
   work, it needs no deletion to be worth landing, and it is what tells you the
   core path is complete.
2. **Keep `flatcompat` as an explicitly-supported mode**, reached by
   `profile='compatibility'` — not as a default and not as an accident. Document it
   in [docs/flat.html](../docs/flat.html) as the fixed-function path, say which
   font providers depend on it, and keep the ~10 demos that pin it as its smoke
   test.
3. **Keep the compat-vs-core cross-check.** Once core is the default it becomes
   more valuable, not less: it is the only mechanical check that the two renderers
   agree.
4. **Take B5a**, which is free.
5. Revisit B5b only if the bitmap font providers are ever ported onto the atlas
   path — at which point it becomes a much smaller and much safer change.

### B6. One viewer: `oglc-view`

**Today.** Eleven console scripts, of which five are viewers of the same kind of
thing:

| Script | Module | Lines |
|---|---|---|
| `oglc-gltf` | [bin/gltf_view.py](../OpenGLContext/bin/gltf_view.py) | 1,288 |
| `oglc-terrain` | [bin/terrain_view.py](../OpenGLContext/bin/terrain_view.py) | 562 |
| `oglc-tiles` | [bin/tiles_view.py](../OpenGLContext/bin/tiles_view.py) | 244 |
| `oglc-vrml` | [bin/vrml_view.py](../OpenGLContext/bin/vrml_view.py) | 140 |
| `oglc-profile` | [bin/profile_view.py](../OpenGLContext/bin/profile_view.py) | 38 |

`gltf_view` is the only mature one: async loading with a progress label, animation
selection and playback, camera cycling, HDR and cube-map environments, physics
walk mode with spawn placement, screenshot capture, a text overlay, declared
movement modes. `vrml_view` has none of it — and its `--shaders` flag reaches into
`renderpass.FLAT.use_shaders` from inside `Redraw`, a hack that B5 deletes anyway.
`tiles_view` and `terrain_view` each re-implement their own framing, their own
`os.environ.setdefault` preamble and their own fly controls.

**Proposal.** One `oglc-view <source>` that chooses a *scene adapter* by content
type, not by which binary you typed:

| Source | Adapter |
|---|---|
| `.wrl` / `.wrz` / `.vrml` / `.gz`, `model/vrml`, `x-world/x-vrml` | `loaders.loader.Loader` (already extension-dispatched) |
| `.gltf` / `.glb`, `model/gltf+json`, `model/gltf-binary` | `loaders.gltf.load_gltf` / `load_gltf_url` |
| `.obj` | existing obj handler |
| `tileset.json` — or any JSON carrying both `asset` and `root` | `TilesTerrain` streaming runtime |
| *(no argument)* | today's procedural terrain world |

The dispatch mechanism already exists and is half-used: `plugins.Loader` in
[\_\_init\_\_.py](../OpenGLContext/__init__.py) maps extensions *and MIME types* to
handlers, and `Loader.getHandler` resolves by suffix. glTF and 3D Tiles are simply
not registered in it. Registering them makes the viewer's dispatch **data rather
than an `if` chain**, and lets a third party add a format without touching the
viewer.

**Structure.**
* ✅ **Done** — `gltf_view.TestContext` is now
  `OpenGLContext/viewer/sceneviewer.py::ViewerContext`, the reusable shell:
  async loading, overlay, screenshots, capture, framing, cameras, animation. The
  physics toggle went further out still, to
  `move/physicswalk.py::PhysicsWalkMixin` on *every* interactive context.
  `bin/gltf_view.py` fell from 1,288 lines to ~270 of argument definitions.
  Configuration is a `ViewerOptions` dataclass that `argparse` fills in, so the
  library and the CLI share one set of defaults. See
  [VIEWER-COMPONENT-EXTRACTION.md](VIEWER-COMPONENT-EXTRACTION.md).
* ✅ **Done** — per-format specifics live behind `SceneAdapter` in
  `OpenGLContext/viewer/adapters/`, registered under a new `plugins.Adapter`
  keyed on suffix and content type, so the dispatch is data and a third party
  adds a format without touching the viewer. glTF, VRML97, OBJ and 3D Tiles.
  `bin/view.py` is `oglc-view`; `oglc-gltf`, `oglc-vrml` and `oglc-tiles` are
  deprecating aliases. See [ONE-VIEWER.md](ONE-VIEWER.md).
* **Still open:** `terrain_view`'s procedural world *baking* is content
  generation, not viewing — split it out as `oglc-bake` (or
  `oglc-view --bake-terrain`), leaving the viewer to open the tileset it
  produces.

**What would be lost.** No functionality — every format *gains* the features only
glTF has today. What changes is CLI names. Keep `oglc-gltf`, `oglc-vrml`,
`oglc-tiles`, `oglc-terrain` as thin aliases that print a one-line deprecation
notice for a release cycle, then drop them.

**Keep separate, deliberately:** `oglc-gltf-regression` (a test harness),
`oglc-gltf-demo` (a curated sample gallery), `oglc-ui`, `oglc-test`,
`physics-cook`. These are not viewers.

**Net:** ~2,270 lines of viewer code become ~1,500 in one place, and the five
copies of the environment-variable preamble become one.

---

## Tier C — housekeeping

### C1. `bin/` non-tools, the second test root, packaging leftovers

* [bin/choosecontext.py](../OpenGLContext/bin/choosecontext.py) (223) and
  [bin/choosefonts.py](../OpenGLContext/bin/choosefonts.py) (209) — interactive
  pickers, not wired to any entry point. They are demos living in a tools
  directory: move to `tests/`. (Keep both — `choosecontext` enumerates the
  supported backends and `choosefonts` the font providers, which is exactly the
  sort of thing the platform commitment wants demonstrable.)
* [bin/keyboardevents.py](../OpenGLContext/bin/keyboardevents.py) (93) — likewise a
  demo; move to `tests/`.
* **`OpenGLContext/tests/`** (255 lines: `test_atlas`, `test_configs`,
  `test_polygonsort`, `test_utilities`, `test_viewplatform`, `sample.ini`) — a
  second test root, listed in `pyproject.toml`'s `testpaths`, that **ships inside
  the wheel**. Move the five modules to `tests/unit/` and delete the package.
* `src/writeplugins.py` — emits a setuptools entry-point block that
  `pyproject.toml` already declares, and it still names `wxvrmlcontext` /
  `pygamevrmlcontext`. Delete `src/`.
* `full/` (a stub `setup.py` + README) and the empty `coverage/` — delete.
* Working-tree litter that should be gitignored rather than present:
  `build/` (13 MB, stale), `.coverage`, `gltf-*.png`, `runtime_ibl_out/`,
  `test-results/`. `newrender.txt` and `ubershader.txt` are design notes that
  [docs/ubershader.html](../docs/ubershader.html) superseded — move to `plans/` or
  delete.

**Withdrawn:** nothing. Every item here is either a move or a build artefact.

---

## Withdrawn candidates

Recorded so the same wrong turn is not taken twice. An earlier draft proposed
these; **the platform commitment rules them out**, and each is now explicitly
supported code.

| Candidate | Why it was proposed | Why it stays |
|---|---|---|
| [text/wglfont.py](../OpenGLContext/scenegraph/text/wglfont.py) + [wglfontprovider.py](../OpenGLContext/scenegraph/text/wglfontprovider.py) (265) | Win32-only; cannot execute on any machine in this dev container | **Windows font support, usable on Windows.** "This container cannot run it" is not evidence about Windows. |
| [text/glutfont.py](../OpenGLContext/scenegraph/text/glutfont.py) (186) | Gated behind `Context.providesGLUT` because GLUT segfaults when uninitialised | The GLUT backend's native font provider, and the only one needing no font library at all. The gate is correct behaviour, not a sign of decay. |
| [text/wxfont.py](../OpenGLContext/scenegraph/text/wxfont.py) (314) | Reached only from `tests/wx_font.py` | The wxPython backend's native font provider. |
| [text/pygamefont.py](../OpenGLContext/scenegraph/text/pygamefont.py) (213) | "keep only if the pygame backend stays" | The pygame backend stays. |
| The wxPython backend (`wxcontext`, `wxinteractivecontext`, `wxvrmlcontext`, `wxtestingcontext`, `events/wxevents`, `resources/context_icon*`) (~1,225) | wx not installed here, no CI coverage | **First-class target.** The correct response to "no CI coverage" is CI coverage. |

**The action item that came out of this, inverted:** wxPython, GLUT and Pygame are
supported but only GLFW is exercised by CI. That is a testing gap to close, not a
support level to lower. Adding a wx/pygame job — even one that only builds a
context, renders a frame and captures it — would turn an assumption into a check.
Worth its own plan document.

**A related note that is *not* a removal:** the nine generated atlases in
`text/fonts/font_atlas_{10..32}.py` (2,235 lines) are live — imported dynamically
by `shaderfont.py` and `ui/metrics.py`, so a static import graph does not see them.
2,235 lines of committed Python tables is a poor container for numeric data and a
single `.npz` would be better, but that is a representation change with no
behaviour attached, and belongs in its own small piece of work.

---

## Sequencing

Each step leaves the tree green and shippable.

1. **Tier A** — pure deletions. No behaviour change.
2. **B1 `browser/`** — extract `appdatadirectory` first, then delete.
3. **B2 `shadow/`** — delete.
4. **B3 `scenegraph/tree/`** — delete, with the commit hash noted in `TERRAIN-SYSTEM.md`.
5. **B4 visiting passes** — now that B1 and B2 have removed their only consumers.
   Rename the three survivors; retire `docs/renderprocess.html`.
6. **B5a `DisplayListCompiler`** — free, independent of everything else.
7. **C1 housekeeping** — independent; can run in parallel throughout.
8. **B6 `oglc-view`** — a build, not a delete. Land `ViewerContext` + adapters
   first with the old scripts as thin wrappers, then flip the entry points.
9. **Flip the default profile to `core`** and re-bless the reference images. The
   single highest-value step in this document, and it deletes nothing.
10. **B5b** — only if it is ever accepted, and only after the bitmap font providers
    have somewhere else to go. Recommendation stands at *decline*.

Separately, and not part of this plan: **close the CI gap on the supported
backends.** GLFW is exercised; GLUT, Pygame and wxPython are supported on the
strength of the code being present. That deserves its own plan document.

## Documentation impact

Per [the workspace rule](../../CLAUDE.md), documentation ships with the change.
Each item's doc work, so none of it is discovered late:

| Item | Documentation to update |
|---|---|
| B1 | `docs/documentation.html` (remove `oglc-visual`); `readme.txt:92` |
| B2 | `docs/renderprocess.html` stencil mention; confirm `docs/shadows.html` needs nothing |
| B3 | `plans/TERRAIN-SYSTEM.md`, `plans/GLTF-*.md` volumetric mentions |
| B4 | **Retire `docs/renderprocess.html` (543 lines)**; fold a short "how a frame renders" section into `docs/renderpasses.html`/`docs/flat.html`; update `docs/documentation.html` index and `docs/structure.html` |
| B5a | `docs/renderpasses.html` — the IFS compiler set, minus the display-list compiler that never ran |
| B6 | `docs/documentation.html`, `docs/gltf.html`, `docs/terrain.html`, `docs/navigation.html` — one viewer, its CLI, and the deprecated aliases |
| C1 | `pyproject.toml` `testpaths`; `.gitignore` |
| profile flip | `docs/flat.html` + `docs/vrml97.html` — core is the default; compatibility is a supported mode reached deliberately, and which font providers live there |
| **done** | `readme.txt` "Supported GUI backends" and [docs/structure.html](../docs/structure.html) "Which backends are supported" — **written as part of this proposal**, since the ambiguity is what produced the withdrawn candidates |

## What is explicitly *not* a removal candidate

Recorded so a later reader does not re-litigate:

* **`atlas.py` (300) / `texturecache.py` (36)** — reached from `context.py`
  through `imagetexture.py`; live.
* **`scenegraph/text/fonts/font_atlas_*.py` (2,235)** — dynamically imported;
  live despite showing zero static importers.
* **Most `scenegraph/` nodes showing zero importers** (`pointset`, `lod`,
  `billboard`, `collision`, `timesensor`, `inline`, `texturetransform`,
  `mouseover`, `indexedlineset`, `simplebackground`, `coordinate`, …) — reached by
  **string name** through the `Node()` plugin registry in `__init__.py`, which the
  import graph cannot see. They are the VRML97 node set; they stay.
* **`frustum.py` vs `loaders/tiles3d/frustum.py`, `scenegraph/boundingvolume.py`
  vs `loaders/tiles3d/boundingvolume.py`** — they look like duplicates and are
  not: one pair is VRML97 scenegraph culling, the other is 3D-Tiles world-space
  traversal with different conventions and different APIs.
* **`ui/` (7,486), `physics/`, `nav/`, `audio/`, `loaders/tiles3d/`,
  `loaders/gltf/`, the shadow-*map* modules** — current, documented, tested.
* **Everything belonging to a supported backend** — the four in-tree context
  families and their event translators, font providers and icons, whether or not
  this machine can execute them. See
  [Withdrawn candidates](#withdrawn-candidates); the general rule is at the top of
  this document.
* **`passes/flatcompat.py`, `displaylist.py`, `doinchildmatrix.py`,
  `text/font.py`** — the compatibility-profile scenegraph path. Removable only via
  B5b, which is recommended against, because three of the five supported backends
  reach their native font provider through it.
