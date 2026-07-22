# Selection/Picking Optimization Results

## Status: Implemented

This document summarizes the performance improvements achieved by optimizing the selection/picking system in OpenGLContext's core profile renderer.

## Implementation Summary

The optimized selection system uses a **screen-space bounding box culling** approach:

1. **Pre-compute screen-space bounding boxes** for all objects once per frame
   - Project each object's 3D bounding volume corners to screen coordinates
   - Compute 2D bounding box from projected points

2. **Per-pick-point processing**
   - For each pick point, find objects whose screen bbox contains the point (simple 2D point-in-rect test)
   - Render only those few candidate objects (typically 1-10) to a tiny 3x3 FBO
   - Read back the single center pixel to identify the selected object

3. **FBO-based rendering** for reduced pixel fill
   - Uses small FBO instead of full framebuffer
   - Pick projection matrix zooms into the pick region

## Performance Results

### Test Configuration
- Platform: Linux 6.8.0 (GLFW backend, Core profile)
- Test: `tests/test_selection_benchmark.py`
- Geometry: Grid of Box nodes with varying counts

### Benchmark Results

| Objects | Events | Baseline (ms) | Optimized (ms) | Improvement |
|---------|--------|---------------|----------------|-------------|
| 1000    | 0      | 91            | 91             | (no selection) |
| 1000    | 10     | 124           | 100            | **20%** |
| 1000    | 100    | N/A           | 111            | Excellent scaling |
| 100     | 50     | N/A           | 17             | 59 FPS |

### Key Findings

1. **Per-event overhead is minimal**: With 100 events, total overhead is only 20ms (~0.2ms/event)
2. **Screen-space bbox computation amortizes well**: Done once per frame, benefits all pick events
3. **Point-in-rect tests are very fast**: O(n) objects but simple integer comparisons
4. **Candidate rendering is the main cost**: Each pick point renders 0-10 objects typically

### Overhead Analysis (1000 objects)

| Metric | Value |
|--------|-------|
| Base render time (no selection) | 91 ms |
| With 10 pick events | 100 ms (9 ms overhead) |
| With 100 pick events | 111 ms (20 ms overhead) |
| Per-event overhead (10 events) | 0.9 ms |
| Per-event overhead (100 events) | 0.2 ms |

## Implementation Details

### Files Modified

- **OpenGLContext/passes/_flat.py**
  - Added `SelectionFBO` class for FBO-based rendering
  - Added `_computeScreenSpaceBBoxes()` for screen-space projection
  - Rewrote `shaderSelectRenderOptimized()` with per-point processing
  - Added `_createPickProjection()` for pick matrix generation
  - Added `_createPickFrustum()` (used by legacy path)

### Algorithm

```
1. Collect all pick points from events
2. Compute screen-space bboxes for all objects (ONCE per frame)
   - For each object: project bbox corners -> compute 2D AABB
3. For each unique pick point:
   a. Filter: objects where bbox contains point (O(n) point-in-rect tests)
   b. If no candidates, set empty result
   c. Else:
      - Bind tiny FBO (3x3 pixels)
      - Render only candidate objects with unique color IDs
      - Read back center pixel
      - Map color to object path
4. Dispatch events to handlers
```

## Comparison with Alternative Approaches

| Approach | Implementation Status | Performance |
|----------|----------------------|-------------|
| Full scene re-render | Original | 124 ms (baseline) |
| Frustum-based per-pick | Attempted | 235 ms (slower!) |
| Ray-AABB intersection | Attempted | 108 ms (13% better) |
| **Screen-space bbox** | **Final** | **100 ms (20% better)** |

The frustum-based approach was slower because creating a Frustum per pick point and calling `bvolume.visible()` involves significant matrix operations per object.

## Future Optimization Opportunities

### Not Implemented (Potential Phase 2)

1. **Hierarchical Selection** (Phase 2.1 from plan)
   - Build BVH over screen-space bboxes
   - O(log n) candidate search instead of O(n)
   - Would help with 10,000+ objects

2. **Occlusion Queries** (Phase 3.3 from plan)
   - Use GPU occlusion queries instead of pixel readback
   - Async results, no pipeline stalls
   - Requires more complex state management

3. **Compute Shader Selection** (Phase 3.2 from plan)
   - Parallel ray-object intersection on GPU
   - Best for very large object counts

### Recommendations

For typical scenes (100-1000 objects):
- Current screen-space bbox approach is sufficient
- 20% improvement over baseline
- Excellent scaling with event count

For very large scenes (10,000+ objects):
- Consider implementing hierarchical selection (BVH)
- Would provide O(log n) instead of O(n) culling

## Test Files

- `tests/test_selection_benchmark.py` - Performance benchmark
- Benchmark results saved to `tests/benchmark_results/`
