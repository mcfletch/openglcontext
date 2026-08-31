# Splitting the terrain documentation, and renaming `oglc-bake`

**Status: ✅ Landed 2026-08-30.**

## Why

[docs/terrain.html](../docs/terrain.html) is 52 KB and fifteen `<h2>` sections.
It is the page where anything to do with ground ended up: two unrelated
rendering paths, a streaming runtime, a fetch-policy statement, a five-step
OpenStreetMap export, the whole vegetation system, and a walking mix-in. A
reader who wants one of those reads past the other five.

The two paths in it belong to different consumers, and that is the line to cut
along.

- **Streamed 3D Tiles** is what [glisteel](../../glisteel/) drives, over a world
  baked by `oglc-bake` and authored in [glisteel-editor](../../glisteel-editor/).
- **Height field and splat** is what the
  [forest demo](../../openglcontext-forest/) runs on: a single DEM, no tiles and
  no baking. The forest demo is also where the vegetation system is exercised at
  full depth — 230k instanced trees with impostor LOD, two camera-following
  grass layers, canopy shade — well beyond the vegetation demos in `tests/`.

Neither game is discussed anywhere on the site. `glisteel` appears twice in
`docs/index.html`, as gallery captions, and once in `docs/physics.html`.

`oglc-bake` is a separate matter of the same kind. It bakes one world,
`OpenGLContext_editor.world.procedural.ProceduralWorld`, which is a racing
circuit: an oval bent out of round, a design speed, banked corners, a
start/finish gantry, signs, and forest cleared back from the carriageway. The
command's options are that world's options. The generic machinery underneath it
— `bake_world()` and the rest of `OpenGLContext_editor.bake` — is generic and
well named, and stays where it is.

## The pages

`terrain.html` keeps its name and the `id`s of every section that stays, so
`physics.html#heightfield`, `#fieldphysics`, `#controlmap`, `#onesurface` and
`#fromfunction` need no edit. An `id` that moves keeps its spelling on the page
that receives it, so only the filename half of a link changes.

| Page | Title | Carries |
|---|---|---|
| `terrain.html` | Terrain & Landscapes | An introduction that routes between the two paths; `#heightfield` and everything under it (`HeightField`, `SplatTerrain`, `#onesurface`, `#fromfunction`, `#controlmap`, `#fieldphysics`, `TerrainWalkMixin`); `#terrainprofile` |
| `tiles3d.html` | Streamed 3D Tiles | `#tiles3d`, what a tileset may reach, `#samples`, how it works, the tileset half of `#making`, refining and tuning, caves and overhangs, `oglc-terrain` |
| `osmcity.html` | A city from OpenStreetMap | `#osm-export` and its five steps, whole |
| `vegetation.html` | Vegetation | `#vegetation` entire: `#vegetationfield`, `#groundcover`, `#clearance`, `#canopyshade`, vegetation in a tile, `#footing` |
| `glisteel.html` | GLinting Steel | New |
| `glisteel-editor.html` | The GLinting Steel track editor | New |

Prose that moves is moved, not rewritten. Two places change:

- `terrain.html`'s introduction becomes a router — what the two paths are, which
  demo runs on each, where to go — and each new page gets an introduction in the
  register the other pages use.
- `#making` straddles the cut. `build_terrain_tileset`, `build_dem_tileset` and
  mounting `TilesTerrain` go to `tiles3d.html`; `TerrainProfile`,
  `terrain_height_for` and `fbm`/`ridged` are height-function authoring and stay
  on `terrain.html`, which `tiles3d.html` links to.

The forest demo is the worked example on `terrain.html` and on
`vegetation.html`; glisteel is the worked example for `tiles3d.html`,
`roads.html` and `baking.html`.

`glisteel.html` says what the game is and which engine capability each part of
it exercises: the streamed world and its per-tile colliders, the road the
circuit is swept into and how a baked centreline reaches the game, the car on
`omi_physics`, the HUD, and pictures taken again from a recorded session.
`glisteel-editor.html` covers drawing a circuit on a landscape, holding a
height, where a lap begins, water, shaping and choosing the land, what a project
is, and baking one to drive. Each game's README stays its developer reference.

Pictures come from the entries already in
[docs/images/manifest.toml](../docs/images/manifest.toml) —
`showcase/glisteel-forest-road`, `showcase/glisteel-viaduct`,
`showcase/tiles-toronto` — placed with the `figure.shot` and `.gallery-rotate`
components. `toronto-3dtiles.jpg` travels with `#osm-export`.

One picture had to be made. `glisteel-editor.html` wants the editor with a
circuit on it, and nothing showed that, so `showcase/track-editor` is a new
manifest entry: the editor run under the engine's auto-exit capture harness
over a new `glisteel-editor/samples/ashdown.glisteel`, which is also the
worked example of the project format that README documents. Two runs write the
same bytes.

`oglc-view` is not the tool for an aerial of a baked world. The shipped bake
carries its ground and its forest *beside* the tileset (`--ground field`), so
the viewer streams the road, the signs and the water and draws the landscape
they sit on nowhere; and re-baking with `--ground tiles --forest tiles` renders
but auto-frames edge-on, with `--elevation`/`--tilt` and an explicit
`--eye`/`--look-at` both leaving the world out of frame. A picture of a baked
world from above is still wanted, and needs the framing looked at first.

## The links that change

| From | Was | Becomes |
|---|---|---|
| `index.html` | `terrain.html#tiles3d`, `#vegetation` | `tiles3d.html`, `vegetation.html` |
| `documentation.html` | `terrain.html#tiles3d`, `#osm-export` | `tiles3d.html`, `osmcity.html` |
| `baking.html` | `terrain.html#vegetationfield`, `#groundcover` | `vegetation.html#…` |
| `gltf.html` | `terrain.html#footing` | `vegetation.html#footing` |
| `roads.html` | `terrain.html#canopyshade` | `vegetation.html#canopyshade` |

`documentation.html` gains an entry for each new page, which is what
`test_every_page_is_reachable_from_the_index` requires. Also updated:
`README.md`, the directory map in `CLAUDE.md`, `move/terrainwalk.py`'s
docstring, and the page tables in
[DOCUMENTATION-IMAGES.md](DOCUMENTATION-IMAGES.md).

New `tests/unit/test_documentation_links.py` holds every relative
`href="page.html#anchor"` in `docs/` to an `id` on the page it names. Nothing
checked those before, and a split is exactly the change that breaks one
silently.

## `oglc-bake` becomes `glisteel-bake`

The command moves to `glisteel-editor`, which already bakes a project from its
own menu (`glisteel_editor/app.py`, `File → Bake a world`, over the same
`bake_world`). A shell command that bakes a GLinting Steel world sits beside the
editor that authors one.

The **CLI alone** moves: `OpenGLContext_editor/bin/bake.py` becomes
`glisteel_editor/bake.py`, entry point
`glisteel-bake = "glisteel_editor.bake:main"`, options unchanged.
`ProceduralWorld`, `bake_world`, `WorldManifest` and the rest of
`OpenGLContext_editor.bake` stay: eight of that package's test files and
`glisteel_editor/project.py` build a `ProceduralWorld`, and glisteel-editor
already depends on `OpenGLContext-editor`, so the command reaches them
unchanged.

`oglc-bake` remains for one release as a notice, the way `oglc-vrml`,
`oglc-gltf` and `oglc-tiles` do. It cannot delegate — openglcontext-editor must
not depend on glisteel-editor — so it says where the command went and exits
non-zero.

Names to follow outward: `openglcontext-editor`'s `pyproject.toml` and
`README.md`; `glisteel-editor`'s `pyproject.toml`; glisteel's `pyproject.toml`
(the `bake` extra), `packaging/entry.py`, `.github/workflows/dist.yml`,
`README.md` and four modules; `docs/baking.html`, `packaging.html` and
`documentation.html`; the worked example in `packaging/multicall.py`; and
`SIBLING_COMMANDS` in `tests/unit/test_documentation_references.py`. Plans keep
their `oglc-bake` mentions, since a plan records what was decided at the time.
`openglcontext-editor/tests/test_bin_bake.py` moves with the command, and
openglcontext-editor keeps a test that the notice names its replacement.

One helper did not travel. `world_name` — a readable name for a world baked
into a directory — sat in the CLI and is used by
`tests/test_bake_manifest.py`, so it moved to
`OpenGLContext_editor.bake.manifest`, whose own docstring already said "what is
here is the name the bake reaches for".

glisteel's frozen bundle and `.deb` now pull in `glisteel-editor` to ship the
baker. It is pure Python on dependencies glisteel already has, and
glisteel-editor's `drive = ["glisteel"]` is an optional extra, so there is no
dependency cycle.

## Left for later

- `glisteel-bake mytrack.glisteel`, baking a saved project — the shell form of
  `File → Bake a world`. The move here stays faithful to what the command does.
- `loaders/tiles3d/vegetation.py` and `foliage.py` sit under the 3D Tiles loader
  while `scenegraph/vegetation/` holds the instanced fields, and the forest demo
  imports the former for a helper while streaming nothing. Documented where it
  is rather than moved.
- Pages for the forest demo, twig-bb and marble-demo.
