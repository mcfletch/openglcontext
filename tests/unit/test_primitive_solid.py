"""X3D's `solid` on the primitives: false draws their insides as well"""
import pytest

from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, Cone, Cylinder, Group, Material, Shape, Sphere, Viewpoint,
)
from OpenGLContext.testing.scenes import drawn_image, scene_context


def inside(geometry, renderer, environment=None):
    """The centre pixel's green, seen from within `geometry`"""
    shape = Shape(geometry=geometry,
                  appearance=Appearance(material=Material(diffuseColor=(0, 0, 0),
                                                          emissiveColor=(0, 1, 0))))
    with scene_context([Viewpoint(position=(0, 0, 0)), Group(children=[shape])],
                       renderer=renderer, environment=environment or {}) as context:
        drawn_image(context)
        return int(drawn_image(context)[48, 48, 1])


PRIMITIVES = [
    pytest.param(lambda solid: Box(size=(4, 4, 4), solid=solid), id='Box'),
    pytest.param(lambda solid: Sphere(radius=3, solid=solid), id='Sphere'),
    pytest.param(lambda solid: Cylinder(radius=3, height=20, solid=solid), id='Cylinder'),
    pytest.param(lambda solid: Cone(bottomRadius=3, height=20, solid=solid), id='Cone'),
]


@pytest.mark.parametrize('make', PRIMITIVES)
@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_a_primitive_that_is_not_solid_is_seen_from_inside(make, renderer):
    assert inside(make(False), renderer) > 200
    assert inside(make(True), renderer) < 40


@pytest.mark.parametrize('make', PRIMITIVES)
def test_the_compatibility_profile_draws_the_inside_too(make):
    environment = {'OPENGLCONTEXT_PROFILE': 'compatibility'}
    assert inside(make(False), 'vrml97', environment) > 200
    assert inside(make(True), 'vrml97', environment) < 40


@pytest.mark.parametrize('make', PRIMITIVES)
def test_solid_and_open_primitives_are_not_one_instanced_draw(make):
    assert make(True).instanceContentKey() != make(False).instanceContentKey()
