"""The flat fill light every lit draw adds, and what a context may say it is.

``context.gltf_scene_ambient`` is one grey level or an RGB triple; anything
else is reported once and the default fill stands.
"""
import numpy as np
import pytest

from OpenGLContext.passes._flat import FlatPass


class _Context:
    def __init__(self, ambient):
        self.gltf_scene_ambient = ambient


def _ambient(value):
    passing = FlatPass.__new__(FlatPass)
    passing.context = _Context(value)
    return passing.sceneAmbient()


def test_nothing_said_is_the_vrml97_fill():
    assert _ambient(None) == (0.2, 0.2, 0.2)


@pytest.mark.parametrize('value', [0.3, [0.3], (0.3,), np.float32(0.3), np.array([0.3])])
def test_one_level_is_grey(value):
    assert _ambient(value) == pytest.approx((0.3, 0.3, 0.3))


@pytest.mark.parametrize('value', [(0.1, 0.2, 0.3), [0.1, 0.2, 0.3],
                                   np.array([0.1, 0.2, 0.3]), (0.1, 0.2, 0.3, 1.0)])
def test_a_colour_is_its_first_three(value):
    assert _ambient(value) == pytest.approx((0.1, 0.2, 0.3))


@pytest.mark.parametrize('value', [(), (0.1, 0.2), 'bright', float('nan')])
def test_anything_else_is_reported_once_and_the_fill_stands(value, caplog):
    passing = FlatPass.__new__(FlatPass)
    passing.context = _Context(value)
    with caplog.at_level('WARNING'):
        assert passing.sceneAmbient() == (0.2, 0.2, 0.2)
        assert passing.sceneAmbient() == (0.2, 0.2, 0.2)
    assert len([r for r in caplog.records if 'gltf_scene_ambient' in r.getMessage()]) == 1
