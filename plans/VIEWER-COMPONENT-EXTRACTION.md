# Extracting a reusable viewer: `OpenGLContext/viewer/` and physics on any context

**Status: complete (2026-08-02).** `bin/gltf_view.py` fell from 1,288 lines to
270; `OpenGLContext/viewer/` (9 modules) and
`move/physicswalk.py::PhysicsWalkMixin` are its two new homes. Full unit suite
green (4,153 tests), `ruff` and `mypy --follow-imports=silent` clean on every
touched path, and the new modules are at 100% line coverage except
`gltfviewer.py` at 93% (the gap is `OnInit`/`OnIdle`/`SwapBuffers`, which need a
live GL loop and are covered by the subprocess and visual suites). No console
script was renamed, added or removed.

Three things were found while doing it, and are recorded in *Defects found* below:
a real `omi_physics` bug (fixed), a weakness in the spawn clearance probe (left
as-is, documented), and a mix-in name collision that killed the first live render
(fixed, with a test that catches the whole class).

## The problem this solved

`bin/gltf_view.py` was 1,288 lines, of which perhaps 120 were a command-line
program. The rest was a glTF viewing *component* with no name and no home: async
scene loading, scenegraph assembly, default lighting, auto-framing, camera
cycling, animation transport, a text overlay, screenshot handling, and a
walk-mode physics avatar with spawn placement. None of it could be used by
anything that was not `oglc-gltf` — `oglc-gltf-demo` reached it only by
subclassing the script's `TestContext` and overriding half-private methods, and
`terrain_view`, `tiles_view` and the sibling `twig-bb` viewer each re-implement
the physics loop from scratch.

This plan gave that code a home, in two layers:

1. **Physics is a capability of any interactive context**, not of one script.
   Enabling walk mode, stepping the character each frame, handing the camera
   between the free-fly navigator and the avatar, spawning the avatar on clear
   floor, and teleporting it to a viewpoint are all context concerns.
2. **A reusable glTF viewing component** — an embeddable mix-in and a ready-made
   context — that an application composes instead of subclassing a script.

It is the enabling phase of [CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md)
§B6 (`oglc-view`), which proposes exactly this shell plus a `SceneAdapter`
protocol and one unified CLI. **This plan deliberately stops short of B6's CLI
consolidation**: no console script is renamed, added or removed, and no format
dispatch is introduced. B6 becomes a much smaller change once the shell exists.

## Goal

- `oglc-gltf` and `oglc-gltf-demo` behave identically, pixel for pixel and flag
  for flag, before and after.
- Embedding a glTF viewer in an application is a subclass with a `ViewerOptions`
  and no argparse:

  ```python
  from OpenGLContext.viewer import GLTFViewerContext, ViewerOptions

  class MyViewer(GLTFViewerContext):
      options = ViewerOptions(source='model.glb', physics=True, background='sky')

  MyViewer.ContextMainLoop()
  ```

- Any interactive context gains walk mode without copying a frame loop:

  ```python
  class MyWorld(BaseContext):
      def OnInit(self):
          self.sg = load_my_world()
          self.enablePhysics(True)      # ViewPlatformMixin capability
  ```

## Naming convention

Context methods are **camelCase**, matching `Context`, `ViewPlatformMixin` and
`ScreenMixin` (`getViewPlatform`, `updateNavigation`, `addHUDLayer`). Module-level
helpers are **snake_case**, matching `move/modes.py` and `passes/`. Names that are
genuinely internal keep a leading underscore. The current code is inconsistent
(`_set_physics` beside `getNavigationPlatform`) because it was written as a script.

## Phase 1 — physics on any interactive context

New module `OpenGLContext/move/physicswalk.py`, class `PhysicsWalkMixin`, mixed
into `ViewPlatformMixin` so **every** interactive context has the capability and
none pays for it until asked: every `omi_physics` / `physics` import stays inside
the methods, so a context that never calls `enablePhysics` never imports the
physics package.

`ViewPlatformMixin.getNavigationPlatform` moves into the new mix-in, where it can
answer "the character controller while walking, the view platform otherwise" in
one place. Today `gltf_view` overrides it to say the same thing.

| `bin/gltf_view.py` today | `PhysicsWalkMixin` |
|---|---|
| `_setup_physics` | `setupPhysics()` |
| `_toggle_physics` | `togglePhysics(event=None)` |
| `_set_physics(on) -> bool` | `enablePhysics(on) -> bool` |
| `_ensure_physics` | `ensurePhysicsWorld() -> bool` |
| — | `buildPhysicsWorld() -> (world, bounds)` — **seam**, default from `self.sg` |
| — | `characterCapabilities(scale)` — **seam** |
| `getNavigationPlatform` | `getNavigationPlatform()` (also removed from `ViewPlatformMixin`) |
| `_bind_physics_input` | `bindPhysicsInput()` |
| `_sync_avatar_to_camera` | `syncAvatarToCamera()` |
| `_spawn_from_viewpoint_or_floor` | `spawnAvatar(lo, hi, caps, viewpoints=())` |
| `_clearance` | `_clearance` (module function) |
| `_yaw_from_platform` | `yawFromPlatform()` |
| `_yaw_from_viewpoint` | `yaw_from_orientation(orientation)` (module function) |
| *(the physics block inside `_cycle_viewpoint`)* | `moveAvatarToViewpoint(vp)` |
| `_physics_step` | `stepPhysics(dt=None)` |
| `_pkey` / `_pfly` | `_physicsKey` / `togglePhysicsFly` |
| `_physics` / `_physics_on` | `physicsPlatform` / `physicsWalking` |

Two things become genuinely reusable rather than incidentally private:

- **`spawnAvatar`** — "find a free viewpoint". The centre of a model is usually
  solid (a statue, thick walls), so it scores candidate footprint positions by how
  many of four horizontal directions the avatar can actually *move* into, and
  stands it on the best. Any world-loading context wants this.
- **`moveAvatarToViewpoint`** — "move the avatar to a defined view". Sets yaw from
  the viewpoint's orientation, safe-binds the eye to its position, and floats
  rather than falls when the viewpoint is aerial.

`_physics` and `_physics_on` are renamed because they become public API; the old
names are not kept as aliases (they were private, and `gltf_demo` — the only
outside user — is updated in the same change).

**Not in scope for this phase:** rewriting `terrain_view`, `tiles_view` or
`twig-bb` onto the mix-in. They keep working untouched. Doing so is worth its own
task and is listed under *Follow-on work*.

## Phase 2 — the reusable pieces

New package `OpenGLContext/viewer/`. Each module is independently useful and
independently testable without GL where possible.

```
OpenGLContext/viewer/
    __init__.py      GLTFViewerContext, GLTFViewerMixin, ViewerOptions
    options.py       ViewerOptions
    source.py        is_url / resolve_source / load_gltf_source
    framing.py       pure camera-placement maths
    environment.py   sky / cubemap / HDR Background construction, count_lights
    asyncscene.py    AsyncSceneMixin
    overlay.py       TextOverlayMixin, ScreenshotMixin
    capture.py       SettleCaptureMixin
    gltfviewer.py    GLTFViewerMixin, GLTFViewerContext
```

### `options.py` — `ViewerOptions`

A frozen-by-convention (but mutable — `gltf_demo` rewrites `yaw` and `background`
per model) dataclass carrying every knob the component reads: `source`, `camera`,
`no_cameras`, `capture`, `capture_delay`, `frames`, `shadows`, `lights`,
`ibl_intensity`, `environment`, `background`, `size`, `physics`, `turntable`,
`no_rotate`, `animation`, `animate`, `anim_time`, `yaw`, `margin`, `elevation`,
`tilt`, `eye`, `look_at`.

**The dataclass owns the defaults, and the CLI parses into it.** `argparse` sets
attributes on any object handed to it, so `build_parser().parse_args(argv,
ViewerOptions())` returns a populated `ViewerOptions` — one options type for the
library and the command line, with no translation layer to drift. Every
`add_argument` gets `default=argparse.SUPPRESS` so an option the user did not pass
leaves the dataclass default in place instead of overwriting it with `None`.

This removes the ~20 `getattr(self.config, 'name', fallback)` calls scattered
through the current code, each of which is a second, silent copy of a default.

`self.config` stays as the attribute name (`gltf_demo`, the regression harness and
a dozen tests use it); `options` is the alias on the component.

### `source.py`

`_is_url`, `_resolve_source`, `_load_source` become `is_url`, `resolve_source`,
`load_gltf_source`. Resolving and fetching a model is loading, not command-line
handling; `main()` needs them for `--list-cameras` and imports them.

### `framing.py`

`_frame` and `_frame_eye_lookat` each compute a camera pose and then push it into
`self.platform`. Split the maths out as pure functions —
`fit_sphere(radius, margin, elevation, tilt)` and `look_from(eye, target)`, each
returning `(fov, near, far, position, orientation)` — leaving one-line context
methods that apply the result. The maths is then unit-testable with no GL and no
context, which is most of what those methods are.

### `environment.py`

`_sky`, `_make_background`, `_env_hdr_background`, `_env_cube_background` and
`_count_lights` become module functions. Constructing "the skybox that matches
what the IBL probe reflects" from `OPENGLCONTEXT_ENV_HDR` /
`OPENGLCONTEXT_ENV_CUBEMAP` is engine behaviour, not viewer behaviour, and today
nothing else can reach it.

### `asyncscene.py` — `AsyncSceneMixin`

The download-off-thread / build-on-the-render-thread handoff, with **no glTF in
it**: `requestScene(produce, label)`, `pollPendingScene()`, `applyLoadedScene`,
`applyFailedLoad`, and the token/lock/flags that guard a superseded load. Any
context that loads a scene from a slow source wants this; `vrml_view` freezes on
load today for want of it.

### `overlay.py` — `TextOverlayMixin`, `ScreenshotMixin`

`overlay_text` / `overlay_error` and their drawing (`_draw_overlay`,
`_active_shader`, `_viewport`, `_extra_overlay`), and the F2 screenshot queue
(`_request_screenshot`, `_save_screenshot`) which is taken before the buffer swap
because reading after the swap returns stale data in this container.

**Note for a later phase, not this one:** every `Context` already has
`ScreenMixin`, `hudLayers` and `ui/hudwidgets`, so this hand-rolled overlay is a
second text-drawing path. Folding it onto a `HUDLayer` is the right end state but
it changes what the overlay looks like and interacts with the "a clean `--capture`
skips the HUD" rule, so it is listed under *Follow-on work* rather than smuggled
into a refactor that is supposed to change nothing.

### `capture.py` — `SettleCaptureMixin`

Installing `SettleCapture` from the options, ticking it before the swap, emitting
the `CAPTURE_STATS load_seconds=… fps=…` line the regression runner parses, and
quitting. Nothing about it is glTF-specific.

## Phase 3 — the glTF component

`gltfviewer.py` holds `GLTFViewerMixin` — scenegraph assembly (`buildScenegraph`),
the light rig, background selection, framing, camera resolution and cycling,
animation transport (`_setup_animation`, `_resolve_animation`, `_advance_animation`,
play/pause, next/previous), the turntable, and the overlay text composition — plus
`GLTFViewerContext`, which is that mix-in over `AsyncSceneMixin`,
`TextOverlayMixin`, `ScreenshotMixin`, `SettleCaptureMixin` and the interactive
base, with `OnInit` / `OnIdle` / `SwapBuffers` / `setupCallbacks` wired.

`movement_modes()` and its `WALK_SPEED` / `RUN_SPEED` / `FLY_SPEED` /
`TURN_RATE` / `TURN_ACCELERATION` constants move to `move/modes.py` as
`walk_fly_modes(scale=1.0)`: they describe navigation, not glTF, and a second
viewer wanting the same two modes should not import a script to get them.

`bin/gltf_view.py` is then the program: the module docstring and its controls
table, the `os.environ.setdefault` render preamble, `build_parser`, `parse_args`,
`apply_render_env`, `_is_hdr_environment`, `_parse_size`, `_parse_vec3`,
`TestContext(GLTFViewerContext)` and `main()`. Roughly 300 lines, nearly all of it
argument definitions and help text.

`TestContext` keeps its name and its module — `gltf_demo`, the regression harness,
`tests/diag_live.py` and `tests/_gltf_toggle_driver.py` all use
`gltf_view.TestContext`, and it is the conventional name for a context class here.

`bin/gltf_demo.py` subclasses `GLTFViewerContext` directly instead of the script's
context, and its per-model profile logic is unchanged.

## Phase 4 — documentation

Per the workspace rule that documentation ships with the change:

- **[docs/gltf.html](../docs/gltf.html)** — a new section on embedding the viewer:
  `GLTFViewerContext`, `ViewerOptions`, and which methods are the seams
  (`_load_scene`, `buildPhysicsWorld`, `_extra_overlay`).
- **[docs/physics.html](../docs/physics.html)** — walk mode as a context
  capability: `enablePhysics`, `buildPhysicsWorld`, `spawnAvatar`,
  `moveAvatarToViewpoint`, and that it is available on every interactive context.
- **[docs/navigation.html](../docs/navigation.html)** — `getNavigationPlatform`
  now lives on the physics mix-in; `walk_fly_modes` is where the viewer's two
  declared modes come from.
- **[docs/structure.html](../docs/structure.html)** — `OpenGLContext/viewer/` in
  the package map.
- **[CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md)** §B6 — record that the
  shell exists and that B6 is now adapters + CLI only.
- **[PROJECT-PLAN.md](PROJECT-PLAN.md)** — summary row.

## Method

Red/Green TDD throughout, which for a move-shaped change means: the test that
proves the *new seam* is written first and fails because the seam does not exist
yet, not merely because an import moved.

The genuinely new behaviour to drive out red-first:

1. A plain interactive context — one that has never heard of glTF — enabling
   physics over a hand-built scenegraph and stepping it.
2. `buildPhysicsWorld` overridden to supply a world the context did not build
   from `self.sg` (this is what `terrain_view` and `twig-bb` need and cannot do
   today).
3. `spawnAvatar` picking a clear footprint in a scene whose centre is solid.
4. `moveAvatarToViewpoint` floating rather than falling from an aerial viewpoint.
5. `GLTFViewerContext` driven from a `ViewerOptions` with no argparse anywhere.
6. `ViewerOptions()` defaults equalling `parse_args([])` field for field — one
   test that pins the CLI and the library together permanently.
7. `fit_sphere` / `look_from` as pure maths, with no context at all.

The ~1,900 existing lines of tests across `test_gltf_view_*.py`,
`test_gltf_demo_*.py` and `test_physics*.py` are the regression net for everything
that only moves; they call through `V.TestContext._method(inst)`, which keeps
resolving through inheritance. Tests that name a moved *module-level* helper
(`V._count_lights`, `V._is_url`, `V._resolve_source`, `V._load_source`) are updated
to import from the new home rather than being propped up by re-export aliases —
they are our tests, and an alias kept only to avoid editing a test is exactly the
cruft this refactor is removing.

Gates before done, per [../CLAUDE.md](../CLAUDE.md) and
[../openglcontext/CLAUDE.md](CLAUDE.md):

- Full suite green — not the touched files, the whole run.
- `ruff check` clean and `mypy --follow-imports=silent` clean on
  `OpenGLContext/viewer/`, `OpenGLContext/move/` and `OpenGLContext/bin/`.
- Coverage at or near 100% on the new modules.
- A live render of `oglc-gltf` and `oglc-gltf-demo` in both walk and free-fly, and
  a `--capture` compared against its reference image.

## Risks

| Risk | Handling |
|---|---|
| `ViewPlatformMixin` gains a base class, changing the MRO of every backend context | The mix-in defines nothing the backends define; `getNavigationPlatform` is *moved*, not duplicated, so there is one definition either way. A test asserts the MRO of each shipped context class. |
| `argparse.SUPPRESS` defaults behave subtly differently (`--list-cameras`, the optional positional) | The defaults-parity test (method item 6) covers every field; `--help` output is compared before and after. |
| `gltf_demo` sets `_physics_explicit`-style attributes on the config object | A plain dataclass has a `__dict__`, so ad-hoc attributes still work. Longer term they should be real fields; not in this change. |
| A capture drifts by a pixel and the reference regression goes red | Capture is compared before and after on the same machine; the render path is not touched at all, only where its inputs are read from. |
| The refactor grows to include the HUD unification or B6's adapters | Both are explicitly out of scope and listed below. |

## Defects found while doing this

**1. `omi_physics.CharacterController.safe_bind` reported a stale `grounded`
(fixed).** A bind resets `flying`, `stuck`, `vy` and `push` for the new pose but
left `grounded` as it was before, so binding to a viewpoint high above a scene
— where the 4-unit floor snap finds nothing — still answered "standing". Callers
asking "is there ground under me?" to choose between walking and flying got the
wrong answer and started the avatar falling out of the shot, which is the exact
opposite of what `moveAvatarToViewpoint` documents. `_ground_snap` now clears it
before searching. Red test first, in `omi_physics/tests/test_character.py`.

**2. The spawn clearance probe is a placement test, not a swept move (left
as-is).** `_clearance` puts the capsule an arm's length along each direction and
depenetrates it. Its reach is `radius + 0.5` — a **fixed** margin, not one scaled
to the avatar — so for the avatar sizes most models produce (radius ≈ 0.15 at
scale 0.5) a wall can never both be touched by the probe *and* push it back far
enough to count as blocking. On a typical model it therefore reports "open in all
four directions" almost always, and the spawn takes the first grounded candidate.
Two further limits: it does not sweep, so a barrier thinner than the capsule is
invisible to it, and against a triangle soup `_push_out` can resolve *into* a
block rather than back out of it, reading a solid as clear.

This is pre-existing and was moved unchanged, because fixing it changes where
avatars spawn in every model and wants visual verification of its own. The code
and `docs/physics.html` now describe what it actually does rather than what the
old comment claimed. **Worth a task**: scale the reach to the avatar and use a
swept move.

**3. A mix-in silently shadowed a context method (fixed).** `TextOverlayMixin`
declared `overlayFontSize = 16`; `ScreenMixin` — which every context has —
defines `overlayFontSize()` as a *method*. Composing them replaced the method
with an integer and the first live frame died in `renderShaderOverlay` with a
traceback naming neither mix-in. Renamed to `captionFontSize`, and
`tests/unit/test_viewer_component.py` now asserts that no viewer mix-in shadows
anything in the context's MRO except a listed set of deliberate overrides — so
the next one is a test failure rather than a puzzling crash.

## Follow-on work (deliberately not in this plan)

- Move `terrain_view`, `tiles_view` and the `twig-bb` viewer onto
  `PhysicsWalkMixin`, deleting three copies of the frame loop.
- Move `vrml_view` and `ui_demo` onto `walk_fly_modes`, deleting their own
  `movement_modes()`. Left alone here because the shared helper carries the
  glTF viewer's turn tuning (`turnRate` 0.9, `turnAcceleration` 3.0) and
  `vrml_view` currently gets the field defaults (2.0 / 1.0), so switching it
  changes how that viewer turns — a deliberate feel change, not a refactor.
- Fix the spawn clearance probe (defect 2 above): scale its reach to the avatar
  and make it a swept move rather than a placement test.
- Give OpenGLContext a `serial` pytest marker for its two clock-sensitive tests,
  as `omi_physics` already has (see `CLAUDE.md` §Testing).
- Fold `TextOverlayMixin` onto `ScreenMixin`/`HUDLayer` so there is one
  text-drawing path.
- Give `vrml_view` `AsyncSceneMixin` so it stops freezing on load.
- [CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md) §B6 proper: the
  `SceneAdapter` protocol, format dispatch through `plugins.Loader`, and one
  `oglc-view` CLI with the four current names as deprecated aliases.

## Files

| File | Change |
|---|---|
| `OpenGLContext/move/physicswalk.py` | new — `PhysicsWalkMixin` |
| `OpenGLContext/move/viewplatformmixin.py` | inherits the mix-in; `getNavigationPlatform` moves out |
| `OpenGLContext/move/modes.py` | gains `walk_fly_modes(scale)` |
| `OpenGLContext/viewer/` | new package — 9 modules |
| `OpenGLContext/bin/gltf_view.py` | 1,288 → 270, CLI only |
| `OpenGLContext/bin/gltf_demo.py` | subclasses `GLTFViewerContext`; renamed physics attributes |
| `tests/unit/test_physicswalk.py` | new |
| `tests/unit/test_viewer_options.py` | new — defaults parity, library construction |
| `tests/unit/test_viewer_framing.py` | new — pure framing maths |
| `tests/unit/test_viewer_asyncscene.py` | new — the handover, on a non-glTF host |
| `tests/unit/test_viewer_overlay.py` | new — caption + screenshot arrangement |
| `tests/unit/test_viewer_capture.py` | new — settle, grab, report, quit |
| `tests/unit/test_viewer_environment.py` | new — backdrop selection, light counting |
| `tests/unit/test_viewer_component.py` | new — embedding with no argparse; mix-in composition |
| `omi_physics/tests/test_character.py` | a bind reports the pose it made (defect 1) |
| `tests/unit/test_gltf_view_*.py` | updated imports for moved module-level helpers |
| `docs/gltf.html`, `docs/physics.html`, `docs/navigation.html`, `docs/structure.html` | updated |
