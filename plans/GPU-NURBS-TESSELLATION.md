# GPU-Based NURBS Rendering via Tessellation Shaders

**Problem**: The current GLU-based NURBS tessellation is CPU-bound and slow, especially at finer tessellation levels. This makes animated NURBS surfaces impractical for real-time use.

**Proposed Solution**: Implement NURBS surface rendering using OpenGL 4.0+ tessellation shaders with `GL_PATCHES`.

## Approach

1. Pass control points to the GPU as patch primitives (`GL_PATCHES`)
2. Tessellation Control Shader (TCS) determines tessellation levels
   - Can be adaptive based on screen-space patch size
   - Allows dynamic LOD without CPU re-tessellation
3. Tessellation Evaluation Shader (TES) evaluates B-spline/NURBS basis functions
   - de Boor's algorithm or direct basis function computation in GLSL
   - Handles rational weights for true NURBS (not just B-splines)
4. Fragment shader handles shading as normal

## Challenges

- Trimming curves: May require a trim texture or parametric coordinate-based discard in fragment shader
- Integration with existing scenegraph architecture
- Fallback path for OpenGL < 4.0

## Benefits

- Much faster rendering, especially for animated surfaces
- Adaptive tessellation without CPU overhead
- Control points can be updated via uniforms or buffer updates for animation

## References

- OpenGL 4.0 Tessellation specification
- "GPU Gems 2" chapter on GPU-based NURBS
- Existing shader infrastructure in OpenGLContext
