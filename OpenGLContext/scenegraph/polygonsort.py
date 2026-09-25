"""Depth sorting for transparent triangle geometry

Alpha blending is order-dependent, so transparent triangles are drawn back to
front.  Sorting them means one distance per triangle and an index array in the
sorted order::

    from OpenGLContext.triangleutilities import centers
    from OpenGLContext.scenegraph import polygonsort

    middles = centers( vertices )        # object space, once per geometry
    order = polygonsort.indices(         # every transparent pass
        polygonsort.distances(
            middles,
            modelView=mode.getModelView(),
            projection=mode.getProjection(),
            viewport=mode.getViewport(),
        )
    ).astype( 'I' )
    glDrawElements( GL_TRIANGLES, order.size, GL_UNSIGNED_INT, order )

:func:`distances` reports window z, which grows with distance from the eye;
:func:`indices` puts the largest first.  :func:`project` is the same
transformation carried through to window x and y as well, which is what
``gluProject`` gives for a single point.
"""
from typing import Any

# Named rather than star-imported: this module's own ``indices`` would otherwise
# collide with numpy's.
from OpenGLContext.arrays import arange, argsort, dot, ones, reshape, take
from numpy import where
from OpenGL.GL import *

__all__ = ['project', 'distances', 'indices', 'sortIndex']


#: The smallest ``w`` a clip-space point is divided by. A point in the eye's
#: own plane has ``w`` of 0, and a triangle reaching it is still sorted.
_SMALLEST_W = 1e-12


def _normalized(clip: Any) -> Any:
    """``(N, 3)`` normalized device coordinates of ``(N, 4)`` clip-space points.

    A ``w`` nearer 0 than :data:`_SMALLEST_W` is taken as that, with its sign,
    so a point in the eye's plane lies far off rather than at infinity or NaN.
    """
    w = clip[:, 3:4].astype('d')
    w = where( abs(w) < _SMALLEST_W, where( w < 0, -_SMALLEST_W, _SMALLEST_W ), w )
    return clip[:, :3] / w


def project(
    points: Any,
    modelView: Any = None,
    projection: Any = None,
    viewport: Any = None,
    astype: str = 'f',
) -> Any:
    """Window coordinates for every point, as ``gluProject`` gives for one"""
    if modelView is None:
        modelView = glGetFloatv( GL_MODELVIEW_MATRIX )
    if projection is None:
        projection = glGetFloatv( GL_PROJECTION_MATRIX )
    if viewport is None:
        viewport = glGetIntegerv( GL_VIEWPORT )
    M = dot( modelView, projection )
    if points.shape[-1] != 4:
        newpoints = ones( points.shape[:-1]+(4,), 'f')
        newpoints[:,:3] = points
        points = newpoints
    v = _normalized( dot( points, M ) )
    v += 1.0
    v /= 2.0
    v[:,0:2] *= viewport[2:4]
    v[:,0:2] += viewport[0:2]
    return v.astype(astype)


def distances(
    points: Any,
    modelView: Any = None,
    projection: Any = None,
    viewport: Any = None,
    astype: str = 'f',
) -> Any:
    """Window z for the given points, growing with distance from the eye

    Does less work than a full project operation, as it
    doesn't need to calculate the x/y values.
    """
    if modelView is None:
        modelView = glGetFloatv( GL_MODELVIEW_MATRIX )
    if projection is None:
        projection = glGetFloatv( GL_PROJECTION_MATRIX )
    if viewport is None:
        viewport = glGetIntegerv( GL_VIEWPORT )
    if points.shape[-1] != 4:
        newpoints = ones( points.shape[:-1]+(4,), 'f')
        newpoints[:,:3] = points
        points = newpoints
    M = dot( modelView, projection )
    v = _normalized( dot( points, M ) )
    return ((v[:,2]+1.0)/2.0).astype(astype)


def indices( zFloats: Any ) -> Any:
    """Triangle-vertex indices in back-to-front order

    zFloats -- one window z per triangle, as :func:`distances` calculates

    The triangles are assumed to be consecutive triples of vertices, so
    triangle ``i`` is vertices ``3i``, ``3i+1`` and ``3i+2``.  The farthest
    triangle comes first, which is the order alpha blending composites in.
    """
    firstVertex = argsort( zFloats )[::-1] * 3
    return (firstVertex.reshape( (-1,1) ) + arange( 3 )).ravel()


def sortIndex( index: Any, zFloats: Any, polygonSides: int = 3 ) -> Any:
    """Reorder an indexed polygon set to draw back to front

    index -- flat vertex-index array, ``polygonSides`` entries per polygon
    zFloats -- one window z per polygon, as :func:`distances` calculates
    polygonSides -- how many vertices each polygon has

    Returns one polygon per row, farthest first.  The vertex indices themselves
    are untouched: only the polygons move, so the winding of each is preserved.
    """
    order = argsort( zFloats )[::-1]
    return take( reshape( index, (-1, polygonSides) ), order, 0 )
