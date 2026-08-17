"""Height field: the elevation grid a splat terrain is built from and walked on.

Wraps a normalised (0..1) elevation grid with its world extent and relief so a
single object answers both the *render* question (give me the mesh + normals) and
the *gameplay* question (how high is the ground under (x, z), how steep is it).
Bilinear sampling matches the interpolated render mesh exactly, so a camera
clamped with :meth:`sample` sits on the surface the player sees, not above or
below it. Also bakes the two static shadow terms used by the splat shader.
"""
import math
from typing import Any, Callable, Optional

import numpy as np
from PIL import Image


class HeightField:
    """A square elevation grid over a centred world square.

    :param grid: (res, res) array of normalised heights in [0, 1].
    :param extent: side length of the terrain in world units (centred on origin,
        so world XZ spans [-extent/2, extent/2]).
    :param relief: world height of a full 0->1 change in the grid.
    :param base: world height the grid's zero stands at. A landscape's lowest
        point is rarely sea level -- a lake bed is below the datum and a valley
        floor a long way above it -- and the grid says nothing about where it
        sits, only how far it rises.
    """
    def __init__(self, grid: np.ndarray, extent: float, relief: float,
                 base: float = 0.0) -> None:
        self.grid = np.asarray(grid, 'd')
        self.res = self.grid.shape[0]
        self.extent = float(extent)
        self.relief = float(relief)
        self.base = float(base)

    @classmethod
    def from_function(cls, height_fn: "Callable[[Any, Any], Any]", res: int,
                      extent: float, base: "Optional[float]" = None,
                      relief: "Optional[float]" = None) -> "HeightField":
        """Sample a height function over the world square into a grid.

        A landscape is *authored* as a function of ``(x, z)`` -- procedural
        noise, a DEM reader, terrain with a road's earthworks cut into it -- and
        rendered and collided against as a grid. This is the step between.

        ``base`` and ``relief`` default to what the function actually does over
        the square, which spends the grid's whole 0..1 range on the ground that
        is there. Give them explicitly when two fields of one landscape have to
        agree -- they meet in a step otherwise -- and ground outside the range
        is held at its edge.
        """
        axis = np.linspace(-extent / 2.0, extent / 2.0, int(res))
        x, z = np.meshgrid(axis, axis)
        heights = np.asarray(height_fn(x, z), dtype='d').reshape(int(res), int(res))
        if base is None:
            base = float(heights.min())
        if relief is None:
            relief = float(heights.max()) - base
        # Level ground has no relief to divide by, and a flat grid of zeros at
        # the datum is exactly right for it.
        span = relief if relief > 0 else 1.0
        grid = np.clip((heights - base) / span, 0.0, 1.0)
        return cls(grid, extent, relief, base=base)

    def save_image(self, path: "Any", format: "Optional[str]" = None) -> None:
        """Write the grid as a 16-bit greyscale PNG.

        Sixteen bits because eight over five hundred metres of relief is
        two-metre steps, which a car drives over as a staircase. The datum and
        the relief are not in the image -- they are two numbers, and belong
        wherever the image is referenced from.
        """
        quantised = np.clip(np.rint(self.grid * 65535.0), 0, 65535).astype('<u2')
        Image.fromarray(quantised).save(path, format=format or 'PNG')

    @classmethod
    def from_image(cls, path: Any, res: int, extent: float, relief: float,
                   base: float = 0.0) -> "HeightField":
        """Load a heightmap image, resampled to ``res`` x ``res``.

        ``path`` is anything PIL opens: a filename, or the bytes of one that
        came off the network rather than off disk.

        The grid feeds :meth:`sample`/:meth:`mesh` as a single 0..1 channel, so
        the divisor tracks the image's real bit depth instead of assuming 16-bit:
        read at /65535 an 8-bit DEM (0..255) collapses to a 0..0.004 range and the
        terrain comes out silently flat. Multi-channel images are folded to
        luminance -- a packed RGB elevation encoding (e.g. Terrarium) is not that,
        and needs an offline decode this loader does not do.

        :raises ValueError: on an image mode with no defined height scaling, or if
            the resampled data is not a single 2-D channel.
        """
        im: Image.Image = Image.open(path)
        if im.mode in ('I', 'I;16', 'I;16B', 'I;16L', 'I;16N'):
            maxval = 65535.0
        elif im.mode in ('L', 'P', 'RGB', 'RGBA'):
            if im.mode != 'L':
                im = im.convert('L')
            maxval = 255.0
        else:
            raise ValueError('Unsupported heightmap image mode %r' % (im.mode,))
        im = im.resize((res, res), Image.Resampling.LANCZOS)
        grid = np.asarray(im).astype(np.float64) / maxval
        if grid.ndim != 2:
            raise ValueError('Heightmap must reduce to a single 2-D channel, got '
                             'shape %r' % (grid.shape,))
        return cls(grid, extent, relief, base=base)

    def sample(self, x: "float | np.ndarray", z: "float | np.ndarray") -> np.ndarray:
        """Bilinear world-height at ``(x, z)`` (scalars or arrays), matching the mesh."""
        E, R = self.extent, self.res
        x = np.asarray(x, 'd')
        z = np.asarray(z, 'd')
        u = np.clip((x + E / 2) / E * (R - 1), 0, R - 1)
        v = np.clip((z + E / 2) / E * (R - 1), 0, R - 1)
        u0 = np.floor(u).astype(int)
        v0 = np.floor(v).astype(int)
        u1 = np.minimum(u0 + 1, R - 1)
        v1 = np.minimum(v0 + 1, R - 1)
        fu = u - u0
        fv = v - v0
        h = self.grid
        h00 = h[v0, u0]
        h01 = h[v0, u1]
        h10 = h[v1, u0]
        h11 = h[v1, u1]
        return ((h00 * (1 - fu) + h01 * fu) * (1 - fv) +
                (h10 * (1 - fu) + h11 * fu) * fv) * self.relief + self.base

    def height_at(self, x: float, z: float) -> float:
        """Scalar world-height at ``(x, z)``."""
        return float(self.sample(x, z))

    def slope(self, x: "float | np.ndarray", z: "float | np.ndarray",
              eps: float = 8.0) -> np.ndarray:
        """Approximate slope magnitude (rise/run) at ``(x, z)``.

        Central difference in the interior; the stencil is clamped inward to a
        one-sided difference at the terrain borders. A symmetric stencil there
        samples past the edge, where :meth:`sample` clamps both taps to the same
        edge cell and a real border cliff reads as flat."""
        x = np.asarray(x, 'd')
        z = np.asarray(z, 'd')
        half = self.extent / 2.0
        xp = np.minimum(x + eps, half)
        xm = np.maximum(x - eps, -half)
        zp = np.minimum(z + eps, half)
        zm = np.maximum(z - eps, -half)
        sx = (self.sample(xp, z) - self.sample(xm, z)) / np.maximum(xp - xm, 1e-6)
        sz = (self.sample(x, zp) - self.sample(x, zm)) / np.maximum(zp - zm, 1e-6)
        return np.hypot(sx, sz)

    def mesh(self) -> "tuple[np.ndarray, np.ndarray]":
        """Interleaved (position, normal) vertices and triangle indices for the grid.

        :returns: ``(vertices Nx6 float32, indices uint32)`` — a regular triangulated
            grid over the world square with per-vertex normals from the gradient.
        """
        E, R = self.extent, self.res
        z = self.grid * self.relief + self.base
        xs = np.linspace(-E / 2, E / 2, R)
        X, Y = np.meshgrid(xs, xs)
        d = E / (R - 1)
        dzdx = np.gradient(z, d, axis=1)
        dzdy = np.gradient(z, d, axis=0)
        nrm = np.stack([-dzdx, np.ones_like(z), -dzdy], -1)
        nrm /= np.linalg.norm(nrm, axis=-1, keepdims=True)
        inter = np.concatenate([np.stack([X, z, Y], -1), nrm], -1).reshape(-1, 6).astype(np.float32)
        i, j = np.mgrid[0:R - 1, 0:R - 1]
        a = (i * R + j).ravel()
        b = a + 1
        c = a + R
        d2 = c + 1
        idx = np.empty((a.size, 6), np.uint32)
        idx[:, 0] = a
        idx[:, 1] = c
        idx[:, 2] = b
        idx[:, 3] = b
        idx[:, 4] = c
        idx[:, 5] = d2
        return inter, idx.ravel()

    def sun_shadow(self, sun: "np.ndarray | tuple[float, float, float]",
                   steps: int = 170, softness: float = 35.0,
                   strength: float = 0.8) -> np.ndarray:
        """Bake terrain self-shadowing: march the grid toward the sun; where higher
        ground blocks the ray the cell is shadowed. Returns lit in [0, 1] (float32)."""
        hm = self.grid * self.relief
        R = hm.shape[0]
        cell = self.extent / (R - 1)
        ts = -np.asarray(sun, float)
        hn = math.hypot(ts[0], ts[2])
        tan_elev = ts[1] / max(hn, 1e-3)
        dz = ts[2] / max(hn, 1e-3)
        dx = ts[0] / max(hn, 1e-3)
        occ = np.zeros_like(hm)
        for k in range(1, steps):
            d = k * cell
            shifted = np.roll(np.roll(hm, -int(round(k * dz)), 0), -int(round(k * dx)), 1)
            occ = np.maximum(occ, shifted - (hm + d * tan_elev))
        return (1.0 - strength * np.clip(occ / softness, 0, 1)).astype(np.float32)

    def canopy_shadow(self, lit: np.ndarray, tree_pos: np.ndarray,
                      sun: "np.ndarray | tuple[float, float, float]",
                      spread: float = 7.0, crown: float = 8.0,
                      darken: float = 0.85, cap: float = 0.55) -> np.ndarray:
        """Darken ``lit`` under tree cover, for the dappled shade of a wood.

        ``tree_pos`` is an (N, 3) array of trunk world positions, offset toward
        the sun by ``spread`` because a tree shades along the light rather than
        straight down.

        A tree shades the ground its *crown* covers, not the cell its trunk
        stands in, so each one is spread over ``crown`` metres and the total is
        scaled so that one tree per crown-area is a closed canopy. That is what
        makes the figure mean something at any grid resolution and any planting
        density: ``darken`` is then how hard a closed canopy darkens the ground
        and ``cap`` the most of the light it may take.
        """
        SR = lit.shape[0]
        ts = -np.asarray(sun, float)
        hn = math.hypot(ts[0], ts[2])
        off = (-ts[[0, 2]] / max(hn, 1e-3)) * spread
        E = self.extent
        sx = np.asarray(tree_pos, float)[:, 0] + off[0]
        sz = np.asarray(tree_pos, float)[:, 2] + off[1]
        gx = np.clip((sx + E / 2) / E * (SR - 1), 0, SR - 1).astype(int)
        gz = np.clip((sz + E / 2) / E * (SR - 1), 0, SR - 1).astype(int)
        dens = np.zeros((SR, SR), np.float32)
        np.add.at(dens, (gz, gx), 1.0)
        # Blurred as floats. Through an 8-bit image the count is clipped before
        # it is spread, which flattens exactly the peaks the shade is made of.
        radius = max(crown / 2.0 / (E / (SR - 1)), 0.5)
        dens = _blurred(dens, radius) * (2.0 * math.pi * radius * radius)
        shaded: np.ndarray = (
            lit * (1.0 - np.clip(dens * darken, 0, cap))).astype(np.float32)
        return shaded


def _blurred(field: np.ndarray, radius: float) -> np.ndarray:
    """A Gaussian blur of a float field, separably, in place of an image filter.

    An image filter would take the field through eight bits first, and a density
    is clipped by that before it is spread -- which flattens exactly the peaks
    the shade is made of. The kernel sums to one on each axis, so a single unit
    at one cell comes out with a peak of about ``1 / (2*pi*radius**2)``.
    """
    reach = int(max(1, round(radius * 3.0)))
    offsets = np.arange(-reach, reach + 1, dtype='f4')
    kernel = np.exp(-0.5 * (offsets / max(radius, 1e-6)) ** 2)
    kernel /= kernel.sum()
    out = np.zeros_like(field, dtype=np.float32)
    padded = np.pad(field.astype('f4'), ((0, 0), (reach, reach)), mode='edge')
    for index, weight in enumerate(kernel):
        out += padded[:, index:index + field.shape[1]] * weight
    padded = np.pad(out, ((reach, reach), (0, 0)), mode='edge')
    out = np.zeros_like(field, dtype=np.float32)
    for index, weight in enumerate(kernel):
        out += padded[index:index + field.shape[0], :] * weight
    return out
