# A crowd of individuals, and the shadows they cast

**Status:** shipped (2026-08-29).

[CHARACTER-SCALING.md](CHARACTER-SCALING.md) made a hundred and fifty figures
cost what one used to. What it left is that they had nothing to be individual
*about*: the crowd demo played one clip on every body from a phase offset, so
the field was one figure drawn a hundred and fifty times at a hundred and fifty
points of the same stride. Two things came out of looking at it.

User documentation is [docs/characters.html](../docs/characters.html) ("A crowd
that walks about"), [docs/shadows.html](../docs/shadows.html) ("What a Rigged
Figure Casts") and [docs/instancing.html](../docs/instancing.html) ("Skinned
figures").

## The shadows stood still

Every figure in the demo cast the shadow of the pose the model was built in,
whatever it was doing. The colour pass and the shadow depth pass both batch
skinned figures into one instanced draw, and both draw through a program
carrying `_skinning_inc.glsl` — but only the colour pass handed its batch the
joint palette. `_renderDepthGroup` set the instancing uniform and drew, never
calling `set_skinning` and never packing a per-instance joint base, so the
depth program's `skinningEnabled` stayed at the 0 it was compiled with and
every instance wrote the rest pose into the shadow map.

It showed only for a *batched* caster. A figure drawn on its own goes through
`PBRMesh.render`, which sets the uniform against whatever program is bound —
the depth program, during the depth pass — so `OPENGLCONTEXT_INSTANCING=0`
rendered the same scene with the shadows following the strides.

That difference is the fix's test, and it is the invariant worth holding:
**batching changes nothing about the picture.** `tests/helpers/_skinning_harness.py`'s
`shadows` job renders a shadowed field of posed figures batched and then
per-shape, and the two frames have to agree —
`tests/unit/test_character_gpu_skinning.py::TestShadowsFollowThePose`. Before
the fix 9.5% of the frame differed; after it, none of it does.

The gathering of a batch's joint bases moved out of `PBRPass` into
`passes/instancing.py` (`instance_joint_bases`, `member_joint_bases`), since
two passes now want it and it is about instanced draws rather than about
colour. Whichever pass runs first in a frame writes the palette and the other
finds it written.

## A layer's weight came from whichever figure led the group

Found on the way to the second half, and a defect in `Crowd` on its own.
Figures are gathered by the *shape* of the work — which layers contribute, what
each is masked to, whether it is additive — deliberately not by the weights, so
that a field part way through a fade is one group and not a hundred and fifty.
`_plain` then decided whether the group could skip the blend entirely by
reading `group[0]`'s layer weight, and applied that answer to every member. A
group led by a figure at full weight wrote the clip straight into the pose of a
member at half, snapping it to the full pose.

Nothing in the engine produced that before, because nothing dialled a layer's
weight per figure across a crowd. `_plain` now reads every member's, so one
figure mid-fade puts the whole group on the blend path —
`tests/unit/test_character_crowd.py::TestManyFiguresAgree::test_figures_whose_layers_are_at_different_weights_agree`.

## What makes a crowd a crowd

`OpenGLContext/character/wander.py`, in three parts that are usable apart:

- **`Wander`** — where every figure is, which way it faces, and what it is
  doing: walk for a while, halt, turn towards somewhere else, walk again. A
  state machine over arrays with a figure axis on it, in the manner of `Crowd`'s
  posing; no clips, no scenegraph, no GL, and every decision drawn from a named
  `entropy` stream, so a seeded session walks the same walk. 150 figures cost
  **0.045 ms** a frame.
- **`Gait`** — one figure's clips dialled between standing and running. Three
  layers: the model's idles underneath, the walk and the run over them at the
  weight the body is travelling with. A body at half speed is a blend of the
  idle and the walk, one picking up speed a blend of the walk and the run, one
  that has stopped the idle alone. Each clip's clock is scaled by the body's own
  speed against that clip's stride, so the feet stay on the ground at any pace.
  A model carrying several idles is given all of them and a figure steps on to
  the next each time it halts.
- **`WanderingCrowd`** — the two tied to a `Crowd` and to a `Transform` per
  figure, plus `schedule(eye, bands)`, which sets each member's pose rate from
  how far it is from the eye. Which figures those are now changes every frame,
  since the field moves.

**Which way a model faces, and how far each clip carries it, are measured.** The
first cut guessed both and got both wrong: figures travelling along
`(-sin θ, -cos θ)` and a stride read off the widest foot swing in rig-root
space. The result was a field of bodies sliding forwards while their legs strode
backwards. Neither error is visible in a still frame — a stride looks the same
either way round until something moves — and neither is deducible from the mesh.

One measurement settles both: play the clip and watch what is touching the
ground. It travels backwards under the body at the speed the clip carries the
body forward, so its velocity is the stride and its direction is the model's
forward. As a fraction of body speed, what is on the ground drifts ~9% with both
right, 19% with the stride out by a quarter, and **103%** with the direction
reversed, which is the moonwalk. `Wander` now states the convention (heading is
measured from +Z, which is what `rotation=(0, 1, 0, heading)` applied to +Z
means) and `WanderingCrowd` takes a `facing` for a model authored the other way,
so the correction is one declared number rather than an assumption buried in the
arithmetic. `TestTheDemoDoesNotMoonwalk` holds the demo's constants to it,
reading the posed mesh rather than a foot bone so it works on a quadruped.

**The demo is `Fox`, not `CesiumMan`.** A crowd needs an idle to blend against,
and `CesiumMan` carries one clip: a walk. Standing was made from it by holding
one frame with the clock stopped, and a frozen mid-stride frame reads as
exactly that. `Fox` is the one rigged model in the Khronos catalogue carrying
several — `Survey` (a look-around that carries the body 0.00 units/s, a true
idle), `Walk` (102.7 units/s) and `Run` (171.9) — and at one mesh and 1728
vertices it is lighter than `CesiumMan`, so a hundred and fifty of them still
collapse into one instanced draw. `BrainStem` was measured for the same job and
is not viable at crowd scale: its single 34.9 s animation really is a varied
performance, but at 59 meshes and 62k triangles a figure it renders at 2.2 fps
for 150 and 18.7 for 20, and posing is only 9% of that.

**Only what moved is written back.** A step reports `walked` and `turned`, and
`_place` writes a node's `translation` or `rotation` only for the figures they
name — a figure walking straight ahead does not turn, and a standing one does
not move. Setting a scenegraph field costs ~3.4 µs (coercion, then the
dispatcher), which for 150 figures twice a frame was 1.09 ms of a 16.6 ms
budget; placing the field now costs **0.54 ms**.

`Crowd.groups` says how many runs of arithmetic the last update took, which is
the number that says whether a crowd is gathering. The demo reports it: a field
where some are walking, some standing and some between costs one run for each
kind.

## Left

- **Placing a crowd is still dominated by the scenegraph's field writes.** The
  0.54 ms above is 150 `SFVec3f`/`SFRotation` sets; a profile puts ~56% of one
  in `pyvrml97`'s `fieldtypes.coerce` and ~34% in `pydispatch`'s receiver
  lookup. Both are hot paths for *anything* that moves, not only for crowds,
  and both are in sibling repositories — their own piece of work.
- **Figures walk through each other.** There is no avoidance and no collision;
  a game would put its own steering over `Wander` or use it as the wander
  behaviour under one.
- **The ground is flat.** `WanderingCrowd` takes one `elevation`; a field over
  terrain wants a height query per figure.
- **A small caster over a wide scene loses its shadow, and this demo is one.**
  Nothing to do with the batching fixed above — it reproduces with a plain
  unscaled `Box`. In a 24 m scene with a directional light, `CesiumMan` at 1.6 m
  casts a clear shadow while a 0.5 m box beside it casts none, whether or not
  the box is reached through a scale. The fox crowd is knee-high over a 26 m
  field and shows almost no shadow at all, so the demo does not presently show
  the thing the first half of this plan fixed. Zeroing `SHADOW_POLYGON_OFFSET_UNITS`
  and `SHADOW_NORMAL_OFFSET` changed nothing measurable, so the cause is **not
  yet known** and the bias constants are only the first place to look; cascade
  fitting and the caster set are the others. Its own piece of work, and it wants
  a reproduction in `tests/unit/` before anything is changed, since the bias
  balance is shared by every shadowed scene in the suite.
