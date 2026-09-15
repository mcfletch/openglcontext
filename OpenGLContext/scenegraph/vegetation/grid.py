"""World-anchored jittered scatter for camera-following vegetation fields.

A grass field that follows the camera must not re-randomise when it recentres, or
every tuft visibly jumps ("pops"). :func:`world_grid_scatter` places instances on a
fixed world grid whose per-cell jitter, yaw and scale are a deterministic hash of
the integer cell index, so a given world location always yields the same tuft. As
the disc recentres on a walking camera, tufts stay put in the world; only those
crossing the far radius appear or disappear (handled by the billboard's distance
dissolve). Returns arrays ready for
:meth:`~OpenGLContext.scenegraph.vegetation.billboards.InstancedBillboards.update_instances`.
"""
import math
from typing import TYPE_CHECKING, Callable, Optional, TypeVar

import numpy as np

if TYPE_CHECKING:
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField


# Independent per-stream seeds. Each derived value (jitter x/z, keep decision, yaw,
# scale) draws from its own integer hash so the streams are uncorrelated; distinct
# 32-bit constants give the avalanche mixer large Hamming differences to spread.
_SEED_JITTER_X = np.uint32(0x2545F491)
_SEED_JITTER_Z = np.uint32(0x9E3779B9)
_SEED_KEEP = np.uint32(0x85EBCA6B)
_SEED_YAW = np.uint32(0xC2B2AE35)
_SEED_SCALE = np.uint32(0x27D4EB2F)
_SEED_PATCH = np.uint32(0x165667B1)

_C_I = np.uint32(0x9E3779B1)
_C_J = np.uint32(0x85EBCA77)
_INV_24 = 1.0 / float(1 << 24)


#: The mixer takes a whole grid of cell indices or a single seed, and gives back
#: what it was given: one avalanche serves both.
_Mixable = TypeVar('_Mixable', np.ndarray, np.uint32)


def _mix32(h: _Mixable) -> _Mixable:
    """Finalize a uint32 array with the lowbias32 avalanche (murmur-style).

    Every input bit affects every output bit, so nearby cell indices and nearby
    stream seeds produce unrelated values.
    """
    h = h ^ (h >> np.uint32(16))
    h = h * np.uint32(0x7FEB352D)
    h = h ^ (h >> np.uint32(15))
    h = h * np.uint32(0x846CA68B)
    h = h ^ (h >> np.uint32(16))
    return h


def _salted(seed: np.uint32, salt: int) -> np.uint32:
    """``seed`` moved onto the stream ``salt`` names.

    Ground cover is several species at once and each wants its own grid, so the
    salt has to reach every stream: salting the cell index instead would move
    all of them together and leave two species standing in each other's places.
    The salt is avalanched before it is mixed in, so adjacent salts -- which is
    what a species index is -- give unrelated streams. Salt 0 is the seed
    itself, because ``_mix32(0)`` is 0: an unsalted scatter is the scatter that
    was there before there were salts to ask for.
    """
    return np.uint32(seed ^ _mix32(np.uint32(salt & 0xFFFFFFFF)))


def _cell_hash(I: np.ndarray, J: np.ndarray, seed: np.uint32) -> np.ndarray:
    """Uniform float in [0, 1) keyed on an integer cell index and a stream seed.

    Integer bit-mixing rather than ``sin()`` of a float index: the cell indices
    grow with world position, and ``sin`` of a large argument collapses to a few
    banded values far from the origin, which structures the jitter and keep set
    into visible stripes and gaps. An integer avalanche has no precision floor, so
    a cell at world coord 1e6 is as well-distributed as one at the origin. Indices
    wrap into uint32 (``astype``), so the same integer cell always maps to the same
    value regardless of the query origin — placement is world-anchored and pop-free.
    """
    a = I.astype(np.uint32)
    b = J.astype(np.uint32)
    h = (a * _C_I) ^ (b * _C_J) ^ seed
    h = _mix32(h)
    return (h >> np.uint32(8)).astype(np.float64) * _INV_24


def world_noise(x: np.ndarray, z: np.ndarray, metres: float,
                salt: int = 0) -> np.ndarray:
    """A smooth world-anchored field in [0, 1], one blob every ``metres``.

    The same integer hash the scatter is placed by, read on a coarser grid and
    interpolated between its corners -- so it is smooth, it repeats nothing, and
    it is anchored to the world rather than to whoever is looking at it. That
    last part is what makes it usable for *where a thing grows*: a bed of
    nettles worked out from this is in the same place every time you walk past
    it, and no two salts agree about where the beds are.

    Smoothstep between corners rather than a straight line, because a linear
    interpolation leaves a visible crease along every coarse cell edge, and a
    bed of plants with a straight edge reads as a planted border.
    """
    u = np.asarray(x, 'd') / float(metres)
    v = np.asarray(z, 'd') / float(metres)
    i = np.floor(u).astype(np.int64)
    j = np.floor(v).astype(np.int64)
    fx = u - i
    fz = v - j
    sx = fx * fx * (3.0 - 2.0 * fx)
    sz = fz * fz * (3.0 - 2.0 * fz)
    seed = _salted(_SEED_PATCH, salt)
    low = (_cell_hash(i, j, seed) * (1.0 - sx)
           + _cell_hash(i + 1, j, seed) * sx)
    high = (_cell_hash(i, j + 1, seed) * (1.0 - sx)
            + _cell_hash(i + 1, j + 1, seed) * sx)
    return low * (1.0 - sz) + high * sz


class Patches:
    """How a species gathers itself into beds, and what that costs the scatter.

    :attr:`weight` is a mask in [0, 1] -- 1 in the middle of a bed, 0 on the
    bare ground between -- and :attr:`thinning` is the fraction of the ground
    it keeps overall.

    The two go together because a mask can only ever *remove* plants: the keep
    test is a probability, so a bed cannot be made denser than the grid it is
    drawn on. A caller that wants density to keep meaning plants per square
    metre therefore scatters on a grid :attr:`thinning` times finer and lets
    the weight take the difference back out -- which is what
    :meth:`density_for` works out. Without it, every patchy species would
    quietly thin the whole world in proportion to how clumped it was.
    """

    def __init__(self, patchiness: float, metres: float, salt: int = 0) -> None:
        self.patchiness = float(np.clip(patchiness, 0.0, 1.0))
        self.metres = float(metres)
        self.salt = int(salt)
        # Raising the field to a power is what turns a gentle rise and fall
        # into distinct beds with bare ground between them.
        self.power = 1.0 + 7.0 * self.patchiness
        self.thinning = 1.0
        if self.patchiness > 0.0:
            # Smoothed between corners, so the field's average is not a uniform
            # distribution's and cannot be written down. It is measured once,
            # here, over ground wide enough to hold many beds.
            span = np.linspace(0.0, 48.0 * self.metres, 192)
            across, along = np.meshgrid(span, span)
            self.thinning = max(float(np.mean(self.weight(across, along))),
                                1e-6)

    def weight(self, x: np.ndarray, z: np.ndarray) -> np.ndarray:
        """How much of this species belongs here, in [0, 1].

        A blend between flat -- as likely here as anywhere -- and the field
        raised to its power, rather than the raised field alone. Blended,
        because the raised field on its own is *already* strongly varying at the
        gentlest setting, so a plant asked to be a little patchy would come out
        as patchy as one asked to be very: there would be no low end.
        """
        if self.patchiness <= 0.0:
            return np.ones(np.shape(np.asarray(x)), 'd')
        clumped = world_noise(x, z, self.metres, self.salt) ** self.power
        return (1.0 - self.patchiness) + self.patchiness * clumped

    def density_for(self, density: float) -> float:
        """The grid density that leaves ``density`` standing after thinning."""
        return float(density) / self.thinning


def world_grid_scatter(cx: float, cz: float, radius: float, density: float,
                       height_field: "HeightField", scale_mul: float = 0.7,
                       jitter: float = 0.95,
                       mask: Optional[Callable[[np.ndarray, np.ndarray], np.ndarray]] = None,
                       salt: int = 0,
                       scale_range: "tuple[float, float]" = (0.5, 1.0),
                       ) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """Deterministic disc of instances around ``(cx, cz)`` on a world-anchored grid.

    :param cx, cz: disc centre (world XZ), typically the camera position.
    :param radius: disc radius in world units.
    :param density: instances per square world unit (grid spacing = 1/sqrt(density)).
    :param height_field: a :class:`HeightField` used to sit instances on the ground.
    :param scale_mul: multiplies the per-instance height scale.
    :param jitter: how far an instance may be displaced from its cell's centre, as a
        fraction of the cell. Above 1 an instance may land in a neighbour's ground,
        which is what breaks the lattice: at or below 1 no two instances can approach
        each other closely and the set reads as diagonals of evenly spaced tufts from
        a few tens of metres away. Clumps and gaps are what real cover looks like.
    :param mask: optional ``mask(px, pz) -> weight`` in [0, 1] (arrays in, array out),
        e.g. a terrain grass-layer weight. Each cell is kept with probability equal to
        its weight, decided by the cell's own deterministic hash — so grass thins where
        the weight falls and vanishes on non-grass ground, and the keep set is
        world-anchored (a cell's fate never changes as the disc recentres, no popping).
    :param scale_range: how far the per-instance scale spreads either side of
        ``scale_mul``, as multiples of it. A scatter of identical plants reads as a
        printed pattern, so each is scaled by its own cell's hash -- but what the
        spread is *around* is the caller's: a species that says it is 0.4 m tall and
        averages 0.28 m is 0.4 m of nothing. A range about 1 keeps the mean where the
        caller put it; the default is the half-to-full spread this has always had.
    :param salt: which grid this is. Ground cover is several species at once, each at
        its own density; a salt of its own gives each one an independent
        world-anchored grid, so no two species stand in the same places and each keeps
        the pop-free property separately. Any integer. The default is the one grid
        there has always been.
    :returns: ``(positions Nx3 float32, yaws N float32, scales N float32)``.
    """
    s = 1.0 / math.sqrt(density)
    # A cell outside the disc can still place its instance inside it, by up to
    # half a cell of jitter, so the sweep is widened by that much.
    reach = radius + s * max(jitter, 1.0) / 2.0
    i0 = int(math.floor((cx - reach) / s))
    i1 = int(math.ceil((cx + reach) / s))
    j0 = int(math.floor((cz - reach) / s))
    j1 = int(math.ceil((cz + reach) / s))
    Igrid, Jgrid = np.meshgrid(np.arange(i0, i1 + 1, dtype=np.int64),
                               np.arange(j0, j1 + 1, dtype=np.int64))
    I = Igrid.ravel()
    J = Jgrid.ravel()

    def hsh(seed: np.uint32) -> np.ndarray:   # deterministic per-cell [0,1)
        return _cell_hash(I, J, _salted(seed, salt))
    fx = hsh(_SEED_JITTER_X)
    fz = hsh(_SEED_JITTER_Z)
    px = I * s + (fx - 0.5) * s * jitter
    pz = J * s + (fz - 0.5) * s * jitter
    keep = ((px - cx) ** 2 + (pz - cz) ** 2) < radius * radius
    if mask is not None:
        w = np.clip(np.asarray(mask(px, pz), float), 0.0, 1.0)
        keep &= w > hsh(_SEED_KEEP)     # per-cell hash: keep with prob = weight
    px = px[keep]
    pz = pz[keep]
    pos = np.stack([px, height_field.sample(px, pz), pz], 1).astype(np.float32)
    yaw = (hsh(_SEED_YAW)[keep] * 2.0 * math.pi).astype(np.float32)
    low, high = scale_range
    sca = ((low + (high - low) * hsh(_SEED_SCALE)[keep])
           * scale_mul).astype(np.float32)
    return pos, yaw, sca
