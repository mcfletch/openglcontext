"""``shadowDistance``: how far from the camera shadows are made, and where they fade out."""
import numpy as np
import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.passes import shadowmath
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.scenes import drawn_image, scene_context


def test_the_fade_covers_the_last_fifth_of_the_distance():
    start, end = shadowmath.shadow_fade(100.0)
    assert (start, end) == pytest.approx((80.0, 100.0))


@pytest.mark.parametrize('distance', [0.0, -5.0, float('nan'), float('inf')])
def test_no_usable_distance_is_no_fade(distance):
    assert shadowmath.shadow_fade(distance) is None


def test_the_definition_has_the_field_and_it_defaults_to_the_farthest_occluder():
    assert ContextDefinition().shadowDistance == 0.0


def _slab(centre, size):
    return basenodes.Transform(translation=centre, children=[basenodes.Shape(
        geometry=basenodes.Box(size=size),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(1, 1, 1))))])


def _long_floor(**definition):
    """A floor running away from the camera with a small slab hovering over it every 20 m.

    The sun slants across the floor so each slab's shadow falls beside it, in view.
    """
    floor = _slab((0, -1, -60), (60, 0.1, 140))
    slabs = [_slab((0, 1, -z), (2, 0.2, 2)) for z in (10, 30, 50, 70, 90)]
    sun = basenodes.DirectionalLight(direction=(1, -1, 0), intensity=1.0, shadows=True)
    eye = basenodes.Viewpoint(position=(-4, 6, 0), orientation=(1, 0, 0, -0.35))
    with scene_context([eye, basenodes.NavigationInfo(headlight=False), sun, floor, *slabs],
                       size=(96, 96), shadowCascades=3, **definition) as context:
        for _ in range(3):
            context.OnDraw(force=1)
        return drawn_image(context).astype(float).mean(axis=2)


@pytest.fixture
def unshadowed(gl_context):
    return _long_floor(shadows=False)


@pytest.fixture
def unlimited(gl_context):
    return _long_floor()


@pytest.fixture
def limited(gl_context):
    return _long_floor(shadowDistance=40.0)


def _shadow(unshadowed, image):
    """How much darker each pixel is for the shadows, as a share of the brightest floor."""
    return (unshadowed - image) / unshadowed.max()


#: Rows of the picture: the slab 10 m out casts its shadow low in it, the one 30 m out in the
#: middle, and the one 90 m out near the top.
NEAR, MIDDLE, FAR = slice(70, 80), slice(30, 40), slice(10, 20)


def test_shadows_within_the_distance_are_made(unshadowed, unlimited, limited):
    for rows in (NEAR, MIDDLE):
        assert _shadow(unshadowed, unlimited)[rows].max() > 0.3
        assert _shadow(unshadowed, limited)[rows].max() == pytest.approx(
            _shadow(unshadowed, unlimited)[rows].max(), abs=0.05)


def test_shadows_beyond_the_distance_are_not_there(unshadowed, unlimited, limited):
    assert _shadow(unshadowed, unlimited)[FAR].max() > 0.3
    assert _shadow(unshadowed, limited)[FAR].max() < 0.05


def test_a_shadow_in_the_last_fifth_of_the_distance_is_part_way_faded(unshadowed, unlimited):
    faded = _long_floor(shadowDistance=33.0)
    full = _shadow(unshadowed, unlimited)[MIDDLE].max()
    part = _shadow(unshadowed, faded)[MIDDLE].max()
    assert 0.1 * full < part < 0.9 * full
