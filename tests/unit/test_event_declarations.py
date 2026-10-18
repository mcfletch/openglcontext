"""What the engine's field lookups answer for a name a node declares as an event.

`vrml.protofunctions.getField` returns a `Field` or an `Event`. An event holds
no value, so the helpers that ask whether a field was set answer that it was
not, and the pose writer refuses a node whose rotation is one.
"""
import pytest
from vrml import field, node

from OpenGLContext import context, renderoptions
from OpenGLContext.physics import manager
from OpenGLContext.viewer import sceneviewer


class Rung(node.Node):
    """A node with one field and two events"""

    PROTO = 'Rung'
    translation = field.newField('translation', 'SFVec3f', 1, (0.0, 0.0, 0.0))
    rotation = field.newEvent('rotation', 'SFRotation', 0)
    rung = field.newEvent('rung', 'SFBool', 1)
    contextDefinition = property(lambda self: self)


def test_an_event_is_not_a_set_render_option():
    assert renderoptions._value(Rung(), 'rung') is None


def test_an_event_is_not_a_set_definition_field():
    assert context._fieldIsSet(Rung(), 'rung') is False


def test_an_event_is_not_a_set_viewer_field():
    assert sceneviewer._isSet(Rung(), 'rung') is False


def test_a_rotation_that_is_an_event_takes_no_pose():
    with pytest.raises(TypeError, match='Rung.rotation'):
        manager.write_pose(Rung(), (1.0, 2.0, 3.0), (0.0, 1.0, 0.0, 0.5))
