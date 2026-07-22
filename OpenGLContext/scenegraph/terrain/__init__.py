"""Authored large-scale game terrain: a height field plus a splat-textured node.

- :class:`HeightField` — the elevation grid you render and walk on (bilinear
  sampling, slope, mesh generation, baked sun/canopy shadow).
- :class:`SplatTerrain` — renders it as a runtime multi-layer splat terrain.

See :mod:`OpenGLContext.move.terrainwalk` for clamping a viewer to a HeightField.
"""
from OpenGLContext.scenegraph.terrain.heightfield import HeightField
from OpenGLContext.scenegraph.terrain.splat import SplatTerrain, DEFAULT_SUN

__all__ = ["HeightField", "SplatTerrain", "DEFAULT_SUN"]
