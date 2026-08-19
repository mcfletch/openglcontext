"""Open water: the surface of a lake, a river or a sea.

Water is not ground of a different colour. Two things make it read as water and
a flat blue plate has neither:

**A shoreline comes from the ground, not from the water.** The shore is the line
where the land passes through the surface, so the terrain has to be meshed as it
actually is -- dipping under -- and the water laid over it. Clamping the ground
flat at the waterline and painting it blue removes the only thing that could
have drawn a shore.

**Water is dark and borrows its brightness.** Almost all of what a lake looks
like is the sky and the hills reflected in it, which is a question of *roughness*
rather than of colour: :func:`water_material` is nearly smooth, barely coloured,
and transparent enough to show the bed in the shallows.

    from OpenGLContext.scenegraph.water import water_surface
    sheet = water_surface(x0, x1, z0, z1, level=0.0)

The sheet is flat and its **normals** carry the ripple, which is what breaks the
specular highlight into the moving glitter a still picture reads as water.
Keeping the positions flat keeps the shoreline exactly where the waterline is.
The ripple is a function of where a point stands in the world, so two sheets
that meet agree along their seam and a world baked twice is the same world.

This is the runtime half, and it decides nothing. *Where* there is water -- which
is a question about the terrain -- is authoring, and lives with whatever builds
the world.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = ['WATER_ALBEDO', 'WATER_ROUGHNESS', 'WATER_TRANSPARENCY', 'WATER_IOR',
           'RIPPLE', 'RIPPLE_SCALE', 'water_material', 'water_surface']

#: Deep water's own colour, which is very little of what is seen: a lake is
#: mostly the sky in it. Dark, and green-blue rather than the postcard blue --
#: fresh water carries silt and weed, and a saturated blue reads as a swimming
#: pool. Very dark, because almost none of what is seen is this: a lake is the
#: sky and the hills in it, and a light albedo washes those out.
WATER_ALBEDO = (0.014, 0.042, 0.058)

#: How smooth it is. Not zero: a perfect mirror is glass, and even still water
#: has enough surface to spread a highlight.
WATER_ROUGHNESS = 0.06

#: How much is seen through it, and how much it bends what is behind. Little:
#: seen from above, water over a pale bed is the bed, and what makes it read as
#: water at all is that it is *darker* than the shore beside it. 1.33 is water's
#: own refractive index.
WATER_TRANSPARENCY = 0.10
WATER_IOR = 1.33

#: How far the ripple tilts the surface, in radians, and over how many metres it
#: repeats. A long, shallow swell rather than chop: what it is for is breaking
#: the highlight up, and a steep one reads as corrugated iron.
RIPPLE = 0.045
RIPPLE_SCALE = 11.0


def water_material() -> PBRMaterial:
    """What open water is made of.

    Smooth, so it reflects; barely coloured, so what it reflects is what is
    seen; transparent, so the bed shows through where it is shallow; and
    two-sided, because a car that has gone in is looking up at it.
    """
    return PBRMaterial(baseColor=WATER_ALBEDO, metallic=0.0,
                       roughness=WATER_ROUGHNESS,
                       transparency=WATER_TRANSPARENCY, alphaMode='BLEND',
                       ior=WATER_IOR, doubleSided=True)


def water_surface(x0: float, x1: float, z0: float, z1: float,
                  level: float = 0.0, resolution: int = 9,
                  ripple: float = RIPPLE,
                  material: Optional[PBRMaterial] = None) -> PBRMesh:
    """A flat sheet of water over a footprint, at ``level``.

    ``resolution`` is how many vertices across it is meshed at. It is a plane,
    so this is not about its shape: it is how finely the ripple in the normals
    is carried, and past a point a caller is paying for glitter nobody can see.

    ``ripple`` is how far the surface tilts, in radians; zero gives a mirror.
    """
    xs = np.linspace(float(x0), float(x1), max(2, int(resolution)))
    zs = np.linspace(float(z0), float(z1), max(2, int(resolution)))
    gx, gz = np.meshgrid(xs, zs, indexing='ij')
    positions = np.stack([gx, np.full_like(gx, float(level)), gz],
                         axis=-1).reshape(-1, 3)
    return PBRMesh(positions=positions.astype('f'),
                   normals=_ripple(gx, gz, float(ripple)),
                   indices=_grid(len(xs), len(zs)),
                   material=material if material is not None else water_material())


def _ripple(gx: np.ndarray, gz: np.ndarray, ripple: float) -> np.ndarray:
    """Normals for a swell, from where each point stands in the world.

    Two waves crossing at an angle, so the highlight breaks up rather than
    striping. Taken from world position rather than from position within the
    sheet, so sheets that meet agree along their seam.
    """
    if ripple <= 0.0:
        normals = np.zeros(gx.shape + (3,), dtype='d')
        normals[..., 1] = 1.0
        return normals.reshape(-1, 3).astype('f')
    first = 2.0 * np.pi / RIPPLE_SCALE
    second = 2.0 * np.pi / (RIPPLE_SCALE * 1.7)
    slope_x = (ripple * np.cos(first * (gx + 0.6 * gz))
               + ripple * 0.6 * np.cos(second * (gx - 1.3 * gz)))
    slope_z = (ripple * 0.6 * np.sin(first * (gx + 0.6 * gz))
               - ripple * np.sin(second * (gx - 1.3 * gz)))
    normals = np.stack([-slope_x, np.ones_like(gx), -slope_z], axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    return normals.reshape(-1, 3).astype('f')


def _grid(across: int, along: int) -> np.ndarray:
    """Triangles for a grid of vertices, wound so the sheet faces up."""
    rows, columns = np.meshgrid(np.arange(across - 1), np.arange(along - 1),
                                indexing='ij')
    corner = (rows * along + columns).ravel()
    quads = np.stack([corner, corner + along, corner + along + 1,
                      corner, corner + along + 1, corner + 1], axis=-1)
    return quads.reshape(-1).astype(np.uint32)


def bounds(x0: float, x1: float, z0: float, z1: float, level: float) -> Any:
    """The box a sheet of water occupies, for a caller that partitions space."""
    return ((min(x0, x1), level, min(z0, z1)), (max(x0, x1), level, max(z0, z1)))
