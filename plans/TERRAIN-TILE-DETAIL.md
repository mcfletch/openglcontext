# Detail baked into the ground tiles

**Goal**: the close-up ground is geometry the *bake* produced — micro-relief and
small rocks meshed into the tile a camera is standing in — and the renderer
draws it as it arrives. The 3D Tiles tree already refines by screen-space error;
this makes that refinement buy *detail* rather than only a denser sampling of the
same smooth function.

What it replaces: `--ground tiles` meshes every tile from one height function at
33 samples across, vertex-coloured. At depth 3 over 2 km that is a sample every
7.8 m at the finest level — coarser than the field terrain's 2 m, and flat-lit,
which is why the tiled ground reads as rough next to the field.

## What the ground is made of

| | Drawn | Driven on, walked on, planted on |
|---|---|---|
| Field ground (today) | one `SplatTerrain` mesh over the whole world | the same `HeightField` |
| Tiled ground (this) | tile glTF, refined and detailed by level | the `HeightField`, unchanged |

**The height field stays** beside the tileset as the analytic surface: colliders,
camera clamping, scatter seating and the bore openings all read it. What the
tiles add is drawn detail, so a bump a player sees at two metres is not a bump
the car feels at two hundred. That is the same split the road already has — the
carriageway is collided against as the swept section, never as the tile's
triangles — and it is what keeps the driven surface from changing under the
wheels as a tile refines.

**The tiles carry plain glTF geometry**, and their material says *ground*: the
renderer blends the world's four detail materials per pixel from the control map
beside the tileset, the way the field terrain already does. The alternative — an
ortho-baked albedo and normal per tile — is standard glTF with nothing special at
draw time, but a 2 km world refined to 128 m tiles is 25–50 MB of texture and
quadruples with each further level, against about 4 MB of shared layer textures
for the whole world.

## The pieces

1. **Engine: ground shading that can draw any mesh.** `SplatTerrain` owns its
   program, its layer array textures, the control map and the baked sun/canopy
   shadow, and draws one mesh with them. Split that into the shared *shading*
   and a *patch* that draws an indexed mesh with it, so a tile's mesh can be
   drawn by the same shading. The fragment shader already works from world XZ
   and needs nothing new; the vertex shader needs the model matrix, since a tile
   is placed by the tileset's transform where the field is not.

2. **Engine: tiles that say they are ground.** A tile's terrain primitive is
   marked at bake time; the tile loader mounts a marked primitive as a ground
   patch sharing the world's shading, and everything else as it does now.

3. **Bake: detail per level.** Each tile is meshed from the height function at
   its own spacing, as now, plus:
   - **micro-relief** — a deterministic function of world position, added to the
     drawn mesh only, with an amplitude bounded by the tile's own geometric
     error, so refining a level never moves the surface further than the error
     the streamer already tolerates;
   - **rocks** — small rock geometry merged into the tile's mesh at the levels
     whose error is under the rock's size. Boulders a car can hit stay props
     with colliders; these are what a hillside is made of, not obstacles.

4. **Bake: the mouth of a bore cut into the tile.** With the ground meshed at
   bake time the opening can be cut exactly, against the portal's own outline,
   instead of against a grid at run time. The run-time mask then has only the
   collider's field to cut. (The run-time cut is in place and works; this is
   where it stops being needed for what is drawn.)

## Decisions taken

- The height field stays as the surface every reader agrees about (collision,
  camera, scatter) -- so detail that is *drawn* goes into it rather than beside
  it. Relief the field cannot carry is relief nothing draws; a stone that is
  drawn is a stone with a body.
- Tile meshes are drawn with the engine's splat shading rather than with a
  per-tile baked texture.
- Detail is bounded by the level's geometric error, so it appears as the tree
  refines and no appearance moves the surface more than the streamer's own
  tolerance.
- A prop says which shape its measurements describe (`Prop.shape`): a `box` is
  a thing that stops you, a `dome` is a thing you go over. Loose stone is the
  second kind, and a block the size of a stone is a kerb across the hillside.

## Order

1. **Split the ground shading out of `SplatTerrain`** — landed.
   `OpenGLContext.scenegraph.terrain.ground` holds `GroundShading` (the program,
   the layer textures, the control map, the baked light) and `GroundPatch` (one
   mesh drawn with it); `SplatTerrain` is a height field's mesh drawn with its
   own ground and nothing else. The vertex shader takes a model matrix, since a
   tile is placed by the tileset's transform where a field is not. What it draws
   is unchanged: rendered against the node as it was, at a fixed frame count,
   the two differ less than either differs from itself run to run.
2. **Ground in the tiles** — landed. A baked ground primitive's material is
   named `ground` (the glTF writer already wrote a material's DEF as its name;
   the loader now reads it back), the tile uploader swaps those primitives for
   patches of the world's ground, and `extras.terrain.drawn` says whether the
   field draws itself or the tiles do. A world whose ground is tiled still
   writes the landscape beside the tileset: the tiles are blended and lit from
   it, and it is what the world is collided against.
3. **Micro-relief, bounded by the level's error** -- landed.
   `OpenGLContext.scenegraph.terrain.Relief` is a band of noise per feature
   size; a surface carries the bands its own sampling can show
   (`samples_per_feature` vertices across a feature), and the whole
   displacement is scaled to fit inside the tile's geometric error.
   `HeightfieldLayer(relief=...)` meshes each tile with its own bands in it,
   and `ProceduralWorld.grain` is what a world carries (`GROUND_RELIEF` by
   default). **The landscape carries it too**: `ProceduralWorld.detailed`
   wraps the height function the landscape is sampled from, at the finest
   tile's spacing and error, so the field a car is driven on and the finest
   tile drawn over it are one surface. `Relief.no_finer_than(spacing)` cuts
   any band the field's grid could not hold before anything draws it.
4. **Rocks in the fine levels** -- landed.
   `OpenGLContext_editor.bake.stones.StoneLayer` strews loose stone over the
   ground and writes what a tile can show as `EXT_mesh_gpu_instancing`
   placements -- one node per shape, however many stones the tile holds. A
   stone appears where the tile's error is no more than `DETAIL` times its
   radius, so a hillside fills in by size as the tree refines, and the stones
   are seated on the surface the tile *draws* -- the relief included -- rather
   than on the height function under it. **They are solid**: each is a
   `Prop` with `shape='dome'`, the whole table travels in `extras.stones`, and
   a game stands the ones near it up with `PropColliders` -- a sphere as wide
   as the stone, sunk until its top stands where the stone's does, so a wheel
   rides over one and a walker stands on one. Its own channel rather than the
   world's `props`, because the two want different reaches: a boulder has to
   stop a car from a long way off (220 m) and a stone only has to be there
   where the wheel is (60 m).

   *Merged* geometry was the plan and placements are what landed. A stone is
   drawn flat-faceted, so twenty faces is sixty vertices, and at forty bytes a
   vertex a tile of a couple of hundred stones is most of a megabyte written
   out as triangles against a few kilobytes written out as placements. Baking
   Beacon tiled at depth 5 measured it: 304 MB merged against 112 MB placed.
   `MOST_PER_TILE` caps what one tile carries, because the tree refines with
   REPLACE and a stone fine enough to draw is written into every level from
   there down.
5. **Cut the bore mouths at bake time** -- landed.
   `RoadPath.bore_openings` gives every mouth in one `holes(x, z)` mask and
   `HeightfieldLayer(holes=...)` cuts the tile's mesh back to it
   (`terrain.holes.cut`), so the opening is the portal's own outline rather
   than a grid's. A tile the opening swallows whole carries no ground. The
   run-time mask stays for the collider's field and for a field-drawn world.
   `BORE_INSET` and `BORE_APPROACH_CELLS` moved into
   `OpenGLContext.scenegraph.roadworks`, so the bake and the game take the same
   numbers from one place.

## What the tiled path still needs, found while wiring it up

Baking Beacon with `--ground tiles` and driving it shows two things that have
nothing to do with the ground's shading and everything to do with the tiled
path's level of detail. Neither is new; both are what "the tiled ground looks
rough" has been made of.

- **The coarse levels draw structures that cannot be drawn.** A tiled world's
  geometric error ladder starts at 94 m where the field world's starts at 3 m,
  so every tile is drawn at a much coarser level for the same screen error --
  including the road's bores and decks, whose geometry at a coarse resampling is
  a two-hundred-metre distortion. On Beacon one of them covered the sky. Fixed
  with a floor under the resampling: `RoadLayer.spacing_for` is capped at
  `COARSEST_SPACING`, because a tube swept along points a hundred metres apart
  is not a coarse tunnel but a shape nothing in the world has.
- **The road's shelf inflates the landscape at coarse levels.** The earthwork
  holds the ground at the height of the nearest stretch of road for a shelf as
  wide as the tile's sample spacing, so that a sample lands inside the corridor.
  At 62 m that is a plateau pinned to whichever stretch of road is nearest,
  which on a climbing or doubling-back road is one far above. Capped at
  `WIDEST_SHELF` road widths, which is enough to put a sample in the corridor
  and not enough to rewrite a hill.

Both landed. Beacon baked tiled at depth 5 draws a landscape -- sky, hills,
forest, stone on the hillsides -- and `glisteel.diagnose` drives it to the
finish with nothing below walking pace and no collision with the world.

## What a tiled world needs from its tree

The detail above is gated on the tile's own sampling, which makes the **depth of
the tree** the thing that decides whether any of it is seen. A world of `extent`
metres meshed at 33 samples a tile has a finest spacing of
`extent / 2**depth / 32`, and its finest geometric error is the root's over
`2**depth`.

At Beacon's `extent = 2048, depth = 3` that is a sample every 7.8 m and an error
of 7.8 m: coarser than the field world's 4 m, and too coarse for any band of the
grain (the widest wants a sample every 6 m) or any stone (the largest wants an
error under 4.5 m). A tiled world wants `depth` chosen so the finest spacing is
the detail it is meant to show -- `depth = 5` over 2 km is a sample every 2 m
and an error of 1.9 m, which carries the two coarsest bands and the upper half
of the stone. That is a decision per recipe, not a default, because it is also
what the bake costs: each level is four times the tiles.

The world is **told** the depth (`ProceduralWorld.depth`, passed by
`glisteel_editor.recipe.world_for`) because `ground_spacing()` is what a
portal's face and the ground cleared in front of it are measured against.
Measured against the root tile -- which is what it answered before -- a tiled
Beacon got a sixty-four-metre headwall and three hundred and eighty metres of
cleared approach at every mouth.

## What driving it taught

The grain and the stone were both written as *drawn* detail first, and making
them collidable is what said whether they were right. Measured with
`glisteel-diagnose --seeds 12`, which drives a world against twelve sets of
traffic, because one lap is chaotic and a change judged from a single
before-and-after is judged from nothing. Beacon, tiled, depth 5:

| grain | finished | mean |
|---|---|---|
| none | 12 of 12 | 98-115 km/h |
| 24 m bands, roughness 0.09 | 3 of 5 | 36-107 km/h |
| 8 m bands, roughness 0.06 | 8 of 12 | 29-113 km/h, 3 mired off the road |
| 8 m bands, roughness 0.03 | 12 of 12 | 98-115 km/h |
| **16 m bands, roughness 0.03, 8 samples a feature** | **12 of 12** | **98-115 km/h** |

The last row is the default, and every seed of it matches the ungrained world
to the tenth of a second. It is the same half-metre of swell as the row above
spread over twice the width -- half the slope -- and sampled eight times across
instead of four, so the collided surface is a swell rather than four flat
facets with a crease at every sample for a wheel to catch.

Four things came out of it:

- **Loose stone costs nothing.** With the stone bodies released the run is
  identical to the run with them standing, byte for byte: the clearing keeps
  them off the road, and a dome a wheel rides over is not an obstacle.
- **The grain was a dune, not a hummock.** A band is as tall as its
  roughness times its own width, so 24 m bands at 0.09 are two and a half
  metres of swell -- terrain, not texture. What a landscape is *shaped* like is
  the height function's job.
- **A road is cleared ground, and cleared ground has no grain.** The fade has
  to start at the edge of the strip the machine went through, not at the edge
  of the tarmac, and it has to follow *height* rather than which structure
  carries the road: a portal and a bridge abutment come up to meet the
  carriageway whatever the stretch is called, and those are exactly where a
  hummock stands in the way. Before that rule the grain stood the hillside
  1.57 m above the carriageway at a portal.
- **The landscape's own grid is the ceiling on felt detail.** Beacon's field is
  a sample every two metres, so of the grain's bands only the coarsest survives
  `no_finer_than`: what the world carries is one 16 m swell of about half a
  metre, which reads as modulation across a hillside rather than as hummocks
  and ruts. Ruts are a metre across, and feeling one needs a surface with
  samples a few tens of centimetres apart near the camera -- a detail surface
  over the field rather than a finer grid over the whole world. That is its own
  piece of work and is not in this one.
