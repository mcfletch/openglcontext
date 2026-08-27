# Core profile by default

**Status:** ✅ Landed. `_get_default_profile()` returns `core`; the four engine
defects are fixed; every script that needs the fixed-function pipeline declares
so; the sweep reports no script that draws under one profile and not the other.
The shader tutorials are core GLSL as well --
[SHADER-TUTORIALS-CORE.md](SHADER-TUTORIALS-CORE.md).
**Related:** [CODEBASE-CONSOLIDATION.md](CODEBASE-CONSOLIDATION.md), whose Tier A
names "flipping the default profile to core" as remaining work. This document is
that item, scoped, with the reason it is now urgent rather than tidy.

## What is true today

`contextdefinition._get_default_profile()` returns `compatibility` unless
`OPENGLCONTEXT_PROFILE` says otherwise. So the profile a program gets when it
asks for nothing is the one built around a pipeline that has been deprecated
since OpenGL 3.0 and is absent from core contexts, from macOS 3.2+, from GLES,
and from every driver that offers only core.

Meanwhile the geometry path everything new is built on does not draw there at
all. `PBRMesh.render` opens with:

```python
if not getattr(mode, 'shader_mode', False):
    return 1  # PBR meshes are shader-only
```

That is correct and should stay: `PBRMesh` is a shader-era node and giving it a
fixed-function arm would put weight on a line we keep only for old-path demos.
The problem is what it means for the *default*: everything built on `PBRMesh` --
the glTF loader, `scenegraph/frommesh.py`, and any generated geometry -- draws
**nothing** under the profile a caller gets by default, returns success, and logs
no complaint.

`scenegraph/extrusions.py` works around it privately: `SweptGeometry.render`
falls back to its own `_render_legacy` when `shader_mode` is off, which is why
`Lathe` and `Screw` draw when a bare `PBRMesh` beside them does not.

### How this was found

Regenerating the `opengl_extrusions` documentation figures. Fifteen of the
eighteen came back correct; three came back **pure black**, and the split was
exactly whether the scene used the scenegraph nodes or built a `PBRMesh`
directly through `frommesh.mesh_from_primitive`:

| Figure | Built with | Result under the default profile |
|---|---|---|
| `fig_lathe`, `fig_spiral`, `fig_screw`, … | `Lathe`/`Spiral`/`Screw` nodes | drawn |
| `fig_contours` | `mesh_from_primitive` only | black |
| `fig_scale_twist` | `mesh_from_primitive` (8 panels) | black |
| `fig_texture_caps` | mixed | only the node panel drawn |

The geometry was correct in every case -- checked directly, right triangle
counts and surface areas. Instrumenting `PBRMesh.render` showed six calls for
`fig_contours`, every one with `shader_mode=False`, each returning without
drawing.

### Every application here already opts out of the default

Nine start-up lines across seven repositories set `OPENGLCONTEXT_PROFILE=core`
before anything else runs, because the default cannot draw what they draw:

| Repository | File |
|---|---|
| twig-bb | `twig_bb/viewer.py`, `twig_bb/hudsample.py`, `twig_bb/botreview.py` |
| glisteel | `glisteel/game.py` |
| glisteel-editor | `glisteel_editor/app.py` |
| openglcontext-forest | `src/openglcontext_forest_demo/run.py` |
| marble-demo | `src/openglcontext_marble_demo/run.py`, `tools/capture.py` |
| opengl_extrusions | `tools/capture_figures.py` |
| openglcontext | `scripts/generate_doc_images.py` |

Each is a workaround at the caller for a default that cannot draw the engine's
own primary geometry node, and each is deleted by this change. That is the
measure of the problem: the default is the profile *nothing* chooses.

## The evidence

Everything in this section was measured in the dev container against an NVIDIA
RTX 3060 Ti (driver 580.173.02) and, for the wx runs, Mesa 25.2.8 llvmpipe under
Xvfb. The probe scene draws a VRML97 `Shape`/`Box` on the left of the frame and a
bare `PBRMesh` on the right, so a capture says which of the two families drew.

### Q1: can every backend give us a core profile? Yes — all five

| Backend | Core context | Renders under core | Note |
|---|---|---|---|
| glfw | GL 3.3, `GL_CONTEXT_PROFILE_MASK` = 1 | yes | |
| pygame (SDL2) | GL 3.3, mask 1 | yes, byte-identical to glfw | |
| glut (freeglut) | GL 3.3, mask 1 | yes, byte-identical to glfw | needed **P1** below |
| wx (wxGTK3) | GL 3.3, mask 1 | yes, identical drawn fractions | needs `PYOPENGL_PLATFORM=egl` (already documented) |
| qt (PySide6) | GL 3.3, mask 1 | yes | separate `openglcontext-qt` distribution |

The same scene under `compatibility` draws the `Box` and **nothing** on the
`PBRMesh` side, on every one of the five. So the profile question is settled:
core is not a glfw-only capability, and the flip does not need the default
backend to change.

Two caveats found on the way, neither of them about the profile:

- **wx renders nothing in this container under Wayland/EGL** — under either
  profile, so it is the container's `libEGL … failed to create dri2 screen`, not
  core. Under Xvfb with the Mesa software rasteriser wx renders correctly in
  both profiles. A wx CI job therefore needs a virtual X server, not a
  compositor.
- **openglcontext-qt is not in the workspace harness** (`pyproject.toml`), so
  nothing here exercises the Qt backend. It was tested for this document by
  putting the checkout on `PYTHONPATH`. Adding it to the harness is small and
  should happen with this work.

### Q2: does the "I really do need compatibility" declaration work? It didn't

Twenty-four classes in `tests/` already declare
`contextDefinition = ContextDefinition(profile='compatibility')`. Measured with
`OPENGLCONTEXT_PROFILE=core` in the environment and that declaration on the
class, **three of the five backends ignored it**:

| Backend | Before | After P2 |
|---|---|---|
| glfw | **core** — declaration ignored | compatibility |
| glut | **core** — declaration ignored | compatibility |
| wx | **core** — declaration ignored | compatibility |
| pygame | compatibility | compatibility |
| qt | compatibility | compatibility |

Each backend built its own `ContextDefinition` in `__init__` and only pygame
looked at the class attribute; `Context.setDefinition` did consult it, but runs
*after* the window already exists, so by then there is nothing left to
configure. It works today only because the default is compatibility and ignoring
the declaration reaches the right answer by accident. **Flipping the default
without fixing this breaks all twenty-four, on the backend we recommend.**

### Q3: what actually breaks? The sweep

This is what the sweep found *before* any of the fixes below; it is the survey
the rest of the plan was written from. What it reports now is under
[Acceptance](#acceptance).

Every runnable script in `tests/` (150 of them) was run twice — once under
`compatibility`, once under `core` — through the auto-exit capture path, and
judged on **both** its exit code and whether its capture drew anything.

| Outcome | Count |
|---|---|
| Draws in both profiles | 81 |
| **Fixed by core** — fails today, works under core | 8 |
| **Silently blank under core** — exit 0, black frame | 45 |
| Crashes under core | 2 |
| Blank in both (non-visual, or nothing to draw) | 15 |
| Broken in both — nothing to do with the profile | 9 |

**The failures are not loud.** The plan previously assumed a fixed-function call
in a core context "raises rather than failing quietly, which is what makes this
tractable". It does raise — `GLError(1282, 'invalid operation')` — but
`_flat.py:696` catches it per node, logs it and carries on, so the process exits
0 with a black frame. Forty-five scripts fail exactly that way. Any acceptance
criterion phrased as "the suite is green" would pass over all of them, and this
is the same failure mode that produced the black figures above. **The sweep has
to judge the capture, not the exit code**, which is what
`scripts/profile_sweep.py` (P5) is for.

#### Fixed by core

`bake_demo.py`, `crowd_demo.py`, `roads_demo.py`, `tiles_landscape.py`,
`tiles_terrain.py`, `tiles_vegetation.py`, `tiles_walk.py`, `water_demo.py` —
the modern demos, which fail outright under the default profile today.

#### Blank under core: 41 scripts that need `profile = 'compatibility'`

These draw with the fixed-function pipeline in their own `Render`. They are
demonstrations *of* that pipeline (PyOpenGL entry-point demos, RedBook
translations, bitmap fonts) or tutorials that teach shaders through it, so the
fix is to declare what they need, not to rewrite them:

| Group | Scripts | Failing call |
|---|---|---|
| Vertex-array entry points | `gldrawarrays`, `gldrawarrays_string`, `gldrawelements`, `gldrawelements_list`, `gldrawelements_string`, `glarrayelement`, `glinterleavedarrays`, `glvertex` | `glVertexPointer`, `glColor3d`, `glEnd`, `glTranslatef` |
| Pixel/imaging entry points | `gldrawpixels`, `gldrawpixelssynth`, `glhistogram`, `getteximage`, `readpixelsleak`, `arbwindowpos` | `glEnable`, `glMatrixMode`, `glHistogram`, `glTranslated` |
| Bitmap text | `glut_bitmap_font`, `glutbitmapcharacter`, `pygame_font` | `glTranslated` |
| RedBook / GLU | `redbook_alpha`, `redbook_surface`, `redbook_surface_cb`, `redbook_trim`, `glu_tess2` | `glMaterialfv`, `glDisable`, `glEnable` |
| Other | `glut_fullscreen`, `ilsstrategies`, `heightmap` | `glDisable`, `glDisableClientState` |
| Shader tutorials | `shader_1` … `shader_10`, `shader_2_c_void_p`, `shader_4_subset`, `shader_ng`, `shader_spike`, `shader_instanced_mapped` | see Q4 |

`heightmap.py` is the odd one: it raises nothing and instead logs
`IndexedPolygons: only triangles render under core profile (polygonSides=8)`
eight times a frame. That is an **engine gap**, not a script problem — see E3.

#### Blank under core: 4 scripts blocked by engine defects

| Script | Where it fails | Defect |
|---|---|---|
| `shader_11`, `shader_12`, `shader_instanced_modern` | `OpenGLContext/texture.py:138` | **E1** |
| `shadergeometry`, `transforms_1` | `OpenGLContext/scenegraph/shaders.py:109` | **E2** |

#### Crashes under core

`pygame_textureatlas.py` and `shaders.py` — both GLSL: `texture()` used in a
shader declared `#version 120`, which core rejects.

#### Broken in both, unrelated to the profile

Six of the nine are the sweep measuring the wrong thing: `glut_font`,
`redbook_alpha3D` and `glutmousewheel` need GLUT, and `wx_font`,
`wx_multiple_contexts` and `wx_with_controls` need wx, and all six were being run
under glfw. The four that name their backend in their file name are skipped now;
the other two want running under `--backend glut`.

The remaining three are real, pre-existing breakage that has nothing to do with
the profile:

| Script | Failure |
|---|---|
| `shadow_1`, `shadow_2` | `AttributeError: 'FlatPass' object has no attribute 'renderGeometry'` |
| `savepostscript` | imports `OpenGLContext.passes.gl2psrenderpass`, which no longer exists |

`shadow_1` and `shadow_2` are **published tutorials** — *Depth-map Shadows*, both
pages of it — calling a render-pass method that was removed. This plan should
not close while they are red.

### Q4: the shader tutorials are a compatibility-profile series

The tutorial index at `docs/tutorials/index.html` is already ordered
shader-first — *Introduction to Shaders*, then *Transformations*, then
*Scenegraph Nodes*, then *Shadows*, with the NeHe translations last. The
ordering is not the problem. The content is: **every one of `shader_1` through
`shader_12`, plus `shader_instanced`, depends on GLSL built-ins that a core
context does not have.**

| Tutorial | `#version` | Built-ins used | Fixed-function API |
|---|---|---|---|
| `shader_1` | 120 | `gl_Vertex`, `gl_ModelViewProjectionMatrix` | `glEnableClientState`, `glVertexPointer` |
| `shader_2`, `shader_2_c_void_p` | — | `gl_Vertex`, `gl_Color`, `gl_ModelViewProjectionMatrix` | + `glColorPointer` |
| `shader_3` | — | as above | + `glRotate` |
| `shader_4`, `shader_4_subset` | — | as above | `glVertexPointer`, `glColorPointer` |
| `shader_5` … `shader_12` | — | `gl_ModelViewProjectionMatrix`, `gl_NormalMatrix` | `glMaterial` (7 only) |
| `shader_instanced` | — | `gl_ModelViewProjectionMatrix`, `gl_NormalMatrix` | — |
| `transforms_1` | 120 | — | — |

`gl_ModelViewProjectionMatrix` and `gl_NormalMatrix` are the *fixed-function
matrix stack seen from GLSL*. They were removed in GLSL 1.40. So the series that
teaches modern OpenGL is, from tutorial 1 to tutorial 12, borrowing the
pipeline it is teaching a reader to leave — which is exactly the inversion this
plan has to correct.

## What to change

### Prerequisites — landed

- **P1. GLUT asks for no accumulation buffer unless one is requested.**
  `ContextDefinition.accumulationBuffer` defaults to -1, "choose the default",
  and GLFW, pygame and wx all read `> -1` before requesting one. GLUT's flag
  table mapped -1 to *request GLUT_ACCUM*, and a driver publishing no
  accumulation-buffer framebuffer config gives freeglut nothing to match, so it
  aborts the process before any window exists — under **either** profile. The
  whole GLUT backend was unusable on this driver. `OpenGLContext/glutcontext.py`;
  `tests/unit/test_glut_display_mode.py`.

- **P2. `Context.resolveDefinition`.** One place resolves what definition a
  context is built from — passed argument, then the class's declared
  `contextDefinition`, then a fresh one — and every backend calls it at the top
  of `__init__`, before the window exists. A declared definition is copied per
  context, since a context writes its own size back to its definition. The copy
  carries only the fields the declaration set, so every other field still
  resolves its default when read. `OpenGLContext/context.py`,
  `glfwcontext.py`, `glutcontext.py`, `pygamecontext.py`, `wxcontext.py`;
  `tests/unit/test_context_definition_resolution.py`.

- **P3. `version` follows the profile it was asked for.** A field default cannot
  see the node it belongs to, so `version` left unset read the profile the
  *environment* named. A definition asking for `compatibility` while
  `OPENGLCONTEXT_PROFILE=core` therefore carried version (3,3), and GLUT turned
  that into a 3.2+ context hint and opened a core window for it. A definition
  that states its profile now settles its version from that one.
  `contextdefinition.version_for_profile`.

- **P4. GLUT names the profile either way.** A version hint of 3.2 or above with
  no profile hint leaves the choice to the driver. GLFW already set
  `OPENGL_COMPAT_PROFILE` explicitly; GLUT now sets
  `GLUT_COMPATIBILITY_PROFILE` to match.

- **The compatibility shorthand.** Twenty-three of the twenty-four existing
  declarations set nothing but the profile, and spend an import and a whole
  `ContextDefinition` to do it — which also *discards* any definition a base
  class declared. `Context.profile` says the one thing:

  ```python
  class TestContext(BaseContext):
      profile = 'compatibility'   # this tutorial draws with the fixed-function pipeline
  ```

  It is applied over `contextDefinition` rather than replacing it, an explicit
  `profile` field on a definition still wins, and a passed definition is never
  overridden. Verified reaching the window on all five backends.

### Engine defects — fixed

- **E1. The fixed-function texture unit.** `Texture.__call__` bound a texture
  *and* called `glEnable(GL_TEXTURE_2D)`, which switches on a fixed-function
  texture unit a core profile does not have. `Texture.bind()` is now the binding
  on its own, `__call__` is the compatibility-profile entry point that also
  enables, and the callers that sample through a shader — `ImageTexture`, the
  atlas's own sub-image uploads — bind. `ImageTexture.renderPost` no longer
  resets the texture matrix stack under a shader, and clamped wrapping asks for
  `GL_CLAMP_TO_EDGE` rather than `GL_CLAMP`.

  Two things came out of it. An **atlas page is a sub-rectangle**, so sampling
  one needs the texture-coordinate transform that places it — which the fixed
  function pipeline carried on its texture matrix stack and a shader has no
  equivalent for. `TextureCache.getTexture` takes `atlasable`, and the shader
  path asks for a texture of its own. Teaching the shader path to apply a page's
  UV transform, and so recover the atlas's batching, is worth doing and is not
  done here. And **`shader_mode` was settled halfway through the frame**, after
  the scene had been walked — so a texture compiled during sorting was compiled
  for the wrong pipeline. It is settled before the walk now.
  `OpenGLContext/texture.py`, `atlas.py`, `texturecache.py`,
  `scenegraph/imagetexture.py`, `passes/_flat.py`;
  `tests/unit/test_texture_core_profile.py`.

- **E2. The declarative shader nodes bind a vertex array object.**
  `ShaderGeometry.Render` set its attribute pointers with no VAO bound, and core
  has no default object 0 to record them into, so every
  `glVertexAttribPointer` was `GLError(1282)` and the shape drew nothing. The
  attribute setup is now recorded into a VAO through
  `shadergeometry.get_or_build_vao` — the same helper `IndexedPolygons` and
  `nurbs` already use — which also stops the pointers being re-specified every
  frame. `OpenGLContext/scenegraph/shaders.py`;
  `tests/unit/test_shader_nodes_core.py`.

- **E3. Quads and quad strips are triangulated, not refused.**
  `IndexedPolygons` with `polygonSides` of 4 or `GL_QUAD_STRIP` logged a warning
  per node per frame and drew nothing. `triangulate_index` rewrites the index
  once, cached against `index` and `polygonSides`; a two-dimensional index is one
  primitive per row, which is what the shape of such an array says and what keeps
  two strips from being joined by a sliver spanning the gap.
  `OpenGLContext/scenegraph/indexedpolygons.py`;
  `tests/unit/test_indexedpolygons_triangulation.py`.

- **E4. A swallowed render failure is counted and reported.**
  `RenderFailureLog` holds what failed to draw for the life of a pass, keyed by
  the pass it happened in, the kind of node and the exception. The traceback goes
  out once per cause rather than once per frame, and `Context.OnQuit` reports the
  whole set — so a black window now ends with a line naming the nodes behind it.
  It holds no GL, so what counts as "the same failure" is tested directly. The
  legacy opaque path's `os._exit(1)` on a render exception went with it.
  `OpenGLContext/passes/renderfailures.py`, `_flat.py`, `renderpass.py`,
  `context.py`; `tests/unit/test_render_failures.py`,
  `test_render_failures_reported.py`.

- **`FlatPass.renderGeometry` is back.** Removed as dead code, and called by
  *Depth-map Shadows* — both pages of it — to draw the scene from a light's point
  of view. `shadow_1` and `shadow_2` render again.
  `tests/unit/test_render_geometry_pass.py`.

### The flip — landed

1. **`_get_default_profile()` returns `core`.** `OPENGLCONTEXT_PROFILE` keeps
   working and `compatibility` stays fully supported; what changed is which one a
   caller gets for free. `tests/unit/test_default_profile.py` holds it, and
   states the original failure as a test: a mesh built through `frommesh` draws
   with no environment variable set.
2. **Forty-eight scripts gained `profile = 'compatibility'`** — the
   vertex-array and pixel entry-point demos, the RedBook translations, the
   bitmap fonts, the backend-specific font and window demos, and the shader
   tutorials until they are rewritten. With the twenty-three that already
   declared it in longhand, seventy-one scripts now say what they need.
3. **The twenty-three `contextDefinition = ContextDefinition(profile=…)`
   declarations collapsed to the shorthand**, and the `contextdefinition` import
   went with them.
4. **The redundant `OPENGLCONTEXT_PROFILE=core` start-up lines are gone** from
   the twenty-one demos under `tests/`, from `bin/terrain_view.py`, from
   `viewer/environment.py`'s `VIEWER_DEFAULTS` and from
   `scripts/generate_doc_images.py`. The harnesses under `tests/helpers/` keep
   theirs: they pin a whole rendering environment for a reproducible measurement,
   which is a different thing from working around a default.

   **The downstream lines stay for now.** `twig-bb`, `glisteel`,
   `glisteel-editor`, `openglcontext-forest`, `marble-demo` and
   `opengl_extrusions` each install OpenGLContext as a dependency and none of
   them names a version floor, so an application whose `setdefault` had gone
   would draw nothing against any OpenGLContext where compatibility is still the
   default. `os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')` asks for
   what it now gets anyway, so it costs nothing to keep. Removing them belongs
   with an OpenGLContext release and a `openglcontext >= <that version>` floor in
   each dependant's `pyproject.toml`, one repository at a time.
5. **`SweptGeometry._render_legacy` stays.** The plan called for removing it, on
   the grounds that its only purpose was drawing when `shader_mode` is off. That
   is still its purpose, and after the flip it is what a caller who declared
   `profile = 'compatibility'` gets: deleting it would stop `Extrusion`, `Lathe`
   and `Screw` drawing in a profile the engine otherwise supports in full. Sixty
   lines that work is not a cost worth a capability.
6. **`savepostscript.py` is removed.** It drove
   `OpenGLContext.passes.gl2psrenderpass` and `OpenGL.gl2ps`, neither of which
   exists. `OBSOLETE_SCRIPTS` in `tests/test_all_scripts.py` is now empty.

### The documentation — landed

- **`docs/tutorials/index.html`** names the profile each path uses, under the
  path's own introduction; the duplicated *Transformations in OpenGL* section at
  the foot of the page is gone.
- **The default is reversed** in `docs/environment.html`,
  `docs/renderpasses.html`, `docs/structure.html`, `docs/pbr.html`,
  `docs/shadows.html`, `docs/overlayui.html`, `docs/terrain.html` and CLAUDE.md.
  The note that core "should typically" use the glfw backend is gone: all five
  backends give one.
- **The twenty-two tutorial pages** whose sources gained the declaration show it
  in their listings.
- **The shader tutorials themselves** are
  [SHADER-TUTORIALS-CORE.md](SHADER-TUTORIALS-CORE.md), proposed and awaiting
  review. Nothing in it is applied.

### Tooling

- **P5. `scripts/profile_sweep.py`** — landed. Runs every script under both
  profiles through the auto-exit capture path and reports, per script, exit code
  *and* drawn fraction, so a black frame is a failure rather than a pass. The
  acceptance criterion below is a run of it.

  ```bash
  scripts/profile_sweep.py --out /tmp/sweep            # both profiles, every script
  scripts/profile_sweep.py --out /tmp/sweep shader_1.py molehill.py
  scripts/profile_sweep.py --report /tmp/sweep/results.json
  ```

  Its core arm sets no variable at all, since core is what a context asks for by
  default and a script declaring `profile = 'compatibility'` outranks the
  variable: setting it would measure something nobody will ever run.

## Risks

- **Reference images.** 26 of 136 comparable captures are pixel-identical
  between the profiles; the rest differ, and each difference has to be judged
  rather than accepted in bulk. Judging the eight largest: **core is the
  correct render in every one.** `shadow_spot` and `shadow_demo` draw no shadow
  at all under compatibility and correct shadows under core;
  `teapot_nurbs` loses its sky background and its lighting under compatibility;
  `extrusions_preprocessing` draws bare wireframe outlines under compatibility
  and the filled polygons under core — the original symptom, in a demo. So the
  re-capture is not a tolerance exercise: the compatibility baselines are
  recording a degraded renderer, and replacing them is the point.
- **Animation, not profile.** Some of the diff is timing: `nehe6` and `nehe7`
  declare compatibility, get it, and still differ by ~13% because they animate
  and the capture lands on a different frame. Anything animated needs a pinned
  `anim_time` before its diff means anything.
- **Downstream.** `twig-bb`, `glisteel`, `glisteel-editor`, `marble-demo` and
  the forest demo all pin core already, so the flip changes nothing for them
  until their pin is removed; each needs a run when it is.
- **wx on Wayland.** wxPython is not installed in the dev container and does not
  render here under a Wayland/EGL surface in either profile. A wx job needs
  Xvfb.

## Acceptance

| Criterion | Where it stands |
|---|---|
| `scripts/profile_sweep.py` reports no script that draws under one profile and nothing under the other, with core as the default and no `OPENGLCONTEXT_PROFILE` set | **met** — the *blank under core* and *crashes under core* buckets are both empty. The sweep's core arm now sets no variable at all, since core is the default and a declaration outranks the variable |
| The full unit suite is green with the default flipped | **met** |
| Every script needing the fixed-function pipeline says `profile = 'compatibility'` itself | **met** — 71 of them, 48 of which gained the line here |
| A scene built from `frommesh` or the glTF loader draws with no environment variable set | **met** — `tests/unit/test_default_profile.py` |
| `shadow_1` and `shadow_2` render again | **met** |
| The published documentation and CLAUDE.md name `core` as the default | **met** |
| The downstream `OPENGLCONTEXT_PROFILE=core` lines are gone, and each of those applications has been run | **deliberately not done** — see the flip, step 4: without a version floor on OpenGLContext, removing them would break each application against any published version where compatibility is still the default |
| `shader_1` … `shader_12` render under core with no compatibility declaration | **open** — [SHADER-TUTORIALS-CORE.md](SHADER-TUTORIALS-CORE.md), proposed and awaiting review |

Two scripts still fail under both profiles, neither for a reason to do with the
profile: `glutmousewheel.py` and `redbook_alpha3D.py` both need the GLUT backend
and the sweep runs under glfw. Run under `--backend glut`, `redbook_alpha3D`
draws in both; `glutmousewheel` segfaults in both, and `glut_font` raises in both
because it asks `GLUTFontProvider.get` for a font without the `mode` that would
tell it which context it is in. Both are demos to fix, and neither is a profile
question.

## Still worth doing

- **Atlas pages on the shader path.** A page is a sub-rectangle, and sampling one
  needs the UV transform that places it; the shader path asks for a texture of
  its own instead, so an `ImageTexture` with `repeatS`/`repeatT` off no longer
  shares a page with its neighbours. Uploading the page's transform through
  `set_texture_transform` would recover the batching. See E1.
- **`heightmap.py` shades differently between the profiles.** It draws correctly
  under both now, but the dips around its six zero-height points read almost
  black under the shader path and nearly flat under the fixed-function one. All
  its normals are `(0,1,0)`, so this is the two lighting models disagreeing, not
  the triangulation.
- **A `Shape` whose appearance is a `Shader` node** draws only in the
  compatibility profile: the geometry is submitted through a vertex array object
  at the attribute locations the pass's own program declares, and a `Shader`
  node's program declares its own. The core pass says so by name rather than
  raising an `AttributeError` per shape per frame, and `shaderobjects.py`,
  `shader_11` and `shader_12` declare compatibility. Giving `GLSLObject` a way to
  name the engine's attribute locations would make the declarative path work
  under core; see [SHADER-TUTORIALS-CORE.md](SHADER-TUTORIALS-CORE.md).
- **`glutmousewheel.py` segfaults and `glut_font.py` raises**, under both
  profiles, on the GLUT backend they each need.
- **`openglcontext-qt` in the workspace harness**, so a `uv sync` here exercises
  the Qt backend.
- **The two older runners.** `tests/run_core_tests.py` forces core onto
  everything, which is no longer the question being asked;
  `scripts/test_core_compatibility.py` judges an exit code and a keyword scan of
  the output, which is the instrument a silent black frame defeats. Both are
  superseded by `scripts/profile_sweep.py`.
