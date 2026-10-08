"""X3D's NURBS geometry as drawn, in both renderers and the compatibility profile"""
import math

import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.testing.scenes import drawn_image, scene_context

SIZE = (64, 64)
PROFILES = [('pbr', 'core'), ('vrml97', 'core'), ('vrml97', 'compatibility')]

#: A square 8 units across facing +z, as a degree-1 patch whose knots run
#: over the square itself.
SQUARE = ('<%(node)s uDimension="2" vDimension="2" uOrder="2" vOrder="2" '
          'uKnot="-4 -4 4 4" vKnot="-4 -4 4 4" %(fields)s>'
          '<Coordinate containerField="controlPoint" point="-4 -4 0 4 -4 0 -4 4 0 4 4 0"/>'
          '%(children)s</%(node)s>')


def square(node='NurbsPatchSurface', fields='', children=''):
    return SQUARE % {'node': node, 'fields': fields, 'children': children}


def document(body, appearance='<Material diffuseColor="0 0 0" emissiveColor="1 0 0"/>'):
    return Loader.loads(('<X3D version="4.0"><Scene><Background skyColor="0 0 0"/>'
                         '<Viewpoint position="0 0 20"/><Shape><Appearance>%s</Appearance>'
                         '%s</Shape></Scene></X3D>' % (appearance, body)).encode(), 'scene.x3d')


def drawn(scene, renderer='pbr', profile='core'):
    with scene_context(scene, size=SIZE, renderer=renderer,
                       environment={'OPENGLCONTEXT_PROFILE': profile}) as context:
        drawn_image(context)
        return drawn_image(context).astype(int)


def red(image):
    return (image[:, :, 0] > 150) & (image[:, :, 1] < 80)


def centre(mask):
    h, w = mask.shape
    return mask[h // 2 - 2:h // 2 + 2, w // 2 - 2:w // 2 + 2].mean()


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_a_patch_surface_draws(gl_context, renderer, profile):
    found = red(drawn(document(square()), renderer, profile))
    assert centre(found) == 1.0
    assert 0.2 < found.mean() < 0.8


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_a_trimmed_surface_has_its_hole(gl_context, renderer, profile):
    hole = ('<Contour2D><ContourPolyline2D controlPoint="-4 -4 4 -4 4 4 -4 4 -4 -4"/></Contour2D>'
            '<Contour2D><ContourPolyline2D controlPoint="-1 -1 1 -1 1 1 -1 1 -1 -1"/></Contour2D>')
    found = red(drawn(document(square('NurbsTrimmedSurface', children=hole)), renderer, profile))
    assert centre(found) == 0.0
    assert found[SIZE[1] // 2, SIZE[0] // 2 - 10]


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_a_solid_surface_is_not_seen_from_behind(gl_context, renderer, profile):
    behind = square(fields='solid="true"').replace('point="-4 -4 0 4 -4 0 -4 4 0 4 4 0"',
                                                     'point="4 -4 0 -4 -4 0 4 4 0 -4 4 0"')
    assert red(drawn(document(behind), renderer, profile)).mean() == 0.0
    both = behind.replace('solid="true"', 'solid="false"')
    assert red(drawn(document(both), renderer, profile)).mean() > 0.2


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_a_texture_is_mapped_across_the_parameters(gl_context, renderer, profile):
    texture = ('<PixelTexture image="2 1 3 0xFF0000 0x00FF00" repeatS="false"/>'
               '<Material diffuseColor="1 1 1"/>')
    image = drawn(document(square(), appearance=texture), renderer, profile)
    row = image[SIZE[1] // 2]
    left, right = row[SIZE[0] // 2 - 8], row[SIZE[0] // 2 + 8]
    assert left[0] > 2 * left[1] and right[1] > 2 * right[0]


CURVE = ('<NurbsCurve order="3" tessellation="32"><Coordinate containerField="controlPoint" '
         'point="-3 0 0 0 3 0 3 0 0"/></NurbsCurve>')


def rows(image):
    """How many rows of the middle column are lit"""
    return int((image[:, SIZE[0] // 2].sum(axis=1) > 200).sum())


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_a_curve_is_drawn_and_widened_by_line_properties(gl_context, renderer, profile):
    white = '<Material emissiveColor="1 1 1"/>'
    plain = rows(drawn(document(CURVE, white), renderer, profile))
    wide = rows(drawn(document(CURVE, white + '<LineProperties linewidthScaleFactor="5"/>'),
                      renderer, profile))
    assert 1 <= plain <= 2
    assert 4 <= wide <= 6


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_a_swept_surface_draws(gl_context, renderer, profile):
    sweep = ('<NurbsSweptSurface solid="false"><NurbsCurve2D containerField="crossSectionCurve" '
             'order="2" controlPoint="-1 -1 1 -1 1 1 -1 1 -1 -1"/>'
             '<NurbsCurve containerField="trajectoryCurve" order="2"><Coordinate '
             'containerField="controlPoint" point="-3 0 0 3 0 0"/></NurbsCurve>'
             '</NurbsSweptSurface>')
    found = red(drawn(document(sweep), renderer, profile))
    assert centre(found) == 1.0


def test_a_swung_surface_draws(gl_context):
    swing = ('<NurbsSwungSurface solid="false"><NurbsCurve2D containerField="profileCurve" '
             'order="2" controlPoint="0.5 -1 0.5 1"/><NurbsCurve2D containerField='
             '"trajectoryCurve" order="3" controlPoint="-3 0 0 3 3 0"/></NurbsSwungSurface>')
    found = red(drawn(document(swing)))
    assert found.mean() > 0.02


def test_a_rational_circle_trim_is_round(gl_context):
    root = math.sqrt(0.5)
    # the corner points are given multiplied by their weights
    circle = ('<Contour2D><ContourPolyline2D controlPoint="-4 -4 4 -4 4 4 -4 4 -4 -4"/></Contour2D>'
              '<Contour2D><NurbsCurve2D order="3" tessellation="64" knot="0 0 0 1 1 2 2 3 3 4 4 4" '
              'weight="1 %(w)g 1 %(w)g 1 %(w)g 1 %(w)g 1" controlPoint="2 0 %(c)r %(c)r 0 2 '
              '-%(c)r %(c)r -2 0 -%(c)r -%(c)r 0 -2 %(c)r -%(c)r 2 0"/></Contour2D>'
              ) % {'w': root, 'c': 2 * root}
    found = red(drawn(document(square('NurbsTrimmedSurface', children=circle))))
    # A disc of radius 2 is cut from the 8 by 8 square
    inside = found[found.any(axis=1)][:, found.any(axis=0)]
    assert 1.0 - inside.mean() == pytest.approx(math.pi * 4 / 64, rel=0.15)
