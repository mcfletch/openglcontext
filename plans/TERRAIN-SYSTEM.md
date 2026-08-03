# Large-World Terrain & Vegetation

**Goal**: A **production-grade** large-world terrain system for OpenGLContext —
able to run a real game, not a demo — that streams huge landscapes at good frame
rates, supports true 3D features (**fissures, crevasses, overhangs, caves**), not
just a height surface, and carries dense **vegetation** (grass, flowers, brush,
trees).

**Primary target**: discrete **GeForce RTX 3060-class** (GL 4.6). Integrated GPUs
and software rasterizers are first-class fallback tiers, not afterthoughts.

**Overriding design constraint — build on standards, not a bespoke pipeline.** A
studio should author terrain, caves, and scatter in existing DCC/GIS tools, export
to a standard, and have it stream in. We build the runtime; we do **not** invent a
terrain file format. The engine today has no real terrain system — the toy
`tests/heightmap.py` (one static `GL_QUAD_STRIP`, flat normals) is a throwaway, not
a foundation, and is not referenced by this design.

---

## Direction reset (Session 5) — authored terrain, not a GIS viewer

The 3D-Tiles-real-dataset direction was reassessed and **demoted**. OGC 3D Tiles is a
GIS *transport* format for streaming real-world captured data; games don't author terrain
in it, every open dataset is coarse municipal blocks or point clouds, and the good data is
auth-gated — so consuming third-party 3D Tiles is a GIS-viewer product, not the authored
game terrain this feature is for. The low fidelity ("early-90s flyover") was coarse content
+ no virtual texturing + no authoring bake + renderer gaps, **not** the streaming engine.

**New north star:** efficiently add large-scale **authored** terrain at modern fidelity.
**Keep** (format-agnostic): streaming runtime (SSE/residency/LRU/prefetch/frustum),
procedural gen, DEM ingest, vegetation scatter+instancing, physics, geomorph skirts,
splatting. **Demote:** the 3D Tiles b3dm/region/external/network loader → optional import
only (it works; Session 4 below). **Build** the fidelity levers we lack, sequenced:

- **M1 Renderer fidelity foundation** — draw sky/environment under the core profile (kills
  the black void), tonemapping/exposure in the PBR path (fixes the washed look), AO.
- **M2 Layered-PBR terrain material** — control-map splat blend of N detail materials +
  triplanar on slopes + macro/micro detail normal maps + distance-based tiling.
- **M3 Authored input pipeline** — heightmap (R16/PNG) + splat/control map + material set
  ingest → chunked-LOD terrain (extends DEM ingest).
- **M4 Close-up geometry** — GPU tessellation / hardware displacement.
- **M5 Vegetation at scale** — use **real CC0/CC-BY glTF tree/plant models** (loaded by
  the existing glTF loader), not procedural cones. Distance LOD chain per instance:
  full mesh (GPU-instanced) near → decimated mesh mid → **octahedral impostor** far (a
  view-atlas pre-rendered offline from the real mesh with our own render-to-texture, sampled
  by a camera-facing quad — the modern UE5-style impostor). Attribution via the existing
  `cc0.py` CREDITS manifest pattern, extended for model credits. Auto-fetchable CC0 sources
  (Poly Haven API, Quaternius, Kenney) load headlessly; Sketchfab CC0/CC-BY needs a login /
  Data-API token, so those get dropped into an assets dir manually (or fetched with a token).
- **Later** — virtual texturing for large worlds; SDF/Transvoxel caves/overhangs.
- **Prove** with an *authored* high-fidelity scene, not a real-world GIS flyover.

Original requirements (clipmaps/chunked-LOD/GPU tessellation, caves, vegetation, RTX 3060,
run real games) still stand; this returns to them. Sessions 1–4 below are prior history.

## Implementation status

**Legend:** ⬜ not started · 🔨 in progress · ✅ done (tests green).

Environment: interpreter `/workspaces/OpenGL-dev/.venv/bin/python` (py3.12); `py3dtiles`
12.1.1 installed. Offscreen rendering via GLFW hidden window (display is busy) —
`OPENGLCONTEXT_BACKEND=glfw`, hidden window, `OPENGLCONTEXT_AUTO_EXIT_FRAMES`/capture
env for regression. TDD Red/Green throughout; run `.venv/bin/python -m pytest tests/tiles3d/`.

Package layout: runtime in `OpenGLContext/loaders/tiles3d/`, node in
`OpenGLContext/scenegraph/tilesterrain.py`, tests in `tests/tiles3d/`.

**Demonstrations:** each phase ships an interactive demo (`tests/tiles_*.py`) that
doubles as a visual-regression capture (per the project's `tests/physics_*.py`
convention), so progress is viewable as it lands. Run e.g.
`OPENGLCONTEXT_BACKEND=glfw .venv/bin/python tests/tiles_terrain.py`.

| Phase | Item | Status | Notes |
|---|---|---|---|
| 1a | screen-space error (`screenspaceerror.py`) — 7 tests | ✅ | perspective SSE + should_refine |
| 1b | tileset/tile data model (`tileset.py` + `boundingvolume.py`) — ✅ 17 tests | ✅ | BVH, geometricError, refine inherit, content resolve, box+sphere world-space transforms. **Finding:** py3dtiles `Tile.from_dict` raises `NotImplementedError` for `sphere`/`region` (box-only), so the runtime *tree* parser is our own thin JSON reader; py3dtiles reserved for content/GLB + bake-side writing |
| 1c | SSE traversal (`traversal.py`) — 8 tests | ✅ | render + want (=render ∪ prefetch at lower threshold); REPLACE hides parent, ADD keeps it |
| 1d | residency LRU + lifecycle (`residency.py`) — 8 tests | ✅ | states UNLOADED→LOADING→READY→RENDERABLE, byte budget, LRU evict, never evict wanted/pinned |
| 1e | load manager (`loadmanager.py`) — 8 tests | ✅ | pure LoadQueue (priority/cancel/FIFO) + threaded LoadManager (worker pool, injectable loader_fn, cancellation) |
| 1f | orchestrator + GL upload + `TilesTerrain` node — 12 tests + render regression | ✅ | `runtime.py` (per-frame tick: traverse→load→upload→evict→parent-fallback, injectable uploader, 5 tests), `gltf_uploader.py` (worker-side glTF parse is GL-free + GL-thread mount, 4 tests), `scenegraph/tilesterrain.py` Group node (3 node-integration tests), `tests/tiles_terrain.py` demo + `test_tiles_terrain_render.py` offscreen pixel regression. **Finding:** terrain rendered black from above — heightfield triangle winding was CW (top face back-face-culled; `doubleSided` is not honored as cull-disable by the PBR path), fixed to CCW-from-above. **Follow-up:** PBR baseColor washes to grey/white under the default light rig (no tone/exposure like gltf_view) — cosmetic, tracked for Phase 2 polish |
| 1g | per-tile physics colliders (`physics_colliders.py`) — 4 tests | ✅ | resident tiles become static `trimesh` bodies in a `PhysicsWorld` via `extract_trimesh`; wired through runtime `on_renderable`/`on_evicted` hooks and `TilesTerrain(physics_world=…)`. **Follow-up:** `PhysicsWorld` has no `remove_body`, so evicted colliders are recorded (`pending_removals`) but not yet reclaimed — needs a small physics-world removal API. **Triplanar splat material deferred to Phase 2** (tiles render with standard per-tile PBR meanwhile) |
| — | sample tileset generator (`sample.py`) + E2E offscreen regression | ✅ | heightfield quadtree glb bake (root + 4 children), doubles as the bake-tool seed |

**Phase 1 is functionally complete: a streamed, walkable 3D-Tiles terrain that renders
offscreen (`tests/tiles_terrain.py`), 66 tests green.** The demo renders correct rolling
heightfield topography with proper normals/shading/LOD. Open follow-ups carried into
later phases:
- **PBR albedo desaturation:** a saturated green baseColor renders as flat tan/grey even
  with IBL off and low ambient — the direct-light path appears to wash saturation (likely
  a gamma/ambient-space or missing-tonemap nuance in the PBR shader). Needs a shader-level
  look; not a terrain defect. (Phase 2 polish)
- single-color `Background` (skyColor) not drawn under core profile (sky reads black);
- `PhysicsWorld` body removal (evicted colliders recorded, not reclaimed);
- triplanar splat material (tiles use standard per-tile PBR meanwhile);
- explicit GL VBO release on eviction (currently GC-reclaimed).

**Phase 2+ progress:**
- **2b SSE hysteresis** ✅ (`traversal.py` sticky refinement + `refined_state`, wired into
  `TilesetRuntime(hysteresis=…)`; 4 tests) — kills LOD flicker at threshold boundaries.
- **2c Draco/meshopt decode** — deferred: the glTF loader decodes Draco only when `DracoPy`
  is installed (see [DRACO-COMPRESSION.md](DRACO-COMPRESSION.md), not yet available here);
  tile payloads flow through the same loader, so it lights up for free once that lands.
- **2a geomorph** — deferred (needs vertex-correspondence data from the bake/simplifier, §10).
- **3 caves/overhangs** ✅ (architecture validated): caves are arbitrary-topology glTF
  octree tiles — no special case. An authored elevated-slab **overhang** tile
  (`build_overhang_tileset`, genuine solid-air-solid) streams, renders (verified
  offscreen), and produces a walkable static collider through the same runtime; 2 tests.
  Procedural **Transvoxel** SDF-carve bake tool is still future (turns a heightfield ±
  cave brushes into these tiles automatically).

- **4 vegetation** ✅ (scatter + instanced render): `scatter.py` — deterministic,
  area-weighted, seeded surface placement (per-triangle uniform barycentric sampling,
  density → count, yaw/scale), 6 tests. `vegetation.py` — turns placements into per-instance
  `Transform`s over one shared prototype so the instancing engine collapses them to a single
  draw, 3 tests. `tests/tiles_vegetation.py` demo + render regression: **hundreds of shrubs
  scattered on the heightfield render in one instanced draw** (verified offscreen).
  **Still future:** octahedral impostor far-LODs, and GPU-grass compute scatter + indirect draw.

### Session 2 — realism, navigation, streaming, culling

- **Procedural realistic terrain** ✅ `procedural.py`: numpy value-noise fBm + ridged
  mountains, a carved river **canyon**, a **lake** basin (water clamped flat), and
  **per-vertex colours** (water/sand/grass/rock/snow by height+slope). Bakes a
  multi-level quadtree (`build_terrain_tileset`, 1+4+16+… tiles). Renders as a
  convincing landscape (green hills, blue river/lake, snow-capped rock). 6 tests.
- **Vertex-colour rendering fixed** ✅ — the earlier grey wash was simply the wrong
  renderer: PBR vertex colours (`COLOR_0`) only render under `OPENGLCONTEXT_RENDERER=pbr`
  (the base pass ignores them). Demos now set it; landscape renders in full colour.
- **Frustum culling** ✅ `frustum.py` (perspective/look-at matrices + Gribb-Hartmann
  plane extraction + sphere test) + `bounding_sphere()` on the volumes, wired into
  `TilesetRuntime.update(view_projection=…)` and `TilesTerrain`. This is what makes the
  resident set a **moving window** instead of the whole world. 5 tests.
- **Physics navigation** ✅ validated **headless** against real procedural-terrain
  trimesh colliders via `PhysicsViewPlatform`: gravity **settles the avatar onto the
  surface**, **walking follows** the terrain, **flying ascends freely**, and switching
  **fly→walk drops to the surface**. 4 tests (`test_navigation.py`).
- **Streaming/caching** ✅ validated with a **flythrough over an 85-tile world** under a
  budget too small to hold it: tiles load as approached, **memory stays bounded**, tiles
  **evict** as they fall behind, and far more distinct tiles stream than are ever resident
  at once — resident tiles stay near the camera. 2 tests (`test_streaming.py`).
- **Terrain-aware vegetation** ✅ scatter gained a `keep` filter; the showcase scatters
  conifers **only on grass elevations** (not water/peaks). Instanced → one draw.
- **Landscape showcase** ✅ `tests/tiles_landscape.py` (procedural terrain + frustum-culled
  LOD + vegetation) with an offscreen render regression asserting grass **and** water.
- **Offscreen hang fixed** ✅ heavy scenes blocked in `swap_buffers` on the hidden window;
  demos now `glfw.swap_interval(0)` (render 180s-hang → 1.3s).

### Session 3 — the remaining plan items

- **Live walk-mode demo** ✅ `tests/tiles_walk.py`: first-person `PhysicsViewPlatform` over the
  streamed terrain — WASD walk, QE turn, Space jump, **G toggles walk/fly**, R/F rise/descend;
  colliders stream with the visuals so you walk on what you see. Render regression confirms the
  eye-level view is seated on the surface.
- **Vegetation LOD + billboard impostors** ✅ `partition_by_distance` + `build_vegetation_lod`:
  near instances render as full meshes, far ones as cheap billboards (one draw each). (Octahedral
  view-atlas impostors are the future refinement of the billboard.)
- **Instanced grass** ✅ `build_grass_patch`: dense blades limited to a disc around the camera and a
  grass elevation band, so blade count stays bounded as the camera moves. (GPU-compute/indirect is the
  future scale-up; this is the working instanced form.)
- **Geomorph / crack-free seams** ✅ **skirts** baked into every tile (`terrain_patch(skirt_depth=…)`,
  scaled per LOD) eliminate gaps between adjacent-LOD tiles; `geomorph.py` provides the morph-factor
  ramp, fine→parent position lerp, and parent-heightfield sampler (the vertex-morph primitives; GPU
  attribute wiring is the remaining integration).
- **Real DEM ingest** ✅ `dem.py`: a grayscale heightmap image (QGIS/USGS/SRTM export, any PIL format)
  becomes a world-space height function (bilinear, edge-clamped) fed to the same baker → a streamable
  tileset. The baker now takes a `height_fn`, so procedural and DEM share one path.

- **User-facing viewer + docs** ✅ `bin/terrain_view.py` → the **`oglc-terrain`** console script
  (registered in `setup.py`/`pyproject.toml`): walk/fly a procedural world, a `--dem` heightmap, or
  an existing `tileset.json`, with `--extent/--levels/--tile-res/--sse/--memory/--fly/--size`. User
  documentation at **`docs/terrain.html`** (quick start, how it works, making a world, vegetation,
  tuning, caves, demos), linked from `docs/documentation.html`.

**Totals: 114 tests green (12s); ~21 runtime modules + node, `oglc-terrain` viewer, 5 demos (heightfield,
overhang/cave, vegetation, procedural landscape, first-person walk), 4 offscreen render regressions.
Sessions 1→2→3:
82 → 101 → 114. Remaining refinements (all future, documented): octahedral view-atlas impostors,
GPU-compute grass + indirect draw, GPU vertex-morph wiring, `PhysicsWorld` body removal, triplanar
splat, Draco decode, single-colour Background under core.**

Remaining (future, documented): octahedral impostors + GPU-grass compute/indirect (5),
procedural Transvoxel cave bake (3), geomorph (2a), Draco decode (2c), PBR albedo/tone
polish (2a), triplanar splat material, `PhysicsWorld` body removal, single-color Background
under core.

### Session 4 — loader/renderer for the *format* (real datasets, not bespoke content)

Re-framing: the deliverable is a robust **loader + renderer for OGC 3D Tiles that
renders real, third-party datasets**, not a from-scratch procedural world. Validated
against Cesium's **`TilesetWithDiscreteLOD`** sample (the "dragon": a `tileset.json`
with an ECEF root transform and a `low→medium→high` `b3dm` LOD chain).

- **`b3dm` tile content** ✅ `gltf_uploader._strip_b3dm` skips the 28-byte Batched-3D-Model
  header + feature/batch tables and hands the embedded GLB to the existing glTF loader.
  The dragon's three LODs all parse and render.
- **ECEF recentring** ✅ `build_runtime_tileset(recenter=True)` subtracts a large ECEF
  offset so a geospatial tileset renders near the origin instead of ~6.4 M m out (where
  float precision shatters it). The offset is the root transform's translation, or — for
  region tilesets — the root region's ECEF centre. Non-identity tile transforms mount via
  `MatrixTransform(localMatrix=world_transform.T)` (row-vector convention).
- **Geodetic `region` bounding volumes** ✅ `boundingvolume.RegionBV` + `geodetic_to_ecef`
  (WGS 84): converts `[west,south,east,north,minH,maxH]` to an enclosing ECEF sphere,
  respecting the spec rule that regions are datum-fixed and **not** transformed by the tile
  matrix (only the recenter offset applies). This unblocks Cesium ion / Google Photorealistic
  / GIS tilesets, which use `region`. 8 tests.
- **External (nested) tilesets** ✅ a tile whose content is another `.json` is loaded via an
  injectable `resolve_external(uri)` (local files by default; a custom resolver fetches
  remote), re-rooted under the referring tile's transform, and grafted as a child subtree.
  Cycle-guarded (`_MAX_EXTERNAL_DEPTH`). 4 tests + a two-file dragon chain rendered end-to-end.
- **Multiple contents per tile** ✅ 3D Tiles 1.1 `contents` (plural): a tile may carry
  several glTF (e.g. buildings + trees). `RuntimeTile.content_uris` is the canonical list
  (`content_uri` stays as the first, for single-content callers); the loader parses all and
  combines them into one `_CombinedScene` drawable. `.json` entries among `contents` still
  split off as external subtrees. 3 tests + Cesium 1.1 `MetadataGranularities` rendered.
- **Network streaming (`http(s)://`)** ✅ `fetch.py`: scheme-aware URI resolution
  (`resolve_uri`/`dir_of`) and `read_bytes(uri, cache_dir)` reading from a local path or a
  URL, caching remote responses on disk (atomic write, keyed by URL, default
  `~/.cache/openglcontext/tiles3d`). Wired through the whole chain — the root, external
  tilesets and tile *content* all fetch over HTTP: `make_tile_loader(cache_dir)` (content),
  `_default_external_resolver` (nested `.json`), and `TilesTerrain(cache_dir=…)` (root). The
  `oglc-tiles` viewer takes a URL source + `--cache-dir`. 7 fetch tests (network mocked, CI-safe).
  **Verified end-to-end:** `oglc-tiles https://raw.githubusercontent.com/CesiumGS/3d-tiles-samples/main/1.0/TilesetWithDiscreteLOD/tileset.json`
  streams and renders the dragon from a cold cache; a second run with HTTP disabled renders
  identically from cache. Only API-key services (Cesium ion, Google) still need auth headers.
- **`oglc-tiles` viewer** ✅ `bin/tiles_view.py` (registered console script): loads any
  `tileset.json`, auto-frames the whole tileset (explicit frustum + mesh-centroid aim), and
  free-flies while streaming by SSE. `--sse/--memory/--fov/--margin/--no-recenter/--capture`.
  6 helper tests. **Finding:** auto-frame must run **before** priming — priming from the
  default camera pose (often *inside* the tileset) refines straight to the finest LOD, and
  with REPLACE refinement the coarse ancestors are never loaded, so jumping to the framed
  pose evicts the fine tile and leaves the first frames empty. Framing first primes the LOD
  the view actually needs. Verified: framed view selects `low`; `--sse 0.02` refines to `high`.

**Known limitation (documented):** a hard camera *teleport* can briefly hole, because REPLACE
refinement never loads coarse ancestors as a standing fallback — gradual flight is fine
(prefetch loads the finer tile ahead and pins the coarser one until it arrives). A standing
coarse-fallback residency is the follow-up. Remaining real-data gaps: auth-gated remote
services (Cesium ion / Google tokens), glTF `RTC_CENTER` content offsets, `.pnts`/`.i3dm`/
`.cmpt` content, and implicit tiling (`.subtree`).

**Verified against real Cesium samples** (CesiumGS/3d-tiles-samples, Apache-2.0), both from
local copies and streamed live over their raw-GitHub URLs: `1.0/TilesetWithDiscreteLOD`
(the dragon: b3dm + ECEF + LOD chain), `1.1/MetadataGranularities` (glTF-native, multiple
contents per tile: houses + trees) and `1.1/MultipleContents`. Documented in
`docs/terrain.html`. Not yet loadable: `.pnts` (point clouds), `.i3dm` (instanced), `.cmpt`
(composite), implicit tiling (`.subtree`), and auth-gated services.

**Totals: 157 tests green.** Sessions 1→2→3→4: 82 → 101 → 114 → 157.

---

## 1. Architecture: OGC 3D Tiles, glTF payloads everywhere

The terrain is an **OGC 3D Tiles** dataset streamed at runtime. This is the open
standard for streaming massive 3D worlds: a `tileset.json` bounding-volume
hierarchy (quadtree for surface extent, **octree** where the world goes 3D) with a
**geometric/screen-space error** per tile that drives LOD refinement, and **glTF**
tile payloads. The engine already has deep, conformant glTF support, so *rendering*
a tile is solved — the new work is the **traversal + streaming runtime**.

The decisive property: **surface, caves, overhangs, arches, and static props are
all just glTF meshes in the same octree.** There is no separate heightfield
representation and no special surface case — a cave tile and a hillside tile differ
only in their geometry, both authored/baked to glTF, both refined and paged by the
same SSE metric. This is why the design is *compact*: one runtime, one payload
format, one material path.

> **ElevationGrid / heightfield tiles were considered and dropped.** A heightfield
> node (X3D `ElevationGrid`) or a GPU-tessellated height texture is a *surface
> representation you displace at runtime*; a 3D Tiles glTF payload is a *finished
> mesh baked at tile resolution*. They do not compose — you cannot GPU-tessellate a
> baked triangle mesh. Committing to 3D Tiles mesh tiles makes a runtime
> ElevationGrid redundant. Heightfields survive only as an **offline authoring
> input** (§3), baked away into glTF tiles before streaming, where a heightmap PNG
> or GIS DEM serves equally well.

### Standard tooling in, standard payloads out
- **Authoring/prep**: any DCC (Blender/Houdini) or GIS pipeline → 3D Tiles, via
  standard converters (Cesium ion, **py3dtiles**, QGIS, CesiumGS tools). Heightmaps
  and DEMs (SRTM/USGS) bake to surface tiles; modeled caves/arches bake to octree tiles.
- **Runtime**: `tileset.json` + glTF/`b3dm` payloads, rendered by the existing loader.
- **Vegetation placement**: standard glTF **`EXT_mesh_gpu_instancing`** (already
  supported, shipped in [INSTANCED-GEOMETRY.md](INSTANCED-GEOMETRY.md)).

**Bespoke surface area** shrinks to: the **3D Tiles runtime** (loader + traversal +
SSE refinement + async paging + LRU eviction), **geomorphing** to hide LOD pops
(§4), the **triplanar terrain material** shaders, and the **GPU grass** system.

---

## 2. Why baked mesh tiles (and what it costs)

How a surface tile becomes triangles at the right detail — the alternatives, and
why 3D Tiles' baked chunked-LOD is the right pick here, with eyes open to its costs.

| Approach | GPU need | CPU/frame | Big worlds | Caves? | Fits 3D Tiles |
|---|---|---|---|---|---|
| ROAM | none | **high** | yes | no | no (dynamic IBO) |
| Geometry clipmaps | GL 3.3 | low | yes | no | no (height-texture pipeline) |
| GPU tessellation | GL 4.0 | minimal | yes | no | no (needs a displaceable surface, not a baked mesh) |
| **Chunked-LOD baked mesh tiles** | GL 3.3 | low | yes | **yes — any mesh** | **yes — this *is* 3D Tiles** |

- **ROAM**: CPU per-frame triangle-tree split/merge — a non-starter in Python at game scale, and
  its dynamic index buffers defeat VBO caching. Historical interest only.
- **Geometry clipmaps / GPU tessellation**: both are *heightmap-texture* techniques with continuous
  LOD; both are heightfield-only and both need a surface you displace at runtime, which a baked glTF
  tile is not. They were the alternative architecture (rejected in favour of standards-native mesh tiles).
  GPU tessellation stays relevant to the engine, but for [GPU-NURBS-TESSELLATION.md](GPU-NURBS-TESSELLATION.md),
  not terrain.
- **Chunked-LOD baked mesh tiles** (the 3D Tiles model): static per-LOD glTF meshes selected by
  screen-space error, stitched with skirts. Meshes cache in the existing `arraygeometry` VBO layer;
  paging is per-tile; LOD selection is a cheap tree walk; and a tile can hold *any* mesh, so caves are
  free. **This is the chosen path.**

**The two costs we accept, and how we pay them:**

1. **Discrete LOD → popping.** Baked levels jump rather than blend. Paid with
   **geomorphing**: adjacent LODs carry a vertex correspondence (or morph targets)
   and the vertex shader lerps between them by an SSE-derived morph factor across a
   transition band, so the switch is invisible. SSE hysteresis + a small screen-space
   dither cross-fade back this up. (§4)
2. **Baked meshes are heavy** (VRAM/disk) versus a compact height texture. Paid with
   **mesh compression** — **Draco** (ties into [DRACO-COMPRESSION.md](DRACO-COMPRESSION.md))
   and/or `EXT_meshopt_compression` on the glTF payloads — plus a strict resident-tile
   memory budget with LRU eviction (§4). This is the standard 3D Tiles story.

---

## 3. Caves, fissures, overhangs — just octree tiles

A heightfield cannot express solid–air–solid in one column; 3D features need a **3D
field meshed to an arbitrary-topology surface**. In this architecture that surface
is *the same glTF-tile mechanism* as everything else — the field/meshing is an
**offline bake**, and the runtime never knows the difference.

Meshing algorithm choices for the bake tool:

| Algorithm | Seamless chunk LOD | Sharp features | Complexity |
|---|---|---|---|
| Marching Cubes | no | no | low |
| **Transvoxel** (Lengyel) | **yes** (transition cells) | no | medium |
| Dual Contouring | hard | **yes** (crisp edges) | high |
| SDF ray-march | n/a | yes | per-pixel; poor fit for a rasterizing scenegraph |

**Choice: Transvoxel** — built for chunked-LOD volumetric terrain, seamless across
LODs, static-mesh output → glTF. Dual Contouring is the upgrade path if
crevasse/fissure edges read too soft.

**Two supported inputs, both landing as glTF octree tiles:**
1. **Authored** — model caves/arches/overhangs in Blender/Houdini, export glTF, place in the
   tileset. Fully standard, zero engine work beyond the runtime that already renders glTF.
2. **Procedural** — a bake tool evaluates `heightfield_sdf − Σ cave_brushes` (CSG carves) and
   Transvoxel-meshes to glTF octree tiles, cached on disk (mirroring the `physics-cook`/glTF cache
   pattern). On the 3060 the SDF→mesh step can run in a **GL 4.3 compute shader** (precedent:
   [physics/glcompute.py](../OpenGLContext/physics/glcompute.py)), enabling future runtime
   carving/destruction; lower tiers bake on CPU at import.

Because caves are ordinary tiles, they inherit streaming, SSE-LOD, culling,
material, shadows, and collision with no special case.

---

## 4. The 3D Tiles runtime (the core deliverable)

New `loaders/tiles3d/` — the one substantial new subsystem. **Build on `py3dtiles`**
(OSGeo/BIMData) for the parts it already solves: the `tileset.json` data model,
lazy hierarchy browsing, tile-content (glTF/`b3dm`) extraction, and the **entire
bake/writer toolchain** (§7). Python has no mature *runtime* 3D Tiles renderer — the
production traversal loops are JS/C++ (**loaders.gl `Tileset3D`**, **cesium-native**)
— so the camera-driven traversal below is ours, but it is a *port of a well-specified
algorithm*, not a new design. **Target 3D Tiles 1.1** (glTF-native tile content →
straight into the existing loader); py3dtiles unwraps any 1.0 `b3dm` glTF.

- **Tileset load**: via `py3dtiles`, read `tileset.json` (lazily), build the bounding-volume
  hierarchy (box/region/sphere), read per-tile geometric error and refinement (`ADD`/`REPLACE`).
- **Traversal = the LOD *and* streaming engine.** Each frame, walk the BVH; convert each tile's
  geometric error → **screen-space error** against the live camera; **refine** into children while
  SSE > threshold, else render the tile. Frustum + distance cull reuse the machinery in
  [passes/instancing.py](../OpenGLContext/passes/instancing.py). Streaming is not a separate
  system — it is what this traversal *decides*: the wanted-tile set drives loads and evictions.
- **Hierarchical LOD (HLOD) — how large/distant objects (mountains) work.** A mountain is a
  large-extent, high **geometric-error** node whose payload is a **coarse decimated mesh of the
  whole feature, baked offline** (§3, §7). Distant → its SSE is small → traversal stops there and
  renders that one low-poly mesh. Approaching → SSE crosses threshold → traversal refines into
  children; **REPLACE** refinement swaps the coarse parent for finer children (**ADD** layers detail
  on). The runtime never *builds* a mountain LOD — it only *selects* among pre-baked ones. This is
  what lets a single low-poly tile stand in for an entire distant range.
- **Sparse, content-only tree — no air, no solid interior.** The BVH is not a dense voxel octree;
  nodes exist only where there is **surface geometry**, and subdivide only where there is detail.
  Empty air is never stored; the solid interior of rock is never stored; only the *skins* (ground
  surface, cave walls/floor/ceiling) are meshed into tiles. The dense voxel/SDF grid used to *find*
  a cave surface lives only transiently in the Transvoxel bake (§3); what reaches the runtime is just
  those surface meshes.
- **Streaming mechanics**: a **priority request queue** (nearer / higher-SSE first, cancelled when
  the camera moves on) feeds async background paging of glTF/`b3dm` payloads (Draco/meshopt decoded
  on load); a resident ring around the camera under a **hard VRAM/memory budget** with **LRU
  eviction**; preload of ancestors/siblings for smoothness. Tiles cache as `arraygeometry` VBOs.
- **Geomorphing**: vertex-shader lerp between a tile and its parent/child LOD across an SSE
  transition band (morph factor uniform), with SSE hysteresis + optional dither cross-fade, to kill
  popping (§2).
- **Material — triplanar PBR splatting**: surface *and* cave tiles shade through the existing PBR
  pass with **triplanar** projection (so vertical cave walls and overhangs texture without relying on
  baked UVs) and per-tile slope/height/biome splat weights; splat layers draw from
  [PBR-TEXTURE-LIBRARY.md](PBR-TEXTURE-LIBRARY.md) CC0 sets. Reuses **CSM shadows**
  ([SHADOW-MAPPING.md](SHADOW-MAPPING.md)) and **IBL** ([RUNTIME-IBL.md](RUNTIME-IBL.md)) unchanged.
- **Collision**: each resident tile emits its mesh as a physics static `trimesh` collider
  ([PHYSICS-COLLISION.md](PHYSICS-COLLISION.md)), so the character controller walks the surface *and
  through caves*; `suppressOverVoid` already covers fissure/hole edges.

**Why this wins:** standards-first (3D Tiles + glTF, tool-authorable), *compact*
(one runtime, one payload, one material), reuses the VBO cache / instancing cull /
CSM / IBL / PBR / physics-trimesh systems, scales to real game worlds under a
bounded resident set + hard memory budget, and treats caves as ordinary tiles.

### Node, components & threading

A **`TilesTerrain`** grouping node (`scenegraph/tilesterrain.py`) owns the runtime
and is drawn by the flat pass like any node; its `render(mode)` runs one traversal
tick and draws the selected tiles. It reads camera world position, frustum, and
viewport from `mode.matrix`/`mode.projection` (the pass already has the camera and
frustum-culls for instancing), sidestepping the "no pointer to the viewpoint"
limitation noted in [scenegraph/lod.py](../OpenGLContext/scenegraph/lod.py).

| Module (`loaders/tiles3d/` unless noted) | Responsibility | Thread |
|---|---|---|
| `scenegraph/tilesterrain.py` — `TilesTerrain` | owns runtime; tick + draw; registers tile physics colliders | GL/main |
| `tileset.py` — `Tileset`, `Tile` | BVH, bounding volume, `geometricError`, `refine` (ADD/REPLACE), content URI — **on py3dtiles readers** | — |
| `screenspaceerror.py` | geometricError → pixel error for the live camera/viewport | GL/main |
| `traversal.py` — `TilesetTraversal` | BVH walk → `SelectionResult(render_set, want_set, evictable)` | GL/main |
| `residency.py` | LRU cache, memory-budget accounting, tile lifecycle | GL/main |
| `loadmanager.py` | priority queue + worker pool: fetch → py3dtiles extract → glTF parse → Draco/meshopt decode → numpy | **workers** |
| `upload.py` | drain ready payloads → `arraygeometry`/`PBRMesh` VBOs, **bounded N/frame** | GL/main |

**Tile lifecycle:** `UNLOADED → LOADING → READY(cpu) → RENDERABLE(vbo) → EVICTED`
(only `RENDERABLE` draws). **Per-frame tick:** (1) camera+frustum from `mode`; (2)
`traversal.select` → `render_set`/`want_set`/`evictable`; (3) diff `want_set` vs
residency → enqueue new wants (priority by SSE/distance), cancel departed requests;
(4) `upload.drain(budget)` moves a bounded number `READY`→`RENDERABLE` (the only
per-frame GL upload, capped to avoid hitches); (5) `residency.enforce_budget()`
LRU-evicts past the memory cap, never evicting a tile serving as parent-fallback;
(6) draw `render_set`, substituting the nearest resident ancestor for any
not-yet-`RENDERABLE` tile (coarse fallback, no hole); (7) register/drop physics
`trimesh` colliders for newly-resident/evicted tiles. **Threading:** traversal +
draw + VBO upload stay on the GL thread (single-context upload avoids the
context-tracking pitfalls in CLAUDE.md); workers do only IO + parse + decode and
return numpy arrays through a ready queue.

### Loading is speculative, not reactive

Purely reactive loading (fetch a block only on entering it) guarantees pop-in and
hitching — a load is fetch + decode + VBO upload, i.e. many ms to seconds. The
runtime prefetches in three layers:

1. **Anticipatory SSE (inherent):** distance-driven SSE crosses the refine threshold
   *as the camera approaches* a feature, so its finer children load while it is still
   ahead — detail for where you are *getting close to*, not where you already are.
2. **Prefetch margin (explicit):** `want_set` = the strictly-visible set grown by one
   finer SSE level, a frustum skirt (covers *turning*), and tiles along the camera
   **velocity vector** (covers *walking forward*). This is what makes it predictive.
3. **Parent retention / fallback:** the coarse ancestor stays resident until the finer
   child is `RENDERABLE`, so the world **sharpens in** rather than popping or holing.

The amount of speculation is a per-tier budget knob (prefetch margin, resident-ring
radius, SSE bias, velocity lookahead), hard-capped by the memory budget — Tier A
prefetches aggressively, Tier C keeps a tight ring.

---

## 5. Vegetation

Scattered **per tile** so it pages with the terrain; placements snap to the tile
mesh, so they work on cave floors and ledges, not just a height surface. Density
and species come from the tile control map or authored `EXT_mesh_gpu_instancing`
placements.

> **VolumetricTree is explicitly not used.** Ray-marching a 3D voxel canopy per
> tree is far too slow for a populated world. Trees are ordinary instanced glTF
> meshes with an impostor far-LOD.

### 5.1 Trees, brush, rocks, ferns (instanced meshes)
- Instanced **glTF** assets via the existing engine ([passes/instancing.py](../OpenGLContext/passes/instancing.py)):
  `glDrawElementsInstanced`, per-instance transform + material, cluster-culled, already shadow-casting
  and pickable. Placement via standard glTF **`EXT_mesh_gpu_instancing`** (supported).
- **LOD chain per asset:** high mesh → low mesh → **octahedral impostor** (a small atlas of
  pre-rendered views, baked at load into a texture array, drawn as an instanced billboard picking the
  nearest view) → cull. One draw renders a whole hillside of trees. Tier C uses a single flat billboard.

### 5.2 Grass & flowers (highest instance count)
- **Tier A:** GPU-driven. A **compute shader** reads the tile density map + position-hashed jitter,
  appends blade/flower instances into a per-tile buffer (frustum + distance culled), drawn with
  **`glDrawElementsIndirect`** — no CPU per-blade cost. Blades = a few instanced cards/strips;
  flowers = instanced cards. **Wind** = vertex-shader sway from a scrolling flow texture. Distance
  bands: 3D blades near → cross-quads mid → ground detail-texture blend far.
- **Tier B (iGPU):** same instancing, scatter precomputed at tile load into a static buffer (no
  compute), lower density, shorter fade.
- **Tier C:** no per-blade grass — a ground detail texture plus a few near billboard tufts.

### 5.3 Keeping vegetation cheap & robust
- **Per-tile buffers + indirect draw** → vegetation count bounded by the resident tile ring, not the world.
- **Instancing + impostors** collapse thousands of plants into a handful of draws.
- Vegetation casts into **near CSM cascades only**; grass is received-only (a standard, unnoticeable economy).
- **Position-seeded deterministic** scatter (no per-frame RNG) → reproducible for visual-regression capture.

---

## 6. Hardware tiers & fallbacks

Capabilities detected once at startup (GL version + extension probe), as the
instancing/compute paths are gated today. A `TerrainQuality` object selects paths
and budgets; `OPENGLCONTEXT_TERRAIN_TIER=a|b|c` forces a tier for testing/regression
capture. The **surface path is identical across tiers** (baked mesh tiles render on
GL 3.3); tiers differ in budgets and in the compute-driven extras. Fallback is by
**capability**, not vendor name.

| | **Tier A — RTX 3060 (primary)** | **Tier B — modern iGPU** | **Tier C — GL 3.3 / software** |
|---|---|---|---|
| Surface tiles | 3D Tiles mesh LOD + geomorph | mesh LOD + geomorph | mesh LOD (geomorph optional) |
| SSE threshold / draw distance | low SSE, large | medium | high SSE, small |
| Cave meshing (offline) | compute (live-capable) | CPU bake, disk-cached | CPU bake, disk-cached |
| Grass/flowers | compute scatter + indirect | precomputed instances | detail texture + few billboards |
| Trees/brush | mesh LOD + impostors | mesh LOD + impostors | single billboards |
| Shadows | full CSM | fewer cascades | near cascade only |
| Splatting | triplanar PBR | triplanar PBR | 2-layer, cheaper shading |
| Mesh compression | Draco/meshopt | Draco/meshopt | Draco/meshopt |

Tier C (llvmpipe / GL 3.3) is the true floor and drops every 4.x-only path
(compute grass, compute cave meshing); it still streams and renders the same baked
mesh tiles, just with tighter budgets.

---

## 7. Integration with the scenegraph

- **3D Tiles runtime** in `loaders/tiles3d/`: **`py3dtiles` supplies the readers/writers** (tileset
  data model, lazy hierarchy, glTF/`b3dm` content extraction); *we* add the runtime the library lacks —
  BVH traversal + SSE refinement + async paging + LRU eviction + geomorph — feeding tiles as scenegraph
  nodes, with glTF payloads going through the existing loader. No third-party runtime *renderer* is
  reusable (they are JS/C++); we port the loaders.gl/cesium-native traversal algorithm. A
  `Tileset`/`Terrain` grouping node in `scenegraph/` owns the runtime and renders through the flat passes
  like any node.
- **Terrain shaders** as a new `terrain_*` set in `shaders/` (triplanar-splat fragment + geomorph vertex
  path), sharing the `_brdf_inc`/`_shadow_inc`/`_lights_inc` includes so lighting matches the rest of the scene.
- **Vegetation** scatter/impostor code beside [passes/instancing.py](../OpenGLContext/passes/instancing.py).
- **Bake tools** in `bin/` built on **`py3dtiles`** as the tileset writer (heightmap/DEM → 3D Tiles
  surface tiles; SDF → Transvoxel glTF octree tiles; impostor-atlas bake), mirroring the existing
  `physics-cook`/glTF cache pattern. Prefer standard external converters (py3dtiles CLI, py3dtilers,
  Cesium tooling) where they already do the job; our bake tools fill only the terrain/cave/impostor gaps.

---

## 8. Code references & licensing

No third-party 3D Tiles *runtime renderer* is reusable as-is (they target other
engines), but the production-grade implementations are **permissively licensed** and
usable as **code references / partial ports with acknowledgment**. OpenGLContext is
**BSD-3-Clause**, and `license.txt` already carries an "Exceptions" section
acknowledging incorporated third-party code (OBJ loader, NeHe, SGI redbook,
PyOpenGL) — the established home for these attributions.

| Reference | License | Role |
|---|---|---|
| **NASA-AMMOS/3DTilesRendererJS** (three.js) | Apache 2.0 (© Caltech/JPL) | **Primary structural model** — engine-agnostic runtime attached to a foreign scene graph, mirroring our situation |
| **cesium-native** (C++) | Apache 2.0 | Authority on SSE traversal, async paging, LRU (powers Cesium for Unreal/Unity/Omniverse) |
| **CesiumJS** | Apache 2.0 | Canonical algorithm, more readable than the C++ |
| **loaders.gl** `@loaders.gl/tiles` | MIT (some modules ISC/BSD/Apache) | Most-permissive traversal-loop / data-structure reference |
| **py3dtiles** | Apache 2.0 (verify at pin) | Reader/writer + bake dependency (§4, §7) |

**Obligations** (all compatible with our BSD-3-Clause): retain copyright + license
notice for any copied MIT/BSD code; for Apache 2.0, preserve the NOTICE, state
modifications, and carry the license (Apache 2.0's patent grant is a plus).
Workflow: read the OGC spec + the reference, implement, and **cite** — add each
referenced project to `license.txt`'s Exceptions section, and mark any ported block
with a one-line module pointer (a legal attribution, not docstring "history").

## 9. Phasing

Each phase is independently useful, testable (TDD + a per-tier demo doubling as a
visual-regression capture, `OPENGLCONTEXT_TERRAIN_TIER` pinned), and shippable.

1. **3D Tiles runtime — static.** `tileset.json` reader (**py3dtiles**) + our BVH traversal + SSE LOD +
   async streaming + LRU eviction, rendering glTF mesh tiles (uses the existing glTF loader). PBR + CSM + triplanar splat;
   physics trimesh colliders per tile. Skirts for cracks. *A walkable, streamed large-mesh world from
   standard tooling — no 4.x dependency.*
2. **Geomorphing + compression.** Vertex-shader LOD morph + SSE hysteresis to kill popping; Draco/meshopt
   payload decode ([DRACO-COMPRESSION.md](DRACO-COMPRESSION.md)) + memory-budget tuning. *Smooth,
   VRAM-bounded streaming.*
3. **Caves / volumetric tiles.** glTF octree tiles: authored first, then the Transvoxel bake tool
   (CPU+cache, then compute) with CSG cave brushes. *Caves, fissures, overhangs; character controller
   walks them.*
4. **Vegetation — instanced meshes.** glTF instancing (`EXT_mesh_gpu_instancing`) + mesh LOD + octahedral
   impostor baking on the existing engine.
5. **Vegetation — GPU grass.** Compute scatter + indirect draw, wind, distance bands; precomputed fallback.
6. **Polish.** Biome/splat authoring, streaming-budget + memory-cap tuning, perf pass, per-tier
   reference-image regression, an interactive game-like demo.

---

## 10. Open questions / future

- **Popping vs. cost:** geomorphing on baked LODs adds vertex-correspondence data; if authoring pipelines
  can't produce it, fall back to a screen-space dither cross-fade between LODs.
- **Bake-time decimation quality:** because HLOD LODs are baked offline, the **mesh-simplifier
  quality is decisive** for how coarse tiles (distant mountains) read and how cleanly they geomorph —
  a weak simplifier shows up as silhouette collapse and morph swimming at range. This is a real
  dependency on the bake toolchain (py3dtiles mesh tiling and/or a simplifier such as
  meshoptimizer); evaluate simplifier options and whether they can emit the vertex-correspondence
  data geomorphing needs (§2). Folds into the Phase 2 geomorph/compression work.
- **Sharp cave features:** start with Transvoxel (seamless LOD); revisit Dual Contouring per-tile if
  crevasse edges read too soft.
- **Runtime carving/destruction:** the SDF + compute-mesh path admits live edits and re-baked tiles; out
  of scope for v1 but the architecture leaves the door open.
- **Geo-referenced DEM ingest:** GIS → 3D Tiles pipelines (QGIS, py3dtiles) for real-world terrain, if wanted.
- **Any-area DEM → forested biome, as a pipeline** *(asked for 2026-08-03; not started)*. Today the
  forest demo ships one baked heightmap of one place. Wanted: name an area, have the elevation
  fetched from an online service in blocks (~200 m each) and chained into a 4 km × 4 km world or
  larger, then scatter a biome onto it — the species mix, the ground splat and the grass the demo
  already derives from slope, elevation and a control map, applied to whatever came back. The
  scatter, the splat and the walking are done and are area-independent
  (`openglcontext_forest_demo.scene.build_forest_scene` takes a `ForestConfig` and a height field);
  what is missing is the fetch, the block chaining and seamless edges between blocks, and a control
  map derived from the data rather than authored. Overlaps the 3D-Tiles DEM baker (`loaders/tiles3d/dem.py`),
  which already tiles a heightmap — the open question is whether an area this size wants the streamed
  tile path or stays one `HeightField` per block.
- **Water:** a **dedicated water shader on a normal transparent surface**, not OIT — Gerstner/FFT
  waves, planar or screen-space reflection, depth-buffer refraction + absorption/fog, shoreline foam
  against terrain height (ties into the "Procedural backgrounds / environment" item). Ordinary
  back-to-front blending (or depth-write + refraction) sorts a single water layer fine.
  [ORDER-INDEPENDENT-TRANSPARENCY.md](ORDER-INDEPENDENT-TRANSPARENCY.md) is **not** required for water;
  it is only an *optional* polish for genuinely stacked transparent overdraw (dense alpha-blended
  foliage/grass billboards, layered canyon mist), and even there it is a nice-to-have.

---

## 11. Deferred real-time draw-cost optimizations (authored path)

The forest-demo authored-terrain path (`scenegraph/terrain` `SplatTerrain`/`HeightField`,
instanced `scenegraph/vegetation` `clumps`/`billboards`/`nearmesh`, `move/terrainwalk`)
got a 4K performance pass. Two levers **shipped**: grass-clump ribbon **decimation**
(`load_clump_glb(length_samples=…)` edge-collapses each blade to N cross-rings, forest-demo
default 1560→520 tris/clump) and **tree-impostor view-cone culling** (`run.py:_stream_impostors`
keeps a forward cone + near disc, dropping ~78% of impostor cards that fall behind/beside the
camera), plus **idle event-driven redraw** (`TerrainWalkMixin.OnIdle` redraws only when the
view pose changes, so a parked camera stops spinning the GPU). *(2026-08-03: the pose gate now
covers the free-fly camera only. With `setupPhysics` enabled the avatar is a simulation — gravity
moves it whether or not anyone touched a key — so a walking context is stepped and drawn every
frame, as twitch and `oglc-view` are.)* Measured at the dev container's
compositor-clamped 435² (true 4K fill is not measurable in-container — the PBR scene FBO follows
the real framebuffer, not a forced viewport): median 13.8→12.3 ms, p95 19.4→16.3 ms while
walking. On real hardware the user measures **~45–50 fps at 4K** (fill-bound), below the
interactivity bar. Three further levers remain, deferred:

3. **Forward-cone cull the grass follow-discs.** `world_grid_scatter`
   (`scenegraph/vegetation/grid.py`) still scatters the whole disc, including cells behind the
   camera (~50% waste on the heaviest node, the near clumps). Grass sits on the ground and the
   eye is ~1.7 m up, so grass behind/beside the view is never visible — culling it to the forward
   view cone (the trick already applied to impostors) is lossless. Add an optional forward
   `(fx, fz)` + cone half-angle to `world_grid_scatter`, restreamed on move-or-turn via the
   existing `add_stream(step, fn, turn=)`. Biggest remaining vegetation win; use a generous margin
   and restream on turn so nothing pops at the cone edge.
4. **Backface-cull solid tree trunks.** `nearmesh.py` renders every part with
   `glDisable(GL_CULL_FACE)` (needed for the flat foliage cards), so solid trunks draw
   double-sided — ~2× their trunk fragment cost. Cull the opaque part (`"o"`) while keeping the
   foliage part (`"b"`) double-sided. Small win, but needs a per-species winding check first —
   some glTF/npz exports are CW, and culling the wrong face makes a trunk vanish from one side;
   verify each species in a capture before shipping.
5. **Depth pre-pass / front-to-back opaque order.** All vegetation is opaque alpha-cutout with
   `discard`, which defeats early-Z — every covered fragment runs the full shader before being
   killed, the classic fill-bound-at-4K cost. A cheap depth-only prime (or at least drawing
   terrain first, front-to-back) lets hi-Z reject most overdraw. Pairs naturally with terrain
   LOD: `SplatTerrain` currently draws all ~524k tris through the full splat shader every frame
   with no distance LOD, so distant tiles pay the same fragment cost as near ones.
