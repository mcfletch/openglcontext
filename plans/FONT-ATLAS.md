# Font Atlas Array

Status: 📋 Planned — **awaiting review, do not implement yet.**

A pre-rendered, paged glyph store for shader-based text: a bundled sans-serif
face with Latin-1 coverage resident from the start, a `GL_TEXTURE_2D_ARRAY` whose
further layers are Unicode pages brought in on demand, and one
`(font, code-point, size)` lookup that returns where a glyph lives and how wide it
is. It replaces the ASCII-only, fixed-width atlas the shader text path ships today.

## Why

The shipped atlas is DejaVu Sans **Mono**, code points 32–126, nine sizes, one
2D texture each (`OpenGLContext/scenegraph/text/fonts/`, built by
`scripts/generate_font_atlas.py`, consumed by
`scenegraph/text/shadertext.py`). Two limits fall out of that:

- **Coverage stops at ASCII.** A `Text` node, a HUD message or a settings label
  carrying `é`, `ñ`, `°` or `—` draws `?` for every such character. VRML97 strings
  are Unicode and the UI accepts Unicode, so the renderer promises more than the
  atlas holds.
- **The layout is monospaced.** `shadertext` advances the cursor by a single
  `char_width` per glyph, so a proportional face cannot be used without changing
  the layout loop, and the only bundled face is a monospace one.

This is the engine's text stack, not a demo's, so the fix belongs here: a store
that carries the characters real content uses, admits more without shipping a
gigabyte of glyphs, and lays out a proportional face correctly.

## What a caller gets

- **A bundled sans-serif face with Latin-1 resident.** ASCII plus the Latin-1
  accented letters and common punctuation are in the texture from the first frame,
  so ordinary Western-European text draws with no page-in and no `?`.
- **On-demand Unicode pages.** Code points outside the resident set live in
  further pages the engine ships (or fetches) but does not upload until something
  asks for them. The first use of a glyph on an un-resident page triggers a
  background page-in and draws a `<?>` placeholder until the upload lands; the
  frame is never blocked on it.
- **One lookup.** `(font, code-point, size) → (layer, u0, v0, u1, v1, advance,
  bearing)`. A glyph the engine has never heard of returns the placeholder record.
- **Proportional and monospace faces both.** Per-glyph advance and bearing come
  out of the same lookup, so a proportional face lays out correctly; a monospace
  face is the case where every advance is equal.
- **A tool that builds all of it** from a named or file-defined character set, so
  adding coverage is a command, not hand-work.
- **Full Unicode from a dropped-in `.ttf`, no baking.** A font set may ship a
  TrueType source instead of pre-built pages; the runtime rasterizes each glyph the
  first time it is used, into the same page format, so a developer gets full
  coverage by supplying a font and its licence.
- **An application's own fonts, without engine edits.** A `fontDirectories` search
  path lets an app drop a font set (directory or archive) that adds a face or
  overrides `default`/`default-mono`; the bundled set sits last, so it is the
  fallback and never in the way.
- **Every installed font credited.** Each font set carries a licence notice, and
  the attribution view lists them all under a "fonts" section by default.

## Font choice

**Recommend DejaVu Sans** (proportional) as the general face and keep **DejaVu
Sans Mono** as the monospace face for the developer overlay and console, where
columns of numbers must align.

The two bundled faces are reached by the **logical names `default` and
`default-mono`**, not by their file names. Every surface that draws text asks for
`default` (or `default-mono`); what those resolve to is decided by the fonts
directories below, so an application replaces the engine's text face by supplying
its own `default`, without touching a single call site.

- **Licence is already cleared and cited.** DejaVu is a Bitstream Vera derivative;
  Bitstream Vera is public domain and the DejaVu additions are under a permissive
  licence that explicitly allows embedding, modification and redistribution. A
  pre-rendered atlas is a permitted derivative. The notice is already carried in
  `scenegraph/text/fonts/__init__.py` and `scripts/generate_font_atlas.py`; the
  same text covers DejaVu Sans. It is **not copyleft**, so it clears the
  workspace licence rule with no further analysis.
- **Coverage is broad enough for the resident ask.** DejaVu Sans carries the full
  Latin-1 Supplement and Latin Extended-A, Greek and Cyrillic — the resident
  Latin-1 plane and the first optional pages come from one face.
- **Keeping the mono face** means the current dev-overlay and console alignment
  does not regress; the `(font, …)` key already distinguishes the two.

For code points DejaVu lacks, the pageable-fallback family is **Noto Sans**. Noto
is under the SIL Open Font License; OFL's reserved-name and bundling terms bind
*font software*, and a rasterised atlas is a bitmap, not font software — but this
is the one licence question on the page that wants a human sign-off before any
Noto-derived page ships, so it is flagged here and left to Phase 4.

## Configuration — the fonts directories

**A `fontDirectories` setting is an ordered search path** an application uses to
supply its own fonts. Each entry is a **directory or a named archive** holding one
or more font sets (a face's pages, its manifest and its licence notice — see
[Storage format](#storage-format)). A logical name resolves to the first face of
that name found while walking the path from front to back.

- **The bundled default set is always the last entry.** So `default` and
  `default-mono` resolve to the engine's DejaVu faces only when nothing earlier
  claims those names — an application that puts its own `default` (or
  `default-mono`) earlier in the path **overrides** the engine face, and one that
  supplies a wholly new name adds a face without displacing anything.
- **The engine never has to be edited to change its text.** Because every surface
  asks for a logical name and the bundled set sits at the end, the override is
  pure configuration.
- **It is a setting with an environment default**, following the pattern the
  rendering features already use: `fontDirectories`, defaulting from
  `OPENGLCONTEXT_FONT_DIRECTORIES` (an `os.pathsep`-separated list), with a
  programmatic `add_font_directory(path)` for an application that assembles the
  path in code. The bundled set is appended after whatever the setting names, not
  stored in it, so no configuration can remove the fallback and leave text
  unrenderable.

A directory or archive that names a face already claimed earlier is ignored for
that name (first wins), which is what makes "last = default = overridable" hold.

## Attribution — every installed font is credited

**A font carries a licence, and the licence must be shown.** Each font set ships a
notice naming the face and its terms; the library keeps the notice of every font
it has loaded from the fonts directories, the bundled set included.

- **A default "fonts" section in the application's attribution view** lists those
  notices — one entry per installed face, with its name and licence text — so an
  application that installs a font has that font called out without writing the
  credit by hand.
- **The attribution view is structured by section**, "fonts" being one; today the
  engine has only the single-wall `dialogs.notice()`, so this plan adds an
  attribution/about panel whose sections are populated by registered providers
  (the same shape the developer overlay uses), and the font library registers the
  "fonts" provider. Other subsystems can register their own sections (models,
  audio, third-party libraries) against the same view.
- **A font set with no notice does not load.** The generator writes the notice
  beside the pages, and the loader treats its absence as a malformed set rather
  than shipping unattributed glyphs — the same discipline the generator already
  applies when it refuses to emit one font's licence over another's glyphs.

## Design

### The store

A `FontLibrary` resolves a logical name (`default`, `default-mono`, or an
application's own) against the [fonts directories](#configuration--the-fonts-directories)
to a font set, and hands out a `FontAtlasArray` for it. A `FontAtlasArray` owns
one `GL_TEXTURE_2D_ARRAY` per `(font, size)`. Each layer is one **page** — a
fixed-size image (candidate 512×512) holding a set of glyphs.

- **Layer 0 is the resident page:** ASCII + Latin-1, uploaded at `initialize()`,
  never evicted. It carries the `<?>` placeholder glyph, so the fallback is always
  drawable.
- **Further layers are optional pages,** each a Unicode block or a packed set the
  build tool emitted. They are uploaded into free layers on demand and
  LRU-evicted (layer 0 exempt) when the array is at capacity.
- **Capacity** is a fixed layer count (candidate 8) sized to cover the pages a
  session realistically touches without an eviction storm; the number is a Phase-3
  tuning decision, measured, not guessed.

### The lookup

A per-font **manifest** maps each code point to its glyph record:

```
(font, code-point, size) → GlyphRecord(page, x, y, w, h, advance, bearing_x, bearing_y)
```

The manifest is cheap metadata, loaded at start for every font; the page *images*
are not. A lookup resolves to one of four states:

1. **Resident** — the record's page is an uploaded layer; return the record with
   its live layer index.
2. **Known but not resident** — the page exists on disk/fetchable but is not
   uploaded; enqueue a background page-in and return the placeholder record for
   this frame.
3. **Rasterizable** — no page carries the code point, but the set declares a
   TrueType source (see [Dynamic rasterization](#dynamic-rasterization)); enqueue
   the glyph for on-the-fly rasterization into a dynamic page and return the
   placeholder for this frame. Once rasterized, the code point has a record and its
   next lookup is state 1.
4. **Unknown** — no page and no rasterizable source carries the code point; return
   the placeholder record.

### Page-in

Off the render thread: decode the page image (the pattern `ui.pictures.PictureCache`
already uses for the model gallery). On the render thread, at a frame boundary:
`glTexSubImage3D` into a free (or LRU-evicted) layer, then flip the page to
resident so the next frame's lookups resolve to state 1. A page-in in flight draws
the placeholder; nothing waits on the upload.

<a name="dynamic-rasterization"></a>
### Dynamic rasterization

A font set may ship a **TrueType source** rather than (or beside) pre-baked pages,
and have glyphs rendered **on the fly** into the same page format. A developer
drops a full-Unicode `.ttf` with its licence and a descriptor that says, in effect,
*if a glyph is not in a page, render it and add it* — and coverage becomes lazy
instead of a wall of pre-built pages.

The producer is the same PIL rasterizer the build tool uses, so a runtime glyph and
an offline one are byte-for-byte the same cell and metrics; only the trigger
differs. On a state-3 miss:

- **Rasterize** the glyph off the render thread with `ImageFont`/`ImageDraw` at the
  atlas's size, reading advance and bearing from the face (`font.getmetrics`,
  `getbbox`) — the same fields a baked `GlyphRecord` carries.
- **Pack** it into a **dynamic page**: a layer of the array kept as a CPU-side
  image with a running shelf/skyline allocator. The glyph is blitted into the free
  slot and that sub-rectangle is re-uploaded (`glTexSubImage3D`), so the page is
  amended in place rather than rebuilt — "add it to the image, reload the image".
- **Record** it in the in-memory manifest (`page`, rect, advance, bearing) so every
  later lookup for that code point is state 1. A glyph in use this frame is pinned;
  when a dynamic page fills, the least-recently-drawn glyphs are evicted and their
  records revert to state 3.
- **Persist, optionally.** A dynamic page and its added records can be written to
  the per-user cache directory (`userpaths.appdatadirectory()`, `0o700`, keyed by
  font + size), so a second run pages the warmed glyphs in (state 2) instead of
  re-rasterizing. The cache is a convenience, never the source of truth: a miss
  falls back to rasterizing.

A set can be **pre-rendered, dynamic, or both** — the common shape is a resident
Latin-1 page baked for determinism with a TrueType source behind it for the long
tail. Rasterization needs Pillow at runtime; a dynamic set on a build without PIL
degrades to its baked pages plus the placeholder, and says so once in the log
rather than per glyph.

### Rendering

`shadertext` changes in two places:

- **Layout** advances the cursor by each glyph's `advance` and offsets the quad by
  its bearing, rather than by a single `char_width`. Monospace falls out as the
  equal-advance case. `measure_text` sums advances instead of multiplying a count.
- **Sampling** moves to `sampler2DArray`: the text quads carry a third texcoord
  component, the layer index, so glyphs from different pages draw in one batch. A
  text-shader variant (or an added uniform/attribute on the unlit program) carries
  the layer. The overlay UI binds the same array texture the way it binds the
  single atlas today (`ShaderTextRenderer.texture`), so its batching path updates
  with `shadertext`, not separately.

### The build tool

Generalise `scripts/generate_font_atlas.py`:

```
generate_font_atlas.py --font "DejaVu Sans" --sizes 10,12,…,32 \
    --charset latin1 --page-size 512 --output-dir <fonts pkg>
```

- `--font` names the face (metrics and glyphs come from the `.ttf` via PIL, as
  today).
- `--charset` is a **named set** (`ascii`, `latin1`, `latin-ext`, `greek`,
  `cyrillic`) **or a file** listing code points and ranges, so "the characters to
  include" is data a caller edits, not code.
- The tool packs each set's glyphs into one or more pages, emits the page images
  and the manifest, and writes the provenance/licence notice beside them. The
  notice is required output, not optional: a set without one does not load.
- `--name` records the logical name the set answers to (`default`,
  `default-mono`, or an application's choice), so an application builds an
  overriding set with the same tool.

<a name="storage-format"></a>
### Storage format — a font set

A **font set** is a directory or a named archive (`.zip`) an application drops on
the fonts directories. It holds:

- **a descriptor** — the logical name, the sizes, and the source: **pre-rendered
  pages**, a **TrueType source** for [dynamic rasterization](#dynamic-rasterization),
  or both;
- **the page images**, when pre-rendered — `.png`, decoded lazily on page-in;
- **the TrueType file**, when dynamic — the `.ttf`/`.otf` the runtime rasterizes
  from, plus the charset (a named set, a file, or "everything the face carries")
  that says what it is allowed to render;
- **the manifest** — one compact table (JSON or `.npy`) per size, carrying the
  per-glyph records (page, rect, advance, bearing) and the page index for whatever
  is pre-baked; a purely dynamic set starts with only its resident page and grows
  the manifest in memory;
- **the licence notice** — a text file naming the face and its terms, surfaced in
  the attribution view and required for the set to load, pre-rendered or not.

So a developer wanting full Unicode drops a directory with a full-coverage `.ttf`,
its licence, and a descriptor naming it dynamic — no page baking, glyphs appear as
they are first used. The bundled `default`/`default-mono` sets ship pre-rendered
for their resident Latin-1 page and may carry their DejaVu `.ttf` as the dynamic
source for the rest. This departs from today's
base64-PNG-in-`.py` modules on purpose: embedding every Unicode page as base64 in
an imported module would load megabytes at import for glyphs a session never
touches, and a `.py` module is not something an application can drop onto a search
path. The resident Latin-1 page is small enough to keep whichever way Phase 2
settles; the optional pages must be file-loaded.

## Deliverables

- **Coverage of the resident plane (called out separately):** the shipped,
  always-resident page covers Latin-1 — the accented letters and common
  punctuation — not merely ASCII 32–126. This is the concrete "reasonable Latin-1
  coverage" bar and it is verified by a test that renders a Latin-1 sample and
  finds no placeholder glyphs.

## Phases

- **Phase 0 — Decide.** Confirm the faces (`default` = DejaVu Sans,
  `default-mono` = DejaVu Sans Mono), the resident coverage (Latin-1), the page
  size, the initial optional pages, and the font-set layout (directory/archive +
  manifest + notice). This is the `m4` "decide on the bundled font" gate; the rest
  follows the decision.
- **Phase 1 — Build tool + font-set format.** `--font`/`--name`/`--charset`/
  `--page-size`, page packing, manifest + metrics with per-glyph advance/bearing,
  the required licence notice. Emits a font set an application can also produce for
  its own faces. Red/Green against a tiny synthetic face so the test needs no
  system font.
- **Phase 2 — Library, store, layout, attribution.** `FontLibrary` resolving
  logical names against the `fontDirectories` search path (bundled set appended
  last, first-wins, `add_font_directory`); `FontAtlasArray` with a resident
  layer-0 and manifest lookup; migrate `shadertext` and the overlay UI to the
  array texture and to advance/bearing layout; `sampler2DArray` text shader;
  placeholder record for unknown glyphs. The **attribution panel** with
  section-providers lands here, with the font library registering the "fonts"
  section. Coverage deliverable met here.
- **Phase 3 — Page-in + eviction.** Background decode, frame-boundary
  `glTexSubImage3D`, LRU with layer-0 pinned, `<?>` while in flight. Capacity and
  page-size tuned against measurement.
- **Phase 4 — Dynamic rasterization.** TrueType-source font sets: off-thread PIL
  rasterization sharing the build tool's producer, the dynamic page + shelf
  allocator, in-memory manifest growth, glyph-level LRU, and the optional per-user
  page cache. `<?>` until a glyph is rendered. Turns a dropped-in `.ttf` into full
  coverage.
- **Phase 5 — Extend bundled coverage.** Latin-Extended / Greek / Cyrillic pages;
  wire the VRML97 `Text` node's Unicode path to the store. Any Noto-derived page
  waits on the OFL human sign-off noted above.

## Compatibility and risk

- **Consumers of the current API.** `fonts.get_closest_atlas(size)`,
  `ShaderTextRenderer.glyph_uv`, `.char_width`/`.char_height` and the UI's reuse of
  `.texture` are the seams. The 2D→2D-array move and fixed→proportional metrics
  change all of them; every consumer migrates in Phase 2, in one piece, so no
  caller straddles two atlas shapes.
- **`GL_TEXTURE_2D_ARRAY` floor.** Array textures are GL 3.0 core, below the 3.3
  floor, so no new capability requirement. Immutable storage (`glTexStorage3D`) is
  used where the advanced paths already require it; the base text path can use
  `glTexImage3D` to stay at the 3.3 floor. Settle in Phase 2.
- **Monospace regression.** The developer overlay and console read as aligned
  columns; keeping DejaVu Sans Mono as a distinct face and defaulting those
  surfaces to it preserves that. Proportional is opt-in per surface, not a global
  default flip.
- **Pillow at runtime for dynamic sets.** PIL already decodes the atlas PNGs, so it
  is a present dependency; dynamic rasterization makes it load-bearing for a
  TrueType set specifically. A build without PIL keeps pre-rendered sets working and
  degrades a dynamic set to its baked pages plus placeholder.
- **Determinism of dynamic glyphs.** Runtime rasterization is reproducible for a
  given font and PIL version but can differ across PIL versions, so reference-image
  tests stay on **pre-rendered** sets; dynamic rasterization is for coverage and
  development convenience, not for the byte-stable regression baselines.

## Documentation

Ships with the change, per the workspace rule:

- `docs/text.html` — the atlas-array model, the resident/paged distinction, the
  `fontDirectories` search path and how an application supplies or overrides a
  font set (including the `default`/`default-mono` names), the required licence
  notice and the "fonts" attribution section, how to add coverage with the build
  tool, and the `(font, code-point, size)` lookup.
- `scenegraph/text/fonts/` provenance/licence notice regenerated for the shipped
  faces and pages.
- `README.md` font notes updated to name the bundled faces and their coverage.
- `docs/overlayui.html` — the attribution panel and its section providers, since
  it joins settings, key bindings and the console on the shared `ui` library.

## Provenance

The bundled faces' licences are recorded in the fonts package and cited from the
build tool and the runtime store. DejaVu's permissive terms cover the shipped
pages; a Noto-derived page (Phase 4) requires the OFL sign-off before it ships.
