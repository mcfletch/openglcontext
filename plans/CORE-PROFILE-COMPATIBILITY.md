# Core Profile Compatibility for flatcore.py

**Problem**: Despite its name and stated intent, `flatcore.py` is not actually core-profile compatible. It still relies on numerous deprecated fixed-function pipeline features that are unavailable in OpenGL core profiles.

**Goal**: Make `flatcore.py` (and the geometry nodes it renders) fully functional with an OpenGL 3.2+ core profile context.

## Non-Core-Profile Features Currently Used

**In flatcore.py / flatcompat.py / _flat.py:**

| Feature | Location | Core Profile Replacement |
|---------|----------|-------------------------|
| `glMatrixMode(GL_PROJECTION/GL_MODELVIEW)` | flatcompat:60,70,74,153,256; _flat:519 | Shader uniforms for matrices |
| `glLoadMatrixf()` | flatcompat:61,71,131,141,154,182,266; flatcore:169,251; _flat:445,529 | Shader uniforms |
| `glLoadIdentity()` | flatcompat:77 | Shader uniforms |
| `glEnable/glDisable(GL_LIGHTING)` | flatcompat:89,220,291; flatcore:275; _flat:553 | Shader-based lighting |
| `glEnable(GL_COLOR_MATERIAL)` | flatcompat:221 | Shader-based material |
| `glDisable(GL_COLOR_MATERIAL)` | flatcompat:290; flatcore:274; _flat:552 | Shader-based material |
| `GL_LIGHT0` + id | flatcompat:123,133,142 | Shader uniform arrays |
| `glColor4ubv()` / `glColor4f()` | flatcompat:263,289; flatcore:248,273; _flat:526,551 | Vertex attributes or uniforms |
| `MAX_LIGHTS` / `GL_MAX_LIGHTS` | flatcompat:122,135,294,302; flatcore:121,278,286; _flat:386,556,564 | Shader-defined limit |

**In geometry/scenegraph nodes (23 files use legacy immediate mode):**

| Node Type | File | Legacy Features Used |
|-----------|------|---------------------|
| Box | box.py | glBegin/glEnd, glVertex, glNormal |
| Sphere/Cylinder/Cone | quadrics.py | GLU quadrics (gluSphere, etc.) |
| IndexedFaceSet | indexedfaceset.py | glBegin/glEnd, glVertex, glNormal, glTexCoord |
| IndexedLineSet | indexedlineset.py | glBegin/glEnd, glVertex, glColor |
| PointSet | pointset.py | glBegin/glEnd, glVertex, glColor |
| Gear | gear.py | glBegin/glEnd, glVertex, glNormal |
| Text (various) | text/*.py | glBegin/glEnd, bitmap fonts |
| Light | light.py | glLightfv, GL_LIGHT0, etc. |
| Material | material.py | glMaterialfv, GL_FRONT, etc. |
| Appearance | appearance.py | glMaterial calls |
| Background | spherebackground.py, cubebackground.py | Immediate mode geometry |
| ArrayGeometry | arraygeometry.py | Mixed - some VBO, some legacy |
| BoundingVolume | boundingvolume.py | Debug rendering with immediate mode |

## Testing Strategy

### Phase 1: Create Core-Only Test Context

Create a test context subclass that forces core profile:

```python
# tests/test_core_profile.py
from OpenGLContext import glfwcontext
from OpenGLContext.contextdefinition import ContextDefinition

class CoreProfileTestContext(glfwcontext.GLFWContext):
    """Test context that enforces OpenGL core profile"""

    def __init__(self):
        definition = ContextDefinition(
            profile='core',
            major_version=3,
            minor_version=2,
        )
        super().__init__(definition)
```

### Phase 2: Systematic Feature Testing

Create test cases for each geometry/feature type:

1. **Basic rendering tests** (one per geometry type):
   - `test_core_box.py` - Box geometry
   - `test_core_sphere.py` - Sphere (quadrics)
   - `test_core_indexedfaceset.py` - IndexedFaceSet
   - `test_core_indexedlineset.py` - IndexedLineSet
   - `test_core_pointset.py` - PointSet
   - `test_core_text.py` - Text rendering

2. **Lighting tests**:
   - `test_core_directional_light.py`
   - `test_core_point_light.py`
   - `test_core_spot_light.py`
   - `test_core_multi_light.py`

3. **Material/Appearance tests**:
   - `test_core_material.py`
   - `test_core_texture.py`
   - `test_core_transparency.py`

4. **Background tests**:
   - `test_core_sphere_background.py`
   - `test_core_cube_background.py`

5. **Selection/picking tests**:
   - `test_core_selection.py`

### Phase 3: Implementation Order

1. **Rendering pass infrastructure**:
   - Create VRML97 lighting shader (vertex + fragment)
   - Add matrix uniform management to FlatPass
   - Remove glMatrixMode/glLoadMatrixf calls
   - Implement shader-based light collection

2. **Basic geometry nodes** (easiest first):
   - Box (simple, well-defined vertices)
   - ArrayGeometry (already partially VBO-based)
   - IndexedFaceSet (most commonly used)

3. **Quadric geometry**:
   - Replace GLU quadrics with VBO-based implementations
   - Sphere, Cylinder, Cone

4. **Line/Point geometry**:
   - IndexedLineSet
   - PointSet

5. **Material/Lighting**:
   - Shader-based material application
   - Multi-light support in shader

6. **Advanced features**:
   - Text rendering (may need complete rewrite)
   - Selection rendering (shader-based color ID)
   - Background rendering

## Success Criteria

- All existing tests pass with core profile context
- No GL errors when running with `GL_KHR_debug` enabled
- Visual output matches compatibility profile (within reason)
- Works on macOS with core profile (primary validation platform)

## Files Requiring Modification

**Rendering passes:**

- `OpenGLContext/passes/flatcore.py`
- `OpenGLContext/passes/_flat.py`

**Geometry nodes:**

- `OpenGLContext/scenegraph/box.py`
- `OpenGLContext/scenegraph/quadrics.py`
- `OpenGLContext/scenegraph/indexedfaceset.py`
- `OpenGLContext/scenegraph/indexedlineset.py`
- `OpenGLContext/scenegraph/pointset.py`
- `OpenGLContext/scenegraph/indexedpolygons.py`
- `OpenGLContext/scenegraph/polygontessellator.py`
- `OpenGLContext/scenegraph/gear.py`
- `OpenGLContext/scenegraph/arraygeometry.py`

**Lighting/Material:**

- `OpenGLContext/scenegraph/light.py`
- `OpenGLContext/scenegraph/material.py`
- `OpenGLContext/scenegraph/appearance.py`

**Background:**

- `OpenGLContext/scenegraph/spherebackground.py`
- `OpenGLContext/scenegraph/cubebackground.py`

**Text (may defer):**

- `OpenGLContext/scenegraph/text/font.py`
- `OpenGLContext/scenegraph/text/glutfont.py`
- `OpenGLContext/scenegraph/text/wxfont.py`
- `OpenGLContext/scenegraph/text/pygamefont.py`
- `OpenGLContext/scenegraph/text/toolsfont.py`

**New files to create:**

- `OpenGLContext/shaders/vrml97_lighting.vert` - Vertex shader
- `OpenGLContext/shaders/vrml97_lighting.frag` - Fragment shader
- `tests/test_core_profile.py` - Core profile test harness
- `tests/core/test_*.py` - Individual geometry/feature tests
