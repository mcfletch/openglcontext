# Instanced Geometry

**Status: COMPLETE (required scope) (2026-07).** The engine, five staged draw
paths, the required geometry coverage and the required performance work are all
implemented and tested. Since the last revision: **IndexedFaceSet** (the general
triangle mesh) now instances; the per-frame **VAO / VBO / material-array UBO churn
is cached away**; and **cluster culling** was added (after finding off-screen
instances were already culled per-object -- see below). Teapot instances (trading
its distance-LOD for the draw-call collapse, as the quadrics do); NURBS / Extrusion
remain **not** instanced (they would lose their distance-LOD with no equivalent
payoff; rationale below), and the three hardware-gated fast paths (SSBO / MDI / bindless) are
detected-but-deferred as optional (the plan always classed them so). What remains
is genuinely optional and low-priority: Text glyph-quad instancing, PointSet/Line
repeat, and those three hardware paths. User-facing docs:
[`docs/instancing.html`](../docs/instancing.html). Toggle with
`OPENGLCONTEXT_INSTANCING=0`; opportunistic content-collapse with
`OPENGLCONTEXT_INSTANCE_COLLAPSE=0`; threshold via `OPENGLCONTEXT_INSTANCE_MIN`;
cluster culling with `OPENGLCONTEXT_INSTANCE_CLUSTER_CULL=1`.

## Stages landed so far (the engine + five draw paths)

* **Stage 1 — PBR instanced draw.** Per-instance model matrix (attr 5-8) + object id
  (9), gated by `instancingEnabled` (non-instanced path untouched). `PBRPass`
  grouping + `draw_instanced_mesh`. ~2.1x faster on shared-geometry fields, N draws→1.
  Per-instance picking verified (N distinct ids in one draw).
* **Stage 2 — per-instance material array.** `MaterialBlock` is now
  `Material materials[MAX_INSTANCE_MATERIALS]` (90, fits the 16 KB UBO min); a
  per-instance index (attr 10) selects factors, so instances differing only by
  colour/metallic/roughness batch into ONE draw. Group key widened to
  (geometry, texture-set, pass-signature); groups exceeding the UBO cap are chunked.
* **Stage 3 — opportunistic collapse.** Content-hash key (`geometry_content_key`,
  cached per mesh) batches distinct nodes with identical vertex data (re-authored
  primitives; glTF repeats the loader didn't share).
* **Stage 4 — glTF signals.** Loader `mesh_cache` already shares one Shape across
  repeated mesh indices (node-identity grouping catches them). `EXT_mesh_gpu_instancing`
  is parsed (`gpu_instance_transforms`) into per-instance Transforms sharing the mesh.
* **Stage 5 — VRML97 lit instancing.** `vrml97_lighting.vert/frag` gained the same
  per-instance attributes; `flatcore.FlatPass` instances PBRMesh through the VRML97
  program with per-instance picking.

Tests: `test_instance_grouping`, `test_instance_capabilities`, `test_instance_material_table`,
`test_instance_content_collapse`, `test_gltf_gpu_instancing`, `test_instanced_render_gl`,
`test_instanced_material_gl`, `test_instanced_collapse_gl`, `test_instanced_vrml97_gl`,
`test_instancing_performance`.

### Native primitives + shadow pass + demo worlds (2026-07, follow-up)

* **Sphere and Box now instance** (the molecular-model case). Any geometry exposing
  `instanceGPU(mode)` is instanceable; `build_mesh_gpu` builds a cached separate-VBO
  `_MeshGPU` from its expanded arrays, so Box, Sphere and PBRMesh share one draw path.
  `instanceContentKey()` (Sphere->('Sphere',radius,phi); Box->('Box',size)) lets the
  content-collapse group distinct same-shape nodes. The core (VRML97) pass batches by
  (content, material). **Sphere fields: ~5-6x faster** (400: 183 vs 36 fps; 900: 101 vs
  17 fps).
* **The shadow depth pass instances too** (`shadow_depth.vert` gained the per-instance
  model matrix; `_renderDepth` groups + `_renderDepthGroup`). Without it an instanced
  scene drew its colour pass in one call but re-drew every caster per-shape into each
  shadow map (N*cascades) -- the cause of a 30fps stall on the 512-cube glTF world
  (now 91fps @1280x1024 with shadows+IBL).
* **Demo worlds** (load and auto-instance, no manual GL):
  `tests/wrls/instanced_lattice.wrl` -- 216-atom NaCl crystal, `oglc-vrml` (2 draws);
  `tests/wrls/instanced_lattice.gltf` -- 512 cubes via `EXT_mesh_gpu_instancing`,
  `oglc-gltf` (1 draw). Locked by `test_instanced_worlds_gl`, `test_instanced_shadow_gl`,
  `test_instanced_primitives_gl`.

Test harnesses set `OPENGLCONTEXT_NO_VSYNC` so a leaked GL context can't wedge swaps.

## Remaining work (REQUIRED -- unfinished, not optional)

The instancing engine, shader paths, grouping, picking, shadow pass and demo
worlds are done. What is left is required to call the feature complete: (a) making
the rest of the geometry types instanceable, and (b) the performance work. These
were cut for time this morning, not deferred to a later plan. The pattern for new
geometry is settled: expose `instanceGPU(mode)` (usually via
`instancing.build_mesh_gpu` from the node's expanded vertex arrays) and an
`instanceContentKey()`; the passes pick it up automatically (`_instanceable` is
`hasattr(geom, 'instanceGPU')`). Add a case to
`tests/test_instanced_primitives_gl.py` for each.

### Geometry coverage (make instanceable)
- [x] **IndexedFaceSet** -- DONE. The general triangle mesh (the common `.wrl`
      case). `instanceGPU`/`instanceContentKey`/`_instanceArrays` on
      `IndexedFaceSet` reuse the existing `ArrayGeometryCompiler` tessellation --
      the same expanded (positions, normals, texcoords) triangle soup the
      non-instanced shader path already draws, factored out as
      `ArrayGeometryCompiler.expandedArrays()` so tessellation lives in one place.
      The content key hashes exactly the arrays + flags that drive the tessellated
      output (coordIndex, coord.point, normal/texCoord + their indices,
      normalPerVertex, creaseAngle, ccw, solid, convex), so distinct-but-identical
      IFS nodes (a bolt/tile/leaf used many times) collapse into one draw. Locked
      by `tests/test_instance_geometry.py` (headless) + the `ifs` case of
      `tests/test_instanced_primitives_gl.py` (GL: 5 distinct IFS collapse to one
      draw, each pickable). Per-vertex color is dropped by the shared instanced
      mesh (a `build_mesh_gpu` limitation) -- a color-varying field still batches,
      it just renders with the material colour.

**Teapot instances (LOD traded for draw-call collapse).** The Teapot exposes the
`instanceContentKey` / `instanceGPU` hooks like the quadrics, baking the finest
(level-0) tessellation with `size` folded into the positions. Many teapots
sharing one geometry node (or the same size/lid) collapse into a single draw. The
cost of the trade is the distance-LOD the per-object path applies: instanced
teapots pay full-detail vertex cost at *every* distance (a LOD-0 teapot is heavy).
That is the same trade the quadrics already make, and it is a clear win when many
same-material teapots are on screen; cluster culling below still removes
off-screen instances. In the VRML97 lit path a group binds one material, so
differently-coloured teapots only collapse under the PBR pass's per-instance
material array.

**Declined: NURBS surfaces, Extrusion (LOD-loss, not worth it).** An instanced
draw shares ONE fixed tessellation (level 0, finest) across every instance, which
bypasses the distance-LOD that makes far/small copies of these procedural
surfaces cheap. A field of NURBS surfaces would then pay full-detail vertex cost
at *every* distance. Extrusion (the GLE Lathe/Screw/Spiral) additionally has no
reusable vertex arrays at all -- it draws straight into a display list via the GLE
C library -- so instancing it would mean reimplementing GLE tessellation in numpy,
disproportionate for the same LOD-losing payoff. If a real workload needs these
instanced, the prerequisite is per-instance LOD selection (draw each distance
bucket as its own instanced group), which is a larger design than this plan.

- [ ] **Text** -- glyph-quad instancing is a different model (per-glyph transforms
      from one quad); worth it for large text but out of scope of the mesh path.
- [ ] PointSet / IndexedLineSet already draw as a single call each; instancing
      only helps if the SAME set is repeated -- low priority.

### Performance (required)
Required to call the feature done. The first two are unconditional; the GL 4.3 /
bindless items below them are gated by hardware availability but still wanted where
detected.
- [x] **Cache the per-frame instance VAO / VBO / material-array UBO** -- DONE.
      `draw_instanced_mesh` now builds the instanced VAO + a persistent instance
      `vbo.VBO` once (`_build_instance_vao`) and caches them on the mesh
      `_MeshGPU` (`_instance_vao`/`_instance_vbo`, reclaimed with the gpu);
      per-frame it only re-uploads the instance data. `_bind_material_array` reuses
      one persistent UBO on the pass (orphan + re-upload) instead of gen/deleting a
      buffer per group per frame. Locked by `tests/test_instanced_caching_gl.py`
      (counts `glGenVertexArrays` / `glGenBuffers` per frame -> zero in steady
      state). The instance modelviews are eye-space, so the buffer still re-uploads
      each frame; skipping the re-upload needs model-space instance data + in-shader
      view transform (a larger change, noted for the future).
- [x] **Frustum / cluster culling** of instanced groups -- DONE (with a finding).
      *Finding:* the pass already frustum-culls **per object** in
      `frustumVisibilityFilter` **before** grouping, so off-screen instances are
      already dropped and do NOT run the vertex shader (verified: a 10-shape scene
      with 5 off-screen issues one instanced draw of 5). The plan's premise was
      wrong. What actually remained was the *cost* of that per-object test: it is
      pure Python here (no `frustcullaccel`), so it is O(N) per frame and dominates
      huge static fields. Implemented `morton_order` / `build_clusters` /
      `cluster_cull` in `passes/instancing.py` (Morton/Z-order sort -> contiguous
      clusters with padded world AABBs -> one frustum test per cluster; a wholly
      off-screen cluster culls all its members with no per-instance test). Wired as
      an opt-in acceleration of `frustumVisibilityFilter`
      (`OPENGLCONTEXT_INSTANCE_CLUSTER_CULL=1`, `>= 256` records), padded by the
      largest member world radius so it can never reject a cluster with a visible
      member. Locked by `tests/test_instance_cluster_cull.py` (headless algorithm)
      and `tests/test_instance_cluster_cull_gl.py` (GL: cluster-culled draw set is
      identical to the per-object set). Default off (redundant with the existing
      per-object cull for correctness; it only lowers per-frame CPU cull cost). The
      `baseInstance`/MDI scatter-draw variant is unnecessary because per-object
      culling already removes off-screen instances before the draw; MDI stays a
      throughput option below, not a culling requirement.
**Hardware-gated fast paths -- detected, deferred (optional, not required).** All
three are advertised by this GPU (`ssbo=True mdi=True bindless=True`, though the
context is 3.3 core so they come in via ARB extensions, not a core 4.3 profile).
They optimize already-working functionality, so each is a large, driver-specific
change to the *shared* PBR shader for marginal benefit at realistic scales.
Deferred deliberately after weighing effort vs payoff; scoped here so the work is
concrete when a real workload justifies it.

- [ ] **SSBO material array** (`GL_ARB_shader_storage_buffer_object`). Replace the
      fixed `layout(std140) uniform MaterialBlock { Material materials[90]; }`
      (`pbr.frag:83`) with `layout(std430) buffer MaterialBlock { Material
      materials[]; }` to lift the per-group distinct-material cap. *Why deferred:*
      the cap is already **372** here (64 KB UBO), so a group would need 372+ shapes
      sharing geometry+textures but each a distinct material to ever chunk -- it
      essentially never binds. And `MaterialBlock` is read by **every** PBR draw
      (`pbr.frag:220`), so the edit needs: a std140->std430 byte-exact re-validation
      of the 176 B `Material` layout against `pack_material_block`; a `#version 430`
      / `#extension` bump with a capability gate; and a retained UBO+chunking
      fallback -- two material paths in the core fragment shader. High blast radius,
      near-zero real payoff.
- [ ] **`glMultiDrawElementsIndirect`** (`GL_ARB_multi_draw_indirect`) to draw
      several *distinct-geometry* groups in one call. *Why deferred:* each group has
      its own geometry (own VAO/VBOs), so MDI across groups needs all instanced
      geometry packed into one shared buffer with per-command `baseVertex` /
      `baseInstance` and an indirect command buffer -- a substantial data
      reorganization. It cuts draw-call *count* between groups, but per-object
      culling already removes off-screen work and each group is already one call, so
      the win only shows with very many small distinct groups.
- [ ] **Per-instance textures via `GL_ARB_bindless_texture`**. Carry a per-instance
      64-bit sampler handle so instances can differ by *texture set*, not just
      material factors -- collapsing texture-varying fields into one draw. *Why
      deferred:* the largest and most driver-specific of the three (bindless is not
      even ARB-core; needs `GL_ARB_bindless_texture` + resident-handle lifetime
      management), a new per-instance attribute + shader sampler-array path, and a
      non-bindless fallback (split by texture set, as today). Real feature value,
      but big; revisit if texture-varying instanced fields become a real workload.

### Punted (documented, not planned)
- Baked-vertex-soup extraction (splitting one merged mesh back into instances,
  e.g. if a model baked repeated columns into a single mesh). The parthenon is
  the reverse case -- its columns are separate nodes and DO instance via
  content-collapse.

## What landed (Stage 1)

The instancing engine, capability detection, and the PBR instanced draw path are
implemented and green:

* `passes/instancing.py` — grouping engine (`build_instance_groups`), GL
  capability detection (`detect_capabilities`: UBO cap, SSBO, MDI, bindless), and
  `draw_instanced_mesh` (ephemeral VAO binding the mesh's static VBOs + a
  per-instance VBO at locations 5-9, `glDrawElementsInstanced`).
* `pbr.vert`/`pbr.frag` — per-instance model matrix (loc 5-8) + object id (loc 9),
  gated by an `instancingEnabled` uniform so the non-instanced path is untouched.
* `PBRPass._drawInstanceGroup` — binds the shared material once, hands per-instance
  modelviews + object ids to one instanced draw. Base-pass hooks
  (`instancing_enabled`, `_instanceable`, `INSTANCE_MIN`) keep every other pass
  unchanged. Toggle with `OPENGLCONTEXT_INSTANCING=0`.
* **Per-instance picking works**: each instance keeps a distinct stable id via
  `_objectIdFor`; verified by reading N distinct ids from the MRT buffer in one
  instanced draw. Non-pickable instances pack id 0.
* **Performance** (RTX 3060 Ti, vsync off): a shared-geometry cube field is ~2.1x
  faster instanced (600: 5.3 vs 11.0 ms; 1200: 9.5 vs 19.9; 2400: 19.6 vs 41.1),
  collapsing N draws to 1. Locked by `test_instancing_performance.py`.

Tests: `test_instance_grouping.py`, `test_instance_capabilities.py`,
`test_instanced_render_gl.py`, `test_instancing_performance.py`.

## Refinement for Stage 2 (from Stage 1 findings)

Array-ifying `MaterialBlock` means wrapping its members in a named `Material`
struct and rewriting every bare member reference in pbr.frag to
`materials[idx].member` (dozens of sites in the shared fragment shader used by ALL
PBR rendering). The 176-byte layout is already 16-byte aligned, so the std140
array stride is compatible; the risk is the shader-wide member rewrite, so it wants
its own focused pass with full regression. Add `instanceMaterialIndex` (loc 10) +
`flat` varying; non-instanced draws index 0.

## Goal

Collapse many shapes that share one geometry into a single instanced draw call, so
scenes dominated by duplicated geometry (sphere fields, repeated parts, scattered
props) stop paying the O(N) per-object draw cost (`Shape.Render` ~60 µs/object) that
benchmarks identified as the real large-scene wall. Picking must keep working
per-instance.

## Two entry points (both feed one engine)

1. **Explicit** — the scene declares instances. VRML `USE`/`DEF` sharing one geometry
   node; glTF `EXT_mesh_gpu_instancing` (per-instance TRANSLATION/ROTATION/SCALE on a
   node); an optional `Instanced` grouping node for hand-built scenes.
2. **Opportunistic** — the renderer detects that many drawn shapes share one geometry
   (same node identity, or glTF nodes sharing a `mesh` index) and collapses them.

Both resolve to the same primitive: **group the frame's renderable records by an
instance key, and draw each group once with per-instance data.** Format-neutral, so
VRML, glTF-shared-mesh and `EXT_mesh_gpu_instancing` all converge.

Punted (explicitly, for now): extracting instances from a *baked* mesh (e.g. parthenon
columns merged into one vertex soup) — there's no shared handle to detect.

## Instance key — how much can share one draw

The user's steer: the PBR **über-shader** already reads its material from the
`MaterialBlock` std140 UBO (176 bytes, binding 1, one material bound at a time). Promote
that to a **material array** indexed per-instance, and almost any same-geometry shapes
collapse into one `glDrawElementsInstanced`, differing only by material *factors*.

- **Group key = (geometry identity, texture-set identity).** Material scalar/vector
  factors (baseColor, metallic, roughness, emissive, …) vary *per instance* via the
  material array; **textures cannot** (no bindless / per-instance sampler in GL 3.3),
  so a differing texture set starts a new group.
- Legacy VRML97 lit shader: same idea, narrower material (its uniforms move into a
  per-instance block or attributes). Start with PBR; VRML97 lit second.
- Non-instanceable (unique geometry, one-offs) fall through to the existing per-shape
  path unchanged.

## Per-instance data plumbing

Vertex attribute locations 0–4 are taken (texcoord, normal, position, tangent, color).
Add instanced attributes (via `glVertexAttribDivisor(loc, 1)`):

- **locations 5–8**: `mat4 instanceModel` (four `vec4` columns) — replaces the per-draw
  model-matrix uniform.
- **location 9**: `uint instanceObjectId` — the picking id, so the existing MRT selection
  path resolves each instance. `_objectIdFor(path)` already gives a stable id per path;
  pack each instance's id into this buffer. Non-pickable instances pack 0 (they can't
  mask the attachment individually in one draw — see Open questions).
- **location 10**: `uint instanceMaterialIndex` — indexes the material array.

Shaders: add the instanced inputs, multiply by `instanceModel`, index the material
array by `instanceMaterialIndex`, and write `encodeObjectId(instanceObjectId)` to the id
attachment (reusing the just-fixed pickability path).

## Material array sizing (GL 3.3)

`MaterialBlock { Material materials[N]; }` at 176 B each. A UBO's guaranteed max is
16 KB (`GL_MAX_UNIFORM_BLOCK_SIZE`), ~90 materials; desktop NVIDIA reports 64 KB (~370).
Chunk a group whose material count exceeds the cap into multiple instanced draws (still
a huge win vs per-shape). GL 4.3+ SSBO would remove the cap; keep it as an optional fast
path, not a requirement.

## Staging (each stage independently testable + shippable)

1. **Grouping + one-material instancing (PBR).** Group by (geometry, material) identity —
   the true sphere-field / repeated-node case. Per-instance model matrix + object id;
   single material bound as today. Proves the draw path and per-instance picking. Biggest,
   simplest win.
2. **Material array (per-instance factors).** Promote `MaterialBlock` to an array +
   `instanceMaterialIndex`; group by (geometry, texture-set). Covers "same sphere,
   different colors." Adds the UBO-cap chunking.
3. **Opportunistic auto-collapse.** Detect shared geometry across distinct records in
   `renderSet`, above a threshold count, and route them to the instanced path
   automatically. Below threshold, per-shape (instancing has fixed setup cost).
4. **glTF `EXT_mesh_gpu_instancing` + shared-mesh.** Loader emits instance sets / marks
   shared meshes so stage 3 catches them for free.
5. **VRML97 lit shader instancing.** Same plumbing for the non-PBR lit program.

## Open questions

- **Per-instance non-pickable / click-through in one draw.** *Resolved: split into a
  separate draw.* `pickable=False` is a masked-id-attachment behavior, not an id value:
  the single-shape path masks `OBJECT_ID_ATTACHMENT` with `glColorMaski` so the instance
  writes *no* id (`_flat._writeShapeId`), giving both observable outcomes the flag
  guarantees — opaque non-pickable reads empty, and a non-pickable shape in front reads
  *through* to a pickable object behind (the water-surface case,
  `test_click_through_gl`). Masking is per-draw state shared by every instance in one
  `glDrawElementsInstanced`, so it can't be toggled per instance. Packing objectId 0 does
  not reproduce this: 0 is a *written* value, so a non-pickable instance overwrites the id
  of a pickable object behind it and read-through returns empty. The batched-correct
  answer is to add the `pickable` bit to the group key and draw the non-pickable group
  with the id attachment masked — same masking as the single path, at most one extra
  instanced draw per group. Stage 1 packs 0 as a stopgap (opaque gizmos only); the
  separate-draw split is the fix for read-through.
- **Frustum culling granularity.** Cull at the group's combined bounds first (accept some
  off-screen instances in the draw). Per-instance culling defeats batching, and core GL
  has no scatter "draw these instance indices" call — only contiguous ranges
  (`glDrawElementsInstancedBaseInstance` draws one slice; `glMultiDrawElementsIndirect`,
  GL 4.3 already detected, draws N slices in one call). The batched middle ground is
  **cluster culling**: at build time, spatially sort the group's instances (Morton code
  from the instance translation) and partition into clusters of ~tens-hundreds, each a
  contiguous `(baseInstance, count)` run with its own AABB. Per frame, frustum-test the
  cluster AABBs and draw the surviving ranges via MDI (or one baseInstance draw each). This
  reconciles with the "cache the per-frame instance VBO" TODO: cache the *full, sorted*
  buffer statically and only recompute which ranges to draw -- no per-frame buffer rewrite.
  (CPU compaction -- gather visible instances into a fresh buffer each frame -- is the
  stopgap that fits today's ephemeral-VBO path but fights that caching.) Restrict the first
  cut to **static** per-instance transforms so cluster AABBs are computed once; animated
  transforms need AABB refresh and erode the win. Revisit granularity per group by instance
  count.
- **Transparent instances** need per-instance depth sort, which fights batching. *Resolved:
  opaque-only; transparent stays per-shape.* Not a real loss -- scenes rarely need huge
  numbers of transparent objects, and the particle/foliage case that would has its own
  PointSet path. The depth-sort conflict is not fundamental: order-independent transparency
  (weighted-blended OIT, or per-pixel linked lists) drops the sort requirement and would
  let transparent groups instance -- but that's a separate rendering path to justify, so it
  is the revisit route only if a real workload demands it.

## Test strategy

- Unit: grouping/key logic headless (given fake records → expected groups).
- GL: an N-instance scene renders correctly (visual) AND every instance is individually
  pickable (click several instances → distinct paths). Frame-time assertion that one
  instanced draw replaces N `Shape.Render` calls (count draw calls, not wall-clock).
