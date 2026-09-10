"""A grouping node's ``children`` field, set, deleted, and watched for sensors.

``children`` carries a flag with it: a group holding a pointing sensor is itself
sensitive, so the pick pass knows to offer it events.  The flag is recomputed
whenever the field is written, and cleared when the field is deleted -- and
deleting a VRML field puts it back to its default, which for ``children`` is an
empty list.
"""

from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.shape import Shape
from vrml.vrml97.basenodes import TouchSensor


class TestSensitivityFollowsTheChildren:
    def test_a_group_of_plain_shapes_is_not_sensitive(self):
        assert not Group(children=[Shape(), Shape()]).sensitive

    def test_a_group_holding_a_pointing_sensor_is_sensitive(self):
        assert Group(children=[Shape(), TouchSensor()]).sensitive

    def test_replacing_the_children_recomputes_the_flag(self):
        group = Group(children=[TouchSensor()])
        assert group.sensitive
        group.children = [Shape()]
        assert not group.sensitive


class TestDeletingTheChildren:
    def test_the_children_go_back_to_the_default(self):
        group = Group(children=[Shape(), Shape()])
        del group.children
        assert list(group.children) == []

    def test_the_group_is_no_longer_sensitive(self):
        group = Group(children=[TouchSensor()])
        assert group.sensitive
        del group.children
        assert not group.sensitive

    def test_the_typed_view_agrees_afterwards(self):
        group = Group(children=[Shape(), Shape()])
        assert len(list(group.renderedChildren())) == 2
        del group.children
        assert list(group.renderedChildren()) == []
