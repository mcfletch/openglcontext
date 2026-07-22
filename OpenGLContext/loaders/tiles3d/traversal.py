"""Camera-driven traversal of a runtime tileset.

Each frame `select_tiles` walks the bounding-volume hierarchy, converting geometric
error to screen-space error against the camera, and returns the tiles to render plus
the tiles to keep resident. Streaming is what these two sets *decide*: the want set
drives loads, and residency evicts anything no longer wanted.

Refinement follows the 3D Tiles rule: a tile refines when its screen-space error
exceeds the pixel threshold and it has children. REPLACE refinement hides the parent
(children stand in for it); ADD keeps the parent and layers children on top. The want
set is the render set unioned with a deeper selection at a lower (prefetch) threshold,
so finer tiles the camera is approaching load before they are strictly needed while
the coarse ancestor stays resident as a fallback.
"""
from OpenGLContext.loaders.tiles3d.screenspaceerror import (
    screen_space_error,
    should_refine,
)


class SelectionResult:
    """Outcome of one traversal: `render` (draw list) and `want` (keep-resident set)."""

    def __init__(self, render, want):
        self.render = render
        self.want = want


def _select(tile, camera, viewport_height, fovy, max_sse, visible, out,
            hysteresis, refined_state):
    if visible is not None and not visible(tile):
        return
    distance = tile.bounding_volume.distance_to(camera)
    sse = screen_space_error(tile.geometric_error, distance, viewport_height, fovy)
    if tile.children:
        # Sticky refinement: a tile already refined last frame keeps refining until
        # its error drops below a lower band, so LOD does not flicker at the threshold.
        threshold = max_sse
        if (refined_state is not None and hysteresis > 0.0
                and refined_state.get(id(tile))):
            threshold = max_sse * (1.0 - hysteresis)
        refine = should_refine(sse, threshold)
        if refined_state is not None:
            refined_state[id(tile)] = refine
    else:
        refine = False
    if not refine:
        if tile.has_content:
            out.append(tile)
        return
    if tile.refine == "ADD" and tile.has_content:
        out.append(tile)
    for child in tile.children:
        _select(child, camera, viewport_height, fovy, max_sse, visible, out,
                hysteresis, refined_state)


def select_tiles(tileset, camera, viewport_height, fovy, max_sse,
                 prefetch_factor=1.0, visible=None,
                 hysteresis=0.0, refined_state=None):
    """Select render and want sets for `tileset` from `camera`.

    `prefetch_factor` >= 1 lowers the effective threshold for the want set
    (`max_sse / prefetch_factor`), so a factor above 1 speculatively pulls in finer
    tiles than are currently rendered. `visible`, if given, is a predicate used to
    prune whole subtrees (frustum culling). `hysteresis` (0..1) with a persistent
    `refined_state` dict makes refinement sticky across frames to prevent LOD flicker;
    only the render traversal updates that state (the prefetch pass does not).
    """
    render = []
    _select(tileset.root, camera, viewport_height, fovy, max_sse, visible, render,
            hysteresis, refined_state)
    if prefetch_factor <= 1.0:
        return SelectionResult(render=render, want=list(render))
    deep = []
    _select(tileset.root, camera, viewport_height, fovy,
            max_sse / prefetch_factor, visible, deep, 0.0, None)
    seen = {id(t) for t in render}
    want = list(render)
    want.extend(t for t in deep if id(t) not in seen)
    return SelectionResult(render=render, want=want)
