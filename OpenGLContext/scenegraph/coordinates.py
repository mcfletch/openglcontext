"""A coordinate node's points in the scene's coordinates; no GL

Geometry reads its points through :func:`points` rather than a coordinate
node's `point` field: a `Coordinate` or `CoordinateDouble` holds them as they
are, and a `GeoCoordinate` holds geodetic, UTM or geocentric coordinates that
:meth:`~OpenGLContext.scenegraph.geospatial.GeoCoordinate.scenePoints`
converts. :func:`fields` names what the points depend on, for a cache to
depend on.
"""
from __future__ import annotations

from typing import Any

__all__ = ['fields', 'points']


def points(coord: Any) -> Any:
    """`coord`'s points in the scene's coordinates; None for no node"""
    if not coord:
        return None
    converted = getattr(coord, 'scenePoints', None)
    if converted is not None:
        return converted()
    return coord.point


def fields(coord: Any) -> list[tuple[Any, str]]:
    """(node, field name) for each field `coord`'s points are worked out from"""
    if not coord:
        return []
    found = getattr(coord, 'pointFields', None)
    if found is not None:
        listed: list[tuple[Any, str]] = found()
        return listed
    return [(coord, 'point')]
