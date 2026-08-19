# Rigged characters: skeleton, blending and attachment points

**Status:** shipped (2026-08-18)

## What it is

`OpenGLContext.character` — the layer between "the glTF loader can play one
animation" and "a game can field a crowd of people". Three pieces, each usable
on its own, and a fourth that is the three of them over one document:

| Module | What it answers |
|---|---|
| `character/humanoid.py` | which joint of a document is which bone of a body |
| `character/mixer.py` | more than one clip playing at once |
| `character/attachment.py` | where a weapon, a tool or a hat goes |
| `character/model.py` | the three together, over one loaded glTF |

`OpenGLContext/bin/character_sheet.py` (`oglc-character-sheet`) is the review
tool: every clip of a model, from four sides, as contact sheets with an index
page. The laying-out half of it is `OpenGLContext.contactsheet` -- `tile` for
one sheet and `index` for the page over a directory of them -- which is not
about characters at all and is used by anything that wants to look at a lot of
frames at once, a game's own review tools included.

User documentation is [docs/characters.html](../docs/characters.html).

## Why these three and not others

They are what every game needs and no game should write twice, and each one is
a place where glTF stops short of what a character is:

* **The skeleton.** glTF names joints whatever the author typed. A game asks
  for "the right hand". The map between the two is the thing, and the
  vocabulary chosen for it is **VRM 1.0's humanoid bones**, because it is a
  published standard with an existing toolchain rather than a fourth naming
  convention of our own. `VRMC_vrm` is read where a file states its own map;
  where it does not, the naming conventions in circulation (VRM's own,
  Mixamo's, Unreal's, Rigify's, and the numbered joint chains the Khronos
  rigged samples use) are read instead. Content that follows none of them
  resolves to nothing, and a caller can tell that apart from a partial rig.

  **A name is read in the company it keeps.** Some rigs cannot be read a bone
  at a time: `spine_01` is the first spine segment on Unreal's mannequin and
  `Spine1` is the *second* on Mixamo's, and a rig read the wrong way has its
  chest where its waist should be. `humanoid.FAMILIES` matches the whole
  skeleton against the set of names a family carries all of — `pelvis` with
  `clavicle_l` and `spine_01` beside it — and reads it from that family's own
  table. Adding a family is a signature and a dictionary; a rig that matches
  none is still read name by name.

* **The blend.** glTF stores clips and says nothing about playing two. A
  character running while it fires is two clips at once, and easing from a walk
  to a run is two more. Layers in order, each masked to the joints it may move,
  each a cross-fade of its own tracks, with additive layers for anything that
  is a difference rather than a pose.

* **The attachment point.** glTF needs no extension: a node parented to a joint
  already inherits that joint's animated transform. What was missing was the
  convention and the lookup, which is thirty lines and no format risk.

  **The convention has two sides**, and the second one matters as much: a rig's
  `socket_grip` says where a thing goes, and a node of the same name *inside
  the thing* says where it is held. `mounted()` lines the two up. Without it a
  weapon hangs off a fist by whatever point its modeller built it about — for
  the rifle here, its balance point, fifteen centimetres from the hand — and
  every game that loads it carries a table of per-model offsets to correct for
  that. With it the fact is stated once, in the model, and re-modelling a
  weapon does not move the hand that holds it.

  The registry was checked again for this (2026-08-18): Khronos has no
  attachment-point extension ratified, in progress or vendor-supplied, and OMI
  has none either — `OMI_seat`, which seats an avatar, is the nearest thing in
  either set. So there is nothing to adopt, and a named node is not a
  workaround for the absence: it is what the format already offers, and it
  survives every tool precisely because it is not an extension.

## Standards read before writing any of it

| Standard | What it gave |
|---|---|
| **VRM 1.0** (`VRMC_vrm`) | the humanoid bone vocabulary, its required subset, its parent chain, and an extension a file can state its own map in |
| **VRM Animation** (`VRMC_vrm_animation`) | the same map in a clip-only document, so a retargetable clip file resolves |
| glTF 2.0 skins / animations | already implemented in `loaders/gltf` |
| OMI's extension set | checked for an attachment/socket extension; there is none, and none is needed |
| Khronos registry, re-read for the model's own side of a socket | no attachment point in any state -- ratified, multi-vendor, vendor or in progress |

There is no standard for animation blending, and nothing proposed; it is
runtime behaviour in every engine. What is standardised is the *clip*, which is
what the mixer consumes.

The VRM specification is published under the MIT licence. Names and a schema
are facts about a format; no VRM code or asset is in this project.

## What the loader gained

`GLTFScene` now exposes the document's node hierarchy and names, which the
three modules need and which nothing else could reach:

* `node_roots` / `node_children` — the hierarchy (previously private
  `_skin_roots` / `_skin_children`)
* `node_names` — the name a document gave each node, which a DEF is not: a DEF
  is sanitised for VRML and made unique
* `extensions` — the document-level extension object, so a consumer can read an
  extension the loader itself does not

`quat_multiply` and `vrml_to_quat_xyzw` joined the quaternion helpers in
`loaders/gltf/animation.py`.

`AnimationMixer.reset` (and `CharacterModel.reset`) stops every layer at once
and writes the rest pose back. What needs it is a respawn: death is a state a
body is *held* in, so something has to say it is over -- and a fade would blend
out of dying into the next thing, which is a body easing back to its feet.

`OpenGLContext.quaternion.fromMatrix` reads a rotation back out of a matrix,
which is the inverse of `Quaternion.matrix` and what `mounted()` needs to turn
a node's composed world transform into a VRML `rotation` field. Going through
the quaternion rather than reading an axis off the matrix is what keeps it
stable at a half turn, where the axis terms vanish; `move/followcam.py` had its
own copy of that arithmetic and now calls this one.

## What the viewer gained

`apply_render_env` and the renderer defaults moved out of `bin/view.py` into
`viewer/environment.py` as `apply_render_env` and `viewer_defaults`. A program
that embeds `ViewerContext` without a command line needs both — several viewer
options are read once by the passes at start-up — and a viewer configured
without them renders with a different pass from the one `oglc-view` uses. The
contact-sheet tool found this the hard way, which is the argument for the move.

## Left open

* **Retargeting.** A clip authored against one rig plays on another only where
  the two skeletons agree. The humanoid map is what a retargeter would need;
  the retargeter itself is not written.
* **`VRMC_springBone`.** Secondary motion for hair and cloth is a published VRM
  extension and is not read. Hair driven by an authored bone chain works today;
  hair driven by the spec's spring simulation does not.
* **`KHR_materials_variants`.** A ratified extension for switching a model
  between authored material sets, which is what a per-team colour wants to be.
  Not read; a game repaints a named material instead.
* **A second UV set, or an ORM texture.** A figure carries a base colour and a
  normal map on one unwrap; roughness and metallic are per-material constants.
  A model that wanted its roughness to vary across a surface would need the
  loader to be given a second set, which it already reads, and its generator to
  paint one.
* **Retargeting a *shape*, not only a name.** The family table says which bone
  is which. It says nothing about a rig whose rest pose is an A-pose where a
  clip was authored against a T-pose, which is the other half of playing
  somebody else's animation.
