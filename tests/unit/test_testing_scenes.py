"""``scene_context`` draws a scene in the test process and puts the configuration back."""
import os

import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context


@pytest.fixture(autouse=True)
def core():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


def _red_box():
    return [basenodes.Transform(translation=(0, 0, -3), children=[basenodes.Shape(
        geometry=basenodes.Box(),
        appearance=basenodes.Appearance(material=basenodes.Material(
            diffuseColor=(1, 0, 0), emissiveColor=(1, 0, 0))))])]


def test_a_frame_is_read_as_it_is_presented():
    with scene_context(_red_box(), size=(64, 48)) as context:
        image = drawn_image(context)
    assert image.shape == (48, 64, 3)
    middle = image[20:28, 28:36].reshape(-1, 3).mean(axis=0)
    assert middle[0] > 100 and middle[0] > 2 * middle[1], middle
    assert np.all(image[0, 0] < 100)


def test_the_scene_configuration_is_put_back(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_BLOOM', '0')
    with scene_context(_red_box(), environment={'OPENGLCONTEXT_BLOOM': '1'}):
        assert os.environ['OPENGLCONTEXT_BLOOM'] == '1'
        assert os.environ['OPENGLCONTEXT_HIDDEN'] == '1'
    assert os.environ['OPENGLCONTEXT_BLOOM'] == '0'


def test_the_pass_goes_with_the_context():
    """Released through the context's own teardown, which drops that context's
    pass and no other."""
    from OpenGLContext.passes import renderpass

    with scene_context(_red_box(), size=(32, 24)) as context:
        drawn_image(context)
        assert renderpass.FLAT is not None
    assert renderpass.FLAT is None
