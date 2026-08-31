# 3D Tiles: viewing a city-sized dataset

**Status: 🟡 In progress — the feature is marked experimental in
[docs/tiles3d.html](../docs/tiles3d.html#tiles3d).**

A real, city-sized OGC 3D Tiles dataset now loads, streams, is walkable and is
documented end to end, from OpenStreetMap to the viewer. This records what
landed, what is still wrong, and what each open fault probably is, so the next
session starts from evidence rather than from the symptom.

The dataset it was all measured against is `toronto-3dtiles/` beside this
checkout: Toronto from High Park to the Don Valley and St Clair south to the
Islands, 83,064 buildings in 436 content tiles plus 241 ground-only tiles,
map-textured ground, 50 MB. It passes the reference `3d-tiles-validator` with no
errors or warnings, and its own `verify_tileset.py` checks every tile's geometry
against the tile it claims to be.

## What landed (2026-08-04)

Each with tests, red first.

| Change | Why |
| --- | --- |
| `asset.gltfUpAxis` honoured (`tileset.gltf_up_axis_matrix`, `RuntimeTile.content_transform`) | glTF content is Y-up and a tile frame is Z-up. Without the conversion every conforming dataset renders on its side — measured: the buildings' height axis was 90° from local up |
| Geospatial datasets levelled as well as recentred (`tileset.level_matrix`) | An Earth-centred dataset otherwise arrives as a tilted slab in a Y-up viewer |
| `framing.look_from` aim corrected | The pitch was composed in the camera's frame rather than the platform's, so `--eye/--look-at` aimed as far above the target as it should have been below. The Sponza conformance baseline was re-blessed; it had been blessed with the fault |
| Movement speeds scale with the framed scene (`sceneviewer.MOVEMENT_REFERENCE_RADIUS`), including the free-fly manager's `STEPDISTANCE` | Speeds are scene units a second, and free-fly does not go through the movement modes at all: it stepped a fixed 0.25 units a press, which is 25 cm in a 15 km city whatever the settings screen said |
| `FlyMode.boostSpeed`, held with shift | Crossing a world is not the same activity as looking at a thing |
| A streamed dataset opens over its content (`adapters/tiles.opening_pose`, `opening_aim`) | Fitting the bounding sphere put the camera 19 km out, where the city is a smudge and every tile is at its coarsest |
| A metric dataset gets a human avatar (`ViewerScene.metric`, `SceneViewerMixin.physicsAvatarScale`) | The avatar was a fortieth of the longest side — a 320 m giant standing above the rooftops, which is what "`g` does nothing" looked like |
| A dataset is turned into the viewer's frame (`tileset.Z_UP_TO_Y_UP`), and the bakers (`procedural`, `sample`) write conformant Z-up bounding volumes | Honouring `gltfUpAxis` without also turning the *dataset* left every local tileset on its side — caught on the Cesium 1.1 samples, which had rendered correctly before. A geospatial dataset is levelled at its reference point; a local one has no reference point, so its Z-up frame is turned to Y-up |
| `g` drops in from the camera in a *world* (`PhysicsWalkMixin.physicsDropIn`, set by the viewer for any dataset it may not re-centre) | The spawn searched from the centre of the world bounds — several kilometres away, over the lake. A *model* keeps the search: its camera is outside the thing, over nothing |
| The opening stand-off follows the tile aimed at (`OPENING_TILE_DISTANCE`) | A fraction of the dataset radius is right for a city spread over its extent and inside the geometry for a dataset that is one object in a wide bounding volume — the Cesium dragon opened within its own neck |

### Caught on the way

The up-axis conversion, landed first, put every *local* tileset on its side —
the Cesium 1.1 samples included, which had rendered correctly before. Honouring
`gltfUpAxis` is only half of it: the dataset's own Z-up frame has to be turned
into the viewer's Y-up world as well, which for a geospatial dataset is the
levelling and for a local one is a quarter turn. The bakers here
(`procedural`, `sample`) now write conformant Z-up bounding volumes to match,
which leaves their terrain exactly where it was.

## Open faults

Reported from a live session on 2026-08-04, in the order they bite.

### 1. Geometry floating above its ground

In places the buildings render well above the ground quad they stand on, as if
the tile's content were lifted. The ground quads sit at elevation 0 in the same
tile frame as the b3dm, so the two should coincide.

Worth checking first: whether those tiles are the ones whose **`region`
bounding volume** and **transform** disagree — a region volume is datum-fixed
and ignores the tile transform, so a tile placed by transform and bounded by
region can be drawn consistently and *bounded* wrongly, which is also a
candidate for fault 4. `verify_tileset.py` compares content against tile
extents and reports no problem, so the discrepancy is likely introduced on the
viewer side (the composed `content_transform`) rather than in the export.

### 2. One tile far from the rest

A single tile renders far out from the body of the dataset, with empty space
between — possibly High Park or another park at the western edge. Either its
transform is being composed against the wrong parent, or the export placed a
tile whose sub-tileset it does not belong to. Both are testable offline: the
tile's ECEF centre against its own tile coordinates.

### 3. Walking and running are far too slow

3 m/s and 6 m/s are correct for a person and useless for crossing a city on the
ground. What is missing is a **way to change the base speed at run time** —
either a driving/vehicle movement mode, or speed up/down keys bound in the
viewer (`[` and `]` are taken by the animation controls; the legacy `Direct`
manager binds them to `faster`/`slower` and is shadowed).

### 4. The initial load fetches the whole dataset

Opening the tileset appears to load every tile at once rather than the ones the
opening view needs. Suspects: the generator gives every tile the same
`geometricError` (512) with `refine: ADD`, so screen-space error cannot
discriminate between them; and the priming rounds in `adapters/tiles._prime`
run before the first frame with no frustum, so nothing is culled. Both are
cheap to test — `build_local_tileset.py` in the sample already writes a proper
error ladder (root 2048 → group 128 → leaf 0) and can be compared directly.

### 5. Rendering is slow — 30 fps or worse

At city scale with everything resident. Each tile is a separate draw with its
own material; 436 building tiles plus 672 ground quads, each ground quad with
its own 512×512 texture, is over a thousand draws and a thousand textures. The
measurements to take: draw-call count per frame, resident tile count, and
whether the cost is in the passes or in the paging.

### 6. A tileset may name unboundedly many tiles

Every payload is size-capped and the resident set is held to the memory budget,
but nothing caps how many tiles a tileset names, so a hostile one can fill the
on-disk fetch cache. The containment rules cover *where* a tileset may reach
(`loaders/resolver.py`) and *how big* each payload may be; total fetched bytes
and cache size are not bounded. Raised 2026-08-04 while re-reading the
"what a tileset is allowed to reach" documentation, whose wording implied the
root URI's *content* was trusted -- it is not, and the page now says so.

## Next

1. Fix 1 and 2 — wrong geometry is worse than slow geometry.
2. Give the viewer a run-time speed control (3), which also makes the rest
   easier to explore while investigating.
3. Then the streaming and performance work (4, 5), measured before changed.
   Fault 4 and item 6 share a remedy: a bound on how much a dataset may pull.
4. Drop the experimental marker when a city-sized dataset opens on the tiles
   the view needs and holds a frame rate worth flying at.

## Related

- [TERRAIN-SYSTEM.md](TERRAIN-SYSTEM.md) — the streaming runtime this builds on.
- [docs/osmcity.html](../docs/osmcity.html) — how to prepare a
  tileset, and the worked Toronto export.
- `toronto-3dtiles/README.md` — the sample, its licence (ODbL) and its build.
