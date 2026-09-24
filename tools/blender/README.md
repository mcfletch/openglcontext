# `oglc_hook` — saying what a thing is, in Blender

A Blender add-on that puts an **Engine Hook** panel on the material and the
object tabs, and writes what it says into the exported glTF as an `OGLC_hook`
extension. OpenGLContext reads that tag as the file loads and makes something of
it: a tagged surface arrives as moving water rather than as a flat blue sheet,
a tagged mirror reflects the room in front of it, and a tagged empty with a
fire burning where it stands.
[docs/gltf.html#hooks](../../docs/gltf.html) is the mechanism,
[docs/water.html#authoring](../../docs/water.html) the `water` kind's parameters,
[docs/reflections.html#mirror-hook](../../docs/reflections.html) the `mirror`
kind's, and [docs/particles.html#authored-particles](../../docs/particles.html)
those of `fire`, `smoke` and `sparks`.

The same tag can be written with no add-on at all, as a custom property called
`OGLC_hook` on the material or the object, exported with **Include ‣ Custom
Properties** ticked. The add-on is for pipelines that would rather have the
extension: it is a form rather than a JSON string, what it writes is checked as
it is typed, and it needs no export option ticked.

## Installing it

Zip the add-on folder and install the zip:

```bash
python -m zipfile -c oglc_hook.zip oglc_hook/
```

**Edit ‣ Preferences ‣ Add-ons ‣ Install from Disk**, choose `oglc_hook.zip`,
and tick *glTF engine hooks (OpenGLContext)*. Blender 4.0 or newer.

## Using it

On the material tab (or the object tab, for a tag on the node), open **Engine
Hook** and tick it. **Kind** offers the engine's kinds as you type and takes
any other name in full. Two groups of kinds have fields of their own, and the
line under the fields is what the file will carry:

- `water`, on a material - style, shading, medium and depth:

  ```text
  OGLC_hook: {"depth": 6.0, "kind": "water", "style": "choppy"}
  ```

- `mirror`, on a material or an object - resolution, redraw interval,
  priority and distortion, each written only where it differs from the
  engine's default. On a material the material shades the reflection; on an
  object the object shows only its reflection. The mesh must be flat, and it
  reflects towards the side its faces point:

  ```text
  OGLC_hook: {"interval": 2, "kind": "mirror", "priority": 0.5}
  ```

- `fire`, `smoke` and `sparks`, on an object - scale and density, each
  written only where it is not 1. An empty is the usual object to tag; a
  tagged mesh keeps its mesh and has the effect standing in it too. The
  object's own scale multiplies the effect's.

A kind on the tab the engine does not read it from - a flame on a material,
water on an empty - is drawn in red with where it belongs. Any other kind is
parameterised by **Parameters**, a JSON object merged over the fields above it:
`{"target": "gate-2"}` for a `twigbb:teleporter`, or `{"color": [0.3, 0.6,
1.0]}` for a gas flame. Export with **File ‣ Export ‣ glTF 2.0** as usual; the
add-on writes the block as each material and each node goes out.

A kind is a name the *application* has bound to a factory, so the engine's own
kinds work in `oglc-view` unaided, and a game's own kinds work in that game. A
file naming a kind nothing registered loads as an ordinary shape.
[docs/particles.html#authored-particles](../../docs/particles.html) has the
effects' parameters.

## The lakeside demo

`demos/lakeside.py` builds a small world with the panel: a lake tagged `water`
in a grass basin, a jetty with a brazier (`fire` and `sparks`) and two torches,
and a campfire (`fire` and `smoke`). `demos/lakeside.blend` is that world to
open and look at with the add-on installed; `demos/lakeside.glb` is what it
exports, and `oglc-view tools/blender/demos/lakeside.glb` shows it moving. To
build both again:

```bash
blender -b --factory-startup --python tools/blender/demos/lakeside.py -- \
    --glb tools/blender/demos/lakeside.glb --blend tools/blender/demos/lakeside.blend
```

Its sun is 5 lux (5/683 W/m² in Blender, whose exporter writes 683 lumens to
the watt). `oglc-view` lights a model against a sky of unit brightness, and a
sun at Blender's usual few watts per square metre arrives as thousands of lux
and whites out every lit surface.

## The mirror hall demo

`demos/mirrors.py` builds a hall with the panel: a checkered marble floor, a
large mirror and a corridor of small ones tagged `mirror` on their materials, a
pool tagged `water`, and a round window tagged `mirror` on the object, so it
shows only its reflection. Its surfaces are baked from the engine's procedural
`OpenGLContext.scenegraph.surfaces`, which the script loads by path. To build
it again:

```bash
blender -b --factory-startup --python tools/blender/demos/mirrors.py -- \
    --glb tools/blender/demos/mirrors.glb --blend tools/blender/demos/mirrors.blend
```

Its lamps are 30 candela each (30 x 4π / 683 W in Blender, whose exporter
writes a point light's watts as lumens over the whole sphere).

## What is in here

| | |
|---|---|
| `oglc_hook/tag.py` | The rules: panel settings → the `OGLC_hook` block. No `bpy`, so it is ordinary testable code — `tests/unit/test_blender_hook_addon.py` drives it, and holds its vocabularies to the engine's; `test_blender_hook_addon_in_blender.py` runs the whole add-on in Blender. |
| `oglc_hook/__init__.py` | The Blender half: the properties, the two panels, and the `gather_material_hook` / `gather_node_hook` exporter hooks. |
| `demos/mirrors.py` | The mirror hall, built with the add-on. `tests/unit/test_mirrors_blender_demo.py` holds the shipped `.glb` to it. |
| `demos/lakeside.py` | The demo world, built with the add-on. `tests/unit/test_lakeside_demo.py` loads the shipped `.glb`, and builds it again where Blender is installed. |
