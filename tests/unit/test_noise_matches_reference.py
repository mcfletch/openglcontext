"""The noise functions give the values a straightforward evaluation of the same arithmetic does.

Landscapes, scatter masks and baked worlds are made from these values, so an
evaluation that is faster must be the same to the last bit. The reference here is
the arithmetic written out one lattice corner at a time.
"""
import warnings

import numpy as np
import pytest

from OpenGLContext import noise


def _hash(ix, iz, seed):
    ix, iz = np.asarray(ix, np.int64), np.asarray(iz, np.int64)
    with np.errstate(over='ignore'):
        h = ix * np.int64(374761393) + iz * np.int64(668265263) + np.int64(seed) * np.int64(1013904223)
        h = (h ^ (h >> np.int64(13))) * np.int64(1274126177)
        h = h ^ (h >> np.int64(16))
    return (h & np.int64(0xFFFFFF)).astype(np.float64) / float(0xFFFFFF)


def _value_noise(x, z, seed):
    x, z = np.asarray(x, np.float64), np.asarray(z, np.float64)
    x0, z0 = np.floor(x).astype(np.int64), np.floor(z).astype(np.int64)
    fx, fz = noise.smoothstep(x - x0), noise.smoothstep(z - z0)
    top = _hash(x0, z0, seed) * (1 - fx) + _hash(x0 + 1, z0, seed) * fx
    bot = _hash(x0, z0 + 1, seed) * (1 - fx) + _hash(x0 + 1, z0 + 1, seed) * fx
    return top * (1 - fz) + bot * fz


def _points(shape, seed=1, span=4000.0):
    rng = np.random.default_rng(seed)
    return rng.uniform(-span, span, shape), rng.uniform(-span, span, shape)


@pytest.mark.parametrize('shape', [(1,), (7,), (9, 5), (2, 3, 4), (500,), (2048,), (2049,), (60, 60)])
def test_value_noise_is_the_reference_over_arrays(shape):
    x, z = _points(shape)
    assert np.array_equal(noise.value_noise(x, z, 17), _value_noise(x, z, 17))


@pytest.mark.parametrize('seed', [0, 1, 17, 211, 4242, 2 ** 31 - 1])
def test_value_noise_is_the_reference_for_each_seed(seed):
    x, z = _points((300,), seed=2)
    assert np.array_equal(noise.value_noise(x, z, seed), _value_noise(x, z, seed))


def test_value_noise_is_the_reference_for_a_scalar():
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        got = noise.value_noise(np.float64(1234.5), np.float64(-77.25), 5)
    assert got == _value_noise(1234.5, -77.25, 5)
    assert np.ndim(got) == 0


def test_value_noise_is_the_reference_for_a_plain_float():
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        got = noise.value_noise(3.25, 0.5, 9)
    assert got == _value_noise(3.25, 0.5, 9)


def test_value_noise_is_the_reference_on_the_lattice_and_across_zero():
    x = np.array([-2.0, -1.0, 0.0, 1.0, 2.0, -0.5, 0.5, -1e-9, 1e-9])
    assert np.array_equal(noise.value_noise(x, x[::-1], 3), _value_noise(x, x[::-1], 3))


def test_value_noise_is_the_reference_far_from_the_origin():
    x, z = _points((200,), seed=3, span=2.0e7)
    assert np.array_equal(noise.value_noise(x, z, 8), _value_noise(x, z, 8))


def test_the_octaves_are_the_references():
    x, z = _points((64,), seed=4)
    total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
    for o in range(5):
        total = total + amp * _value_noise(x * freq, z * freq, 3 + o * 101)
        norm += amp
        amp *= 0.5
        freq *= 2.0
    assert np.array_equal(noise.fbm(x, z, seed=3), total / norm)


def test_a_result_does_not_share_memory_with_the_inputs():
    x, z = _points((16,), seed=5)
    before = x.copy()
    noise.value_noise(x, z, 1)
    assert np.array_equal(x, before)
