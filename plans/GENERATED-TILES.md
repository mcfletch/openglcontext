# Generated tiles

Streaming a world that has no `tileset.json`: the tiles are made as the camera nears them.

## Why

`TilesTerrain` reads a baked tileset, so every tile is named before the first frame. An endless world (the
`hill-runner` game's hill) or a world cheaper to compute than to store needs the tree to grow with the camera,
and a game should not rebuild the streaming runtime to get that.

## What landed

- `loaders/tiles3d/generated.py`: `GeneratedTileset` and the `TileGenerator` protocol
  (`keys_near`, `bounds`, `generate`). The root has no content and always refines; children are leaves, made
  within `reach` of the camera and dropped beyond `retain`. The root's sphere is resized to hold its children,
  so frustum culling of the root culls only what is out of view.
- `TileGenerator.origin(key)` (optional): the tile's local origin in world coordinates; the tile's
  `world_transform` is the translation to it and its geometry is built around it, which keeps 32-bit
  vertex coordinates precise far from the world's origin.
- `RuntimeTile.content_key`: a tile made by a generator has no file, and `has_content` is true for it.
- `TilesetRuntime.discard(tile)`: releases a drawn tile, cancels its queued load and ignores one still in
  flight. `pending_uploads` says how many loaded tiles wait for an update.
- `GLTileUploader(own_materials=...)`: a generator's tiles share materials, so releasing a tile deletes its
  meshes and leaves the textures.
- `scenegraph/generatedtiles.py`: `GeneratedTiles`, the node (`update_for_camera`, `prime`, `dispose`).
- `noise.py`: the value-noise hash wraps in 64 bits on purpose; `errstate` stops NumPy reporting it for
  scalar inputs far from the origin.

Tests: `tests/unit/test_tiles3d_generated.py`, `test_generated_tiles_node.py`, `test_vegetation_replant.py`, `test_cover_any_ground.py`, `test_noise_wraparound.py`.
Documented in `docs/tiles3d.rst#tiles3d-generated`.

- `VegetationField.replant`: swaps a forest's table keeping its GL objects, for a world planted a stretch at a time. `GroundCover` takes any ground with `sample(x, z)` (the `Ground` protocol); `GroundCover.relocate` grows it on another ground keeping its nodes, and `dispose` frees its GL objects.

## Open

- A generator's tiles are all leaves. Levels of detail for a generated world (a coarse parent per group of
  tiles) need the generator to say what a parent is.
- `update_for_camera` deletes GL objects, so it needs the context current. `Context.OnIdle` runs without one;
  `hill-runner` brackets the call with `setCurrent()` and `unsetCurrent()`. A context hook that runs with GL
  current each frame would remove the bracket.
