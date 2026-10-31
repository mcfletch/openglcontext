# Node documentation: where a node is used, and a world for each

**Status:** 🟡 Part 1 (the usage index and its section on the API pages) is
built; part 2 (the sample worlds) is built for the 54 nodes of VRML97, with their
renders and sources on the node pages, and open for the rest of X3D; the live view
and the glTF links are open. The tutorial
paths' hand-written `index.rst` (background text ahead of the first script) is
in [SPHINX-DOCS.md](SPHINX-DOCS.md#a-paths-introduction).

PyOpenGL's reference pages end with a *Sample code references* section: for each
entry point, the files in other projects that use it, with line numbers.
(`directdocs/references.py` scans checkouts; `generate.py` writes the section.)
This plan gives each scenegraph node's API page the same, and one more:

1. a *Where this node is used* section on the node's API page, linking to
   Python, VRML97, X3D XML and ClassicVRML files that instantiate it;
2. a small sample world for each node, in X3D XML and VRML97 syntax, shown on the
   page with its reference render, and a test that it loads and draws as the
   reference does;
3. a way to link from a node to files a reader cannot read as text (glTF
   binary).

Decided: the section goes on the API pages only (no separate node reference);
the index covers the projects in this workspace, since nothing else uses the
nodes yet; every node with behaviour (sensors, interpolators and the like) gets
a sample, every sample has a reference render, and a live X_ITE view is added only
to a sample that is interactive.

## What there is to build on

- 351 node types in `vrml.x3d.nodes`, plus the engine's own (`OpenGLContext`,
  `X_ITE` components, `vrml.x3d.components`). `protofunctions.protoName(cls)`
  gives the node name a class answers to in a document. The VRML97 subset is the
  54 nodes of ISO/IEC 14772-1.
- `tests/wrls/` holds 40 `.wrl` files; the tutorials and `bin/` hold the Python.
  Web3D's example archives (`vrml.x3d.corpus`) hold about 1200 scenes, each
  published in `.x3d`, `.x3dv`, `.wrl`, `.json` and `.x3db`.
- `docs/api/` is written by `directdocs/dumbpydoc.py` in the PyOpenGL
  repository; `build-docs.py` passes it the projects and a few paragraphs.

## 1. Where a node is used

`docbuild/nodeusage.py` scans the workspace's projects and answers, for a node
name, the files that use it. One scanner per file kind:

| Kind | Read by | A node is |
|---|---|---|
| Python | `ast` | a `Name` or `Attribute` that the file's own `import`/`from` lines bind to a name in `OpenGLContext` or `vrml`; a `*` import from those packages binds every node name the file does not define itself |
| X3D XML, ClassicVRML, VRML97, X3D JSON, binary (`.x3d`, `.x3dv`, `.wrl`, `.x3dj`, `.x3db`, gzipped) | `vrml.x3d.readers` with a `SceneBuilder` subclass that notes each `start_node` and the line the reader is on | a node the loader builds; not a `ROUTE`, an `IS`, a `DEF` name, a comment or a string |

Imports are not read from the file by running it, so a file that builds nodes
through `getattr` or from a string of VRML is not found. `Box` the node and a
local variable named `Box` are told apart because only a name bound by an engine
import counts.

Each use is recorded with its line, so a link goes to `#L<n>` on the project's
GitHub page. A file's entry lists the lines it uses the node on.

Not scanned: `tests/unit` (assertions about nodes, not examples of using them),
reference images, build output, worktrees, virtualenvs and Web3D's downloaded
archives.

An entry for a tutorial script also links the walkthrough page. Entries are
ordered tutorials, sample worlds, `tests/wrls`, the engine's commands and demos,
the other projects, then the remaining tests. A page lists at most twelve, then a
count of the rest.

The section is added to a class's page through a `class_sections` argument of
`directdocs.dumbpydoc.render_projects`: `(cls) -> list[str]`, the reST for any
block to put after the class's docstring. The callable is the OpenGLContext
side's; a class that is not a node, or has no uses, gets nothing. A class is a
node when it declares its own name as a node (it defines `PROTO`, or the name it
answers to in a document is its `__name__`).

### Linking to files a reader cannot read

- Binary X3D (`.x3db`, Fast Infoset) and X3D JSON are read by the same scanner
  and have no lines, so their entry links the file without an anchor.
- GLB and glTF: a node is an extension or a combination of extensions, not a
  name in the file. `docbuild/gltfnodes.py` maps each extension `loaders/gltf`
  reads to the nodes it produces (`KHR_materials_clearcoat` to
  `PhysicalMaterial`'s clearcoat fields, `KHR_lights_punctual` to the light
  nodes); a test asserts every registered extension is in the table. The scanner
  reads `extensionsUsed` from a file's JSON chunk, which needs no GL.
- `vrml.x3d.files.dumps` writes any loaded document as X3D XML. For a binary
  file that matters (a sample model a tutorial loads), the usage entry can link
  to a committed `.x3d` written from it.

## 2. A sample world for each node

### Layout

`docs/samples/nodes/<Name>.x3d` and `<Name>.wrl` where VRML97 has the node, with the
files they name in `docs/samples/nodes/assets`. One small file each: the node under test, a light and background that make
it visible, one viewpoint, and a `META` entry saying which fields the sample
exercises. Nodes VRML97 lacks have no `.wrl`, and the page says X3D only.

The `.x3d` is written by hand, with comments saying what it shows, and the
`.wrl` is converted from it by `python -m docbuild.nodesamples --write`
(`vrml.x3d.files.dumps`, ClassicVRML at version 2.0), so the pair cannot differ.
What a sample says about itself is `meta` in its `head`: `title`, `description`,
`sample:frames` (the frames drawn before the reference render) and
`sample:interactive`. A sample of a VRML97 node uses only VRML97 fields, so that
the conversion is complete.

### Reference render

`oglc-x3d-regression --samples` draws each sample as a settled still, by the path
the corpus run uses, and compares it with
`tests/reference_images/x3d_samples/Samples.<Node>.png` (the record beside it
holds the renderer, date and size). A sample whose point is behaviour names the
frames to draw in `sample:frames`, so the render shows the result of the circuit
and not its starting state: a TimeSensor starting at 0 with a four second cycle
is at a quarter of it after 59 frames. The page figure is that PNG, copied by the build. The samples are ours and BSD,
so `ATTRIBUTION.md` gains nothing.

### On the page

The section for a node shows its sample's source in both syntaxes beside the
reference render.

A sample that is interactive (a `TouchSensor` to click, a `PlaneSensor` to drag,
a navigation mode, a Billboard to orbit round) is also embedded as a live view.
X_ITE, the JavaScript X3D browser the regression references are drawn by (MIT,
version-pinned and digest-checked in `scripts/x3d_xite_references.py`), is added
to the built site's `_static`, and an `x3d-sample` directive writes
`<x3d-canvas src="…">` for the sample. The sample's builder marks it
`interactive`; no other sample loads X_ITE. Engine-only nodes (the
`OpenGLContext` component) have no view in another browser, so the page shows the
render and the source.

### Test

`tests/unit/test_nodesamples.py`:

- every node of VRML97 has a sample (the rest of X3D, when its samples are
  written, joins the list or is named with the reason it has none);
- every sample loads without a fault, is titled for its node and holds it;
- the `.wrl` is what the `.x3d` converts to and parses to the same world;
- each circuit does what its description says: a TimeSensor is run to the moment
  of the reference render, a pointing sensor is pressed and dragged, an
  environmental sensor is told the viewer is in its box, and the routed field is
  read.

The render comparison is `oglc-x3d-regression --samples`, which exits 1 where a
render differs from its baseline.

The circuits caught one fault in the samples while they were written: an
OrientationInterpolator with keys a whole turn apart does not turn, because the
shorter arc between a rotation and itself is nothing. The samples use a key for
each quarter turn.

### Size of the work

351 nodes, divided by component through `components.component_of`. First batch:
VRML97's 54, since they are in both syntaxes and every reader meets them. Then
the X3D components in turn, with a few samples per family where the family
shares one scene (NURBS, volume, geospatial, HAnim, particles, rigid body, the
engine's components).

## Order of work

1. [x] `nodeusage.py`: the three scanners, the index, tests with fixture files
   for each kind, including a node name in a comment and a string that must not
   count.
2. [x] `class_sections` in `directdocs` (PyOpenGL repository) and the section on
   node classes' API pages.
3. [x] Samples for the 54 nodes of VRML97, the load and circuit tests and the
   reference renders.
4. [x] The sample on the node's page: the reference render and the source in both
   syntaxes, a *Sample world* block ahead of *Where this node is used*. The renders
   are copied from the baselines to `docs/images/samples` by the build, so the page
   needs no manifest group; `tools/doc_images.py` is for the curated gallery.
5. [ ] The `x3d-sample` directive and X_ITE in the built site, for the
   interactive samples.
6. [ ] The glTF extension table.
7. [ ] Remaining components in batches, each with its tests and renders.
