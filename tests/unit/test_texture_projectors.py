"""X3D's texture projectors: where each casts, and what it casts there

The projection is checked without GL (``projector_matrix``); the casting by
what a white square shows with a projector in front of it.
"""
import math

import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.textureprojector import (
    TextureProjector, TextureProjectorParallel, is_projector, projector_matrix,
)


def cast(projection, point):
    clip = np.append(np.asarray(point, float), 1.0) @ projection.matrix
    return clip[:3] / clip[3], clip[3]


def test_a_projector_casts_its_centre_along_its_direction():
    projector = TextureProjector(location=(0, 0, 2), direction=(0, 0, -1))
    found, w = cast(projector_matrix(projector), (0, 0, 0))
    assert w > 0
    assert found[:2] == pytest.approx((0, 0), abs=1e-6)


def test_its_field_of_view_is_the_smaller_angle():
    angle = math.radians(60)
    projector = TextureProjector(location=(0, 0, 0), direction=(0, 0, -1), fieldOfView=angle)
    edge = math.tan(angle / 2)
    wide = projector_matrix(projector, aspect=2.0)
    found, _w = cast(wide, (0, edge, -1))
    assert found[1] == pytest.approx(1.0, abs=1e-5)       # the height is the field
    found, _w = cast(wide, (2 * edge, 0, -1))
    assert found[0] == pytest.approx(1.0, abs=1e-5)
    tall = projector_matrix(projector, aspect=0.5)
    found, _w = cast(tall, (edge, 0, -1))
    assert found[0] == pytest.approx(1.0, abs=1e-5)       # the width is the field


def test_behind_a_projector_nothing_is_cast():
    projector = TextureProjector(location=(0, 0, 0), direction=(0, 0, -1))
    _found, w = cast(projector_matrix(projector), (0, 0, 1))
    assert w < 0


def test_its_world_matrix_places_it():
    projector = TextureProjector(location=(0, 0, 0), direction=(0, 0, -1))
    world = np.identity(4)
    world[3, :3] = (5, 0, 0)
    found, w = cast(projector_matrix(projector, world), (5, 0, -3))
    assert w > 0 and found[:2] == pytest.approx((0, 0), abs=1e-6)
    assert projector_matrix(projector, world).location == pytest.approx((5, 0, 0))


def test_its_up_vector_turns_the_picture():
    projector = TextureProjector(location=(0, 0, 0), direction=(0, 0, -1), upVector=(1, 0, 0))
    found, _w = cast(projector_matrix(projector), (0.1, 0, -1))
    assert found[1] > 0 and found[0] == pytest.approx(0, abs=1e-6)


def test_a_parallel_projector_casts_its_rectangle_straight():
    projector = TextureProjectorParallel(location=(0, 0, 0), direction=(0, 0, -1),
                                         fieldOfView=(-2, -1, 2, 1))
    projection = projector_matrix(projector)
    for depth in (-1, -50):
        found, w = cast(projection, (2, 1, depth))
        assert w == pytest.approx(1.0)
        assert found[:2] == pytest.approx((1, 1))
    assert not projection.perspective


def test_near_and_far_bound_it_where_given():
    projector = TextureProjector(location=(0, 0, 0), direction=(0, 0, -1),
                                 nearDistance=1, farDistance=4)
    projection = projector_matrix(projector)
    assert projection.bounded == (True, True)
    assert cast(projection, (0, 0, -0.5))[0][2] < -1
    assert cast(projection, (0, 0, -5))[0][2] > 1
    assert projector_matrix(TextureProjector()).bounded == (False, False)


@pytest.mark.parametrize('field', [0.0, -1.0, 4.0])
def test_a_field_of_view_no_projection_has_casts_nothing(field):
    assert projector_matrix(TextureProjector(fieldOfView=field)) is None
    assert projector_matrix(TextureProjectorParallel(fieldOfView=(1, 1, -1, -1))) is None


def test_a_projector_is_not_a_lamp():
    assert is_projector(TextureProjector())
    assert not is_projector(x3d.PointLight())


RENDERERS = ['pbr', 'vrml97']

RED = b'<PixelTexture containerField="texture" image="1 1 3 0xFF0000"/>'
SQUARE = (b'<Shape DEF="Square"><Appearance><UnlitMaterial emissiveColor="1 1 1"/></Appearance>'
          b'<IndexedTriangleSet index="0 1 2 0 2 3" solid="false">'
          b'<Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/></IndexedTriangleSet></Shape>')


def drawn(body, renderer, size=64):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'<X3D version="4.0"><Scene><Background skyColor="0 0 0"/>'
                         b'<Viewpoint position="0 0 2.4"/>' + body + b'</Scene></X3D>',
                         'scene.x3d')
    with scene_context(scene, size=(size, size), renderer=renderer) as context:
        context.OnDraw(force=1)
        return drawn_image(context).astype(int)


def close(found, expected, tolerance=8):
    return all(abs(a - b) <= tolerance for a, b in zip(found, expected))


def projector(fields=b''):
    return (b'<TextureProjector location="0 0 2" direction="0 0 -1" fieldOfView="0.2" %s>'
            % fields + RED + b'</TextureProjector>')


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_projector_casts_its_picture_where_it_falls(gl_context, renderer):
    image = drawn(projector() + SQUARE, renderer)
    assert close(tuple(image[32, 32]), (255, 0, 0)), tuple(image[32, 32])
    # Outside its narrow field, the square's own white.
    assert close(tuple(image[32, 6]), (255, 255, 255)), tuple(image[32, 6])


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_projector_casts_its_colour_by_its_intensity(gl_context, renderer):
    image = drawn(projector(b'intensity="0.5"') + SQUARE, renderer)
    found = tuple(image[32, 32])
    assert found[0] > 240 and 100 < found[1] < 230, found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_projector_off_casts_nothing(gl_context, renderer):
    image = drawn(projector(b'on="false"') + SQUARE, renderer)
    assert close(tuple(image[32, 32]), (255, 255, 255))


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_scoped_projector_casts_only_on_its_group(gl_context, renderer):
    body = b'<Group>' + projector(b'global="false"') + b'</Group>' + SQUARE
    image = drawn(body, renderer)
    assert close(tuple(image[32, 32]), (255, 255, 255)), tuple(image[32, 32])
    body = b'<Group>' + projector(b'global="false"') + SQUARE + b'</Group>'
    image = drawn(body, renderer)
    assert close(tuple(image[32, 32]), (255, 0, 0)), tuple(image[32, 32])


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_projector_does_not_light_as_a_lamp(gl_context, renderer):
    # A lit grey square: the projector adds no light of its own.
    lit = (b'<Shape><Appearance><Material diffuseColor="0.5 0.5 0.5"/></Appearance>'
           b'<IndexedTriangleSet index="0 1 2 0 2 3" solid="false">'
           b'<Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/></IndexedTriangleSet></Shape>')
    nav = b'<NavigationInfo headlight="false"/>'
    aside = (b'<TextureProjector location="5 0 2" direction="0 0 -1" fieldOfView="0.2">'
             + RED + b'</TextureProjector>')
    image = drawn(nav + aside + lit, renderer)
    assert tuple(image[32, 32])[0] < 10


def test_a_projector_sends_its_pictures_proportions(gl_context):
    wide = b'<PixelTexture containerField="texture" image="2 1 3 0xFF0000 0xFF0000"/>'
    body = (b'<TextureProjector DEF="P" location="0 0 2" direction="0 0 -1">' + wide
            + b'</TextureProjector>' + SQUARE)
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'<X3D version="4.0"><Scene>' + body + b'</Scene></X3D>', 'scene.x3d')
    with scene_context(scene, size=(16, 16)) as context:
        context.OnDraw(force=1)
        assert scene.getDEF('P').aspectRatio == pytest.approx(2.0)
