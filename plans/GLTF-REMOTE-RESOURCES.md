# glTF Viewer: Remote Multi-File `.gltf` Support

**Status: RESOLVED** — the viewer now routes http(s) sources through
`gltf.load_gltf_url()` (the resolver-backed URL path) instead of downloading the
single `.gltf` file and loading it locally. A remote multi-file `.gltf` resolves
its external `.bin`/image references against the document origin; a remote `.glb`
still loads unchanged; off-origin references are rejected by the `Resolver`.
Implemented in `bin/gltf_view.py`: `_resolve_source` keeps a URL intact,
`_load_source` branches URL→`load_gltf_url` (disk-cached under the per-user
app-data dir) / path→`load_gltf`, and the single-file `_download` helper is gone.
Verified end-to-end against Khronos `BoxTextured/glTF/BoxTextured.gltf` (external
`Box0.bin` geometry + PNG texture resolve). Tests:
`tests/test_gltf_view_cli.py::TestRemoteSourceRouting`. Original plan below.

---

**Status (original):** Planned

## Problem

The `oglc-gltf` viewer cannot correctly open a remote (`http(s)`) `.gltf` that
references external resources (`.bin` buffers, image textures). It downloads only
the single `.gltf` file to a temporary path and then loads it locally, so the
document's base URL is lost and its relative external references cannot be
resolved. The model loads with missing geometry and/or textures.

A self-contained binary `.glb` over a URL works fine, because it embeds all of
its resources.

## Why it is this way

The viewer's URL path (`OpenGLContext/bin/gltf_view.py`, `_download()`) was
written for the common self-contained `.glb` case: fetch one file, hand the local
path to `load_gltf()`. The single-file downloader never grew base-URL-relative
resource resolution.

The capability already exists in the loader. `OpenGLContext.loaders.gltf`
provides `load_gltf_url(url, cache_dir=None)`, which resolves external buffers and
images relative to the document URL and confines them to its origin (the
`_Resolver` same-origin / size-cap policy). The viewer simply does not use it for
URL sources.

## Fix

Route URL sources in the viewer through `load_gltf_url()` instead of
`_download()` + `load_gltf()`:

- In `gltf_view.py`, when the source is an `http(s)` URL, call
  `gltf.load_gltf_url(url)` (optionally with a cache directory) rather than
  downloading a single file.
- Keep the local-file path (`load_gltf()`) unchanged.
- Remove or repurpose `_download()` once nothing depends on it.

## Considerations

- **Caching.** `load_gltf_url()` accepts a `cache_dir`; decide whether the viewer
  should cache downloads (e.g. under a user cache dir) so repeat views are fast
  and offline-friendly.
- **Security.** The existing same-origin and size-cap policy (`_Resolver`) already
  guards resource fetches; the viewer should surface a clear error when a resource
  is rejected rather than failing silently.
- **Progress / errors.** Multi-file fetches can be slow or partially fail; report
  which resource failed.

## Tests

- Load a known multi-file `.gltf` (e.g. a Khronos `glTF/` variant, not
  `glTF-Binary/`) from a URL and assert buffers and textures resolve.
- Confirm a `.glb` URL still loads unchanged.
- Confirm an off-origin external reference is rejected by the resolver.
