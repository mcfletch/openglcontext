"""A Shape whose appearance or geometry is an instance of an EXTERNPROTO
that was not read (Basic/development/ExampleExternPrototype2).

Such an instance stands for no node. As X_ITE reads a field holding a node
of the wrong type, the Shape draws as if the field were empty: no geometry
draws nothing, and no appearance is the default appearance.
"""
from vrml import node

from OpenGLContext.scenegraph.basenodes import Appearance, Box, Material, Shape


def unread(name):
    """An instance of an EXTERNPROTO whose file was never read"""
    return node.prototype(name, [], externalURL=['https://example.invalid/x.wrl#%s' % name])()


def test_an_unread_geometry_draws_nothing():
    assert Shape(geometry=unread('MyNodeGeometry')).drawsNothing()


def test_no_geometry_draws_nothing():
    assert Shape().drawsNothing()


def test_a_geometry_draws():
    assert not Shape(geometry=Box()).drawsNothing()


def test_an_unread_appearance_is_the_default_appearance():
    shape = Shape(appearance=unread('MyNodeAppearance'), geometry=Box())
    assert shape.drawnAppearance is None
    assert shape.sortKey(None, None) == Shape(geometry=Box()).sortKey(None, None)


def test_an_appearance_is_drawn():
    appearance = Appearance(material=Material())
    assert Shape(appearance=appearance, geometry=Box()).drawnAppearance is appearance
