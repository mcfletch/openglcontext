# OpenGLContext - Claude Code Guidelines

## Development environment: real OpenGL IS available

This is a **Wayland** dev container with **hardware-accelerated OpenGL** (`WAYLAND_DISPLAY` set).
Real GL runs here — render, benchmark, and reproduce visual bugs directly via the **GLFW default
context** (backend `glfw`; a hidden window with `glfw.window_hint(glfw.VISIBLE, glfw.FALSE)` works).
The `egl` backend renders with no window at all, and `LIBGL_ALWAYS_SOFTWARE=1` gives llvmpipe where
a run wants a deterministic rasteriser. Do **not** claim the sandbox is headless or that GL can't run.

**Ask which GPU this is rather than assuming** — the container has been rebuilt on different
hardware, and a fault can be specific to one vendor's driver:

```bash
/workspaces/OpenGL-dev/.venv/bin/python -c \
  "from OpenGLContext.testing.glcontext import describe_gl; print(describe_gl())"
```

At the time of writing that answers AMD Radeon (radeonsi, Mesa). It matters: the teardown segfault
PyOpenGL's `tests/README.md` records — roughly one context teardown in ten, inside
`libnvidia-eglcore` — appears on **NVIDIA only**, so a machine like this one cannot reproduce it
and a green run here says nothing about it. See `OpenGLContext.testing.glfwteardown`.

## Project Overview

OpenGLContext is a Python OpenGL framework providing a scenegraph-based rendering system with VRML97 compatibility. It supports both legacy fixed-function OpenGL (compatibility profile) and modern shader-based rendering (core profile).

## User Documentation

User documentation is in the `docs/` directory as reStructuredText, built into
a site by Sphinx. When asked to "update the docs" or "update the
documentation", update the pages in `docs/`, not this file (CLAUDE.md).

Key documentation files:

- `docs/index.rst` - Main landing page, and the toctrees every page hangs from
- `docs/documentation.rst` - Documentation index, annotated
- `docs/structure.rst` - Structural overview: the packages, and the page that describes each
- `docs/backends.rst` - The windowing backends, what each runs on, the methods every one provides, and context teardown
- `docs/profiles.rst` - Core vs. compatibility contexts, and declaring the one a program needs
- `docs/loading.rst` - Loading each format from Python, and the background load pool
- `docs/capturing.rst` - Screenshots, settled still captures, and video recording
- `docs/tutorials/` - The code walkthroughs, written from `tests/*.py`

Two directories beside them are **generated and not in version control**:
`docs/tutorials/*.rst` from the `'''`-string commentary in `tests/*.py`, and
`docs/api/` -- a page per module of the engine, of the packages it is built
from and of the ones built on it. `python build-docs.py` writes both and runs
Sphinx; `--stage DIR` puts a copy somewhere to look at and `--publish` puts it
on `gh-pages`. The module pages need PyOpenGL's `directdocs` package, which is
in the PyOpenGL *repository*: `DIRECTDOCS=../pyopengl` or `--directdocs` says
where. `docbuild/` holds this project's half of it.

## Project Plans

Project plans are stored in the `plans/` directory. The main index is [plans/PROJECT-PLAN.md](plans/PROJECT-PLAN.md), which contains a summary table of all plans with their status and links to individual plan documents.

When creating new plans:

1. Create a separate markdown file in `plans/` for detailed planning (e.g., `plans/FEATURE-NAME.md`)
2. Add an entry to the summary table in `plans/PROJECT-PLAN.md` with:
   - Link to the plan file
   - Current status (Planned, In Progress, Complete, etc.)
   - Brief description
3. Keep individual plan files focused on a single feature or initiative

## Directory Structure

Every sub-package of `OpenGLContext/`. **Keep this list complete**: it is how a
change finds the package it belongs in, and a package missing from it is a
package whose code ends up somewhere else.

```text
OpenGLContext/
├── audio/            # Spatial audio nodes + the per-context engine -- docs/audio.rst
│   └── vehicle.py    # A road vehicle's motor, tyres, wind and impacts as
│                     # scene nodes -- docs/audio.rst#audio-vehicle
├── bin/              # The console commands (see [project.scripts]) -- docs/viewer.rst
│   └── mirrorhall.py # The room oglc-mirrors hangs its mirrors in; scenery,
│                     # not a command
├── character/        # Rigged characters: rig, clips, mixer, crowds -- docs/characters.rst
├── contentpacks/     # Data an application fetches rather than ships: the
│                     # registry, the store, safe extraction and the polled
│                     # download job -- docs/contentpacks.rst
│   ├── application.py  # One application's packs: its registry, its store,
│   │                 # the first-run fetch and where its art is now
│   └── publish.py    # The release command every release-assets.py runs
├── packs.json        # The content packs this project publishes: the
│                     # bust-gallery world's URL, digest and terms, written
│                     # by release-assets.py, read by oglc-view --pack
│                     # -- docs/lod.rst
├── debug/            # Developer aids: buffer dumps, GL state, leak counts
├── demos/            # A view inside a Tk or wx application -- docs/embedding.rst
│                     # (the Qt one is in the openglcontext-qt distribution)
├── edit/             # Editor toolkit: tool modes, plan/orbit views, handles -- docs/editing.rst
│   ├── gizmo.py      # The tri-axis handle; a drag held to one axis
│   └── controlnet.py # A NURBS node's control points, as pickable markers
├── events/           # Cross-backend event generation and dispatch -- docs/eventmodel.rst
│   ├── framestep.py  # A simulation's time step each frame, from the clock:
│   │                 # the longest step and a frame cap -- no GL
│   └── wheel.py      # Rotation reports into whole notches, for the backends
│                     # whose toolkit states a detent size
├── loaders/          # File formats into the scenegraph -- docs/loading.rst, gltf.rst, vrml97.rst
│   ├── background.py # The pool a url field hands its fetch to, and the rule
│   │                 # that its imports are made by the submitting thread
│   ├── documentvalues.py  # A document's values, checked: JSONObject, a
│   │                 # default or a bound and one report, or DocumentError
│   │                 # for a part the document cannot be read without
│   ├── resolver.py   # Where a document's references may lead; ContainedPath
│   │                 # and CheckedURL, and the openers that take only them
│   │                 # -- docs/untrusted.rst
│   ├── gltf/         # glTF 2.0 / GLB
│   │   ├── lod.py    # MSFT_lod: a node's coarser levels, and when each is
│   │   │             # worth drawing -- docs/gltf.rst#lod. Making them is
│   │   │             # openglcontext-editor's job, not the engine's
│   │   └── lodasset.py  # A chain read one level at a time, sidecars
│   │                 # opened only when asked -- docs/baking.rst#writing-lod
│   └── tiles3d/      # Streamed OGC 3D Tiles -- docs/tiles3d.rst
├── move/             # Camera, movement modes, walking -- docs/navigation.rst
│   └── orbit.py      # The examine gestures: orbit, dolly, pan -- no GL, no events
├── multiview/        # Several views of one scene -- docs/multiview.rst
│   ├── views.py      # View, ViewStyle, ViewLayout: what is drawn where, and
│   │                 # which view an event belongs to -- no GL
│   ├── strategy.py   # How a frame reaches every view: vertex-stage routing,
│   │                 # a geometry stage, or the scene drawn once per view
│   ├── cameras.py    # OrthoView: a view along one axis at a scale
│   ├── viewpoints.py # The scene's cameras (VRML97 Viewpoints, glTF cameras)
│   │                 # as the render pass finds them, and a view looking
│   │                 # through one
│   ├── navigation.py # What the pointer does in one view: the gestures its
│   │                 # camera offers, and the bindings that raise them
│   ├── gestures.py   # Reading the pointer, and asking the view it is in
│   ├── grid.py       # The grid a view is measured against: how closely it
│   │                 # is ruled, and where its lines are
│   ├── viewset.py    # Several arrangements of one set of views, by name
│   ├── mixin.py      # Four views in any context that wants them, over the
│   │                 # camera it already had -- docs/multiview.rst
│   └── quad.py       # Three orthographic views around a perspective one
├── nav/              # Navigation mesh generated from a collision mesh
├── packaging/        # Shipping an application: /opt environments, .deb -- docs/packaging.rst
├── passes/           # Rendering passes -- docs/renderpasses.rst, flat.rst, pbr.rst
│   ├── _flat.py      # What both flat passes share; not instantiated directly
│   ├── flatcore.py   # Core-profile pass (GLSL)
│   ├── flatcompat.py # Compatibility-profile pass (fixed function)
│   ├── renderpass.py # Chooses between the two and caches the choice
│   ├── disposal.py   # The chain that deletes a pass's GL objects on a scene
│   │                 # swap or a context's teardown -- docs/renderpasses.rst
│   ├── framestate.py # What one frame shares among its stages (the walk of
│   │                 # the scene), dropped when the frame ends
│   ├── glstate.py    # GL state set for a block and put back however it
│   │                 # ends (enabled, bound_framebuffer, program, scissor),
│   │                 # and the baseline a frame starts from -- docs/renderpasses.rst
│   ├── pbrpass.py    # Metallic/roughness uber-shader -- docs/ubershader.rst
│   ├── ibl.py        # Image-based lighting probe
│   ├── reflection.py # Planar reflections' arithmetic: which surfaces are
│   │                 # mirrors, their planes, a mirror's camera -- docs/reflections.rst
│   ├── multiviewpass.py      # The pass's side of several views: layout, a
│   │                         # cull per view, the shared draw, pick routing
│   ├── reflectionpass.py     # The pass's side: a frame's mirror views drawn
│   │                         # into the atlas, and each mirror told its tile
│   ├── reflectionplanner.py  # A frame's mirrors: what to draw and read -- no GL
│   ├── reflectiontiles.py    # The atlas packer and the schedule -- no GL
│   ├── reflectionatlas.py    # The texture every reflection is a tile of
│   ├── gputimer.py   # GPU time of a stretch of a frame, read without waiting
│   ├── renderstats.py # What a frame cost in shapes and draws, for the
│   │                 # developer overlay -- docs/hud.rst
│   ├── zonepass.py   # The pass's side of zones: placing them each frame,
│   │                 # what each draw is given, captures -- docs/zones-internals.rst
│   ├── zonelayers.py # What zones give a draw, a camera, a listener -- no GL
│   ├── zoneprobes.py # When a zone's probe is captured, and the cube it is
│   │                 # drawn into
│   ├── zonebake.py   # Every capturing zone captured once and read back,
│   │                 # for a world to ship as image lights -- docs/zones.rst
│   ├── layerguard.py # An optional frame layer, switched off at its first
│   │                 # failure while the frame is drawn without it
│   ├── shadow*.py    # Shadow mapping -- docs/shadows.rst
│   ├── instancing.py # Collapsing repeated shapes -- docs/instancing.rst
│   └── shaderpass.py # VRML97ShaderProgram -- compiles and holds the programs
├── __pyinstaller/    # PyInstaller hooks, found by entry point -- docs/packaging.rst
├── physics/          # Rigid bodies, colliders, gravity zones -- docs/physics.rst
│   └── events.py     # Collision subscriptions: a callback per body, delivered
│                     # once a frame, and a trigger's occupancy
│                     # -- docs/physics.rst#physics-collisions
├── resources/        # Generated Python modules holding icons and shader text
├── py.typed          # The engine's declarations are real -- docs/typing.rst
├── scenegraph/       # VRML97-style nodes
│   ├── basenodes.py  # Every registered node class, by name
│   ├── basenodes.pyi # ...declared, since that namespace is filled at import
│   │                 # time. `scripts/write_basenodes_stub.py` writes it
│   ├── _basenodes_stub.py  # ...and this works out what it should say
│   ├── shape.py      # Binds Appearance to geometry
│   ├── extrusions.py # Swept geometry nodes -- docs/extrusions.rst
│   ├── nurbs*.py     # NURBS surfaces, curves, trims, sampling -- docs/nurbs.rst
│   ├── frommesh.py   # Generated glTF-shaped arrays -> scenegraph nodes
│   ├── pbrmaterial.py, pbrmesh.py   # The metallic/roughness material and mesh
│   ├── reflector.py  # PlanarReflector: a material's surfaces are mirrors
│   ├── mirrorhooks.py    # The mirror OGLC_hook kind -- docs/reflections.rst
│   ├── surfaces.py   # Procedural PBR maps (marble, tiles, brick, metals) and
│   │                 # geometry that wears them by the metre; NumPy only,
│   │                 # so Blender loads it too -- docs/surfaces.rst
│   ├── varied.py     # Varied: a node's copy with some fields changed
│   ├── lightgrid.py  # Baked irradiance grid: lights what a lightmap cannot
│   ├── zone.py       # Zone and its settings nodes; placing a frame's zones
│   │                 # -- docs/zones.rst
│   ├── zones.py      # Zones' arithmetic: shapes, distances, layering -- no GL
│   ├── imagebasedlight.py  # A document's own convolved environment
│   │                 # (EXT_lights_image_based) -- docs/pbr.rst
│   ├── octahedral.py # The fold an impostor's views are laid out by; the same
│   │                 # arithmetic is in pbr.vert -- docs/lod.rst#impostors
│   ├── geometryarrays.py   # What a geometry offers a shader, and binding it
│   ├── vertexsemantics.py  # Which attribute location each vertex array is read at
│   ├── road*.py      # Roads, roadworks, signs -- docs/roads.rst
│   ├── roadcourse.py # Where something is on a road at run time: along it,
│   │                 # off it, across it -- no GL -- docs/roads.rst#roadcourse
│   ├── particles.py  # Emitters, presets, one instanced draw -- docs/particles.rst
│   ├── particlehooks.py  # The fire, smoke and sparks OGLC_hook kinds
│   ├── water/        # Wave field, surface, medium -- docs/water.rst
│   ├── terrain/      # Height fields and splat materials -- docs/terrain.rst
│   ├── vegetation/   # Instanced cover and fields -- docs/vegetation.rst
│   └── text/         # Text rendering and font providers -- docs/text.rst
├── shaders/          # GLSL sources (.vert/.frag plus shared _*.glsl includes)
├── telemetry/        # A whole session to one file, and back -- docs/telemetry.rst
├── testing/          # The shipped test machinery conftest.py imports
├── tests/            # A second test root -- being moved to tests/unit/ (C1)
├── ui/               # Overlay UI: panels, widgets, skin -- docs/overlayui.rst
│   ├── overlay.py    # OverlayStack + OverlayMixin: the stack and input routing
│   ├── panel.py      # One screen: focus, accelerators, modality
│   ├── widgets.py    # Label/Button/Toggle/Select/Slider/Text+NumberField
│   ├── hudwidgets.py # The in-world HUD: reticule, meters, messages -- docs/hud.rst
│   ├── debugoverlay.py  # The developer overlay, fed by registered providers
│   ├── contentscreen.py # Downloading content packs: the offer, its terms,
│   │                 # a progress bar, Stop -- docs/contentpacks.rst
│   ├── viewchrome.py # A window of several views: each one's name, axes and
│   │                 # controls, and the splitters between them -- docs/multiview.rst
│   ├── tooltip.py    # What a control says when the pointer rests on it
│   ├── layout.py     # Row/Column/Grid (built on hud.GUIBox)
│   ├── draw.py       # The GL renderer: one program, one batched buffer
│   └── generate.py   # A settings page from a node's fields (UI_HINTS)
├── video/            # H.264 capture of the colour buffer -- docs/recording.rst
├── viewer/           # The embeddable viewer behind oglc-view -- docs/viewer.rst
│   └── adapters/     # One per format; what oglc-view dispatches on
├── windowsystem/     # The window a Context draws in, one module per toolkit,
│   │                 # and choose(): which one a definition opens -- docs/backends.rst
│   ├── base.py       # WindowSystem: the protocol, and the shared main loop
│   ├── glfw.py, glut.py, pygame.py, tk.py, wx.py   # A window through each toolkit
│   └── egl.py, wgl.py  # No window: a pbuffer on Linux or Windows -- docs/offscreen.rst
├── atomicfiles.py    # A file or directory written whole or not at all:
│                     # staged beside its path, moved in with one rename, and
│                     # a lock for two processes writing the same one
├── hud.py            # Screen-space layout GUINode/GUIBox use (see ui/)
├── noise.py          # Value noise over the ground plane (fbm, ridged): the
│                     # grain landscapes and what is added to them are made
│                     # of -- numpy only
├── outline.py        # The scenegraph as rows, for a tree control -- no GL, no
│                     # toolkit -- docs/embedding.rst
├── processexit.py    # Ending the process at once, output and coverage flushed:
│                     # what a capture or a bounded run exits through
├── renderoptions.py  # How a pass reads a rendering feature from the definition
├── screenshot.py     # The F2 key every context binds -- docs/capturing.rst
├── swapcontrol.py    # Waiting for the refresh, for backends that name nothing
├── contextresources.py   # Caches let go of a GL context's names as it dies;
│                         # ContextKey, what a per-context table keys on
├── contextdefinition.py  # The fields a context is configured by
├── context.py        # Context: ContextCore plus the event, camera and scene
│                     # mix-ins, holding a WindowSystem
├── glfwcontext.py, glutcontext.py, pygamecontext.py, tkcontext.py,
│   wxcontext.py, eglcontext.py, wglcontext.py
│                     # Context with one window system pinned, plus the
│                     # *interactive*, *vrml* and *testing* names for it
├── interactivecontext.py  # The event-handler mix-in under its published name
├── vrmlcontext.py    # VRMLSceneMixin: load() and lazily loaded font providers
└── testingcontext.py      # getInteractive(): Context, or one pinned by name
```

## Rendering Architecture

### Multi-Pass Rendering System

The rendering system uses a **FlatPass** that observes the scenegraph structure and renders objects in multiple passes:

1. **Background Pass** - Renders sky/ground colors or cube maps
2. **Opaque Pass** - Renders non-transparent geometry (front-to-back)
3. **Transparent Pass** - Renders transparent geometry (back-to-front, depth-sorted)
4. **Selection Pass** - Color-based picking using unlit shader
5. **Overlay Pass** - Frame counter, HUD elements

### Shader vs Legacy Rendering

The system supports two rendering modes, controlled by `use_shaders` on FlatPass:

**Legacy Mode (use_shaders=False)**:

- Uses OpenGL fixed-function pipeline
- Requires compatibility profile
- Uses `glLight*`, `glMaterial*`, display lists
- Geometry nodes use `glVertexPointer`, `glColorPointer`, etc.

**Shader Mode (use_shaders=True)**:

- Uses GLSL shaders implementing VRML97 lighting model
- Compatible with OpenGL 3.3+ core profile
- Geometry nodes check `mode.shader_mode` and use VAO/VBO rendering
- Shader program manages uniforms for matrices, materials, lights

### Key Mode Attributes

During rendering, geometry nodes receive a `mode` object with:

```python
mode.shader_mode       # True if using shader-based rendering
mode.shader_program    # VRML97ShaderProgram instance (if shader_mode)
mode.matrix            # Current modelview matrix
mode.projection        # Current projection matrix
mode.visible           # True for visible pass, False for selection
mode.transparent       # True during transparent pass
mode.lighting          # True if lighting is enabled
mode._bound_texture_id # Texture ID bound by Shape (for geometry nodes)
```

### Adding Shader Support to Geometry Nodes

To add shader support to a geometry node:

```python
def render(self, mode=None, **kwargs):
    # Check for shader mode
    if getattr(mode, 'shader_mode', False):
        return self._render_shader(mode)

    # Legacy rendering path
    # ... glVertexPointer, glDrawArrays, etc.

def _render_shader(self, mode):
    shader_program = mode.shader_program

    # Switch to appropriate shader if needed
    shader_program.use(lit=True)  # or use_point(), use(lit=False), etc.

    # Set matrices
    shader_program.set_matrices(mode.matrix, mode.projection)

    # Create VAO/VBO, set up vertex attributes at the locations
    # scenegraph/vertexsemantics.py declares
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    glEnableVertexAttribArray(LOC_POSITION)
    glVertexAttribPointer(LOC_POSITION, 3, GL_FLOAT, GL_FALSE, stride, None)

    glDrawArrays(GL_TRIANGLES, 0, vertex_count)

    # Cleanup
    glBindVertexArray(0)
    glDeleteVertexArrays(1, [vao])
```

### Shader Programs

The `VRML97ShaderProgram` class (in `passes/shaderpass.py`) manages multiple shader programs:

- `program` - Main lit shader with VRML97 Phong lighting
- `unlit_program` - For selection/picking and unlit rendering
- `vertex_color_program` - For per-vertex colored geometry (NURBS)
- `point_program` - For PointSet/particles with per-vertex colors
- `line_program` - For IndexedLineSet with per-vertex colors
- `depth_program` - Position-only, for the shadow depth passes

**Attribute locations are fixed, and `OpenGLContext/scenegraph/vertexsemantics.py`
is where they are decided** -- keyed by glTF's vertex semantics, which is the
vocabulary the loaders already speak:

| Location | Semantic | Shader name |
|---|---|---|
| 0 | `TEXCOORD_0` | `aTexCoord` (vec2) |
| 1 | `NORMAL` | `aNormal` (vec3) |
| 2 | `POSITION` | `aPosition` (vec3) |
| 3 | `TANGENT` | `aTangent` (vec4) |
| 4 | `COLOR_0` | `aColor` (vec4) |
| 5-10, 14 | -- | reserved for the per-instance inputs |
| 11 | `TEXCOORD_1` | `aTexCoord1` (vec2) |
| 12, 13 | `JOINTS_0`, `WEIGHTS_0` | `aJoints`, `aWeights` (vec4 each) |

Locations rather than names, because a VAO records locations: with them fixed,
one VAO per geometry serves the lit pass, the unlit pass and the depth pass
alike. Import the `LOC_*` constants rather than writing the number. A program
that owns both its geometry and its shader (the overlay UI batcher, particles,
the vegetation and terrain layers) numbers its own inputs, but must not spell one
of the names above and mean something else by it --
`tests/unit/test_vertex_semantics.py` holds every shader in the package to that.

**Each input in a shader a pass binds says whether it can be drawn without.**
The first word of the declaration's own comment is the marker: `required`, or
`optional` and what the default value means there. An uber-shader declares every
array any geometry might carry and reads most of them only where a uniform says
this one did, so `required` is the short list, and it is what
`report_missing_inputs` names a geometry against
(`passes/shadersource.required_inputs`, `docs/renderpasses.rst`).

```glsl
layout(location = 1) in vec3 aNormal;    // required: shading has no direction without it
layout(location = 3) in vec4 aTangent;   // optional: zero disables normal mapping
```

## Environment

Use the virtualenv at `/workspaces/OpenGL-dev/.venv` for all Python operations. It
is a Python 3.12 environment with OpenGL installed as an editable install from
`pyopengl/`; it is the only interpreter here that imports OpenGL and OpenGLContext.

```bash
source /workspaces/OpenGL-dev/.venv/bin/activate
```

Or run directly with:

```bash
/workspaces/OpenGL-dev/.venv/bin/python <script.py>
```

Do **not** use `../.env` or the project-local `openglcontext/.venv` — neither can
`import OpenGL` in this devcontainer.

## Environment Variables

**Most of these are now `ContextDefinition` fields**, and the environment
variable is the field's *default* rather than a competitor: a shell variable
still pins a feature for a script or a CI run, while the settings screen
(`OpenGLContext.ui.settings`) writes the field and takes precedence from then on.
The engine reads the environment only through `OpenGLContext.renderoptions`
(and `userpaths` for the platform's per-user directories), which ruff's
banned-api list holds it to; a program pins a variable with
`renderoptions.set_env` / `default_env`, which forget an answer already read
once. The fields are `shadows`, `shadowsSoft`, `shadowCascades`,
`maximumLights`, `bloom`, `ibl`, `iblIntensity`, `transmission`,
`planarReflections` (with the reflection budget: `reflectionViews`,
`reflectionBounces`, `reflectionSeparateViews`, `reflectionAtlas`,
`reflectionMilliseconds`),
`instancing`, `tessellationLOD`, `vsync` and `uiScale`; see
[docs/overlayui.rst](docs/overlayui.rst).

**These are start-up switches, and each is read once.** A pass that changed its
mind mid-session because something else edited `os.environ` would be
unpredictable, and the field is the thing meant to change at runtime. So the
variable settles the default the first time it is asked for — through
`renderoptions.env_flag_once` / `env_number_once`, which is the one place that
memo lives — and the field outranks it from then on. Never read one at import
time: the answer is then frozen before any application or test can set it, and
nothing can reach it afterwards. `renderoptions.reset_env_cache()` clears the
memo, and `tests/unit/conftest.py` calls it around every test.

A value that is neither a yes nor a no is **reported rather than swallowed**:
these variables are how a feature is pinned for a CI run, and a typo that
silently reverses the pin makes that run's result a lie. An unset variable and
an empty one mean the same thing, because that is what an unexported shell
variable expands to.

`uiScale` (env: `OPENGLCONTEXT_UI_SCALE`) is the player's own multiplier on the
overlay's size. It is *on top of* the automatic scaling the window's height
already applies, so a 4K display gets a larger interface without anyone setting
it. Every pixel measurement in the UI — skin insets, widget margins,
`maximumWidth`, grid row padding — goes through that scale; see
`OpenGLContext.ui.metrics`.

### OPENGLCONTEXT_PROFILE

Controls the OpenGL profile used for rendering:

- `core` (default) - OpenGL 3.3+ core profile, rendered through shaders
- `compatibility` - the fixed-function pipeline

```bash
export OPENGLCONTEXT_PROFILE=compatibility
```

All six backends (`glfw`, `glut`, `pygame`, `tk`, `wx`, `qt`) create a real core
context and render identically in one.

**A program that needs a profile declares it**, rather than relying on whoever
runs it to set the variable:

```python
class TestContext( BaseContext ):
    profile = 'compatibility'   # this demo draws with the fixed-function pipeline
```

`Context.profile` is applied over whatever `contextDefinition` the class
declares, so it composes rather than replacing; it settles the OpenGL version to
match; and a definition passed to the constructor outranks both. Declare it for
anything calling `glBegin`, `glVertexPointer`, `glMaterial`, `glLight`, the
matrix stack, display lists, or GLSL's `gl_ModelViewProjectionMatrix` — none of
which exist in core. `Context.resolveDefinition` is where the order is decided,
and every backend calls it before it opens a window, since the profile, version
and buffer formats are all window-creation parameters. See
[docs/profiles.rst](docs/profiles.rst).

**`scripts/profile_sweep.py` compares the two profiles by what they drew.** A
fixed-function call in a core context raises `GLError(1282)`, and the render pass
catches it per node and carries on — so the process exits 0 and the frame is
black. An exit code is therefore not evidence that anything rendered; the sweep
runs every script under both profiles through the auto-exit capture path and
reports the drawn fraction of each capture.

```bash
scripts/profile_sweep.py --out /tmp/sweep            # both profiles, every script
scripts/profile_sweep.py --out /tmp/sweep shader_1.py molehill.py
scripts/profile_sweep.py --report /tmp/sweep/results.json
```

**GL feature floor.** All shaders target `#version 330 core` and the VRML97/base
shader path runs on GL 3.3. The **advanced render paths** — runtime IBL
(`passes/ibl.py`), shadow maps (`passes/shadowmap.py`), bloom and screen-space
transmission — additionally use **immutable texture storage**
(`glTexStorage2D/3D`), which is **GL 4.2 core / `ARB_texture_storage`**. That
extension is present on every desktop GPU driver since ~2012 (integrated Intel/AMD
included) and on macOS 4.1, so it is not a practical restriction, but it means the
effective floor for those paths is GL 4.1 + `ARB_texture_storage`, not 3.3. There
is no per-level `glTexImage` fallback; a driver lacking immutable storage raises
during IBL/shadow setup (IBL then degrades to the analytic path, see
`resolve_ibl_mode`).

### OPENGLCONTEXT_LOD

Distance level-of-detail for procedurally tessellated geometry (teapot, quadrics,
NURBS surfaces). On by default: geometry far from the camera is tessellated (and
cached) more coarsely, scaled by object size. Set to `0`/`off`/`false` to force
full detail at every distance (deterministic output, e.g. reference-image
regression). The finest level (0, close up) matches the pre-LOD tessellation.

```bash
export OPENGLCONTEXT_LOD=off
```

### OPENGLCONTEXT_BACKEND

Selects the window system a context opens on where its definition's
`windowsystem` field names none (the field wins; then this; then the user's
`defaultcontext.txt`; then the first that imports, GLFW first -- see
`OpenGLContext.windowsystem.choose` and docs/backends.rst):

- `glut` - Use GLUT/freeglut (default on many systems)
- `glfw` - Use GLFW (recommended for core profile)
- `pygame` - Use Pygame
- `tk` - Use Tkinter, through PyOpenGL's own `OpenGL.Tk.GLFrame` widget. Needs
  no package installed, and needs an X display: Tk has no Wayland backend, so a
  headless machine runs it under `xvfb-run`.
- `wx` - Use wxPython
- `qt` - Use Qt 6 / PySide6, from the separate `OpenGLContext-qt` distribution
  (`openglcontext-qt/`). Needs a Qt platform plugin that gives a drawable GL
  surface; the Wayland plugin does not in this container, so run Qt work with
  `QT_QPA_PLATFORM=xcb`.
- `egl` - Offscreen on Linux: no window and no display server (`windowsystem/egl.py`)
- `wgl` - Offscreen on Windows: a pbuffer, no window on screen (`windowsystem/wgl.py`)
- `offscreen` - whichever of `egl` and `wgl` this platform has

```bash
export OPENGLCONTEXT_BACKEND=glfw
```

A program pins one with `ContextDefinition(windowsystem='egl')`, or on its
class with `windowSystemName = 'offscreen'`. See
[docs/offscreen.rst](docs/offscreen.rst).


### OPENGLCONTEXT_STALL_MS / OPENGLCONTEXT_TRACE_STALLS

Diagnostics for a loop that stutters while the frame rate reads healthy. The
frame counter times only the inside of `OnDraw`, only for frames that changed
something, and publishes a *median* — so an application whose simulation lives
in `OnIdle` can crawl at a few updates a second with no number contradicting
another. `OpenGLContext.looptrace` measures wall-clock time per **loop
iteration**, divided among phases that sum to it (`poll`, `repeats`, `idle`,
`wait`, `draw`, and `cascade`/`render` inside the draw).

`OPENGLCONTEXT_STALL_MS` sets what counts as a stall (default 50) *and*
switches logging on; `OPENGLCONTEXT_TRACE_STALLS` logs at the default
threshold. Counting is always on and costs a few clock reads per iteration.

```bash
OPENGLCONTEXT_STALL_MS=40 /workspaces/OpenGL-dev/.venv/bin/python -m twig_bb
# WARNING OpenGLContext.looptrace: main loop stalled 912ms: idle 901ms, render 9ms, poll 1ms
```

Unlike the variables above, these change nothing about what a frame looks like,
so they are **not** in `renderoptions.ENVIRONMENT` and a subprocess capture
inherits them. See [docs/hud.rst](docs/hud.rst) and
[plans/LOOP-INSTRUMENTATION.md](plans/LOOP-INSTRUMENTATION.md).

### OPENGLCONTEXT_STALL_TRACE

Records each slow period to a JSON-lines file, with the main thread's Python
stack **sampled while the stall is happening** — the only way to learn which
code was running, since the stack has unwound by the time the iteration closes.
Sampling is gated on the stall itself, so healthy frames are never profiled.

```bash
OPENGLCONTEXT_STALL_TRACE=/tmp/stalls.jsonl /workspaces/OpenGL-dev/.venv/bin/twig-bb ...
/workspaces/OpenGL-dev/.venv/bin/python -m OpenGLContext.stalltrace /tmp/stalls.jsonl
```

The file is not meant to be read by eye — always go through the reader. Each
record is one *episode* (a whole slow period, not a frame) and leads with a
per-function `self`/`cumulative` tally; the whole stacks under it are the
evidence for that tally, not the answer. `OpenGLContext.stalltrace`.

### OPENGLCONTEXT_TELEMETRY / OPENGLCONTEXT_TELEMETRY_REPLAY

Records a **whole session** to one JSON-lines file: every input the platform
delivered (stamped with the frame that acted on it), every frame's wall-clock
time and phase breakdown, every exception with its traceback, logged warnings,
and the developer overlay's own sections sampled every few seconds. Read it
back with the module; **replay** it to run the session again.

```bash
OPENGLCONTEXT_TELEMETRY=/tmp/session.jsonl /workspaces/OpenGL-dev/.venv/bin/twig-bb
/workspaces/OpenGL-dev/.venv/bin/python -m OpenGLContext.telemetry /tmp/session.jsonl
OPENGLCONTEXT_TELEMETRY_REPLAY=/tmp/session.jsonl /workspaces/OpenGL-dev/.venv/bin/twig-bb
```

`OPENGLCONTEXT_TELEMETRY=1` writes a dated file under the user's app-data
directory; `OPENGLCONTEXT_TELEMETRY_MAX_MB` caps the file (default 128), past
which exceptions and marks still get through. An application switches it on for
itself with `context.startTelemetry(path)` and marks its own events with
`context.mark('level-loaded', map='ztn3dm1')` — a call whether or not anything
is recording. A replay compares those marks with the recorded ones and logs how
the two accounts agreed as it ends, which is how a session says whether it
played out the same way.

Unlike the stall switches these **are** in `renderoptions.ENVIRONMENT`: a
journal names one file for one session, so a subprocess capture that inherited
the name would overwrite its parent's, and a replay drives the camera. See
[docs/telemetry.rst](docs/telemetry.rst) and
[plans/SESSION-TELEMETRY.md](plans/SESSION-TELEMETRY.md).

### OPENGLCONTEXT_SEED

Fixes the session's randomness — `OpenGLContext.entropy` owns one seed per
session, and setting this seeds the ordinary `random` and `numpy.random`
generators from it as well, so a whole run is reproducible. Useful well beyond
telemetry: a reference image whose scene scatters vegetation or throws sparks is
deterministic under a pinned seed.

```bash
OPENGLCONTEXT_SEED=4242 /workspaces/OpenGL-dev/.venv/bin/python -m twig_bb
```

Unset, the engine still chooses a seed for its own **named streams**
(`entropy.generator('trees')`, `entropy.randomizer('bots')`) but leaves the
process's generators exactly as it found them — a library that reseeded them
would silently undo an application's own `random.seed(...)`. Telemetry records
the seed *and* where those generators stood, and a replay puts both back.
Also in `renderoptions.ENVIRONMENT`: a capture that wants a fixed sequence pins
it rather than inheriting one.

### OPENGLCONTEXT_CAPTURE_FPS

What a capture's world clock advances by per frame. A bounded run
(`OPENGLCONTEXT_AUTO_EXIT_FRAMES`) puts the engine's time source on a
`FixedStepClock` starting at zero and advancing one frame's worth per `OnDraw`,
so a scene animated from a `Timer` or a `TimeSensor` reaches the same point on
every machine and the frame read back is a picture of the scene rather than of
how long the process took to start. This names a rate other than 60, or `0` for
a capture that wants to watch real time pass.

```bash
OPENGLCONTEXT_CAPTURE_FPS=30 /workspaces/OpenGL-dev/.venv/bin/python tests/nehe4.py
```

Only what reads `OpenGLContext.events.systemtime` follows — every `Timer` and
`TimeSensor`. A demo calling `time.time()` itself does not, and asks
`systemtime.systemTime()` instead; nor does state advanced from `OnIdle`, which
the main loop calls as often as it has room for. `OpenGLContext.video.clock`.

## Code Conventions

### Writing Style

Use simple, plain-spoken text. Omit needless adjectives and adverbs.

**State facts; never dare the reader to check them.** A sentence that invites
verification — "grep it and see", "count them yourself", "if you don't believe
me", "check the code" — reads as anxiety about being believed, and it makes the
claim *less* trustworthy, not more: nobody hedges a fact they are sure of. It
also wastes the reader's attention on something trivial, which is the opposite
of what documentation is for. Write the fact and move on. This applies to
documentation, docstrings, comments, plans and commit messages alike.

```text
Bad:  The mixer imports no path, no matrix and no listener -- grep it and see.
Good: The mixer imports no path, no matrix and no listener: it is handed gains
      and produces blocks.

Bad:  This really is O(1), honestly -- look at the loop.
Good: This is O(1): the table is indexed, not scanned.
```

The same instinct shows up as defensive padding — "to be clear", "note that
this genuinely does", "as you can verify" — and as needless self-justification
in a report. Cut all of it. If a claim is load-bearing and hard to believe, the
answer is to *state the mechanism* that makes it true, or point at the test that
holds it, not to challenge the reader.

A **pointer** is not a dare: "see `tests/unit/test_x.py` for the cases this
covers" is useful, because it tells the reader where to go for more than the
sentence can hold. The difference is whether the reader is being *offered*
something or being *challenged* to prove you right.

**Never write about this software as a failure or a confession.** It is our own
code, described for someone deciding whether to use it. A feature is not
"unrendered until now", "declared for twenty-odd years and never implemented",
"barely tested", "crude", "naive", or "not really finished" — that is either
history (see below) or an apology, and neither tells the reader anything they can
act on. The tone matters as much as the content: a page that runs itself down
reads as a warning, and the reader takes the warning.

A **limit** is not an apology, and limits must still be stated. The difference is
that a limit is a fact with a boundary the reader can work inside, while an
apology is a judgement on the work:

```text
Bad:  UTF-8 should allow non-English content, but this has never been tested
      beyond the most rudimentary sample content.
Good: The string field is Unicode; what a non-English string renders as is a
      question of the chosen font carrying the glyphs for it.

Bad:  A crude, naive frustum test that really ought to be a proper BVH.
Good: Culling is a per-object frustum test. Scenes of tens of thousands of
      small objects spend measurable time in it; a spatial index would not.

Bad:  Fog is VRML97's own node, declared for twenty-odd years and unrendered
      until now.
Good: Fog is VRML97's own node, with the fields that specification gives it.
```

The same instinct reversed — "blazingly fast", "state of the art", "the right
way to do it" — is equally unwelcome. State what it does and what it costs, and
let the reader judge.

**Comments:** Leave off "what I'm doing" comments in non-tutorial code. Comments should explain a hidden idea, an underlying motivation, or an intention that isn't clear from the code itself.

```python
# Bad: Set the color to red
color = (1.0, 0.0, 0.0)

# Good: Red indicates selection failure in legacy GL implementations
color = (1.0, 0.0, 0.0)
```

**Describe what is, never history.** A docstring is for a reader who
opens the file today with no memory of how it got here. Say why the module/class
exists, what it does for the caller, and where and how it is used. Do **not**
record how the code came to be — that provenance is dead the day it lands, git
blame already keeps it, and it crowds out the description a reader actually needs.

This applies to every docstring, comment and module header **and to the user
documentation in `docs/`**. A user reading `docs/audio.rst` has even less use
for the backstory than a maintainer does: "nothing has ever played them, they
work now" tells them nothing about how to play a sound, dates the page the moment
it lands, and reads as the project congratulating itself. Write what the feature
does and how to use it.

```text
Bad:  pyvrml97 has declared Sound and AudioClip for twenty-odd years and nothing
      has ever played them. They work now:
Good: VRML97's own Sound and AudioClip play, with the fields pyvrml97 declares
      for them:

Bad:  This replaces the frame-rate display FrameCounter used to draw through
      glOrtho, which means nothing in a core profile. It no longer draws.
Good: FrameCounter measures the frame rate and does not draw it: the provider
      reads its number and the HUD puts it on screen. Drawing it from there would
      mean glOrtho, which means nothing in a core profile.
```

Note what survives in each: the *reason* (glOrtho is meaningless in a core
profile) is worth keeping, stated in the present tense as a fact about the code
that is there. It is the narrative around it that goes.

`plans/` is the exception, and the only one: a plan document records what was
decided and what landed, so a status note, a dated entry or a "still open" list
belongs there. Nowhere else.

Phrasings that are always history, never description — if you write one, delete it:

- **Origin of the code:** "Split out of X", "moved from / extracted from Y",
  "promoted to a package", "was part of Z".
- **Review/ticket bookkeeping:** "finding 7c", "(finding 4.14)", "per the code
  review", any bare issue/finding number.
- **A former state or behavior:** "previously this was…", "the old default
  was…", "used to be…", "was doubled, which…", "originally we…".
- **A replaced or rejected alternative:** "replaces the …-lists pattern that X
  used", "instead of the old closure approach", "rather than the previous
  helper", "no longer needs the …". The reader does not care about the design
  that never landed or the one that was removed — describe only the code that is
  there now.
- **Continuity reassurance:** "still works", "keeps resolving", "as they always
  have", "for backward compatibility with the old path".
- **The size of what changed:** "~22% of the god class", "the ~250-line cluster",
  "cut from 1857 lines".

When a *reason* survives the history (why a path is chosen, why a subtle branch
exists), state the reason in the present tense and drop the backstory.

```python
# Bad: "Split out of :mod:`context` (finding 7c): the config factory made up
#       ~22% of the god class and was mostly classmethods with no state."
# Good: "Per-user configuration and backend selection for `Context`: resolves the
#        app-data directory, reads/writes the default-font and default-backend
#        preferences, and loads a backend `Context` subclass from entry points."

# Bad: "The old default (<system-temp>/oglc_gltf_cache) is world-writable and
#       shared between accounts, so another user could pre-seed a cache (finding 4.14)."
# Good: "Cache under the per-user app-data directory, not world-writable system
#        temp, so another account cannot pre-seed an entry this user then loads."
```

### File Locations

The full map is under [Directory Structure](#directory-structure); this is the
short answer for the places a change most often lands.

- Unit tests are in `tests/unit/`; the runnable demo scripts the visual
  regression suite drives are in `tests/`
- Scenegraph nodes are in `OpenGLContext/scenegraph/`
- Rendering passes are in `OpenGLContext/passes/`
- Shaders are in `OpenGLContext/shaders/` as `.vert` and `.frag` files
- The window systems (GLFW, GLUT, Pygame, Tk, wx, EGL, WGL) are in
  `OpenGLContext/windowsystem/`; `Context` itself is `OpenGLContext/context.py`
- User documentation is `docs/*.rst`; plans are `plans/*.md`

**A capability a game would also want belongs in the engine, not in a demo or
a tool.** If the natural home is a new module, add it to a package that already
owns the subject and add it to the directory map above.

### Geometry Node Pattern

Geometry nodes typically follow this pattern:

```python
class MyGeometry(basenodes.MyGeometry):
    def render(self, visible=1, lit=1, textured=1, transparent=0, mode=None):
        # Early exit if nothing to render
        if not self.data:
            return 1

        # Check for shader mode
        if getattr(mode, 'shader_mode', False):
            return self._render_shader(mode, textured=textured)

        # Legacy rendering path
        # ...
        return 1

    def _render_shader(self, mode, textured=False):
        # Shader-based rendering
        # ...
        return 1
```

### Instanced Rendering

`render()` above is the **per-object** path — one draw per shape. When many shapes
share one geometry (a sphere field, repeated glTF parts, a scatter of props), the
pass collapses them into a single instanced draw instead of calling `render()` once
each. There are two distinct instancing paths, and **neither goes through
`render()`**:

**1. Pass-level automatic batching (the common case).** The pass groups opaque
records that share geometry + a compatible appearance
(`passes/instancing.build_instance_groups`) and draws each group with one
`glDrawElementsInstanced` (`draw_instanced_mesh`) — see `_drawInstanceGroup` in
`passes/pbrpass.py` and `passes/flatcore.py`. A geometry node opts in by exposing
two methods; it does **not** touch its own `render()`:

```python
def instanceContentKey(self):
    # Cheap content signature: distinct nodes with an equal key batch together.
    # Boxes of equal size, spheres of equal radius, etc.
    return ('Box', tuple(round(float(v), 6) for v in self.size))

def instanceGPU(self, mode):
    # A separate-VBO _MeshGPU (position=2, normal=1, texcoord=0) that
    # draw_instanced_mesh() can draw. build_mesh_gpu caches it on the context and
    # rebuilds it when a depend_field changes (e.g. size / radius).
    from OpenGLContext.passes.instancing import build_mesh_gpu
    return build_mesh_gpu(
        mode, self, positions, normals, texcoords, indices=None,
        cache_key='instance_gpu',
        depend_fields=('size',))     # names or field objects; names are clearer
```

Working examples: `scenegraph/box.py`, `quadrics.py` (Sphere/Cone/Cylinder),
`teapot.py`, `indexedfaceset.py`. The batcher is format-neutral, so VRML
`USE`/`DEF` sharing, glTF shared meshes and `EXT_mesh_gpu_instancing` all feed it.

**2. Node-driven raw-GL instancing (vegetation / terrain).** Nodes under
`scenegraph/vegetation/` and `scenegraph/terrain/` drive core-profile GL directly
inside their own `render()` — their own program, VAO, per-instance buffer and
`glDraw*Instanced` — bypassing the VRML97/Shape path entirely. They restream
per-frame instance data (camera-following fields) via the shared helpers in
`scenegraph/instancedgl.py`: `InstanceBuffer` (grow-or-`glBufferSubData`, no
per-frame realloc), `setup_instance_attribs`, and the `GLLayer` base, whose
`ensure_gl()` makes the node's GL objects at its first draw (a failure sets `failed`,
so a driver quirk drops the layer instead of crashing the frame) and whose `drawn`
switch leaves a layer undrawn. To compose with the
driving pass's GL state they use the pass's own CPU state memo, not a `glGet`
snapshot: they restore the pass's bound program with `mode.current_program()` and
route face-cull through `passes.instancing.set_cull_state(mode, ...)` (the same memo
`PBRMesh._apply_draw_state` uses), which the pass resets once per frame. Reach for
this path only when the standard batcher can't express the node (dynamic instance
sets, array textures, custom shaders).

### Shape/Geometry Interaction

The `Shape` node handles material and texture setup, then calls `geometry.render()`:

1. Shape sets up material uniforms via `configure_material_from_node()`
2. Shape binds texture and stores ID in `mode._bound_texture_id`
3. Shape calls `geometry.render(textured=True/False, mode=mode)`
4. Geometry can access the bound texture via `mode._bound_texture_id`

## Requirements for New Code

**The goal is perfect code quality, not merely code that runs.** "It works" is the
floor, not the bar. Every one of the following applies to new code before a task is
done:

### Workspace-wide rules also apply

[../CLAUDE.md](../CLAUDE.md) binds every project here. Three of its requirements
are easy to skip and must not be:

- **Never destroy work to run an experiment.** Do not revert, restore over or
  delete files you did not create this session — no `git checkout HEAD --`, no
  `git clean`, no archive-extract over the working tree — to get a baseline or
  test a hypothesis. Experiment in a `git worktree` or a scratchpad copy, use
  absolute paths for anything that writes files, and remember that untracked
  files (`plans/`, design notes) have no undo. A red test is to be **fixed, not
  attributed**, so the blame experiment that tempts this is never needed.
- **Documentation ships with the change.** New feature, new option, changed
  default, changed public API — update `docs/` (and `plans/` where a design note
  exists) in the same piece of work, and say in your report what you changed.
- **Never copy copyleft code.** Any task that would involve reading a GPL/LGPL/
  AGPL/CC-BY-SA codebase must follow [../CLEAN-ROOM.md](../CLEAN-ROOM.md):
  prefer a non-copyleft source, split the Reader and Implementer roles, and let
  only a spec in [../specs/](../specs/) cross the wall.

### Red/Green TDD

Write the failing test first, watch it fail (red), then write the code that makes
it pass (green). The test must genuinely exercise the new behavior and fail for the
right reason before the implementation exists — a test that was never red proves
nothing.

### Coverage: 100%, or as near as is practical

New code should be fully covered by tests. Aim for 100%; where a line is genuinely
impractical to reach (a defensive branch that needs a broken GL driver, say),
cover everything around it and leave the gap deliberate and explained, not
accidental.

```bash
/workspaces/OpenGL-dev/.venv/bin/python -m pytest --cov=OpenGLContext --cov-report=term-missing tests/
```

### Test real machinery, not mocks of the whole world

Tests should drive as much of the actual code path as practical. Do not mock out
the entire world just to assert one line — a test that replaces every collaborator
with a stub proves the stubs work, not the code. Prefer real objects, real
geometry, a real GL context (this container has one — see the top of this file)
over a mock whenever it is feasible. Reserve mocks for the genuinely
hard-to-instantiate edges (a specific GL error, missing hardware, network).

### Types: annotated, mypy-clean

All new code is fully type annotated and passes mypy with the project config in
[pyproject.toml](pyproject.toml). No new `# type: ignore` without a reason, and no
widening the `physics.*` override to escape a real error.

```bash
/workspaces/OpenGL-dev/.venv/bin/python -m mypy --follow-imports=silent OpenGLContext/<path>/
```

**Per path, not the whole package.** `OpenGLContext/` as a whole still carries a
large backlog of pre-existing errors — mostly `name-defined` from the star
imports in the older modules — which was invisible for as long as `python_version`
disagreed with the interpreter and mypy aborted on numpy's own stubs before
checking anything. The gate is that the path you touched is clean; the backlog is
its own job, and re-suppressing it package-wide is not a way to do it.

### Lint: ruff-clean

New code passes `ruff check` with no warnings under the project config
(`E`/`W`/`F`/`B`).

```bash
/workspaces/OpenGL-dev/.venv/bin/python -m ruff check OpenGLContext/<path>/
```

### Caches

A cache answers what the computation would answer, for every input the
computation reads.

Key on the object, never on `id()` alone. An `id()` is reused as soon as its
object is collected, so a cache keyed on `id(positions)` or on a raw context
address answers a new object with an old object's result. Hold the key object
(a `WeakKeyDictionary`, or the object itself in the key or the entry), or key
on something the object carries that is not reused.

Cover every input. A memo that checks only some of what its answer depends on
keeps a stale answer when one of the others changes: a field of the node
itself, a setting, a scale, a texture edited in place. Compare every input, or
key on a generation count that the scenegraph's field observers bump when any
of them is set -- a `('set', field)` signal through `pydispatch.dispatcher`
(`passes.reflection.mirror_generation` is one), or a `vrml.cache` holder whose
`depend(node, field)` names them (`scenegraph.boundingvolume`).

A cache's tests edit each input in turn and assert that the answer changes,
so an input the key misses fails a test rather than a frame.

### Before a change is finished

The static gates (ruff, mypy, `oglc-check`) catch what the syntax and the
types show. These defect classes they do not, so a change that can introduce
one carries the test that holds it, from `OpenGLContext.testing` (the
conventions are in [docs/testing.rst](docs/testing.rst#conventions)):

- A memo or cache - `check_memo_inputs`, one edit per input its answer is
  made from (`tests/unit/test_memo_inputs.py`).
- Anything drawn every frame - `check_still_frame`: a still scene's second
  frame makes, fills and compiles nothing (`tests/unit/test_still_frames.py`).
- Per-frame work over the scene's objects - `check_scaling` at n and 4n, by
  count where the work can report one, by time under `serial`
  (`tests/unit/test_scaling.py`).
- An optional frame layer - `check_failing_layer`: made to fail, it is tried
  once, reported once and asks for no frames (`tests/unit/test_failing_layers.py`).
- A geometry node or a draw path - `check_mirrored_render`, and a case in
  `tests/unit/test_mirrored_geometry.py` for a new geometry class.
- A numeric entry point - the suite's `numpy_errors = "raise"`, and tests at
  zero, negative, huge and non-finite inputs.
- A module that opens files - the suite's open audit: through the resolver or
  `atomicfiles`, or listed in `open_audit_sanctioned` in `pyproject.toml` with
  the reason its paths are its own.
- A second implementation of one API, or a specification's format - a
  differential test between the implementations, or the specification's own
  sample assets.
- Logic in a window-bound class - hoisted into a plain object and tested
  there.
- A user-visible change - its page in `docs/` updated in the same commit.

### Imports

`from x import *` is traditional in this codebase and should **not** be churned out
of *old* code — leave existing star imports alone. In **new** code, prefer explicit
imports; `from OpenGL import GL as gl` (and similar aliased module imports) is the
preferred style where a qualified namespace helps readability.

## Testing

**The test suite must pass. Always. It does not matter who broke a test or when —
if it is red, it is your job to make it green before you are done.** Never dismiss
a failure as "pre-existing", "environmental", "unrelated to my change", or
"flaky". A failure in the full run is a real failure; investigate and fix it (or
fix the test if the test itself is wrong). "It passes in isolation" is not passing
— if a test only fails in the full run, that is a real test-isolation bug to fix,
not to wave away.

### The suite renders offscreen

`tests/conftest.py` sets `OPENGLCONTEXT_HIDDEN=1` and `OPENGLCONTEXT_NO_VSYNC=1`
for the whole session, and both reach subprocess tests through `os.environ` and
survive `renderoptions.clean_environment()` (see `renderoptions.PRESENTATION`).
A hidden window renders and reads back identically, so nothing is traded away —
and several hundred *mapped* windows flashing over whatever you are doing, and
stealing focus while you type, is not something to inflict on anyone.

It also stops swaps blocking: a compositor throttles the swap to its own frame
callback, and a window nothing is showing never gets one.

**Set `OPENGLCONTEXT_HIDDEN=0` to watch a test render** — which is how you find
out why one looks wrong. A scratch script outside the suite has to set both
itself.

**`OPENGLCONTEXT_TEST_WINDOWING=offscreen` runs it with no window at all**, on
the platform's offscreen backend (a WGL pbuffer on Windows), which is what a
machine with no desktop or no GLFW needs. The default is `glfw`, the hidden
window. A test that reaches past the context to the window it came from uses
`testing.glcontext.make_current` / `release_current` / `framebuffer_size`, which
work under both, and one that genuinely asks GLFW about a window skips on
`glcontext.windowing() != 'glfw'`. See [docs/testing.rst](docs/testing.rst).

Order-dependent GL failures are almost always **context/state pollution** between
tests. The fix is better isolation, not weaker assertions: prefer the test harness
that creates a **fresh window/GL context per test** (and tears it down), so no test
inherits another's GL state. Run the *whole* suite (not just the files you touched)
before declaring done.

### Asking for a GL context: `gl_context`

A test that renders in-process asks for the `gl_context` fixture and gets a
hidden core-profile 3.3 window, current for that test and gone afterwards. It
comes from `OpenGLContext.testing.plugin`, which `pyproject.toml` turns on with
`addopts = "-p OpenGLContext.testing.plugin"`, so an application built on the
engine turns the same fixtures on the same way -- see
[docs/testing.rst](docs/testing.rst).

```python
def test_the_glow_spreads(gl_context):
    ...                                   # the context is current here

@pytest.fixture                           # a bigger one, or another profile
def gl_context(gl_window):
    return gl_window('bloom', size=(96, 96))
```

`gl_context_compat` is the compatibility-profile one, for the fixed-function
paths; `gl_window` is the factory both are built on. **Do not hand-roll the
GLFW calls in a test module.** Thirty of them did, each subtly different -- four
never reset the sticky window hints, so the context they got was the one the
previous test had asked for, and two asked for no profile at all while needing
`glGenLists` and `glFrustum`. `OpenGLContext.testing.glcontext.hidden_window` is
the same thing without pytest, for a module-scoped fixture or a scratch script,
and `gl_available()` answers "can this machine render at all" once for the
process instead of once per test file.

### The tests that need a quiet machine: `serial`

A test that measures against the *clock* rather than against a value passes on
an idle machine and fails on one busy with the rest of the suite --
`test_instancing_performance.py` compares wall-clock frame times with instancing
on and off, and under load the margin between them closes. Those carry the
`serial` marker, so a full run is two passes:

```bash
/workspaces/OpenGL-dev/.venv/bin/python -m pytest tests/unit -q -m "not serial"
/workspaces/OpenGL-dev/.venv/bin/python -m pytest tests/unit -q -m serial
```

The second pass is short and has the machine to itself, which is the whole of
what it needs. The sibling `omi_physics` project marks its own timing checks the
same way, for the same reason.

The marker is for **a wall-clock margin and nothing else**: every other failure
in a full run is a real failure to fix.

**The conformance views are no longer among them.** The Parthenon views used to
be bimodal -- pixel-identical to the baseline or ~10% different, never in
between -- and other sky-lit views were suspected of the same. The cause was
image-based lighting adapting to the frame rate while the capture was being
taken, so the frame landed at whatever point the climb back to `full` had
reached. A capture now pins it, exactly as it already pinned the shadow
cascades (`renderoptions`/`ibl.ibl_is_adaptive`), and those views render the
same bytes every time. `RecursiveSkeletons` was separately nondeterministic
because it is animated and its scene entry pinned no `anim_time`; it does now.
If a conformance view starts differing again, it is a regression, not weather.

Run tests from the project root:

```bash
/workspaces/OpenGL-dev/.venv/bin/pytest tests/<testname>.py
```

Many tests are interactive demos that display OpenGL content.

### Automated Test Suite

The automated test suite runs all test scripts in subprocesses with coverage collection:

```bash
# Run all tests with visual regression and HTML report
/workspaces/OpenGL-dev/.venv/bin/python -m pytest tests/test_all_scripts.py::TestVisualRegression -v

# Run all tests (including non-visual functionality tests)
/workspaces/OpenGL-dev/.venv/bin/python -m pytest tests/test_all_scripts.py::TestAllScripts -v

# View the HTML report after tests complete
open tests/report.html
```

The test infrastructure provides:

- **Auto-exit**: Scripts exit automatically after N frames via `OPENGLCONTEXT_AUTO_EXIT_FRAMES` env var
- **Screenshot capture**: Auto-capture on exit via `OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR` and `OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME`
- **FPS display toggle**: Disable FPS overlay via `OPENGLCONTEXT_DISABLE_FPS_DISPLAY` for clean screenshots
- **Visual regression**: Compare result images against reference images in `tests/reference_images/`
- **HTML reports**: Generated at `tests/report.html` with side-by-side image comparisons

### Test Categories

Scripts are categorized for appropriate testing:

- **Visual scripts**: Produce graphical output, included in visual regression (`TestVisualRegression`)
- **Non-visual scripts**: Functionality tests with stdout output (glget.py, boundingvolume.py, etc.) - run via `TestAllScripts`
- **Platform-specific**: Windows-only (WGL), wxPython, pygame scripts with automatic skip logic
- **Randomized**: Scripts whose captured frame does not follow from the scene,
  marked with `expect_visual_diff` and run for their exit status. A capture
  counts frames rather than seconds, so an animated scene is compared normally;
  what is left here advances its state from `OnIdle`. See
  `RANDOMIZED_SCRIPTS` in `tests/test_all_scripts.py`.

### Unit Test Requirements

**All new functionality must have unit tests before a task is considered complete.**

**Coverage goal:** 80-100% code coverage. Use coverage reports to identify uncovered lines and target new test cases accordingly:

```bash
/workspaces/OpenGL-dev/.venv/bin/python -m pytest --cov=OpenGLContext --cov-report=term-missing tests/
```

**Test framework:** Use pytest. Run tests in subprocesses when they require OpenGL contexts or other isolated environments.

**Test naming:** Name tests after the use case or condition being tested, not the implementation detail.

Unit tests should:

1. **Verify code execution** - Tests must actually exercise the new code paths. A common failure mode is tests that pass but don't call the code being tested (mocking too much, testing the wrong class, or import errors that silently skip tests).

2. **Test with realistic inputs** - Use inputs that exercise the actual logic, not just edge cases that short-circuit.

3. **Verify outputs** - Assert on actual behavior/output, not just that code didn't crash.

4. **Run independently** - Tests should run without requiring a GUI or OpenGL context when possible. Use mock objects for context-dependent code.

5. **Review for refactoring** - After tests pass, review for opportunities to create fixtures or helper functions to reduce duplicate code.

Example:

```python
def test_mousemove_events_filtered_when_no_handlers():
    """Mousemove events should be removed when no handlers are registered."""
    fp = FlatPass.__new__(FlatPass)
    fp._has_mousemove_handlers = None

    events = {
        ('mousemove', (100, 200)): MockEvent('mousemove', 100, 200),
        ('mousebutton', (100, 200)): MockEvent('mousebutton', 100, 200),
    }

    result = fp._optimizePickEvents(MockContext(), events)

    assert len(result) == 1
    assert list(result.values())[0].type == 'mousebutton'
```

**Tutorial code:** Files with embedded triple-quoted strings describing the code at length are tutorials. Do not modify tutorial code as part of test suite changes.

### Testing the compatibility profile

```bash
OPENGLCONTEXT_PROFILE=compatibility /workspaces/OpenGL-dev/.venv/bin/pytest tests/<testname>.py
```

#### wxPython, GTK3 and EGL

wxPython on GTK3 makes its GL context through EGL rather than GLX, and on X11
it may be either. **Do not set `PYOPENGL_PLATFORM` for it.** PyOpenGL's Linux
platform loads both interfaces and probes for the live context
(`OpenGL/platform/linux.py`), so the calls are routed to whichever API owns the
context the toolkit made — naming one pins it and breaks the other. Pinning is
for an offscreen render (`PYOPENGL_PLATFORM=egl`, or `osmesa`), where there is
no toolkit to ask.

Key test files:

- `tests/particles_simple.py` - Particle system (PointSet with colors/textures)
- `tests/nurbssurface.py` - NURBS with per-vertex colors
- `tests/shader_*.py` - Shader-specific tests
- `tests/lighting_*.py` - Lighting model tests

### Headless / CI rendering

The visual suite renders real frames, so it needs *some* GL target. Without one
it skips every visual test, which reads as green even though nothing rendered.
On a headless runner provide a target explicitly:

- **Offscreen GL:** set `PYOPENGL_PLATFORM=egl` (or `osmesa`). The suite treats
  EGL/OSMesa as a usable display and runs instead of skipping.
- **Virtual X server:** wrap the run in
  `xvfb-run -a /workspaces/OpenGL-dev/.venv/bin/python -m pytest ...`.

Reference images are compared with a **percentage tolerance** (default 2% of
pixels, per-channel delta > 5), not byte-for-byte, because cross-GPU
rasterization, anti-aliasing and gamma differ. For byte-stable references pin a
software rasterizer (llvmpipe / `LIBGL_ALWAYS_SOFTWARE=1`) in CI so every run
uses the same renderer. `OPENGLCONTEXT_CAPTURE_DELAY` (seconds) makes the
pre-capture stabilization wait more generous on slow CI; capture also waits for
a minimum frame count, so it is a floor, not the only readiness signal.

Directional-shadow cascade count is normally fps-adaptive, which makes shadowed
frames nondeterministic. Set `OPENGLCONTEXT_SHADOW_CASCADES=<n>` to pin the
rendered cascade count (bypassing the fps probe) so shadow output is reproducible
for reference-image regression.

## Common Debugging

### GL Errors

When debugging GL errors in shader mode:

```python
err = glGetError()
if err != GL_NO_ERROR:
    log.error("GL Error: %s", err)
```

### Shader Compilation

Shader compilation errors are logged during `VRML97ShaderProgram.compile()`.

### Attribute Verification

To verify shader attribute locations match your VBO setup:

```python
from OpenGL.GL import glGetAttribLocation
pos_loc = glGetAttribLocation(program, 'aPosition')
log.info("aPosition location: %d", pos_loc)
```

### Matrix Issues

The shader uses column-major matrices. Ensure numpy arrays are in the correct format:

```python
matrix = np.ascontiguousarray(matrix, dtype='f')
```
