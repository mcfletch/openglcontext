# GLinting Steel — large-world authoring, roads, water and the track editor

**Status legend:** ✅ **Complete** — shipped · 🟡 **Partial** — core landed, named pieces
missing · 📋 **Planned** — designed here, not yet built · ⬜ **Todo** — wanted, not yet
designed · 🛑 **Shelved** — deliberately not done.

§A, a minimal §C, §F, §G and §H are built; their status log is §9. §B, §D and
§E are designed here and not yet built.
Everything the plan *leans on* was already built, and that is the point of §3.

## What this is

The forest demo proved the streaming-vegetation engine: DEM-sourced terrain, a splat
material, dense instanced grass and trees with an LOD chain down to impostors, physics
colliders that page with the tiles, and a quality ladder that holds a frame rate. This
initiative drives that engine the rest of the way to a **large, authored game world** —
one a developer *builds* from real elevation and their own annotations, *bakes* into a
streamable tileset, and *ships* inside a game.

The driving application is a racing game, tentatively **GLinting Steel** (`glisteel`),
authored in a **`glisteel-editor`**. A designer loads a real area — "San Francisco",
say — draws a road across it, drops rivers and lakes, and the tools generate a world:
the road baked with its shoulders, embankments and background reflections; vegetation
matched to the forest demo's distribution but held to far LODs except where the road
runs; the whole thing partitioned into an octree and written out as baked, streamable
tiles with glTF content per branch. The car game then streams that world at 60 fps.

**The product is the engine, not the game.** `glisteel` and `glisteel-editor` are
advertisements — a way to drive, showcase and stress the authoring and runtime engine —
exactly as the forest demo and twig-bb are. Every capability a *second* game or editor
would want identically is built as an owned, reusable engine API and *called* by the
apps. This document is mostly about those engine capabilities; the two new repos are the
thin wrappers that prove them.

---

## 0. Three decisions taken up front

These shape the whole plan and are settled, with rationale, so later sections do not
re-litigate them.

1. **The reusable authoring core lives in a new `OpenGLContext_editor` sibling project,
   not in OpenGLContext itself.** The *runtime* — the nodes a shipped game renders (road
   mesh, water surface, the tiles3d streamer that already exists) — stays in
   OpenGLContext, so a game that only links the runtime stays lean. The *authoring* half
   — world generation (roads, water simulation, DEM→splat, road-aware refinement), the
   **tile baker**, and the editor UI toolkit (menus, tool-modes, gizmos, ortho map) —
   goes in `OpenGLContext_editor`. A car game imports OpenGLContext; the track editor
   imports both. This keeps heavy generation and editor code out of every game's
   dependency tree without scattering it demo-side where a second editor could not reuse
   it.

2. **We build our own glTF 2.0 writer and 3D Tiles writer.** OpenGLContext today reads
   glTF and reads/streams 3D Tiles; it has no writer for either
   ([`OpenGLContext/loaders/gltf/`](../OpenGLContext/loaders/gltf/) is load-only, and
   the tileset bakers in [`OpenGLContext/loaders/tiles3d/procedural.py`](../OpenGLContext/loaders/tiles3d/procedural.py)
   and [`sample.py`](../OpenGLContext/loaders/tiles3d/sample.py) are proof-of-concept
   generators built on `pygltflib`). The requirement is "far more interesting tiles than
   the upstream provides" — our own LOD ladder, road-adjacent refinement, and per-branch
   baked vegetation/impostors. Those are not expressible through a general GIS baker, so
   we own the writer. `py3dtiles` (Apache-2.0, already installed) stays available as a
   *reader/interop* reference and a cross-check, not the write path.

3. **The 60 fps bar is a modern discrete GPU (≈GTX 1060 / RTX 3060-class), at 1080p.**
   This matches the terrain system's stated primary target
   ([TERRAIN-SYSTEM.md](TERRAIN-SYSTEM.md) §1). Integrated GPUs are a first-class reduced
   tier via the quality ladder and dynamic resolution, best-effort at 60. The forest
   demo's measured native-1080p fill floor on an Intel UHD 630 — where trees, terrain and
   billboards cost more than a frame even at the lowest grass setting — is a real limit,
   not a target to gate the game work behind. A racing camera favours far LODs, which is
   leverage the walking forest demo never had (§I).

---

## 1. The rules this work is done under

These are the workspace rules ([../../CLAUDE.md](../../CLAUDE.md), [../CLAUDE.md](../CLAUDE.md))
restated where they bite hardest on *this* plan.

**Features live in the engine.** The division is applied throughout, and §2 makes it a
table. A capability implemented in `glisteel` or `glisteel-editor` that a second game or
editor would want identically is in the wrong place.

**Real-world data is licensed data — treat it like fetched content.** Elevation and
vector data carry terms. SRTM and USGS 3DEP are public domain; Mapzen/AWS Terrain Tiles
aggregate public sources; OpenStreetMap is **ODbL** (share-alike on the *data*, which is
a database-licence question, not a code-copyleft one, but it still governs redistribution
and attribution). No DEM, tile or OSM extract enters any repository. Data is fetched to a
user cache at the user's request — the pattern the forest demo's heightmap provenance
already documents ([TERRAIN-ASSET-FORMATS.md](TERRAIN-ASSET-FORMATS.md)) and twig-bb's
`download.py` already implements — and attribution ships with any world a user bakes.

**Never copy copyleft code, and this plan has two live exposures.** GIS libraries and
game engines both include GPL/AGPL code (GRASS, parts of GDAL's ecosystem, most road/
terrain code in open engines). Any task that would read one follows
[../../CLEAN-ROOM.md](../../CLEAN-ROOM.md): prefer a spec or observed behaviour, split
Reader and Implementer, and let only a numbered spec under `OpenGLContext_editor/specs/`
cross the wall. Road-network and 3D-Tiles-writer facts come from **published
specifications** — the OGC 3D Tiles 1.1 spec, the glTF 2.0 spec, `KHR_*` extension specs —
which are permitted sources; cite the spec, never an implementation.

**Documentation ships with the change.** Each phase names the docs it updates —
OpenGLContext keeps user docs as HTML in [`../docs/`](../docs/) and design notes in
`plans/`; `OpenGLContext_editor` and the two game repos keep theirs in `docs/`/`README.md`.
A phase is not done while a doc still describes the world before it. Each engine phase
also earns a line in [PROJECT-PLAN.md](PROJECT-PLAN.md).

**Red/Green TDD, headless-first.** Every phase names the half of itself that runs without
a window, and designs that to be the larger half. A baker is pure data in, files out; a
road cross-section is geometry; a river flow is a simulation over an array; an octree
partition is a tree over points; a menu layout is metrics. All of it is asserted on
numerically. The GL half is smoke-tested through the existing subprocess-and-capture
harness. The container has a real GPU (GLFW backend) — nothing here is blocked on being
headless.

**Never destroy work to run an experiment.** Bakes write to *output* directories under a
scratch or cache path, always by absolute path; a bake never writes over the working
tree, and a diagnostic never reverts it.

---

## 2. Where each piece lives

Four homes, one dividing line: **does a second game or editor want this identically?**

| Home | Holds | Because |
|---|---|---|
| [OpenGLContext](../) (runtime engine) | 3D-Tiles streaming (exists); **road-mesh render node**; **water-surface render node**; glTF/tiles **writer**; ortho-projection pass; the ray-pick pipeline; anything a shipped *game* renders or loads | every game renders roads/water and streams tiles; the writer is engine machinery a build step calls |
| **`OpenGLContext_editor`** (new) | the **tile baker**; world generation — road generation ops, river/lake simulation, DEM→control-map, road-aware refinement, octree partition; the **editor UI toolkit** — tool-mode framework, menu/dropdown/context menus, gizmos, top-down map view | every *editor* wants these identically; no *game* wants the generation or editor code in its dependency tree |
| **`glisteel-editor`** (new app) | the race-track editor: the specific menus ("add roadway", "add water"), the track/checkpoint model, the project file, editor-session wiring | rules of *this* editor |
| **`glisteel`** (new app) | the car game: vehicle physics and handling, the race rules, camera, HUD content, the baked world it ships or streams | rules of *this* game |

**Repo bootstrap.** Both new projects are git submodules and editable workspace members,
following twig-bb and the forest demo exactly:

- `git submodule add` each new repo under `/workspaces/OpenGL-dev/{name}`.
- Each gets a `pyproject.toml` depending on `OpenGLContext` (and, for the editor,
  `OpenGLContext_editor`; for the game, `omi_physics`) by name — the root
  [`/workspaces/OpenGL-dev/pyproject.toml`](../../pyproject.toml) `[tool.uv.sources]`
  resolves those to editable paths, and running `uv sync` from the workspace root wires
  them.
- Layout: `glisteel` flat like twig-bb (`glisteel/`, tests read files beside the
  package); `glisteel-editor` and `OpenGLContext_editor` may use the `src/` layout the
  forest demo uses. Console scripts in `[project.scripts]`: `glisteel`,
  `glisteel-editor`.
- `OpenGLContext_editor` is not a game; it is an engine-adjacent library and gets the
  same test/lint/type/coverage bar as OpenGLContext, plus a `specs/` and its own
  `CLEAN-ROOM.md` for any GIS/OSM/road-spec reading.

---

## 3. Foundations already in place

This is the leverage. The initiative is mostly *composition and baking* on top of a
streaming engine that already exists, plus four genuinely new subsystems (writer, roads,
water, editor toolkit).

| Foundation | Where | What the phases take from it |
|---|---|---|
| ✅ 3D-Tiles streaming runtime — SSE traversal, LRU residency, prefetch, async load pool, upload throttle, frustum cull | [`OpenGLContext/loaders/tiles3d/`](../OpenGLContext/loaders/tiles3d/): `traversal.py`, `residency.py`, `loadmanager.py`, `runtime.py`, `frustum.py` | the whole runtime consumer of a baked world — §A bakes *for* it, §H streams *through* it |
| ✅ `TilesTerrain` scenegraph node + viewer adapter | [`OpenGLContext/scenegraph/tilesterrain.py`](../OpenGLContext/scenegraph/tilesterrain.py), [`OpenGLContext/viewer/adapters/tiles.py`](../OpenGLContext/viewer/adapters/tiles.py) | mounts a streamed world into a scene and frames the opening view |
| ✅ DEM ingest — grayscale raster → world height function → baked quadtree | [`OpenGLContext/loaders/tiles3d/dem.py`](../OpenGLContext/loaders/tiles3d/dem.py) (`height_function_from_image`, `build_dem_tileset`) | §B's terrain input; extended to georeferenced and multi-block |
| ✅ Procedural terrain baker + per-vertex colour + water clamp | [`OpenGLContext/loaders/tiles3d/procedural.py`](../OpenGLContext/loaders/tiles3d/procedural.py) (`build_terrain_tileset`, `terrain_patch`, `terrain_colors`) | the mesh-generation half §A grows a real writer around |
| ✅ Layered splat terrain material — RGBA control-map blend of N PBR layers, triplanar, macro/detail tiling, baked sun/canopy term | [`OpenGLContext/scenegraph/terrain/splat.py`](../OpenGLContext/scenegraph/terrain/splat.py), [`heightfield.py`](../OpenGLContext/scenegraph/terrain/heightfield.py); format in [TERRAIN-ASSET-FORMATS.md](TERRAIN-ASSET-FORMATS.md) | §B's terrain look; §C paints road/shoulder layers into the control map |
| ✅ Vegetation scatter + full LOD chain — area-weighted scatter, world-grid camera-following scatter, instanced near-mesh, real-geometry clumps, billboard impostors, per-tile physics colliders | [`OpenGLContext/loaders/tiles3d/scatter.py`](../OpenGLContext/loaders/tiles3d/scatter.py), [`vegetation.py`](../OpenGLContext/loaders/tiles3d/vegetation.py), [`OpenGLContext/scenegraph/vegetation/`](../OpenGLContext/scenegraph/vegetation/) (`grid.py`, `nearmesh.py`, `clumps.py`, `billboards.py`), [`physics_colliders.py`](../OpenGLContext/loaders/tiles3d/physics_colliders.py) | §E's distribution and refinement — the forest demo's density is the target §E matches away from the road and thins near it |
| ✅ Quality ladder + async streaming pattern | forest demo [`quality.py`](../../openglcontext-forest/src/openglcontext_forest_demo/quality.py), [`streaming.py`](../../openglcontext-forest/src/openglcontext_forest_demo/streaming.py) | §I's scalable presets; the `AsyncStreamer` off-thread pattern generalises |
| ✅ Overlay UI toolkit — modal panel stack, widget set (Label/Button/Toggle/Select/Slider/Text/Number/KeyCapture), Row/Column/Grid layout, one-program batched renderer, dialogs, settings-from-node generation | [`OpenGLContext/ui/`](../OpenGLContext/ui/); design in [OVERLAY-UI.md](OVERLAY-UI.md) | §F's editor panels and dialogs are built on this; menus and tool-modes are the additions |
| ✅ HUD widget layer — anchored non-interactive overlay, crosshair/bar/readout/message/wash | [`OpenGLContext/ui/hudwidgets.py`](../OpenGLContext/ui/hudwidgets.py), [`OpenGLContext/hud.py`](../OpenGLContext/hud.py) | the editor's status/tool readouts; the game HUD |
| ✅ MRT object picking — colour+id+depth in the forward pass, O(1) CPU lookup, async PBO readback | [`OpenGLContext/passes/selection.py`](../OpenGLContext/passes/selection.py), [`selectionbuffers.py`](../OpenGLContext/passes/selectionbuffers.py), [`asyncpick.py`](../OpenGLContext/passes/asyncpick.py) | §F's "which handle did I click" — the id buffer already answers it |
| ✅ glTF skinning/animation, PBR path, IBL, shadows, sky/environment | [`OpenGLContext/loaders/gltf/`](../OpenGLContext/loaders/gltf/), PBR/IBL/shadow passes | §D's reflections lean on the environment path; baked tile content is glTF the loader already reads |
| ✅ Physics — rigid bodies, trimesh colliders, raycast, character controller | [omi_physics](../../omi_physics/) | §H's vehicle; §D's buoyancy; road/terrain colliders that stream |
| ✅ Clean-room + spec convention, content-fetch-with-consent | twig-bb [`specs/CLEAN-ROOM.md`](../../twig-bb/specs/CLEAN-ROOM.md), [`download.py`](../../twig-bb/twig_bb/download.py) | the pattern for DEM/OSM fetch and for reading any GIS/road spec |

**The direction is aligned, not novel.** The terrain system already chose *authored*
terrain baked to our own tiles over consuming third-party GIS 3D Tiles
([TERRAIN-SYSTEM.md](TERRAIN-SYSTEM.md) "Direction reset"). This initiative is that
north star carried to a full authoring application: a bake pipeline, the annotations
(roads, water) a game world needs, and the editor that drives them.

---

## 4. The gaps this initiative fills

What does *not* exist yet, and which phase builds it:

- **A glTF/3D-Tiles writer** (§A) — the keystone. No scene→glTF export, no tileset/octree
  writer, no b3dm/i3dm packaging. The current bakers are demo-grade.
- **Georeferenced, multi-block DEM + procedural control maps** (§B) — DEM ingest is
  single-image, PIL-only, no CRS; control maps are hand-authored.
- **Roads** (§C) — nothing. No spline/polyline geometry, no cross-section extrusion, no
  bridges/tunnels/causeways, no road material, no reflection bake.
- **Water beyond a flat plane** (§D) — only a clamped water level and a translucent box.
  No rivers, flow, lakes with shaped shorelines, foam, whitewater, beaches or boats.
- **Road-aware refinement and octree partition** (§E) — no spatial partition of a baked
  world, no distance-to-road driving LOD, no near-road detail refinement.
- **The editor toolkit** (§F) — no menu bar, no tool-mode framework, no gizmos, no
  top-down ortho map view. 3D point placement/dragging is *not* a gap: the existing
  depth-aware pick already unprojects the surface point under the cursor (§F).
- **The two apps** (§G, §H) and **the perf work to 60 fps** (§I).

---

## 5. Phases

Ordered so that each phase can be finished, shipped and *seen* before the next, and so
the phases most likely to change the design of the others come first. The keystone (§A)
is first because everything downstream bakes through it; the editor toolkit (§F) is
sequenced after the generation phases so it has real operations to drive, but §F.0 (the
ortho map and tool-mode skeleton) can be pulled forward whenever a UI-shaped stretch
appears.

| # | Phase | Home | Status | Depends on |
|---|---|---|---|---|
| §A | The writer & baker — glTF + 3D Tiles + octree, proven by baking a world | OpenGLContext (writer) + editor (baker) | ✅ | — |
| §B | Terrain authoring — georef DEM, multi-block, procedural control map | editor (+ engine ingest) | 📋 | §A |
| §C | Roads — spec, cross-sections, the four ops, render node, reflections | engine (render) + editor (gen) | 🟡 all four ops, the plan-easing that keeps a route on the ground, and the control-map paint landed; the reflection bake outstanding | §A, §B |
| §D | Water — rivers, lakes, surface render, shorelines, whitewater, beaches | engine (render) + editor (gen) | 📋 | §A, §B |
| §E | Road-aware refinement & octree LOD | editor | 📋 | §A, §B, §C |
| §F | Editor toolkit — tool-modes, menus, picking, gizmos, ortho map | engine (picking/ortho) + editor (toolkit) | 🟡 tool modes, menus, surface picking, the plan view and the translate gizmo landed; rotate/scale handles and occluded picking outstanding | §F.0 independent; rest after §C/§D |
| §G | `glisteel-editor` — the race-track editor app | new repo | 🟡 draws a circuit on the shipped landscape and bakes a world to drive; water and real elevation wait on §D/§B | §B–§F |
| §H | `glisteel` — the car game demo | new repo | ✅ streams, drives, times a lap | §A runtime, §E output |
| §I | Performance to 60 fps on the discrete-GPU target | engine + game | ✅ 106 fps at 1080p driving the shipped world | §H to measure |
| §J | Furniture — signs, obstacles, junctions | engine (render) + editor (gen) | 🔨 | §C |
| §K | The game a player plays — controls, feel, traffic, and what is on screen | game (glisteel) | 📋 | §H, §J |

---

### §A — The writer and the baker ✅

**Goal.** Turn an in-memory authored world — terrain mesh, splat control map, road and
water geometry, scattered vegetation, impostors — into a **baked, streamable 3D Tiles
octree** whose per-branch content is glTF the existing loader reads and the existing
runtime streams. This is the keystone: §B–§E all end by *baking through here*, and §H
*streams the result*.

**The forest demo is §A's first world and its acceptance test.** The demo already
assembles a known-good rendered world — a `SplatTerrain` over a DEM heightfield plus the
deterministic tree scatter and impostors — and `oglc-forest` renders it to a look we can
capture. So §A does not need a synthetic world to prove itself against: it bakes the
*forest demo's* world to octree-glTF and checks two things — that the writer reproduces
what the current terrain builder produces, and that the engine, streaming the baked file
through `oglc-view`, reproduces what `oglc-forest` renders live.

**The two owned writers.**

- **A glTF 2.0 writer** in [`OpenGLContext/loaders/gltf/`](../OpenGLContext/loaders/gltf/)
  (a `writer.py` beside the loader). Input is our own mesh data (positions, normals, UVs,
  tangents, per-vertex colour, indices) and PBR materials with texture references; output
  is `.glb`. It writes the subset our content needs — meshes, materials, textures,
  nodes, and the `KHR_materials_*` our PBR path already reads — and round-trips: a mesh
  written then loaded through [`OpenGLContext/loaders/gltf/`](../OpenGLContext/loaders/gltf/)
  is the mesh that went in. Owning this ends the `pygltflib` dependency the demo bakers
  lean on and gives every future "export a scene" task one path.
- **A 3D Tiles 1.1 writer** in the editor's baker: `tileset.json` with a bounding-volume
  hierarchy, geometric-error ladder, and refinement strategy per tile, referencing glTF
  (or b3dm-wrapped glTF) content. It writes what our runtime reads —
  [`tileset.py`](../OpenGLContext/loaders/tiles3d/tileset.py) is the contract — so the
  writer and reader are tested against each other.

**How LOD is encoded — and the dense grass is *not* in the tiles.** LOD travels in the
**OGC 3D Tiles refinement tree** the runtime already streams (geometric error + REPLACE/
ADD refinement + screen-space error), but the octree carries only what tolerates coarse
tiles: **terrain, roads, water, and sparse or far vegetation** (trees as instances, a
far-impostor grass backdrop). Its node count is therefore set by *terrain/road/water*
granularity, not by grass.

**Dense near-field grass is a runtime camera-following field, not baked geometry — this
is what keeps the octree from exploding.** Baking grass across a large map is a
non-starter arithmetically (§7 does the numbers), and tiling it finely enough for a smooth
near→far gradient would need a ruinous number of octree nodes. So grass follows the forest
demo's proven model: a **continuous, camera-bounded, per-instance, cross-faded field**
([`vegetation.py`](../OpenGLContext/loaders/tiles3d/vegetation.py) `build_vegetation_lod`,
[`grid.py`](../OpenGLContext/scenegraph/vegetation/grid.py),
[`billboards.py`](../OpenGLContext/scenegraph/vegetation/billboards.py)) populated only
within a radius of the camera and gated by **baked 2D masks** — a density/species control
map and a distance-to-road field, textures the writer emits map-wide cheaply. The field
reads the masks and scatters accordingly, so grass detail is **decoupled from tile size**:
its gradient is per-instance and smooth, and the map's extent costs a texture, not a
subtree. Trees can ride either path — baked as octree instances, or the same runtime
radius filter the demo already uses; §E decides per species.

Vegetation that *is* baked (trees, far backdrop) is written with the **standard
`EXT_mesh_gpu_instancing`** glTF extension the loader already reads
([`loaders/gltf/scene.py`](../OpenGLContext/loaders/gltf/scene.py)), so thousands of
instances ride in one tile. What is *ours* is the **policy** — the near-mesh→billboard-
impostor choice and the mask-driven density — with §E deciding which tier each tile and
each region gets. Octahedral view-atlas impostors (the modern billboard upgrade) are the
one custom asset still to build, per [TERRAIN-SYSTEM.md](TERRAIN-SYSTEM.md) M5 and §8.

**Two LOD axes, and why the plan does not reach for `MSFT_lod`.** Grass detail varies on
two axes, handled differently:

- **Distance from the *road* (§E) is view-independent** — a patch far from the road is
  low-detail wherever the camera is — so it is **baked into the 2D mask**, not selected at
  runtime: the distance-to-road field lowers the density and shifts the LOD tier away from
  the road, and the runtime grass field reads that when it scatters. No LOD extension
  touches this axis, and it needs no finer tiles.
- **Distance from the *camera* is view-dependent** and is served by two mechanisms that
  are finer and smoother than `MSFT_lod`: the near zone by the vegetation system's
  **continuous, per-instance, cross-faded field** (the demo's near-clump→billboard dither,
  granular per blade and *blended*, which is what stops grass popping), and the baked
  remainder by **tile-tree SSE refinement**.

`MSFT_lod` selects a discrete LOD **per node, by screen coverage**; a grass node
instancing a whole tile's blades has the *tile's* coverage, so node-level `MSFT_lod`
collapses to tile-level LOD, and an intra-tile gradient out of it means subdividing into
many nodes — finer tiling by another name, which refinement already does. It also
switches **without a blend**, reintroducing the pop the cross-fade removes, and it is a
runtime selector the loader does not implement. So on-tile grass gradient comes from the
continuous field and from tile granularity, not from `MSFT_lod`. **The one case that
would revive it:** grass baked *fully static* with no runtime field, wanting intra-tile
camera-distance LOD without finer tiles — a fallback, recorded in §8, not the current
design.

**The octree baker** (editor). Takes the authored world and produces the tree:

- Partition the world's content (terrain patches, road segments, water, vegetation
  instances) into an **octree** by spatial bounds — the general 3D partition roads,
  bridges and tunnels need, where the terrain system's quadtree assumes a height surface.
- Per node, generate the LOD appropriate to its geometric error: leaves carry full-detail
  meshes and dense vegetation; interior nodes carry down-sampled terrain, decimated road
  geometry, and impostor stand-ins for vegetation (§E decides the detail policy; §A
  provides the mechanism).
- Write each node's content as glTF, the tree as `tileset.json`, external sub-tilesets
  where a branch is large enough to bake independently.
- Emit an attribution/provenance manifest beside the tileset (data sources, licences),
  in the `cc0.py`/CREDITS pattern the engine already uses for asset credits.

**The bake driver — copy the demo's scene, do not convert the demo.** The forest bake is
a **new path that imports the demo's existing scene-assembly functions** (the terrain,
heightfield and scatter builders in
[`openglcontext_forest_demo/scene.py`](../../openglcontext-forest/src/openglcontext_forest_demo/scene.py))
and writes a file — a `oglc-forest-bake` entry point (or `--bake` mode) in the forest
demo package, calling the `OpenGLContext_editor` writer. `oglc-forest` itself is left
untouched, because it *is* the live baseline the bake is compared against: mutating the
demo to write files would destroy the reference the test depends on. The dependency
direction stays clean — the forest demo (an app) depends on the writer (an engine-adjacent
library), never the reverse.

**What bakes, and what does not.** Terrain mesh, the deterministic tree scatter (as glTF
instances) and the impostor stand-ins bake to static octree tiles directly. The
camera-following near-grass grid is *runtime-procedural* — an unbounded field regenerated
around the camera, not a static asset — so §A bakes a chosen extent of it at a fixed
density into the leaf tiles and leaves the infinite field to the runtime. The acceptance
bar is that the baked static world matches the live demo *at sampled viewpoints*, not that
an unbounded procedural field is frozen whole.

**Two equivalence checks, staged.** They gate §A before any of §B–§E leans on the writer:

1. **Writer-vs-builder equivalence, "or better" (no GL).** Point the new glTF/tileset
   writer at the same `height_fn` the current terrain builder bakes
   ([`build_terrain_tileset`](../OpenGLContext/loaders/tiles3d/procedural.py),
   [`build_dem_tileset`](../OpenGLContext/loaders/tiles3d/dem.py)) and assert the emitted
   world is **geometrically equivalent or better**, not array-identical. The existing
   baker is a *reference*, not an oracle to be reproduced byte-for-byte: the new writer is
   free to reorder vertices, add attributes the old one omits (tangents, a second UV),
   tighten bounding volumes, or refine the error ladder further. The test asserts the
   *surface and the tree*, at a tolerance: the baked height sampled at many XZ points
   matches the reference within epsilon; extent and coverage are equal; the tile tree
   refines to at least as fine a geometric error with monotone bounds; and there are no
   holes or seams the reference lacked. "Better" passes; only a *worse* surface —
   coarser, gapped, misplaced — fails. This proves the writer faithful in isolation, on
   terrain the demo already ships, before it grows vegetation and octree partitioning.
2. **Round-trip render fidelity (GL smoke test).** Bake the forest world, stream it back
   through `oglc-view`'s tiles adapter
   ([`viewer/adapters/tiles.py`](../OpenGLContext/viewer/adapters/tiles.py)), and compare
   the captured frames to `oglc-forest`'s at the same viewpoints, through the existing
   subprocess-and-capture visual-regression harness. The demo's own captures are the
   baseline; a match means the writer + runtime reproduce the authored look.

**Testable without GL.** All of it. A written `.glb` is bytes to parse and assert on; a
round-trip (write mesh → load mesh → compare arrays) needs no window; a tileset is JSON
with a bounding-volume tree to validate; the octree partition is a tree over points with
assertable invariants (every instance in exactly one leaf, child bounds inside parent,
geometric error monotone up the tree). Streaming the baked output *back* through the
runtime is the one GL smoke test, and the harness already does exactly that for the demo
bakers.

**Docs.** [`../docs/`](../docs/) gains a "baking a world" page (the writer API, the
tileset the runtime expects, the octree policy); [PROJECT-PLAN.md](PROJECT-PLAN.md) gains
the writer row; `OpenGLContext_editor` README documents the baker CLI.

---

### §B — Terrain authoring pipeline 📋

**Goal.** Turn "here is an area" into a terrain the rest of the world is built on: a
georeferenced heightfield, its splat control map generated from the land itself, baked
through §A.

**Build.**

- **Georeferenced DEM ingest** (engine, extends [`dem.py`](../OpenGLContext/loaders/tiles3d/dem.py)).
  Today's ingest is a single grayscale image with an assumed extent. Add coordinate
  awareness: read a GeoTIFF's bounds and CRS so an area is placed and scaled from its real
  metres, and map lat/lon to world XZ. `rasterio`/GDAL is the tool, kept an **optional
  dependency** (a plain PNG heightmap still works without it), because a GIS stack is a
  heavy thing to force on a game that only wants to *stream* the result.
- **Multi-block DEM** (editor). A real area is many source tiles. Stitch a grid of blocks
  with seam blending at the edges, cache blocks under the user cache, and bake the region
  as one world. The forest demo's heightmap recipe (4×4 slippy tiles stitched to one
  raster, [TERRAIN-ASSET-FORMATS.md](TERRAIN-ASSET-FORMATS.md)) is the manual version of
  this; §B automates it.
- **Procedural control-map generation** (editor). Derive the RGBA splat weights from the
  terrain — rock on steep slopes, grass on gentle ones, wet/silt low and flat, forest
  floor in the remainder — the slope/elevation rules [TERRAIN-ASSET-FORMATS.md](TERRAIN-ASSET-FORMATS.md)
  already describes for the forest control map, parameterised and run over any DEM.
  Optional land-cover input (if a source provides it) refines the guess.
- Bake terrain mesh + control map through §A; the runtime renders it with the existing
  [`SplatTerrain`](../OpenGLContext/scenegraph/terrain/splat.py) material.

**Testable without GL.** DEM stitch and seam blend (arrays in, array out); CRS/extent math
(known lat/lon → known world XZ); control-map generation (a synthetic slope → known
channel weights). Baking is §A's test surface.

**Docs.** [`../docs/`](../docs/) terrain page gains georeferenced ingest and control-map
generation; the DEM/data provenance and licences are recorded where the fetch lives.

---

### §C — Roads 🟡

**Goal.** A designer's 3D polyline becomes a road that sits on the land — with shoulders,
grassy embankments and the structures a route needs to cross real terrain — and the
world around it knows the road is there.

**The road spec** (`OpenGLContext_editor/specs/`, from published sources and our own
choices). A road is a **3D polyline** (control points with height) plus a **cross-section
profile** (carriageway width, lane count, shoulder, verge, camber) and a **generation
mode** per segment. Road-network conventions come from published references, not any
engine's source.

**The four generation operations**, chosen by the height difference between the polyline
and the terrain under it:

- **Highway on dirt** — the road follows the ground; the profile is extruded along the
  polyline, the terrain is conformed to meet the shoulder, and embankments fill the
  cut/fill to either side.
- **Causeway across a large valley** — a raised embankment carries the road over a broad
  low area; fill geometry drops from the shoulders to the valley floor.
- **Bridge over a small valley** — a deck on piers spans a narrow gap the terrain is left
  under.
- **Tunnel through a mountain** — the road enters and exits a portal; the span between is
  not rendered as surface road, and the terrain above is left intact.

The generator picks per segment (small drop → nothing; medium → bridge; large/broad →
causeway; polyline below terrain → tunnel), and the designer overrides.

**Build.**

- **Road-mesh render node** (engine, `OpenGLContext/scenegraph/road.py`). Renders an
  extruded-profile mesh with the road material — a PBR surface with the reflective wet/
  tarmac look a racing game wants. This is runtime: `glisteel` renders roads without any
  editor code.
- **Road generation** (editor). Polyline + profile + mode → mesh, plus the terrain
  conforming (raise/lower the heightfield to meet the shoulder) and the embankment fill.
- **Reflection bake** (editor + engine environment path). Bake the background — sky,
  distant terrain — into the road's environment so a car sees the world reflected in wet
  tarmac, leaning on the existing IBL/environment path rather than a per-frame planar
  reflection.
- **Road physics collider** (engine + omi_physics). A trimesh (or convex decomposition)
  per segment, streamed with the tile, so the car drives on the road surface.
- **Road-aware terrain material.** The road, shoulder and embankment paint into the §B
  control map so the splat material transitions tarmac → gravel → grass without a seam.

**Testable without GL.** Cross-section extrusion (polyline + profile → known vertex ring
positions); mode selection (a height profile → the expected sequence of ops); terrain
conforming (a heightfield and a road → the conformed heightfield); the collider mesh. The
render node and the reflection bake are the GL smoke tests.

**Docs.** `OpenGLContext_editor` docs gain the road spec and the four ops; OpenGLContext
docs gain the road render node and material; the spec is cited from the code.

**What landed (2026-08-17).** All four operations, and the two things that turned out to
matter more than any of them.

- **The four ops.** `OpenGLContext_editor.world.structures.choose_structures` partitions a
  settled alignment into `DIRT`, `CAUSEWAY`, `BRIDGE` and `TUNNEL` by reading the finished
  line against the undisturbed ground, with minimum lengths, approach reach-out, and a
  merge that gives a short stretch between two structures to the first of them (a deck
  lands on the portal it runs into rather than leaving ten metres of embankment inside a
  hillside). `OpenGLContext.scenegraph.roadworks` builds the geometry: a deck with
  parapets on blade piers dropped to the ground, and a bore — a closed tube with a floor,
  its own shade carried on its vertices, and a portal at each end.
- **The road narrows onto a structure.** `RoadProfile.on_structure()` turns the verge into
  an edge beam, and `road_surface(sections=…)` sweeps a section per point so the change is
  a taper rather than a step. The same mechanism would widen a road for a lay-by.
- **`conform_terrain` leaves the ground alone under a structure**, and reshapes a segment
  with *either* end on the land — stopping one segment short leaves a lip of hillside
  across the road at the place a car arrives at speed.
- **The route is slid onto ground a road can follow** (`world.route.ease_route`). This was
  the surprise: an ellipse drawn across five hundred metres of relief is viaduct and bore
  for **72%** of its length whatever the grade limit says, because no drivable grade
  follows that landscape. Sliding each point along its own contour, and holding the
  corners to the radius the design speed allows (`hold_radius`, `cornering_radius`),
  brings the shipped circuit to **75% laid on the ground** — which is what makes it a road
  through a landscape rather than a road over one.
- **The landscape's relief is a world knob.** `ProceduralWorld.relief` scales the shipped
  terrain; at 1 no road can follow it, at 0.5 the same shapes are hill country a road can
  be built through with a handful of crossings where it still cannot.

**Still open.** The reflection bake (wet tarmac reflecting the baked environment);
junctions (§J); a bridge is one structural form and a tunnel one bore.

---

### §D — Water 📋

**Goal.** Rivers and lakes a car races past and sees *into* — flowing water with rocks
and whitewater, lakes with shaped shorelines and beaches, both dropped on the map by the
designer and filled in with enough detail to read at speed.

**Build.**

- **River generation** (editor). From a source point (or a drawn path), route flow
  downhill over the §B heightfield with a simple flow simulation, carve the channel,
  and generate three geometries: **channel bed**, **water surface** (with a flow
  direction along the course), and **bank/edge** geometry where water meets land. Place
  **rocks** and mark **whitewater** where the gradient steepens.
- **Lake generation** (editor). Fill a basin to a level; generate the water surface, a
  shaped **shoreline**, and **beaches** where the bank is shallow. Place LOD'd **boats**
  on the surface.
- **Water-surface render node** (engine, `OpenGLContext/scenegraph/water.py`). Runtime:
  animated surface with a flow field (scrolling normal/flow for rivers, gentle waves for
  lakes), depth-based colour and transparency, **reflection and refraction** (leaning on
  the environment path and a depth read, single-layer blend — order-independent
  transparency is not required, per [TERRAIN-SYSTEM.md](TERRAIN-SYSTEM.md) §10),
  **shoreline foam** where the surface meets terrain, and **whitewater** where the river
  marks it. `glisteel` renders water without editor code.
- **Buoyancy** (engine + omi_physics), for boats and anything that floats — a water plane
  the physics world queries.
- **Road/water interaction.** A road crossing water is a §C bridge or causeway; the
  generators cooperate at the crossing.
- **Vegetation fill along water** (composes with §E). Trees and brush thicken along a
  river bank and a lakeshore so a car sees down the river in detail, thinning away from
  it — the same distance-driven density §E applies to roads, keyed to the water edge.

**Testable without GL.** Flow routing (a heightfield → a downhill path); channel carve
(heightfield in, carved heightfield out); basin fill (a basin + a level → the shoreline
polygon); foam/whitewater marking (a gradient → the marked segments); buoyancy (a body at
a depth → the force). The render node is the GL smoke test.

**Docs.** `OpenGLContext_editor` docs gain river/lake generation; OpenGLContext docs gain
the water render node and buoyancy; both cited.

---

### §E — Road-aware refinement and octree LOD 📋

**Goal.** The distribution the forest demo scatters — but **held to far LODs except near
the road and water**, where the road, shoulder, embankments and the first rows of bushes
and trees carry full detail so a car sees everything at speed, dropping to stand-ins or
down-sampled geometry as the LOD falls.

**Two outputs, matching §A's two homes for detail.** §E writes the road-relative detail
into a **baked mask** (for the runtime vegetation field) *and* into the **octree
refinement** (for baked content). It does not bake dense grass into tiles.

**Build.**

- **Distance-to-feature field** (editor). Compute, per point in the world, the distance to
  the nearest road or water edge. This is baked as a **2D raster mask** beside the §B
  control map — the view-independent input both outputs read.
- **Mask-driven vegetation density and tier** (drives the runtime field, §A). The mask
  raises the target density and shifts the LOD tier *toward full detail* within a band of
  the road/water, and thins toward far-billboard-only coverage beyond it. The runtime
  grass/tree field reads the mask when it scatters, so the near-road strip is lush and the
  far field is sparse — per-instance, smooth, and **decoupled from tile size** (the point
  of §A). The forest demo's species distribution is the *target* density inside the band.
- **Octree refinement near the route** (drives §A's per-node baked detail). Refine the
  octree deeper along the road/water so the **baked** content there — road, shoulder,
  embankment terrain, conformed heightfield, and any baked trees — carries the finest
  tiles; deeper from the route, tiles carry decimated terrain and far-impostor vegetation.
  The geometric-error ladder the runtime already refines on
  ([`traversal.py`](../OpenGLContext/loaders/tiles3d/traversal.py)) expresses this, and
  the refinement is bounded to the band so the tree stays small (§7's node-count point).
- **The two agree at the band edge.** Mask density and octree tier are driven by the same
  distance field, so the runtime field thins out just as the baked tiles coarsen — no seam
  where one detail source hands off to the other.

**Testable without GL.** The distance field (geometry in, distances out); mask density
(a distance → the expected density/tier, and the runtime field's instance count when it
samples the mask); the octree refinement bound (a distance → which tiles refine, and that
the tree stays within a node budget); partition invariants (§A). Streaming the result and
seeing the band carry detail is the GL smoke test.

**Docs.** `OpenGLContext_editor` docs gain the refinement policy and its knobs (band
width, target density, LOD tiers).

---

### §F — Editor toolkit 🟡

**Goal.** The interactive machinery a *second* editor would want identically: a tool-mode
framework, real menus, picking a point on the terrain and dragging it, gizmos, and a
top-down map view. Built on the existing overlay UI ([`OpenGLContext/ui/`](../OpenGLContext/ui/))
and MRT picking, which carry most of the weight.

**§F.0 — Ortho map view and tool-mode skeleton** (can be pulled forward). An orthographic
top-down pass over the world, and a `ToolMode` framework — the current tool holds the
mouse/keyboard, falls back to the camera when it does not consume an event, and switches
through UI. Modelled on the navigation-mode pattern
([`OpenGLContext/move/navigation.py`](../OpenGLContext/move/navigation.py)).

**Build.**

- **Tool-mode framework** (engine or editor — engine, since a second editor wants it). A
  tool base with `on_mousebutton`/`on_mousemove`/`on_key` hooks, event routing that
  checks the active tool before the camera, and a tool registry the UI drives.
- **Menus** (engine UI). A menu bar with dropdowns and a right-click context menu — the
  one interactive-UI primitive [OVERLAY-UI.md](OVERLAY-UI.md) does not yet have (it has
  modal panels, dialogs and settings pages). Built on the same batched renderer and
  layout the widgets use.
- **3D point placement and dragging** (engine, small). Place a point where the user
  clicks on the terrain, and drag it. This is **already almost entirely built**: the
  pick path reads object-id *and depth* per sample
  ([`asyncpick.py`](../OpenGLContext/passes/asyncpick.py) sets
  `event.viewCoordinate = (x, y, depth)`), and
  [`MouseEvent.unproject()`](../OpenGLContext/events/mouseevents.py) runs `gluUnProject`
  to return the world-space surface point under the cursor — O(1), async, and correct for
  terrain because terrain writes depth like any geometry. The work is wiring, not a
  pipeline: ensure the streamed terrain participates in the pick pass, enable pick
  handlers, and add the drag mechanics — re-unproject the depth under the cursor each
  mousemove to drag along the surface, or a closed-form ray/plane intersect to drag at a
  fixed height. The surface **normal** comes analytically from the
  [`HeightField`](../OpenGLContext/scenegraph/terrain/heightfield.py) gradient, not from
  picking. The CPU ray/BVH pipeline ([RAYCAST-PICKING.md](RAYCAST-PICKING.md)) stays
  **shelved**; it is wanted only for picking an *occluded or off-screen* point (a road
  point on terrain behind a hill, without moving the camera), which is an edge case a
  track editor can defer.
- **Gizmos** (engine). ✅ **Landed 2026-08-30** as `edit/gizmo.py`:
  `TranslationGizmo` is three arms of ordinary scenegraph geometry, so the existing
  MRT buffer hit-tests them like any other pick, and the grabbed arm drives a
  closed-form axis-constrained drag (`axis_parameter`, the closest approach of the
  eye ray to the arm's line). It works in the coordinates of whatever group it is
  put in, taking that transform from the node path the pick resolved, so a road
  control point or a water source is dragged in the units it is stored in.
  `edit/controlnet.py` is the companion for geometry a pick cannot name a point
  within: `ControlNet` puts a pickable marker on every control point of a NURBS
  node and an unpickable cage line along every row and column, so a designer can
  see what a pull is about to do before making it. `tests/molehill_edit.py` is
  the demo. Rotate and scale handles are the same shape of problem and are not
  built.
- **Editor panels** (editor). Tool options, a layer/inspector panel, the project browser —
  `Panel`s and `HUDLayer`s from the existing toolkit.

**Testable without GL.** Tool event routing (a synthetic event stream → which handler
saw it); menu layout (items → laid-out rectangles, the metrics are already pure); the
drag math — closed-form ray/plane intersect (a ray + a plane → the hit point) and the
terrain normal from a heightfield gradient; gizmo constraint (a drag delta → the
constrained motion). Unprojection and MRT picking are exercised by the existing pick
tests; rendering is the GL smoke test.

**Docs.** OpenGLContext docs gain menus, tool-modes, the ortho pass and the picking slice;
[RAYCAST-PICKING.md](RAYCAST-PICKING.md) is updated with what §F lands of it.

---

### §G — `glisteel-editor`, the race-track editor 🟡

**Goal.** The application that drives §B–§F: load an area, draw a track, drop water, bake
a world.

**Build** (all in the new repo; the reusable half is already in §B–§F):

- **Load an area** — a dialog to choose a region (a named place or a lat/lon box); §B
  fetches, stitches and bakes the terrain; the ortho map (§F) shows it top-down.
- **`menu → add roadway`** — click to place control points on the terrain (§F picking),
  the height read from the land; drag to adjust (§F gizmos); the road generates live
  (§C), choosing bridge/causeway/tunnel per segment with a manual override.
- **`menu → add water`** — drop a river source or a lake, simulate and generate (§D);
  vegetation fills in along the water (§E).
- **The track model** — checkpoints, start/finish, the racing line — this editor's own
  data, not the engine's.
- **Bake** — write the world through §A/§E to a tileset the game streams; save the editor
  project (the annotations) separately so a track is re-editable.

**Testable without GL.** The track/project model (serialise → deserialise → equal); the
menu-to-generation wiring (a scripted "add road here" → the expected road in the world).
The editor session is the GL smoke test.

**Docs.** `glisteel-editor` README and a getting-started doc: load an area, draw a track,
bake.

---

### §H — `glisteel`, the car game demo ✅

**Goal.** Prove the runtime: stream a baked world at speed and drive it.

**Build** (new repo, runtime only — no editor or generation dependency):

- **Stream the baked world** through the existing [`TilesTerrain`](../OpenGLContext/scenegraph/tilesterrain.py)
  runtime; the world §G baked is the world §H loads.
- **Vehicle** — a car with handling built on [omi_physics](../../omi_physics/): a
  chassis, wheels on the road collider (§C), the racing feel this game owns.
- **Race** — checkpoints, lap timing, the camera that chases the car, the HUD (speed,
  lap, position) on the existing HUD layer.
- **The world it ships** — one baked track, fetched or bundled, with its attribution.

**Testable without GL.** Vehicle dynamics (inputs → motion over a known surface); lap/
checkpoint logic; streaming a baked world headlessly (the tiles load and the colliders
page). Driving it is the GL smoke test.

**Docs.** `glisteel` README: run the demo, the controls, where the world comes from.

---

### §J — Furniture: signs, obstacles and junctions 📋

**Goal.** A road with things on it and beside it, and roads that meet.

- **Signs — landed.** Warning of what the alignment already knows about itself: a dip, a
  crest, a bend tighter than the ones before it, a tunnel ahead. The alignment carries the
  curvature and the grade, so the *placement* is derivable rather than authored — which is
  the point of generating a road rather than drawing one. A sign is a post and the plates
  on it, placed at a stopping distance before what it warns of.
  **The pattern is Ontario's**: a black symbol on a yellow diamond, an advisory speed on a
  tab below it, and the posted limit as a white MAXIMUM plate repeated along the road. How
  fast a bend is worth is derivable too — `road.corner_speed` is what its radius and its
  lean will hold and `road.advisory_speed` is 60% of that, rounded down to 10 km/h, which
  is the number on the tab. The posted limit is a decision rather than a measurement, so it is told to the
  world (`ProceduralWorld.posted`). See [../docs/roads.html](../docs/roads.html).
- **Obstacles.** Parked and moving cars, rocks, deer, foxes. Two different problems: a
  *placed* obstacle is a `MeshLayer` entry with a collider, and a *moving* one is an actor
  the game steps. Both want a shared notion of "a thing in the world with a body", which
  the baker has no concept of yet.
- **Junctions.** Two roads that cross currently produce two surfaces at the crossing
  point. A junction is its own generation operation: the two cross-sections are merged
  over the intersection, the markings change, and the terrain is conformed to the union.
  It is the largest single piece of road work left and it changes `RoadPath` from a line
  into a graph.

**Testable without GL.** Where a sign is placed for a given alignment; what a junction's
surface is for two known centrelines; that an obstacle's collider is where its mesh is.

---

### §K — The game a player plays 📋

**Goal.** Everything between "the world is right" and "this is a game somebody
would play". Signs, obstacles and traffic (§J) made the road *inhabited*; this
is the driving and the reading of it.

**Controls.**

- **A game controller,** for steering above all: the current input is three
  states — full left, straight, full right — and no amount of tuning makes that
  feel like a car. Analogue steering, throttle and brake axes, with a dead zone
  and a shaping curve. `driver_input()` returns three floats and `Car.control`
  passes them through, so there is one clean insertion point.
- **Mouse drive,** before that and for anyone without a pad: the pointer's
  sideways movement steers proportionally, the way mouse-look turns a head.
  Wants the same pointer capture a look-around mode uses, and a sensitivity.

**Feel.**

- **An EV power curve.** The car applies a constant `engine_force` at every
  speed, so it pulls as hard at 160 km/h as at 30 and its top speed is set by
  rolling resistance because there is no aerodynamic drag at all. What a motor
  actually gives is constant torque to a base speed and constant *power* above
  it. Regenerative braking is deliberately out of scope for now.

**Traffic that reacts to the player** (§J gave it traffic that reacts to
*itself*: it follows the car in front and will not drive through it).

- **A player stopped in the road** is something to get round or to queue behind
  and lean on the horn about, decided per driver.
- **A player on the wrong side of the road** is a decision for the oncoming
  driver: swerve if there is room and time, and if there is not, hit them --
  and sound the horn either way. The severity rule already exists
  (`race.Collisions`); what is missing is the other driver's judgement.

**What is on screen.**

- **The lap timer** is already there (current, last and best). What it wants is
  to be legible at speed and to say where the time went.
- **A visible start/finish** ✅ — a chequered banner on a beam over the
  carriageway with a chequered line painted under it, so the lap turning over
  has something a driver saw coming. `OpenGLContext.scenegraph.gantry` is the
  object, `world.gantry.start_finish` decides where it goes from the road's own
  alignment, and `bake.gantry.GantryLayer` writes it. The frame and the line are
  one mesh reading one picture, so the marker costs a world one draw; the two
  legs go into the world's props, so a car that hits one hits it whatever the
  streamer is doing. The line's chequer is *geometry*: seen from a driving seat
  the paint is nearly edge-on, and a texture nine times wider than it is deep
  loses its pattern to the mip level that grazing angle asks for, so it read as
  a plain white bar from the one place anybody looks at it.
- **A map** of the whole circuit with the car on it, so a driver knows what is
  round the next bend and how much of the lap is left.

**Testable without GL.** Where the mouse's movement puts the steering; what the
power curve gives at each speed; what an oncoming driver decides for a given
closing speed and gap; where a car is on the map for a given position.

---

### §I — Performance to 60 fps ✅

**Goal.** 60 fps at 1080p on the discrete-GPU target, streaming a world heavier than the
forest demo, with a racing camera.

**Where it stands.** Measured 2026-08-17 in this container, driving `glisteel` on the
autopilot at 1000×560 over a 2048 m world, twenty seconds each:

| Tree instances per tile | Depth | Before | After |
|---|---|---|---|
| 0 | 3 | 125.6 fps | 147.3 fps |
| 40 | 3 | 25.8 fps | 110.8 fps |
| 24 | 4 | 16.5 fps | 73.9 fps |
| 240 | 4 | 5.3 fps | 61.4 fps |

At **1920×1080**, the target resolution, the 24-instance world went from 37.2 fps to
**57.5 fps**. A frame there is about 10 ms of drawing, 5 ms of physics and 3 ms of
everything else.

The frame rate tracked the baked instance count and nothing else: with the trees out it
was four times the target, and each instance cost 0.06–0.2 ms of CPU. The draw was always
one call; the work before it was not. The loader expanded an `EXT_mesh_gpu_instancing`
node into one `Transform` per instance, and the pass then built a record — matrix
concatenation, bounding volume, frustum test, batch key, shadow-caster record — for every
one of them, to reach a draw the file had already declared.

**What landed.** `OpenGLContext.scenegraph.instancedshape.InstancedShape` is a `Shape`
plus an `(N,4,4)` array of placements; the pass does its per-object work once for the set
and expands the placements at the draw, and sets of the same geometry still batch
together, so a hundred tiles of one forest remain one call. A glTF instancing node loads
as one of these. Anything that reads the scenegraph for geometry has to expand the
placements to see what is really there — the collision extraction in
`physics/gltf_world.py` does, so a car cannot drive through a tree it can see. What being
one object costs is in [docs/instancing.html](../docs/instancing.html): one bounding box,
one pick id, one sort key for the set.

Two things beside it were re-deriving a scene's worth of work because one thing moved.
The shadow pass kept its casters' world geometry per caster *set*, so the car moving
invalidated the trees; it is now kept per caster. The batcher asked its key and its
instanceable test of every record, where both read nothing but the shape.

**Three more things, each a defect rather than a tuning.**

- **The same image, loaded by every tile, was a texture each.** A streamed world is
  hundreds of files and the tree in one tile is the same tree as in the next — the same
  bark, byte for byte, embedded in every tile that has a tree in it. That was a hundred
  copies of one image in video memory and, worse, a hundred *different* textures, so
  every tile's trees were their own instanced draw. The loader keys textures on what is
  in them now, held weakly.
- **A car's four wheels were cast into the world one at a time.** They look at very
  nearly the same piece of it, so `omi_physics.raycast_many` decides which bodies matter
  once and asks a landscape's mesh once for the triangles near all four. 1.05 ms → 0.02 ms
  per step.
- **Every body was asked each step whether it had moved.** A streamed landscape is dozens
  that never do, and once the answer is always no, the asking is the cost. 0.5 ms → 0.11 ms
  per step.

**Reached, and then passed, by changing what a world is made of** (2026-08-17). The
shipped world now runs at **106 fps at 1080p** driving on the autopilot — a frame of
4.7 ms drawing, 2.2 ms physics and 2.5 ms of everything else — against 57.5 before. None
of it came from making the old frame faster:

| | before | after |
|---|---|---|
| frame, 1080p | 57.5 fps | 106 fps |
| draw | 10.9 ms | 4.7 ms |
| of which shadows | 5.5 ms | 1.9 ms |
| shapes the pass gathered | 148 | 29 |
| trees in the world | 45k, in tiles | 379k, in a field |

The three changes, all of them "put this somewhere else":

- **The ground stopped being tiles.** One
  [splat terrain](../docs/terrain.html#heightfield) over a 1025² height field is one draw
  and casts no shadow, where a tree of vertex-coloured patches was a hundred shapes that
  did. It also looks incomparably better, which was the reason for doing it.
- **The forest stopped being tile content.** 379k trees in a
  [`VegetationField`](../docs/vegetation.html#vegetationfield) are two instanced draws per
  species over a table, re-chosen when the camera moves eight metres, against 45k trees
  that were per-tile geometry rasterised into three shadow cascades as well as the frame.
- **Physics stopped reading the drawn geometry.** The ground is
  [chunks of the height field](../docs/terrain.html#fieldphysics) and the carriageway is
  [swept from the course](../docs/physics.html#roadcolliders), so nothing streams under
  the car.

Dynamic resolution, the lever this plan named first, is still **not** the one: at 1280×720
the same world runs at the same rate as at 1080p, so the frame is CPU-bound and fewer
pixels buy nothing.

**The other levers, and why a racing game has ones the forest demo lacked.**

- **Racing favours far LODs.** The forest demo walks through dense near-field grass at eye
  level; a car sees mostly the road and the middle distance, and §E already holds
  everything off the road to far LODs. The near-field fill that floors the walking demo is
  concentrated in the road band, which is a fraction of the frame.
- **Dynamic resolution** (engine). Scale the internal render resolution to hold 16.6 ms,
  presenting upscaled — the real native-1080p lever the forest work identified, and the
  one that lets the reduced iGPU tier reach 60 at a lower internal resolution. The forest
  demo's resolution-aware quality ladder ([`quality.py`](../../openglcontext-forest/src/openglcontext_forest_demo/quality.py))
  is the starting point; dynamic resolution generalises it.
- **The scalable quality ladder** carries over directly: grass-clump density/radius, LOD
  fade distances, shadow settings, all driven to a frame-time target.
- **Measure against the real world, not the demo.** Profile `glisteel` streaming a baked
  track — the heavier scene the perf bar is actually set against — with the forest demo's
  subsystem breakdown harness ([`tools/profile_breakdown.py`](../../openglcontext-forest/tools/profile_breakdown.py))
  generalised.

**Engine defects to fix belong upstream**, per the engine-first rule: any glGet stall,
redundant state change or sub-optimal hot path §I finds in OpenGLContext is fixed in
OpenGLContext (it helps twig-bb and the forest demo too), not worked around in the game.

**Testable without GL.** The dynamic-resolution controller (a frame-time series → the
resolution decisions); the quality picker. Frame rate is the GL measurement, on the real
GPU this container has.

**Docs.** OpenGLContext docs gain dynamic resolution; `glisteel` README documents the
quality options.

---

## 6. Cross-cutting concerns

**Licensing.** Three distinct licences travel with this work and none becomes a repo
dependency or a vendored byte:

- **Elevation data** — SRTM/USGS public domain, AWS Terrain Tiles aggregate; fetched to
  the user cache, attributed in the baked world's manifest.
- **OpenStreetMap** (if road/vector import is added) — **ODbL**, share-alike on the
  *data*. This governs a baked world that *includes* OSM-derived geometry, so the manifest
  records it and the fetch is consented. It is a data-licence obligation, not code
  copyleft, and does not touch the BSD code.
- **CC0/CC-BY assets** (trees, rocks, boats, road textures) — the forest demo and twig-bb
  patterns: CC0 may be committed with credit, CC-BY fetched or committed with attribution,
  nothing share-alike vendored.

**Clean-room exposure.** GIS tooling and open game engines carry copyleft. The writer
(§A), road network (§C) and tile formats come from **published specs** (glTF 2.0, OGC 3D
Tiles 1.1, `KHR_*`) — permitted sources, cited by number. Reading any GPL/AGPL
implementation to learn a fact triggers [../../CLEAN-ROOM.md](../../CLEAN-ROOM.md): a
Reader produces a spec under `OpenGLContext_editor/specs/`, the Implementer works from the
spec.

**Testing strategy.** The initiative is unusually testable because it is mostly data
transformation: writers round-trip, generators are arrays in and geometry out, the octree
has invariants, simulations run on arrays. Each phase's "testable without GL" section
names the larger, window-free half. The GL half rides the existing subprocess-and-capture
harness with the `gl` marker, on the container's real GPU.

**Dynamic-resolution and dependency budget.** `rasterio`/GDAL (§B) and any river-sim or
mesh-decimation helper are **optional** dependencies: the runtime game (`glisteel`) links
none of them, and the editor degrades gracefully when a heavy optional is absent (a PNG
heightmap works without GDAL).

---

## 7. Sequencing and dependencies

The critical path is **§A → §B → {§C, §D} → §E → §G**, with §F feeding §G and running
partly in parallel (§F.0 anytime), and §H/§I closing it out on the runtime side.

- **§A first, always.** It is the keystone; §B–§E all end by baking through it, and
  nothing downstream is *seen* until a world can be written and streamed back. Build it
  against the **forest demo** — bake the demo's world, prove writer-vs-builder equivalence
  ("or better") and round-trip render fidelity against `oglc-forest`'s own captures —
  before any new generation leans on it.
- **§B before §C/§D.** Roads and water are built *on* the terrain and its control map.
- **§C and §D in parallel** once §B lands — they share §A and the environment path but
  are otherwise independent, and each is a self-contained "seen" milestone.
- **§E after §C** (it needs the distance-to-road field) and composes with §D's water
  edges.
- **§F alongside** — §F.0 (ortho map, tool skeleton) can precede everything as a
  UI-shaped warm-up; the picking/gizmo slice is wanted by §G's road drawing, so land it
  before §G's interactive road tool.
- **§G** assembles §B–§F into the editor; **§H** streams §E's output; **§I** measures §H
  and drives the engine fixes.

A pragmatic first vertical slice, to get *something baked and driven* early, and it
starts from the forest demo rather than a fresh scene:

1. **Bake the forest world** — the writer emits the demo's terrain + tree scatter +
   impostors as octree-glTF via `oglc-forest-bake`, proven by §A's two equivalence checks
   (writer-vs-builder equivalence "or better", then round-trip render fidelity in `oglc-view` against
   `oglc-forest`'s captures). This is the whole writer/baker/runtime spine, validated
   against a world we already trust, before any new content type exists.
2. **Add one road** — a minimal §C (highway-on-dirt only) drawn over the same terrain,
   baked into the same octree.
3. **Drive it** — a minimal §H streams the baked world and drives a car on the road
   collider.

That slice touches the whole spine — write, bake, octree, stream, collide — without the
other three road ops, water, refinement or the editor, and it earns its confidence from
the forest demo's existing baseline rather than from a scene built to pass its own test.
Everything after is depth on a proven path.

### Why grass is a runtime field, not tiles — the arithmetic

The reason §A keeps dense grass out of the octree is a size argument, not a preference.
A 4 km × 4 km map is 16 million m². The forest demo's near-clump density is ~9 blades/m²;
baking grass at that density map-wide is ~1.4 × 10⁸ clumps of ~520 triangles — order 10¹¹
triangles of static content, before any LOD. It cannot be stored, and tiling it finely
enough for a smooth near→far gradient would need an octree with a ruinous number of leaves.
So grass is **only ever present within a radius of the camera** — the demo populates a disc
of a few hundred metres, full density only within ~30 m, which is order 10⁵–10⁶ instances
live at once regardless of map size — and that field is regenerated as the camera moves,
off-thread. What the writer bakes map-wide for grass is the **2D masks** (density, species,
distance-to-road): a handful of textures, a few MB, not a subtree. This is why the octree's
node count is set by terrain, roads and water — which are sparse and tolerate coarse
tiles — and never by grass. Trees (~0.09/m² → ~1.4 M over the map) are borderline: bakeable
as octree instances, or the same camera-radius runtime filter the demo already uses for
them; §E decides per species.

---

## 8. Open questions

- **Vehicle physics depth.** omi_physics has rigid bodies and raycast; a satisfying car
  needs a wheel/suspension model. Is that omi_physics machinery (a second game would want
  it) or `glisteel`'s? Leaning omi_physics for the vehicle *primitives*, `glisteel` for
  the handling feel — to be decided when §H starts.
- **Impostor generation for baked vegetation.** The forest demo ships pre-baked impostor
  atlases; a baked *arbitrary* world needs impostors generated for whatever species it
  scatters. The terrain plan names octahedral view-atlas impostors rendered offline with
  our own render-to-texture ([TERRAIN-SYSTEM.md](TERRAIN-SYSTEM.md) M5) — §E depends on
  that existing or building it. Confirm scope when §E starts.
- **OSM road import.** The plan assumes the designer *draws* roads. Importing an existing
  road network from OSM is a natural extension (and an ODbL obligation to plan for) but is
  not in the phases above — a later addition if wanted.
- **Trees: baked into tiles, or runtime field?** Grass is settled (runtime field over
  masks); trees sit on the fence at ~1.4 M over a 4 km map. Baking them as octree instances
  streams like standard content but grows the tree; the demo's camera-radius filter keeps
  the octree small but regenerates per move. Decide per species in §E — likely far/mid
  trees baked as impostor backdrop, near trees a runtime field.
- **`MSFT_lod` revisit condition.** The plan gets on-tile detail from the runtime field and
  from tile granularity, not `MSFT_lod` (§A). The one design that would revive it: grass
  baked *fully static* per tile with no runtime field, wanting intra-tile camera-distance
  LOD without finer tiles. That trades the smooth per-instance field for static content and
  a discrete per-node selector we would then have to implement — a fallback if the runtime
  field ever proves too costly to regenerate at map scale, not the current design.
- **World size ceiling.** The octree and streaming scale to large worlds; virtual
  texturing (deferred in the terrain plan) is the lever for *very* large ones. What area
  size a first `glisteel` track targets sets whether that is needed.

---

## 9. Status log

- **2026-08-16** — Plan written. Decisions taken (§0): authoring core in a new
  `OpenGLContext_editor` sibling; own glTF + 3D Tiles writer; 60 fps bar is the discrete
  GPU. Grounded in an audit of the existing tiles3d/terrain/vegetation/UI/picking
  subsystems (§3) and the forest-demo performance findings. No code started.
- **2026-08-17** — **§A landed.** `OpenGLContext.loaders.gltf.writer` writes meshes,
  materials, textures, node hierarchies and `EXT_mesh_gpu_instancing`, round-tripped
  through the loader and cross-read by pygltflib; the engine's procedural tileset baker
  now writes through it, so the bake path owns its glTF. The baker
  (`OpenGLContext_editor.bake`) partitions a world, asks each layer for content at the
  node's error, and emits a 1.1 tileset with the traversal's invariants checked as it is
  built. `oglc-bake` bakes the shipped procedural world and `oglc-view` streams it.
  Equivalence check 1 passes — measured against the height function itself, the new
  surface is no worse than `build_terrain_tileset`'s at 400 off-grid sample points, with
  equal footprint and at least as fine a leaf level. Check 2 passes as a GL smoke test:
  the baked world renders through `oglc-view` with ground, sky and trees where they
  belong. Documentation: [docs/baking.html](../docs/baking.html), indexed from
  `documentation.html`; the editor's README gained the quick start.
  **Deferred, recorded:** content is written in world coordinates with no per-tile
  transform, which is fine within a few kilometres of the origin and is §B's problem
  when placement goes georeferenced; `sample.py` and `foliage.py` still build glTF
  through pygltflib and want converting to the owned writer.
- **2026-08-17** — First vertical slice (§7) started; task breakdown and the reader
  contract the writers must satisfy are in
  [GLISTEEL-SLICE-A-HANDOFF.md](GLISTEEL-SLICE-A-HANDOFF.md). Task 1 done: the sibling is
  bootstrapped at `/workspaces/OpenGL-dev/openglcontext-editor` — distribution
  `OpenGLContext-editor`, package `OpenGLContext_editor`, `src/` layout, `specs/` with the
  clean-room procedure, and an editable workspace member of the root `pyproject.toml` and
  `requirements-dev.txt`. Nothing bakes yet; §A's glTF writer is next.
- **2026-08-17** — **The first vertical slice closes: a car drives a baked world.** The
  autopilot completed a lap of the baked 4.6 km circuit in **1:52.550**, never more than
  6.1 m off the centreline, on a world that streamed in around it and became collision as
  it arrived.

  **§C, minimal (highway-on-dirt and causeway).** `OpenGLContext.scenegraph.road` extrudes
  a cross-section profile along a resampled polyline and builds the tarmac material;
  `OpenGLContext_editor.world.road` conforms the ground to it and bakes the runs into the
  octree, one run to exactly one tile by half-open bounds. Three things had to be true
  before a road was visible on the *meshed* ground rather than on the heightfield it was
  cut into, and each is now a test on the mesh: the cut is widened to at least the ground's
  sample spacing, or it falls between two vertices; the carve is sagged by that widening
  times the path's grade limit, or a climbing road crosses its own earthwork between
  samples; and the centreline is held a freeboard above the water, or a circuit routed
  round an ellipse spends a third of a lap under a lake. The grade limiter wraps for a
  closed circuit. Roads travel in the tileset's `extras`, so a game gets the centreline
  with the world.

  **§H.** [`glisteel`](../../glisteel/) — world, car, camera, autopilot, lap timing, HUD
  and the window that runs them. The car is `omi_physics`' `RaycastVehicle`; the controls
  are sampled inside the fixed 120 Hz step, because a steering loop at the frame rate
  holds full lock for a quarter of a second on a slow frame and puts the car on its roof.

  **Engine defects found by driving, fixed where they belong.** Three were invisible to a
  static camera and appear the moment something moves:

  - *pyvrml97:* the C accelerator's `__set__` called a `cdef` setter, so no Python `fset`
    override ever ran. `node.children = [...]` detached the list from the scenegraph, and
    a tileset streamer's tiles stopped reaching the render pass — the ground never drew.
  - *omi_physics:* a streamed world stepped at 3.4 Hz. Static mesh proxies were rebuilt
    every step, AABBs were measured by building a proxy, raycasts walked every body in
    Python, and a box against terrain ran GJK/EPA per candidate triangle. Now 256 Hz.
  - *OpenGLContext:* the near plane came from the dataset radius and clipped 14 m of road
    ahead of the car; it is now taken from what the camera is looking at. Shadow
    capabilities are memoised per GL context rather than re-read per shader compile.

  **§I measured, not started.** See the table above: 148 fps with no trees, 33 fps at 40
  instances a tile. The per-instance render record is the lever.

  **Deferred, recorded:** `github.com/mcfletch/openglcontext-editor` and the `glisteel`
  remote both need creating by a networked shell before either can be a submodule here.
- **2026-08-17** — **The editor draws a track and bakes a world to drive it**
  (§F and §G, as far as a procedural landscape takes them).

  **§F, the toolkit.** `OpenGLContext.edit` holds the parts of an editor that
  are not about one editor: `tools` (the tool in force is asked before the
  camera, and a tool that takes a press keeps the pointer until the release),
  `surface` (the point under the cursor from the depth the pick already reads
  back, and the plane arithmetic a drag needs instead), and `mapview` (an
  orthographic plan view, so a metre is the same number of pixels wherever it is
  and the line drawn on it is the line the world gets). `OpenGLContext.ui.menu`
  adds the one interactive primitive the overlay toolkit did not have: a bar of
  titles, a list under each, submenus, checkable items, shortcuts. Documented in
  [docs/editing.html](../docs/editing.html) and the menus section of
  [docs/overlayui.html](../docs/overlayui.html).

  **§G, the application.** [`glisteel-editor`](../../glisteel-editor/): a
  landscape from above, a route drawn by clicking, the road settling onto the
  ground when the pointer is let go, and `File → Bake a world` writing the
  tileset the game streams. What is drawn is the ground *with its earthworks*.
  Its `tests/test_baking.py` draws a circuit, bakes it, and reads the track back
  out of the tileset through the game's own reader.

  **Engine defects the editor found**, each fixed where it belongs: `PBRMesh`
  declared its colour attribute four wide and handed a three-wide array to the
  card, which read past the end of every vertex (glTF's COLOR_0 is VEC3 or
  VEC4); `MouseEvent.unproject` named `long` on the path an editor unprojects a
  ray through; a widget could not be given its callbacks in the constructor; a
  HUD layer had no way to be told that a menu bar was using the top of the
  window.

  **The road generator got an index.** Every ground sample asks how far it is
  from the road, and the earthwork's reach is hundreds of metres, so conforming
  a landscape was comparing every sample against every segment. Grouped by cell:
  1.26 s to 0.29 s for the editor's view of a 4.6 km circuit.

  **Still outstanding for §F/§G:** rotate and scale handles (the translate
  gizmo landed 2026-08-30), picking a point behind a hill (the depth buffer
  answers only for what is drawn — see
  [RAYCAST-PICKING.md](RAYCAST-PICKING.md)), a file browser rather than the path
  on the command line, undo, and more than one route per project. §B would give the editor real elevation to draw on and §D
  the water to drop into it.
- **2026-08-17** — **§I, most of the way.** The 24-instance world at 1920×1080 went from
  37.2 fps to 57.5, and at 1000×560 from 16.5 to 73.9; the heaviest world measured (240
  instances a tile) from 5.3 to 61.4. The table in §I has the rest.

  None of it was the lever this plan expected. **Dynamic resolution would buy almost
  nothing**: at 1000×560 the same world runs at 74 fps against 57 at 1080p, so the frame
  is CPU-bound and fewer pixels are not what is wanted. What it was, in order of size:
  one render record per declared instance set rather than one per instance; one texture
  per image rather than one per tile that embeds it; a car's four wheels cast together;
  and a landscape's bodies not asked every step whether they have moved.

  Each of those is a defect in the engine underneath rather than a knob on the game, and
  each was fixed there. The quality ladder and dynamic resolution remain unbuilt and are
  now worth less than they looked.
- **2026-08-17** — **The circuit reads as a road through a wood.** Three things
  were asked for and all three are in the engine rather than in the game.

  **The forest is a forest.** Candidate density 0.12 → 0.5 trees/m² and the
  poisson spacing cut to `0.55 + 0.085·height`, so what decides the stand is the
  spacing rather than the scatter running out of candidates: 379k trees → 575k,
  fifteen metres tall, with the cleared corridor narrowed to 0.8 m beyond the
  road's own half-width. A first-person **cockpit camera** is the default view,
  which is most of why it did not read as deep enough before — and the player's
  own car is not drawn for it, because the eye is inside its shell.

  **A causeway is a structure, not a shape of the land.** `Op.CAUSEWAY` joined
  `CARRIED`; `roadworks.causeway_meshes` sweeps a retained fill at the width of
  the road it carries, with a low wall a seated driver sees over. Built as
  earthworks, a road three metres over a lake margin dragged the terrain up with
  it and battered out a hundred metres either side.

  **It is dark under the trees, and everything standing there agrees.**
  `HeightField.canopy_shadow` now spreads a tree over its *crown* and normalises
  so that one tree per crown-area is a closed canopy — the figure then means the
  same thing at any grid resolution and any planting density, which the old
  trunk-count-times-sixty did not. `SplatTerrain.shading`/`shade` make that
  public, and the shared instance layout every vegetation node uses carries a
  per-instance shade: the ground, the trees, the grass and the road's own vertex
  colours all read one answer. `TilesTerrain` wires it, because it is the one
  place that knows both where the ground is and where the trees on it are.

  **Grass, as clumps and cards.** `scenegraph.vegetation.cover` scatters a
  `CoverSpecies` on a world-anchored disc around the camera, masked by the splat
  control map — which already has the road's corridor painted out of it, so
  nothing else has to know about roads. It travels in a baked world as a recipe
  rather than a table: sixteen million blades is not a thing to write down.

  **Two defects found on the way, fixed where they belong.** A `Switch` set to
  `whichChoice = -1` crashed the flat pass, which integrated the *absent* child
  into a node path — so nothing in the scenegraph could be hidden. And the
  shipped world's splat control map was 512 pixels over four kilometres, eight
  metres a pixel, which cannot resolve a twelve-metre road corridor: the grass
  grew over the carriageway. 2048 now, and the docs say to size the map to the
  smallest thing it has to say.

  **Measured:** 62–80 fps at 1080p (from 106 with 379k trees and bare ground),
  an autopilot lap of **3:32.296** over 8.3 km, worst 2.6 m off the line, no
  recoveries.

  **Documentation:** [docs/terrain.html](../docs/terrain.html) gained *what grows
  between the trees* and *how dark it is under the trees* and a note on sizing a
  control map; [docs/roads.html](../docs/roads.html) gained the causeway and *the
  shade a road runs through*; [docs/baking.html](../docs/baking.html) gained
  *ground cover as a recipe*; both READMEs updated.
- **2026-08-17** — **§J, signs.** A road that is generated already knows what it
  is about to do, so which sign belongs where is derived rather than authored:
  `OpenGLContext_editor.world.signs.warn_of` reads the alignment's own
  curvature, its grade reversals and its bores, and places each warning a
  stopping distance before what it is about. The shipped circuit signs itself
  with 21 plates over 8.3 km — one every four hundred metres, a mix of bends,
  double bends, a dip and its two tunnels.

  Three things were worth getting right rather than approximating. A **dip is a
  turning point, not a curvature**: named by local curvature, one dip becomes
  three signs, because the brows either side of it curve the other way and are
  as real as the bottom. A **long constant bend is one bend**, so a radius that
  wobbles over the limit and back is closed up first. And a **double bend means
  the road turns one way and then the other** — two corners the same hand in a
  row are one corner to drive, and the reversal has to be found *inside* a run
  of tight radius, because a left running straight into a right never leaves it.

  `OpenGLContext.scenegraph.roadsigns` is the object: a post, a triangular plate
  and a painted face, built at the origin so a world's tens of signs are one
  instanced prototype per kind with the picture written once beside the tileset.

  **A defect the user found first.** Trees grew through the side of the
  causeway. On the ground a crown over the carriageway is the point of a forest
  road; where the road is *carried*, a tree at the same distance is rooted metres
  below the surface and its crown goes through the structure. The clearance is
  now the corridor on the land and the corridor plus a crown above it.

  **And one that turned out not to be.** A capture showed the road running into
  the dirt and stopping. It was a four-second static capture with the tiles
  still arriving, but "does the road disappear" is not a question to settle by
  eye: `RoadLayer.segments_in` now says which stretches of the centreline a tile
  is responsible for, and `tests/test_world_road_coverage.py` holds that the
  tiles at every level of the tree write each segment exactly once — never none,
  which vanishes under refinement, and never two, which flickers.
- **2026-08-18** — **§J, obstacles; and a bake that can be iterated.**

  **Obstacles.** `OpenGLContext.scenegraph.props.Prop` is the thing the baker had
  no concept of: a *placed* thing, a mesh and a body at one spot, with the
  measurements a physics world needs to stand it up without being handed the
  geometry. `PropColliders` holds the ones within reach and lets go of the rest;
  the records travel in the tileset's `extras`, because a collider built from
  tile geometry is a rock the car drives through at the moment the tile behind
  it swaps. The shipped world strews 107 boulders along its verges, clear of the
  carriageway by their own size, and `rock_mesh` grows them from a subdivided
  icosahedron so no art is needed. Parked cars, deer and foxes are the same
  mechanism waiting for art.

  **A defect measured rather than argued.** Concrete, barrier, rock and sign post
  all rendered white. A swatch of six known albedos through the real PBR pass
  settled it in one render: the ramp is right and the numbers were simply at the
  bright end of it. They are chosen by eye now, and say so.

  **The bake: 4m36s → 25s.** Profiled by phase, 91.5% of it was the tree scatter,
  and nearly all of that was questions about ground the answer did not depend on.

  - *Ask for a spacing, not a density.* Uniform random candidates thinned to a
    minimum separation is dart-throwing: eight million candidates for half a
    million trees. A jittered grid at the spacing gives the same forest from two
    and a half million. 286 s → 31 s.
  - *Filter cheapest-first, each on what the last one left,* and let a caller
    that has already sampled the ground answer "how steep is it" with a lookup
    (`slope_fn`) instead of four evaluations of a conformed height function.
    31 s → 16 s, and the tree layer's own slopes 2.7 s → 0.07 s.
  - *Do not iterate over cells the road never reaches.* The query index grouped
    a 2048-pixel control map into most of a million cells and walked every one.
    One vectorised rejection against the road's own occupancy first:
    `bake_world` 11.4 s → 4.1 s, painting the corridor 8.0 s → under one.

  `RoadPath.index_cells` is the measurement that made the last one visible —
  `comparisons` counts the work the index saves and says nothing about the
  iterations it costs.

  **Still open:** signs cost 21 fps of the 73 the world drove at before them
  (measured across four bakes: no signs 73.3, signs 51.8, signs and props 45.9).
  The plate's material is no longer an alpha cutout, which was one reason; the
  rest is a node per kind per part per tile and is not yet measured.
- **2026-08-18** — **§J, traffic; and one geometry for every sign.**

  **Traffic.** `glisteel.traffic` puts other cars on the road in both
  directions, driven by *station* rather than simulated as vehicles: a
  kinematic body and a transform apiece rather than four raycasts a step, which
  is what lets there be eight of them for nothing measurable. They keep to their
  own side, drive at the limit, and decide for themselves — a car brakes for
  something its driver can see and the player cannot, or pulls off the road
  altogether — from a seed, so the same world drives the same way twice.

  Getting them not to drive *through* each other took the rule rather than a
  number. A following window with a distance in it is a driver who notices the
  queue too late to join it if the window is shorter than the braking distance,
  and one who crawls behind nothing if it is longer; the speed a car may go is
  `sqrt(2 a s)` in the room it has plus whatever the car in front is doing, and
  the step it takes is clamped so however badly that is judged, nobody drives
  through anybody.

  **The player is part of the traffic.** A car on the grid is a car in the road,
  and the road behind it has to notice — which is what made the whole thing work
  at all: before it, the first car along shoved the stationary player into the
  trees inside five seconds.

  **A road with two directions is a road you keep a side of.** `Course.across`,
  `Course.lane_point` and `Course.driving_lane` are that side, in the frame
  everything swept along a road already uses, and the grid and the autopilot
  take it when there is traffic. On an empty circuit the line is still the
  centreline, because that is the racing line.

  **Two defects on the way.** `Course.across` on a closed course asked for the
  direction of the segment between the last point and the first — which are the
  same point, so it fell back to a fixed vector with the wrong sign, and
  everything that keeps a side of the road swapped sides for the length of a
  tile. And a sign's plate was declared an alpha cutout although it is a
  triangular prism whose picture never reaches a transparent fragment, which put
  every sign in the world into the sorted transparent pass.

  **Signs are one geometry and one picture now.** `sign_atlas` puts every
  plate — and a flat patch of the post's own colour — in one image, so a sign is
  one material whatever it says and a tile's signs are one mesh and one draw.
  Measured at 1080p on the shipped world: 51 shapes and 8.35 ms of draw became
  41 and 6.70. Baked into place rather than instanced, because instancing is for
  thousands of copies and a per-instance *texture offset* is a fair amount of
  engine for a few hundred triangles a tile.

- **2026-08-18** — **The lap has a line.** A start/finish gantry stands where
  the centreline begins: two legs off either shoulder, a beam over the
  carriageway with a chequered banner on it, and a chequered line painted across
  the tarmac beneath. `OpenGLContext.scenegraph.gantry` is the object,
  `OpenGLContext_editor.world.gantry.start_finish` reads its place off the
  road's own alignment, and `bake.gantry.GantryLayer` writes it. Nothing in
  `glisteel` changed: the marker arrives as tile geometry and the legs arrive in
  the props the game already stands up.

  **Three things worth keeping.**

  *The chequer on the road had to be geometry.* Painted as a texture it read as
  a plain white bar from the driving seat — a 9:1 image on a surface seen nearly
  edge-on picks a mip level off its short axis and blurs the long one to its own
  average. Each square is now its own quad reading a flat colour out of the
  atlas, which is a chequer at any angle and costs 72 triangles once per world.
  The banner keeps its picture, because it is seen face-on.

  *A leg needs its own ground.* The two sides of a road are rarely level with
  it, so `start_finish` measures the height under each foot and the mesh takes a
  drop per leg; each is also sunk a `FOOTING` below what it measured, because
  the drop is taken against the design height and a terrain tile a hundred
  metres off is a coarser surface than that.

  *Two layers can now fill one channel.* The gantry's legs and the landscape's
  boulders are both the world's props, and the bake driver used to `update()`
  one dict over another, so whichever layer was listed later silently won.
  Lists join; anything else arriving twice stops the bake, because "where does
  the lap begin" has one answer and picking a winner from two writes a world
  whose timing belongs to whoever was last.

  **Shared out of the signs, not duplicated.**
  `OpenGLContext.scenegraph.atlasmesh` now owns packing pictures into one image
  and concatenating geometry into one mesh, and
  `OpenGLContext_editor.bake.placing` owns standing a prototype somewhere and
  gathering the results; the sign path was moved onto both. Bake of the shipped
  world, measured on a quiet machine: 27.5 s.

- **2026-08-21** — **Corners are banked.** A road may now be superelevated: the whole
  carriageway rolled about its centreline so that a corner leans into itself.
  `OpenGLContext.scenegraph.road` owns the arithmetic — `plan_curvature` for how tightly
  the line turns and which way, `superelevation` for the lean that balances a car at a
  given speed, `bank_profile` for the lean along a whole alignment with its transitions,
  `banked_sections` for the camber the lean uses up, and a `bank` argument on
  `sweep_frames`, `road_surface`, `road_mesh`, the three `roadworks` sweeps and
  `RoadColliders`. `corner_speed`, `cornering_radius` and `advisory_speed` all take one.
  `RoadPath` carries it, `conform_terrain` meets the verge each side is actually at,
  `RoadLayer` writes it into the tileset beside the centreline, and `glisteel` reads it
  back for the collider, the traffic and the plates.

  **Decisions taken, and why.**

  *Road banking, not an oval's.* `MAXIMUM_BANK` is 0.10 — 5.7°, the upper end of what is
  built into a road. Highway practice runs from about 0.04 where ice is expected, since a
  vehicle stopped on a steeper one slides down it, to about 0.12 where it is not. What it
  buys is a corner some 10% faster than the same corner flat, or a fifth tighter for the
  same speed: the shipped circuit's corner floor went from 315 m to 270 m. An oval reaches
  three or four times this; nothing stops a caller asking for it, but it is not what a
  road is.

  *The design speed is a floor, not a target.* Each corner is banked to *balance* a car at
  the design speed — at that speed the road alone holds it and the tyre's grip is
  untouched — so what the corner actually holds is strictly more. The shipped circuit's
  slowest corner is 205 km/h against a 200 km/h design speed, and its median corner holds
  anything at all. `CORNER_MARGIN` keeps the floor clear rather than grazed: a plan is
  drawn at one spacing, filleted, draped and re-sampled, and each of those moves the line.

  *The runoff leads the corner rather than lagging it.* The first rate limiter clipped the
  demand forwards, which put the roll *inside* the bend — the one place a driver cannot be
  given something else to deal with. What landed is a cone dilation: the lean at a point is
  the most any corner within reach asks for, less what the road lets out over the distance
  to it, so the whole transition sits on the approach. `BANK_GRADIENT` is 1 in 200, some
  70 m of transition for a full bank on a two-lane road. Where two opposite corners crowd
  each other, or a corner is near the end of a road that is not a circuit, the pair get
  what the road between them can deliver; an open road starts and ends flat.

  *The frame rolls; the cut does not tilt.* Rotating the frame keeps the carriageway the
  width it was told — tilting the cut instead stretches it by the cosine of the lean. The
  camber is handled separately and turns out to be a one-line adjustment: the crown is
  *used up* by the lean, symmetrically, so `RoadProfile.banked(bank)` is the same profile
  with `crossfall` reduced by `|bank|`. The outer half of the cut rotating up about the
  crown and the whole plane then rotating together fall out of that identity.

  *A gantry does not lean.* The line painted across the road does — a flat strip on a road
  at one in ten stands a third of a metre proud on one side — but the steel over it stands
  upright on its two feet, which is what a gantry over a banked road does. `placed()` grew
  a `roll` for the paint.

  **Checked end to end.** A ray dropped onto the collider at the point `Course.lane_point`
  puts a car lands within 0.1 mm of it, right across a banked corner; swept flat under the
  same road it is out by more than 20 cm. Documentation:
  [docs/roads.html](../docs/roads.html) gained a *Banked corners* section,
  [docs/physics.html](../docs/physics.html) the collider's `bank`, and the READMEs of the
  world generator, the game and the track editor say what a designer and a player get.

- **2026-08-21** — **A road with a character of its own.** The alignment's limits
  may now *vary along it*: `follow_terrain` takes `smoothing`, `maximum_grade`
  and `design_speed` as one figure or one per point, `hold_corners` takes a
  radius per corner, and a new `OpenGLContext_editor.world.character` decides
  what all of those should be. `RoadPath` carries the cleared corridor and the
  widening; `RoadLayer` writes the widening into the tileset; the engine gained
  `RoadProfile.widened` and `widened_sections`, and `RoadColliders` a
  `widening`. The shipped circuit is now a lap with a hairpin on it.

  **Everything is derived, not sprinkled.** The corners come from a mix, so a
  lap has one to brake for and one to carry flat; how fast a stretch is laid out
  for is what its own corner allows; how steeply it may climb is what the land
  demands over a quarter-kilometre; how much it is smoothed follows the speed,
  so slow stretches keep the ground's shape and fast ones are ironed flat; how
  far the trees go back is the sight a driver needs round the bend they are on,
  read off `sqrt(8·r·clear)`; and the climbs get an extra lane's width, worst
  first, until a budget is spent. The shipped four-kilometre circuit comes out
  with corners from 60 m to a straight, stretches laid out for 87 to 200 km/h,
  grades to 14% where the land climbs, corridors from 6.1 m to 11.0 m, and two
  widened climbs over a sixth of the lap.

  **Decisions taken, and why.**

  *A drawn route keeps its corners.* `corner_radii` applies to the circuit the
  generator invents, never to a route a caller gave: a designer who drew a
  hairpin meant it, and re-drawing it from a mix is the generator overruling
  them. A drawn route still gets everything derived from the line and the land,
  which follows from what they drew rather than replacing it.

  *A budget on the climbing lanes.* Derived purely, this landscape earns a
  climbing lane over 40% of the lap — which is a wide road, not a road with
  passing places on it. `CLIMBING_LANE_SHARE` caps it at a sixth and gives it to
  the worst climbs first. How much of a road is built three lanes wide is a
  decision somebody pays for, so it is a knob rather than a consequence.

  *A ramp, not an average, for the taper.* Averaging a 0/1 flag reaches half its
  height at the edge of what was flagged and the rest in one step — for a lane
  that is a lane beginning in mid-air. The taper is a distance ramp instead:
  full where earned, nothing a taper away, straight between.

  *A variable-width box filter for the smoothing.* A convolution cannot take a
  width per point; a difference of running sums can, in one pass, and is exactly
  the average of the points each window covers.

  **Two things looked into and left alone.** A coarse tile's road wanders from
  the fine one by cutting its corners, and tighter corners make that worse — but
  the root geometric error of a baked world is 6 m whatever its depth, so the
  spacing never gets coarse enough for it to matter, and a cap on it was written
  and then removed as machinery nothing exercises. And two ground-level captures
  that came back with no road on them were the camera, not the world: an eye
  1.6 m up aimed a hundred metres along a tight corner is aimed into the trees
  beside it. Seen from above, both places have the road exactly where it belongs.

  Documentation: [docs/roads.html](../docs/roads.html) gained *Somewhere to be
  passed*, and the READMEs of the world generator, the game and the track editor
  say what a designer and a player get.

- **2026-08-22** — **The driver, and the edge of a deck.** An autopilot lap of the
  varied circuit with traffic on it did not finish, and taking it apart turned up
  five defects, none of them in the road:

  *A pass counted as a crash.* `Session._watch_for_a_crash` asked "what is in
  front" at the width a driver *reads the road* at (2.8 m), but two cars in
  their own lanes on a 7.2 m carriageway are 3.6 m apart. Drift two feet towards
  the crown and every car met on a two-way road ended the run with nothing
  touching. `CONTACT_REACH` was documented as "touching distance and no more"
  and had no width beside it; now `CONTACT_WIDTH`, and the two questions are
  asked at their own widths.

  *A following distance was a length of road.* Seven metres is comfortable at a
  crawl and a third of a second at ninety, and the driver spent the lap surging
  up to whatever was in front and braking off it again. It is a **time** now,
  which is what `FOLLOWING_SECONDS` already argued for in its own docstring --
  `StandIn` had been overriding the figure every frame, so only the direct
  autopilot was driving on the bad one. The rule moved into `DriverStyle`, and a
  stand-in says "a pass is not a follow" by asking for no seconds at all.

  *It could not overtake.* The plain `Autopilot` had no lane decision, so it
  queued behind the first slow car for the whole lap while everything quicker
  piled up behind it. It pulls out now, sized by **two** speeds -- how long the
  pass takes is the gain it has *now*, and how much road that consumes is what
  closes on the other side of a two-way road -- and it abandons back to its own
  side the moment the way through shuts. Sized on one speed it asked for forty
  metres and used four hundred.

  *`--pace` never reached it.* Documented as how hard the car drives itself, and
  passed only to the stand-in; the direct autopilot drove at the limit of the
  tyres with nothing in hand.

  *And it could not rejoin.* Pure pursuit steers at a point up the road and
  holds whatever speed the road allows, and neither knows the car is off it. A
  car knocked wide drove on at road speed into the trees. It lifts to
  `REJOIN_SPEED` with a wheel off the carriageway now.

  **The bridge, which was the one that mattered.** A deck and a causeway are
  *drawn* with a barrier along each edge -- that is what the barrier is for, and
  `BarrierProfile`'s own docstring says so -- and nothing in `physics/` had ever
  heard of it. The car went through the railing and off into the valley the
  bridge was built over, every time it ran wide on one. `roadworks.barrier_wall`
  is the shape a collider takes: the drawn barrier's footprint carried to its
  full height, solid, because the holes in a railing are for seeing through
  rather than driving through. `RoadColliders` takes the carried stretches and
  puts one up along both edges of each; a **bore** is carried too and gets none,
  since what is beside a tunnel is the hillside it is in. Measured on the
  shipped circuit: a wall 4.4 m from the crown on every deck and causeway, and a
  car driven at full lock into the edge for six seconds stays on it.

  Found on the way and fixed: `RoadColliders.triangle_count()` only ever went
  up. It counts what is *held* now, which is what it says it counts.

  **Where it leaves the autopilot.** `--control line`, which drives through the
  stand-in, gets round: 7192 m in 439 s with sixteen cars on the road, never
  more than 2.4 m off the centreline. The default `--control wheel`, which
  steers directly, no longer leaves the road and no longer falls off a bridge,
  but queues -- its passing rule wants some 275 m of clear oncoming lane and
  sixteen cars rarely leave that. What would finish it is lifting the stand-in's
  tuned passing -- sight, `PASS_MARGIN`, refusals, slipping into gaps -- out of
  `StandIn` and into the driver so both share one; that is a refactor of a
  subtle mechanic and is not started.

  Documentation: *What keeps a car on a structure* in
  [docs/roads.html](../docs/roads.html), the collider's `barriers` in
  [docs/physics.html](../docs/physics.html), and the game's README on what the
  driver knows about traffic and what a deck's edge does.
