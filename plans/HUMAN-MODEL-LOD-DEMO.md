# A human model, decimated, walked up to

**Status:** 🟡 Mostly landed, 2026-09-19. The demo runs: `oglc-view` opens the
published content pack directly -- `oglc-view gallery-world.tar.gz` -- and it is
a hall of 120 marble busts on plinths, each a six-level `MSFT_lod` chain, and from
the far end 108 of them are on screen across four levels in **four instanced
draws** -- eleven for the whole frame. What is left is geomorphing (M9), the
baked normal map (M10), and lazy per-level decoding.

## What landed

**Authored in Blender, which is the part that matters to anyone else.** The
chain is not made by a script of ours that nobody else can run: it is cut by
Blender's own Decimate modifier through an add-on
(`OpenGLContext_editor/blender/openglcontext_lod`) that also writes `MSFT_lod`
from Blender's ordinary glTF export. An artist installs the add-on and never
installs this toolkit. The gallery world is built by that same add-on driven
headlessly (`oglce-gallery`), so what ships is what the add-on produces rather
than a second path that might disagree with it.

**The world is a room, not a void.** The earlier note here said "nothing else in
the scene: a background would only give the eye somewhere else to go". That was
wrong for the demonstration this turned out to be. A field of busts in a void
gives a viewer no sense of distance, and distance is the whole subject; a hall
with a floor, walls and beams receding is what makes the switch legible, because
the eye reads the depth off the room and then notices the geometry changing in
it. Polished parquet with a clearcoat, white plaster, dark beams -- all CC0 from
ambientCG, the bust CC0 from Poly Haven.

**A content pack, published from this repository.** `OpenGLContext/packs.json`
plus `release-assets.py`, the same three flags as every other project's. The
pack carries the finished world rather than the Poly Haven download, so nothing
is decimated at startup. It is the engine's own first content pack.

**Two defects the demo found, both fixed in the engine:**

- *Every coarse level was drawn in the wrong place.* An `MSFT_lod` alternative
  stands **in place of** the node that names it, so its transform is in that
  node's parent space; the reader was applying it underneath the carrier's
  instead. Translation doubled and rotation applied twice, which put a bust two
  metres down the hall four metres down it and facing elsewhere -- and it was
  invisible in every test until a chain was placed somewhere other than the
  origin *and* turned. Levels are now drawn where the carrying node is, and an
  alternative asking to stand somewhere of its own is drawn there anyway with a
  warning.
- *The light meter read one lamp and not the room.* `_meter_exposure` took the
  **strongest** light's illuminance at the scene centre where illuminance
  **adds**, so a hall with twenty lamps metered the same as a hall with one and
  rendered about that many times over.

**And one engine limit the demo has to live inside:** the forward PBR pass binds
eight lights. The gallery's lamps are therefore eight, spread the length of the
hall; twenty of them is not a brighter hall but the first eight lighting one end
of a dark one. Worth knowing before a world is authored, and worth lifting one
day.

## Why a human

Level of detail is judged on faces. A viewer will forgive a rock losing a
thousand triangles and will notice a chin losing ten, because a face is the one
shape everybody has been reading since birth. A demo that shows decimation
working on terrain proves nothing a viewer cares about; a demo that lets them
walk up to a head until it fills the screen, and back away, proves the whole
thing.

It is also the hardest case for the error metric. A quadric concentrates
triangles where curvature is, and on a head that is exactly where the eye looks
-- so a metric that is wrong shows up immediately rather than hiding in a
silhouette nobody studies.

## The asset

**`marble_bust_01` from Poly Haven** -- CC0, a human bust, 17,456 triangles,
9,746 vertices. It is what the measurements in
[MESH-DECIMATION.md](MESH-DECIMATION.md) were taken on.

Poly Haven is the right first source because its licence is unambiguous and
stated: everything there is CC0, and the engine already fetches CC0 material
from ambientCG through `loaders/cc0.py`, so the pattern exists.

**Two things to know about Poly Haven models.** The `1k`/`2k`/`4k`/`8k` suffix
is *texture* resolution -- the mesh is byte-identical in all four, so `8k` buys
bigger maps and not one extra triangle. And most of its models are retopologised
game assets in the tens of thousands of triangles; the scanned ones are where
the density is (`coastal_cliff_04` is 1.5M, `pine_tree_01` is around 24M).

**Higher-poly human subjects, to investigate.** 17k triangles is a thin slice of
what the decimator is for, and the demo would be better on a scan:

- **The Metropolitan Museum of Art** publishes 3D scans under CC0 through its
  Open Access programme. Sculpture and portrait busts, and the licence is
  explicit.
- **Smithsonian Open Access** -- CC0, with a working API
  (`api.si.edu/openaccess/api/v1.0/search`), and 3D holdings including busts.

**Three D Scans is not usable.** Its archive is exactly what this demo wants --
museum sculpture, millions of triangles, much of it human -- and it is widely
described as free of restrictions. But the site states no licence, on its front
page, its info page or its model pages. Under the workspace's licensing rule an
asset with no stated terms is an asset we cannot ship, whatever it is described
as elsewhere. Worth an email to the project asking them to state one.

## What the demo does

**Hundreds of busts, not one.** A gallery of them receding into the distance, and
a camera the viewer walks through it. One bust proves the metric; a field of them
proves the *system*, because it is the only arrangement in which every level of
the chain is on screen at once -- the near ones at level 0 and the far ones at
level 5, with the switch happening somewhere in the middle of the view where a
viewer can watch it. It is also the only arrangement that exercises what a game
actually pays: the draw call count with a chain in play.

**Which is where instancing meets level of detail.** The levels are decoded once
and shared, and the pass batches by the geometry and appearance a record uses --
so the busts at a given level collapse into one instanced draw and the frame
costs one draw per *level in use*, not one per bust. Two hundred busts over a
six-level chain is at most six draws. The readout should say so: busts on
screen, draws issued, and the split across levels, because the case for the
whole design is the distance between those first two numbers.

Nothing else in the scene: the subject of the demo is the geometry, and a
background would only give the eye somewhere else to go.

- **Walk in from far.** The chain switches down as the bust grows, and the
  switch distances are the ones `meshlod.measure_chain` computed for *this*
  model rather than numbers picked by hand.
- **A toggle to hold a level.** Freeze at level 5 and walk in, and the faceting
  is obvious. That is the point: the demo should be able to show the thing
  failing as well as working, or it is an advertisement rather than a
  demonstration.
- **A readout**: triangles drawn, the level in use, its measured outline and
  shading change, and the distance at which it was judged safe.
- **The transition itself.** With the level held, a switch is a pop; with
  geomorphing on, the vertices lerp along the correspondence `vertex_map`
  already provides. Being able to turn it off and on beside each other is what
  makes the case for it.

## What it needs that does not exist yet

1. **A content pack for the asset.** `OpenGLContext/contentpacks/` already has
   the registry, the fetch, the store and safe extraction, and requires a
   `copyright` field because the notices screen is generated from it. The bust
   becomes an entry in a `packs.json`; nothing large is committed. What the pack
   carries is the **baked chain** -- the glb plus its sidecars, as
   `meshlod.write_chain` produces them -- rather than the Poly Haven download,
   so the demo opens a file the loader already reads and nothing is decimated at
   startup. That makes this the engine's own first content pack: the three in
   the workspace belong to forest, twig-bb and glisteel, so OpenGLContext gains
   a `release-assets.py` of the same shape, publishing to a content tag on its
   own repository.
2. **The scene.** The loader's own: the pack's glb loads as a
   `ScreenCoverageLOD`, and the demo places copies of it. The levels are shared
   between the copies, which is what lets the batcher collapse them.
3. **Geomorph in the shader.** A second position stream and a morph factor in
   `pbr.vert`, per [MESH-DECIMATION.md](MESH-DECIMATION.md) M9.
4. **A baked chain on disk** -- which is what the pack carries, and
   `meshlod.write_chain` is what writes it. Decimating 17k triangles into five
   levels takes a few seconds; doing it at every startup is a few seconds
   nobody should pay, and doing it for the two hundred assets this design is
   aimed at is not a startup at all.
5. **A normal map baked from the fine mesh** (M10). The measurements say this is
   worth more to the coarse levels than any further decimator work: the outline
   is already within two per cent at a thirty-second of the triangles, and it is
   the shading that gives the level away.

## What it proves

That the engine can be handed a model at whatever density its author left it,
and produce the rungs itself, with the switching distances derived from
measurement rather than guessed -- which is the thing the engine could not do at
all before, and the reason [MESH-DECIMATION.md](MESH-DECIMATION.md) exists.

## Open questions

1. **How high-poly a human can we actually get under CC0?** The Met and the
   Smithsonian both need a search to answer rather than an assumption.
2. **Does the demo belong in `openglcontext/tests/` as a runnable script, or as
   its own project?** The forest and marble demos are separate projects; this is
   smaller than either and is closer to a reference scene, which argues for
   `tests/` beside the other runnable examples. A pack published from this
   repository argues the same way: the asset and the scene then live together.
3. **Which material.** The measurements were taken with a deliberately plain
   shader and a sharp specular, which is the pessimistic case. A real PBR marble
   will hide some faceting and show other artefacts; the switch distances should
   be re-measured against the material the demo actually uses.
