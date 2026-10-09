"""Tests for drawing far from the origin: transforms and the camera are composed
in double precision, and only the model-view, relative to the camera, is
single precision.

At 6 378 137 metres, the Earth's radius, single precision steps by half a
metre; the scene here is placed to a tenth of that.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.transform import MatrixTransform
from OpenGLContext.testing.scenes import drawn_image, scene_context

FAR = 6378137.3


def placed(x):
    matrix = np.identity(4)
    matrix[3, :3] = (x, 0.0, 0.0)
    return MatrixTransform(localMatrix=matrix, children=[basenodes.Shape(
        geometry=basenodes.Box(size=(0.05, 0.05, 0.05)),
        appearance=basenodes.Appearance(material=basenodes.Material(
            diffuseColor=(0, 0, 0), emissiveColor=(1, 1, 1))))])


def column(image):
    lit = np.argwhere(image.sum(axis=2) > 200)
    assert len(lit), 'nothing drawn'
    return lit[:, 1].mean()


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_a_shape_far_from_the_origin_is_drawn_where_it_is(gl_context, renderer):
    """The box is 0.2 m left of a camera 1 m away; in single precision both round
    to the same half metre and it would be drawn in the middle"""
    with scene_context([placed(FAR)], size=(64, 64), renderer=renderer) as context:
        context.platform.setPosition((FAR + 0.2, 0.0, 1.0))
        drawn_image(context)
        image = drawn_image(context)
    assert column(image) < 32 - 8


def test_the_path_matrices_are_double_precision():
    from OpenGLContext.scenegraph import nodepath
    transform = placed(FAR)
    path = nodepath.NodePath([]) + basenodes.sceneGraph(children=[transform]) + transform
    assert path.transformMatrix()[3, 0] == pytest.approx(FAR, abs=1e-6)


def test_the_camera_position_is_double_precision():
    from OpenGLContext.move.viewplatform import ViewPlatform
    platform = ViewPlatform()
    platform.setPosition((FAR, 0.0, 0.0))
    assert platform.position[0] == pytest.approx(FAR, abs=1e-6)
    assert abs(platform.modelMatrix(inverse=True)[3, 0]) == pytest.approx(FAR, abs=1e-6)
