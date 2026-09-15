# Ground cover diversity

**Status: in progress.**

One kind of grass is what the forest floor is made of today. `GroundCover` takes
a single `CoverSpecies`, and the forest demo does not use it at all — it builds
its own richer chain in `scene.py`. This plan makes ground cover a *set* of
plants, moves the demo's chain into the engine so a baked world gets it too, and
brings in a set of CC0 scanned plants to fill it.

## Where the pieces are now

Two chains draw the same thing at different qualities.

`GroundCover` (`scenegraph/vegetation/cover.py`) is the engine's: one species,
one clump-geometry rung, one card disc, re-scattered when the camera has moved
`SETTLED_METRES`. `TilesTerrain._mount_cover` builds one from a baked world's
`cover` record, so glisteel and anything else driving a streamed world gets this
one.

The forest demo's (`openglcontext_forest_demo/scene.py`) is better, and is not
reusable by anything:

- **two** geometry rungs — full detail to `CLUMP_LOD_FRAC * radius`, a coarser
  mesh to `radius` — so the outer four fifths of the disc, which is most of the
  instances, costs a fifth of the triangles;
- **two** card discs — a mid one fading in exactly where the clumps fade out, and
  a coarse far one out to `grass_far_radius`;
- a cached scatter over a disc wider than the drawn one, with the drawn subsets
  re-selected against the *live* camera every frame, so the disc never lags the
  walk;
- live retuning of every radius and density, which is what the quality presets
  move.

A demo carrying that is the wrong way round: it is engine work sitting where no
game can reach it, and where no test can either.

## What is built

### 1. A scatter stream per species

`world_grid_scatter` gains a `salt`, mixed into the cell hash. Each species then
scatters on its own world-anchored grid at its own density — sparse ferns on a
coarse grid, dense grass on a fine one — and no two species contend for a cell.
Determinism and the pop-free property are per species exactly as they were.

The alternative, one scatter partitioned by a per-instance species hash, ties
every species to one grid spacing and makes density a share rather than a figure
in plants per square metre. The cost is the same either way: the cells are the
same cells, divided differently.

### 2. `CoverSpecies` says what a plant is, at both rungs

Added: `clump_far` (the coarse geometry rung), `card_width`, `sun_level`, and
`source_height` — the real height of the plant the model was scanned from, in
metres, so a species' default size is the plant's own rather than a guess.

### 3. `GroundCover` takes a sequence and owns the whole chain

The demo's chain, moved: two geometry rungs and two card discs per species, the
wide cache with per-frame re-selection, and a `retune` for the quality presets.
`GroundCover(field, species)` accepts one species or many; a world record carries
a list.

`scene.py` then constructs one and streams it, and glisteel inherits both the
diversity and the better LOD through `TilesTerrain`.

### 4. Baking a scanned plant into a clump

[Poly Haven](https://polyhaven.com/) publishes scanned plants as glTF under
**CC0**, which is compatible with the BSD terms everything here ships under and
carries no attribution requirement. Credit is given anyway, in
`ASSET-LICENSES.md`, in the pack's `copyright`, and in `CREDITS.txt`.

`OpenGLContext_editor.assets` fetches and bakes them. It is authoring, so it
lives in the editor toolkit: an editor imports it, a shipped game does not.

Four facts decide the shape of the bake:

- **The glTF download has no alpha.** Its base colour is a JPEG, and these plants
  are alpha-cut cards. The mask is published beside the model as its own map
  (`Alpha`, or `opacity`, or `Mask`, depending on the asset), so the bake merges
  it into the base colour and writes one RGBA cutout texture.
- **One file can hold several plants.** `fern_02` is four fern clumps as four
  nodes — four variants for the price of one download.
- **Triangle counts are authored for a render, not a field.** `shrub_04` is
  27,000 triangles for one shrub against the ~500 the shipped clump runs at, so
  the bake decimates with `opengl_decimate`, whose border preservation is what
  keeps an alpha card's silhouette. A bake-time dependency only: nothing
  decimates at runtime.
- **The texture must not be baked in twice.** A 1k RGBA texture is about a
  megabyte, and a variant-and-LOD per file would carry it eight times over. One
  `.glb` per source asset holds every variant and rung against one embedded
  image, and `load_clump_glb` gains a `mesh` selector to choose among them.

### 5. The plants

Seven, from the Poly Haven pine-forest collection: `grass_medium_01`,
`grass_medium_02`, `shrub_01`, `shrub_04`, `fern_02` (four variants),
`nettle_plant` and `periwinkle_plant`.

`dead_tree_trunk_02` is deliberately left out. It is a four-metre fallen log —
scenery, not cover — and a camera-facing card is the wrong far rung for something
that long. It wants the prop or near-mesh path, which is its own piece of work.

### 6. Shipping them

The forest demo's art is a content pack fetched before the first frame. The
baked cover joins it, and the pack goes to **`content-v2`**: one pack holding
everything rather than a second to keep in step.

## Open

- The release asset for `content-v2` has to be built and uploaded to the
  repository's releases before the catalogue entry resolves;
  `tools/release_content.py` builds it and records the digest.
- glisteel's own packs carry the baked cover for its worlds once the editor's
  world bake writes the species list.
