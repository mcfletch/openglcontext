"""Value noise over the ground plane: the grain landscapes are made of.

:func:`fbm` and :func:`ridged` are deterministic in their seed, vectorised and
numpy-only. The shipped procedural landscape
(:mod:`OpenGLContext.loaders.tiles3d.procedural`) is built from them, and so is
anything that adds to a landscape -- a sculpted hill
(:mod:`OpenGLContext.scenegraph.terrain.relief`), a scatter mask, a splat
weight -- so that what is added has the same grain as what it is added to.

One unit of ``x``/``z`` is one feature of the coarsest octave, so a caller
working in metres divides by the size it wants the features to be.
"""
import numpy as np
from numpy.typing import NDArray

__all__ = ['FUSED_POINTS', 'fbm', 'ridged', 'smoothstep', 'value_noise']


#: The offsets of a lattice cell's four corners from its lowest one, along the first axis of
#: the arrays :func:`_hash01` is given.
_CORNER_X = np.array([0, 1, 0, 1], dtype=np.int64)
_CORNER_Z = np.array([0, 0, 1, 1], dtype=np.int64)


#: How many points :func:`value_noise` hashes the four corners of together: more than this and the
#: arrays outgrow the processor's cache, and one corner at a time is quicker.
FUSED_POINTS = 2048


def _hash01(ix: NDArray[np.int64], iz: NDArray[np.int64], seed: int) -> NDArray[np.float64]:
    """A value in [0, 1] for each integer lattice point, fixed by ``seed``.

    ``ix`` and ``iz`` are integer arrays of at least one dimension. The hash wraps in 64
    bits, which is what mixes the bits; NumPy reports a wrap in a scalar and not in an
    array, so the arrays need no ``errstate``, which costs more than the hash.
    """
    h = ix * np.int64(374761393) + iz * np.int64(668265263) + np.int64(seed) * np.int64(1013904223)
    h ^= h >> np.int64(13)
    h *= np.int64(1274126177)
    h ^= h >> np.int64(16)
    h &= np.int64(0xFFFFFF)
    return h.astype(np.float64) / float(0xFFFFFF)


def smoothstep(t: np.ndarray) -> np.ndarray:
    """``3t² - 2t³``: 0 at 0, 1 at 1, level at both ends."""
    return np.asarray(t * t * (3.0 - 2.0 * t))


def value_noise(x: np.ndarray, z: np.ndarray, seed: int) -> np.ndarray:
    """One octave: lattice values blended by :func:`smoothstep`, in [0, 1]."""
    x0 = np.floor(x).astype(np.int64)
    z0 = np.floor(z).astype(np.int64)
    fx = smoothstep(x - x0)
    fz = smoothstep(z - z0)
    if x0.size <= FUSED_POINTS:
        # The four corners of every cell, hashed as one array with the corner along the first
        # axis: a handful of NumPy calls however few points there are.
        where = (4,) + (1,) * x0.ndim
        v00, v10, v01, v11 = _hash01(x0 + _CORNER_X.reshape(where), z0 + _CORNER_Z.reshape(where),
                                     seed)
    else:
        v00 = _hash01(x0, z0, seed)
        v10 = _hash01(x0 + 1, z0, seed)
        v01 = _hash01(x0, z0 + 1, seed)
        v11 = _hash01(x0 + 1, z0 + 1, seed)
    top = v00 * (1 - fx) + v10 * fx
    bot = v01 * (1 - fx) + v11 * fx
    return np.asarray(top * (1 - fz) + bot * fz)


def fbm(x: np.ndarray, z: np.ndarray, seed: int = 0, octaves: int = 5,
        lacunarity: float = 2.0, gain: float = 0.5) -> np.ndarray:
    """Fractal value noise over ``(x, z)``, from 0 to 1.

    ``octaves`` octaves of :func:`value_noise`, each ``lacunarity`` times finer
    and ``gain`` times weaker than the one before.
    """
    x = np.asarray(x, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    total = np.zeros_like(x, dtype=np.float64)
    amp, freq, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        total += amp * value_noise(x * freq, z * freq, seed + o * 101)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


def ridged(x: np.ndarray, z: np.ndarray, seed: int = 0,
           octaves: int = 5) -> np.ndarray:
    """Ridged fractal noise over ``(x, z)``, from 0 to 1.

    The same noise folded about its middle, which turns rounded hills into
    ridges with sharp crests -- what mountains are made of here.
    """
    x = np.asarray(x, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    total = np.zeros_like(x, dtype=np.float64)
    amp, freq, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        n = value_noise(x * freq, z * freq, seed + o * 211)
        r = 1.0 - np.abs(2.0 * n - 1.0)
        total += amp * (r * r)
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm
