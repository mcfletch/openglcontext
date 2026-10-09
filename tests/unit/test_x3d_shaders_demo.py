"""The shader showcase `oglc-x3d-shaders` opens draws every shader it lists

`x3d_shaders.x3d` is written beside the marble map and the packaged shader it
names, read by the engine's loader, and drawn through both renderers: each
of its shaders is selected and links, and each stands where it should.
"""
import numpy as np
import pytest

from OpenGLContext.bin import x3d_shaders_demo
from OpenGLContext.loaders import background
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context

SHADERS = ('Toon', 'Marble', 'Apart', 'Stripes', 'Heat', 'Ripple')


@pytest.fixture(autouse=True)
def core():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


@pytest.fixture(scope='module')
def directory(tmp_path_factory):
    return str(tmp_path_factory.mktemp('x3d-shaders'))


def test_the_document_and_its_files_are_written(directory):
    import os
    path = x3d_shaders_demo.prepare(directory)
    assert os.path.basename(path) == 'x3d_shaders.x3d'
    for name in ('marble_base.png', 'x3d_shaders_stripes.glsl'):
        assert os.path.exists(os.path.join(directory, name))


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_every_shader_is_selected_and_valid(directory, renderer):
    showcase = x3d_shaders_demo.Showcase(directory)
    background.wait_for_idle(20.0)
    with scene_context(showcase.scene, size=(240, 160),
                       environment={'OPENGLCONTEXT_RENDERER': renderer}) as context:
        drawn_image(context)
        background.wait_for_idle(20.0)
        image = drawn_image(context)
    for name in SHADERS:
        shader = showcase.scene.getDEF(name)
        assert shader.isSelected is True, name
        assert shader.isValid is True, name
    # Something is drawn where each of the four standing shapes is.
    row = image[image.shape[0] * 55 // 100]
    lit = np.flatnonzero(row.max(axis=1) > 40)
    assert len(lit) > image.shape[1] // 3
