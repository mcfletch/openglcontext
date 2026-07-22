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
import numpy as np


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


def _mix32(h):
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


def _cell_hash(I, J, seed):
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


def world_grid_scatter(cx, cz, radius, density, height_field, scale_mul=0.7, jitter=0.95,
                       mask=None):
    """Deterministic disc of instances around ``(cx, cz)`` on a world-anchored grid.

    :param cx, cz: disc centre (world XZ), typically the camera position.
    :param radius: disc radius in world units.
    :param density: instances per square world unit (grid spacing = 1/sqrt(density)).
    :param height_field: a :class:`HeightField` used to sit instances on the ground.
    :param scale_mul: multiplies the per-instance height scale.
    :param jitter: fraction of a cell an instance may be displaced from its centre.
    :param mask: optional ``mask(px, pz) -> weight`` in [0, 1] (arrays in, array out),
        e.g. a terrain grass-layer weight. Each cell is kept with probability equal to
        its weight, decided by the cell's own deterministic hash — so grass thins where
        the weight falls and vanishes on non-grass ground, and the keep set is
        world-anchored (a cell's fate never changes as the disc recentres, no popping).
    :returns: ``(positions Nx3 float32, yaws N float32, scales N float32)``.
    """
    s = 1.0 / math.sqrt(density)
    i0 = int(math.floor((cx - radius) / s)); i1 = int(math.ceil((cx + radius) / s))
    j0 = int(math.floor((cz - radius) / s)); j1 = int(math.ceil((cz + radius) / s))
    I, J = np.meshgrid(np.arange(i0, i1 + 1, dtype=np.int64),
                       np.arange(j0, j1 + 1, dtype=np.int64))
    I = I.ravel(); J = J.ravel()
    hsh = lambda seed: _cell_hash(I, J, seed)   # deterministic per-cell [0,1)
    fx = hsh(_SEED_JITTER_X); fz = hsh(_SEED_JITTER_Z)
    px = I * s + (fx - 0.5) * s * jitter; pz = J * s + (fz - 0.5) * s * jitter
    keep = ((px - cx) ** 2 + (pz - cz) ** 2) < radius * radius
    if mask is not None:
        w = np.clip(np.asarray(mask(px, pz), float), 0.0, 1.0)
        keep &= w > hsh(_SEED_KEEP)     # per-cell hash: keep with prob = weight
    px = px[keep]; pz = pz[keep]
    pos = np.stack([px, height_field.sample(px, pz), pz], 1).astype(np.float32)
    yaw = (hsh(_SEED_YAW)[keep] * 2.0 * math.pi).astype(np.float32)
    sca = ((0.5 + 0.5 * hsh(_SEED_SCALE)[keep]) * scale_mul).astype(np.float32)
    return pos, yaw, sca
