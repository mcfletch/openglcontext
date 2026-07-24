"""Bounding volumes for 3D Tiles tiles, in world space.

Each provides `distance_to(point)` — the distance from a point to the nearest
surface, zero when the point is inside — which feeds screen-space error, and a
`center`. Sphere, oriented-box and geodetic-region (the 3D Tiles `sphere`, `box`
and `region` volumes) are supported; all are stored already in the renderer's
world frame.
"""
from collections.abc import Sequence
from typing import Any, Optional

import numpy as np

# WGS 84 ellipsoid, the datum EPSG:4979 region volumes are expressed against.
WGS84_A = 6378137.0                     # semi-major axis (equatorial), metres
_WGS84_F = 1.0 / 298.257223563          # flattening
WGS84_B = WGS84_A * (1.0 - _WGS84_F)    # semi-minor axis (polar), metres
_WGS84_E2 = 1.0 - (WGS84_B / WGS84_A) ** 2   # first eccentricity squared


def geodetic_to_ecef(longitude: Any, latitude: Any, height: Any) -> np.ndarray:
    """Convert geodetic (lon, lat in radians; height in metres) to ECEF metres.

    Earth-Centered, Earth-Fixed Cartesian coordinates on the WGS 84 ellipsoid:
    +X toward (lon 0, lat 0), +Z toward the north pole. This is the frame glTF
    tile content lives in once a region tileset's tiles are placed.
    """
    sin_lat = np.sin(latitude)
    cos_lat = np.cos(latitude)
    n = WGS84_A / np.sqrt(1.0 - _WGS84_E2 * sin_lat * sin_lat)
    x = (n + height) * cos_lat * np.cos(longitude)
    y = (n + height) * cos_lat * np.sin(longitude)
    z = (n * (1.0 - _WGS84_E2) + height) * sin_lat
    return np.array([x, y, z], dtype="d")


class SphereBV:
    """World-space bounding sphere (`center`, `radius`)."""

    def __init__(self, center: Any, radius: float) -> None:
        self.center = np.asarray(center, dtype="d")
        self.radius = float(radius)

    def distance_to(self, point: Any) -> float:
        d = np.linalg.norm(np.asarray(point, dtype="d") - self.center)
        return max(0.0, float(d) - self.radius)

    def bounding_sphere(self) -> tuple[np.ndarray, float]:
        return self.center, self.radius


class BoxBV:
    """World-space oriented bounding box.

    `half_axes` is three vectors (the 3D Tiles `box` X/Y/Z half-axes): each points
    along a box axis and its length is that axis's half-extent. Distance projects
    the offset onto each unit axis and accumulates the per-axis overshoot.
    """

    def __init__(self, center: Any, half_axes: Any) -> None:
        self.center = np.asarray(center, dtype="d")
        axes = np.asarray(half_axes, dtype="d")
        self._half = np.linalg.norm(axes, axis=1)
        # Unit axis directions; guard against a degenerate (zero-length) axis.
        with np.errstate(invalid="ignore", divide="ignore"):
            self._dirs = np.where(
                self._half[:, None] > 0, axes / self._half[:, None], 0.0
            )

    def distance_to(self, point: Any) -> float:
        d = np.asarray(point, dtype="d") - self.center
        proj = self._dirs @ d
        excess = np.maximum(0.0, np.abs(proj) - self._half)
        return float(np.linalg.norm(excess))

    def bounding_sphere(self) -> tuple[np.ndarray, float]:
        # Enclosing sphere: centre of the box, radius to the far corner.
        return self.center, float(np.linalg.norm(self._half))


class RegionBV:
    """A geodetic `region` volume `[west, south, east, north, minH, maxH]`.

    Longitudes/latitudes are radians, heights metres. Per the 3D Tiles spec a
    region is fixed to the WGS 84 datum and is *not* affected by the tile
    transform, so we convert it straight to ECEF here. We enclose the region in a
    sphere sampled over its boundary — conservative but cheap, which is all the
    screen-space-error distance needs. `offset` (an ECEF point) is subtracted so a
    recentred tileset renders near the origin instead of ~6.4 million metres out.
    """

    def __init__(self, region: Sequence[float], offset: Optional[Any] = None) -> None:
        west, south, east, north, min_h, max_h = (float(v) for v in region)
        offset = np.zeros(3, dtype="d") if offset is None else np.asarray(offset, "d")
        lons = np.linspace(west, east, 3)
        lats = np.linspace(south, north, 3)
        corners = [
            geodetic_to_ecef(lon, lat, h) - offset
            for lon in lons for lat in lats for h in (min_h, max_h)
        ]
        pts = np.asarray(corners, dtype="d")
        self.center = pts.mean(axis=0)
        self.radius = float(np.linalg.norm(pts - self.center, axis=1).max())

    def distance_to(self, point: Any) -> float:
        d = np.linalg.norm(np.asarray(point, dtype="d") - self.center)
        return max(0.0, float(d) - self.radius)

    def bounding_sphere(self) -> tuple[np.ndarray, float]:
        return self.center, self.radius

    def ecef_center(self) -> np.ndarray:
        """The un-offset ECEF centre, used to pick a recenter origin."""
        return self.center
