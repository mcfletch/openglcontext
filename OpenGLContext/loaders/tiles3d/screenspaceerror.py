"""Screen-space error for 3D Tiles refinement.

Converts a tile's geometric error (world units) into the pixel error it would
introduce if rendered at its current distance, using the standard perspective
relationship. Traversal refines a tile when this exceeds a pixel threshold.
"""
import math


def screen_space_error(
    geometric_error: float, distance: float, viewport_height: float, fovy: float
) -> float:
    """Pixel error for `geometric_error` seen at `distance` under a perspective camera.

    `fovy` is the vertical field of view in radians. A tile at or behind the camera
    (`distance <= 0`, i.e. the camera is inside its bounding volume) returns infinity
    so it always refines to maximum detail.
    """
    if distance <= 0.0:
        return math.inf
    sse_denominator = 2.0 * math.tan(0.5 * fovy)
    return (geometric_error * viewport_height) / (distance * sse_denominator)


def should_refine(sse: float, max_sse: float) -> bool:
    """True when a tile's screen-space error exceeds the pixel threshold.

    Equality renders the tile (does not refine), so `max_sse` is the largest error
    tolerated before descending into children.
    """
    return sse > max_sse
