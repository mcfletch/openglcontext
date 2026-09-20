# What a frame costs per object

**Status:** A to E 🟢 complete (A-D 2026-09-19, E 2026-09-20); F 🔴 withdrawn 2026-09-20, the figure it rested on being a whole-run total read as a per-frame rate. The per-object slope is **24.7 -> 10.6 µs** with a still camera and 22.7 -> 11.6 with it moving, so the gain grows with the world: 1.5x at fifty objects, **2.3x at sixteen hundred**. The bust gallery goes 5.26 -> 2.57 ms a frame. See [How it scales](#how-it-scales).

A scene of three hundred objects costs about **5 ms of processor time a frame
before anything is drawn**, and the cost is very nearly linear in the number of
objects rather than in what is in them. That is a ceiling of ~200 frames a
second at three hundred objects and ~30 at two thousand, on a machine whose GPU
is doing almost nothing.

This is not a rendering problem. It is the same per-object Python work being
done two and three times a frame, a memo that never hits, and a per-caster
numpy loop where a single batched call would do.

## What was measured

The bust gallery (`docs/lod.html#demo`): a hall, 120 plinths, 120 busts, 30
beams — about 300 objects, of which 108 busts and their plinths are on screen.
Radeon 8060S (radeonsi), 1280x720. Frame time is measured by rendering the same
scene at two frame counts and dividing the difference by the difference, so
process start-up and scene load cancel.

| Scene | ms/frame |
|---|---|
| 120 busts, no LOD, no shadows | 2.20 |
| 120 busts, 6-level LOD, no shadows | 3.10 |
| 120 busts, no LOD, shadows | 3.81 |
| **120 busts, 6-level LOD, shadows** | **5.01** |
| 4 objects (a two-block test scene) | **0.59** |

Three facts follow, and each was checked on its own:

- **It is not fill.** The same world renders in the same ~5.2 ms at 640x360, at
  1280x720 and at 1920x1080. Nine times the pixels, no change.
- **It is not geometry.** Cutting the busts from 103,536 triangles to 39,460 —
  62% — moved the frame from 4.96 ms to 4.93, which is inside the run-to-run
  spread. (The same change is worth 2.4x on a software rasteriser, where
  geometry *is* the bottleneck; that is what says the two are separable.)
- **It is the object count.** Four objects cost 0.59 ms and three hundred cost
  5.01, which is about **15 microseconds of processor time per object per
  frame**.

## Where the time goes

`cProfile` over 300 frames, sorted by cumulative time inside `_flat.Render`.
The profiler roughly triples the frame, so the *shares* are what to read:

| | share of the frame |
|---|---|
| `shaderRenderOpaque` | 27% |
| `renderShadowMaps` | 25% |
| `renderSet` | 20% |
| `selectLevels` | 17% |

and by self time, the top entries are `vrml/nodepath.py:__getitem__` (959,000
calls in 300 frames — 3,200 a frame), `shadowmixin._casterGeometry`,
`numpy.asarray` (612,000 calls), and `_flat._boundingArrays`.

Subtracting the configurations above gives the same picture in milliseconds:

| | ms/frame | of 5.01 |
|---|---|---|
| Shadow caster gathering and the depth passes | ~1.7 | 34% |
| Level-of-detail selection, 120 nodes | ~1.0 | 20% |
| Everything else per object (bounding, frustum, sort, submit) | ~1.6 | 32% |
| The fixed cost of a frame at all | ~0.6 | 12% |

## A. The shadow caster memo never hits — 🟢 landed 2026-09-19

Measured after: `_occluderPoints` **1.56 → 0.15 ms**, the memo's hit rate
**0 → 99.1%** (29,760 hits against 276 misses over 120 frames, the misses being
the first two frames' populate), and the frame **5.05 → 3.65 ms** — 198 to 274
frames a second. The whole glTF conformance suite is unchanged, which is what
says no pixel moved.

The account below is what was found; what was done about it is at the end of the
section.


`ShadowMapMixin._casterWorldGeometry` keeps a per-caster memo so that "a game
has one car moving through several hundred still trees" does not re-derive the
trees. **It has a hit rate of zero.** Counted on the gallery:
`_casterGeometry` runs **250.3 times a frame**, which is once per caster, every
frame, for a scene in which nothing moves.

The key is `(id(tmatrix), id(bvolume))`. The bounding volumes are stable — the
same scene shows only **10 distinct `bvolume` ids** — but `tmatrix` comes from
`_flat._worldMatrices`, which writes into a reused `(N,4,4)` buffer and hands
out `matrices[index]`: a **fresh view object every frame**. Its `id` is never
the one the memo stored, so every lookup misses and every caster is derived
again.

Two changes, either of which pays:

1. **Key it on something that lasts.** A `NodePath` is stable between
   re-flattens, so `(id(path), id(bvolume))` identifies a caster across frames.
   Movement still has to invalidate it: keep the 4x4 in the entry and compare it
   with `np.array_equal` on a hit — 250 comparisons of 16 doubles a frame
   against 250 derivations.
2. **Derive them all at once.** `_casterGeometry` runs per caster: an
   `asarray`, a concatenate, a 4x4 matmul over 8 points, a `min` and a `max`.
   For 250 casters that is well over a thousand numpy calls a frame on arrays of
   eight rows, which is the shape where numpy's per-call overhead is the whole
   cost. Stack the local corners into `(K,8,4)` and the matrices into
   `(K,4,4)`, one `matmul`, then `min`/`max` over axis 1 — three calls instead
   of thousands, and it removes the memo's reason to exist for the static case
   as well.

Do (2) first: it is a smaller change, it is not conditional on a cache being
correct, and it makes the moving case fast too.

### What landed

Both, and a third thing that turned out to be the actual defect.

The memo's key was never wrong: `_shadowCasterRecords` builds its records from
`path.transformMatrix()` and its ids *are* stable, which is why
`_refreshCasterData` was already reusing last frame's answer and cost 0.31 ms.
Every miss came from the **other** caller. `_occluderPoints` is handed the
camera's render set, and `renderSet` filled the matrix slot from a row of the
`(N,4,4)` buffer `_worldMatrices` refills each frame — the same numbers, a new
object every frame. So the one path that ran 250 times a frame missed 250 times.

- `_worldMatrices` now returns the stacked buffer **and** the matrix objects as
  the transform cache handed them over. The stack is still what the camera
  product and the frustum test run on; the objects are what goes in the record,
  so identity means what every memo downstream reads it as meaning.
  `tests/unit/test_per_frame_gather.py` holds the gather to that directly,
  rather than leaving it to be noticed as a slow frame.
- `shadowmath.world_bounds(points, matrices)` places `K` point sets by their own
  matrices and boxes each, in one pass. `_casterGeometryBatch` gathers a scene's
  volumes by point count — a scene of boxes is one group — and
  `_casterWorldGeometry` derives a frame's misses together.
- `_casterGeometry` is that batch with one member. That is safe *here* because
  nothing on a frame's path calls it — it is the one-caster form the tests check
  the batch against. Where the one-at-a-time form is itself hot, writing it as
  its plural with one member costs more than it saves; see the note at the end
  of B.

## B. Level-of-detail selection is a Python loop over a matrix walk — 🟢 landed 2026-09-19

Measured after: `selectLevels` for 120 nodes **1.20 → 0.93 ms** with the camera
moving every frame, and **→ 0.40 ms** where nothing has moved. The frame goes
**3.65 → 3.38** with the camera moving and **→ 2.86** with it still. Cumulative
with A: **5.05 → 2.86 ms** still, **→ 3.38** moving.


`_flat.selectLevels` costs **~1.0 ms for 120 nodes — 8 to 10 microseconds
each**, to decide a number that is usually the number it decided last frame.
For each node it calls `path.transformMatrix()`, `dot`s it with the camera
matrix, and works out a distance and a coverage in Python.

- **The matrices are already to hand.** `renderSet` calls `_worldMatrices` over
  every rendering path in the same frame and stacks them. The LOD paths are a
  subset. Compute the stack once per frame and let both read it.
- **Distance is one expression over an array.** With the world matrices stacked,
  every LOD node's centre, distance and coverage is a handful of vectorised
  operations rather than 120 trips through Python. Only the nodes whose level
  actually changed then need `show()` called on them, which is the part that has
  to stay per node because it fires a signal.
- **A still camera changes no levels.** When neither the view matrix nor any
  LOD's world transform has changed since the last frame, the answer is last
  frame's answer. How often that holds depends on the application; it is free to
  check and it costs a matrix comparison when it does not.

### What landed

- `lod.viewer_distances`, `lod.uniform_scales` and `lod.screen_fractions` are
  the plural forms. `selectLevels` stacks the nodes' world matrices, puts them
  through the camera in one product, and hands each node its own distance and
  scale. Each has a singular form beside it written in its own terms, and what
  keeps the pair honest is that each is tested against the other rather than
  implemented in terms of it — see below.
- `LOD.selectAt(distance, scale, tangent)` is what the pass calls: the node is
  left the part that is genuinely its own, which threshold the coverage falls in
  and whether the change is worth announcing. `selectFor(modelview, tangent)`
  stays as the single-node entry point, and is that call with the two numbers
  worked out from the one matrix.
- `_levelsAlreadyChosen` is the still-scene shortcut, and on a static camera it
  is the larger half of the win. It compares the path generation, the camera,
  and each node's world matrix **by identity** -- which is what the transform
  cache guarantees. The matrices are kept rather than their `id`s: a freed
  matrix's address can be handed to the one that replaced it, and a comparison
  against an address nothing holds would read a move as a stillness.

The stack is the LOD paths' own rather than a slice of `renderSet`'s, because
`selectLevels` runs *before* the gather -- it has to, since a level change
replaces a subtree the gather then walks. What is left in it is `path[-1]` and
`path.transformMatrix()` per level-of-detail path: 0.40 ms of the frame, and C's
to remove.

**A singular form is not its plural with one member.** Written that way first,
`screen_fraction` — a float multiply and a comparison — became two
`np.asarray` calls, a `np.maximum`, a `np.minimum` and a `np.where` to work out
one number, and `LOD.selectAt` asks it once per object per frame: 2.61 µs
against 0.168, and 4.5 ms of a 1600-object frame. Delegating was meant to stop
the two drifting apart, and what actually stops that is the test that asserts
they agree (`TestTheWholeSceneAtOnce`), which costs nothing at run time. Each
form is now written in the terms that suit it. The array form earns its numpy
calls over several hundred objects; over one it spends them doing arithmetic a
float multiply had already done.

## C. The same paths are walked three times a frame — 🟢 landed 2026-09-19

Measured after: `transformMatrix()` **680 → 404** calls a frame and
`nodepath.__getitem__` **3,199 → 2,648**; `_refreshCasterData` **0.27 → 0.05 ms**
and the merged walk **1.20 → 1.08**. A fourth change, in pyvrml97, took the
remaining `__getitem__` calls from 0.144 µs to 0.053.


`nodepath.__getitem__` is called **3,200 times a frame**: `renderSet`,
`selectLevels` and the shadow caster gather each walk the scene's paths
independently, and each asks for world matrices and bounding volumes the others
have already asked for.

Compute **one per-frame path table** — world matrix, bounding corners, whether
it draws — and have the three read it. `_boundingArrays` already says in its own
docstring that the node's volume cache "is where that question is already
answered correctly; this only stacks the answers": so the stack can be kept
between frames and only the rows whose volume cache version moved need
rewriting.

### What landed

`gatherPaths()` walks the scene once and publishes a `GatheredPaths` table --
paths, nodes, stacked matrices, the transform cache's own matrix objects,
volumes, corners, and the `bounded`/`drawing` masks. `_boundingArrays` and
`_worldMatrices` were two loops over the same paths and are now that one walk.
`renderSet` reads the table, and so does `_shadowCasterRecords`, which had been
asking every path for its node, its matrix and its volume a second time.

`takeGather()` rather than a plain attribute, because the table is only true for
the frame that built it: one left lying about would answer next frame's
questions with last frame's transforms and nothing would say so. Taking it makes
that impossible -- a caller that finds none walks the scene itself. Keeping the
table as an ordinary cache was written first and was wrong for exactly this
reason: `tests/unit/test_shadow_caching.py` caught it as a moved caster whose
shadow geometry was never re-derived.

The cost that remains is the walking itself: `path[-1]` is how every pass
reaches the node it is about to draw, and 2,648 of them a frame made
`nodepath.__getitem__` the largest self-time entry in the profile. The override
is there so that a slice of a path is a path; nothing about an integer index
needs it, and it was building a `super()` object on every lookup. Testing for
the slice first and going through `list.__getitem__` leaves the common case at
0.053 µs against 0.144. That is a **pyvrml97** change (`vrml/nodepath.py`), not
this project's, and it is where the cost actually is.

What is **not** done: `selectLevels` still asks its 120 paths for their
matrices, because it runs before the gather and has to -- a level change
replaces the subtree the gather then walks. Sharing there would mean gathering
twice or choosing levels from last frame's placement.

## D. Keep a number on it — 🟢 landed 2026-09-19


None of the above is visible from a suite that asserts pixels. A benchmark that
reports ms/frame for a scene of N objects — the gallery is one, parameterised by
`--bays` — makes the ceiling a tracked figure rather than something rediscovered
when a world gets big. `tests/unit/test_instancing_performance.py` is the
pattern: it compares wall-clock frame times and carries the `serial` marker so
it gets the machine to itself, which anything measuring a clock has to.

### What landed

`tests/unit/test_per_object_frame_cost.py` over
`tests/helpers/_frame_cost_harness.py`: a field of shadow-casting
level-of-detail chains, rendered at 60 objects and at 360, with the slope read
off the difference so the fixed cost of a frame cancels.

It tracks the milliseconds, but what it *asserts* hardest is the **work**, which
is the same number on every machine:

| | still | what a regression does |
|---|---|---|
| world matrices asked for | one per path | 3 per object when the caster pool walks the scene again |
| caster geometry derived | none | one per caster per frame when the memo's key moves |
| level choices made | none | one per frame with the shortcut refused |

Each of the three was checked by putting the defect back: the memo keyed on the
buffer row again gives 200 derivations a frame against 0 and costs 0.52 ms at
200 objects; the shortcut refused gives 1 choice a frame and costs 0.93 ms; the
caster pool walking the scene itself gives 602 matrices against 402. All three
turn their assertion red.

The ms/frame check keeps `performance` as well as `serial`, and its ceiling is
deliberately loose — 45 µs an object against a measured ~13 — because what it
is there to catch is a per-object cost coming back, which shows as a multiple.
The counts are the tight gate.

The still-against-moving check is loose for the same reason, and has to be: a
still frame and a moving one draw the same scene, so the two medians land
within noise of each other — 5.66 ms against 5.61 at 360 objects in one run —
and a strict ordering between them decides on that noise rather than on the
engine. `STILL_MARGIN` is 10%, which a still path that stopped taking its
shortcuts would clear several times over.

## How it scales

The frame time is very nearly linear in the object count, so the figure that
decides how big a world can get is the **slope** — what one more object adds to
every frame — and that is what this was for. The gallery's 2x is one point on
that line; the line itself is what follows.

Measured on D's harness, 50 to 1600 shadow-casting level-of-detail chains, each
count timed turn about against the same count on the other tree so load affects
both alike. Three rounds of 80 frames each, medians, on an idle machine, with
A to E all in.

**Camera still** (the shortcuts apply):

| objects | before | after | | fps after |
|---:|---:|---:|---:|---:|
| 50 | 2.11 ms | 1.37 | 1.53x | 728 |
| 100 | 3.93 | 1.92 | 2.05x | 522 |
| 200 | 6.41 | 3.56 | 1.80x | 281 |
| 400 | 10.60 | 5.46 | 1.94x | 183 |
| 800 | 20.11 | 9.66 | 2.08x | 104 |
| 1600 | 40.90 | 17.96 | **2.28x** | 56 |

**Camera moving every frame** (nothing from last frame can be reused):

| objects | before | after | | fps after |
|---:|---:|---:|---:|---:|
| 50 | 2.47 ms | 1.63 | 1.51x | 613 |
| 100 | 4.19 | 2.71 | 1.55x | 370 |
| 200 | 6.18 | 3.94 | 1.57x | 254 |
| 400 | 10.44 | 6.02 | 1.73x | 166 |
| 800 | 19.84 | 10.97 | 1.81x | 91 |
| 1600 | 37.83 | 19.83 | **1.91x** | 50 |

Least squares over the whole sweep:

| | slope | fixed cost |
|---|---|---|
| before, still | 24.68 µs an object | 1.05 ms |
| **after, still** | **10.61 µs** | 1.08 ms |
| before, moving | 22.67 µs | 1.59 ms |
| **after, moving** | **11.59 µs** | 1.43 ms |

**The slope is halved: 2.33x still, 1.96x moving.** That is the result the
frame-time figure follows from, and it is why the speedup *grows* with the
object count rather than shrinking — 1.53x at fifty objects, 2.28x at sixteen
hundred. A fixed cost that stays fixed matters less the bigger the world gets;
a slope that halves matters more.

In the terms this plan opened with — "a ceiling of ~200 frames a second at
three hundred objects and ~30 at two thousand" — two thousand objects now
extrapolate to about **45 frames a second** against the measured 20.

### What the slope is still made of

At 1600 objects, by what the profile counts per frame. Neither of these is
level-of-detail's, and neither was in A to D; they are E and F below.

- **`path[-1]`, 17,500 times** — about eleven per object, across seven
  consumers that each walk a record to the node it ends at. That is E, and it
  was worth having.
- **`cache.depend_signal`, 2,000 times** — which turned out not to be a
  per-frame figure at all. That is F, and it was withdrawn.

## What it was worth

The estimate was 5.0 ms going to somewhere near 3.0–3.5. The measured answer is
**5.26 → 2.57 ms, a 2.05x speedup**, 190 frames a second to 389.

| the gallery, 300 objects, 1280x720 | ms/frame | fps |
|---|---|---|
| before | 5.258 | 190 |
| after | 2.569 | 389 |

Measured by rendering the same world at two frame counts and dividing the
difference by the difference, so start-up and scene load cancel; the two trees
were timed **turn about** over eleven rounds rather than one after the other, so
a machine that gets busier during the run moves both readings together instead
of favouring whichever went second. The two spreads do not overlap (4.945–5.492
against 2.327–2.763), and a separate seven-round run gave 2.07x.

Where it went, per frame:

| | before | after |
|---|---|---|
| `_occluderPoints` (shadow fit) | 1.56 ms | 0.15 |
| `selectLevels`, 120 nodes | 1.20 | 0.40 still / 0.93 moving |
| `_refreshCasterData` | 0.27 | 0.05 |
| the walk itself | 1.20 | 1.08 |
| `transformMatrix()` calls | 680 | 404 |
| `nodepath.__getitem__` calls | 3,199 | 2,648 |
| caster memo hit rate | 0% | 99.1% |

**A still camera is the best case, and it is not the only case measured.** With
the camera moving every frame, so that nothing worked out last frame can be
reused, the per-object slope goes from **22.2 µs to 16.1 µs** — measured on D's
own harness between 60 and 360 objects — and 360 objects go from 9.89 ms to
6.71.

**Nothing here changes a pixel**, and the whole glTF conformance suite is what
says so: 10,025 tests pass, with the baselines untouched.

**The frame is still not fill-bound.** The same world renders in the same time
at 640x360, 1280x720 and 1920x1080 after the change as before it — nine times
the pixels, no difference. What was removed was processor time, and what is left
is processor time too: the draw-set work that is still per record (the sort key,
the material grouping, the instancing grouping) is where the next of it is.

## E. Every reader walks the record back to its node — 🟢 landed 2026-09-20

A render record is `(sortKey, mvmatrix, tmatrix, bvolume, path)`, and what
almost every reader of one actually wants is the node at the end of that path.
So each of them asks for it, and `path[-1]` is a Python `__getitem__` on a
`list` subclass:

| asks `path[-1]` | times a frame at 1600 objects |
|---|---:|
| `instancing.record_placements` | 7,207 |
| `_flat.selectLevels` | 1,600 |
| `_flat._walkPaths` | 1,600 |
| `instancing.build_instance_groups` | 1,596 |
| `shadowmixin.renderShadowMaps` | 1,370 |
| `flateffects.transmissiveRecords` | 1,369 |
| `_flat._materialSortKey` | 1,369 |
| `instancing.group_material_table` | 1,369 |

**Carry the node in the record.** The gather already has it — `gatherPaths`
puts every path's node in `nodes` — so the record can hold it and no reader
need walk anything. It costs one more slot in a tuple that is built once per
visible object per frame; a plain tuple's sixth element is free, where a
`NamedTuple`'s would not be (0.131 µs to build against 0.016).

Two things fall out of it:

- The five `instancing` key functions all open with `shape = path[-1]` and use
  nothing else of the path, so they should take the node. That changes the
  `key` argument of `build_instance_groups` from "record-path -> key" to
  "node -> key", which is the honest signature.
- `record_placements` is asked **5.3 times for every record** — by
  `instance_counts` from `build_instance_groups`, again from the pass, again
  from `instance_matrices`, again from the shadow pass. That is its own
  question, separate from the walk.

The cost of the change is its breadth: the tuple's shape is read in about
twenty-five places and built in a dozen test files.

### What landed

All of it. A record is now
`(sortKey, mvmatrix, tmatrix, bvolume, path, node)`; the five `instancing` key
functions and the passes' `_instanceKey`/`_instanceable` hooks take the node;
`_shapePickable` and `applyLightGrid` read the node they were walking to; and
every loop that unpacked a record unpacks the node with it.

**Path walks fall from 17,487 a frame to 3,205 at 1600 objects** — 82% — and
what is left is exactly the two that have to happen: the gather's one per
renderable path, which is where the record's node comes from, and level
selection's one per LOD path, which runs before the gather. Everything else
reads the node off the record.

| objects | before | after | |
|---:|---:|---:|---:|
| 200 | 4.008 ms | 3.747 | −6.5% |
| 800 | 10.691 | 10.136 | −5.2% |
| 1600 | 20.296 | 19.165 | −5.6% |

Five rounds alternating between the two trees. `record_placements` still runs
5.3 times per record; what it no longer does is walk a path each time.

The harness counts `path_walks` now, and
`test_a_path_is_walked_to_its_node_twice_a_frame_at_most` holds it to two per
object. On the tree before this change that reads 2,294 at 200 objects against
the 416 the gate allows, so it is a gate rather than a comment.

## F. Changing a level rebuilds the transform cache — 🔴 withdrawn 2026-09-20

**There is nothing here. The figure this item was raised on was a total read as
a rate**: `cache.depend_signal` runs 131,250 times over a 1600-object run, and
dividing that by the frame count gave "2,000 times a frame". It is not per
frame. Counted inside the measured window instead of across the process:

```
connects total 131250; before the measured frames 131250; during them 0
```

All of it is scene setup — 3,204 paths each building one transform-cache entry
and registering the fields it depends on, once. `integrate` runs **0.0 times a
frame** in that scene, because a camera creeping 0.01 units a frame crosses no
threshold: nothing was switching, so the cost of switching could not have been
what the profile was showing.

Driven hard enough to switch — the camera moving 0.9 units a frame, 13 to 18
levels changing over per frame — it is **400 connects a frame**, not 2,000. And
that costs nothing measurable. Freezing every level change after warm-up, on an
idle machine, against the same scene:

| | normal | levels frozen |
|---|---|---|
| 800 objects, switching | 9.95 / 9.95 / 10.09 ms | 10.21 / 9.88 / 10.32 |
| 1600 objects, creeping | 18.51 / 18.77 / 18.93 | 19.17 / 18.73 / 18.82 |

The two are indistinguishable. Neither of the routes this section proposed was
worth taking, and one of them was tried: making a path with no `Transforming`
node of its own defer to its parent's cache entry is **slower**, because the
deferring path then caches nothing and re-walks on every call — 18.54 ms to
20.01 at 1600 objects. It is reverted.

### What to take from it

`cProfile` charges its own per-call overhead to the caller, so a function
called 121,645 times over a run is inflated far more than one called 60 times,
and `saferef.__init__` sat at the top of the profile while costing nothing a
frame. A profile ranks *where to look*. What settles whether something costs
anything is removing it and timing the frame — which is the same discipline
this plan's own D section is built on, and which reading the profile as an
answer skipped.

## Where this came from

The bust gallery, built to demonstrate level of detail
([HUMAN-MODEL-LOD-DEMO.md](HUMAN-MODEL-LOD-DEMO.md)). Octahedral impostors cut
62% of its triangles and made it no faster, which is what prompted the
measurement: the frame was never waiting on the thing the technique addresses.
The impostor work stands on its own — 2.4x on a software rasteriser — and the
ceiling it ran into is this.
