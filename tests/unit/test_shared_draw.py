"""Which shapes one draw can serve for several views, and how they are grouped.

``FlatPass.sharesDraw`` decides per record whether a single draw, sent to
every view that sees the shape, draws it as each view alone would;
``sharedRecords`` collects those records across the views and groups them by
the set of views each reaches. Both are Python over the frame's records, with
no GL.
"""
import numpy as np
import pytest

from OpenGLContext.multiview.strategy import ViewFrame
from OpenGLContext.multiview.views import View, ViewStyle
from OpenGLContext.passes._flat import FlatPass
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.reflector import PlanarReflector


def _shape(appearance=None, geometry=None):
    return basenodes.Shape(geometry=geometry or basenodes.Sphere(radius=1.0),
                           appearance=appearance or basenodes.Appearance(
                               material=PBRMaterial()))


#: One path per shape, as a frame's walk hands every view the same one.
_PATHS: dict = {}


def _record(shape, transparent=False, x=0.0):
    world = np.identity(4, 'f')
    world[3, 0] = x
    path = _PATHS.setdefault(id(shape), [shape])
    return ((transparent, [], 0.0), world, world, None, path, shape)


@pytest.fixture
def passing():
    return FlatPass.__new__(FlatPass)


class TestOneDrawForEveryView:
    def test_an_opaque_shape_of_shared_geometry_shares(self, passing):
        assert passing.sharesDraw(_record(_shape()))

    def test_a_transparent_shape_is_sorted_per_view(self, passing):
        assert not passing.sharesDraw(_record(_shape(), transparent=True))

    def test_geometry_that_does_not_say_so_is_drawn_per_view(self, passing):
        from OpenGLContext.scenegraph.text.text import Text
        assert not passing.sharesDraw(_record(_shape(geometry=Text(string=['a']))))

    def test_a_mirror_reads_a_reflection_per_view(self, passing):
        material = PBRMaterial(reflector=PlanarReflector())
        assert not passing.sharesDraw(_record(_shape(basenodes.Appearance(material=material))))

    def test_an_appearance_with_its_own_program_is_drawn_per_view(self, passing):
        shader = basenodes.Shader(objects=[])
        assert shader.bringsProgram
        assert not passing.sharesDraw(_record(_shape(shader)))

    @pytest.mark.parametrize('field, value', [('transmission', 0.5),
                                              ('octahedralViews', 8)])
    def test_glass_and_impostors_are_drawn_per_view(self, passing, field, value):
        material = PBRMaterial(**{field: value})
        assert not passing.sharesDraw(_record(_shape(basenodes.Appearance(material=material))))

    def test_a_set_that_culls_its_own_copies_is_drawn_per_view(self, passing):
        shape = _shape()
        shape.visiblePlacements = lambda *args, **named: None
        assert not passing.sharesDraw(_record(shape))


def _frame(x, wireframe=False):
    modelview = np.identity(4, 'f')
    modelview[3, 0] = -x
    view = View(name='at %s' % x, style=ViewStyle(wireframe=wireframe))
    return ViewFrame(view, None, (0, 0, 10, 10), modelview, np.identity(4, 'f'),
                     modelview, None)


class TestTheSharedRecords:
    def test_each_is_grouped_by_the_views_that_see_it(self, passing):
        both, left, right = _shape(), _shape(), _shape()
        first, second = _frame(0.0), _frame(5.0)
        first.toRender = [_record(both), _record(left)]
        second.toRender = [_record(both), _record(right)]
        groups = passing.sharedRecords([first, second], first)
        drawn = {mask: [record[5] for record in records]
                 for mask, records in groups.items()}
        assert drawn == {0b11: [both], 0b01: [left], 0b10: [right]}

    def test_each_is_placed_in_the_reference_views_eye_space(self, passing):
        shape = _shape()
        first, second = _frame(0.0), _frame(5.0)
        second.toRender = [_record(shape, x=2.0)]
        (record,) = passing.sharedRecords([first, second], second)[0b10]
        assert record[1][3, 0] == pytest.approx(-3.0)

    def test_a_wireframe_view_takes_no_part(self, passing):
        shape = _shape()
        solid, wire = _frame(0.0), _frame(5.0, wireframe=True)
        solid.toRender = wire.toRender = [_record(shape)]
        assert list(passing.sharedRecords([solid, wire], solid)) == [0b01]

    def test_nothing_that_shares_is_no_group(self, passing):
        frame = _frame(0.0)
        frame.toRender = [_record(_shape(), transparent=True)]
        assert passing.sharedRecords([frame], frame) == {}
