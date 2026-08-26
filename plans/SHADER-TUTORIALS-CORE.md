# The shader tutorials in core GLSL — a proposal

**Status:** 📋 Proposed, for review. Nothing in this document has been applied.
**Related:** [CORE-PROFILE-DEFAULT.md](CORE-PROFILE-DEFAULT.md), whose documentation
section this is the detail of. The default profile is now core; these tutorials
declare `profile = 'compatibility'` so they still run, and this is the plan for
taking that declaration back off.

## What is true today

`docs/tutorials/index.html` is already ordered shader-first — *Introduction to
Shaders*, then *Transformations*, then *Scenegraph Nodes*, then *Shadows*, with
the NeHe translations last. The ordering is not the problem.

The content is. Every tutorial in the *Introduction to Shaders* path is written
against GLSL 1.20 and the fixed-function pipeline seen from inside it, so the
series that teaches modern OpenGL borrows the pipeline it is teaching a reader to
leave. Measured, per file:

| Tutorial | `#version` | Built-ins it depends on | Fixed-function API |
|---|---|---|---|
| `shader_1` | 120 | `gl_Vertex`, `gl_ModelViewProjectionMatrix`, `gl_FragColor` | `glEnableClientState`, `glVertexPointer` |
| `shader_2`, `shader_2_c_void_p` | — | + `gl_Color`, `varying` | + `glColorPointer` |
| `shader_3`, `shader_4_subset` | — | as above | + `glRotate` |
| `shader_4` | — | `gl_ModelViewProjectionMatrix`, `attribute` | `glVertexPointer`, `glVertexAttribPointer` |
| `shader_5` … `shader_10` | — | `gl_ModelViewProjectionMatrix`, `gl_NormalMatrix`, `attribute`/`varying` | `glVertexAttribPointer` (no VAO); `glMaterial` in 7 |
| `shader_11`, `shader_12` | — | as above, plus `texture2D` | declarative nodes |
| `shader_ng`, `shader_spike`, `shaders` | — | `gl_NormalMatrix`, `attribute`/`varying` | `glVertexAttribPointer` (no VAO) |
| `shader_instanced` | — | `gl_ModelViewProjectionMatrix`, `gl_NormalMatrix`, `texture2D` | — |

`gl_ModelViewProjectionMatrix` and `gl_NormalMatrix` are the fixed-function matrix
stack seen from GLSL, removed in GLSL 1.40. `attribute`/`varying` became `in`/`out`
in 1.30, `gl_FragColor` was replaced by a declared output, and `texture2D` by
`texture`. A `glVertexAttribPointer` with no vertex array object bound is
`GLError(1282)` in a core context, since core has no default object 0 to record
into.

Two files are already close, and both fail on the same thing:

- **`shader_instanced_modern.py`** is written in `#version 140` with explicit
  matrix uniforms and `texture()`. It binds no vertex array object. Adding one is
  the whole change, after which it runs core with no declaration.
- **`transforms_1.py`** is `#version 120` but uses no fixed-function built-in at
  all — it builds and uploads its own matrices, which is what the tutorial is
  about. It needs a VAO, its `#version` raised, and `attribute`/`varying`
  renamed.

One engine gap sits behind the rest:

- **A `Shape` whose appearance is a `Shader` node** — `shaderobjects.py`,
  `shader_11`, `shader_12` — draws only in the compatibility profile. The
  geometry submits its vertices through a vertex array object at the attribute
  locations the pass's own program declares, and a `Shader` node's program
  declares its own. Giving `GLSLObject` a way to say which of the engine's
  attribute locations it wants would make the whole declarative path work under
  core; the core pass says so by name in the meantime
  (`Shape._render_shader`).

## What to change

### The GLSL

One substitution table, applied through the series:

| Today | Core |
|---|---|
| no `#version`, or `#version 120` | `#version 330 core` |
| `attribute vec3 position;` | `in vec3 position;` |
| `varying vec4 baseColor;` | `out` in the vertex shader, `in` in the fragment shader |
| `gl_FragColor = c;` | `out vec4 fragColor;` … `fragColor = c;` |
| `texture2D(sampler, uv)` | `texture(sampler, uv)` |
| `gl_ModelViewProjectionMatrix` | `uniform mat4 mat_modelproj;` |
| `gl_NormalMatrix` | `uniform mat4 mat_modelview;` and the normal matrix derived from it, or a `mat3` uniform of its own |
| `gl_Vertex`, `gl_Color` | declared `in` attributes bound to locations the tutorial sets |

`mat_modelproj`, `mat_modelview` and their inverses and transposes are uniforms
the render pass already supplies to any `GLSLObject` — see
`FlatPass._UNIFORM_NAMES` — so the declarative tutorials (`shader_11`,
`shader_12`, `shader_ng`) get them by naming them, with nothing to upload. The
hand-written ones (`shader_1` … `shader_10`) upload their own with
`glUniformMatrix4fv`, which is the thing being taught.

### The Python

- **A VAO around the attribute setup.** `glGenVertexArrays(1)` in `OnInit`,
  bound while the attribute pointers are specified and while drawing. This is
  the single change that `shader_instanced_modern`, `shader_spike`, `shader_ng`
  and `shader_5` … `shader_11` each need beyond the GLSL.
- **`glVertexPointer`/`glEnableClientState` become `glVertexAttribPointer`/
  `glEnableVertexAttribArray`** in `shader_1` … `shader_4`. `shader_4` already
  teaches the generic form; the earlier three should not teach the fixed-function
  one first and then replace it.
- **`glRotate` becomes a matrix the tutorial builds** in `shader_3` and
  `shader_4_subset`. `OpenGLContext.arrays` has what is needed, and building the
  matrix is the honest version of what `glRotate` was doing.
- **`glMaterial` in `shader_7` becomes uniforms**, which is what the tutorial's
  own text is already about.

### The prose

The workspace rule is to describe the fixed-function pipeline in terms of the
shaders, not the reverse. Concretely, through the series:

- A sentence that says a shader "replaces" or "does the job of" a fixed-function
  call should say what the shader computes, and mention the older call as the way
  the same thing used to be written, if at all.
- `shader_intro.html`'s requirements section should say the tutorials need
  OpenGL 3.3, which every driver of the last decade gives, rather than listing
  the 2.0-era extensions.
- Each page that keeps a fixed-function step should say so in a sentence at the
  top, matching the profile line now on `docs/tutorials/index.html`.

### The order

Unchanged. Shader-first already, NeHe last and labelled. The one addition:
`shader_instanced.py` (legacy GLSL) and `shader_instanced_modern.py` teach the
same lesson twice, and once the series is core there is no reason to keep the
legacy one. Either fold it into a note on the modern page or drop it.

## How to do it

Per tutorial, in this order, because each depends on the one before:

1. `transforms_1` — smallest, and one VAO from core.
2. `shader_instanced_modern` — one VAO.
3. `shader_1` … `shader_4` — the geometry tutorials; these establish the
   attribute-and-VAO pattern the rest inherit.
4. `shader_5` … `shader_10` — the lighting series; one matrix-uniform change
   applied identically to each.
5. `shader_11`, `shader_12`, `shader_ng` — the declarative-node tutorials, which
   take their matrices from the pass.
6. `shaders`, `shader_spike`, `shader_sphere` — the remaining hand-written ones.

Each step is done when:

- the tutorial has no `profile = 'compatibility'` declaration,
- `scripts/profile_sweep.py <name>.py` shows it drawing in both arms,
- `docs/tutorials/<name>.html` matches the source it quotes, and
- the prose describes what the shader does rather than what it replaces.

## What this does not cover

- **The NeHe series stays as it is** — compatibility, last in the index,
  labelled. It is a translation of a legacy tutorial and is worth keeping as one.
- **The shadow tutorials** (`shadow_1`, `shadow_2`) are compatibility and stay
  so for now: they teach the ARB depth-texture technique against the fixed
  function pipeline, and the engine's own shadow maps are documented separately
  in `docs/shadows.html`.
- **`redbook_*`, `gl*` entry-point demos, bitmap fonts.** These demonstrate the
  fixed-function API itself. They declare compatibility and that is the correct
  answer for them.
