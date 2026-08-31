# Pictures in the documentation

**Status:** 🟡 Steps 1–3 landed 2026-08-30; steps 4–7 open. See
[What landed](#what-landed) at the foot of this document.

A graphics engine's documentation should show what it draws. Thirty-five pages in
`docs/` carry 52 images between them, 34 of those on two pages, and 19 pages
carry none at all:
`viewer.html`, `overlayui.html`, `physics.html`, `particles.html`,
`navigation.html`, `audio.html`, `renderpasses.html` and `flat.html` among them.
`README.md` — the page most readers see first, and the one GitHub puts in front
of anyone who lands on the repository — has no image in it either.

The renders exist. This document says which picture goes where, whether we
already have it, and what produces it. It also proposes two pieces of
machinery: a rotating gallery any page can include, and one tool that
regenerates every documentation image so the pages keep up with the renderer.

## What we have already

| Set | Count | Size | Where | Notes |
|---|---|---|---|---|
| `tests/reference_images/gltf_baseline/*.png` | 159 | 900×640 | reference-images submodule (LFS) | Our own renders of the Khronos sample roster, each with a `.json` recording source URL, framing, environment, frame count, GL renderer and date. Doc-quality as they stand. |
| `tests/reference_images/*.png` | 139 | 300×300 | reference-images submodule (LFS) | The script suite's reference frames. Too small for a page image; the *script* behind each is the asset, and re-running it at doc size is what the tool below does. |
| `docs/images/gltf/*.jpg` | 7 | 1100×680 | in tree | Curated sample models, used by `pbr.html` and `gltf.html`. |
| `docs/images/demos/*.jpg` | 11 | 1100×680 | in tree | One per feature demo in `tests/*_demo.py`. Ten are placed; `molehill_edit.jpg` is new and unplaced. |
| `docs/images/parthenon/*.jpg` | 10 | 1100×680 | in tree | The baked cameras of the Parthenon model. |
| `docs/images/extrusions/*.png` | 18 | figures | in tree | `extrusions.html` is the best-illustrated page in the set. |
| `docs/images/*.jpg,png` | 8 | mixed | in tree | Includes three nothing links to: `beautiful-game.jpg` (3839×2056), `flighthelmet.jpg` (3839×2056) and `forest-lod.png`. |
| `openglcontext-forest/shots/shot_*.png` | 6 | — | sibling repo | Produced by that repo's `tools/capture.py`. |

`docs/` is 9.7 MB, 7.1 MB of it images, none of it in LFS.

**The three unused files are the shape of the problem.** `beautiful-game.jpg`
and `flighthelmet.jpg` are 4K renders of two of the best-looking models we
support, committed to the documentation directory, and no page shows them.

## The rotating gallery

A component any page can include, showing several renders of whatever that page
is about, one at a time.

### Markup

The tool writes the block; an author writes the marker and the set name.

```html
<!-- gallery: pbr -->
<div class="gallery-rotate" data-gallery="pbr" data-interval="6000">
  <figure class="slide"><img src="images/gallery/pbr/CompareMetallic.jpg"
      width="720" height="512" alt="A row of spheres from dielectric to metal">
    <figcaption>Metalness, swept from 0 to 1.</figcaption></figure>
  <figure class="slide"><img src="images/gallery/pbr/CompareRoughness.jpg"
      width="720" height="512" loading="lazy" alt="…">
    <figcaption>…</figcaption></figure>
</div>
<!-- /gallery -->
```

The slides are written into the page rather than fetched from a JSON manifest at
run time. A page opened from disk — which is how anyone reads the docs in a
checkout — cannot `fetch()` a sibling file, so a manifest-driven gallery would be
empty for exactly the readers who have the repository.

### Behaviour

`docs/style/gallery.css` and `docs/js/gallery.js`, both new, both self-contained,
no dependency:

- With no JavaScript, the first slide shows as an ordinary `<figure>` and the
  rest are hidden by CSS. The page is never blank and never a stack of images.
- The script adds a class to the container and takes over: cross-fade between
  slides, dot indicators, previous/next controls, arrow keys when focused.
- Rotation pauses on hover and on keyboard focus, and does not run while the
  gallery is off screen (`IntersectionObserver`).
- `prefers-reduced-motion: reduce` switches auto-advance off and leaves the
  controls; nothing moves unless the reader asks it to.
- Every slide has `alt` text and a `<figcaption>`; the container is a labelled
  region so a screen reader reaches the captions in order.
- First slide eager, the rest `loading="lazy"`, `width`/`height` on every image
  so nothing reflows as they arrive.

### Weight

Gallery slides render at 720×512, JPEG quality 82 — around 70 KB each. A
six-slide gallery costs one image up front. The whole of `docs/images/` should
stay under 25 MB; at that size that is room for roughly 150 more pictures than
we have, which is more than this plan asks for.

### Sets

Defined in the manifest, so a set is a list of image ids and a page includes it
by name:

| Set | Slides | Source |
|---|---|---|
| `showcase` | 10 | The landing-page mix: a game, a world, a crowd, a shadowed scene, water, roads, a 4K model render. |
| `conformance` | 24 | Drawn from the 159 `gltf_baseline` renders — the ones that look like something rather than the ones that test a triangle. |
| `pbr` | 16 | The `Compare*` roster: `CompareMetallic`, `CompareRoughness`, `CompareClearcoat`, `CompareSheen`, `CompareTransmission`, `CompareIridescence` and the rest. Each is a sweep of one dial, which is what those pages are explaining. |
| `worlds` | 8 | Terrain, 3D Tiles, roads, water, vegetation, baking. |
| `scripts` | 12 | Demo scripts re-rendered at doc size — particles, physics, text, extrusions, shadows. |

## Where the pictures go

`Have` means the file exists at usable resolution. `Regen` means we have the
thing that draws it and need to run it at doc size. `New` means nobody has
produced this picture yet.

### The front pages

| Page | Where | Image | State |
|---|---|---|---|
| `README.md` | under the opening paragraph | One wide render, then a three-across thumbnail row for *What it does* — a rendered model, a streamed world, a crowd | Have (`beautiful-game`, `toronto-3dtiles`, `crowd_demo`) |
| `index.html` | between the `<h1>` and *Introduction* | `showcase` gallery | Have |
| `index.html` | each of the seven feature groups | one thumbnail floated beside the list | Have for Rendering, Geometry, Worlds, Interaction; **New** for Simulation, Loading content, Windowing |
| `documentation.html` | under the introduction | `conformance` gallery | Have |
| `structure.html` | the pass sequence | an SVG diagram, hand-drawn, not a render | New (optional) |

### Pages with no image today

| Page | Image | State |
|---|---|---|
| `viewer.html` | The launch menu; the model library grid; the settings screen; the controls screen. Four shots of a program that already exists, on a page selling the thing a reader will run first | **New** — `oglc-view` under the capture harness with each screen open |
| `overlayui.html` | The generated settings screen, the key-binding editor, the console, a menu | **New** — `oglc-ui-demo` |
| `physics.html` | The eight physics demos: bounce, friction, joints, gravity zones, triggers, room drop, stress, cook view | Regen — `tests/physics_*.py` at doc size |
| `particles.html` | Fire, smoke, sparks, an explosion | Regen — `tests/particles_effects.py`, `particles_simple.py` |
| `navigation.html` | The same world from each movement mode: examine, fly, walk, FPS | **New** — one capture per mode |
| `audio.html` | The spatial-audio demo, and the developer overlay's audio section | Regen (`audio_spatial`) + **New** (overlay) |
| `renderpasses.html` | One frame taken apart: background only, plus opaque, plus transparent, plus overlay | **New** — four captures of one scene with passes disabled, composed side by side |
| `flat.html` | The same scene in the core profile and the compatibility profile, side by side | **New** — `scripts/profile_sweep.py` already renders both; this composes two of its captures |
| `testing.html` | The regression report's side-by-side panel: reference, result, difference | **New** — a capture of `tests/report.html` |
| `vrml97.html` | A VRML97 world | Regen — pick a script from the suite |
| `packaging.html` | none | Deliberate: a page about `.deb` files and PyInstaller bundles has nothing to show that a picture improves |
| `environment.html`, `glslversions.html`, `eventmodel.html`, `numeric_arrays.html` | none | Deliberate: reference tables and prose about mechanisms |

### Pages with one or two images

| Page | Add | State |
|---|---|---|
| `shadows.html` | Acne and the same scene biased; PCF against PCSS at the same edge; a cascade-split view | **New** — the scenes are already built, in `tests/unit/test_shadow_bias_gl.py` and `tests/shadow_spot.py` |
| `pbr.html` | `pbr` gallery under *Most of a PBR material comes down to a colour and two dials* | Have (`Compare*`) |
| `ubershader.html` | The same gallery, one slide per section as each feature is introduced | Have |
| `water.html` | Still, flowing and choppy side by side; a shot from under the surface | **New** — `tests/water_demo.py` takes the style |
| `terrain.html` | `showcase/forest-walk` at the head, over the two-paths table | Placed |
| `tiles3d.html` | `showcase/tiles-toronto` at the head; a `worlds` gallery under *How it works* | Placed in part |
| `osmcity.html` | `toronto-3dtiles.jpg`, which travelled with the export it illustrates | Placed |
| `vegetation.html` | `showcase/forest-walk` at the head; `forest-lod.png` on the near-mesh/impostor cross-fade, where it belongs | Placed in part |
| `glisteel.html` | `showcase/glisteel-forest-road` and `showcase/glisteel-viaduct` | Placed |
| `glisteel-editor.html` | `showcase/track-editor` — the map view with a circuit on it, captured through the auto-exit harness from `glisteel-editor/samples/ashdown.glisteel` | Placed |
| `roads.html` | The four road operations — highway, causeway, viaduct, bore | **New** — from a glisteel bake |
| `characters.html` | A character sheet: every clip from four sides | **New** — `oglc-character-sheet`, a shipped command |
| `hud.html` | The reticule and meters close up; the developer overlay | **New** — `tests/hud_demo.py` framed closer |
| `text.html` | Atlas text, solid text and outline text together | Regen — `tests/solid_font.py` and friends |
| `editing.html` | The gizmo mid-drag; the plan view beside the perspective view | Have in part (`molehill_edit.jpg`, unplaced) |
| `navmesh.html` | The mesh drawn over the level; a route pulled taut through portals | Regen — `tests/navmesh_demo.py` |
| `baking.html` | The octree's tiles at three refinement levels | **New** |
| `gltf.html` | Replace the static seven-figure grid with the `conformance` gallery, keeping the grid's captions | Have |
| `instancing.html` | Already has two; add a count-and-frame-rate pair | Have |

### The games

The demos are the advertisements, so the landing page and `README.md` should
lead with them.

| Source | Image | State |
|---|---|---|
| `openglcontext-forest` | A walk through the forest | Have (`shots/shot_*.png`), better regenerated at doc size |
| `glisteel` | The car on a viaduct with the world streaming ahead | **New** — needs a baked world, which `oglc-bake` produces |
| `marble-demo` | A marble on a generated board | **New** — `marble-demo/tools/capture.py` does exactly this |
| `twig-bb` | A level, with the HUD | **New**, and see the licensing note below |

## Licensing of what is in the picture

Everything in `docs/images/` today is a render this project produced of a model
that is ours or Khronos-sample (CC-BY 4.0 or CC0, credited in `gltf.html`).
Publishing a screenshot re-publishes what is in it, so the manifest carries a
`licence` field per image and the tool refuses an entry that has none.

**twig-bb needs deciding before a screenshot of it is published.** Its content
packs are downloaded rather than shipped, and the catalogue in
`twig_bb/packs.json` is OpenArena and ioquake3 data under GPL and CC-BY-SA
terms. A screenshot of a level built from that art is a derivative of the art.
The options are a shot framed on twig-bb's own furniture — the HUD, the
BSD-licensed weapon stand-ins — or a shot with attribution and share-alike terms
recorded beside it, or no twig-bb shot. Prefer the first. The glisteel, marble
and forest demos have no such question: their assets are CC0 stand-ins generated
by committed pipelines.

## The regeneration tool

### Why one tool

Today `openglcontext/scripts/generate_doc_images.py` renders the glTF gallery,
the Parthenon cameras and one demo script. The other ten images in
`docs/images/demos/` were made by hand, one commit at a time, and nothing
records how. An image nobody can reproduce is an image that quietly stops being
what the engine draws.

### Where it lives

`tools/doc_images.py` in the workspace root. It is run from a checkout of the
root repository and may call into any sibling: `oglc-view` and the test scripts
from `openglcontext`, `oglc-forest`, `glisteel`, `oglc-marble`, `twig-bb`.
A repository that is absent, or an asset that has not been fetched, is skipped
with a message, and the committed image is left alone. Nothing this tool does
deletes an image.

`openglcontext/docs/build.sh` calls it when the workspace is present and falls
back to `scripts/generate_doc_images.py` otherwise, so a standalone clone of
OpenGLContext can still regenerate the images that need only itself.

### The manifest

Each consuming repository owns the list of its own images, so
`openglcontext/docs/images/manifest.toml` describes OpenGLContext's and the tool
reads whichever manifests it finds.

```toml
[[image]]
id      = "shadows-bias"
out     = "images/shadows/bias.jpg"
pages   = ["shadows.html#acne"]
alt     = "The same lit floor with shadow acne, and without"
caption = "Left, no depth bias: the floor shadows itself. Right, three texels of bias."
licence = "rendered by this project; BSD-3-Clause"
producer = "montage"
size     = [1100, 680]

  [[image.montage.panel]]
  producer = "script"
  module   = "shadow_spot"
  label    = "no bias"
  env      = { OPENGLCONTEXT_SHADOW_BIAS = "0" }

  [[image.montage.panel]]
  producer = "script"
  module   = "shadow_spot"
  label    = "default bias"

[[gallery]]
name   = "pbr"
images = ["pbr-metallic", "pbr-roughness", "pbr-clearcoat"]
```

### Producers

| Producer | What it runs | Present today as |
|---|---|---|
| `script` | a demo under `tests/` through the auto-exit capture harness | `_capture_script` |
| `model` | `oglc-view <model> --capture` with framing | `_spawn` |
| `baseline` | converts a `gltf_baseline/*.png` to a gallery JPEG; needs no GL | new, trivial |
| `command` | a console script from any repo, under the capture environment | new |
| `sheet` | `oglc-character-sheet` | new |
| `montage` | composes several captures into one labelled figure | new, PIL only |

### Determinism

A picture that changes every run is a picture nobody can review a change to.
Every capture pins `OPENGLCONTEXT_SEED`, `OPENGLCONTEXT_CAPTURE_FPS`,
`OPENGLCONTEXT_SHADOW_CASCADES`, `OPENGLCONTEXT_IBL`, `OPENGLCONTEXT_HIDDEN=1`
and `OPENGLCONTEXT_DISABLE_FPS_DISPLAY=1`, and `OPENGLCONTEXT_LOD=off` where
distance tessellation would otherwise vary with the framing. These are the same
switches the visual suite and the conformance captures already use.

Each image gets a sidecar `<name>.json` recording the producer and its
arguments, the git revision of the repository it came from, the GL renderer and
version, and the date — the shape `gltf_baseline/*.json` already uses.

### Interface

```bash
tools/doc_images.py                  # everything whose source is available
tools/doc_images.py --list           # what is declared, and what it needs
tools/doc_images.py --only shadows-bias pbr-metallic
tools/doc_images.py --repo openglcontext
tools/doc_images.py --check          # render nothing; report what is missing or stale
tools/doc_images.py --write-galleries    # rewrite the gallery blocks in the pages
```

`--check` needs no GL, so it belongs in CI.

## Keeping it honest

New in `openglcontext/tests/unit/test_doc_images.py`, none of it needing a GL
context:

- Every `<img src=…>` under `docs/` resolves to a file that exists. Tutorial
  regeneration lost `transforms_1`'s screenshots once and nothing noticed until
  someone opened the page.
- Every `<img>` has non-empty `alt`.
- Every manifest entry's `out` exists, and every file under `docs/images/` is
  named by a manifest entry — which would have found the three unused renders
  sitting there now.
- Every `pages` entry names a page that exists and that references the image.
- Every gallery block has at least two slides, each pointing at a file that
  exists, and every `data-gallery` name is a set the manifest declares.
- Every manifest entry carries a `licence`.
- Every producer resolves: the module is under `tests/`, the command is a
  registered console script, the baseline PNG is in the submodule.

The last one is what stops the manifest and the tree drifting apart without
anybody rendering anything.

## Order to do it in

1. **The component.** `gallery.css`, `gallery.js`, and the `pbr`, `conformance`
   and `showcase` sets built from images we already have. Nothing rendered.
2. **The tool**, covering what `generate_doc_images.py` covers today, plus the
   `baseline` producer for the gallery sets. `docs/build.sh` delegates to it.
   `test_doc_images.py` lands with it.
3. **Place what we have.** The three unused renders, `molehill_edit.jpg`, and
   the demo images onto the pages named above.
4. **Regenerate at doc size** the scripts whose only picture today is a 300×300
   reference frame: physics, particles, text, tiles, audio.
5. **Render what is missing**: the viewer and overlay-UI screens, the shadow
   comparisons, the water styles, the profile comparison, the render-pass
   breakdown, the character sheet, the navigation modes.
6. **The games**: forest, glisteel and marble, then `README.md` and
   `index.html` leading with them.
7. **twig-bb**, once the content question above is settled.

Steps 1 to 3 use images that exist and would put a picture on every page in the
set. Steps 4 onwards are where the tool earns its place, because each of them is
a render that has to be reproducible to be worth committing.

## What landed

**2026-08-30 — steps 1 to 3.** The component, the tool, and the pages a reader
meets first.

- `docs/style/gallery.css` and `docs/js/gallery.js`, as described above, with two
  additions from review: the picture is its own control, so clicking its left
  half goes back and its right half forward; and the container is capped at
  `--slide-width`, the render's own pixel width written into the page beside the
  slides, because `width: 100%` had been scaling a 1200-pixel render across a 4K
  display.
- `tools/doc_images.py` in the workspace root, with the `baseline`, `copy`,
  `command` and `script` producers, `--check`, `--galleries`, and a `crop` on an
  entry for a render that sits low in its window or carries a developer overlay.
  `docs/build.sh` calls it, and skips it in a standalone clone.
- `docs/images/manifest.toml` — 41 pictures and two galleries. The `showcase`
  set (1200&times;675) leads `index.html`; the `conformance` set
  (900&times;640, from the blessed baselines) leads `documentation.html`; the
  `features` thumbnails index the feature pages from both.
- New captures: `glisteel` twice, the forest demo, the marble demo and
  `crowd_demo`, all through the shipped programs under the capture harness.
  `--size` was added to `marble-demo/tools/capture.py` to get one at doc
  resolution.
- `README.md` leads with a render and carries a six-picture table.
- `docs/images/ATTRIBUTION.md` records the terms on everything in a picture, and
  the models deliberately kept out.
- `tests/unit/test_doc_images.py` — twelve cases, no GL: every `<img>` resolves,
  carries `alt`, and declares the size the file actually is; the manifest and the
  managed directories agree; every gallery is declared, has slides that exist,
  and shows its first one without JavaScript.

Three things found while doing it:

- **`beautiful-game.jpg` and `flighthelmet.jpg` are screen captures**, with the
  developer overlay and the viewer's reference thumbnail in them, which is why
  no page ever used them. Both are cropped to the render by the manifest. A
  clean re-render through `oglc-view --capture` would be better.
- **`DamagedHelmet`'s textures are CC-BY-NC**, which is a narrower licence than
  the pages showing it should carry. It leads `pbr.html` and appears twice in
  `gltf.html`. Named in `ATTRIBUTION.md`; the substitution is a decision to take.
- **A `glisteel` capture was not frame-for-frame reproducible**, and now is.
  `--drive-seconds` drives the car for a wall-clock interval through a physics
  step, so the same command landed near a place rather than on it — one re-run
  swapped a sunlit road for a dark canopy. Two things fixed it, and both belong
  to glisteel rather than here: a **recorded session**
  (`glisteel/sessions/doc-lap.jsonl`, 1,680 frames over 115 seconds, 62 KB)
  which `OPENGLCONTEXT_TELEMETRY_REPLAY` drives the engine's clock and the
  session's randomness from; and **`--capture-frame N`**, which captures on a
  counted frame rather than after a wall-clock delay, because under a replay
  the frame is the deterministic thing and the clock is not. Both pictures come
  from frames of that one lap — 569 and 1297 — and two runs of either write
  byte-identical PNGs. The manifest carries a `replay` key that names the
  journal; `curated` is gone.

## Open questions

- **Thumbnails on the tutorial index.** Every tutorial page already carries its
  own screenshot; `docs/tutorials/index.html` lists them as text. Adding a
  thumbnail per entry is a change to `directdocs`' `tutorialindex.kid` template
  in the `pyopengl` checkout, not to this repository.
- **Whether `docs/images/` should move to LFS.** At 7 MB it does not need to;
  at the 25 MB budget above it is worth asking, and it would make the doc images
  behave like the reference images already do.
- **Animated figures.** Several of these — the movement modes, water, particles,
  a crowd walking — are motion, and a still under-sells them. The engine records
  H.264 straight from the framebuffer (`docs/recording.html`), so a short loop is
  within reach of the same tool. Deferred: it is a second output format, a much
  larger page weight, and a decision about autoplay.
