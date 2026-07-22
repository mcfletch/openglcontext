# Selection/Picking Optimization Plan

## Status: Complete (Phase 2 + Phase 3.2). Phase 3.1 optional/deferred.

The MRT object-ID approach shipped and was refactored out of `_flat.py` into a dedicated `OpenGLContext/passes/selection.py` (mixed into `FlatPass` via `SelectionMixin`). What landed:

- **`SelectionBufferFBO`** — MRT framebuffer with color + object-id + depth attachments.
- **O(1) pick resolution** — `processPickEventsFromBuffer` / `read_pixel(x, y)` read only the pixels under each pick point (better than the whole-buffer CPU copy sketched below), resolving via `id_map`. No per-pick GPU render pass.
- **`use_mrt_selection`** flag on `SelectionMixin`, wired into the forward render in `_flat.py`.
- **Fragment shaders emit object IDs** at `layout(location = 1)` — `vrml97_lighting`, `vrml97_unlit`, `vrml97_point`, `vrml97_vertex_color`, `vrml97_line`, `vrml97_background`, and `pbr`.
- **`set_object_id`** in `shaderpass.py`, made program-switch-safe (`_apply_object_id`) so point/line/unlit program switches still write the id.
- **Phase 3.2 async PBO readback — done** (`use_async_pick`): pooled pixel-pack buffers + `glFenceSync` + `glMapBufferRange`, ≤4 reads in flight. Config knob in `contextdefinition.py`.
- **Tests**: `test_mrt_draw_buffer_contract`, `test_unlit_shader_writes_id`, `test_object_id_blend`, `test_async_pick_gl`, `test_pick_persist_ids`, `test_click_through_gl`, `test_unlit_pickable_gl`, `test_pickable_flag`, plus instanced-id tests.

**Not done (intentionally):** Phase 3.1 hierarchical BVH selection — the plan lists it as an optional future step for 10,000+ object scenes; not needed given the async MRT path's ~O(1) per-pick cost.

The original Phase 1/2 write-up follows for reference.

---

**See [SELECTION-OPTIMIZATION-RESULTS.md](SELECTION-OPTIMIZATION-RESULTS.md) for Phase 1 implementation details.**

Phase 1 (screen-space bbox culling) achieved ~20% improvement in synthetic benchmarks but real-world interactive use still felt slow due to per-pick-point GPU rendering and synchronous glReadPixels stalls.

**Phase 2 implements a fundamentally different approach: Multiple Render Targets (MRT) to render object IDs alongside the normal scene, eliminating all per-pick GPU work.**

## Scope

**Focus on flatcore.py** - The core profile renderer is the target default, so optimization efforts should focus there. Legacy flatcompat.py selection will remain as-is for compatibility profile users.

## Problem Statement

The current selection/picking implementation has two key issues:

1. **First-pick latency**: The first pick event triggers a separate selection render pass which causes a noticeable delay (~0.5 seconds)
2. **Event queue accumulation**: Rapid clicking overwhelms the system because each pick triggers GPU work and synchronous readback

Even with Phase 1 optimizations (screen-space bbox culling), the fundamental problem remains: **each pick event causes GPU pipeline stalls**.

## Phase 2: MRT-Based Selection Buffer (Current Implementation)

### Approach

Render a full-resolution object ID buffer alongside the normal color buffer during the forward rendering pass using Multiple Render Targets (MRT). This eliminates all per-pick GPU work.

### How It Works

1. **During forward render**: Use MRT to render both:
   - Color attachment 0: Normal scene color (as today)
   - Color attachment 1: Object ID encoded as color (R16G16 for 32-bit IDs)

2. **After frame completes**: Single `glReadPixels` to read the entire ID buffer to CPU memory

3. **Pick event handling**: Simple array lookup: `id = buffer[y * width + x]`
   - No GPU rendering
   - No pipeline stalls
   - O(1) per pick point

### Key Benefits

- **Zero per-pick GPU overhead**: Pick events are pure CPU array lookups
- **No additional render passes**: ID buffer rendered during forward pass
- **Full resolution**: No aliasing or edge ambiguity
- **One-frame latency**: Acceptable for interactive use (buffer shows previous frame's state)
- **Excellent scaling**: 1000 picks costs the same as 1 pick

### Memory Cost

- Full-res RGBA8 texture: 1920x1080 = ~8MB
- Acceptable for modern systems

### Implementation Details

#### Files to Modify

1. **OpenGLContext/passes/_flat.py**
   - Add `SelectionBufferFBO` class for MRT framebuffer
   - Modify `Render()` to bind MRT FBO during forward pass
   - Add buffer readback after frame
   - Replace `shaderSelectRenderOptimized()` with buffer lookup

2. **OpenGLContext/shaders/vrml97_lighting.frag**
   - Add second output for object ID: `layout(location = 1) out vec4 objectId;`
   - Output unique color ID per object

3. **OpenGLContext/shaders/vrml97_unlit.frag** (and other shaders)
   - Same MRT output changes

4. **OpenGLContext/passes/shaderpass.py**
   - Add `set_object_id()` method to pass object ID to shaders

#### FBO Setup

```python
class SelectionBufferFBO:
    """Full-resolution selection buffer using MRT."""

    def __init__(self):
        self.fbo = None
        self.color_texture = None      # Normal scene color
        self.id_texture = None         # Object ID buffer
        self.depth_renderbuffer = None
        self.id_buffer = None          # CPU-side numpy array
        self.width = 0
        self.height = 0
```

#### Shader Changes

```glsl
// Fragment shader additions
uniform uint objectId;  // Set per-object during rendering

layout(location = 0) out vec4 fragColor;
layout(location = 1) out vec4 fragObjectId;

void main() {
    // ... existing lighting calculations ...
    fragColor = vec4(finalColor, alpha);

    // Output object ID (encoded as RGBA)
    fragObjectId = vec4(
        float((objectId >> 0) & 0xFFu) / 255.0,
        float((objectId >> 8) & 0xFFu) / 255.0,
        float((objectId >> 16) & 0xFFu) / 255.0,
        float((objectId >> 24) & 0xFFu) / 255.0
    );
}
```

#### Pick Event Processing

```python
def processPickEvents(self, events, id_buffer, width, id_map):
    """Process pick events using cached ID buffer."""
    for event in events.values():
        x, y = event.getPickPoint()
        x, y = int(x), int(y)

        if 0 <= x < width and 0 <= y < len(id_buffer) // width:
            # Direct array lookup - no GPU work
            pixel_offset = (y * width + x) * 4
            r, g, b, a = id_buffer[pixel_offset:pixel_offset+4]
            object_id = r | (g << 8) | (b << 16) | (a << 24)
            path = id_map.get(object_id, [])
            event.setObjectPaths([path])
        else:
            event.setObjectPaths([[]])
```

## Performance Targets

| Metric | Phase 1 | Phase 2 Target |
|--------|---------|----------------|
| First-pick latency | ~500ms | <16ms (one frame) |
| Per-pick overhead | ~0.2-0.9ms | <0.001ms |
| 100 picks/frame | 20ms | ~0ms |
| Memory overhead | ~1MB | ~8MB |

## Previous Approaches (Phase 1)

### Phase 1.1: Screen-Space BBox Culling (Implemented)

- Pre-compute screen-space bounding boxes for all objects
- For each pick point, filter to objects whose bbox contains the point
- Render only candidate objects to tiny FBO
- **Result**: ~20% improvement in synthetic benchmarks, but still too slow for interactive use

### Why Phase 1 Wasn't Enough

The fundamental problem is **per-pick GPU work**:
- Each pick point still requires: bind FBO → render candidates → glReadPixels
- `glReadPixels` causes GPU pipeline stall every time
- First pick has cold-start overhead
- Rapid clicks queue up, causing visible lag

## Future Optimization Opportunities (Phase 3)

If MRT approach proves insufficient for very large scenes:

### 3.1 Hierarchical Selection with BVH
- Build spatial index over screen-space bboxes
- O(log n) candidate lookup instead of O(n)
- Would help with 10,000+ objects

### 3.2 Async Buffer Readback with PBO
- Use Pixel Buffer Objects for async readback
- Avoids single-frame pipeline stall
- Returns two-frame-old data (usually acceptable)

## Testing Strategy

1. **Functional testing**: `tests/selectrendermode.py` for interactive validation
2. **Performance testing**: `tests/test_selection_benchmark.py` for measurements
3. **Edge cases**: Background clicks, rapid clicking, screen edge picks

## References

- [OpenGL MRT Tutorial](https://learnopengl.com/Advanced-Lighting/Deferred-Shading)
- [GPU Gems: Deferred Shading](https://developer.nvidia.com/gpugems/gpugems2/part-ii-shading-lighting-and-shadows/chapter-9-deferred-shading-tabula-rasa)
- [glReadPixels Performance](https://www.khronos.org/opengl/wiki/Pixel_Transfer#Pixel_Buffer_Object)
