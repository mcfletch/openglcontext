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
| After | **0.005 ms** in a crowd of 250, and nothing uploaded but what it is playing |

Across the counts the plan asked for, every figure on screen and large:

| Figures | Animation | Drawing | Frame | |
|---|---|---|---|---|
| 100 | 0.8 ms | 2.7 ms | 3.5 ms | **283 fps** |
| 250 | 1.3 ms | 6.8 ms | 8.1 ms | **124 fps** |
| 500 | 2.4 ms | 14.1 ms | 16.5 ms | **61 fps** |

Two hundred and fifty figures were ~9 fps before any of this.

**What the tiers cost.** The engine's own floor is GL 3.3 with none of the
above; each tier is what a driver missing the one below falls back to, measured
at 100 figures:

| | Animation | Frame |
|---|---|---|
| Everything | 0.8 ms | **283 fps** |
| No compute (`OPENGLCONTEXT_GPU_SKELETON=0`) | 3.7 ms | 157 fps |
| No shader skinning either (`OPENGLCONTEXT_GPU_SKINNING=0`) | 68 ms | 13 fps |

The last row is where a figure started, and it is what a driver with no texture
unit to spare for a joint palette still gets, correctly.

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

## And the clips, too

`shaders/pose_blend.comp` finishes the job: a thread per joint of every figure
samples whatever clips that figure is playing and blends them by weight,
writing the translation, rotation and scale the skeleton pass then composes.
The build's clips are uploaded once -- a channel table indexed by
`(clip, joint, path)`, the keyframe times and values behind it -- and a frame
sends only what each figure is playing: a clip, a time and a weight per track,
sixteen bytes. At 250 figures the animation half went **3.9 ms → 1.3 ms**, and
at 500 it is 2.4 ms.

The blend is a weighted **mean**, the shortfall from where the joint rests, and
the shorter arc for rotations -- the arithmetic the numpy blend does, which is
what the test holds it to: over a fifty-seven bone rig, figures on different
clips at different moments, and a cross-fade at unequal weights, the two agree
to 1.7 × 10⁻⁷.

All three of glTF's interpolations: step, linear, and the cubic one that stores
a tangent either side of each value, which is what a curve authored rather than
baked exports as. Cubic cost the same to move across as the others -- at 250
figures on cubic clips the animation half is 3.7 ms on the processor and
1.2 ms here -- and it is held to the same agreement, on an asset whose tangents
genuinely bend the curve away from the line its keys would draw.

**Layers, in order, each masked to what it may move**, because that is what a
figure firing while it runs is: a base layer walking the whole body and an
upper one masked to the arms over it. The distinct masks of a group go up as a
bit per joint, deduplicated -- a crowd all firing from the shoulder is one mask
between them -- and the shader skips a layer for a joint the mask leaves out.

**What a figure still owes this side** is the joints something outside the rig
reads: a weapon hangs off a hand and the renderer walks to it, so that hand and
the joints down to it have to say where the pose put them. Those are worked out
here -- and *only* those. `ClipSampler.restricted` narrows a clip to a few
joints once, so reading the pose of ten joints costs ten channels rather than a
hundred and seventy, and the whole group's write-back converts out of numpy in
one go rather than once a figure.

For a figure of the shape twig-bb fields -- carrying a weapon, with a masked
upper layer -- 250 of them cost **15.5 ms of animation on the processor and
9.5 ms with the blend on the GPU**, which is 38 fps against 50.

**What it does not read**, and what therefore falls back to numpy for that
group: additive layers and morph weights.

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

## A lighter mesh at range

VRML97's own `LOD` node held several versions of a thing and the distances
between them, and always returned the first: choosing needed the viewer, which
nothing handed it. `scenegraph/lod.py` chooses now, and
`FlatPass.selectLevels` is what tells it where the viewer is -- once a frame,
before the render set is gathered, and **only from the camera**, since a shadow
pass draws the same scene from a light and detail chosen by how far off a
*lamp* was would swap levels as the sun moved. A change announces itself on the
signal a `Switch` uses, so the flattened scenegraph the pass renders from is
rebuilt for the new level. Every scene with an `LOD` in it gains this, not only
characters.

On top of it, `character/levels.py`: `model.add_level(source, distance)` reads
the coarser document, checks its skeleton is the model's joint name for joint
name, hands its meshes to the skins already being posed, and puts both under an
`LOD`. So a second level costs a figure **nothing per frame** -- one skeleton,
one pose, one range of the joint palette between them -- and the near figures
batch into one instanced draw while the far ones batch into another. A level
whose skeleton does not match is refused with a warning rather than adapted.

twig-bb uses it: the `*_lod1.glb` beside each build, which nothing had ever
selected, is drawn beyond eighteen metres. At 500 figures packed into thirty
metres the benchmark goes from 44 to 48 fps; a scene where most figures are
genuinely distant gains more, since more of them are on the lighter mesh.

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

* **Additive layers are blended on the processor.** A layer that adds its
  difference from a reference frame needs that frame sampled as well, which is
  a second read of every channel; the shader does not do it, so a group using
  one is blended in numpy.
* **Level of detail is by distance, not by screen size.** A figure's size on
  screen is its distance *and* the field of view; `LOD`'s ranges are VRML97's
  own and are in metres, so a scene that changes its field of view materially
  would want its ranges chosen for the widest.
* **The per-figure load swap.** A figure still arrives with its level rather
  than swapping from a stand-in the moment its own load posts.
* **Morph weights are not batched.** A group whose clips drive them falls back
  to posing its figures one at a time; morph weights are per mesh and of no
  fixed width, so they do not join the skeleton's arrays.
* **Integrated graphics are unmeasured.** There is none on this machine. Every
  tier below the top one is exercised and correct (the table above), so what is
  unknown is the *speed* of a part whose vertex throughput and bus are much
  smaller, not whether it works.
