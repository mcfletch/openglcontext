"""A grid of baked irradiance, for lighting the things a lightmap cannot.

A lightmap records the light arriving on the surfaces that existed when the
world was built, addressed by a texture coordinate those surfaces carry.
Anything that arrives afterwards -- a character, a pickup, a projectile, a door
-- has no such coordinate, so a scene lit that way has nothing to light it with
and it draws black.

The answer the baked-lighting workflow uses is a second, coarser record of the
same solution: a regular grid of samples over the world, each one saying how
much light arrives at that point and from which way.  An object is lit by
looking its own position up in the grid, which costs one interpolation per
object per frame and needs nothing of the object but where it is.

Each sample holds two terms because one is not enough to shade with: an
``ambient`` irradiance that arrives from every direction, and a
``directional`` one arriving from ``direction``.  A figure lit by the ambient
term alone is a silhouette in a flat colour; the directional term is what puts
a lit side and a shaded side on it.

Sampling is trilinear and clamps at the edges, so an object that walks out
past the last sample keeps the light of the nearest one instead of falling
dark.  The samples are held as flat arrays indexed with x varying fastest::

    index = ix + counts[0] * (iy + counts[1] * iz)

Who fills it in: a loader that has a baked grid to convert (see
:mod:`twig_bb.lighting` for the Quake 3 one).  Who reads it: the PBR render
pass, which finds the node in the scenegraph and lights each object that
carries no lightmap of its own with it -- see
:mod:`OpenGLContext.passes.pbrpass` and ``docs/pbr.html``.
"""
from typing import Any, List, Optional, Tuple

import numpy as np
from vrml import field, node
from vrml.vrml97 import nodetypes

__all__ = ['LightGrid', 'bound_grid']


class LightGrid(nodetypes.Children, node.Node):
    """A regular grid of baked irradiance covering the world.

    ``origin`` is the world-space position of sample (0, 0, 0) and ``spacing``
    the distance between neighbouring samples along each axis, so the grid
    covers ``origin`` to ``origin + spacing * (counts - 1)``.  It is axis
    aligned: a loader whose file uses different axes puts the samples into
    these before it builds the node, since a grid that had to be rotated on
    every lookup would pay for the rotation once per object per frame.

    ``intensity`` scales every sample as it is read, which is the same knob
    :attr:`PBRMaterial.lightmapStrength` is for the surfaces: a baked solution
    is in whatever units its compiler wrote, and matching the two is the
    caller's business rather than the file's.
    """
    PROTO = 'LightGrid'

    #: World-space position of sample (0, 0, 0).
    origin = field.newField('origin', 'SFVec3f', 1, (0.0, 0.0, 0.0))
    #: Distance between neighbouring samples along x, y and z.
    spacing = field.newField('spacing', 'SFVec3f', 1, (1.0, 1.0, 1.0))
    #: How many samples there are along x, y and z.
    counts = field.newField('counts', 'MFInt32', 1, list)

    #: Linear irradiance arriving at each sample from every direction.
    ambient = field.newField('ambient', 'MFColor', 1, list)
    #: Linear irradiance arriving at each sample from :attr:`direction`.
    directional = field.newField('directional', 'MFColor', 1, list)
    #: Unit vector at each sample pointing *towards* the light.
    direction = field.newField('direction', 'MFVec3f', 1, list)

    #: Multiplier applied to both irradiance terms as they are read.
    intensity = field.newField('intensity', 'SFFloat', 1, 1.0)

    #: Where a sample says nothing about which way the light came from --
    #: an empty grid, or one whose stored direction interpolated to zero
    #: between two samples pointing opposite ways.  Up, because a baked world
    #: is lit from above far more often than from anywhere else, and because a
    #: direction has to be *some* unit vector for the shading to be defined.
    DEFAULT_DIRECTION = (0.0, 1.0, 0.0)

    @property
    def filled(self) -> bool:
        """Whether there is anything here to light with.

        A node with no samples is not an error -- a map may simply have no
        baked grid -- so the pass asks this once a frame rather than sampling
        a grid that would answer black for every object in the scene.
        """
        shape = self.shape
        if not shape:
            return False
        return len(self.ambient) >= shape[0] * shape[1] * shape[2]

    @property
    def shape(self) -> Tuple[int, ...]:
        """``counts`` as a tuple of three ints, or ``()`` if it is not three."""
        counts = self.counts
        if len(counts) != 3:
            return ()
        found = (int(counts[0]), int(counts[1]), int(counts[2]))
        return () if min(found) < 1 else found

    def cell(self, point: Any,
             counts: Optional[Tuple[int, ...]] = None
             ) -> Tuple[float, float, float]:
        """Where ``point`` falls in the grid, in samples rather than metres.

        Clamped to the grid, so a point outside it lands on the boundary and
        is lit by the nearest samples: an object that steps past the last one
        keeps the light it had rather than going dark at an invisible line.

        ``counts`` is :attr:`shape`, for a caller that has already read it.
        """
        if counts is None:
            counts = self.shape
        origin = self.origin
        spacing = self.spacing
        found = []
        for axis in range(3):
            step = float(spacing[axis])
            # A zero spacing is a grid of no extent along that axis: every
            # point lies on the first sample, and dividing by it says nothing.
            if step == 0.0:
                found.append(0.0)
                continue
            limit = float(counts[axis] - 1) if counts else 0.0
            value = (float(point[axis]) - float(origin[axis])) / step
            found.append(min(max(value, 0.0), limit))
        return (found[0], found[1], found[2])

    def sample(self, point: Any) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The light at ``point``, as (ambient, directional, direction).

        The two irradiances are linear colours scaled by :attr:`intensity`;
        the direction is a unit vector pointing towards the light.  An empty
        grid answers black light from :attr:`DEFAULT_DIRECTION`, so a caller
        never has to special-case one.

        Written in scalars down to the three array reads because it is called
        once per lit object per frame: the same arithmetic expressed over
        three-element numpy arrays costs several times as much in call
        overhead as it does in the work it is doing.
        """
        shape = self.shape
        if not shape or len(self.ambient) < shape[0] * shape[1] * shape[2]:
            black = np.zeros(3, dtype='d')
            return black, black.copy(), np.array(self.DEFAULT_DIRECTION,
                                                 dtype='d')
        indices, weights = self._corners(self.cell(point, shape), shape)
        scale = float(self.intensity)
        ambient = weights @ self.ambient[indices] * scale
        directional = weights @ self.directional[indices] * scale
        direction = weights @ self.direction[indices]
        length = float(np.linalg.norm(direction))
        if length < 1e-6:
            return ambient, directional, np.array(self.DEFAULT_DIRECTION,
                                                  dtype='d')
        return ambient, directional, direction / length

    @staticmethod
    def _corners(position: Tuple[float, float, float],
                 counts: Tuple[int, ...]) -> Tuple[List[int], np.ndarray]:
        """The eight samples around ``position`` and what each contributes.

        Spelled out rather than looped because the eight of them are the whole
        of a trilinear read, and this runs once per lit object per frame.
        """
        nx, ny, nz = counts
        ix, iy, iz = (int(position[0]), int(position[1]), int(position[2]))
        fx, fy, fz = (position[0] - ix, position[1] - iy, position[2] - iz)
        nfx, nfy, nfz = 1.0 - fx, 1.0 - fy, 1.0 - fz
        # How far the *next* sample along each axis is, or zero where this is
        # already the last: the clamp that keeps an object at the edge of the
        # grid lit by the edge rather than reading past it.
        dx = 1 if ix + 1 < nx else 0
        dy = nx if iy + 1 < ny else 0
        dz = nx * ny if iz + 1 < nz else 0
        base = ix + nx * (iy + ny * iz)
        return (
            [base, base + dx, base + dy, base + dx + dy,
             base + dz, base + dx + dz, base + dy + dz, base + dx + dy + dz],
            np.array([
                nfx * nfy * nfz, fx * nfy * nfz, nfx * fy * nfz, fx * fy * nfz,
                nfx * nfy * fz, fx * nfy * fz, nfx * fy * fz, fx * fy * fz,
            ], dtype='d'),
        )


def bound_grid(paths: Any) -> Optional[Any]:
    """The first light grid among ``paths`` that has samples in it.

    One grid lights a world, so the first filled one wins; an empty node is
    passed over rather than being allowed to darken a scene that has a real
    grid further down.
    """
    for path in paths or ():
        grid = path[-1]
        if grid.filled:
            return grid
    return None
