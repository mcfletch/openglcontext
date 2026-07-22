# OpenGLContext - Claude Code Guidelines

## Development environment: real OpenGL IS available

This is a **Wayland** dev container with **full NVIDIA OpenGL** support (`WAYLAND_DISPLAY` set).
Real GL runs here — render, benchmark, and reproduce visual bugs directly via the **GLFW default
context** (backend `glfw`; a hidden window with `glfw.window_hint(glfw.VISIBLE, glfw.FALSE)` works).
Do **not** claim the sandbox is headless or that GL can't run. EGL/OSMesa default-display init fails
in this container; that is a quirk of those paths, NOT evidence that GL is unavailable — use GLFW.

## Project Overview

OpenGLContext is a Python OpenGL framework providing a scenegraph-based rendering system with VRML97 compatibility. It supports both legacy fixed-function OpenGL (compatibility profile) and modern shader-based rendering (core profile).

## User Documentation

User documentation is in the `docs/` directory as HTML files. When asked to "update the docs" or "update the documentation", update the files in `docs/`, not this file (CLAUDE.md).

Key documentation files:

- `docs/index.html` - Main landing page
- `docs/documentation.html` - Documentation index with links to tutorials and references
- `docs/structure.html` - Structural overview of the codebase (contexts, rendering, events)
- `docs/tutorials/` - Tutorial HTML files

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

```text
OpenGLContext/
├── passes/           # Rendering passes (multi-pass rendering system)
│   ├── _flat.py      # Base FlatPass with shader and legacy support
│   ├── flatcore.py   # Core profile FlatPass (use_shaders=True by default)
│   ├── flatcompat.py # Compatibility profile FlatPass
│   ├── shaderpass.py # VRML97ShaderProgram - shader management
│   └── renderpass.py # Base render pass classes
├── scenegraph/       # VRML97-style scenegraph nodes
│   ├── shape.py      # Shape node (binds Appearance to geometry)
│   ├── appearance.py # Appearance node (material + texture)
│   ├── pointset.py   # PointSet geometry (particles, point clouds)
│   ├── indexedfaceset.py  # Indexed face set geometry
│   ├── arraygeometry.py   # VBO-based geometry base class
│   ├── background.py      # Background nodes
│   ├── light.py           # Light nodes (DirectionalLight, PointLight, SpotLight)
│   ├── text/              # Text rendering subsystem
│   │   ├── fontprovider.py   # Font provider registry
│   │   ├── glutfont.py       # GLUT bitmap font (legacy)
│   │   ├── shaderfont.py     # Shader-compatible font wrapper
│   │   └── shadertext.py     # Texture atlas text renderer
│   └── ...
├── shaders/          # GLSL shader source files
│   ├── vrml97_lighting.vert/frag  # Main lit shader (Phong lighting)
│   ├── vrml97_unlit.vert/frag     # Unlit shader (picking, text)
│   ├── vrml97_point.vert/frag     # Point/particle shader
│   ├── vrml97_vertex_color.vert/frag  # Per-vertex color shader
│   └── vrml97_background.vert/frag    # Background shader
├── events/           # Event handling system
├── move/             # Camera/viewpoint movement
├── loaders/          # File format loaders (VRML, OBJ, etc.)
├── context.py        # Base context class
├── glutcontext.py    # GLUT context implementation
├── glfwcontext.py    # GLFW context implementation
├── interactivecontext.py  # Interactive context with mouse/keyboard
└── testingcontext.py      # Testing context utilities
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

    # Create VAO/VBO, set up vertex attributes
    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)
    # ... setup vertex attributes at fixed locations
    # layout(location = 0) = position
    # layout(location = 1) = normal or color
    # layout(location = 2) = texcoord

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

Shader attribute locations are fixed:

- `layout(location = 0)` - position (aPosition or aTexCoord for text)
- `layout(location = 1)` - normal or color (aNormal or aColor)
- `layout(location = 2)` - texcoord or position (aTexCoord or aPosition)

## Environment

Use the virtualenv at `../.env` for all Python operations:

```bash
source ../.env/bin/activate
```

Or run directly with:

```bash
../.env/bin/python <script.py>
```

## Environment Variables

### OPENGLCONTEXT_PROFILE

Controls the OpenGL profile used for rendering:

- `compatibility` (default) - Use OpenGL compatibility profile with legacy fixed-function pipeline
- `core` - Use OpenGL 3.3+ core profile with shader-based rendering

```bash
export OPENGLCONTEXT_PROFILE=core
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

Selects the windowing backend:

- `glut` - Use GLUT/freeglut (default on many systems)
- `glfw` - Use GLFW (recommended for core profile)
- `pygame` - Use Pygame
- `wx` - Use wxPython

```bash
export OPENGLCONTEXT_BACKEND=glfw
```

**Note:** When using `OPENGLCONTEXT_PROFILE=core`, the backend should typically be set to `glfw` as it properly supports core profile context creation.

## Code Conventions

### Writing Style

Use simple, plain-spoken text. Omit needless adjectives and adverbs.

**Comments:** Leave off "what I'm doing" comments in non-tutorial code. Comments should explain a hidden idea, an underlying motivation, or an intention that isn't clear from the code itself.

```python
# Bad: Set the color to red
color = (1.0, 0.0, 0.0)

# Good: Red indicates selection failure in legacy GL implementations
color = (1.0, 0.0, 0.0)
```

**Docstrings describe what is, never history.** A docstring is for a reader who
opens the file today with no memory of how it got here. Say why the module/class
exists, what it does for the caller, and where and how it is used. Do **not**
record how the code came to be — that provenance is dead the day it lands, git
blame already keeps it, and it crowds out the description a reader actually needs.
This applies to every docstring, comment, and module header.

Phrasings that are always history, never description — if you write one, delete it:

- **Origin of the code:** "Split out of X", "moved from / extracted from Y",
  "promoted to a package", "was part of Z".
- **Review/ticket bookkeeping:** "finding 7c", "(finding 4.14)", "per the code
  review", any bare issue/finding number.
- **A former state or behavior:** "previously this was…", "the old default
  was…", "used to be…", "was doubled, which…", "originally we…".
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

- Tests are in the `tests/` directory
- Scenegraph nodes are in `OpenGLContext/scenegraph/`
- Rendering passes are in `OpenGLContext/passes/`
- Shaders are in `OpenGLContext/shaders/` as `.vert` and `.frag` files
- Context implementations (GLUT, GLFW, etc.) are in `OpenGLContext/`

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

### Shape/Geometry Interaction

The `Shape` node handles material and texture setup, then calls `geometry.render()`:

1. Shape sets up material uniforms via `configure_material_from_node()`
2. Shape binds texture and stores ID in `mode._bound_texture_id`
3. Shape calls `geometry.render(textured=True/False, mode=mode)`
4. Geometry can access the bound texture via `mode._bound_texture_id`

## Testing

**The test suite must pass. Always. It does not matter who broke a test or when —
if it is red, it is your job to make it green before you are done.** Never dismiss
a failure as "pre-existing", "environmental", "unrelated to my change", or
"flaky". A failure in the full run is a real failure; investigate and fix it (or
fix the test if the test itself is wrong). "It passes in isolation" is not passing
— if a test only fails in the full run, that is a real test-isolation bug to fix,
not to wave away.

Order-dependent GL failures are almost always **context/state pollution** between
tests. The fix is better isolation, not weaker assertions: prefer the test harness
that creates a **fresh window/GL context per test** (and tears it down), so no test
inherits another's GL state. Run the *whole* suite (not just the files you touched)
before declaring done.

Run tests from the project root:

```bash
../.env/bin/python tests/<testname>.py
```

Many tests are interactive demos that display OpenGL content.

### Automated Test Suite

The automated test suite runs all test scripts in subprocesses with coverage collection:

```bash
# Run all tests with visual regression and HTML report
pytest tests/test_all_scripts.py::TestVisualRegression -v

# Run all tests (including non-visual functionality tests)
pytest tests/test_all_scripts.py::TestAllScripts -v

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
- **Randomized**: Scripts with non-deterministic output marked with `expect_visual_diff`

### Unit Test Requirements

**All new functionality must have unit tests before a task is considered complete.**

**Coverage goal:** 80-100% code coverage. Use coverage reports to identify uncovered lines and target new test cases accordingly:

```bash
../.env/bin/python -m pytest --cov=OpenGLContext --cov-report=term-missing tests/
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

### Testing Core Profile

```bash
OPENGLCONTEXT_PROFILE=core python tests/<testname>.py
```

#### wxPython GTK3 Requires EGL for Core Profile

**Important:** wxPython GTK3 uses EGL (not GLX) for OpenGL context creation.
Core profile rendering with wxPython requires `PYOPENGL_PLATFORM=egl` to be set
so PyOpenGL can properly track the OpenGL context.

The `wxcontext` module attempts to set this automatically when GTK3 is detected,
but if OpenGL is imported before wxcontext, you must set it manually:

```bash
PYOPENGL_PLATFORM=egl OPENGLCONTEXT_PROFILE=core python tests/<testname>.py
```

Or in code (before any OpenGL imports):

```python
import os
os.environ['PYOPENGL_PLATFORM'] = 'egl'
```

**Symptoms if EGL is not set:** Errors like "Attempt to retrieve context when no
valid context" during shader rendering, particularly in `glVertexAttribPointer`
or other VAO/VBO operations. Legacy (fixed-function) rendering may still work
because it doesn't rely on PyOpenGL's context tracking.

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
- **Virtual X server:** wrap the run in `xvfb-run -a pytest ...`.

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
