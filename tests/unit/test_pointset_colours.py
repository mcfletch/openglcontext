"""A PointSet's colours (X3D 19775-1, 11.4.11): one per point, the first of a
Color node holding more; with fewer, the points take the appearance's colour.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.basenodes import Color, Coordinate, PointSet


def points(count, colours):
    return PointSet(coord=Coordinate(point=[(i, 0, 0) for i in range(count)]),
                    color=Color(color=[(0, 1, 0)] * colours))


@pytest.mark.parametrize('colours', [3, 5])
def test_as_many_colours_or_more_colour_every_point(colours):
    found = points(3, colours).pointColours()
    assert found is not None and found.shape == (3, 3)
    assert np.all(found == (0, 1, 0))


def test_fewer_colours_colour_none(caplog):
    assert points(3, 2).pointColours() is None
    assert 'fewer colours' in caplog.text


def test_no_colour_node_colours_none():
    assert PointSet(coord=Coordinate(point=[(0, 0, 0)])).pointColours() is None


def test_extra_colours_are_drawn(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    steps = np.linspace(-6.0, 6.0, 61)
    grid = ' '.join('%g %g -10' % (x, y) for x in steps for y in steps)
    colours = ' '.join(['0 1 0'] * (len(steps) ** 2 + 10))
    scene = Loader.loads((
        '<X3D version="3.3"><Scene><Viewpoint position="0 0 0"/><Shape><PointSet>'
        '<Coordinate point="%s"/><Color color="%s"/></PointSet></Shape></Scene></X3D>'
        % (grid, colours)).encode(), 'a.x3d')
    with scene_context(scene, size=(32, 32)) as context:
        drawn_image(context)
        centre = drawn_image(context)[8:24, 8:24].reshape(-1, 3).astype(int)
    brightest = centre[centre.sum(axis=1).argmax()]
    assert brightest[1] > 200 and brightest[0] < 50, brightest
