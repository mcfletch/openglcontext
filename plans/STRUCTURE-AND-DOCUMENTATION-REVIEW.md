# Structure & Documentation Review — consistency, cohesion, obviousness

**Status:** 🟡 Partial — **steps 1–7 landed** on branch `docs-structure-review`
(findings 5, 6, 8, 9, 10, 13 and part of 7), and **findings 11 and 12 landed**
on branch `demos`. Findings 1, 2, 3, 4 and the rest of 7 are open.
**Date:** 2026-08-20.
**Scope:** the `OpenGLContext` package, `docs/`, `README.md` and `CLAUDE.md`.
Not a bug hunt: every item here is about whether a developer can *predict* where
something lives, *find* how to use it, and *trust* what the page in front of them
says.

## Method

An AST pass over all 403 modules in `OpenGLContext/` for docstring coverage,
duplicate definitions and naming; a cross-check of every `OPENGLCONTEXT_*` name in
the code against `docs/` and `renderoptions.ENVIRONMENT`; a link-and-reference
check of the 29 pages under `docs/`; and a comparison of the registries in
`OpenGLContext/__init__.py` against `pyproject.toml`'s console scripts and against
what `docs/structure.html` says about both.

Where an item is already owned by an existing plan it is marked and cross-linked
rather than restated. [CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md) item
C1 already covers the second test root and the non-tool modules in `bin/`; nothing
below re-proposes those.

## Summary

| # | Finding | Cost of leaving it | Size |
|---|---------|--------------------|------|
| 1 | Two spellings for the same concept inside one package (`contentRect` beside `content_size`) | Every new method is a coin toss; a caller has to look | Medium |
| 2 | Three implementations of the perspective/look-at matrix, two `Frustum` classes | Two conventions in one engine; a fix lands in one copy | Medium |
| 3 | `hud.py` at top level, its other half in `ui/`; culling maths under `loaders/` | The layout does not predict the contents | Small |
| 4 | Nine of fifteen sub-packages have no front door in `__init__.py` | No answer to "what do I import from `passes`?" | Small |
| 5 | `viewer/options.py` re-implements the environment readers, with different semantics | `OPENGLCONTEXT_PHYSICS=off` turns physics **on** | Small, and a defect |
| 6 | Two rendering settings sit on `ENVIRONMENT`'s exemption list, and one listed variable is read by nothing | `clean_environment()` does not clean them; setting `MAXIMUM_LIGHTS` does nothing | Small, and a defect |
| 7 | Docstrings are two-tier: 49 large legacy modules carry one terse line | The oldest, most-read core is the least explained | Large |
| 8 | Five docstrings name modules that moved; one names a module that never existed | The reader follows the pointer and lands nowhere | Small |
| 9 | `structure.html` and `basenodes.py` document an extension mechanism that is not the one in the code | A third party follows it and nothing registers | Small |
| 10 | No environment-variable reference page; 41 variables scattered over 13 pages | The switches are unfindable unless you know the feature | Small |
| 11 | `nav/` has no user documentation, no index entry and no demo | A whole subsystem is invisible | Small |
| 12 | Roads, water, HUD, telemetry, characters, baking, recording, editing have no runnable demo | The 1998 NeHe ports are demonstrated; the 2026 engine is not | Medium |
| 13 | `CLAUDE.md`'s directory map omits 13 of 21 packages; the root docstring and `README.md` describe an older project | The first thing a reader meets is the least current | Small |

## What is already sound

Stated so the work below is not read as a verdict on the whole.

- **Module docstring coverage is 97.3%** (392/403), and the modules written since
  2025 — `renderoptions.py`, `hud.py`, `nav/navmesh.py`, `viewer/sceneviewer.py`,
  `passes/renderpass.py`, `move/bindingstore.py` — carry the kind of docstring
  that explains a design rather than restating a class name.
- **Every one of the 29 pages under `docs/` is reachable from
  `docs/documentation.html`.** There are no orphan pages.
- **`plans/PROJECT-PLAN.md` indexes 51 plans with live status.** The planning
  discipline is real and current.
- **No dead top-level modules.** Every one of the 46 has at least one live
  importer; the sparsest, `extensionmanager`, is reached from `context.py:427`.
- **403 unit-test modules under `tests/unit/`**, and the shared runner lives in the
  shipped `OpenGLContext.testing` package rather than in a private copy inside
  `conftest.py`.
- **`renderoptions.py` is the model the rest of the package should be measured
  against**: it says what it is for, why the indirection exists, and what a caller
  who ignores it will get wrong.

---

## 1. One concept, two spellings, inside one package

### Evidence

`OpenGLContext/ui/` defines 110 camelCase and 115 snake_case public callables, and
the split runs *through individual classes*:

| File | camelCase | snake_case |
|---|---|---|
| `ui/panel.py:102,111` | `contentRect` | `content_size` — same class |
| `ui/widgets.py:235,242,319` | `paintTree`, `paintChildren`, `layoutChildren` | `content_size`, `widget_at`, `arrange_content` — same class |
| `ui/scroll.py:63,278` | `layoutChildren`, `paintChildren`, `barRect`, `thumbRect` | `arrange_content`, `widget_at`, `knob_rect` (`widgets.py`) |
| `ui/hudwidgets.py` | `barRect`, `fillRect`, `iconRect`, `haloRect` | `bounds`, `content_size`, `widget_at` |

`ui/scroll.py` spells a scrollbar thumb's rectangle `thumbRect`; `ui/widgets.py`
spells a slider thumb's rectangle `thumb_rect`. Both are new code.

`scenegraph/` is 155/134, `move/` is 82/28, `viewer/` is 111/23. `CLAUDE.md` has a
"Code Conventions" section (line 362) that does not mention naming at all.

### Why it matters

The mixture is not arbitrary — camelCase is what VRML97 and the `vrml` package
require of node fields and of the `Context` API (`OnInit`, `OnDraw`,
`addEventHandler`), and that is a hard external constraint. What has happened is
that the constraint leaked past its boundary: `ui/` implements no VRML97 protocol
and answers to no external naming, and it still went both ways. A developer
writing the next widget has no rule to follow, and a caller cannot guess a method
name.

### Fix

1. **Write the rule down** in `CLAUDE.md` under Code Conventions, as a boundary
   rather than a preference:

   > **Naming.** `snake_case` for everything the project names itself.
   > `camelCase` only where an external protocol requires it: VRML97 node fields
   > and `exposedField` names, the `Context` lifecycle (`OnInit`, `OnDraw`,
   > `OnIdle`), and the event API (`addEventHandler`, `ProcessEvent`). A method on
   > a class that implements no VRML97 or `Context` protocol is `snake_case`.

2. **Apply it to `ui/` first**, which is the newest package and has no VRML97
   surface at all. Renames, with the old name kept as an alias for one release
   where a game may already call it:

   | Now | Becomes |
   |---|---|
   | `Panel.contentRect`, `Menu.contentRect`, `ToolPalette.contentRect` | `content_rect` |
   | `Widget.paintTree` / `paintChildren` / `paintFocus` | `paint_tree` / `paint_children` / `paint_focus` |
   | `Widget.layoutChildren`, `ScrollViewport.layoutChildren` | `layout_children` |
   | `ScrollViewport.barRect` / `thumbRect` / `viewRect` / `scrollTo` / `scrollBy` / `maximumScroll` / `needsBar` | `bar_rect` / `thumb_rect` / `view_rect` / `scroll_to` / `scroll_by` / `maximum_scroll` / `needs_bar` |
   | `Widget.baseSkin` / `activeSkin` / `scaleSkin` / `textColour` / `wheelAdjusts` / `wrapsToWidth` | `base_skin` / `active_skin` / `scale_skin` / `text_colour` / `wheel_adjusts` / `wraps_to_width` |
   | `hudwidgets` `*Rect` / `*Colour` / `*Width` (22 names) | `*_rect` / `*_colour` / `*_width` |
   | `settings.doApply` / `doCancel` / `doReset` / `doDiscard` / `doBindings`, `bindings.doSave` / `doCancel` | `apply` / `cancel` / `reset` / `discard` / `open_bindings` / `save` |
   | `OverlayStack.pushOverlay` / `popOverlay` / `layoutOverlays` / `overlaySinks` / `screenTrees` / `releaseOverlayPictures` / `hasMouseMoveHandlers` | `push_overlay` / `pop_overlay` / `layout_overlays` / `overlay_sinks` / `screen_trees` / `release_overlay_pictures` / `has_mousemove_handlers` |

   `OverlayMixin.ProcessEvent` stays: that one *is* the `Context` event protocol.

3. **Leave `scenegraph/`, `events/` and `move/` alone for now** beyond the written
   rule. Their camelCase is load-bearing (VRML97 field names, `EventManager`
   protocol), and a rename there is a compatibility event, not a tidy-up. Apply the
   rule to *new* methods in those packages.

---

## 2. The perspective matrix exists three times, the frustum twice

### Evidence

| Thing | Location | Convention |
|---|---|---|
| `perspectiveMatrix` | `pyvrml97`'s `transformmatrix` | row-vector |
| `perspective_matrix` | `passes/shadowmath.py:57` | delegates to the above |
| `perspective` | `loaders/tiles3d/frustum.py:16` | column-vector, hand-written |
| `look_at_matrix` | `passes/shadowmath.py:30` | row-vector, with a parallel-up guard |
| `look_at` | `loaders/tiles3d/frustum.py:27` | column-vector, no guard |
| `Frustum` (plane extraction from a matrix) | `frustum.py:55` — a `vrml.node.Node`, reads `glGetFloatv` when not given matrices | compatibility-profile |
| `Frustum` (plane extraction from a matrix) | `loaders/tiles3d/frustum.py:51` — plain numpy, Gribb-Hartmann | core-profile |
| `_normalize` | `passes/shadowmath.py:23` and `move/followcam.py:27` | identical bodies |
| `normalise` | `utilities.py:33` (one vector) and `vectorutilities.py:55` (many) | a deliberate pair, but the names do not say so |

The two `Frustum` classes are both live. The `tiles3d` one is imported by
`scenegraph/vegetation/field.py:337`, `viewer/adapters/tiles.py:284` and
`bin/terrain_view.py:69` — none of which is a loader.

### Why it matters

Two matrix conventions in one engine is the kind of thing that produces a bug
nobody can reproduce, because it works everywhere the two paths do not meet. A
guard added to one `look_at` does not reach the other. And there is no module a
developer can look in first: geometry maths is spread over `utilities.py`,
`vectorutilities.py`, `triangleutilities.py`, `quaternion.py`,
`passes/shadowmath.py` and `loaders/tiles3d/frustum.py`.

### Fix

1. **Create `OpenGLContext/matrices.py`** — one module, row-vector convention
   throughout (the convention `pyvrml97` and the rest of the renderer already
   use), holding `perspective`, `orthographic`, `look_at`, `normalize`,
   `cross`, `magnitude`. Each function's docstring states the convention in its
   first two lines, because that is the fact a caller gets wrong.
2. **Move `Frustum` to `OpenGLContext/culling.py`** — one class, built from a
   view-projection matrix, with `contains_sphere` and `contains_box`. Give it the
   `tiles3d` implementation's body (plain numpy, no `glGet`) and the `frustum.py`
   version's `fromViewingMatrix` classmethod as a compatibility-profile
   convenience that reads the GL matrices and calls the same code.
3. **`frustum.py` becomes a two-line shim** re-exporting from `culling.py`, for
   `scenegraph/boundingvolume.py` and the tutorials that import it by name;
   `loaders/tiles3d/frustum.py` becomes a shim re-exporting `Frustum` and
   `view_projection`. Both shims get a docstring saying where the code is and are
   removed in 3.1.
4. **`passes/shadowmath.py` keeps only what is about shadows** —
   `near_far_from_points`, the cascade split maths, the texel-snap — and imports
   the rest.
5. **Delete `move/followcam._normalize`** in favour of the shared one.
6. **Rename for the vector/array pair.** `utilities.normalise` and
   `vectorutilities.normalise` differ only in arity, which no reader can see from
   the call site. Keep `vectorutilities` as the array module and have
   `utilities.py` say so in its first line: *"Single-vector convenience wrappers
   over `vectorutilities`, which does the same work for arrays of vectors."* Its
   current line — "Simple utility functions that should really be in a C module" —
   describes an implementation wish rather than the module.

---

## 3. Two modules are filed where nobody would look for them

### `hud.py` is the layout half of `ui/`

`OpenGLContext/hud.py` (404 lines) opens with:

> *"This is the layout half of a widget… The drawing half, the input half and the
> concrete widgets are in `OpenGLContext.ui`."*

Its importers are `ui/menu.py`, `ui/toolpalette.py`, `ui/layout.py`,
`ui/widgets.py`, `ui/panel.py`, `ui/hudwidgets.py` and one test. Nothing outside
`ui/` uses it. Meanwhile `ui/hudwidgets.py` is a *different* thing — the in-world
HUD — so the package contains `hud.py` and `ui/hudwidgets.py` meaning two
unrelated subjects.

**Fix:** move to `OpenGLContext/ui/layoutbase.py` (the name `ui/layout.py` is
taken by `Row`/`Column`/`Grid`, which are built on it), leaving
`OpenGLContext/hud.py` as a re-export shim for one release. Update the seven
importers and `docs/overlayui.html`. Rename `ui/hudwidgets.py` to
`ui/hud.py` in the same change, since it is the HUD and nothing else in `ui/` now
claims that name.

### Frustum culling lives under `loaders/`

`loaders/tiles3d/frustum.py` is general culling maths reached by the vegetation
renderer and the terrain viewer. Covered by finding 2's move to `culling.py`.

### Already owned elsewhere

The second test root (`OpenGLContext/tests/`, five modules, shipped in the wheel,
listed in `pyproject.toml:169`) and the three demo modules in `bin/`
(`choosecontext.py`, `choosefonts.py`, `keyboardevents.py`) are
[CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md) item C1. Worth noting only
that `OpenGLContext/tests/` is the one package in the tree at 0/5 module
docstrings, so if C1 slips, five modules' worth of documentation debt sits inside
the distribution.

---

## 4. Half the sub-packages have no front door

`__init__.py` declares an `__all__` and re-exports in `ui`, `viewer`, `character`,
`telemetry`, `nav` and `testing`. It is empty in `physics`, `edit`, `audio`,
`video`, `scenegraph`, `events`, `move`, `passes`, `loaders` and `bin`.

So `from OpenGLContext.nav import NavMesh` works and `from OpenGLContext.physics
import ...` has no answer — the caller must already know that the manager is in
`physics/manager.py`. The two halves were written years apart and the split is not
a decision anyone made.

**Fix:** give every sub-package an `__init__.py` with a docstring naming what the
package is for, the two or three names most callers want, and `__all__`. Concretely:

| Package | Re-export |
|---|---|
| `passes` | `FlatPass`, `defaultRenderPasses`, `PBRPass` |
| `move` | `ViewPlatform`, `ViewPlatformMixin`, `MovementManager`, `MovementMode` |
| `loaders` | `load`, `Loader`, and a line pointing at `loaders.gltf` / `loaders.tiles3d` |
| `physics` | `PhysicsManager`, `HeightField`, and the `enablePhysics` context call |
| `scenegraph` | a docstring pointing at `basenodes` as the way to reach node classes; no re-exports, since `basenodes` is populated from the registry at import |
| `events` | `Event`, `EventManager`, and the mixin |
| `audio`, `video`, `edit` | the one class each that a caller starts from |
| `bin` | a docstring listing the console scripts and their entry points |

The `passes/__init__.py`, `move/__init__.py`, `loaders/__init__.py` and
`scenegraph/__init__.py` files are currently zero bytes; a package with no
docstring produces an empty `pydoc` page, which is what a reader following
"PyDoc References" from `documentation.html` reaches today.

---

## 5. The viewer re-implements the environment readers, and gets a value wrong

### Evidence

`viewer/options.py:26`:

```python
def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value == '':
        return default
    return value != '0'
```

`renderoptions.py:243` already provides `env_flag`, which maps the value through
`TRUE_WORDS`/`FALSE_WORDS` and **logs a warning** for anything that is neither:

> *"A value that is neither a yes nor a no is reported, not swallowed: these
> variables are how a feature is pinned for a CI run, and a typo that silently
> reverses the pin makes the result of that run a lie."*

The local copy is exactly the failure that docstring describes.
`OPENGLCONTEXT_PHYSICS=off`, `=no` and `=false` all enable physics through
`viewer/options.py:116`, silently. `_env_float` at line 33 likewise swallows an
unparseable number where `renderoptions.env_number` reports it.

### Fix

Delete both local helpers; import `renderoptions.env_flag` and
`renderoptions.env_number`. One test in `tests/unit/test_viewer_options.py`
asserting `OPENGLCONTEXT_PHYSICS=off` yields `physics is False`. This is a defect,
not only a tidy-up — do it first and separately.

---

## 6. Two rendering settings were exempted, and one variable was read by nothing

**Corrected after implementation.** The first draft of this finding said four
variables had been forgotten from `renderoptions.ENVIRONMENT`. That was wrong:
the invariant is already tested
(`test_every_variable_the_package_reads_is_listed`), and those names sit on a
deliberate `allowed` list carrying a stated rationale — sound for the audio pair
and the three diagnostics, which change no pixels and which a subprocess should
inherit rather than silently lose. What was actually wrong was narrower.

### `OPENGLCONTEXT_PHYSICS` and the framing yaw are rendering settings

Physics drops the avatar under gravity and collides it with the scene; the
framing yaw turns a model with no camera of its own on the turntable it is
framed against. Both decide where the camera ends up, so a reference image
rendered with either inherited is a reference for whatever the parent process
happened to be carrying. Both are now in `ENVIRONMENT`, and the exemption list
says per-name why each of the remaining six is exempt.

### `OPENGLCONTEXT_MAXIMUM_LIGHTS` was read by nothing

It was listed in `ENVIRONMENT` — and so dropped by `clean_environment()` — but
`ContextDefinition.maximumLights` was the one field in that class whose default
was a literal `8` rather than a `renderoptions.env_number` lambda. Setting the
variable did nothing at all. It now reads its variable, exactly as
`shadowCascades` immediately above it does.

The existing invariant test only checks one direction — every variable read is
listed. It does not catch a listed variable nothing reads, which is how this
survived. The reference page added in finding 10 closes that gap from the other
side: a variable in the tuple must appear on the page, and the page may name
nothing the package does not.

## 7. Docstrings are two-tier

### Evidence

| Level | Coverage |
|---|---|
| Modules | 392/403 — **97.3%** |
| Public classes | 511/547 — **93.4%** |
| Public functions and methods | 2294/2875 — **79.8%** |

The gap is not spread evenly. **49 modules over 100 lines have a whole-module
docstring under 70 characters** — one line, no body. They are the pre-2019 core:

```
819  scenegraph/text/toolsfont.py    "rendering of TTF outlines (as provided by _fonttools)"
812  scenegraph/shaders.py           "Shader node implementation"
475  events/mouseevents.py           "Events relating to the mouse"
452  scenegraph/text/font.py         "Abstract base-class for all font implementations"
449  texture.py                      "Resource-manager for textures (with PIL conversions)"
426  scenegraph/indexedlineset.py    "IndexedLineSet VRML97 node implemented using display-lists"
335  move/viewplatformmixin.py       "Mix-in class for contexts needing to control a viewplatform object"
300  atlas.py                        "Texture atlas implementation"
283  move/viewplatform.py            "Mobile camera implementation using quaternions"
282  contextdefinition.py            "Definition of a Context's visual parameters"
246  passes/flatcompat.py            "Flat rendering mechanism using structural scenegraph observation"
```

Two of those summary lines are no longer true:

- **`toolsfont.py`** cites `_fonttools`. No module of that name exists anywhere in
  the tree.
- **`indexedlineset.py`** says "implemented using display-lists". It has a shader
  path at line 177, which is what the recommended core profile takes.

And two modules share a summary line verbatim:

```
passes/flatcore.py    "Flat rendering mechanism using structural scenegraph observation"
passes/flatcompat.py  "Flat rendering mechanism using structural scenegraph observation"
```

A reader in `pydoc` cannot tell the core-profile pass from the compatibility one.
`flatcore.py`'s body then adds *"which **now** supports both legacy fixed-function
and shader-based rendering paths"* — the narrative tense the project's own writing
rule excludes.

Two whole classes of undocumented public surface stand out:

- **`viewer/sceneviewer.py::SceneViewerMixin` — 15 undocumented public methods**,
  including `nextInLibrary`, `applyLoadedScene`, `applyFailedLoad`, `nextCamera`,
  `onPhysicsModeChanged`, `toggleAnimation`. This is the class `docs/viewer.html`
  tells an application to embed. Its *module* docstring is excellent and names six
  overridable methods; the class has around forty public methods.
- **`move/physicsplatform.py::PhysicsViewPlatform` — 11 undocumented public
  methods** (`set_move`, `set_fly`, `set_swim`, `jump`, `blocked`, `apply`), and
  the class itself has no docstring. This is the walking API.

Full lists: 26 public classes and 41 public module-level functions carry no
docstring at all.

### Fix

Not "document everything" — that produces `"""Set the move."""`. Three targeted
passes, in this order:

**7a. Repair the eleven wrong or duplicated summary lines.** Half an hour, and it
removes the reader's reason to distrust the rest.

- `toolsfont.py` → *"Filled and extruded 3D glyphs from TrueType outlines, via
  FontTools."*
- `indexedlineset.py` → *"IndexedLineSet: polyline geometry with per-vertex or
  per-line colour, drawn through the shader pass or as a display list under the
  compatibility profile."*
- `flatcompat.py` → *"The compatibility-profile flat pass: fixed-function
  lighting and materials, `glLight*`/`glMaterial*`, display lists."*
- `flatcore.py` → *"The core-profile flat pass: the VRML97 lighting model in
  GLSL, drawn through `VRML97ShaderProgram`."* Drop the sentence containing
  "now".
- `passes/_flat.py` keeps its base-class summary but should say which of the two
  subclasses a caller actually instantiates, pointing at
  `renderpass.defaultRenderPasses`.

**7b. Give the fifteen 300-plus-line legacy modules the body their newer
neighbours have.** The bar is `renderoptions.py` and `hud.py`: what the module is
for, what a caller does with it first, and the one thing that is not obvious.
`move/viewplatform.py`, `contextdefinition.py`, `texture.py`, `atlas.py`,
`events/mouseevents.py`, `scenegraph/shaders.py`, `scenegraph/text/font.py` are
the highest-traffic.

**7c. Document the two public APIs above, method by method** — `SceneViewerMixin`
and `PhysicsViewPlatform` — because they are what a game calls. One line each is
enough for the obvious ones (`nextCamera`, `previousCamera`); `applyLoadedScene`,
`applyFailedLoad`, `blocked` and `apply` need to say which thread they run on and
what a subclass is allowed to do in them, which is exactly what the module
docstring already does well for the six it covers.

For the remaining undocumented methods, the rule to write into `CLAUDE.md` is:
**an override of a protocol method documented on the base class does not repeat
it; anything else public gets a line.** That converts most of the 581 into "no
docstring needed, by rule" and leaves a list short enough to finish.

---

## 8. Five docstrings point at modules that moved

An automated check of every `OpenGLContext.<dotted.path>` inside a docstring
against the modules that exist:

| Where | Says | Should say |
|---|---|---|
| `context.py:97` | `OpenGLContext.basenodes.sceneGraph` | `OpenGLContext.scenegraph.basenodes.sceneGraph` |
| `context.py:724` | `OpenGLContext.eventhandlermixin.EventHandlerMixin` | `OpenGLContext.events.eventhandlermixin.EventHandlerMixin` |
| `context.py:1165` | `OpenGLContext.loader` | `OpenGLContext.loaders.loader` |
| `move/direct.py:133` | `OpenGLContext.viewplatform.ViewPlatform.straighten` | `OpenGLContext.move.viewplatform.…` |
| `move/viewplatform.py:22` | `OpenGLContext.viewplatformmixin.ViewPlatformMixIn` | `OpenGLContext.move.viewplatformmixin.ViewPlatformMixin` |

The last is wrong three ways — the package, the module and the capital `I` in
`MixIn` (the class is `ViewPlatformMixin`). The same class docstring also says:

> *"Shadow-rendering Context's will actually use a subclass which generates
> 'infinite' perspective views required by the particular stencil-buffer shadowing
> algorithm."*

The stencil shadow-volume system was removed
([CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md) B2); no such subclass
exists. The only `ViewPlatform` subclasses are `edit/orbitview.py:177` and
`edit/mapview.py:171`.

**Fix:** correct the five paths, delete the stencil sentence, and add the check
itself as a test — walk every docstring for `OpenGLContext.…` references and
assert the longest module-shaped prefix imports. Six lines of pytest, and it never
happens again.

**Also:** `docs/gltf.html:119` sends the reader to `tests/pbr_gltf_demo.py`, which
was folded into `oglc-gltf-demo`. Point it at `oglc-gltf-demo` and
`OpenGLContext/bin/gltf_demo.py`.

**And:** the six markdown-style links inside docstrings
(`viewer/__init__.py:43`, `viewer/adapters/__init__.py:17`,
`sceneviewer.py:48`, `move/physicswalk.py:36`, `move/terrainwalk.py:35-36`) render
as literal brackets in `pydoc`. Three of them also point at the wrong page:
`viewer/__init__.py`, `viewer/adapters/__init__.py` and `sceneviewer.py` all cite
`docs/gltf.html` when `docs/viewer.html` is the page about the viewer. Settle on
one form — `See ``docs/viewer.html``.` — and use it everywhere.

---

## 9. The documented extension mechanism is not the implemented one

`docs/structure.html:39`:

> *"Context classes are registered via SetupTools `entry_points` in the `setup.py`
> script. You can register context classes for your GUI library and produce a
> `.egg` file which will plug into OpenGLContext."*

`scenegraph/basenodes.py:5` says the same for nodes, with a worked example:

```python
entry_points = {
    'OpenGLContext.scenegraph.nodes': [
        'NodeName = full.path.to.the.Class',
    ],
}
```

There is no `setup.py` in the repository, `pyproject.toml` declares no
`entry_points` beyond `[project.scripts]`, and `OpenGL.plugins.Plugin.__init__`
simply appends to a class-level list. Registration is the direct calls in
`OpenGLContext/__init__.py:29-56`. A third party following either page registers
nothing.

`docs/viewer.html` documents the mechanism correctly for adapters, with a working
example. So the project has two contradictory accounts of the same registry.

**Fix:**

1. Rewrite `structure.html`'s paragraph to match `viewer.html`: registration is a
   call to `OpenGLContext.plugins.Context('name', 'dotted.path.to.Class')` made at
   import time by the registering package, and a third party's package is reached
   because the application imports it.
2. Rewrite `basenodes.py`'s docstring the same way, replacing the `entry_points`
   block with `plugins.Node('MyNode', 'mypackage.nodes.MyNode')`.
3. Remove the `XXX` note about overriding built-in nodes from `basenodes.py`, or
   turn it into a plan entry. An `XXX` in a user-facing module docstring reads as
   a note to the maintainer that the reader was not meant to see.
4. `structure.html:230` names two commands that do not exist — `oglc-ui`
   (registered as **`oglc-ui-demo`**) and **`oglc-profile`** (not registered at
   all; `bin/profile_view.py` has a `main()` with no entry point) — and omits
   `oglc-character-sheet`. Decide whether `oglc-profile` should be registered, then
   make the list match `pyproject.toml`.
5. Add a test that reads `[project.scripts]` and asserts each `docs/`-mentioned
   `oglc-*` name appears in it.

---

## 10. There is no environment-variable reference

41 `OPENGLCONTEXT_*` and `PYOPENGL_*` variables are read by the package. They are
described across 13 different feature pages, and five are described nowhere:
`OPENGLCONTEXT_ENV_CUBEMAP`, `OPENGLCONTEXT_ENV_HDR`,
`OPENGLCONTEXT_MAXIMUM_LIGHTS`, `OPENGLCONTEXT_PICKING`,
`OPENGLCONTEXT_GLTF_BASELINE`. `CLAUDE.md` documents nine of them in detail, which
helps a contributor and reaches no user at all.

`renderoptions.ENVIRONMENT` is already the canonical list.

**Fix:** add `docs/environment.html`, linked from `documentation.html` under a new
"Reference" heading, with one table: name, what it changes, accepted values,
default, and the feature page that explains it. State the two facts that are
currently only in the code — that a value which is neither a yes nor a no is
ignored with a warning rather than treated as true, and that `auto` on `IBL` and
`transmission` means the engine decides. Generate the skeleton from
`renderoptions.ENVIRONMENT`, `CHOICES` and `LABELS` so the page and the tuple
cannot drift; the same test proposed in finding 6 then covers both.

---

## 11. `nav/` is invisible

`OpenGLContext/nav/navmesh.py` builds a navigation mesh from a collision mesh,
does A* over the cells and string-pulls the result through the portals. Its module
docstring is one of the best in the package — it explains why the mesh is
generated rather than baked, and why the string pull matters. It has a unit test
(`tests/unit/test_nav_mesh.py`).

It has no page under `docs/`, no line in `documentation.html`, no entry in
`plans/PROJECT-PLAN.md`, no demo, and no mention in `README.md`. The word
"navmesh" does not appear anywhere in `docs/`.

**Fix:** a short `docs/navmesh.html` — what `build()` takes, what `path()`
returns, the slope threshold and its units, what the string pull does and where it
does not help — linked from `documentation.html` under *Supporting Features*
beside *Movement Modes & Navigation*, and cross-linked from `physics.html` since
the collision mesh is where the input comes from. A row in `PROJECT-PLAN.md`. A
demo, per finding 12.

---

## 12. The demos demonstrate the 1998 engine

`tests/` holds roughly 150 runnable scripts. Twelve are NeHe tutorial ports, a
dozen are `redbook_*`/`glget*`/`arb*` probes of individual GL calls, and eighteen
are `shader_*` tutorials. That is the right library for the tutorials, and
`docs/tutorials/` (34 pages) is built on it.

What has no runnable demo:

| Feature | Documentation | Demo |
|---|---|---|
| Roads | `docs/roads.html` | none |
| Water | `docs/water.html` | none |
| HUD & developer overlay | `docs/hud.html` | none |
| Session telemetry | `docs/telemetry.html` | none |
| Rigged characters, crowds | `docs/characters.html` | `oglc-character-sheet` (a contact sheet, not a scene) |
| Baking a world | `docs/baking.html` | none |
| Video recording | `docs/recording.html` | none |
| Editing (tool modes, plan view) | `docs/editing.html` | none |
| Navigation mesh | none | none |
| Pass-level instancing | `docs/instancing.html` | `shader_*_instanced.py` demonstrate raw GL instancing, not the batcher |

Ten features carry a documentation page each and no way to see them run. The
workspace rule is that the engine is the product and the demos are how it is
driven; a feature with a page and no demo has been described but not exercised
from the outside.

**Fix:** one small script per row, in `tests/`, following the shape of
`particles_effects.py` and `physics_gravity_zones.py` — under 150 lines, opens a
window, shows the one thing, and is picked up by `TestVisualRegression` so it also
becomes a rendering check. Named for the feature: `roads_demo.py`, `water_demo.py`,
`hud_demo.py`, `telemetry_demo.py`, `crowd_demo.py`, `bake_demo.py`,
`recording_demo.py`, `editing_demo.py`, `navmesh_demo.py`,
`instancing_batched.py`. Link each from the foot of its documentation page — the
pages currently link to unit tests, which is the wrong audience.

Do these in the same commit as any future feature, per the workspace rule that
documentation ships with the change; the ten above are the backlog from before
that rule was applied.

---

## 13. The first pages a reader meets describe an older project

**`OpenGLContext/__init__.py`'s docstring** — the first thing `pydoc
OpenGLContext` and `help()` show:

> *"Taking advantage of this simplified environment, we have provided a number of
> testing modules… (note that there are unfinished contexts)."*

`README.md` and `docs/structure.html` both say the opposite: five first-class
backends, none a candidate for removal, and *"closer to a game engine than a
demonstration library"*. Rewrite the docstring to match, in four or five lines,
naming what the package is now: contexts across five toolkits, a VRML97/glTF
scenegraph, core-profile and PBR render passes, physics, audio and a viewer.

**`CLAUDE.md`'s "Directory Structure" block (line 39)** lists `passes/`,
`scenegraph/`, `shaders/`, `events/`, `move/`, `loaders/` and `ui/`. It omits
`audio/`, `bin/`, `character/`, `debug/`, `edit/`, `nav/`, `physics/`,
`resources/`, `telemetry/`, `testing/`, `tests/`, `video/` and `viewer/` — 13 of
21 packages, including several of the most recently built. "File Locations" (line
505) repeats the same partial list. This is the map an agent or a new contributor
uses to decide where a change belongs, so its gaps become misplaced code.

**`README.md`** is headed `3.0.0a1` while `__init__.py:23` says `3.0.0a2`, and its
"What it does" list does not mention water, roads, telemetry, video recording,
world baking, crowds or the navigation mesh — all of which have documentation
pages.

**Fix:** update all three. For `CLAUDE.md`, one line per package, and add the rule
that the block is updated whenever a package is added — it is cheap to keep
current and expensive to rebuild from scratch. For `README.md`, take the version
from `__init__.py` and add the six missing bullets.

---

## What landed, and what is left

Steps 1–7 are on branch `docs-structure-review`, six commits, based on
`develop` at `f702190`. Full unit suite after: **6298 passed, 0 failed**
(`OPENGLCONTEXT_GLTF_BASELINE` must be pinned when running from a worktree
outside the workspace, since the baselines are a sibling directory).

| Step | Work | State |
|---|---|---|
| 1 | Delete `viewer/options._env_flag`/`_env_float` | ✅ Done |
| 2 | `ENVIRONMENT`: the two rendering settings, the dead variable | ✅ Done |
| 3 | Five docstring paths, the stencil sentence, the docs paths, the reference test | ✅ Done |
| 4 | The wrong and duplicated summary lines | ✅ Done |
| 5 | The `.egg` paragraphs and the command list | ✅ Done |
| 6 | Root docstring, `CLAUDE.md` map, `README.md` | ✅ Done |
| 7 | `docs/environment.html` | ✅ Done |
| 8 | Package front doors and `__init__` docstrings (finding 4) | 📋 Open |
| 9 | The naming rule; apply it to `ui/` (finding 1) | 📋 Open |
| 10 | `matrices.py` and `culling.py`, with shims (finding 2) | 📋 Open |
| 11 | `hud.py` → `ui/layoutbase.py` (finding 3) | 📋 Open |
| 12 | `docs/navmesh.html` (finding 11) | ✅ Done |
| 13 | Ten demos (finding 12) | 📋 Open |
| 14 | Legacy module docstrings, the two public APIs (finding 7b, 7c) | 📋 Open |

### Found while implementing, and not in the original findings

- **`viewer/options.py` read a bare `YAW`.** Unnamespaced, so a variable
  belonging to anyone else in the shell turned the framing camera and every
  capture made there. It is `OPENGLCONTEXT_VIEW_YAW`, and in `ENVIRONMENT`.
- **`Context.getSceneGraph`'s worked example did not run** — there is no
  `loader.vrml97` to import from. It is `Loader.load` now.
- **`OPENGLCONTEXT_MAXIMUM_LIGHTS` was read by nothing** (finding 6 above).
- **`flatcore.py`'s docstring example** told the reader to set
  `use_shaders=True`, which that class has defaulted to true for some time.
- **`bin/profile_view.py`** has a `main()` and no entry point, and its usage
  string named `vrml_view.py`. `docs/structure.html` promised it as
  `oglc-profile`. The promise is withdrawn rather than the command registered:
  it opens VRML97 only, where `oglc-view` opens four formats, so a profiling
  option on `oglc-view` is the right shape if it is wanted. Whether the module
  moves out of `bin/` is [CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md)
  C1's call.

### What the demos turned up (branch `demos`)

Ten demos landed, one per documented feature that had none, each with a render
in its page captioned with what it shows and the command to run it, and each
carrying runnable sample code that was executed before it was pasted.
`tests/unit/test_feature_demos.py` renders every one offscreen and checks its
page names it and shows it; the five that move are marked randomized so the
visual suite does not diff a frame that is never the same twice.

**Building them found five engine defects.** Every one was invisible to the
unit suite and visible the moment something tried to use the feature from
outside — which is the argument for demos, made concrete.

| Defect | Where | Effect |
|---|---|---|
| `OnQuit` discarded buffered stdout | `context.py` | `os._exit` with no flush, and stdout is block-buffered on a pipe — every demo's printed output was lost under the harness and only looked right run by hand |
| A `Background` of one `skyColor` painted nothing | `spherebackground.py` | Two causes stacked: `colorSet` returned an empty set, and once that was fixed `buildSphere` still made a degenerate two-vertex sphere. Two agents hit it independently; one worked around it, one shipped a black sky |
| A pick event carried the last drawn node's matrix | `selection.py`, `asyncpick.py` | `self.matrix` is rewritten per node by the traversal, so `event.unproject()` answered in that node's local space. Every editor tool built on `edit.surface` was off by that node's transform |
| `LampRow` defaulted to an anchor `place()` does not know | `ui/hudwidgets.py` | `'top-center'` is not in `ANCHORS`, so the fallback put a default lamp row in the middle of the screen |
| Shadow acne on GPU-displaced water | `passes/shadow*`, `scenegraph/water` | A moved sheet casts its shadow map from the flat mesh the CPU still holds, so it shadows itself in bands. **Not fixed** — recorded, and the water demo pins `OPENGLCONTEXT_SHADOWS=0` |

**Also not fixed, and worth its own work:** the environment-specular term is not
weighted by the Fresnel factor a dielectric needs, so water's F0 of about 0.02
takes far more of the environment than it should and open water reads pale.
`OPENGLCONTEXT_IBL_INTENSITY` does not scale that term. It lives in the PBR
shader and pass, which were being edited elsewhere while this branch was
written. `docs/water.html` states both limits.

**One thing to watch:** `crowd_demo` opens a Khronos sample model. It is in the
asset cache here, and the test skips rather than fails where it is absent, so a
machine with no network reports honestly instead of going red.

### Notes for whoever merges this

- **`OpenGLContext/telemetry/` is not in this branch.** It was uncommitted work
  in the primary checkout when the branch was cut, so `CLAUDE.md`'s directory
  map has no line for it. `test_documentation_references.py` fails until one is
  added, which is the intended prompt.
- **`renderoptions.ENVIRONMENT` is edited on both sides.** This branch appends
  two names; the primary checkout appends the telemetry trio and
  `OPENGLCONTEXT_SEED`. Both are additions to the same tuple — take both, and
  add the new names to `docs/environment.html`, which its own test requires.
- **`CLAUDE.md` is edited on both sides** but in different regions: the
  directory map at the top here, the environment-variable section around line
  333 there.

## Not proposed

- **Renaming `scenegraph/`, `events/` or `move/` methods.** Their camelCase is the
  VRML97 field vocabulary and the `Context` protocol. The rule in finding 1 applies
  to new code there, not a sweep.
- **Removing the compatibility profile or any backend.** Settled in
  [CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md) (B5b declined, the
  platform commitment).
- **Splitting `context.py`.** [GOD-OBJECT-DECOMPOSITION.md](GOD-OBJECT-DECOMPOSITION.md)
  is complete; 1307 lines for the class every backend derives from is not the
  problem this review found.
- **Converting `docs/` to a generator.** The hand-written HTML is consistent,
  fully cross-linked and better written than most generated reference. Only
  `environment.html` should be generated, because it mirrors a tuple in the code.
