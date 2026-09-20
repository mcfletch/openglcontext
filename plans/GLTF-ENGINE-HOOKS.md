# glTF engine hooks: authoring what a material or an object *is*

Status: **Complete** — 2026-09-20. Stages 1 to 3 have landed: the registry, both
hook points, the writer's two spellings, the built-in `water` kind, and the
documentation. Stages 4 and 5 are the optional ones and are untouched.

Three things the build settled that the design had not:

- **`ctx.bounds` is the primitive's local box**, with `ctx.world_matrix` beside
  it and `ctx.world_bounds()` to place it. The material hook stands in
  `_primitive_shape`, where the world matrix arrives as an argument and the
  bounds have not been placed yet; the loader frames the camera from whatever
  the hook leaves in `bounds`, so the writable-extent property holds either way.
- **One factory serves both hook points**, and `ctx.at` — `'material'` or
  `'node'` — says which it stands at, since what a return value means differs
  between them.
- **`water` takes a fourth parameter, `depth`.** A surface has no thickness, so
  a sheet bounds a box nothing can be inside of; `depth` is how far below the
  surface the body reaches.

An artist models a lake in Blender, gives the surface a material and exports it.
The file loads as a flat PBR sheet, because a material is all the loader can see
and a `PBRMaterial` is all it can make. The engine has water — a wave field, the
three styles, the GPU path, media and volumes
([WATER.md](WATER.md)) — and no way for a file to ask for it.

The same gap is under lava, force fields, portals, holograms, animated banners
and anything else a game wants to intercept at load: the format carries the
geometry and the PBR factors, and nothing else crosses.

Two different facts want tagging, and they are not the same fact:

- **This surface is made of that substance.** A material-level fact. It selects
  the shading, and for water it also puts `wave_style` on the *geometry*
  (`scenegraph/water/surface.py:424`), which the material has no way to reach.
- **This object is a thing of that kind.** A node-level fact — a body of water
  with bounds, a spawn point, a trigger volume. It replaces or augments the node.

Both are in scope. One tag format, one registry, two places it is read.

## What glTF offers

There is no ratified way to say "this material wants shader X":

| | |
|---|---|
| `KHR_techniques_webgl` | The 2.0 port of glTF 1.0's `technique`/`program` — literally a shader per material. **Archived**; the registry says archived extensions are for reading old files, not writing new ones. |
| `NV_materials_mdl` | The one current registry extension attaching a shading definition to a material. Vendor, and MDL-specific. |
| `KHR_materials_variants` | Swaps *which material* a primitive draws with. Not shader selection. |
| `KHR_interactivity` | A behaviour graph. Not shading. |
| `EXT_structural_metadata`, `EXT_mesh_features` | Typed semantic metadata over geometry and sub-geometry, from the 3D Tiles work. The principled home for per-feature classification of a baked city; a class schema, property tables and feature IDs to say "this material is water". |
| `extras` | The spec's own slot for application-specific data on any object, including materials and nodes. |

The format's intended answer is to describe the substance *physically* —
`KHR_materials_transmission`, `_volume`, `_ior`, `_dispersion`, all of which the
loader already reads (`loaders/gltf/materials.py:184`) — and let the renderer
decide. That covers a still pool. It cannot ask for a Gerstner sum on the card.

So: `extras` for the artist path, and a vendor extension for the authored path.

## What Blender gives us

Confirmed in the exporter source (`glTF-Blender-IO`,
`addons/io_scene_gltf2/blender/exp/material/materials.py`):

- `extras=gather_extras(bmat.material, export_settings)` — **custom properties on
  the material datablock export into `material.extras`**, gated on
  Include ‣ Custom Properties. Object custom properties reach `node.extras` the
  same way. This is in Blender 4.x; **5.x is not required**.
- `export_user_extensions('gather_material_hook', …)` — an add-on can write a
  real extension block onto the material.

So the zero-install artist path is a custom property, and the add-on path can
emit the extension for pipelines that prefer one. The format below is the same
either way.

## The tag

One payload, two spellings. A `kind` naming what the application should make of
it, and whatever parameters that kind defines:

```jsonc
// material.extensions -- the authored spelling
{"OGLC_hook": {"kind": "water", "style": "choppy", "level": 12.5}}

// material.extras -- the Blender custom-property spelling
{"OGLC_hook": {"kind": "water", "style": "choppy"}}

// extras, shorthand: a bare string is the kind, with no parameters
{"OGLC_hook": "water"}
```

The extension wins where both are present, because a file that carries an
extension was written by a tool that knew what it meant. An unknown `kind` loads
as an ordinary shape, with one `log.debug` naming it — a file authored for
another engine must not fail to load here.

`node.extras` / `node.extensions` take the same block for the node-level fact.

**A file names a kind; it never names code.** The registry is populated by the
application, so a downloaded model can only select among what the running
program already registered. There is no entry-point scan in this design: an
installed package cannot add a kind to somebody else's viewer by being present.
`OPENGLCONTEXT_GLTF_HOOKS=0` turns the whole mechanism off.

## What lands

| File | Holds |
|---|---|
| `loaders/gltf/hooks.py` | The registry, the tag reader, `HookContext`, `register()` / `registered()` |
| `loaders/gltf/meshes.py` | The material hook point, in `_primitive_shape` |
| `loaders/gltf/scene.py` | The node hook point, in `_SceneBuilder.build`; `GLTFScene.hook_data`; `GLTFScene.advance()` |
| `loaders/gltf/writer.py` | `extras` pass-through and the `OGLC_hook` extension, so a tag round-trips and an editor can author one |
| `scenegraph/water/gltf.py` | The built-in `water` hook, registered by `scenegraph.water` |
| `viewer/sceneviewer.py` | `advanceHooks()`, beside `advanceAnimation()` |

### The registry

```python
from OpenGLContext.loaders.gltf import hooks

@hooks.register('water')
def water_hook(ctx: hooks.HookContext): ...
```

`register(kind, factory=None, *, shareable=True, advance=None)` works as a
decorator or a call. `registered(kind)` answers what is bound, for a viewer that
wants to report which tags in a file it can honour.

The kinds the engine ships are a fixed table in `hooks.py` — `BUILTIN` — and the
module naming one is imported the first time a document asks for it, so
`scenegraph.water` never has to be imported for a tagged lake to load and an
application that never meets water never imports it. Still no entry-point scan:
the table is ours, in our source.

### The material hook

Called in `_primitive_shape` (`loaders/gltf/meshes.py:90`) once the `PBRMesh`,
the material and the `Shape` exist, so a hook gets the finished objects rather
than the accessors. The context is mutable and the return value optional:

| `HookContext` | |
|---|---|
| `kind`, `params` | From the tag |
| `mesh`, `material`, `shape` | What the loader built |
| `document`, `primitive`, `resolver` | For a hook that needs to read more of the file |
| `bounds` | The primitive's world-space box, writable: a hook that changes the extent says so |
| `scene_data` | The dict that becomes `GLTFScene.hook_data`, keyed by kind |

A hook returns `None` to keep the loader's own `Shape` — which is what water
does, because all it needs is two attributes on the geometry — or a node to use
in its place.

### The node hook

Called in `_SceneBuilder.build` (`loaders/gltf/scene.py:564`), beside
`KHR_node_visibility` and `EXT_mesh_gpu_instancing`, after the node's children
are gathered. The context carries the node's `Transform`, the children built for
it, its local and world matrices, and the same `scene_data`. This is where "this
object is a body of water" registers a `Volume`
(`scenegraph/water/volumes.py`) against the group's bounds.

A node hook returns `None`, or a node and whether that node is *replacing* the
one the loader built:

| Return | What the loader does |
|---|---|
| `None` | Keeps its own `Transform` and children. The hook augmented and nothing else changed. |
| `(node, False)` | Puts the node inside the glTF node's `Transform`, in place of the children the loader gathered. The node's TRS still places it, and the hook may return **any** node type — a `Switch`, an `LOD`, a `Billboard`, a node the game defined. |
| `(node, True)` | Puts the node in the glTF node's own slot in the parent. The `Transform` is gone and the hook owns the placement; `ctx.local_matrix` is the transform it has taken responsibility for. |

The flag is per return rather than per registration, because whether a hook
replaces the node is a property of what it made of *this* node, not of the kind:
a hook may take the slot for one tag and sit under the transform for the next.
`False` is the answer that needs no thought — a hook that forgets the TRS
produces an object in the wrong place and a plausible-looking scene — so it is
the one spelled out in the common case.

The material hook has no such choice: its `Shape` sits in a list of children, so
returning a node replaces it and there is nothing else it could mean.

Either way the loader stamps the node's DEF on whatever ends up in the slot, so
`getDEF` finds the same name it would have found. The children the loader built
are in `ctx.children` for a replacement to carry; one that ignores them drops
that subtree, which is a reasonable thing for a hook to do deliberately and a
surprise to do accidentally, so the plain `None` return remains the common case.

### Sharing, instancing and LOD

`mesh_shapes` caches shapes by mesh index (`loaders/gltf/scene.py:496`) so two
nodes referencing one mesh share one `Shape`. A hook whose result carries
per-instance state — a wave clock, a trigger's fired flag — must not be shared,
so `register(..., shareable=False)` suppresses the cache entry for that mesh, in
the same way a morphed or skinned mesh already suppresses it.

`EXT_mesh_gpu_instancing` builds an `InstancedShape` from `shape.geometry`. When
a hook has replaced the node, that path has nothing to instance: the hooked node
is placed per instance instead, with a `log.warning` naming the mesh. A hook that
only mutated the geometry instances as before. `MSFT_lod` needs nothing special —
each level is a primitive and carries its own material.

### Time

A wave costs nothing because the card moves it: `Shape.render` reads
`wave_style` and `wave_time` off the geometry and hands them to
`PBRShaderProgram.set_wave` (`scenegraph/shape.py:143`,
`passes/pbrpass.py:603`). Today
the application writes `wave_time` each frame, which is why water loaded from a
file would sit still.

`GLTFScene.advance(when)` walks the hooks that registered an `advance` callable
and returns whether anything changed — the shape `advanceAnimation()` already
has. `SceneViewerMixin.OnIdle` calls it beside the others
(`viewer/sceneviewer.py:1069`) and redraws on a true. A game that drives its own
loop calls `scene.advance(t)` itself.

A hook registers what it wants advanced rather than the loader guessing: the
water hook appends its mesh, and `advance` writes `wave_time`. A scene with no
timed hook has an empty list and `advance` is a return.

`TimeSensor` (`scenegraph/timesensor.py`) drives the VRML side of the engine and
is how a scenegraph-routed clock would look, but `wave_time` is a float the PBR
path reads as a plain attribute, and a sensor node plus a route to set one is
more mechanism than the value needs.

### The built-in water hook

`kind: "water"`, shipped registered, so a tagged file works in `oglc-view` with
no application code:

| Parameter | |
|---|---|
| `style` | `still` / `flowing` / `choppy`, or the five `WaterStyle` fields inline |
| `material` | `keep` (default) to shade with the file's own material, or `engine` for `water_material()` |
| `medium` | `water` / `slime` / `lava`, default `water` — what being inside it is like |
| `depth` | How far below the surface the body reaches, in metres, default `0` |

It sets `wave_style` and `wave_time` on the mesh, leaves the `Shape` alone, and
records a `WaterBody` — the mesh, the style and the world-space `Volume` — in
`scene_data['water']`, so a walking context can be submerged by it. Registered
`shareable=False`, because the box is round *this* copy of the surface. Lava is
the same hook with a different medium and material; it needs no second kind.

### Writing it back

The writer emits no `extras` at all today. Materials and nodes gain `extras`
pass-through, and `OGLC_hook` joins the material extension table, so a scene that
is loaded and re-saved keeps its tags and the editors
(`glisteel-editor`, `marble-editor`) can bake a world with water already marked.

## Stages

1. ~~**`hooks.py` + the material hook point + the writer's `extras`.** No built-in
   kinds. Ends with the round-trip, precedence, unknown-kind and sharing tests.~~
   Landed.
2. ~~**The node hook point, `hook_data` and `advance`.** The viewer calls it.~~
   Landed, as `SceneViewerMixin.advanceHooks()` beside `advanceAnimation()`.
3. ~~**The water hook, the GL test and the documentation.**~~ Landed.
4. *Optional:* a Blender add-on under `tools/blender/` adding a material panel
   and emitting the extension through `gather_material_hook`, for pipelines that
   want the extension rather than a custom property.
5. *Optional:* reserve the `OGLC_` prefix in the Khronos registry, if the
   extension spelling is to be published rather than kept in-house.

## Tests

No GL but the last file; each test writes a document with `writer` and reads it
back with `load_gltf`, as `tests/unit/test_gltf_named_materials.py` does.

`tests/unit/test_gltf_hooks.py`
- a tag in `extras` reaches the registered hook, with its parameters
- a tag in `extensions` does too, and wins when both are present
- a bare string is the kind
- an unregistered kind loads as a plain `Shape` and logs once
- `shareable=False` gives two nodes on one mesh two geometries; the default still shares
- `OPENGLCONTEXT_GLTF_HOOKS=0` leaves every tag unread
- a material hook returning a node has that node in the scenegraph, and its `bounds` frame the camera
- a node-level tag reaches the node hook with the group, the children and the world matrix
- a node hook returning `None` leaves the `Transform` and children as the loader built them
- `(node, False)` keeps the `Transform`: the node's TRS still places it, and the returned node is what is under it
- `(node, True)` puts the returned node in the parent's slot, with `ctx.local_matrix` carrying the TRS the hook has taken on
- one kind returning `True` for one node and `False` for another gets both, in the same file
- the node's DEF resolves to whatever ends up in the slot, in all three cases
- `hook_data` arrives on the `GLTFScene`
- the tag round-trips through the writer, both spellings

`tests/unit/test_gltf_water_hook.py`
- a material tagged `water` gives the mesh a `wave_style`, and the named styles map
- `advance()` moves `wave_time` and reports the change
- the volume and medium land in `hook_data`

`tests/unit/test_gltf_water_hook_gl.py`
- a tagged file renders, and the surface moves between two `advance()` values —
  the shape of `tests/unit/test_water_gpu_gl.py`

## Documentation

- **`docs/gltf.html`** — a new "Engine hooks" section: the tag, both spellings,
  the built-in `water` kind and its parameters, registering your own, and the
  note that a file names a kind and never code. Listed in the extension coverage
  above it.
- **`docs/water.html`** — how to author water in a model rather than in Python:
  the Blender custom property, the export checkbox, the parameters.
- **`docs/documentation.html`** — the index entry, if the glTF section grows a
  sub-heading.
- **[WATER.md](WATER.md)** — cross-reference, since "where there is water is
  authoring and lives with whatever builds the world" now has an answer for
  files.

## Settled

- **The prefix is `OGLC_`** (2026-09-19), and `OGLC_hook` is the key in both
  spellings — an extension block and an `extras` key of the same name, so an
  artist and a tool write the same word. It is the prefix to reserve if stage 5
  happens.
- **`kind` is an open string** (2026-09-19). A game introduces a kind by
  registering it, and the engine validates nothing beyond finding it in the
  registry. The engine claims the bare lowercase names it documents and ships —
  `water` is the only one at stage 3 — so an application naming its own kinds
  keeps them out of that namespace: `glisteel:rail`, `twigbb:teleporter`. A
  convention, read by nothing, so that a kind a game invents today does not
  collide with one the engine ships later.
- **A material's name never selects a hook** (2026-09-19). The tag is the only
  thing the loader reads; a material called `water` is a material called
  `water`. A name is what an artist types, it repeats across files and it
  changes when a mesh is duplicated, so a loader acting on one would surprise
  whoever renamed it. `GLTFScene.materials` (`loaders/gltf/scene.py:751`) stays
  what it is: an index a game may use to drive an asset by name after load.
- **A node hook may return any node type** (2026-09-19), and says on the return
  whether it is replacing the node or standing under its transform: `None`,
  `(node, False)` or `(node, True)`, described in
  [The node hook](#the-node-hook). Per return rather than per registration, so
  one kind can do both.
- **The clock is `GLTFScene.advance(when)`** (2026-09-19), called from the
  viewer's idle beside `advanceAnimation()`. `wave_time` is a float on the
  geometry, and a `TimeSensor` plus a route to write one is more mechanism than
  that needs. [Time](#time) has the shape of it.

Every question this plan opened is answered, and stages 1 to 3 are built. What
is left is the two optional ones: a Blender add-on for pipelines that want the
extension rather than a custom property, and reserving the `OGLC_` prefix with
Khronos if the spelling is to be published.
