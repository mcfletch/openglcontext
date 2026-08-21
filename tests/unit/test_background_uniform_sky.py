"""A Background of one colour paints that colour
(:class:`OpenGLContext.scenegraph.background.Background`).

VRML97 gives ``skyColor`` a matching ``skyAngle`` for every stop after the
first, so a single colour with no angle is the ordinary way to say "the sky is
this colour all over".  It is also the first thing anyone writes when they want
a background that is not black.

``colorSet`` compounds the sky and ground stops into one angle:colour set, and
returned nothing at all when there were no angles and no ground -- which is
exactly the single-colour case.  The sphere is skipped when the set is empty,
so the frame kept whatever the buffer was cleared to.
"""
from math import pi

from OpenGLContext.scenegraph.background import Background

BLUE = (0.3, 0.5, 0.9)


class TestOneSkyColour:
    def test_it_produces_a_set_rather_than_nothing(self):
        assert len(Background(skyColor=[BLUE]).colorSet())

    def test_the_set_spans_the_whole_sphere(self):
        found = Background(skyColor=[BLUE]).colorSet()
        assert float(found[0][0]) == 0.0
        assert abs(float(found[-1][0]) - pi) < 1e-5

    def test_every_stop_is_that_colour(self):
        for stop in Background(skyColor=[BLUE]).colorSet():
            assert tuple(round(float(v), 5) for v in stop[1:]) == BLUE


class TestTheSphereIsDrawable:
    """An angle set is not enough on its own: it has to describe a surface.

    ``buildSphere`` lays a vertex pair per stop *between* the poles, so a set
    of only the two poles yields two vertices, no triangles, and a frame that
    keeps whatever it was cleared to -- which looks exactly like the empty set
    it replaced.
    """

    def test_it_has_vertices_to_rasterise(self):
        background = Background(skyColor=[BLUE])
        vertices, _colors = background.buildSphere(background.colorSet())
        assert len(vertices) > 2

    def test_every_vertex_carries_the_colour(self):
        background = Background(skyColor=[BLUE])
        _vertices, colors = background.buildSphere(background.colorSet())
        for colour in colors:
            assert tuple(round(float(v), 5) for v in colour) == BLUE


class TestTheOtherCasesAreUnchanged:
    def test_nothing_at_all_is_still_nothing(self):
        assert not len(Background(skyColor=[]).colorSet())

    def test_a_gradient_still_has_its_stops(self):
        found = Background(skyColor=[BLUE, (0.7, 0.8, 1.0)],
                           skyAngle=[1.57]).colorSet()
        assert len(found) == 4
        assert abs(float(found[1][0]) - 1.57) < 1e-5

    def test_ground_colours_still_reach_the_set(self):
        found = Background(skyColor=[BLUE], groundColor=[(0.2, 0.15, 0.1)],
                           groundAngle=[1.4]).colorSet()
        assert len(found)
