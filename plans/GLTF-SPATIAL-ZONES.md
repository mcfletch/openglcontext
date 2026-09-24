# Spatial zones: glTF extensions that apply inside a shape

Status: **Planned** — 2026-09-24. Plan only, awaiting review.

## Why

The Parthenon's two cella rooms are lit as brightly as the street outside. The
image-based lighting is the sky, it arrives everywhere with the same strength,
and nothing between the sky and a surface blocks it, so a roofed room with one
door reads flat. Turning the IBL down for the whole scene darkens the shaded
exterior by the same amount and leaves the ratio between inside and outside
where it was.

The same shape of problem turns up across the games built on the engine:

- a cave, a cellar or a tunnel wants dimmer or different environment lighting
  than the terrain above it;
- a room wants its own lamps lit only for what is in the room, so a lamp does
  not light the far side of a wall it has no shadow map for;
- a room wants its own ambience (room tone, a fountain, a crowd) audible while
  the player is in it and fading out at the door;
- a mirror is worth its extra scene draw only while the player can see it;
- a gravity volume changes which way is down inside a region.

Each is an extension's setting that holds inside a region of space and not
outside it. This plan adds one mechanism for all of them: a node carries a shape
and a set of extension blocks, and each block applies to whatever is inside the
shape.

## Standards this builds on

glTF 2.1 shapes - the 2.1 core adds a top-level `shapes` array of implicit
shapes: `box` (`size`), `sphere` (`radius`), `capsule`, `cylinder` and `plane`,
each with its data in a sub-object named after its type. It carries the same
data as the `KHR_implicit_shapes` extension it supersedes, and its explainer
lists "volume restriction" and "semantic labeling of volumes" among its uses
([KhronosGroup/glTF#2588](https://github.com/KhronosGroup/glTF/issues/2588)).
The spec is written so that a zone works in both versions of the format. In a
2.1 document its shape is an entry in the core `shapes` array. In a 2.0
document it is an entry in `KHR_implicit_shapes`' `shapes` array, which holds
the same objects. A tool moves a file from 2.0 to 2.1 by moving that array to
the top level and changing nothing in the zones.

glTF 2.1 `boundingVolume` - a node property holding a shape that "completely
encloses the node's content", for culling, collision, ray tests and deferred
loading
([Khronos blog](https://www.khronos.org/blog/introducing-gltf-2.1-with-complex-scenes)).
It is not the control: it describes where a node's content lies and is expected
on every node, so an exporter that writes one for culling would otherwise put
the whole scene inside zones. A zone node has no content except its region, so
its `boundingVolume`, where a 2.1 file carries one, is the same box; the loader
does not need it. How a 2.1 node binds a shape has not been published yet (the
feature explainers are the reference), so the zone names its shape by index in
its own block, as the physics extensions do.

`OMI_physics_gravity` - the precedent. A gravity volume sits on a node whose
`OMI_physics_body` has a `trigger` naming a shape, and volumes carry `priority`,
`replace` and `stop` (`omi_physics.gravity.resolve_gravity`). A zone is the
same arrangement, generalised from gravity to any extension.

Scene-level forms - several extensions already have a block that says "this
applies to the whole scene": `EXT_lights_image_based` puts `{"light": 0}` on a
scene, and `KHR_audio_emitter` puts `{"emitters": [0, 1]}` on a scene or node.
A zone reuses that block unchanged, so a zone reads as scene settings with a
region attached.

No standard says "this extension applies inside this region", so that part is
an engine extension, `OGLC_zone`, in the namespace `OGLC_hook` and
`OGLC_castsShadow` already use.

## The extension

The specification is `docs/extensions/OGLC_zone.rst`, written in the layout of
a Khronos extension README (overview, properties, JSON schema, examples,
implementation notes), with the schema beside it as
`docs/extensions/schema/node.OGLC_zone.schema.json`. It covers both versions of
the format.

- In a glTF 2.0 document the shapes are the `KHR_implicit_shapes` extension's
  `shapes` array, and `KHR_implicit_shapes` is listed in `extensionsUsed`.
- In a glTF 2.1 document (`asset.version` 2.1 or later) the shapes are the
  core top-level `shapes` array.
- `shape` indexes whichever of the two the document's version selects. A 2.1
  document that also carries `KHR_implicit_shapes` still resolves against the
  core array, since that is the one its version defines.

The 2.0 form:

```json
"extensionsUsed": ["OGLC_zone", "KHR_implicit_shapes", "KHR_audio_emitter"],
"extensions": {
  "KHR_implicit_shapes": {"shapes": [
    {"type": "box", "box": {"size": [29.6, 10.2, 19.06]}},
    {"type": "box", "box": {"size": [13.6, 10.2, 19.06]}}
  ]}
},
"nodes": [
  {"name": "naos-interior", "translation": [7.3, 6.6, 0.0],
   "extensions": {"OGLC_zone": {
     "shape": 0, "priority": 0, "blend": 1.0,
     "environment": {"intensity": 0.12}}}},
  {"name": "west-chamber-interior", "translation": [-15.3, 6.6, 0.0],
   "extensions": {"OGLC_zone": {
     "shape": 1, "blend": 1.0,
     "environment": {"intensity": 0.12},
     "extensions": {"KHR_audio_emitter": {"emitters": [2]}}}}}
]
```

The same zones in a 2.1 document: the shapes move to the top level, the zones
are unchanged, and `KHR_implicit_shapes` is no longer used.

```json
"asset": {"version": "2.1"},
"extensionsUsed": ["OGLC_zone", "KHR_audio_emitter"],
"shapes": [
  {"type": "box", "box": {"size": [29.6, 10.2, 19.06]}},
  {"type": "box", "box": {"size": [13.6, 10.2, 19.06]}}
]
```

| Field        | Type    | Default | Meaning |
|--------------|---------|---------|---------|
| `shape`      | integer | —       | Index of the region's shape. Required. |
| `priority`   | integer | 0       | Where zones overlap, the higher priority's block for an extension is the one applied. |
| `blend`      | number  | 0       | Metres outside the shape over which the zone's effect fades to nothing. |
| `environment` | object | —       | The zone's own image-based lighting: `intensity`, a multiplier (default 1), and from phase 5 `capture`, a probe captured inside the zone. |
| `extensions` | object  | —       | Extension name to that extension's block, or `false`. |

`environment` belongs to `OGLC_zone` because no extension defines scaling the
environment lighting in place. A block under `extensions` always means what
that extension's own specification says. So `"EXT_lights_image_based":
{"light": 1}` selects a probe, and when a zone carries both, `environment`
scales the probe it selects.

The rules:

1. The shape is in the node's local space, so the node's world transform
   places, rotates and scales it. A box is an oriented box, not an
   axis-aligned one.
2. A block is the form that extension takes at scene level, where it has one.
   Inside the shape it applies to the extension's subject (below) as a scene
   block would apply everywhere.
3. `false` in place of a block switches that extension off inside the shape.
   For example, `"KHR_lights_punctual": false` turns off every punctual light
   for what is inside. An engine hook kind is addressed under `OGLC_hook` by
   kind, so `"OGLC_hook": {"mirror": false}` stops mirrors being drawn from a
   camera inside the shape.
4. Something a zone switches on (a light node, an emitter, a mirror) is
   controlled by zones: it is on for a subject inside a zone that names it,
   and off for a subject outside every such zone. A node no zone names behaves
   as it would in a file with no zones.
5. Where zones overlap, each extension resolves on its own: the highest
   `priority` wins, and a tie goes to the zone with the smaller shape volume,
   which is the more specific one. The naos zone's IBL and the west chamber's
   audio can therefore come from different zones for the same subject.
6. `blend` fades the effect from full at the shape's surface to none at `blend`
   metres outside it, weighted by the signed distance to the shape.
7. An extension name nothing is registered for is ignored, with one log line
   per document, and the zone's other blocks still apply. A file names
   extensions; which code handles each is decided by the engine and the
   application, exactly as for `OGLC_hook`.
8. `OGLC_zone` goes in `extensionsUsed` and never in `extensionsRequired`, so
   a viewer without it loads the file and shows it without zones.

## Subjects

Each extension decides what is tested against the zone, and the file does not
choose. There are three kinds of subject: what is drawn, the camera, and
physics bodies.

| Extension | Subject | Inside means | Effect |
|---|---|---|---|
| `environment` (the zone's own) and `EXT_lights_image_based` | each drawn object, then each of its fragments | the object's world box meets the shape; fragments weighted by distance | IBL intensity, later a different probe |
| `KHR_lights_punctual` | each drawn object | the object's world box meets the shape | the zone's light nodes are on for that object |
| `KHR_audio_emitter` | the camera | the camera's position is in the shape | the named emitters play, gain faded by `blend` |
| `KHR_node_visibility` | the camera | the camera's position is in the shape | the named nodes are shown or hidden |
| `OGLC_hook` `mirror` ([PLANAR-MIRRORS.md](PLANAR-MIRRORS.md)) | the camera | the camera's position is in the shape | the mirror's reflection is drawn |
| `OMI_physics_gravity` | each physics body | the body's centre is in the shape | the zone's block becomes a gravity volume in `omi_physics` |

With several views, a camera-subject extension that affects drawing
(visibility, mirrors) resolves per view. Audio has one listener, and it
resolves against the camera the listener is attached to, which is the main
view's.

### Why the IBL test finishes per fragment

"An object inside the box gets this IBL" is the reflection-probe rule most
engines use, and it assumes a model built with that rule in mind. The Parthenon
is not built that way, and a real level often is not either. `walls` is one mesh
holding both faces of every cella wall, and `stairs` is the crepidoma, whose top
is the floor of both rooms and also the steps outside. An object-level choice
would darken the whole exterior of the walls, or none of the interior floor.

So the object test does the selection and the fragment does the weighting,
and only where it has to. For each draw, the render pass sorts every zone near
the object into one of three cases:

- The object is outside the zone and its `blend` band. The zone is left out.
- The object is wholly inside the shape. The zone's effect is a constant for
  the whole draw, passed as a uniform, with no per-fragment test.
- The object crosses the shape's surface or its `blend` band. Only here does
  the zone go to the shader for per-fragment weighting.

Most objects in a room fall in the first two cases. The Parthenon's straddlers
are the handful of large meshes built across the boundary: `walls`, `stairs`,
the ceiling and the entablature.

For a straddler, the per-fragment work is kept small. The world-to-shape
transform is affine, so the vertex shader applies it and passes the position in
the shape's own frame as a varying, which interpolates exactly. The fragment
shader is left with the distance in the shape's frame. For a box that is
`abs`, subtract, `max` and `length`, about eight operations. A sphere is one
`length`, and a capsule or cylinder is a few more. It then does one `smoothstep`
across `blend`. The PBR fragment shader beside it already does several
cube-map lookups, multi-sample shadow filtering and a light loop.
`MAX_STRADDLED_ZONES` is 2, which uses two `vec3` varyings. More than two zones
crossing one object is a model that should be split at the zone boundary, and
the pass logs it once per object.

Before the feature lands, it has to pass a measurement. The measurement is a
fill-bound frame (full-screen straddling geometry, several zones, the IBL and
shadows on), timed with zones on and off. That comparison goes in the
performance tests. If a scene ever needs many overlapping zones on one object,
the alternative is a coarse 3D texture of zone weights, which costs one lookup
whatever the zone count. It is not built until a scene needs it.

Lights stay per object in their first phase. The same weights could later drive
per-fragment light masks, if a straddling object turns out to need them.

### Captured probes: [RUNTIME-IBL.md](RUNTIME-IBL.md)

RUNTIME-IBL plans a probe for each object: a cubemap captured from the object's
position, convolved into irradiance and prefiltered specular maps, cached by
the object's quantised box centre, and bound when that object draws. Its
motivating case is this plan's: two objects in different rooms should not
share one environment.

A zone is a coarser and cheaper unit for the same capture. A zone can ask for
a probe captured from inside its shape, and everything the zone's IBL applies
to shares that probe:

- A probe captured inside the naos sees the walls, the ceiling and the doorway,
  not the sky. So it is dark indoors and bright toward the door without any
  hand-set number. `environment.intensity` is the tuned approximation of that,
  and remains the cheap choice for a scene that wants no capture.
- One probe per room costs one capture per room at load, rather than one per
  object. Objects that move within the room need no recapture.
- The zone's box is the proxy geometry that box projection (parallax
  correction) needs. A reflection sampled from a room probe is corrected to
  the room's walls, so the reflection in the naos's pool and polished floor
  lines up with the colonnade rather than floating at infinity.
- Objects in no zone keep RUNTIME-IBL's per-object capture, or the scene's
  probe.

In the file this is the zone's own `environment` property: `{"capture": true}`
asks for a captured probe, alongside or instead of `intensity`. It is phase 5,
because it needs RUNTIME-IBL's capture and per-object binding.

The per-fragment blend has a cost on this path that it lacks with an intensity
alone. A straddling object blends up to three environments (its two straddled
zones and the one outside them), and that means three probe sets bound at once.
The PBR program's fragment texture units are already committed up to the
reflection unit (31). The capture phase therefore decides between binding
several probes, packing zone probes into a cubemap array indexed per zone, and
limiting straddlers to one captured zone. A cubemap array is the likeliest
choice, since it costs one unit for every zone.

### Audio

A `KHR_audio_emitter` block in a zone is the scene form, `{"emitters": [...]}`.
Audio is tested against the camera, the user's own position in the world. A
global emitter named there is room tone: it plays at full gain while the camera
is inside the shape and fades out over `blend` metres beyond it. A positional
emitter named there keeps its own distance curve and cone, and the zone
multiplies its gain the same way, so a fountain behind a wall is not heard from
the other room. The gain is applied in the engine's audio glue, through the
per-voice gain `omi_audio` already exposes, so `omi_audio` keeps no knowledge of
zones. Whether an emitter starts playing on first entry or runs silently
throughout is its `autoPlay`, as the extension defines it.

The engine already does this by hand. `OpenGLContext.audio.areas.box_gain` is
1 inside an axis-aligned box and falls linearly to 0 over a margin, and
`docs/audio.rst` ("Background sound for an area") tells an application to set a
global emitter's gain from it each frame from the camera's position, which
`bin/audio_demo.py` does for its cave and stream. Zones are the same thing
authored in the file. `box_gain` becomes the axis-aligned case of the zone
distance function, and it stays as a function for code that builds areas
without a file. The demo's two areas become zones, and the docs section
describes zones first.

## Engine structure

The zone logic is plain Python with no GL, so tests reach all of it. The window
classes build it, feed it and draw what it answers.

- `OpenGLContext/loaders/gltf/shapes.py` - reads the document's shape table
  into `ShapeSpec` records: the core `shapes` array for `asset.version` 2.1 or
  later, and `KHR_implicit_shapes` for 2.0. One module, so that 2.1's
  `boundingVolume` and a later `KHR_physics_rigid_bodies` reader take their
  shapes from the same place.
- `OpenGLContext/scenegraph/zone.py` - the `Zone` node, with fields `shapeType`,
  `size`, `radius`, `height`, `radiusTop`, `radiusBottom`, `priority`, `blend`
  and `overrides` (MFNode). Each extension's block becomes a typed override node
  (`EnvironmentOverride`, `LightSwitch`, `AudioSwitch`, `VisibilitySwitch`), so
  zones can be built from code and edited in the editor like any other scene
  state.
- `OpenGLContext/scenegraph/zones.py` - the maths: signed distance for each
  shape type, box-against-shape overlap, and `resolve(zones, subject)`, which
  returns each extension's winning block and its weight. This is where the
  priority, tie and `false` rules live, and where the tests go.
- `OpenGLContext/loaders/gltf/zoning.py` - reads `OGLC_zone` into `Zone` nodes
  through a registry, `register_scoped(name, reader)`. It has the same `BUILTIN`
  table and the same rule as `hooks.py`: a document can select only among
  readers the running program has registered.
- Render pass - `Zone` joins `INTERESTING_TYPES` beside `LightGrid`, and each
  frame the zones' world placements are computed once. For each draw, the
  record's world bounds select the zones and uniforms are set only when the
  selection changes, so a sorted draw list mostly skips the upload.
  `setupViewLighting` resets the zone state, which covers the water reflection
  and the shared multi-view path, both of which route through it.
- `shaders/_zone_inc.glsl` - `zoneConstant` (the combined effect of zones the
  object is wholly inside), `zoneStraddled` (0 to 2), and for each straddled
  zone a world-to-shape matrix, which `pbr.vert` applies. Also per zone, the
  shape parameters and `(intensity, blend)`, which `pbr.frag` reads. `pbr.frag`
  scales the environment terms (`ambDiffuse`, `ambSpecular`, `irrBack`) by the
  result. Baked lightmap and light-grid terms are left alone, since a bake
  already contains its own occlusion. The depth-only shadow program is
  untouched.

On CPU cost: resolving zones is O(zones) a frame. Per draw, the cost is one
box-against-shape test per zone near the object. Once a scene has more than
about 32 zones, a uniform grid over them keeps that to the neighbours, and that
grid is where 2.1's bounding-volume hierarchy would plug in. Static objects keep
their classification until an object or zone moves, so a static level pays for
it once.

## Phases

1. Shapes reader, `Zone` node, resolver, `OGLC_zone` reading, and
   the zone's `environment.intensity`, which scales whatever IBL is in
   force. That is enough for the Parthenon. This phase also
   includes the documentation and the Parthenon changes below.
2. `KHR_audio_emitter` in zones, tested against the camera. `box_gain` becomes
   the axis-aligned case of the zone distance, and `audio_demo.py`'s areas
   become zones.
3. `KHR_lights_punctual` light switching: a per-draw light mask, and no shadow
   pass for a zone-owned light that no visible object is zoned into.
4. Camera-subject extensions: `KHR_node_visibility`, and the `mirror` hook kind
   once [PLANAR-MIRRORS.md](PLANAR-MIRRORS.md) lands.
5. Zone probes, together with [RUNTIME-IBL.md](RUNTIME-IBL.md)'s capture:
   `environment: {"capture": true}` captures a probe from inside the zone,
   box-projected against the zone's shape. `EXT_lights_image_based` is loaded
   properly (spherical-harmonic irradiance plus the prefiltered specular
   images), both at scene level and as a zone's `{"light": n}`. Zone probes
   are packed into a cubemap array.
6. `OMI_physics_gravity` blocks in zones, handed to `omi_physics` as gravity
   volumes whose region is the zone's shape.

## Parthenon, on phase 1

- Two zones, the naos and the west chamber, each a box on the room's inside
  faces, with IBL intensity around 0.1 (tuned by eye against captures) and a
  1 m blend so the doorway fades.
- `sky-fill` removed. It is an unshadowed directional light that shines through
  the roof, and the IBL already supplies the sky's fill outside.
- The pool becomes a sunken basin: a low marble curb, a dark limestone floor,
  and a flat water sheet whose material carries `OGLC_hook: {"kind": "water",
  "style": "still"}`. The tag gives the sheet a `waveStyle`, which is what turns
  on the engine's planar reflection, so the colonnade and the coffered ceiling
  reflect in it. The sheet is a flat mesh rather than the present box, because
  the reflection plane is taken from the sheet.
- A spot light in the middle of each doorway (at the centre of the opening and
  of the wall's thickness), aimed into the room with a wide outer cone of about
  1.2 rad and a narrow inner cone of about 0.2 rad, so the light fades across
  most of the cone. `castShadows` is kept on. At that cone the shadow frustum's
  field of view is about 151°, inside `spot_light_view_projection`'s 171° limit.
  Captures with shadows on confirmed that the present door spots do cast.
- The capture runner renders with `--no-shadows`, so no baseline checks a
  shadow. A `shadows` field on `SceneSpec`, set for the Parthenon, puts the
  door-light shadows under regression. The Parthenon baselines are then
  re-blessed after review.

## Documentation

- `docs/extensions/OGLC_zone.rst` and its JSON schema, new: the specification,
  covering the 2.0 and 2.1 forms. It is written first, reviewed before the
  code, and the reader is tested against its examples.
- `docs/zones.rst`, new: the user guide. It covers what zones do, the subjects
  table, what the engine supports in each phase, authoring a zone from code and
  in a file, and a worked example. Indexed from `docs/index.rst` and
  `docs/documentation.rst`.
- `docs/gltf.rst`: `OGLC_zone`, `KHR_implicit_shapes` and 2.1 `shapes` in the
  extension table.
- `docs/pbr.rst` and `docs/environment.rst`: where the IBL term is scaled by a
  zone, and that lightmaps are not.
- `docs/audio.rst`: "Background sound for an area" leads with zones, with
  `box_gain` kept for areas built in code (phase 2).
- `docs/testing.rst`, or wherever the capture runner is documented: the
  `shadows` field.

## Tests

- Resolver: each shape's signed distance, including under rotation and
  non-uniform scale; priority; ties decided by volume; `false`; `blend`
  weights; two extensions won by different zones for the same subject.
- Reader: the specification's 2.0 and 2.1 examples loading to the same zones;
  a 2.1 document that also carries `KHR_implicit_shapes`; an unknown extension
  name; a missing or out-of-range shape; and a zone with no `extensions`.
- Classification: an object wholly inside, wholly outside, in the `blend`
  band, and crossing the surface, each landing in its case, and a third
  straddled zone being logged.
- Performance: the fill-bound frame timed with zones on and off, under the
  `serial` marker.
- Rendering (GL, red first): a closed box room with an IBL zone inside and a
  wall that crosses the zone boundary. The inside face is darker, the outside
  face is unchanged, an object outside is unchanged, and the water reflection
  sees the same room.
- Audio: the camera outside, crossing `blend`, and inside, giving the expected
  gains; `box_gain` giving the same answers as before for axis-aligned boxes.

## Decided

- The specification works with glTF 2.0 plus `KHR_implicit_shapes`, and with
  glTF 2.1's core `shapes`.
- Audio, mirrors and node visibility are tested against the camera.
- The Parthenon is written as a 2.0 file with `KHR_implicit_shapes`, since
  `trimesh` and `pygltflib` write 2.0. It moves to 2.1 when its tools do.

- The name is `OGLC_zone`. The specification is written so that it could be
  proposed as an `EXT_` later without changing the JSON.
- Something a zone controls is off for any subject outside every zone that
  names it (rule 4). No flag on the target is needed.
- `KHR_lights_punctual` has no scene-level form, so its zone block is
  `{"nodes": [3, 7]}`, naming light nodes, since one light definition can be
  instanced by several nodes.
- Scaling the IBL is the zone's own `environment` property. Borrowed extension
  blocks are used exactly as their specifications define them.
