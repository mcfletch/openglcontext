# Draco Mesh Compression Support

**Status: ✅ Complete.** Implemented in
[`OpenGLContext/loaders/gltf/draco.py`](../OpenGLContext/loaders/gltf/draco.py)
(soft `DracoPy` import; decode + warn-and-skip fallback), wired into the primitive
decode path in `loaders/gltf/meshes.py`, with tests in
[`tests/test_gltf_draco.py`](../tests/test_gltf_draco.py) (synthetic round-trip, the
missing-library skip path, a self-contained render, and the Khronos Duck Draco
variant checked against the uncompressed model). `DracoPy` is the optional
`OpenGLContext[draco]` extra.

**Goal**: Decode Draco-compressed glTF geometry via the `KHR_draco_mesh_compression`
extension, using the optional [`DracoPy`](https://pypi.org/project/DracoPy/) library
when it is installed. Draco-compressed `.glb`/`.gltf` assets are common in the wild
(and in the Khronos sample set) and currently fail to load because the loader can't
decode the compressed buffer views.

## Approach

Treat DracoPy as a **soft dependency**: detect it at import time, and only advertise
Draco support when present. When a Draco primitive is encountered and the library is
missing, log a clear message and skip that primitive (or fall back to any uncompressed
attributes) rather than crashing the whole load.

```python
try:
    import DracoPy
    HAVE_DRACO = True
except ImportError:
    HAVE_DRACO = False
```

## How KHR_draco_mesh_compression works

For each mesh primitive that uses the extension:

- `primitive.extensions["KHR_draco_mesh_compression"]` supplies a `bufferView`
  (the compressed blob) and an `attributes` map of semantic → Draco attribute id.
- The `bufferView` bytes are handed to the Draco decoder, which returns decoded
  vertex positions, normals, texcoords, colors, and the index list.
- The primitive's top-level `attributes`/`indices` accessors still describe
  component type, count, and (for POSITION) min/max, so they must be reconciled with
  the decoded arrays — the extension spec says the accessor is authoritative for
  type/normalization, the Draco stream for the actual values.

`DracoPy.decode(bytes)` returns an object exposing `points`, `faces`, and per-attribute
arrays; map its output back onto the accessor semantics the loader already uses.

## Implementation

1. **Detection** — add the soft-import guard in the glTF loader
   (`OpenGLContext/loaders/gltf.py` or wherever `KHR_*` extensions are dispatched)
   and register `KHR_draco_mesh_compression` in the supported-extensions list only
   when `HAVE_DRACO`.

2. **Primitive decode path** — when a primitive carries the extension:
   - read the compressed `bufferView` slice,
   - `DracoPy.decode(...)`,
   - build the interleaved/parallel attribute arrays the existing mesh path expects
     (reusing the accessor metadata for dtype and normalization),
   - synthesize the index array from the decoded faces.

3. **Fallback** — if `not HAVE_DRACO`, warn once per load and skip the primitive; the
   rest of the scene still loads.

4. **Docs** — note the optional dependency (`pip install DracoPy`) in the glTF loader
   docs and, if we keep an extras list, add a `draco` extra.

## Testing

- Unit test with a small Draco-compressed `.glb` from the Khronos sample assets
  (e.g. `2CylinderEngine` / `Duck` Draco variants) — assert vertex/face counts match
  the uncompressed variant within tolerance.
- Test the missing-library path by monkeypatching `HAVE_DRACO = False` and asserting a
  clean skip + warning, no exception.
- Add the Draco sample(s) to the glTF regression/demo roster once decoding is green.

## Cross-references

- [GLTF-COMPLETE-SUPPORT.md](GLTF-COMPLETE-SUPPORT.md) — Draco is one of the remaining
  gaps to full Khronos-sample coverage.
- [GLTF-FULL-FEATURE-CONFORMANCE.md](GLTF-FULL-FEATURE-CONFORMANCE.md) — several roster
  models ship Draco-compressed variants.
