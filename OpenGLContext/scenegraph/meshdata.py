"""A geometry node's triangles as arrays, and the triangles of a scene merged; no GL

Every geometry node that draws triangles answers `meshArrays()` with a
:class:`~OpenGLContext.scenegraph.composedgeometry.ComposedArrays`: glTF-shaped
arrays (``POSITION``, ``NORMAL``, ``TEXCOORD_0``, ``COLOR_0``) in the node's
own frame, and the triangle corners as ``indices`` or, where that is None,
every three vertices a triangle. :func:`geometry_arrays` asks a node for them;
a node of lines, points or text has none.

:func:`merged_arrays` walks nodes as the render pass does (through
`renderedChildren`), and joins every shape's triangles into one set of arrays,
placed by the transforms above the shape. X3D's `InlineGeometry` draws a file
this way.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, Optional

import numpy as np

from OpenGLContext.scenegraph import nodepath
from OpenGLContext.scenegraph.composedgeometry import ComposedArrays, vertex_normals

__all__ = ['arrays', 'flattened', 'geometry_arrays', 'merged_arrays']

#: The colour a merged shape without colours is given, where others have them.
WHITE = (1.0, 1.0, 1.0, 1.0)


def arrays(positions: Any, normals: Any, texcoords: Any = None, colors: Any = None,
           indices: Any = None) -> Optional[ComposedArrays]:
    """Arrays of one geometry; None where there are no triangles

    positions -- one row of three per vertex
    normals -- one row of three per vertex; None to average them across the
        triangles that share each vertex
    texcoords -- one row of two per vertex, or None
    colors -- one row of three or four per vertex, or None
    indices -- the triangle corners, or None for every three vertices a triangle
    """
    if positions is None or not len(positions):
        return None
    positions = np.ascontiguousarray(positions, dtype=np.float32).reshape(-1, 3)
    if normals is None or len(normals) != len(positions):
        shared = (np.arange((len(positions) // 3) * 3) if indices is None
                  else np.asarray(indices, dtype=np.int64).ravel())
        normals = vertex_normals(positions, shared.reshape(-1, 3))
    found = {'POSITION': positions,
             'NORMAL': np.ascontiguousarray(normals, dtype=np.float32).reshape(-1, 3)}
    if texcoords is not None and len(texcoords):
        found['TEXCOORD_0'] = np.ascontiguousarray(texcoords, dtype=np.float32).reshape(-1, 2)
    if colors is not None and len(colors):
        colors = np.asarray(colors, dtype=np.float32)
        found['COLOR_0'] = np.ascontiguousarray(colors.reshape(len(colors), -1))
    corners = None if indices is None else np.ascontiguousarray(indices, dtype=np.uint32).ravel()
    if corners is not None and not len(corners):
        return None
    return ComposedArrays(attributes=found, indices=corners)


def geometry_arrays(geometry: Any) -> Optional[ComposedArrays]:
    """`geometry`'s triangles in its own frame; None for a node that draws none"""
    answer = getattr(geometry, 'meshArrays', None)
    if answer is None:
        return None
    found: Optional[ComposedArrays] = answer()
    return found


def _corners(found: ComposedArrays) -> np.ndarray:
    count = len(found.attributes['POSITION'])
    if found.indices is None:
        return np.arange((count // 3) * 3, dtype=np.uint32)
    return np.asarray(found.indices, dtype=np.uint32).ravel()


def _placed(found: ComposedArrays, matrix: np.ndarray) -> ComposedArrays:
    """`found` moved by the row-vector `matrix`, its normals turned to match"""
    positions = found.attributes['POSITION'].astype(np.float64)
    moved = positions @ matrix[:3, :3] + matrix[3, :3]
    turn = np.linalg.inv(matrix[:3, :3]).T
    normals = found.attributes['NORMAL'].astype(np.float64) @ turn
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    length[~(length > 0)] = 1.0
    corners = _corners(found)
    if np.linalg.det(matrix[:3, :3]) < 0:
        corners = corners.reshape(-1, 3)[:, [0, 2, 1]].ravel()
    attributes = dict(found.attributes)
    attributes['POSITION'] = moved.astype(np.float32)
    attributes['NORMAL'] = (normals / length).astype(np.float32)
    return ComposedArrays(attributes=attributes, indices=corners)


def _shapes(nodes: Iterable[Any], parent: Any) -> Iterator[tuple[Any, Any]]:
    """Each shape under `nodes` with its path, walked as the render pass walks"""
    for node in nodes:
        path = parent + node
        if getattr(node, 'geometry', None) is not None:
            yield node, path
        children = getattr(node, 'renderedChildren', None)
        if children is not None:
            yield from _shapes(children(), path)


def merged_arrays(nodes: Iterable[Any]) -> Optional[ComposedArrays]:
    """Every shape's triangles under `nodes`, placed by its transforms, as one set

    Texture coordinates are kept where every shape has them, and colours
    where any has them (white for those that do not). None where no shape
    draws triangles.
    """
    parts = []
    for shape, path in _shapes(nodes, nodepath.NodePath([])):
        found = geometry_arrays(shape.geometry)
        if found is not None:
            parts.append(_placed(found, np.asarray(path.transformMatrix(), dtype=np.float64)))
    if not parts:
        return None
    textured = all('TEXCOORD_0' in part.attributes for part in parts)
    coloured = any('COLOR_0' in part.attributes for part in parts)
    joined: dict[str, list[np.ndarray]] = {'POSITION': [], 'NORMAL': []}
    if textured:
        joined['TEXCOORD_0'] = []
    if coloured:
        joined['COLOR_0'] = []
    corners, offset = [], 0
    for part in parts:
        count = len(part.attributes['POSITION'])
        for name in joined:
            if name == 'COLOR_0':
                joined[name].append(_rgba(part.attributes.get(name), count))
            else:
                joined[name].append(part.attributes[name])
        corners.append(_corners(part) + offset)
        offset += count
    return ComposedArrays(
        attributes={name: np.ascontiguousarray(np.concatenate(values), dtype=np.float32)
                    for name, values in joined.items()},
        indices=np.concatenate(corners).astype(np.uint32))


def _rgba(colors: Optional[np.ndarray], count: int) -> np.ndarray:
    if colors is None:
        return np.tile(np.asarray(WHITE, np.float32), (count, 1))
    if colors.shape[1] == 3:
        return np.column_stack([colors, np.ones(count, np.float32)])
    return colors


def flattened(found: ComposedArrays) -> ComposedArrays:
    """`found` with every triangle's corners its own vertices, and its own normal"""
    corners = _corners(found)
    attributes = {name: values[corners] for name, values in found.attributes.items()}
    triangle = attributes['POSITION'].astype(np.float64).reshape(-1, 3, 3)
    with np.errstate(invalid='ignore'):
        faces = np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0])
        length = np.linalg.norm(faces, axis=1, keepdims=True)
        length[~(length > 0)] = 1.0
    attributes['NORMAL'] = np.repeat(faces / length, 3, axis=0).astype(np.float32)
    return ComposedArrays(attributes=attributes, indices=None)
