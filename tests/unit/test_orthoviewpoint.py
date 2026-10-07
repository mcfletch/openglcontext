"""X3D's OrthoViewpoint, and the viewpoint clip distances.

An ``OrthoViewpoint`` looks through an orthographic window, ``fieldOfView``
as (minimum x, minimum y, maximum x, maximum y) in its own coordinates; the
window is widened along one axis to the shape of the view. A viewpoint's
``nearDistance`` and ``farDistance`` set the clip planes where positive.
"""
import numpy as np
import pytest
from vrml.vrml97 import transformmatrix

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.move import viewplatform
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.scenegraph.basenodes import sceneGraph
from OpenGLContext.scenegraph.viewpoint import OrthoViewpoint, Viewpoint


@pytest.mark.parametrize('aspect, expected', [
    (1.0, (-1.0, -1.0, 1.0, 1.0)),
    (2.0, (-2.0, -1.0, 2.0, 1.0)),
    (0.5, (-1.0, -2.0, 1.0, 2.0)),
])
def test_the_window_is_widened_to_the_views_shape(aspect, expected):
    assert viewplatform.fitted_window((-1, -1, 1, 1), aspect) == pytest.approx(expected)


def test_an_off_centre_window_keeps_its_centre():
    assert viewplatform.fitted_window((0, 0, 2, 1), 1.0) == pytest.approx((0, -0.5, 2, 1.5))


def test_an_orthographic_platform_projects_through_its_window():
    platform = ViewPlatform(aspect=2.0, near=0.5, far=100.0)
    platform.setOrthographic((-1, -1, 1, 1))
    expected = transformmatrix.orthoMatrix(-2, 2, -1, 1, 0.5, 100.0)
    assert np.allclose(platform.viewMatrix(), expected)
    assert np.allclose(platform.viewMatrix(inverse=True), np.linalg.inv(expected), atol=1e-5)


def test_the_passs_negative_trim_leaves_the_orthographic_depth():
    """The pass trims with a negative depth, which a perspective matrix reads
    as a far plane at infinity; an orthographic one keeps its far plane"""
    platform = ViewPlatform(near=0.5, far=100.0)
    platform.setOrthographic((-1, -1, 1, 1))
    assert np.allclose(platform.viewMatrix(-102.01), platform.viewMatrix())
    assert np.allclose(platform.viewMatrix(20.0),
                       transformmatrix.orthoMatrix(-1, 1, -1, 1, 0.5, 20.0))


def test_a_perspective_frustum_ends_the_orthographic_window():
    platform = ViewPlatform()
    platform.setOrthographic((-1, -1, 1, 1))
    platform.setFrustum(1.0)
    assert platform.window is None
    assert platform.viewMatrix()[2, 3] == -1.0


class Path(tuple):
    def transformMatrix(self):
        return np.identity(4)

    def quaternion(self):
        from OpenGLContext import quaternion  # noqa: PLC0415 kept with its use
        return quaternion.fromXYZR(0, 1, 0, 0)


class Viewing:
    def __init__(self):
        self.platform = ViewPlatform()


def test_an_ortho_viewpoint_is_the_engines():
    assert prototypes()['OrthoViewpoint'] is OrthoViewpoint


def test_an_ortho_viewpoint_sets_the_window_and_stands_at_its_position():
    view = OrthoViewpoint(position=(1, 2, 3), fieldOfView=[-4, -3, 4, 3],
                          nearDistance=0.25, farDistance=50.0)
    context = Viewing()
    view.moveTo(Path((sceneGraph(), view)), context)
    assert context.platform.window == (-4.0, -3.0, 4.0, 3.0)
    assert tuple(context.platform.position[:3]) == (1.0, 2.0, 3.0)
    assert context.platform.frustum[2:] == (0.25, 50.0)


def test_an_ortho_viewpoint_with_a_short_field_of_view_has_the_default_window():
    view = OrthoViewpoint(fieldOfView=[-2.0])
    context = Viewing()
    view.moveTo(Path((sceneGraph(), view)), context)
    assert context.platform.window == (-1.0, -1.0, 1.0, 1.0)


def test_a_viewpoints_clip_distances_are_used_where_positive():
    view = Viewpoint(nearDistance=0.5, farDistance=900.0)
    context = Viewing()
    view.moveTo(Path((sceneGraph(), view)), context)
    assert context.platform.frustum[2:] == (0.5, 900.0)
    unset = Viewpoint()
    before = context.platform.frustum[2:]
    unset.moveTo(Path((sceneGraph(), unset)), context)
    assert context.platform.frustum[2:] == before


def test_a_document_drawn_through_an_ortho_viewpoint(gl_context):
    """A unit box in a two-unit window is half the frame wide at any distance"""
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <Background skyColor="0 0 0"/>
      <OrthoViewpoint position="0 0 50" fieldOfView="-1 -1 1 1"/>
      <Shape><Appearance><UnlitMaterial emissiveColor="1 1 1"/></Appearance>
        <Box size="1 1 1"/></Shape>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(96, 96)) as context:
        image = drawn_image(context)
    row = image[48].max(axis=1) > 128
    assert row.sum() == pytest.approx(48, abs=3)
