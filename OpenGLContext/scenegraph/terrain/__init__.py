"""Authored large-scale game terrain: a height field plus a splat-textured node.

- :class:`HeightField` — the elevation grid you render and walk on (bilinear
  sampling, slope, mesh generation, baked sun/canopy shadow). Built from an
  image, or from the height function a landscape is authored as.
- :class:`SplatTerrain` — renders it as a runtime multi-layer splat terrain.
- :class:`LayerRule` and :func:`control_map` — which of the splat's materials
  shows where, derived from the land's own elevation and steepness.

See :mod:`OpenGLContext.move.terrainwalk` for clamping a viewer to a HeightField.
"""
from OpenGLContext.scenegraph.terrain.control import LayerRule, control_map
from OpenGLContext.scenegraph.terrain.heightfield import HeightField
from OpenGLContext.scenegraph.terrain.splat import SplatTerrain, DEFAULT_SUN

__all__ = ["HeightField", "SplatTerrain", "DEFAULT_SUN", "LayerRule",
           "control_map"]
