# Node documentation: where a node is used, and a world for each

**Status:** 📋 Planned. Nothing here is built. The tutorial paths' hand-written
`index.rst` (background text ahead of the first script) landed separately; see
[SPHINX-DOCS.md](SPHINX-DOCS.md#a-paths-introduction).

PyOpenGL's reference pages end with a *Sample code references* section: for each
entry point, the files in other projects that use it, with line numbers.
(`directdocs/references.py` scans checkouts; `generate.py` writes the section.)
This plan gives each scenegraph node the same two things, and one more:

1. a *Where this node is used* section on the node's page, linking to Python,
   VRML97, X3D XML and ClassicVRML files that instantiate it;
2. a minimal sample world for each node, in X3D XML and VRML97 syntax, with its
   render on the page;
3. a way to link from a node to files a reader cannot read as text (glTF
   binary, binary X3D).

## What there is to build on

- 351 node types in `vrml.x3d.nodes`, plus the engine's own (`OpenGLContext`,
  `X_ITE` components, `vrml.x3d.components`). `protofunctions.protoName(cls)`
  gives the node name a class answers to in a document; `components.component_of`
  gives its component and level. The VRML97 subset is the 54 nodes of ISO/IEC 14772-1.
- `tests/wrls/` holds 40 `.wrl` files; the tutorials and `bin/` hold the Python.
  Web3D's example archives (`vrml.x3d.corpus`, ConformanceNist and Vrml2Sourcebook
  by default, five more by `--fetch`) hold about 1200 scenes, each published in
  `.x3d`, `.x3dv`, `.wrl`, `.json` and `.x3db`.
- `tests/reference_images/x3d_baseline/` holds our render of every one of those
  scenes, `x3d_xite/` X_ITE's, and `oglc-x3d-regression` keeps them current.
- `tools/doc_images.py` turns an entry in `docs/images/manifest.toml` into a page
  image (producers `baseline`, `copy`, `command`, `script`), sized and
  licence-tagged. Its `baseline` producer already reads a reference image.
- `docs/api/` is written by `directdocs/dumbpydoc.py` in the PyOpenGL
  repository; `build-docs.py` passes it the projects and a few paragraphs, and
  it has no hook for a per-class section.

## 1. Where a node is used

### The index

A new module, `docbuild/nodeusage.py`, scans for node names and writes
`node-usage.json`: node name to a list of
`{kind, path, lines, url, title}`. One scanner per file kind:

| Kind | Found by | A node is |
|---|---|---|
| Python | `ast`: a call or reference whose name is a class registered under a node name (`Box(...)`, `scenegraph.Box`, `X3D.Box`); also `ast` string constants that parse as a document, for scripts that build a scene from text | a `Name`/`Attribute` resolving to the class |
| X3D XML | `xml.etree` iterparse, the element tag, with `DEF`/`USE` ignored | a start tag |
| ClassicVRML / VRML97 | the tokenizer in `vrml` (not a regex, so a node name in a comment or a string does not count) | a node-type token before `{` |
| ClassicVRML `PROTO` bodies | same, recorded against the PROTO's file | as above |

A Python reference is matched by the class the name resolves to, not by spelling,
so `Box` the node and a local variable named `Box` are told apart: the scanner
imports nothing from the file, it resolves names through the file's own
`import`/`from` lines against the registry.

The record carries the line of each use, so a link goes to `#L<n>`; X3D and VRML
files are line-oriented, so the same works for them.

### Which files

In scope, in this order of preference for what a page lists first:

1. the node's sample world (section 2);
2. tutorials (`tests/tutorials/**`), as links to the generated tutorial page
   rather than the script, since the page shows the code beside its commentary;
3. `tests/wrls/` and the other repository-owned documents;
4. `bin/` commands and the other projects' demos (forest, twig-bb, glisteel,
   marble-demo) by URL into each project's repository;
5. Web3D's example archives, linked on web3d.org (their licence permits
   linking and the archives are not redistributed here).

Each section caps at a handful of entries with a "and 14 more" line pointing at a
per-node page listing all of them, so a node like `Transform` stays readable.

### Where it shows

`directdocs` has no per-class hook, so the section is added there: an optional
`class_sections` callable on `render_projects`, `(cls) -> list[str]` of reST
paragraphs, called while a class is rendered. This is a PyOpenGL-repository
change and is its own commit there. The OpenGLContext side supplies a callable
that looks the class's node name up in `node-usage.json`. A class that is not a
node gets nothing.

A second page set, `docs/nodes/<Name>.rst`, is the node reference by *document*
name rather than Python class: component, level, fields with types and defaults
(from the registry), the sample world, and the usage list. `docs/x3d.rst`'s
component table links each node to it. The API page links to this page and back.
Generated, not in version control, like `docs/api/`.

### Linking to files a reader cannot read

- **Binary X3D (`.x3db`), Fast Infoset:** Web3D publishes every scene in all
  encodings under one stem, so the scanner indexes the `.x3d` and links the
  `.x3db` as "same scene, binary" beside it. Nothing is lost.
- **GLB and glTF with extensions:** a node is an extension or an extension
  combination, not a name in the file. The index records the glTF extension
  (`KHR_materials_clearcoat` -> `PhysicalMaterial.clearcoat`, `KHR_lights_punctual`
  -> `PointLight`/`SpotLight`/`DirectionalLight`) from `extensionsUsed` in the
  JSON chunk, a read that needs no GL. A table in the repository
  (`docbuild/gltfnodes.py`) maps each extension the loader reads to the nodes it
  produces; `tests/unit` asserts every extension `loaders/gltf` registers is
  in it.
- **A text rendering:** `vrml.x3d.files.dumps` writes any loaded document as X3D
  XML. For a binary file that matters (a sample model a tutorial loads), the
  usage entry can link to a committed `.x3d` written from it, skipped for large
  models. The extension mapping above covers the common case without it.

## 2. A sample world for each node

### Layout

`docs/samples/nodes/<Component>/<Name>.x3d` and `<Name>.wrl` where VRML97 has the
node. One small file each: the node under test, a lit ground or background that
makes it visible, one viewpoint, a `META` entry stating the field values the
sample exercises. The `.wrl` is the same scene in VRML97 syntax; nodes VRML97
lacks have no `.wrl`, and the page says X3D only.

The pair is produced from one source so they cannot differ: a Python builder
per sample constructs the scene with the node classes and
`vrml.x3d.files.dumps` emits both files (its XML encoding for `.x3d`, its
VRML97 encoding for `.wrl`). The committed
files are the output; a test re-emits and compares. Authors edit the builder,
not the files.

### Render

Each sample is drawn as a settled still (`oglc-view`, `docs/capturing.rst`) by
the path `oglc-x3d-regression` uses, into
`tests/reference_images/x3d_samples/<Component>.<Name>.png` with its JSON
sidecar (renderer, date, camera). `tools/doc_images.py` gets one manifest group
that generates an entry per sample with the `baseline` producer, so the page
image, size, JPEG quality and licence tag follow the rest of the set.
`ATTRIBUTION.md` lists nothing new: the samples are ours and BSD.

### Test

- every node in the registry that is drawable or has a visible effect has a
  sample, or an entry in `NO_SAMPLE` with the reason (a sensor with no
  geometry, a node that only exists inside another's field);
- every sample loads in a plain `Context` without a warning;
- the `.x3d` and `.wrl` parse to the same field values;
- the render equals the reference within the suite's tolerance.

### Size of the work

351 nodes. The count by component comes from the registry
(`components.component_of`), and the work divides by what a sample has to show:

- geometry, appearance, lighting and grouping nodes: a few lines and a still;
- sensors, interpolators, sound, networking, scripting and event utilities: the
  sample shows behaviour, so it is a `TimeSensor` driving an interpolator, or a
  `TouchSensor` that needs a click. Those render a chosen frame, or are
  `NO_SAMPLE` with a link to the nearest tutorial;
- volume, geospatial, NURBS, HAnim, particles, rigid body and the engine's
  components: a few samples per component family rather than one per node.

First batch: VRML97's 54, since they are in both syntaxes and every reader meets
them.

## Order of work

1. `nodeusage.py`: the scanner for the four kinds, the index, tests with fixture
   files for each kind, including a node name in a comment and a string that
   must not count.
2. `class_sections` hook in `directdocs` (PyOpenGL repository) and the section on
   `docs/api/` node pages.
3. `docs/nodes/` generator, component table links in `docs/x3d.rst`.
4. Sample builder, the VRML97 54 first, the reference renders, the manifest
   group and the page figures.
5. glTF extension table and binary-encoding siblings.
6. Remaining components in batches, each batch with its tests and renders.

## Decisions for the maintainer

- Whether the node reference (`docs/nodes/`) is a new page set, as drafted, or
  the section goes on the API pages only.
- Whether other projects' demos (forest, twig-bb, glisteel) are indexed by URL
  into their repositories, or only this repository's files.
- Whether the `NO_SAMPLE` list may include the behaviour nodes, or each needs a
  rendered frame.
