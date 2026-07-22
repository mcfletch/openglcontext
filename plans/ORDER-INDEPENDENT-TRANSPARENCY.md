# Order-Independent Transparency (OIT) Plan

## Status: Planned

## Problem Statement

The current transparency implementation uses simple back-to-front depth sorting, which produces visual artifacts when:

- Transparent objects intersect each other
- Objects have complex concave geometry
- Multiple transparent layers overlap at different depths within the same object
- Camera angle causes sorting order to be incorrect for some triangles

These artifacts appear as incorrect blending, "popping" when objects move, and visible seams where transparent surfaces meet.

## Current Implementation Analysis

### How Transparency Works Now

The current system in `_flat.py` and `flatcompat.py`:

1. **Depth Sorting**: Objects are sorted by distance from camera (bounding volume center)
2. **Two-Pass Rendering**:
   - First pass: Render opaque geometry with depth write enabled
   - Second pass: Render transparent geometry back-to-front with depth write disabled
3. **Simple Blending**: Uses `GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA` blending

### Limitations

- **Object-level sorting only**: Sorting is per-object, not per-triangle
- **No intra-object handling**: A single transparent object cannot correctly blend with itself
- **Intersecting objects fail**: Two intersecting transparent objects will always have artifacts
- **View-dependent errors**: Sorting based on center point fails for large or elongated objects

### Relevant Code Locations

- `OpenGLContext/passes/_flat.py:FlatPass.Render()` - Opaque/transparent pass separation
- `OpenGLContext/passes/flatcompat.py:renderTransparent()` - Legacy transparent rendering
- `OpenGLContext/passes/flatcore.py` - Core profile (needs OIT support)

## Proposed Solutions

### Option 1: Weighted Blended Order-Independent Transparency (WBOIT)

**Recommended for initial implementation**

A single-pass technique that approximates correct transparency without sorting.

#### How it works:
1. Render transparent geometry to two render targets:
   - Accumulation buffer: Premultiplied color weighted by depth
   - Revealage buffer: Product of (1 - alpha) values
2. Composite pass combines accumulation with background

#### Pros:
- Single geometry pass (fast)
- No sorting required
- Handles intersecting geometry correctly
- Works with any number of overlapping layers
- Moderate GPU memory overhead

#### Cons:
- Approximation - not physically accurate
- Can have issues with very high or very low alpha values
- Color bleeding at extreme depth differences

#### Implementation Requirements:
- Two additional render targets (RGBA16F or RGBA32F)
- Composite shader for final pass
- FBO setup for multi-render-target output

### Option 2: Depth Peeling

A multi-pass technique that renders layers front-to-back or back-to-front.

#### How it works:
1. Render frontmost transparent layer
2. Render next layer (fragments behind first)
3. Repeat for N layers
4. Composite all layers

#### Pros:
- Exact results (no approximation)
- Predictable quality based on layer count

#### Cons:
- Multiple geometry passes (slow for high layer counts)
- Fixed maximum layer count
- Complex FBO ping-pong setup

### Option 3: Per-Pixel Linked Lists (A-Buffer)

GPU-based linked list storing all fragments per pixel.

#### How it works:
1. Render transparent geometry, storing all fragments in GPU linked lists
2. Sort and composite fragments per-pixel in a compute/fragment shader

#### Pros:
- Exact results
- Handles unlimited layers
- Single geometry pass

#### Cons:
- Requires OpenGL 4.2+ (shader storage buffers, atomic counters)
- High memory usage for complex scenes
- Complex implementation

## Recommended Implementation: WBOIT

### Phase 1: Core Infrastructure

#### 1.1 FBO Management
- Create FBO with multiple color attachments for accumulation and revealage
- Handle resize and format selection

#### 1.2 Shader Modifications
- Modify `vrml97_lighting.frag` to output to multiple render targets when in OIT mode
- Create composite shader for final pass

#### 1.3 Render Pass Changes
- Add OIT accumulation pass to FlatPass
- Add composite pass after transparent rendering

### Phase 2: Shader Implementation

#### 2.1 OIT Fragment Shader Output

```glsl
// In transparent pass
layout(location = 0) out vec4 accumulation;
layout(location = 1) out float revealage;

void main() {
    vec4 color = /* standard lighting calculation */;

    // Weight function based on depth and alpha
    float weight = clamp(pow(min(1.0, color.a * 10.0) + 0.01, 3.0) *
                         1e8 * pow(1.0 - gl_FragCoord.z * 0.9, 3.0), 1e-2, 3e3);

    accumulation = vec4(color.rgb * color.a, color.a) * weight;
    revealage = color.a;
}
```

#### 2.2 Composite Shader

```glsl
void main() {
    vec4 accum = texture(accumTexture, texCoord);
    float reveal = texture(revealTexture, texCoord).r;

    // Avoid division by zero
    vec3 averageColor = accum.rgb / max(accum.a, 1e-5);

    fragColor = vec4(averageColor, 1.0 - reveal);
}
```

### Phase 3: Integration

#### 3.1 Mode Selection
- Add `oit_mode` option to context definition
- Allow runtime switching between sorted and OIT transparency

#### 3.2 Fallback
- Detect if hardware supports required features
- Fall back to depth-sorted transparency on older hardware

## Implementation Checklist

- [ ] Create FBO class for OIT buffers
- [ ] Add OIT output to vrml97_lighting.frag
- [ ] Create vrml97_oit_composite.frag shader
- [ ] Modify FlatPass to use OIT when enabled
- [ ] Add oit_mode to ContextDefinition
- [ ] Test with transparency test scenes
- [ ] Performance benchmarking
- [ ] Documentation

## Files to Modify/Create

### New Files
- `OpenGLContext/shaders/vrml97_oit_composite.vert` - Simple fullscreen quad
- `OpenGLContext/shaders/vrml97_oit_composite.frag` - OIT compositing
- `OpenGLContext/passes/oit.py` - OIT buffer management

### Modified Files
- `OpenGLContext/shaders/vrml97_lighting.frag` - Add OIT output mode
- `OpenGLContext/passes/_flat.py` - OIT pass integration
- `OpenGLContext/passes/shaderpass.py` - OIT shader compilation
- `OpenGLContext/contextdefinition.py` - Add oit_mode option

## Performance Considerations

| Aspect | Sorted Transparency | WBOIT |
|--------|---------------------|-------|
| Geometry passes | 1 | 1 |
| Fill rate | 1x | 2x (two render targets) |
| Memory | None | ~16 bytes/pixel |
| CPU sorting | Required | None |
| Quality | View-dependent artifacts | Approximate but consistent |

Expected overhead: 10-30% increase in transparent rendering time, but eliminates CPU sorting cost and artifacts.

## Testing Strategy

1. Create test scenes with:
   - Overlapping transparent spheres
   - Intersecting transparent boxes
   - Complex transparent meshes
2. Compare visual results with reference images
3. Verify no artifacts at any camera angle
4. Performance comparison with sorted transparency

## Dependencies

- Requires core profile support (CORE-PROFILE-COMPATIBILITY)
- Requires FBO support (standard in OpenGL 3.0+)
- WBOIT requires floating-point render targets (RGBA16F)

## References

- [Weighted Blended OIT (McGuire & Bavoil 2013)](http://jcgt.org/published/0002/02/09/)
- [OpenGL Insights: Order-Independent Transparency](http://openglinsights.com/)
- [NVIDIA GameWorks: Order-Independent Transparency](https://developer.nvidia.com/content/transparency-or-translucency-rendering)
- [LearnOpenGL: OIT](https://learnopengl.com/Guest-Articles/2020/OIT/Introduction)
