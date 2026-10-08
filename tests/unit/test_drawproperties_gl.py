"""Tests for X3D's line, point and fill properties as drawn"""
import numpy as np
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.scenes import drawn_image, scene_context

SIZE = (64, 64)


def drawn(scene, renderer='pbr'):
    with scene_context(scene, size=SIZE, renderer=renderer) as context:
        drawn_image(context)
        return drawn_image(context).astype(int)


def document(body, appearance=''):
    return Loader.loads(('<X3D version="4.0"><Scene><Background skyColor="0 0 0"/>'
                         '<Viewpoint position="0 0 10"/><Shape><Appearance>'
                         '<Material emissiveColor="1 1 1"/>%s</Appearance>%s</Shape>'
                         '</Scene></X3D>' % (appearance, body)).encode(), 'scene.x3d')


def lit(image):
    return int((image.sum(axis=2) > 200).sum())


POINT = '<PointSet><Coordinate point="0 0 0"/></PointSet>'


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_point_properties_size_a_point(gl_context, renderer):
    plain = lit(drawn(document(POINT), renderer))
    large = lit(drawn(document(POINT, '<PointProperties pointSizeScaleFactor="8" '
                                      'pointSizeMaxValue="8"/>'), renderer))
    assert plain <= 4
    assert 40 <= large <= 80


def test_attenuation_shrinks_a_distant_point(gl_context):
    near = lit(drawn(document(POINT, '<PointProperties pointSizeScaleFactor="8" '
                                     'pointSizeMaxValue="8" attenuation="0 1 0"/>')))
    assert near <= 4


@pytest.mark.parametrize('coloured', [False, True])
def test_a_point_sets_own_size_is_drawn(gl_context, coloured):
    colour = basenodes.Color(color=[(1, 1, 1)]) if coloured else None
    points = basenodes.PointSet(coord=basenodes.Coordinate(point=[(0, 0, 0)]),
                                color=colour, size=6)
    shape = basenodes.Shape(geometry=points, appearance=basenodes.Appearance(
        material=basenodes.Material(diffuseColor=(0, 0, 0), emissiveColor=(1, 1, 1))))
    count = lit(drawn([basenodes.Viewpoint(position=(0, 0, 10)), shape]))
    assert 20 <= count <= 50


LINE = '<IndexedLineSet coordIndex="0 1"><Coordinate point="-3 0 0 3 0 0"/></IndexedLineSet>'
COLOURED_LINE = ('<IndexedLineSet coordIndex="0 1"><Coordinate point="-3 0 0 3 0 0"/>'
                 '<Color color="1 1 1 1 1 1"/></IndexedLineSet>')
PROFILES = [('pbr', 'core'), ('vrml97', 'core'), ('vrml97', 'compatibility')]


def drawn_in(scene, renderer, profile):
    with scene_context(scene, size=SIZE, renderer=renderer,
                       environment={'OPENGLCONTEXT_PROFILE': profile}) as context:
        drawn_image(context)
        return drawn_image(context).astype(int)


def rows(image):
    """How many rows of the image's middle column are lit"""
    return int((image[:, SIZE[0] // 2].sum(axis=1) > 200).sum())


def runs(image):
    """How many separate lit runs the line's brightest row has"""
    lit_rows = image.sum(axis=2) > 200
    row = lit_rows[int(lit_rows.sum(axis=1).argmax())]
    return int(np.count_nonzero(row[1:] & ~row[:-1]) + row[0])


@pytest.mark.parametrize('renderer, profile', PROFILES)
@pytest.mark.parametrize('line', [LINE, COLOURED_LINE])
def test_the_scale_factor_widens_a_line(gl_context, renderer, profile, line):
    plain = rows(drawn_in(document(line), renderer, profile))
    wide = rows(drawn_in(document(line, '<LineProperties linewidthScaleFactor="5"/>'),
                         renderer, profile))
    assert plain <= 2
    assert 4 <= wide <= 6


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_a_dashed_line_has_gaps(gl_context, renderer, profile):
    solid = runs(drawn_in(document(LINE, '<LineProperties linewidthScaleFactor="2"/>'),
                          renderer, profile))
    dashed = runs(drawn_in(document(LINE, '<LineProperties linetype="2" '
                                          'linewidthScaleFactor="2"/>'), renderer, profile))
    assert solid == 1
    assert dashed >= 2


SQUARE = ('<IndexedFaceSet solid="false" coordIndex="0 1 2 3"><Coordinate '
          'point="-4 -4 0 4 -4 0 4 4 0 -4 4 0"/></IndexedFaceSet>')


def colours(image):
    """The share of the image that is red, and that is green"""
    red = (image[:, :, 0] > 150) & (image[:, :, 1] < 80)
    green = (image[:, :, 1] > 150) & (image[:, :, 0] < 80)
    return red.mean(), green.mean()


def red_document(body, fill=''):
    return Loader.loads(('<X3D version="4.0"><Scene><Background skyColor="0 0 0"/>'
                         '<Viewpoint position="0 0 10"/><Shape><Appearance>'
                         '<Material diffuseColor="0 0 0" emissiveColor="1 0 0"/>%s'
                         '</Appearance>%s</Shape></Scene></X3D>' % (fill, body)).encode(),
                        'scene.x3d')


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_a_hatch_is_drawn_over_the_fill(gl_context, renderer, profile):
    plain_red, plain_green = colours(drawn_in(red_document(SQUARE), renderer, profile))
    red, green = colours(drawn_in(red_document(
        SQUARE, '<FillProperties hatchStyle="5" hatchColor="0 1 0"/>'), renderer, profile))
    assert plain_red > 0.5 and plain_green == 0
    assert 0.1 < green < 0.4 and red > 0.3


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_unfilled_draws_only_the_hatch(gl_context, renderer, profile):
    red, green = colours(drawn_in(red_document(
        SQUARE, '<FillProperties filled="false" hatchStyle="1" hatchColor="0 1 0"/>'),
        renderer, profile))
    assert red == 0 and 0.05 < green < 0.2


def test_a_shape_after_a_hatched_one_is_plain(gl_context):
    hatched = red_document(SQUARE, '<FillProperties hatchStyle="5" hatchColor="0 1 0"/>')
    scene = list(hatched.children) + [basenodes.Transform(
        translation=(0, 0, 1), children=[basenodes.Shape(
            geometry=basenodes.Box(size=(3, 3, 0.1)),
            appearance=basenodes.Appearance(material=basenodes.Material(
                diffuseColor=(0, 0, 0), emissiveColor=(0, 0, 1))))])]
    image = drawn(scene)
    centre = image[28:36, 28:36].reshape(-1, 3)
    assert (centre[:, 1] < 80).all() and (centre[:, 2] > 150).all()


@pytest.mark.parametrize('renderer, profile', PROFILES)
def test_fill_properties_leave_a_line_alone(gl_context, renderer, profile):
    image = drawn_in(document(LINE, '<FillProperties filled="false" hatched="false"/>'),
                     renderer, profile)
    assert rows(image) >= 1
