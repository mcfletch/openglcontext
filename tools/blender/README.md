# `oglc_hook` — saying what a thing is, in Blender

A Blender add-on that puts an **Engine Hook** panel on the material and the
object tabs, and writes what it says into the exported glTF as an `OGLC_hook`
extension. OpenGLContext reads that tag as the file loads and makes something of
it: a tagged surface arrives as moving water rather than as a flat blue sheet.
[docs/gltf.html#hooks](../../docs/gltf.html) is the mechanism, and
[docs/water.html#authoring](../../docs/water.html) the `water` kind's parameters.

The same tag can be written with no add-on at all, as a material custom property
called `OGLC_hook` exported with **Include ‣ Custom Properties** ticked. This is
for pipelines that would rather have the extension: it is a form rather than a
JSON string, what it writes is checked as it is typed, and it needs no export
option ticked.

## Installing it

Zip the add-on folder and install the zip:

```bash
python -m zipfile -c oglc_hook.zip oglc_hook/
```

**Edit ‣ Preferences ‣ Add-ons ‣ Install from Disk**, choose `oglc_hook.zip`,
and tick *glTF engine hooks (OpenGLContext)*. Blender 4.0 or newer.

## Using it

On the material tab (or the object tab, for a tag on the node), open **Engine
Hook** and tick it. `water` is the kind the panel has fields for — style,
shading, medium and depth — and the line under the fields is what the file will
carry:

```text
OGLC_hook: {"depth": 6.0, "kind": "water", "style": "choppy"}
```

Any other kind is named in **Kind** and parameterised by **Parameters**, a JSON
object merged over the fields above it: `{"target": "gate-2"}` for a
`twigbb:teleporter`. Export with **File ‣ Export ‣ glTF 2.0** as usual; the
add-on writes the block as each material and each node goes out.

A kind is a name the *application* has bound to a factory, so the engine's own
kinds — `water` — work in `oglc-view` unaided, and a game's own kinds work in
that game. A file naming a kind nothing registered loads as an ordinary shape.

## What is in here

| | |
|---|---|
| `oglc_hook/tag.py` | The rules: panel settings → the `OGLC_hook` block. No `bpy`, so it is ordinary testable code — `tests/unit/test_blender_hook_addon.py` drives it, and holds its vocabularies to the engine's. |
| `oglc_hook/__init__.py` | The Blender half: the properties, the two panels, and the `gather_material_hook` / `gather_node_hook` exporter hooks. |
