# Shader-Based Rendering Pass for Legacy VRML97 Content

**Problem**: OpenGLContext's rendering of legacy VRML97 content relies on the fixed-function pipeline, which is deprecated in modern OpenGL core profiles and unavailable on some platforms (e.g., macOS 3.2+ core context). This limits portability and prevents taking advantage of modern GPU features.

**Proposed Solution**: Create a shader-based rendering pass that implements the VRML97 lighting model, allowing legacy scenegraph content to render through programmable shaders.

## Key Constraints

- **Backward Compatibility**: The existing `flatcompat` rendering path must continue to work unchanged. Most current clients use this path and rely on its behavior.
- **Parallel Implementation**: New shader-based code should exist alongside legacy code, not replace it initially.
- **Gradual Migration**: Clients can opt-in to shader-based rendering; it should not be forced.

## Architecture

### New Protocols for Geometry Nodes

Geometry nodes will need to support a new protocol for shader-compatible rendering:

```python
class ShaderGeometryProtocol:
    """Protocol for geometry nodes to provide shader-compatible data"""

    def get_vertex_buffer(self, mode) -> VBO:
        """Return VBO with vertex positions"""

    def get_normal_buffer(self, mode) -> VBO:
        """Return VBO with vertex normals"""

    def get_texcoord_buffer(self, mode) -> VBO:
        """Return VBO with texture coordinates"""

    def get_color_buffer(self, mode) -> VBO:
        """Return VBO with vertex colors (if per-vertex coloring)"""

    def get_index_buffer(self, mode) -> Optional[VBO]:
        """Return index buffer for indexed drawing, or None"""

    def shader_render(self, mode, shader_program):
        """Render using the provided shader program"""
```

### Shape Node Updates

The Shape node will need parallel implementation to:

1. Detect whether shader-based or legacy rendering is active (via `mode` parameter)
2. Set up shader uniforms for material properties when in shader mode
3. Bind appropriate textures as texture samplers
4. Delegate to geometry node's shader rendering method

### Shader Requirements

**Primary Shaders:**

| Shader | Purpose |
|--------|---------|
| `vrml97_lighting.vert` | Vertex shader: transforms, normal matrix, pass-through to fragment |
| `vrml97_lighting.frag` | Fragment shader: VRML97 lighting model with all light types |
| `vrml97_textured.frag` | Fragment shader variant with texture sampling |
| `vrml97_unlit.vert/frag` | Simple unlit shader for selection/picking |

**Uniform Blocks:**

```glsl
// Material properties
uniform MaterialBlock {
    vec4 diffuseColor;
    vec4 specularColor;
    vec4 emissiveColor;
    float ambientIntensity;
    float shininess;
    float transparency;
};

// Light array (up to 8 lights)
uniform LightBlock {
    int lightType[8];        // 0=off, 1=directional, 2=point, 3=spot
    vec4 lightColor[8];
    vec4 lightPosition[8];   // w=0 for directional
    vec4 lightDirection[8];  // for directional and spot
    vec4 lightAttenuation[8]; // constant, linear, quadratic, unused
    vec2 lightSpotParams[8]; // cutoff angle, exponent
    int numLights;
};
```

### Texture Handling

Textures will need updates to work with texture samplers:

- `ImageTexture` nodes bind to sampler2D uniforms
- Texture coordinate generation modes (sphere map, etc.) implemented in vertex shader
- Multiple texture unit support for multi-texturing
- Texture transform matrix as uniform

```glsl
uniform sampler2D diffuseTexture;
uniform bool hasDiffuseTexture;
uniform mat3 textureTransform;
```

## Approach

1. Implement VRML97 lighting model in GLSL fragment shader
   - DirectionalLight, PointLight, SpotLight support
   - Material properties: diffuseColor, specularColor, emissiveColor, ambientIntensity, shininess, transparency
   - Per-vertex or per-fragment lighting calculations
2. Vertex shader handles standard transforms (modelview, projection, normal matrix)
3. Uniform blocks or UBOs for light and material parameters
4. Rendering pass collects active lights and materials from scenegraph, populates uniforms
5. Geometry nodes (Sphere, Box, IndexedFaceSet, etc.) render using VBOs with the shader program

## Challenges

- Multiple light support (VRML97 allows up to 8 lights typically)
- Texture coordinate generation modes (sphere mapping, etc.)
- Maintaining visual compatibility with fixed-function appearance
- Integration with existing RenderPass/RenderVisitor architecture
- Ensuring `flatcompat` continues working for existing clients

## Benefits

- Forward compatibility with OpenGL core profiles
- Foundation for adding modern rendering features (PBR, shadows, etc.)
- Better performance through batching and reduced state changes
- Enables rendering on platforms without fixed-function support

## Implementation Phases

1. **Infrastructure**: Create shader loading, uniform management, VBO protocol ✅
2. **Basic lighting**: Single directional light with diffuse/specular ✅
3. **Multi-light**: All VRML97 light types, up to 8 lights ✅
4. **Materials**: Full material model including transparency ✅
5. **Textures**: Texture sampling, texture transforms ✅
6. **Geometry nodes**: ShaderGeometryMixin and ShaderBox ✅
7. **Shape node**: ShaderShape and ShaderShapeMixin ✅
8. **Integration**: Selectable render path, comparison testing ✅

## Implementation Status: Integrated into FlatPass

The shader infrastructure is now integrated into the core rendering system:

### Core Infrastructure

- `OpenGLContext/passes/shaderpass.py` - VRML97ShaderProgram with full uniform management
- `OpenGLContext/shaders/vrml97_lighting.vert/frag` - GLSL 330 shaders with VRML97 lighting
- `OpenGLContext/shaders/vrml97_unlit.vert/frag` - Simple shaders for picking
- `OpenGLContext/scenegraph/shadergeometry.py` - Geometry protocol and Box implementation
- `OpenGLContext/scenegraph/shadershape.py` - Shader-aware Shape node
- `OpenGLContext/testing/framebuffer_comparison.py` - Reusable comparison testing

### FlatPass Integration ✅

- `OpenGLContext/passes/_flat.py` - Updated with shader-based rendering path
- `OpenGLContext/passes/flatcore.py` - Simplified to inherit from _flat.FlatPass
- Set `use_shaders=True` on FlatPass instances to enable shader rendering

### Command-line Support ✅

- `OpenGLContext/bin/vrml_view.py` - Added `--shaders` flag for shader mode
- Usage: `oglc-vrml --shaders myscene.wrl`

### Geometry Support ✅

All geometry types now support shader-based rendering:

- **Box** - Native VBO-based shader rendering
- **Sphere, Cone, Cylinder (Quadrics)** - VBO with indexed drawing
- **IndexedFaceSet** - Via ArrayGeometry with separate VBOs
- **ArrayGeometry** - Generic triangle arrays with separate VBOs
- **PointSet** - Points rendered with unlit shader
- **IndexedLineSet** - Line strips with unlit shader
- **Gear** - Generates triangle VBOs for shader rendering
- **GLE Extrusions (Lathe, Screw, Spiral)** - Fallback to legacy mode (GLE library limitation)

### Shape Node Integration ✅

Shape node now automatically detects shader mode and:

- Calls `configure_material_from_node` to set shader uniforms
- Binds textures to shader sampler
- Applies texture transforms
- Delegates to geometry's `_render_shader` method

### Test Suite ✅

Comprehensive test suite added:

- `tests/test_shader_comprehensive.py` - Multi-scene test with:
  - Multi-light scenarios (directional, point, spot)
  - Transparency rendering
  - All geometry types (Box, Sphere, Cone, Cylinder, Gear, IndexedFaceSet)
  - Points and lines (PointSet, IndexedLineSet)
  - Specular highlight variations
  - Emissive materials
  - Background rendering
- `tests/test_shader_textures.py` - Texture-specific tests:
  - RGB textures
  - RGBA textures with alpha
  - Texture repetition
  - Multiple textured objects
- `tests/test_shader_all_geometry.py` - Geometry type showcase

### Remaining Work

- Add texture coordinate generation modes (sphere mapping, etc.)
- Visual regression testing with saved reference images

### Future Enhancements

- **GLTF Support**: Add support for loading geometry and scenes from GLTF/GLB files.
  This would provide a modern, well-supported format for 3D content that works well
  with shader-based rendering. GLTF's PBR material model could be mapped to
  VRML97-compatible rendering or extended with a PBR shader path.

## Files to Create

- `OpenGLContext/shaders/vrml97_lighting.vert`
- `OpenGLContext/shaders/vrml97_lighting.frag`
- `OpenGLContext/shaders/vrml97_textured.frag`
- `OpenGLContext/shaders/vrml97_unlit.vert`
- `OpenGLContext/shaders/vrml97_unlit.frag`
- `OpenGLContext/scenegraph/shader_geometry.py` - Protocol and base classes
- `OpenGLContext/passes/shaderpass.py` - Shader-based rendering pass

## Files to Modify (add parallel shader support)

- `OpenGLContext/scenegraph/shape.py`
- `OpenGLContext/scenegraph/box.py`
- `OpenGLContext/scenegraph/quadrics.py`
- `OpenGLContext/scenegraph/indexedfaceset.py`
- `OpenGLContext/scenegraph/arraygeometry.py`
- `OpenGLContext/scenegraph/light.py`
- `OpenGLContext/scenegraph/material.py`
- `OpenGLContext/scenegraph/appearance.py`
- `OpenGLContext/scenegraph/imagetexture.py`
