"""How ``IndexedPolygons`` hands its vertex arrays to the fixed-function pipeline.

``get_vbos`` answers a holder whose ``_enable*`` methods set the client arrays.
Which holder it is depends on whether the driver has buffer objects: with them,
each array is uploaded and the pointer calls name an offset in the bound buffer;
without them the pointer calls have to be given client memory, so the holder
carries the arrays themselves.
"""

import numpy as np
import pytest

from OpenGL.arrays import vbo
from vrml.vrml97 import basenodes

from OpenGLContext.scenegraph import indexedpolygons


@pytest.fixture
def node():
    return indexedpolygons.IndexedPolygons(
        coord=basenodes.Coordinate(point=[[0, 0, 0], [1, 0, 0], [1, 1, 0]]),
        index=[0, 1, 2],
        polygonSides=3,
    )


def test_without_buffer_objects_the_holder_carries_client_arrays(node, monkeypatch):
    """A driver with no VBO support is given the arrays, not buffer objects."""
    monkeypatch.setattr(vbo, 'get_implementation', lambda *args: None)
    holder = node.get_vbos(None)
    assert isinstance(holder, indexedpolygons.Holder)
    assert not isinstance(holder, indexedpolygons.VBOHolder)
    assert not hasattr(holder.coord, 'bind')
    assert np.asarray(holder.coord).tolist() == [[0, 0, 0], [1, 0, 0], [1, 1, 0]]


def test_a_node_without_normals_leaves_that_array_empty(node, monkeypatch):
    monkeypatch.setattr(vbo, 'get_implementation', lambda *args: None)
    holder = node.get_vbos(None)
    assert holder.normal is None
    assert holder.color is None
    assert holder.texCoord is None
