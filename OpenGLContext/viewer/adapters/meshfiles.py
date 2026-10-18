"""Opening an STL, PLY or OFF model.

Each holds one mesh in coordinates of its modeller's choosing, with no
cameras, lights or sky, as an OBJ does: :mod:`OpenGLContext.loaders.meshfiles`
reads it and the viewer frames it.
"""
from OpenGLContext.viewer.adapters.obj import OBJAdapter

__all__ = ['OFFAdapter', 'PLYAdapter', 'STLAdapter']


class STLAdapter(OBJAdapter):
    """An STL model, ASCII or binary."""

    name = 'stl'


class PLYAdapter(OBJAdapter):
    """A PLY model, point cloud or 3D Gaussian splat set."""

    name = 'ply'


class OFFAdapter(OBJAdapter):
    """An OFF model."""

    name = 'off'
