# BodyParts3D: a named, hierarchical anatomy dataset

**Status: 📋 Planned**

[BodyParts3D](https://dbarchive.biosciencedbc.jp/en/bodyparts3d/) is the Database
Center for Life Science's anatomy database: a whole human body as separate
polygon meshes, one per organ, each carrying its Foundational Model of Anatomy
concept id and its English name, with a part-of hierarchy given as a separate
table. Release 4.0 is on the archive as two zips of Wavefront OBJ plus
tab-delimited metadata, under CC Attribution 4.0 International.

It is worth having because of what it is shaped like. Every large scene in the
tree today is either **few meshes drawn many times** (the forest: instanced trees
and grass) or **many tiles mostly culled** (Toronto: 83,064 buildings spread over
15 km, a horizon's worth of them off-screen at any moment). BodyParts3D is
neither: 1,258 distinct meshes, no two alike, all inside 1.7 m, all potentially
visible at once, nested inside each other. That combination — dense, interior,
named, hierarchical, translucent-shells-over-contents — exercises paths the other
two datasets never reach.

## The dataset

Measured from `partof_BP3D_4.0_obj_99.zip` (2026-09-09).

| | |
| --- | --- |
| Distribution | `isa_BP3D_4.0_obj_99.zip` (136 MB) and `partof_BP3D_4.0_obj_99.zip` (62 MB) under `https://dbarchive.biosciencedbc.jp/data/bodyparts3d/LATEST/`, plus five tab-delimited metadata files (parts lists, inclusion relations, composite-part definitions) |
| PART-OF release contents | 1,258 `.obj` files, 218 MB expanded, 839 distinct representation ids (52 of the files are `M`-suffixed mirrored counterparts) |
| Largest mesh | `FJ2810`, the skin: 102,467 vertices, 203,382 triangles, 408,332 lines of text |
| Geometry | `v` and `vn` only — no `vt`, no `mtllib`, one `g grp1` and one `usemtl mtl1` per file, faces as `f v//vn`. Colour and material are the viewer's to choose |
| Frame | Millimetres, Z-up, origin at neither the feet nor the centre: the skin spans (-334, -247, -78) to (333, 45, 1641), so a 1.72 m body standing along +Z |
| Per-file header | `File ID` (the filename, `FJnnnn`), `Representation ID` (`BPnnnn`), `Concept ID` (`FMAnnnnn`), `English name`, `Bounds(mm)` and `Volume(cm3)` — present on all 1,258 files |
| Metadata join | The parts lists are keyed on concept id and representation id; the OBJ **filenames are file ids**, which appear only inside the headers. Name, id and hierarchy therefore join through each file's header block, not through the filename |
| Hierarchy | `partof_inclusion_relation_list.txt`: 1,367 parent→child rows, each naming both ends. 546 listed parts have no mesh of their own — a composite organ is drawn by drawing its atomic parts |

The IS-A release is the larger one (2,905 listed parts); PART-OF is the one to
build against, and is the tree an anatomy browser wants.

## Licence

The [licence page](https://dbarchive.biosciencedbc.jp/en/bodyparts3d/lic.html)
states **Creative Commons Attribution 4.0 International**, with the attribution
string "BodyParts3D, © The Database Center for Life Science licensed under CC
Attribution 4.0 International".

The comment block at the top of each OBJ in release 4.0, and the 2011 README
still on the archive, carry the older CC Attribution-Share Alike 2.1 Japan text
and its attribution string. Share-alike is on this workspace's forbidden list
(see the root `CLAUDE.md`), so the discrepancy has to be settled by a human
before any of these bytes are redistributed from here — not worked around by
picking the more convenient of the two statements.

**The design does not wait on that answer, because it never redistributes the
data.** `loaders/cc0.py` already does exactly the right thing for ambientCG
materials: fetch once from the publisher, cache under the per-user app-data
directory, write a provenance manifest, and fall back to something local when
offline. BodyParts3D is fetched the same way — nothing enters the repository, the
user's copy comes from DBCLS, and the attribution string is displayed in the
viewer and written into the cache manifest. The archive server's own bytes are
what any question of licence attaches to.

## Engine work this asks for

Each item is an OpenGLContext capability with the anatomy demo as a caller, not
a capability built inside the demo.

**1. A fast OBJ read path.** `loaders/obj.py` parses line by line in Python and
builds `IndexedFaceSet` index lists element by element. The skin alone is 408,332
lines; the set is 218 MB across 1,258 files, and read at the current rate that is
the whole of the load time. A numpy path — bulk-decode the `v`/`vn`/`f` blocks
into arrays instead of appending to Python lists — is worth having for every OBJ
any `oglc-view` user opens, and this dataset is what makes it measurable. Keep the
existing parser's output exactly: same nodes, same DEF names, same winding.

**2. A manifest read from headers, before any geometry.** Name, bounding box and
volume for all 1,258 parts come out of the first fourteen lines of each file.
That is enough to build the shelf entry, order the load by size or by distance,
cull, and pick an LOD — all without parsing a triangle. The engine shape is the
one 3D Tiles already has from `tileset.json`: an index a `SceneAdapter` pages
against. OBJ has no such index; this dataset supplies one, and the mechanism
belongs beside the adapter rather than in the anatomy code.

**3. Units and up-axis declared by the source, not baked into the files.** mm,
Z-up, and an origin that is not on the ground. The 3D Tiles path answered this
already (`tileset.Z_UP_TO_Y_UP`, `ViewerScene.metric`, the levelling matrix); OBJ
has nowhere to record it, so the adapter needs to carry a source frame —
scale, up-axis and grounding — and apply it once. Pre-scaling the cached files
would be the workaround; the adapter is where it belongs.

**4. Picking that answers with a name.** 1,258 named parts is the case the
picking work has never had: click a shape and get `FMA7163 / Skin` back, not an
index. The MRT selection buffer already returns the node; what is missing is the
path from node to the loader's metadata for it.

**5. The scenegraph tree beside the view.** `OpenGLContext/outline.py` renders a
scene as rows for a `ttk.Treeview` / `QTreeWidget` / `wx.TreeCtrl`
(EMBEDDING-EXAMPLES). The part-of hierarchy is 1,367 real parent→child rows with
names on both ends — an inspector tree with something to say, and a two-way
selection test (pick in the view, highlight in the tree; select in the tree,
frame in the view).

**6. Order-independent transparency, on geometry that needs it.** Skin over
muscle over viscera is nested translucent shells with no correct back-to-front
order — sorting by centroid gets it wrong wherever one part encloses another,
which here is most of them. This is the dataset
[ORDER-INDEPENDENT-TRANSPARENCY.md](ORDER-INDEPENDENT-TRANSPARENCY.md) should be
judged against.

**7. Section planes.** Cutting a body open is how anatomy is looked at, and the
tree has no user clip planes — only the fixed-function ones enumerated in
`debug/state.py`. A core-profile clip-plane node driven through
`gl_ClipDistance`, honoured by the flat passes, is a general engine feature that
a machine-part viewer or a terrain editor wants equally.

**8. Draw-call cost with nothing to instance.** 1,258 unique meshes in a 1.7 m
volume, none repeated, few culled. The forest measures instancing and the city
measures streaming; this measures the per-draw cost of the flat passes
themselves, which is the number a developer with a detailed model hits first.

**9. A 3D Tiles bake with a full interior.** The octree baker in
`openglcontext-editor` has only ever been given datasets whose insides are empty
— a city is shells on a plane. A body is solid all the way through, so every
node of the octree has content and the SSE LOD has to choose between parts at
every depth rather than between distances.

## Phases

Red/Green throughout; the phases are ordered so each is useful alone.

- **Phase 0 — fetch and cache.** `loaders/bodyparts3d.py` on the `cc0.py` model:
  bounded download of the PART-OF zip, extraction under the per-user app-data
  directory with per-member size caps, provenance manifest carrying the
  attribution string, offline handled as an absence rather than an error. Tests
  against a small fixture archive, no network in the suite.
- **Phase 1 — the header index.** Parse the header block and the two metadata
  tables into a typed index: part id, names, bounds, volume, parent, children.
  Pure data, no GL, fully testable. Join through header file ids, and record what
  the 17 mesh ids absent from the parts list turn out to be.
- **Phase 2 — the fast OBJ path.** Numpy read in `loaders/obj.py`, held to the
  existing parser's output on the OBJ files already in the suite, then measured
  on the skin.
- **Phase 3 — the adapter.** A source frame (mm → m, Z-up → Y-up, grounded) on
  the OBJ adapter, a `ViewerScene` built from the index, and a `Library` entry so
  `oglc-view` offers the body on its shelf. Attribution displayed.
- **Phase 4 — naming, tree and picking.** Pick returns the anatomical name;
  `outline.py` shows the part-of hierarchy; selection travels both ways.
- **Phase 5 — seeing inside.** Section planes and per-part visibility, with the
  OIT path judged on skin-over-viscera.
- **Phase 6 — the measurements.** Draw-call and load-time numbers written down,
  a visual-regression case or two on a fixed part set and camera, and the 3D
  Tiles bake if the numbers say the direct path is not enough.

## Open questions

- The licence discrepancy above, for a human.
- Whether to carry the IS-A release at all, or leave it as a second catalogue
  entry once PART-OF works.
- What a part with no mesh should be in the scenegraph — an empty `Group` that
  owns its atomic children is the obvious answer, and it makes the composite
  organs selectable, which is what a browser wants.
- Whether the 52 mirrored files are geometry or references; if they are exact
  mirrors, they are a `Transform` with a negative scale and 4 MB less to read.

## Documentation

New user documentation is due with Phase 3 (`docs/` — the fetch, the cache
location, the attribution requirement, the units and the shelf entry), an
`obj.html` note on the fast path with Phase 2, and the clip-plane node documented
with Phase 5. The dataset's facts and provenance — ids, frame, header fields,
attribution string — go in `specs/` and are cited from the loader, so nobody
re-derives them from the archive.
