# Ground cover diversity

**Status: landed, less the release upload.**

One kind of grass is what the forest floor was made of. `GroundCover` took a
single `CoverSpecies`, and the forest demo did not use it at all — it built its
own richer chain in `scene.py`. This made ground cover a *set* of plants, moved
the demo's chain into the engine so a baked world gets it too, and brought in CC0
scanned plants to fill it.

## Where the pieces were

Two chains drew the same thing at different qualities.

`GroundCover` (`scenegraph/vegetation/cover.py`) was the engine's: one species,
one clump-geometry rung, one card disc. `TilesTerrain._mount_cover` builds one
from a baked world's `cover` record, so glisteel and anything else driving a
streamed world got that one.

The forest demo's was better, and no game could reach it: two geometry rungs, two
card discs, a cached scatter re-selected against the live camera every frame, and
live retuning for the quality presets. Engine work sitting where no test could
put it under a microscope either.

## What landed

### The engine

**`world_grid_scatter` gained a `salt`**, mixed into the cell hash, so each
species scatters on its own world-anchored grid at its own density and no two
contend for a cell. And a `scale_range`, because the old half-to-full spread
meant a species stating 0.4 m averaged 0.28 m — every plant in the world quietly
smaller than the model it was scanned from.

**`Patches`** turns a species into beds. `patchiness` runs 0 (as likely here as
anywhere) to 1 (thickets with bare ground between) and `patch_metres` is how far
across one is, over a smooth world-anchored field (`world_noise`) so a bed of
nettles is in the same place every time you walk past. Density keeps meaning
plants per square metre: a mask can only *remove* plants, so a patchy species is
scattered on a finer grid and thinned back rather than simply reduced.

**`SplatTerrain.closure` / `canopy_cover`** — how closed the canopy is, 0 open
and 1 a crown deep, *unclamped*. The shading is clamped at `canopy_deepest`, so
past that a stand with gaps in it and a closed one are equally dark; they are not
equally full, and which of the two you are standing in is what decides whether
shrubs grow. `HeightField.canopy_density` is the half of `canopy_shadow` that
already computed it.

**`CoverSpecies`** gained `clump_mesh`/`clump_far_mesh` (which mesh of a file is
which rung), `card_width`, `sun_level`, `patchiness`, `patch_metres` and
`canopy` — the band of tree cover the plant grows under. A plant near the edge of
its band grows, but smaller (`STRAGGLER`).

**`GroundCover`** takes a sequence and owns the whole chain: two geometry rungs
and two card discs per species, the wide cache with per-frame re-selection, a
`retune` for the quality presets, a `density_scale` over the whole set, and the
`compute_*`/`apply_*` split so the scatter can run off the render thread. A
single species is still accepted and means a set of one.

`load_clump_glb` gained a `mesh` selector, by index or name.

### The bake

`OpenGLContext_editor.assets` — authoring, so it lives in the editor toolkit —
with `oglc-bake-plants` over it. Four facts shaped it:

- **The glTF download has no alpha.** The base colour is a JPEG and these plants
  are alpha-cut cards; the mask ships as its own map (`Alpha`, `opacity` or
  `Mask`, per asset), and is merged back in.
- **One file is often several plants.** `fern_02` is four fern clumps in four
  nodes — four variants for one download. `--per-asset` keeps the fullest few,
  by triangle count: the *tallest* tufts of a published grass are its leggy seed
  stalks, which is the one thing a card cannot show.
- **Triangle counts are authored for a render.** `opengl_decimate` brings them to
  a field's budget, in one reduction read off at both rungs. Border preservation
  is what keeps an alpha card's silhouette.
- **The texture must not be baked in twice.** One `.glb` per source asset holds
  every variant and rung against one embedded image.

The billboard is rendered from the geometry itself, so the two agree across the
distance where they cross-fade, and the card is cut to the plant's own aspect
rather than squeezed into a square.

**Downloads and the library's own answers are cached per user**
(`OPENGLCONTEXT_POLYHAVEN`, beside the rest of OpenGLContext's cached assets), so
a re-bake and a second world wanting the same plant ask Poly Haven for nothing.

### The plants

Six, all CC0, from Poly Haven: `grass_medium_01` and `grass_medium_02` (the
carpet, even), `periwinkle_plant` (flowers through the grass), `fern_02` (beds,
in shade), `nettle_plant` (beds, in the thinner cover) and `shrub_04` (thickets,
where the trees stand apart and along the edges of clearings).

`shrub_01` is deliberately left out. It is a 2.6 m hedge strip — 156,000
triangles of separate leaf islands — and at a field's budget the decimator
removes whole leaves and leaves bare twigs. Even at full detail it covers 5% of
its card, because it is a strip rather than a clump. `dead_tree_trunk_02` is left
out as well: a four-metre fallen log is scenery, not cover, and a camera-facing
card is the wrong far rung for something that long. Both want the prop path,
which is its own piece of work.

### The demo and the worlds

`scene.py` constructs one `GroundCover` and streams it; `quality.py` moves
`density_scale` and the three radii through it. The dead config knobs went with
the chain they drove (`clump_density`, `clump_scale`, `grass_mid_*`,
`grass_sun`, `*_length_samples`), replaced by `--cover-density` and
`--grass-card-radius`.

`VegetationLayer.cover` takes a set and writes a `species` list;
`TilesTerrain._mount_cover` reads either that or the bare record a world baked
before this carries. `shipped_cover` reads the demo's `cover.json`, so a
glisteel world gets the same plants.

## Open

- **The `content-v2` release asset has to be uploaded.**
  `tools/release_content.py --tag content-v2` has built `forest-art.tar.gz`
  (65.5 MB, sha256 `f7d7aa99d4d4…`) and written the digest into `packs.json`;
  the file itself has to be attached to that tag on the repository before the
  catalogue entry resolves.
- glisteel's own packs carry the baked cover once its worlds are re-baked.
- The `canopy` bands are in crowns deep, so they are tuned to how densely a
  particular world was planted. The forest demo's runs 0–18. A world planted
  differently wants its own figures.
