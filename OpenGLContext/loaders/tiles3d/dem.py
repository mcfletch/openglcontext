"""Ingest a real heightmap (DEM) image into the terrain tileset baker.

Turns a grayscale elevation raster (PNG/TIFF/…, any format PIL reads) into a
world-space height function that the procedural baker meshes into a streamable 3D
Tiles quadtree. This is the real-world-data path: export a DEM from QGIS/USGS/SRTM to
a grayscale image and bake it. Bilinear sampling gives smooth terrain between texels;
positions outside the raster clamp to the edge.
"""
import numpy as np

from OpenGLContext.loaders.tiles3d.procedural import build_terrain_tileset


def height_function_from_array(heights, extent, height_scale, base=0.0):
    """A height_fn(x, z) sampling `heights` (H,W) bilinearly over [-extent/2, extent/2].

    `height_scale` maps the raster's 0..1 range to world metres; `base` offsets it.
    """
    heights = np.asarray(heights, dtype="d")
    h, w = heights.shape
    lo = -extent / 2.0

    def height_fn(x, z):
        x = np.asarray(x, dtype="d")
        z = np.asarray(z, dtype="d")
        # World -> texel coordinates (x -> column, z -> row), clamped to the raster.
        u = np.clip((x - lo) / extent * (w - 1), 0, w - 1)
        v = np.clip((z - lo) / extent * (h - 1), 0, h - 1)
        x0 = np.floor(u).astype(int)
        z0 = np.floor(v).astype(int)
        x1 = np.minimum(x0 + 1, w - 1)
        z1 = np.minimum(z0 + 1, h - 1)
        fx = u - x0
        fz = v - z0
        top = heights[z0, x0] * (1 - fx) + heights[z0, x1] * fx
        bot = heights[z1, x0] * (1 - fx) + heights[z1, x1] * fx
        return base + height_scale * (top * (1 - fz) + bot * fz)

    return height_fn


def height_function_from_image(path, extent, height_scale, base=0.0):
    """A world-space height_fn from a grayscale DEM image at `path`."""
    from PIL import Image
    img = Image.open(path).convert("F")
    arr = np.asarray(img, dtype="d")
    if arr.max() > 1.0:                     # 8/16-bit rasters -> normalise to 0..1
        arr = arr / arr.max()
    return height_function_from_array(arr, extent, height_scale, base=base)


def build_dem_tileset(image_path, directory, extent=2048.0, height_scale=400.0,
                      base=-40.0, levels=3, tile_res=33):
    """Bake a streamable terrain tileset from a DEM image; return tileset.json path.

    `base` below 0 lets low DEM areas fall under the water level so they read as lakes/
    sea, matching the procedural colouring.
    """
    height_fn = height_function_from_image(image_path, extent, height_scale, base)
    return build_terrain_tileset(directory, extent=extent, levels=levels,
                                 tile_res=tile_res, height_fn=height_fn)
