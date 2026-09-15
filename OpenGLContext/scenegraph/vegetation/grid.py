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


def world_grid_scatter(cx: float, cz: float, radius: float, density: float,
                       height_field: "HeightField", scale_mul: float = 0.7,
                       jitter: float = 0.95,
                       mask: Optional[Callable[[np.ndarray, np.ndarray], np.ndarray]] = None,
                       salt: int = 0,
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
    sca = ((0.5 + 0.5 * hsh(_SEED_SCALE)[keep]) * scale_mul).astype(np.float32)
    return pos, yaw, sca
