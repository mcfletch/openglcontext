# Models in zip archives

Status: planned, 2026-10-26. Follows [OBJ-SUPPORT.md](OBJ-SUPPORT.md).

## Problem

Models are distributed as zips: a model file with its material library,
textures or buffers beside it. `Loader.load('couch-obj.zip')` raises, because
`.zip` has no reader registered, `.gz` covers one file only, and the resolver
reaches files on disk and same-origin URLs only. The sample that raised the
question, `content-samples/couch-obj.zip`, holds `model.obj` (32.8 MB, 288,138
triangles), `model.mtl`, `texture_0.png` and a licence note.

## Design

The change is in the resolver, so every format with sidecar files gains it: OBJ
with MTL and images, glTF with `.bin` and images, X3D and VRML with inlines.

- `Loader.load('x.zip')` opens the archive and reads the one model file in it,
  choosing the reader by that member's suffix. A zip with several model files
  raises `ValueError` listing them; `x.zip#model.obj` names one.
- A `Resolver` over a zip resolves a reference to another member, under the
  rules a directory has: no `..` out of the archive, no absolute path.
- Member and total sizes are checked against the resolver's size limits before
  anything is read, so a zip bomb fails at the limit.
- `SceneLoader` and the viewer take a zip path or URL as any other source; a
  zip served over http is downloaded to the asset cache first.

## Tests

- A zip of an OBJ, an MTL and a texture loads with the texture applied.
- A glTF with an external `.bin` loads from a zip.
- A reference to `../x`, an absolute path or a member outside the archive is
  refused.
- A member declaring more than the limit raises before it is read.
- Two model files in one archive raise naming both; `#name` picks one.
