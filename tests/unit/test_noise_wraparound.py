"""The noise hash wraps in 64 bits by design and says nothing about it."""
import warnings

import numpy as np
import pytest

from OpenGLContext.noise import fbm, value_noise


@pytest.mark.parametrize('x, z', [(np.array(1.0e4), np.array(-3.0e4)),
                                  (np.array([2.5e4, 9.0e3]), np.array([-4.0e4, 1.0e2]))])
def test_far_from_the_origin_the_noise_wraps_without_a_warning(x, z):
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        value = fbm(x, z, seed=21, octaves=4)
    assert np.all((value >= 0.0) & (value <= 1.0))


def test_the_values_are_those_the_wrapping_hash_has_always_given():
    x = np.array([123456.5, -98765.25, 0.5])
    z = np.array([77777.75, 31415.5, -2.5])
    with np.errstate(over='ignore'):
        expected = value_noise(x, z, 5)
    with warnings.catch_warnings():
        warnings.simplefilter('error')
        assert np.array_equal(value_noise(x, z, 5), expected)
