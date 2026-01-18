# OpenGLContext - Claude Code Guidelines

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

Run tests from the project root:

```bash
../.env/bin/python tests/<testname>.py
```

Many tests are interactive demos that display OpenGL content.

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
