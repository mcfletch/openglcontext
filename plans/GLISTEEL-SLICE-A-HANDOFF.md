# GLISTEEL first-vertical-slice — implementation handoff

Working notes for building the first vertical slice of
[GLISTEEL-WORLD-AUTHORING.md](GLISTEEL-WORLD-AUTHORING.md). This file records the
decisions taken and the reader contract the §A writers must round-trip through, so
implementation can start without re-deriving it. It is a `plans/` working note, not
user documentation.

## Decisions taken

- **Scope of the first push: the plan's own first vertical slice** (§7): bake the
  forest world through a real writer (two equivalence checks) → one highway-on-dirt
  road → drive it. Not §A–§I in one go.
- **Target machine is this devcontainer.** "caramon" is the host running this
  container; work happens here in `/workspaces/OpenGL-dev`. There is no separate
  remote to drive.
- **This container has no network path to the git remotes.** All `git fetch`
  attempts fail here; pushes are impossible from inside it. Submodule
  upstream-sync must be checked from a networked shell. As of the last cached
  fetch, `openglcontext` was 8 behind `feature/testsuite-automation`, `website` 3
  behind `gh-pages`, `simpleparse` 1 behind `master`; all others level or ahead.
- **Homes (§0/§2):** the glTF + 3D-Tiles *writers* and the road/water *render
  nodes* live in `OpenGLContext` (runtime). The *baker* (octree, tile writer) and
  world *generation* live in a new `OpenGLContext_editor` sibling. `glisteel` and
  `glisteel-editor` are thin apps.

## Task breakdown (dependency order)

1. ✅ **Bootstrap `OpenGLContext_editor`** sibling — `src/` layout, `pyproject.toml`
   depending on `OpenGLContext`, `specs/`, its own `CLEAN-ROOM.md`; workspace
   member so `uv sync` wires it. Landed 2026-08-17, see below.
2. ✅ **§A glTF 2.0 writer** — `OpenGLContext/loaders/gltf/writer.py`.
3. ✅ **§A 3D Tiles 1.1 writer + octree baker** — `OpenGLContext_editor.bake`.
4. ✅ **§A bake driver + two equivalence checks** — `oglc-bake`, with the checks in
   the editor's `tests/test_bake_equivalence.py` and `tests/test_bake_renders.py`.
   Built against the *procedural* world rather than the forest demo's: the demo's
   scene assembly is GL-bound (it builds scenegraph nodes, not layers), and the
   procedural world exercises the same spine — heightfield, instanced trees with an
   impostor ladder — against a reference baker that is already in the engine. Baking
   the forest demo's own assets is now a content task rather than a spine task.
5. **Minimal §C road** (highway-on-dirt) + collider, baked into the octree. Blocked by 4.
6. **Minimal §H `glisteel`** — stream + drive. Blocked by 4, 5.

## Task 1 as built (2026-08-17)

`/workspaces/OpenGL-dev/openglcontext-editor`, on `main`, one commit.

- **Names.** Distribution `OpenGLContext-editor`, import package
  `OpenGLContext_editor`, checkout directory `openglcontext-editor` — the
  `OpenGLContext-qt` / `openglcontext-qt` pattern, and what the plan's
  `OpenGLContext_editor` normalises to. Version `0.1.0a1`, read by setuptools
  from the module rather than restated in the metadata.
- **Layout.** `src/OpenGLContext_editor/` (with `py.typed`), `tests/`, `specs/`,
  `license.txt` (BSD-3-Clause), `README.md`.
- **The bar.** ruff with the engine's `E`/`W`/`F`/`B` plus `I`/`UP`/`BLE`/`S110` —
  the forest demo's stricter set, adopted from the first commit because nothing
  here predates it; mypy at `python_version = "3.12"` with
  `disallow_untyped_defs`; pytest with a 300 s backstop timeout; a tox matrix
  py310–py314 with `pip_pre`. All three are green and coverage is 100%.
- **Wiring.** An editable member of the root
  [`pyproject.toml`](../../pyproject.toml) (`[tool.uv.sources]` plus the explicit
  dependency uv needs to apply that source) and of
  [`requirements-dev.txt`](../../requirements-dev.txt). `uv sync` installs it.
- **Red/Green.** `tests/test_packaging.py` — module version is PEP 440, installed
  metadata reports *that* version, `OpenGLContext` is a declared requirement, and
  the engine imports. Red as `ModuleNotFoundError` before the package existed.

Two things a networked shell still has to do, which this container cannot:

- **Create `github.com/mcfletch/openglcontext-editor` and register the
  submodule.** The checkout is a plain local repo; nothing is in the parent's
  `.gitmodules` yet, because pointing it at a URL that does not resolve would
  break a fresh clone of the workspace.
- **Nothing else is pending on the remote side** for task 2 to start; the writer
  work is entirely local.

**`uv sync` prunes anything outside the harness's dependency closure.** This run
removed PySide6-Essentials/shiboken6 (which `openglcontext-qt` needs) and
trimesh (which the forest demo's `tools/bake_assets.py` and `parthenon` need);
both were reinstalled at their previous versions afterwards. Neither is reachable
from the root `pyproject.toml`, so the next `uv sync` will prune them again —
worth adding to the harness rather than rediscovering.

## Reader contract the writers must satisfy

All references are `file:line` under `/workspaces/OpenGL-dev/openglcontext/`.
Verified by exploration of the reader code; re-check before coding against any one.

### glTF loader → what a written `.glb` must load back as

- **Load entry:** `load_gltf(source, base_url, max_resource_bytes, pointer_time)
  -> GLTFScene` — `OpenGLContext/loaders/gltf/loader.py:37`. Uses `pygltflib.GLTF2`
  internally (lazy import, `loader.py:27`). Scene assembly:
  `_build_scene(...)` via `_SceneBuilder` — `loaders/gltf/scene.py:671`.
- **Mesh lands as `PBRMesh`** — `scenegraph/pbrmesh.py:182`:
  `PBRMesh(positions, normals, texcoords, tangents, colors, indices, solid=True,
  material=None, morph_targets=None, skin_joints=None, skin_weights=None,
  texcoords1=None, draw_mode=GL_TRIANGLES)`. After load:
  - `positions (N,3) f32`, `normals (N,3) f32`, `texcoords (N,2) f32`,
    `texcoords1 (N,2) f32` optional, `tangents (N,4) f32`,
    `colors (N,4) f32` optional, `indices (M,) u32` or `None`.
  - Primitive → Shape wrapping: `_primitive_shape(...)` — `loaders/gltf/meshes.py:90`.
- **Material lands as `PBRMaterial`** — `loaders/gltf/materials.py:207`:
  `baseColor (r,g,b,a)`, `metallic`, `roughness`, base-color/metallic-roughness/
  normal/occlusion/emissive textures, `emissiveColor`, `alphaMode`
  (OPAQUE/MASK/BLEND), `doubleSided`, `KHR_texture_transform`. `KHR_materials_*`
  handler table at `materials.py:172` (unlit, ior, specular, clearcoat, sheen,
  transmission, volume, emissive_strength, …). The slice needs only
  metallic-roughness + base color; the writer emits the subset our content uses.
- **`EXT_mesh_gpu_instancing`** read at `scene.py:213`
  `gpu_instance_transforms(g, ext_dict, resolver)` — TRANSLATION(VEC3)/
  ROTATION(VEC4 quat)/SCALE(VEC3) accessors → one `Transform` per instance sharing
  one mesh Shape. This is how baked tree instances ride in one tile.

### tiles3d reader → what a written `tileset.json` must parse as

- **Parse entry:** `build_runtime_tileset(tileset_dict, base_uri, recenter,
  resolve_external) -> RuntimeTileset` — `loaders/tiles3d/tileset.py:323` (takes a
  parsed dict, not a path). Per-tile parse `_build_tile(...)` — `tileset.py:215`.
- **`RuntimeTile`** (`tileset.py:67`): `bounding_volume` (SphereBV/BoxBV/RegionBV),
  `geometric_error`, `refine` "REPLACE"|"ADD" (inherited if omitted),
  `content_uris`/`content_uri`, `world_transform`, `content_transform`, `children`.
- **Tile dict fields the writer emits:** `boundingVolume` as
  `{"box":[cx,cy,cz, hx1,hy1,hz1, hx2,hy2,hz2, hx3,hy3,hz3]}` (center + 3 half-axes,
  column-major) or `{"sphere":[cx,cy,cz,r]}` or `{"region":[...]}`;
  `geometricError`; `refine`; optional `transform` (16, column-major);
  `content:{"uri"}` (1.0) or `contents:[{"uri"},…]` (1.1); `children:[…]`.
  `asset.gltfUpAxis` default "Y".
- **Existing bakers to compare against (reference, not oracle):**
  `build_terrain_tileset(directory, extent, levels, tile_res, height_fn) -> path`
  — `loaders/tiles3d/procedural.py:307`; `terrain_patch(x0,x1,z0,z1,res,height_fn,
  skirt_depth) -> (positions, normals, colors, indices)` — `procedural.py:162`;
  `_glb(pos,nrm,col,idx) -> bytes` (currently via `pygltflib`) — `procedural.py:267`.
  DEM: `height_function_from_image(...)`, `build_dem_tileset(...)` — `dem.py:49`.
  `HeightFn = Callable[[np.ndarray, np.ndarray], np.ndarray]`, `procedural.py:18`.
  The new writer is pointed at the *same* `height_fn` and asserted "equivalent or
  better" (§A check 1): height sampled at many XZ within epsilon, equal extent,
  monotone tile tree, no new holes.
- **Runtime consumer** (only the entry API a baked tileset must feed):
  `TilesetRuntime.update(camera, viewport_height, max_sse, visible,
  view_projection)` — `runtime.py:40`; `select_tiles(...)` — `traversal.py:77`;
  `Residency` LRU — `residency.py:26`.

### Test patterns to follow (do not invent infra)

- glTF round-trip: `tests/unit/test_gltf_loader.py:59` (`_triangle_glb()`,
  `_find_shape()`, asserts on `PBRMesh`/`PBRMaterial` attrs).
- Instancing: `tests/unit/test_gltf_gpu_instancing.py:58`.
- Tileset parse: `tests/tiles3d/test_tileset.py:16` (uses `build_runtime_tileset`).
- Bake→parse: `tests/tiles3d/test_procedural.py:50` (bake, reparse, count tiles).
- Headless GL: `OPENGLCONTEXT_HIDDEN=1`, `OPENGLCONTEXT_NO_VSYNC=1`, GLFW backend;
  `tests/conftest.py`.

### The glTF writer's acceptance test (Red first)

Build synthetic mesh data (positions, normals, texcoords, tangents, colors,
indices) + a metallic-roughness material → `write_glb(...)` → `load_gltf(bytes)` →
`_find_shape()` → assert the `PBRMesh` arrays equal what went in (allclose) and the
material fields match. Owning this ends `pygltflib` on our bake path.
