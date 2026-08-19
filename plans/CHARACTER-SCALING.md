# A crowd of rigged figures at frame rate

**Status:** shipped (2026-08-19) for the per-frame path; the demo-side wiring
and the load-time swap are listed at the end.

The engine half of
[twig-bb/plans/PLAN-CHARACTER-ANIMATION-SCALING.md](../../twig-bb/plans/PLAN-CHARACTER-ANIMATION-SCALING.md),
whose load-time half (a fast glTF decode, `parse_gltf`/`SharedDocument`) landed
first. This is the per-frame half: what a figure costs every frame, and what
two hundred and fifty of them cost together.

User documentation is [docs/characters.html](../docs/characters.html) ("Many
figures at once" and "Where the skinning happens").

## What a figure cost, and what it costs

One figure of a fifty-seven bone rig, ~4 000 skinned vertices, twenty-three
clips, measured on an RTX 3060 Ti:

| | Per figure, per frame |
|---|---|
| Before | **2.85 ms** of processor time, plus a re-upload of every deformed position, normal and tangent |
| After | **0.016 ms** in a crowd of 250, and nothing uploaded but the pose |

Two hundred and fifty figures, all on screen, all on their own clocks:

| | Animation | Drawing | Frame |
|---|---|---|---|
| Before | ~71 ms | ~39 ms | ~9 fps |
| After | **4.0 ms** | 16.2 ms | **50 fps** |

The drawing column at that count is mostly the GPU filling pixels rather than
work the engine is doing: the processor-side cost of the whole frame is 12 ms
of the 20. At a hundred figures the frame is 7.5 ms (134 fps).

The benchmark is `tests/helpers/_crowd_perf_harness.py`; it takes a figure
count and reports the split, and `joints`, `vertices`, `skinning`, `compute`,
`crowd` and `budget` switch each lever independently.

## The five things that were expensive

Each was most of the cost once the one before it was gone, which is why they
are all here rather than one of them.

### 1. A clip was sampled a channel at a time

An exported character clip carries a channel per joint per path -- a hundred
and seventy for this rig -- and each was a search and a blend of its own.
**`character/clip.py`** regroups a clip once, at load: channels that share a
time grid, an interpolation and a path become one block, so one search serves
the whole block; and a channel that holds one value for the clip's whole length
-- 157 of the 171, because an exporter writes every joint whether it moves or
not -- is answered from that value with nothing to search. **7.5×**, and it is
the same answer: the test is agreement with `Animation.evaluate` at the
keyframes, between them and outside the clip at either end.

### 2. The skeleton was walked a node at a time, through the scenegraph

`compute_world_matrices` read each joint's `Transform` fields, built a matrix
through pyvrml97 and composed them recursively. **`character/rig.py`** lays the
hierarchy out as arrays -- parents before children, the parent of each slot as
an index, slots grouped by depth -- so composing a generation is one matrix
product. **10.6×**, and in double precision where the walk was in single.

### 3. The pose was written back to joints nothing reads

A joint whose only children are further joints is read by nothing: the skin
takes its matrices from the pose arrays directly. `pose_write = 'exposed'`
writes only the joints something outside the rig reaches -- a mesh, an
attachment point with a weapon on it -- and every joint on the way down to one.
Which joints those are is settled against a counter the attachment API bumps,
not by walking the skeleton, because a crowd asks the question once a figure a
frame. The default is still `'all'`: a game that reads a joint's transform
should find it current.

### 4. Skinning was a CPU deform and a vertex re-upload

`PBRMesh._apply_deform` blended four joint matrices per vertex in numpy and the
result went up the bus every frame. It now happens in the **vertex shader**
(`shaders/_skinning_inc.glsl`), reading a **joint palette** -- one growable
texture buffer for the whole context, each mesh holding a range of it
(`scenegraph/skinning.py`). What crosses the bus per frame is a matrix per
joint. The CPU deform stays as the reference and as the path for a driver with
no texture unit to spare; the test is that a posed figure rendered each way
comes out the same, against a real driver.

Two things follow. A skinned mesh's vertex arrays now hold the **rest pose**,
so `PBRMesh.posed_positions()` is how a caller gets the posed ones; and its
bounds are worked out from the joints -- the union over joints of the sphere
around that joint's own rest vertices, carried by its matrix -- rather than
from vertices that no longer move.

### 5. Every figure was a run of arithmetic of its own

On a few dozen rows almost all of what a numpy call costs is setting the call
up, so posing 250 figures one at a time cost 250 × the set-up and barely more
arithmetic than posing one. **`character/crowd.py`** does the work for every
figure it holds in one pass over arrays with a figure axis on them. Figures
doing the same *kind* of thing are answered together -- the same layers, masks
and number of clips, whatever their weights, wherever their clocks stand, and
**whichever clips they are playing**: only the sampling has to know that, so a
crowd on twenty-three different clips is still one blend.

It is not an approximation. Cross-fades, masked layers, part weights and
additive layers all batch, and the test is that a figure in a crowd ends the
frame in the pose it would have been in on its own.

## And then the same work again, on the GPU

With the above, composing skeletons and assembling palettes was what remained.
`character/gpuskeleton.py` moves it across: per frame the crowd uploads the
**pose** -- forty-eight bytes a joint -- and two compute dispatches
(`shaders/skeleton_world.comp`, `shaders/skeleton_palette.comp`) write the
palettes straight into the buffer the skinning shader already reads. Nothing is
read back.

* **Compute in a GL 3.3 context.** `ARB_compute_shader` and
  `ARB_shader_storage_buffer_object` are GL 4.3 features that many 3.3 drivers
  expose, so asking for the *extensions* rather than the version is what lets a
  context built to the engine's floor use them. Where they are absent the crowd
  does the same arithmetic in numpy.
* **One thread per joint, walking to the root.** Composing a generation at a
  time would need a dispatch per generation and a buffer of local matrices;
  walking up instead costs each thread as many small products as the skeleton
  is deep and buys the whole pass. A GPU has far more threads than a skeleton
  has joints.
* **The bounds still come back to the processor**, but only every sixth frame:
  nothing reads a palette back, and a figure's bounds move slowly enough that
  ten times a second is plenty for culling and for what reads a scene's extent.
* 250 figures: the animation half went **8.3 ms → 4.0 ms**, and the palette
  uploads left the draw as well.

The test is agreement with the numpy path, joint for joint, on a fifty-seven
bone rig -- to 3 × 10⁻⁸, which is single-precision round-off and what the
palette is stored in either way.

## Drawing them

A crowd of figures out of one build hold the **same rest-pose vertices**, so
they batch on content like any other repeated mesh; each instance carries the
place its own joints start in the palette (attribute 14), so one
`glDrawElementsInstanced` covers a hundred bodies in a hundred poses. A figure
the CPU skins is excluded, because its buffers hold its *posed* vertices and no
two of them are the same geometry.

Two things were found in the way and fixed for every instanced draw, not only
skinned ones:

* **A material's packed block is kept against its own `_ubo_version`.** An
  instanced group repacked its whole material table every frame; a crowd out of
  one document carries a material apiece that nothing is changing.
* **The material table groups by what a material says, not by which object says
  it.** 250 identical materials filled the table with copies of one entry and
  split the batch into a draw per seventy-three figures.

Together these took the draw of 250 figures from ~16 ms of processor time to
~4 ms.

## Not posing everyone

`Crowd.update(dt, budget=N)` brings at most N figures up to date, taken in turn
so none is starved, and a member's `rate` asks for it less often again. Clocks
always run, so a figure posed every third frame is where its clip says it is
when its turn comes. At 250 figures a budget of 80 takes the animation half to
2.7 ms.

## A capture no longer depends on how fast the machine is

Found while proving the shader's skinning matched the processor's: a skinned
conformance view had regressed, and it was not the skinning -- the two render
identically. Image-based lighting steps down when the frame rate sags and
climbs back after headroom, and the capture was being taken at whatever point
of that climb it happened to reach, so a faster frame produced a different
image.

Adaptation is a courtesy to somebody watching and **a capture has nobody
watching**, so a capture now pins it, exactly as it already pinned the shadow
cascades. The Parthenon conformance views, documented as bimodal and failing
about half the time, are now bit-deterministic; `RecursiveSkeletons` was
separately nondeterministic because it is animated and its scene entry pinned
no `anim_time`, and now does. Three baselines recorded the half-adapted state
and were re-blessed.

## Left open

* **The clip blend itself is still on the processor.** The GPU does the
  skeleton and the palettes; sampling and blending is ~2 ms of the 4 at 250
  figures. Putting it across means the whole pose set on the GPU -- the clip
  keyframes as buffers, and a bounded per-figure track record uploaded each
  frame -- which is a natural extension of `gpuskeleton.py` and its buffers.
* **Level of detail by screen size.** The `*_lod1.glb` beside each character is
  never chosen; `Crowd` has the update budget and rate, but nothing picks a
  coarser *mesh* for a distant figure.
* **The per-figure load swap.** A figure still arrives with its level rather
  than swapping from a stand-in the moment its own load posts.
* **Morph weights are not batched.** A group whose clips drive them falls back
  to posing its figures one at a time; morph weights are per mesh and of no
  fixed width, so they do not join the skeleton's arrays.
