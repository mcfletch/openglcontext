# Mesh decimation and cluster LOD

**Status:** 🟡 In progress. The decimator exists: `opengl_decimate`, a workspace
sibling, covering M0–M3 and M6. Everything from M4 (the compiled accelerator) on
is still plan.

## What has landed

`opengl_decimate` — NumPy in, NumPy out, no GL, no engine import. 100% statement
coverage, ruff- and mypy-clean, `py.typed`, a tox matrix over CPython 3.10–3.14
and PyPy, and release-on-push-to-main wired the way the other siblings are. It
is in `[tool.uv.sources]`, `requirements-dev.txt` and `tools/preflight.toml`.

| Milestone | State |
|---|---|
| M0 project skeleton | done |
| M1 sequential QEM, manifold and border, position | done |
| M2 attributes | **partly** — carried and seam-preserving, not yet part of the metric |
| M3 parallel schedules | **partly** — `multiple-choice` done, batch-independent-set not |
| M6 collapse sequence and instant re-target | done |
| M4, M5, M7–M12 | plan |

What it does today: quadric accumulation with area weighting and border
constraint planes; classical and probabilistic metrics sharing one storage and
one solve; the link condition, a duplicate-face check, a normal-flip test and an
optional shape floor; manifold/border/locked classification with `lock_boundary`
and an explicit locked set; `heap` and `multiple-choice` schedules, seeded and
reproducible; optimal and endpoint placement; tolerance welding; a recorded
collapse sequence whose `at()` reaches any target by prefix replay; and a
measured two-sided sampled Hausdorff for certification.

**Two things the plan said that the implementation changed**, both recorded here
rather than quietly:

1. **The probabilistic metric is opt-in, not the default.** It is the better
   answer on a reconstructed surface and it is what M5's scanner path will
   select, but it needs a noise figure, and a wrong one is worse on clean
   geometry than the classical metric is. `metric='quadric'` is the default;
   `metric='probabilistic'` uses the noise given, or 0.001 of the bounding-box
   diagonal where none is.
2. **Attributes are carried, not minimised.** An output vertex is a distinct
   combination of *point* and *attribute values*, so a UV seam stays a seam and a
   hard edge stays hard with no seam-specific machinery — but the attributes
   themselves are not in the error metric, so a texture can slide where a point
   moves a long way. `placement='endpoint'` removes that entirely at some cost in
   geometric accuracy. Hoppe's extended quadric is what closes it properly, and
   it is what is left of M2.

### Measured on real assets

**Quality, on Poly Haven's `marble_bust_01` (CC0, 17,456 triangles).** Levels
built by halving, measured by `OpenGLContext.meshlod` rendering each against the
original over distances from touching the surface to sixty-four radii out. The
share of the object's own pixels that change, split into outline and shading:

| Level | Triangles | Outline change | Shading change |
|---|---|---|---|
| 1 | 8,728 | 0.04 – 0.12% | 2.3 – 6.6% |
| 2 | 4,364 | 0.12 – 0.30% | 11.2 – 14.7% |
| 3 | 2,182 | 0.27 – 0.91% | 19.5 – 24.7% |
| 4 | 1,090 | 0.49 – 1.36% | 31.5 – 36.5% |
| 5 | 544 | 0.98 – 2.04% | 42.5 – 47.1% |

**The shape survives; the shading is what goes.** At a thirty-second of the
triangles the outline still moves by one to two per cent -- the face is
recognisable, the eyes and nose still read. What degrades is faceting, and it
degrades steadily rather than suddenly.

That splits the remaining work cleanly. More triangles are not what the coarse
levels need: a normal map baked from the fine mesh (M10) is, and it is worth
more than any amount of decimator tuning.

**Carrying normals beats recomputing them, measured.** A surviving corner keeps
the normal it arrived with, so a flat triangle shades like the curve it
replaced. Against recomputing them from the coarse surface, on the same bust:
3.0–6.6% shading change at half the triangles instead of 9.0–14.0%, with an
identical outline. `build_chain` carries by default for that reason.

**Speed, on Poly Haven's `coastal_cliff_04` (CC0, 1,537,926 triangles).** Three
defects found by profiling the real scan rather than the synthetic shapes:

| | Before | After |
|---|---|---|
| `classify` | 18.7 s | 1.55 s |
| Per contraction, allocated | 3.84 MB | 0.005 MB |

- **Classification was a per-corner Python pass** over 4.6M corners, and two
  `np.unique(..., axis=0)` calls that sort rows as voids. Fan connectivity is now
  whole-array hooking and pointer-jumping, and edge pairs are encoded as one
  `int64` so the sort is an integer sort.
- **Every contraction copied the whole position array** to move one vertex --
  18.5 MB per contraction on this scan, which is what made the reduction
  quadratic. Now only the affected corners are gathered.
- **Counting live faces scanned a 1.5M-element flag array**, once per
  contraction. Now a running total.

**M4 landed, and it is what made the scale target real.** The NumPy loop ran
at 371 contractions a second and needed half a gigabyte of face-per-point sets
before it started. The same algorithm in Cython -- the faces on a point as a
doubly-linked list over a fixed pool of 3F incidences, the queue as parallel
arrays -- reduces the cliff to 50% in 6.3 seconds and to 2% in 9.4, under a
gigabyte, and takes a 6,982,937-triangle tree to 5% in 67 seconds. That is
120,000 contractions a second against 371.

It is the *same* reduction: the compiled and NumPy paths produce identical
contractions in identical order, which took two things. The queue is seeded
from the caller's edge list in the caller's order, because equal-priced edges
separate on the serial they were queued with and a flat region is full of edges
costing nothing. And staleness is a version per point rather than a comparison
of prices -- a stale entry whose price has not changed is exactly what a flat
region produces.

**A correction.** The killed run recorded above was blamed on the reduction's
memory. It was not: the certification was allocating a
``(block, triangles, 3)`` temporary -- 256 points against 1.5M triangles is
nine gigabytes for one block. Blocking over triangles as well as points bounds
it. The reduction's own memory was never what failed.

The compiled path is the accelerator the plan called Rust. It is **Cython**,
for a concrete reason: there is no Rust toolchain in the development container,
and Cython is what `opengl_extrusions`, `omi_physics` and `PyOpenGL-accelerate`
already use, so the build, the fallback and the wheel matrix all follow a shape
this workspace has.

### What the levels ship as

Baking is not optional at the scale this targets: two hundred assets at seconds
each cannot be decimated when a player opens a door. The chain is baked once and
shipped, and the file it ships in is **existing standards rather than a new
format**:

- **`MSFT_lod`** declares the levels. The node carrying it is the finest, `ids`
  lists the coarser alternatives in decreasing detail, and
  `MSFT_screencoverage` says where each takes over. A reader that does not know
  the extension draws the finest level, which is the right default.
- **A glb may point outside itself.** Its binary chunk is buffer zero and is the
  one buffer with no `uri`; every other buffer is an ordinary glTF buffer and
  may name an external file. The coarsest level rides inside the glb, so the
  file always draws something; each finer level is a sidecar the operating
  system never opens until it is wanted.
- **glTF is addressable.** `accessor -> bufferView -> buffer` is an offset and a
  length, so a level is a seek and a read, and opening a file parses only the
  JSON chunk.

`OpenGLContext.meshlod.asset` writes and reads that, and the streaming claims
are tested by deleting the other levels' files.

**3D Tiles is the alternative and is not the same tool.** The engine already
implements it, and it is the right answer for streaming a *scene* -- a spatial
hierarchy of many tiles, with refinement and geometric error. For one asset with
discrete levels it puts a tileset in front of every model. The two compose: a 3D
Tiles tile's content can be a glTF using `MSFT_lod`.

The rest of this document is the plan as it stands.

## What this is for

The engine cannot make a level of detail. It can only use ones somebody else
made. Every LOD in the tree today arrives pre-built:

- `openglcontext-forest/tools/bake_assets.py` pulls `Fir01_LOD0_…` and
  `Acer_…_LOD2_…` out of the source `.glb` by node name — the artist supplied
  the rungs, and the bake picks them.
- `OpenGLContext/scenegraph/tessellationlod.py` re-tessellates *procedural*
  geometry (quadrics, NURBS, the teapot) at a coarser parameter. It has no
  answer for a mesh that arrived as triangles.
- `OpenGLContext/loaders/tiles3d/geomorph.py` builds a coarse parent by
  resampling a **height field** at half resolution. That works because the
  surface is a function of *x, z*; it says nothing about a character or a
  vehicle.
- `OpenGLContext/scenegraph/lod.py` (VRML97 `LOD`) switches between whole child
  nodes the file already contained.

So a developer who hands the engine a 4-million-triangle scan, a photogrammetry
capture, or a film-resolution asset gets one thing: all four million triangles,
every frame, at every distance. That is the gap. A toolkit people build games on
has to be able to take the model it is given and produce the rungs itself —
offline as a bake step, and at load time for content that arrives at runtime.

The second half of the gap is granularity. A discrete LOD chain swaps a whole
object at once. What a heavy scene needs is the ability to swap **sections**: the
near face of a building at full detail while its far wall is coarse, the front of
a car sharp while the boot is not. That requires an LOD structure with
sub-object granularity whose pieces join without cracks, and a transition policy
that keeps the change off the screen.

## Targets

These numbers set the design. They are budgets to build and measure against.

### The assets to ingest

Film- and scan-resolution source material, of the kind sold for virtualised-
geometry pipelines and produced by photogrammetry:

| Property | Target |
|---|---|
| Triangles per object | 1M typical, 50M upper bound |
| Objects per scene | thousands, sharing baked DAGs by instance |
| Texture atlases | 8K–16K, unique-UV as scanners produce them |
| Input condition | non-manifold, multi-component, self-intersecting, holed, with floaters |
| Formats | glTF/GLB, OBJ, PLY, and anything that reaches NumPy arrays |

Above roughly 20M triangles the ingest is out-of-core: the pipeline must not need
the whole mesh resident, because a 50M-triangle scan with attributes is tens of
gigabytes and the machine doing the bake is a workstation, not a cluster.

### The hardware to render on

**The floor is Intel integrated graphics** — Iris Xe (96 EU) as the reference,
UHD 620 as the bottom. That hardware has no dedicated video memory, shares 25–50
GB/s with the CPU, and is fill-rate limited long before it is triangle limited.
It settles several decisions:

- **No required compute shaders, no indirect draw, no mesh shaders.** The
  engine's floor is GL 3.3 and the draw path stays there. GL 4.3 adds an optional
  compute tier, and nothing above 4.3 is used.
- **Geometry is quantised on the GPU, not just on disk.** Bandwidth is the
  binding constraint, not arithmetic.
- **The triangle budget is a dial, not a property of the bake.** One baked DAG
  serves both the iGPU and a discrete card; the runtime raises or lowers its pixel
  error threshold to hold whatever budget the machine can afford.

At 1920×1080 and 60 Hz on the reference iGPU:

| Budget | Target |
|---|---|
| Triangles, main view | ≤ 500k |
| Triangles, all passes including shadows | ≤ 1.2M |
| Resident geometry (shared memory, so the user's RAM) | ≤ 600 MB |
| Draw calls after `glMultiDrawElements` batching | ≤ 200 |
| Cut selection + culling, CPU, per frame | ≤ 1 ms |

What makes 500k triangles enough for a 50M-triangle asset is that the cut is
chosen by projected error: at a sensible viewing distance the great majority of
an asset's clusters are represented by an ancestor a few levels up.

### The editor to build on it

A decimation editor in `openglcontext-editor`, taking a scanner asset and
producing something a game can load, has to answer while the user is still
looking at it:

| Interaction | Target |
|---|---|
| First coarse preview of a 5M-triangle input | ≤ 1 s |
| Target-count slider response, after the first decimation | ≤ 16 ms |
| Full DAG bake of a 5M-triangle asset, 8 cores | ≤ 2 min |

The slider target is what shapes the library's interface. Re-running a
decimation per slider position cannot meet 16 ms and never will. Instead the
first run records the **ordered collapse sequence**, and every later target is a
prefix of it — replaying or rewinding a prefix is an array operation over the
remap, so any triangle count between the base and the input is reachable
immediately. That is Hoppe's progressive mesh used as the *editing*
representation, with the cluster DAG as the *runtime* representation. The two
coexist: the sequence is what the editor scrubs, the DAG is what ships.

## Scope

**In scope**

- A new standalone library that decimates triangle meshes given as glTF-shaped
  NumPy arrays, preserving normals, texture coordinates, tangents, vertex
  colours, skinning weights and material boundaries.
- Robust handling of scanner output: non-manifold, multi-component,
  self-intersecting and holed input, with an optional repair pass.
- Out-of-core ingest for assets larger than memory.
- A recorded collapse sequence, so an editor can reach any triangle count without
  re-decimating.
- A cluster-DAG LOD structure built on that decimator, giving crack-free
  sub-object level of detail with a monotone error bound.
- Engine-side runtime: cut selection per frame, cluster streaming and residency,
  quantised vertex data, the draw path, geomorph and cross-fade, a scenegraph
  node, and the bake integration.
- Normal-map and attribute baking from the fine mesh onto a coarse one, without
  which a scan reduced a thousandfold has nothing left to shade with.
- Measurable quality gates: geometric error, on-screen pop, crack-freeness,
  determinism, throughput, and frame cost on the reference iGPU.

**Not in scope for this plan**

- Remeshing that discards the input's parameterisation (voxel/SDF remeshing,
  field-aligned quad remeshing). Those change the UVs, so the existing textures no
  longer fit; a separate job with a different set of trade-offs.
- Texture *atlas repacking* — reparameterising a scan's unique-UV atlas to a
  tighter layout. M9 bakes onto the parameterisation that is there; repacking
  needs a UV packer and a chart segmenter, and is its own plan.
- Compressed transmission (`EXT_meshopt_compression`, Draco). Orthogonal, and
  the quantisation this plan does is most of the win anyway.
- Reading Nanite's own on-disk format. The target is assets at that scale and
  quality, from any source; UE's container is proprietary and not a goal.

## Survey of the approaches

This is the ground the design stands on. Each entry is what the method is, what
it is good at, and where it fails.

### 1. Simplification operators

**Vertex clustering** (Rossignac & Borrel 1993; out-of-core, Lindstrom 2000).
Overlay a grid, collapse every vertex in a cell to one representative, drop
degenerate triangles.

- *Strengths:* Trivially parallel, single pass, no adjacency, streaming — it
  handles meshes far larger than memory, at roughly disk speed. The only method
  that ingests a 500-million-triangle scan without a graph.
- *Drawbacks:* Quality is poor and grid-aligned. Thin features vanish, topology
  changes uncontrollably, the output has no correspondence to the input, and the
  error is bounded only by the cell size.
- *Use here:* A pre-pass for input too large to build adjacency over, never the
  final answer.

**Vertex decimation** (Schroeder et al. 1992). Classify a vertex, delete it,
re-triangulate the hole.

- *Strengths:* Simple, preserves topology, retains the original vertex positions
  exactly — a subset of the input, which some pipelines want.
- *Drawbacks:* Cannot move a vertex to a better place, so it plateaus in quality
  well above what an optimal-placement collapse reaches. Hole re-triangulation is
  fiddly and can fail.

**Edge collapse / pair contraction** (Garland & Heckbert 1997). Merge the two
ends of an edge into one vertex, placed where the error metric says.

- *Strengths:* Local, cheap, invertible (the inverse is a vertex split, which is
  what makes progressive meshes and geomorphs possible), and it produces the best
  measured quality per triangle of any practical operator. Everything modern is
  built on it.
- *Drawbacks:* Needs adjacency and a validity test — an unchecked collapse folds
  triangles over, produces non-manifold edges, or turns the mesh inside out.
- *Variant — half-edge collapse:* place the result at one endpoint instead of at
  the optimum. Slightly worse error, but the survivor is an original vertex, which
  makes the correspondence for geomorphs and attribute transfer exact and free.
- *Variant — vertex-pair contraction:* allow collapsing pairs that are not edges,
  within a distance threshold. Joins separate components and closes cracks, which
  is what a mesh assembled from parts needs; it also merges things that should
  not merge, so the threshold matters.

**Variational shape approximation** (Cohen-Steiner et al. 2004) and related
proxy-fitting methods. Fit *k* planar proxies by Lloyd iteration, then rebuild.

- *Strengths:* Outstanding on mechanical, piecewise-planar shapes; the result
  looks designed rather than eroded.
- *Drawbacks:* Global and iterative, so it is slow and does not stream; the output
  is a new mesh with new UVs; poor on organic surfaces.

**Simplification envelopes / appearance-preserving simplification** (Cohen et al.
1996, 1998). Simplify inside a guaranteed geometric envelope, and bound the
*texture* deviation rather than the surface deviation.

- *Strengths:* Gives a real bound on what the viewer can see, not just on where
  the surface is. This is the theory behind normal-map baking for far LODs.
- *Drawbacks:* Expensive to build; the envelope construction is fragile on dirty
  input; needs the texture pipeline to come with it.

**Impostors and billboards.** Replace the geometry with rendered cards.

- *Strengths:* The cheapest far rung by a wide margin. The engine already does
  this for trees (`scenegraph/vegetation/billboards.py`).
- *Drawbacks:* Parallax and lighting are wrong off-axis, silhouettes are fixed,
  and the transition back to geometry is the hardest pop in the system.

### 2. Error metrics

**Quadric error metric (QEM)** (Garland & Heckbert 1997). Each vertex carries a
4×4 symmetric matrix (10 unique coefficients) accumulating squared distance to
the planes of its incident triangles. A collapse costs the quadric sum evaluated
at the optimal point, found by one 3×3 solve.

- *Strengths:* Constant storage per vertex, additive under collapse, and the
  optimum is closed-form. Excellent quality for the cost. It is the baseline
  every other method is compared against, and has been for nearly thirty years.
- *Drawbacks:* Measures distance to *planes*, not to the surface, so error
  accumulates optimistically and unbounded — the reported cost is not a Hausdorff
  bound. Degenerate on flat and near-flat neighbourhoods, where the 3×3 system is
  singular and needs a pseudo-inverse or a fallback. Ignores attributes entirely.

**Attribute-extended quadrics** (Garland & Heckbert 1998; Hoppe 1999). Extend the
quadric to *3 + m* dimensions so normals, UVs and colours are part of the
minimisation, with the attribute terms arranged so the position solve stays 3×3.

- *Strengths:* The only principled way to keep a texture from sliding. Hoppe's
  wedge formulation handles attribute discontinuities (UV seams, hard normal
  edges) correctly rather than by locking them.
- *Drawbacks:* Storage grows as *(3+m)²*; the attribute weights are scale-
  dependent and have to be normalised against the model's extent or the metric is
  dominated by whichever attribute has the largest numbers.

**Probabilistic quadrics** (Trettner & Kobbelt 2020). Treat each input plane as a
sample from a Gaussian and minimise the *expected* squared error. Closed form,
same storage.

- *Strengths:* The minimisation becomes a well-conditioned linear system — the
  paper reports roughly 50× faster than the SVD path — which removes the
  degenerate-quadric special-casing that classical QEM needs. It also regularises
  placement on noisy scan data, which is exactly the input this library is meant
  to ingest.
- *Drawbacks:* One more parameter (the assumed noise magnitude); on clean
  synthetic geometry it is marginally more conservative than classical QEM.
- *Use here:* Selectable beside classical QEM, and the one the scanner path
  takes. The change is confined to accumulation and solve, so offering both costs
  almost nothing — both are implemented and share the storage.

**Memoryless / volume-preserving simplification** (Lindstrom & Turk 1998, 1999).
Derive the placement from volume and area constraints on the *current* mesh
rather than from accumulated history.

- *Strengths:* No per-vertex history to store, and it preserves volume, which
  keeps silhouettes from shrinking as a closed shape is reduced hard.
- *Drawbacks:* Needs a closed surface to have a volume to preserve; quality on
  open or dirty meshes trails QEM.
- *Use here:* An optional volume term added to the quadric cost, for closed
  shapes reduced past ~90%.

**Hausdorff-bounded methods.** Carry an explicit two-sided distance bound.

- *Strengths:* A guarantee, which is what a screen-space error budget actually
  wants — a monotone cluster DAG needs a bound it can trust.
- *Drawbacks:* Far more expensive than a quadric, and hard to maintain
  incrementally.
- *Use here:* Not as the driving metric. Sampled Hausdorff is computed once per
  level at bake time to *certify* the quadric-derived bound, and the certified
  number is what ships in the DAG.

**Simplifying meshes in the wild** (Liu, Zhang & Yuksel, TOG 2025). Decimate the
simplicial 2-complex rather than a manifold, with a modified quadric that reduces
to standard QEM on watertight manifold input, plus a generalised winding number
for inside/outside on arbitrary soups, and a texture metric defined on surface
colour rather than on UV layout.

- *Strengths:* Addresses precisely the input a game engine is handed —
  non-manifold, multi-component, self-intersecting, with duplicated and
  degenerate faces. Degrades to familiar behaviour on clean meshes.
- *Drawbacks:* More machinery; the winding-number field costs a build.
- *Use here:* The robustness layer, milestone M5, after the manifold path is
  solid.

### 3. Scheduling, and how each parallelises

**Global priority heap.** One binary heap over all candidate collapses, pop the
cheapest, re-cost its 1-ring, repeat.

- *Strengths:* Best quality. This is the reference the others are measured
  against.
- *Drawbacks:* Inherently sequential — every collapse can change the cost of its
  neighbours, so the next pop depends on the last. Heap churn dominates the
  runtime on large meshes.

**Lazy heap.** Push updated costs without removing stale entries; discard stale
pops on the way out.

- *Strengths:* Removes decrease-key, which is most of the heap cost. Same output
  in practice.
- *Drawbacks:* Still sequential; the heap grows.

**Multiple-choice** (Wu & Kobbelt 2002). Draw *k* random live edges (*k* ≈ 8),
collapse the cheapest of them, forget the rest.

- *Strengths:* No global data structure at all. O(1) per collapse, constant
  memory, and measured quality within a few percent of the full heap. Because
  there is no shared ordering, it parallelises directly — this is the basis of the
  published GPU implementations.
- *Drawbacks:* Non-deterministic unless the sampling is seeded; a small quality
  loss that shows most at extreme reduction ratios.

**Independent-set batches.** Each round, cost every live edge, take a cheap
subset, then select a maximal set of collapses whose affected neighbourhoods do
not overlap, and apply the whole set at once.

- *Strengths:* Turns the algorithm into a sequence of whole-array operations,
  which is the only way a NumPy implementation is fast, and it is the same shape a
  GPU compute kernel wants. Deterministic given a cost order and a seeded tiebreak.
- *Drawbacks:* A round's collapses are costed against the state at the start of
  the round, so quality sits between multiple-choice and the full heap. The
  independence test has to cover the 2-ring, not the 1-ring, or two collapses can
  agree on a vertex they both move.

**Partition and lock.** Split the mesh spatially, decimate each part with its
border locked, then shift the partition and repeat so the previously locked seams
become interior.

- *Strengths:* Embarrassingly parallel across parts, with no shared mutable
  state; scales across cores and processes. The locked-border idea is the same one
  the cluster DAG is built on.
- *Drawbacks:* Locked borders carry more triangles than they need until a later
  pass releases them; needs several alternating passes to avoid a visible grid.

**GPU parallel collapse** (Koh's GPU multiple-choice scheme; CuMesh-style
atomics; *Interactive GPU-based Decimation of Large Meshes*, 2023; PaMO 2025 for
the intersection-free variant).

- *Strengths:* The published results reduce large meshes in well under a second.
- *Drawbacks:* Conflict resolution needs atomics or mutexes, and the compaction
  passes are where the complexity lives. Results vary between drivers, and the
  engine's floor is GL 3.3, where compute is not guaranteed.
- *Use here:* An optional engine-side tier behind `compute_is_available()`, the
  way `character/gpuskeleton.py` already gates GPU skinning. Never required.

### 4. LOD structures

**Discrete chain (LOD0…LODn).**

- *Strengths:* Simple, one draw call per object, trivially cacheable, and it is
  what every DCC tool and every glTF LOD extension already speaks.
- *Drawbacks:* Whole-object granularity, so a large object is either all-fine or
  all-coarse. Every switch is a pop unless it is morphed or faded.

**Progressive meshes** (Hoppe 1996). Store a base mesh plus an ordered list of
vertex splits; any triangle count is reachable by replaying a prefix.

- *Strengths:* Continuous resolution, exact geomorphs between any two levels, and
  it streams — the base arrives first and refines.
- *Drawbacks:* Refinement is per-vertex CPU work with poor locality, and the
  vertex buffer changes every frame, which is the opposite of what a GPU wants.

**View-dependent progressive meshes** (Hoppe 1997) and hierarchical vertex
trees. Refine only where the viewer is looking, subject to dependency conditions
that keep the selection legal.

- *Strengths:* True sub-object granularity, which is the requirement here.
- *Drawbacks:* Per-vertex runtime selection, pointer-chasing, and a dependency
  test on every node. It was designed when triangles were the scarce resource and
  draw calls were cheap; the ratio has reversed.

**Batched multi-triangulation** (Cignoni et al. 2004, 2005). Same idea as the
vertex tree, but the unit of selection is a *patch* of a few thousand triangles
instead of a vertex, with patch boundaries arranged so that any legal cut joins
without cracks.

- *Strengths:* Keeps view-dependent granularity while giving the GPU batches it
  can actually draw. This is the design that works on modern hardware.
- *Drawbacks:* A build step, and a patch is the smallest thing that can change.

**Cluster DAG / virtualised geometry** (Karis et al. 2021, and the open
reimplementations built on `meshoptimizer`). Partition into small clusters
(≈128 triangles), group neighbouring clusters (≈8–32), simplify each group as a
unit with the group's *outer* boundary locked, split the result back into
clusters, and record those as the parents of everything in the group. Because
groups are re-partitioned at every level, the locked boundaries move, so no edge
stays locked all the way up.

- *Strengths:* Sub-object granularity with GPU-sized batches; crack-freeness
  follows from a monotone error bound rather than from stitching; the cut is a
  vectorisable test over a flat array; it is a DAG rather than a tree, so it does
  not accumulate locked seams. It is the current answer for ingesting very high
  poly models and drawing them at a fixed triangle budget.
- *Drawbacks:* The heaviest build of any option here — partition, group,
  simplify, re-partition, per level. Skinning and deformation are awkward,
  because the cut changes which vertices exist. Small objects get no benefit and
  pay the overhead.
- *Use here:* The recommended structure, with the discrete chain kept as the
  cheap tier for small and skinned objects.

### 5. Transitions — keeping the switch off the screen

**Hard switch inside an error budget.** Choose the cut so the geometric error
projects to under a pixel.

- *Strengths:* Costs nothing at runtime and needs no correspondence. With a
  cluster DAG and a certified bound it is a real guarantee, not a hope.
- *Drawbacks:* Only affordable at a tight threshold; loosen it for performance
  and the pops return. Sub-pixel geometry still moves *shading* — a normal that
  changes by 30° changes a specular highlight regardless of how little the
  surface moved.

**Geomorph.** Carry, per vertex, where that vertex sits on the coarser level, and
lerp toward it as the switch approaches.

- *Strengths:* Continuous. The correspondence falls straight out of the collapse
  log, so it is free to produce. The engine already has the runtime primitives in
  `loaders/tiles3d/geomorph.py` and applies them to terrain.
- *Drawbacks:* Needs a second position stream (and ideally a second normal
  stream) in the vertex buffer, so it costs bandwidth. It does not help across a
  topology change or a switch to an impostor, and it cannot morph an attribute
  that is discontinuous.

**Dithered cross-fade resolved by temporal accumulation.** Draw both levels for a
few frames with a screen-space dither threshold ramping between them, and let TAA
resolve it.

- *Strengths:* Works for *any* pair, including mesh-to-impostor and across a
  material change. No sorting, no overdraw beyond the transition window, no
  translucency cost. The engine already does this for the tree impostor handoff
  (`scenegraph/vegetation/billboards.py`, `LOD_NEAR`/`LOD_FAR`).
- *Drawbacks:* Needs temporal accumulation to look clean; without it the dither
  is visible as noise. Both levels are drawn during the window.

**Alpha-blended cross-fade.** The same idea with real translucency.

- *Strengths:* Clean without TAA.
- *Drawbacks:* Sorting, overdraw, and it breaks depth-based effects. Not
  recommended.

**Hysteresis.** Separate the refine and coarsen thresholds so a viewer hovering
at a boundary does not oscillate.

- *Strengths:* Removes the worst artefact — flicker — for one comparison.
- *Drawbacks:* None worth the name; it is a requirement, not an option.

### 6. Getting the data in and keeping it small

At the scale this plan targets, what the geometry *costs* matters as much as what
it looks like, and on an integrated GPU it matters more.

**Full residency.** Upload everything, select per frame.

- *Strengths:* Simplest possible runtime; no hitches, no loader.
- *Drawbacks:* A 50M-triangle asset does not fit, and on shared memory the
  geometry budget is taken out of the user's RAM.

**Demand streaming of cluster groups.** Hold only what the cut wants, plus a
margin, with an LRU eviction against a byte budget.

- *Strengths:* Decouples asset size from memory. A group is the natural unit —
  it is what was simplified together, so it is what refines together. The engine
  already has both halves: `loaders/tiles3d/residency.py` is an LRU with a byte
  budget that never evicts what the current view needs, and
  `loaders/tiles3d/loadmanager.py` is a priority queue and worker pool with an
  injectable loader, so cluster groups drop in where tiles do.
- *Drawbacks:* A fast camera can outrun the loader. The answer is to draw the
  resident ancestor — always available, because the cut's parent chain is
  resident by construction — which shows coarse geometry rather than a hole.

**Vertex quantisation.** Store cluster-local normalised integers instead of
floats: position as three `int16` in the cluster's bounding box, normal
octahedral-encoded in two `int16`, UV as two `int16` against the cluster's UV
bounds, and cluster-local `uint8` indices since a 128-triangle cluster has under
256 unique vertices.

- *Strengths:* Roughly 12 bytes per triangle against roughly 40 unquantised —
  the difference between an 8M-triangle asset being a 200 MB resident set and a
  650 MB one, and a proportional saving in the bandwidth that an iGPU is short of.
  The precision is *better* than float32 in practice, because the range is a
  cluster rather than the world. glTF already has the vocabulary in
  `KHR_mesh_quantization`, which the loader reads today.
- *Drawbacks:* The shader dequantises, which means per-cluster scale and bias
  uniforms and a vertex format the current semantics table does not declare.
  Normals lose a little accuracy; octahedral at 16 bits is well under a degree,
  which does not show.

**Out-of-core ingest.** Process the input in spatial chunks that fit in memory,
decimate each with its borders locked, then join and continue.

- *Strengths:* The only way a 50M-triangle scan is processable on a workstation.
  It is the same locked-border mechanism the DAG uses, applied one level lower.
- *Drawbacks:* Several passes over the file, so it is I/O bound; the first level's
  chunk borders carry extra triangles until a later level releases them.

## What we build

### The library

A new project, `opengl_decimate`, sitting beside `opengl_extrusions` and
`omi_physics` as a renderer-agnostic component: NumPy in, NumPy out, no GL, no
scenegraph, no engine import. It becomes a workspace submodule installed editable
by `uv sync`, with ruff and mypy configured in `pyproject.toml`, GitHub CI running
the suite, release-on-push-to-main, and an entry in `tools/preflight.toml`.

*Why a separate library rather than a module in the engine:* the core is a
compiled, parallel, stateful algorithm with its own release cadence and an
audience beyond this engine, and it must be usable by the editor's bake tools and
by other people's pipelines without pulling in a windowing toolkit. It is also
the piece most likely to want a language the engine does not otherwise build.

*Why not inside `opengl_extrusions`:* that library generates geometry from
curves and outlines. Decimation consumes arbitrary geometry and is a much larger
body of code; folding it in would double the package and stretch its remit.

**Data model.** The input is glTF's vocabulary as plain NumPy arrays — the same
shape `opengl_extrusions.mesh.Primitive` produces and `PBRMesh` consumes, so a
mesh crosses the boundary without a copy:

```python
import numpy as np
from opengl_decimate import simplify, SimplifyOptions

result = simplify(
    attributes={
        'POSITION': positions,      # (n, 3) float32
        'NORMAL':   normals,        # (n, 3) float32
        'TEXCOORD_0': uvs,          # (n, 2) float32
        'JOINTS_0': joints,         # (n, 4) uint16   -- carried, not interpolated
        'WEIGHTS_0': weights,       # (n, 4) float32
    },
    indices=indices,                # (m * 3,) uint32
    options=SimplifyOptions(target_ratio=0.25),
)
result.attributes['POSITION']       # (n', 3) float32
result.indices                      # (m' * 3,) uint32
result.error                        # certified surface deviation, model units
result.vertex_parent                # (n,) int32 -- where each input vertex went
```

Anything the library does not understand is carried through by the vertex
remap rather than refused, so a pipeline with its own attributes still works.

**The API surface, in full.**

| Entry point | What it does |
|---|---|
| `simplify(attributes, indices, options)` | One mesh to one coarser mesh. The primitive everything else is built from. |
| `collapse_sequence(…, options)` | The ordered collapse log for the whole reduction, once. |
| `CollapseSequence.at(count \| ratio \| error)` | Any target, by replaying a prefix. An array operation, so an editor's slider calls it per frame. |
| `simplify_chain(…, levels, ratio)` | A discrete LOD chain, each level carrying its parent correspondence for geomorphing. |
| `repair(attributes, indices, options)` | The scanner pass: weld, drop degenerate and duplicate faces, remove floaters, optionally fill small holes. Reports what it changed. |
| `build_clusters(…, max_triangles)` | Partition into clusters, boundary-minimising. |
| `build_cluster_dag(…, options)` | The full DAG: cluster, group, simplify-with-locked-border, re-cluster, per level. |
| `build_cluster_dag_streaming(reader, …)` | The same, out-of-core, over a chunked reader for input that does not fit in memory. |
| `quantize(dag, options)` | Cluster-local integer vertex data plus per-cluster scale and bias. |
| `ClusterDAG.save / load` | The baked form (`.npz` today; a glTF vendor extension once the shape settles). |
| `select_cut(dag, error_limit, view)` | The per-frame cut and frustum test, vectorised over the cluster array. Pure arrays — the engine calls it, and it is testable with no window. |
| `weld(…)`, `classify_vertices(…)` | The preparation steps, exposed because callers need them separately. |

**Options**, with defaults chosen for "a game asset, decimated well":

```python
SimplifyOptions(
    target_ratio=None, target_count=None, target_error=None,  # one of the three
    metric='probabilistic',        # or 'quadric'
    attribute_weights={'NORMAL': 1.0, 'TEXCOORD_0': 1.0},     # relative to position, auto-scaled
    lock_boundary=False,           # True for a cluster group's outer border
    lock_material_edges=True,
    preserve_topology=True,        # link condition enforced
    max_normal_flip=90.0,          # degrees; reject a collapse that turns a face past this
    min_triangle_quality=0.02,
    volume_weight=0.0,             # Lindstrom-Turk term for closed shapes
    pair_distance=0.0,             # >0 allows non-edge pair contraction
    schedule='batch',              # 'heap' | 'multiple-choice' | 'batch'
    seed=0,                        # determinism
    threads=None,                  # None = all cores
)
```

### Language and packaging

The inner loop is pointer-chasing over a topology structure with a priority
order, run hundreds of millions of times. Python cannot do it, and the honest
choice is which compiled language.

- **Cython** is the workspace's existing answer (`opengl_extrusions`'s
  `_predicates_native.pyx`, `omi_physics`, `PyOpenGL-accelerate`). It is the
  lowest-friction option: no new toolchain, sdists build with a C compiler, and
  the fallback pattern is already established. It suits a *kernel*. This is not a
  kernel; it is an engine with its own data structures, and expressing a
  half-edge mesh, a lazy heap and a work-stealing scheduler in Cython means
  writing C with manual memory management and a Python object model in the way.
- **C** compiles anywhere and matches PyOpenGL's world. It is also where
  segfaults come from, and this workspace has a standing rule that a core dump
  stops all other work until it is understood. Manual lifetime management over
  mesh surgery — where an index into a half-edge array is invalidated by a
  collapse three operations ago — is the exact case that produces them.
- **Rust** with PyO3 and maturin gives memory safety on precisely that code,
  `rayon` for work-stealing parallelism across cluster groups inside one process,
  `abi3` wheels built once per platform rather than per Python version, and no
  dependency management beyond `cargo`. The costs are a Rust toolchain in CI and
  a second language in the workspace, and a source install on a platform with no
  wheel needs `cargo` present.

**Recommendation: Rust core, exposed through PyO3, with a pure-NumPy reference
implementation in the same project that is always importable.** The split
follows the `PyOpenGL` / `PyOpenGL-accelerate` precedent:

- `opengl_decimate` — pure Python and NumPy. Always installs, on any platform,
  with no toolchain. Implements every documented entry point using the
  batch-independent-set schedule, which keeps the work in whole-array operations
  and is within reach of usable on meshes up to a few hundred thousand triangles.
- `opengl_decimate_accelerate` — the Rust extension, shipped as wheels. Imported
  opportunistically at load; absent, the pure path runs.

That arrangement earns three things beyond speed. `pip install` never fails. The
NumPy implementation is the readable statement of the algorithm and what the
suite differential-tests the Rust against — both must produce the same output for
the same seed, which is a strong correctness gate on the compiled code. And the
GIL is released around every Rust call (`Python::allow_threads`), so `rayon`'s
threads are genuinely parallel today, not only on a free-threaded interpreter.

Zero-copy at the boundary: inputs arrive as `PyReadonlyArray2<f32>` views over
the caller's arrays; outputs are allocated in Rust and handed over as arrays. No
serialisation, no pickling, and the process pool that a Python implementation
would need over cluster groups is replaced by threads over shared immutable
input.

The scale targets are what make the choice load-bearing rather than a
preference. A 50M-triangle out-of-core build is hours of pointer-chasing over
indices that a collapse invalidates, run across every core; and the editor's
one-second first preview is a latency budget, not a throughput one. Neither is
reachable from Python, and both are the kind of code where a use-after-free is
found by a user rather than by a test.

### What stays in the engine

`OpenGLContext/meshlod/` — GL-free selection and bookkeeping, plus the draw path:

- `MeshLOD`, a scenegraph node that holds a baked `ClusterDAG` and draws the
  current cut. Sits beside `PBRMesh` and uses the same vertex semantics, so the
  lit pass, the unlit pass and the shadow pass all take it unchanged.
- Cut evaluation per frame, reusing `loaders/tiles3d/screenspaceerror.py` —
  a cluster's error is a sphere radius, so the existing projection applies
  directly. Re-evaluated only when the camera has moved past a threshold, the way
  `update_clump_lod` already avoids re-selecting a static scene.
- Draw: one persistent index buffer holding every resident cluster's triangles
  once, and a per-frame list of (offset, count) pairs through
  `glMultiDrawElements` — core since GL 1.4, so the 3.3 floor is met with no
  extension. No geometry is uploaded per frame; the only per-frame traffic is the
  offset list. Where `GL_ARB_multi_draw_indirect` is present, the same list
  becomes an indirect buffer the GPU fills itself.
- Streaming: cluster groups paged against a byte budget, through
  `loaders/tiles3d/residency.py` and `loaders/tiles3d/loadmanager.py`, whose
  loader is already injectable. A group that has not arrived is covered by its
  resident ancestor rather than by a hole.
- Quantised vertex formats: per-cluster scale and bias uniforms, an octahedral
  normal decode, and `GL_SHORT`/`GL_UNSIGNED_BYTE` normalised attributes declared
  in `scenegraph/vertexsemantics.py` alongside the float forms.
- A triangle-budget controller: a small feedback loop that moves the pixel-error
  threshold to hold the frame's triangle budget, so the same asset runs on an
  iGPU and on a discrete card from one bake.
- Geomorph: generalise `loaders/tiles3d/geomorph.py` from height fields to a
  second vertex stream, with the morph factor as a uniform, and add the blend to
  `pbr.vert` behind a define.
- Cross-fade: reuse the vegetation dither for the cases geomorph cannot cover.
- Bake integration: `openglcontext-editor`'s tile baker calls `build_cluster_dag`
  for mesh content, which is what gives the 3D Tiles pipeline real geometry LOD
  instead of item subsetting.

## The algorithm, in the order it runs

1. **Weld and classify.** Merge positionally-coincident vertices, then classify
   each: *manifold* (free to move), *boundary* (may collapse only along the
   boundary), *seam* (an attribute discontinuity — free along the seam), *locked*
   (non-manifold, a material edge, or a cluster group's outer border). This step
   decides most of the output quality, and it is also where the "wild" input
   cases are absorbed.
2. **Accumulate quadrics.** Per vertex, area-weighted over incident triangle
   planes, plus constraint planes perpendicular to boundary and seam edges, plus
   the attribute terms. Probabilistic accumulation by default.
3. **Cost and place every candidate.** Batched 3×3 solves — one `np.linalg.solve`
   over an *(E, 3, 3)* stack in the NumPy path, a `rayon` map in the Rust path.
4. **Reject the invalid.** Link condition, normal-flip test over the full
   affected 1-ring, triangle quality floor, classification rules. Rejection is
   per-candidate and independent, so it vectorises.
5. **Schedule.** `batch` selects a cheap subset, then a maximal independent set
   over the 2-ring via a scatter-min claim on vertices — deterministic given the
   cost order and a seeded tiebreak. `heap` is the sequential reference. Apply the
   selected collapses as one vectorised remap.
6. **Record.** Each applied collapse appends to the sequence — the two vertices,
   the survivor's placement and attributes, and the cost. The sequence is the
   whole reduction expressed once, and every later target is a prefix of it.
7. **Repeat** to the target count, ratio or error.
8. **Certify.** Sample both surfaces and measure two-sided Hausdorff and mean
   deviation. The certified number is what the level reports, not the accumulated
   quadric value.

**Building the DAG**, per level: partition the dual graph into ≈128-triangle
clusters by boundary-minimising region growing; partition the cluster-adjacency
graph — weighted by shared edge count — into groups of ≈8; simplify each group's
merged triangles by half with the group's outer boundary locked; re-cluster the
result; record the new clusters as parents of the group's clusters; set each
parent's error to `max(own certified error, max child error)` so the bound is
monotone up the DAG. Stop when a level fits in one group.

**Out-of-core**, for input past what memory holds: stream the file once to build
a spatial bin index and the bounding box, then process one chunk at a time —
each chunk read, repaired, clustered and reduced to its first DAG level with its
chunk borders locked, and written out. The chunk borders are then released the
same way group borders are: the next level re-partitions across them, so nothing
stays locked for more than one level. Only one chunk's worth of geometry plus the
level's cluster metadata is resident at any moment, which is what makes the
50M-triangle case a matter of time rather than of memory.

Partitioning is ours, in the library. METIS is Apache-2.0 and would serve, and
the library will use it if `pymetis` is importable, but it will never be
required: a compiled graph-partitioning dependency on a default install is a cost
the engine should not impose.

**Selecting the cut** at runtime: a cluster is drawn when its own projected error
is within budget and its parent's is not. Monotonicity makes that test agree
across every former group boundary, which is what leaves no cracks — nothing is
stitched, and no neighbour is consulted. The test is a comparison over two float
arrays and a boolean and, so it vectorises over the whole DAG at once.

**Skinning, morphs and materials.** Joint indices are discrete: the survivor
takes the weights of the lower-error endpoint, renormalised and capped to four
influences, and a difference in joint sets adds a penalty so collapses prefer to
stay inside one influence region. Morph targets are decimated by applying the
base mesh's vertex remap to each target's deltas, so the targets stay consistent
with the base. Material boundaries are locked and clusters never span materials,
because a cluster is the unit of a draw.

## Ingesting a scanner asset

Photogrammetry and lidar output breaks the assumptions a textbook decimator
makes, and it breaks them every time rather than occasionally. The pipeline
handles it in a `repair` pass that runs before anything else, reports everything
it changed, and changes nothing the caller did not switch on:

- **Scale normalisation.** Scans arrive in arbitrary units. Every tolerance and
  attribute weight in the library is expressed against the bounding-box diagonal,
  so a model in millimetres and the same model in metres decimate identically.
- **Weld within a tolerance**, defaulting to a fraction of the diagonal rather
  than to exact equality, because a scan's "same" vertex differs in the last few
  bits.
- **Drop zero-area, duplicate and degenerate faces.** A scan is full of them and
  a quadric accumulated over a zero-area triangle is a NaN waiting to happen.
- **Remove floaters** — isolated components below an area or diameter threshold.
  These are the specks of noise reconstruction leaves in the air, and they wreck
  a bounding volume, a cluster partition and an error budget alike.
- **Fill holes below a perimeter threshold**, optionally. A scan is holed where
  the camera could not see; small holes are noise and worth closing, large ones
  are real absences and closing them invents surface.
- **Non-manifold tolerance.** Past the repair pass, the 2-complex formulation
  (M5) carries whatever is left — T-junctions, edges with three faces, isolated
  vertices — rather than refusing the mesh.

Scans also tend to carry colour per vertex rather than in a texture, which the
attribute quadric already handles as `COLOR_0`; and a unique-UV atlas, which
decimation preserves, so the existing textures keep fitting at every level. What
decimation cannot preserve is the *detail* that was in the geometry, which is
what M9's normal-map bake moves into the texture instead.

## Fitting an integrated GPU

The reference iGPU has no video memory of its own and is fill-rate limited, and
every choice below follows from that rather than from the geometry being clever:

1. **One bake, per-machine budget.** The cut is driven by a pixel-error
   threshold, so the same DAG is a 500k-triangle draw on Iris Xe and a 5M-triangle
   draw on a discrete card. A controller nudges the threshold to hold the budget,
   with enough damping that it does not oscillate against the frame rate it is
   measuring.
2. **Quantised, cluster-local vertex data**, per the survey's §6: roughly 12
   bytes per triangle instead of 40, which is both the memory budget and the
   bandwidth budget.
3. **Nothing uploaded per frame.** Resident clusters live in persistent buffers;
   the frame's only new data is a list of offsets and counts.
4. **Cull before selecting.** Cluster bounding spheres against the frustum is the
   same vectorised array pass as the cut, so it costs almost nothing and removes
   most of the geometry before any of it is submitted. Fill rate is the scarce
   resource; not submitting is the cheapest way to save it.
5. **No compute requirement.** GL 3.3 is the baseline path and it is complete.
   Compute is an optional tier for the cut, gated exactly as
   `character/gpuskeleton.py` gates GPU skinning, and the two must agree.
6. **Streaming against a byte budget**, so the asset's size and the machine's
   memory are independent numbers.
7. **A shared DAG, a cut per instance.** Instances of one asset share the baked
   geometry and the buffers; each needs its own cut, since each is at its own
   distance. Selecting for *n* instances is the same array pass with an extra
   axis, so a hundred instances cost little more than one — which is what keeps
   the per-frame budget at 1 ms for a scene rather than for an object.

## The editor

`openglcontext-editor` gains an asset decimation tool — the authoring toolkit is
where it belongs, since a shipped game loads the baked result and never runs the
decimator. What it does:

- Load a scanner or film-resolution asset, run `repair`, and report what it
  found — face counts, components removed, holes closed — because a silent repair
  on somebody's scan is not acceptable. The engine reads glTF and OBJ today;
  scans commonly ship as PLY, so a PLY reader is part of this milestone.
- Show a first coarse preview inside a second by decimating hard and fast, then
  refine in the background.
- Offer a target-count or target-error slider that responds immediately, by
  replaying a prefix of the cached `CollapseSequence` rather than decimating
  again. This is the single interaction that decides whether the tool feels like a
  tool, and it is why the sequence is a first-class object in the API.
- Show the error being traded: deviation against the original, the triangle
  count, and the estimated frame cost on a chosen hardware profile.
- Bake the result — a discrete chain, a cluster DAG, or both — with a normal map
  baked from the fine mesh, and write it where the engine loads it.

## Quality gates

Every one of these is a test with a number, not an eyeball check.

**Geometric.** Two-sided sampled Hausdorff and RMS deviation against the input,
normal deviation, UV distortion, and volume change, on shapes whose answer is
known analytically (a subdivided sphere's quadric error is computable) plus a
small corpus of real assets. The certified error a level reports must bound the
measured deviation — if it does not, the DAG's crack-freeness argument fails.

**Topological.** Manifold input stays manifold. No inverted triangles. No
degenerate triangles. Component count preserved unless pair contraction was asked
for.

**On-screen pop.** Extend the existing metric in
`tests/unit/test_lod_transitions.py`, which already measures the fraction of an
object's *own* pixels that change across a switch and already has a
holes-in-the-interior check. The gates: at the distance the error budget chooses
the switch, the pop is under budget; with geomorph on, the largest single-frame
delta across the whole transition is under a much tighter budget; and rendering
any valid cut of a DAG shows no background pixels inside the silhouette, which is
the crack test.

**Determinism.** The same input and seed give byte-identical output, on both the
NumPy and the Rust path, and the two agree with each other. The engine's
`OPENGLCONTEXT_SEED` already establishes this expectation.

**Throughput**, as budgets to measure against rather than claims:

| Path | Budget |
|---|---|
| Rust, one core, 1M triangles to 10% | ≤ 5 s |
| Rust, 8 cores, full DAG build on 5M triangles | ≤ 2 min |
| Rust, out-of-core DAG build on 50M triangles | ≤ 40 min, ≤ 8 GB resident |
| NumPy fallback, 100k triangles to 10% | ≤ 10 s |
| First editor preview, 5M triangles | ≤ 1 s |
| `CollapseSequence.at()` re-target, any count | ≤ 16 ms |
| Cut selection and frustum cull, 100k clusters, CPU | ≤ 1 ms/frame |

**Frame cost on the reference hardware.** A separate gate, because the rest of
the suite can be green while the thing is unplayable: a scene of baked DAG assets
drawn on the reference iGPU at 1920×1080 holds the budgets in *Targets* — 500k
triangles in the main view, 600 MB resident, under 200 draw calls. The engine's
telemetry (`OPENGLCONTEXT_TELEMETRY`) already records frame timings, so this is a
measured run rather than a new harness. Where the container has no Intel GPU, the
triangle, memory and draw-call counts are still gates; the wall-clock number is
recorded against whichever GPU ran it and compared only with itself.

A note on where each path wins, because it drives the milestones: the batch
schedule wins on large meshes, where arrays are long and Python's per-call
overhead disappears into them. The compiled path wins on a DAG build, which is
thousands of *tiny* simplifications of a thousand triangles each — there the
overhead is all there is.

## Milestones

Each names the test that goes red first, per the workspace's Red/Green rule.

**M0 — Project skeleton.** Done, except that the checkout is not yet a
submodule: that needs the GitHub repository created, and the `.gitmodules` entry
and initial push with it.

**M1 — Sequential QEM, manifold, border, position.** Done. Weld, classify,
accumulate with border constraints, heap schedule, validity tests, certify.
*Red:* a subdivided icosphere decimated to a quarter deviates from the sphere by
more than 0.01.

**M2 — Attributes.** Carried and seam-preserving (done: an output vertex is a
distinct point-and-attributes combination). Still open: Hoppe's extended quadric
so normals and UVs are part of the minimisation, plus skinning and morph-target
rules and material locking.
*Red:* a UV-mapped cube decimated across a seam slides its texture past the
distortion budget.

**M3 — Parallel schedules.** Multiple-choice (done: seeded, reproducible, within
a small factor of the heap's error). Still open: the batch-independent-set
schedule, which is the one that keeps the work in whole-array operations and
maps to a GPU kernel.
*Red:* the batch path's output differs between two runs with the same seed.

**M4 — The Rust accelerator.** `opengl_decimate_accelerate`: PyO3, maturin,
`rayon`, `abi3` wheels, GIL released. Differential-tested against the NumPy path.
*Red:* the two paths disagree on the corpus.

**M5 — Scanner input.** The `repair` pass (weld by tolerance, degenerate and
duplicate faces, floaters, small holes), scale normalisation, the 2-complex
formulation, pair contraction, generalised winding number.
*Red:* a self-intersecting multi-component scan crashes, loses a component, or
reports a repair it did not make.

*Why pair contraction is not optional, measured on an asset already in the
tree:* the forest demo's fir trunk is 4392 triangles over 2622 points, and 852
of those points are border — **246 separate open loops**, one per branch stub.
A loop cannot fall below three vertices, so the floor is 738, and the decimator
reaches exactly 738 points and 738 faces and stops. Nothing is wrong: an open
surface cannot be reduced past its own boundaries. Getting below that floor means
joining pairs that are not edges, which is what closes a stub and merges two
shells that touch — and it is the same mechanism a scan needs for the cracks
reconstruction leaves. Until then, a mesh of many small open shells reduces to
about a sixth and no further.

**M6 — Collapse sequence and instant re-target.** Done. `CollapseSequence.at()`
reaches any count, ratio or error by prefix replay, and agrees with a direct
`simplify` to the same count.
*Red:* `at(n)` costs materially more than one `at` call when asked fifty times,
or disagrees with a direct `simplify` to the same count.

**M7 — Cluster DAG.** Clustering, grouping, locked-border group simplification,
DAG assembly, monotone certified error, the baked `.npz` form.
*Red:* a cut through a built DAG leaves a crack the interior-holes test finds.

**M8 — Quantisation and out-of-core ingest.** Cluster-local integer vertex data
with per-cluster scale and bias; chunked streaming build for input larger than
memory.
*Red:* a 50M-triangle input exhausts memory, or the quantised DAG exceeds 12
bytes per triangle.

**M9 — Engine runtime.** `OpenGLContext/meshlod/`, the `MeshLOD` node, cut
selection and frustum culling, quantised vertex formats, the
`glMultiDrawElements` path, cluster streaming through the existing residency and
load manager, geomorph in `pbr.vert`, dither cross-fade, hysteresis, the
triangle-budget controller, and the editor's baker calling it.
*Red:* the pop metric on a real asset exceeds budget at the chosen switch
distance; and a scene of baked assets exceeds the reference frame budgets.

**M10 — Normal-map and attribute bake.** Transfer the fine mesh's normals — and
optionally its colour and occlusion — onto a coarse level's existing
parameterisation, by ray-casting along the coarse surface's normals against the
fine surface.
*Red:* a scan reduced a thousandfold and shaded with the baked normal map
deviates from the fine render past the pixel budget.

**M11 — The editor tool.** In `openglcontext-editor`: load, repair with a
report, first preview inside a second, an immediate target slider over the
collapse sequence, the error and cost readout, and the bake.
*Red:* the slider misses 16 ms, or the first preview misses one second.

**M12 — Optional GPU tier.** Compute-shader cut selection and indirect draw
behind `compute_is_available()`, with the CPU path as the fallback and both
producing the same cut.
*Red:* the GPU cut differs from the CPU cut on the same frame.

## Documentation

Part of the work, not a follow-up:

- A new `openglcontext/docs/meshlod.html`: what the node does, how to bake a DAG,
  the error budget's units and default, the triangle-budget controller, the
  streaming budget, the geomorph and cross-fade switches, and the limits (skinned
  meshes use the discrete chain; small objects should not pay for a DAG). Linked
  from `docs/documentation.html`, with the new subpackage added to
  `docs/structure.html`.
- `opengl_decimate`'s own `README.md` and `docs/`, covering the API table above,
  every option with its units and default, the repair pass and what each of its
  steps changes, and the quality/throughput numbers the suite measures.
- A page on the decimation tool in `openglcontext-editor`'s documentation:
  taking a scan from import to a baked asset, and what each readout means.
- `docs/baking.html` gains the mesh path beside the world-baking it already
  covers.
- The workspace `CLAUDE.md` project list gains `opengl_decimate` under
  "Renderer-agnostic engine components".
- `openglcontext/CLAUDE.md`'s directory map gains `OpenGLContext/meshlod/`.
- `plans/PROJECT-PLAN.md` gains the summary row.

## Licensing

Everything here ships BSD-style, so the sources this work may read matter.

**Safe to read:** the published papers listed below; `meshoptimizer` (MIT);
Assimp (BSD); METIS (Apache-2.0, and optional at that). A paper is the preferred
source in every case — it states the facts without carrying anyone's expression.

**Must not be read for this work:** MeshLab and VCGlib, CGAL's surface
simplification package, and Blender's decimation code, all of which are GPL.
Neither may `pymeshlab` become a dependency. If a fact is needed that only those
carry, [CLEAN-ROOM.md](../../CLEAN-ROOM.md) applies — a separate Reader agent, a
spec file under the consuming project's `specs/`, and the code citing the spec.
Anything not on the safe list has its licence checked before it is opened.

The Rust crate graph needs the same check: `pyo3`, `numpy` and `rayon` are
Apache-2.0/MIT, and every transitive dependency is audited (`cargo deny`) in CI
so a copyleft crate cannot arrive unnoticed.

## Open questions

1. **Name.** `opengl_decimate` follows the sibling convention, but the library
   ends up owning clustering and the DAG as well as decimation. `opengl_meshlod`
   describes the result better and dates worse.
2. **Rust in the workspace.** This is the first Rust in a Python-and-C tree.
   Worth confirming before M4; M1–M3 do not depend on the answer, and if the
   answer is no, the accelerator becomes Cython at a cost in complexity, not in
   capability.
3. **Baked format.** `.npz` is what the forest's runtime assets use and is enough
   to start. A glTF vendor extension for cluster DAGs would let the 3D Tiles
   pipeline carry them, and is worth defining once the DAG's fields stop moving.
4. **Skinned cluster DAGs.** The cut changes which vertices exist, which
   complicates a GPU skinning palette. The plan's answer is that skinned meshes
   use the discrete chain; whether that is good enough for a crowd of high-poly
   characters is a question for a later measurement.
5. **Reference hardware for the frame gate.** The container's GPU is AMD
   (radeonsi); the iGPU budgets need an Intel machine to be measured on rather
   than reasoned about, and `LIBGL_ALWAYS_SOFTWARE=1` answers a different
   question. Until one is available the triangle, memory and draw-call gates
   stand and the wall-clock gate is recorded per-GPU.
6. **The spatial index.** Hausdorff certification, the winding number, pair
   contraction and M10's normal bake all want the same thing: a ray- and
   box-queryable index over a triangle soup. The library builds its own rather
   than depending on a physics package, and `omi_physics.trigrid` is the shape
   that works — a uniform grid returning a superset the caller tests exactly.
7. **Quantised attributes in the semantics table.**
   `scenegraph/vertexsemantics.py` declares float attribute formats. Normalised
   integer forms have to join them without disturbing the programs that read the
   float forms, since the same locations serve the lit, unlit and shadow passes.

## References

- Rossignac & Borrel, *Multi-resolution 3D approximations for rendering complex
  scenes*, 1993.
- Schroeder, Zarge & Lorensen, *Decimation of Triangle Meshes*, SIGGRAPH 1992.
- Cohen et al., *Simplification Envelopes*, SIGGRAPH 1996.
- Hoppe, *Progressive Meshes*, SIGGRAPH 1996; *View-Dependent Refinement of
  Progressive Meshes*, SIGGRAPH 1997.
- Garland & Heckbert, *Surface Simplification Using Quadric Error Metrics*,
  SIGGRAPH 1997; *Simplifying Surfaces with Color and Texture Using Quadric Error
  Metrics*, IEEE Vis 1998.
- Cohen, Olano & Manocha, *Appearance-Preserving Simplification*, SIGGRAPH 1998.
- Lindstrom & Turk, *Fast and Memory Efficient Polygonal Simplification*, IEEE
  Vis 1998; *Evaluation of Memoryless Simplification*, 1999.
- Lindstrom, *Out-of-Core Simplification of Large Polygonal Models*, SIGGRAPH
  2000.
- Wu & Kobbelt, *Fast Mesh Decimation by Multiple-Choice Techniques*, VMV 2002.
- Cohen-Steiner, Alliez & Desbrun, *Variational Shape Approximation*, SIGGRAPH
  2004.
- Cignoni et al., *Adaptive TetraPuzzles*, SIGGRAPH 2004; *Batched Multi
  Triangulation*, IEEE Vis 2005.
- Trettner & Kobbelt, *Fast and Robust QEF Minimization using Probabilistic
  Quadrics*, Computer Graphics Forum 39(2), 2020.
  https://onlinelibrary.wiley.com/doi/full/10.1111/cgf.13933
- Karis, Stubbe & Wihlidal, *A Deep Dive into Nanite Virtualized Geometry*,
  SIGGRAPH 2021 Advances in Real-Time Rendering.
- *Interactive GPU-based Decimation of Large Meshes*, ACM 2023.
  https://dl.acm.org/doi/fullHtml/10.1145/3587421.3595422
- Liu, Zhang & Yuksel, *Simplifying Textured Triangle Meshes in the Wild*, ACM
  TOG. https://arxiv.org/abs/2409.15458
- *PaMO: Parallel Mesh Optimization for Intersection-Free Low-Poly Modeling on
  the GPU*, 2025. https://arxiv.org/abs/2509.05595
- Koh, *GPU-based Multiple-Choice Scheme for Mesh Simplification*, NTU.
- `meshoptimizer` (MIT), `clusterlod.h` and the DAG discussions at
  https://github.com/zeux/meshoptimizer/discussions/750
- Bevy virtual geometry, https://jms55.github.io/posts/2025-03-27-virtual-geometry-bevy-0-16/
