"""A glTF document's table of implicit shapes, in either version of the format.

glTF 2.1 has a top-level ``shapes`` array of implicit shapes: a ``box``,
``sphere``, ``capsule``, ``cylinder`` or ``plane``, each with its dimensions
in a sub-object named after its type. A glTF 2.0 document carries the same
objects in the ``KHR_implicit_shapes`` extension's ``shapes`` array, which the
2.1 core took over unchanged. :func:`document_shapes` reads whichever one the
document's ``asset.version`` selects, so everything that names a shape by index
-- a zone (:mod:`~OpenGLContext.loaders.gltf.zoning`), and later a 2.1
``boundingVolume`` or a physics collider -- takes it from the same place.

A 2.1 document that also carries ``KHR_implicit_shapes`` resolves against the
core array, since that is the one its version defines.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Sequence

from OpenGLContext.scenegraph.zones import BOX, CAPSULE, CYLINDER, SPHERE, ShapeSpec

log = logging.getLogger(__name__)

__all__ = ['EXTENSION', 'document_shapes', 'is_core_version', 'read_shape',
           'shape_at']

#: The glTF 2.0 extension a 2.1 document's core ``shapes`` array came from.
EXTENSION = 'KHR_implicit_shapes'


def is_core_version(version: Optional[str]) -> bool:
    """Whether ``asset.version`` is 2.1 or later, where ``shapes`` is core."""
    try:
        major, minor = (int(part) for part in str(version or '').split('.')[:2])
    except ValueError:
        return False
    return (major, minor) >= (2, 1)


def _raw_table(g: Any) -> Optional[Sequence[Any]]:
    """The array of shape objects the document's version selects, or None."""
    version = getattr(getattr(g, 'asset', None), 'version', None)
    if is_core_version(version):
        core = getattr(g, 'shapes', None)
        if isinstance(core, list):
            return core
    extensions = getattr(g, 'extensions', None) or {}
    block = extensions.get(EXTENSION) if isinstance(extensions, dict) else None
    table = block.get('shapes') if isinstance(block, dict) else None
    return table if isinstance(table, list) else None


def read_shape(entry: Any) -> Optional[ShapeSpec]:
    """One shape object as a :class:`ShapeSpec`, or None for one a zone cannot use.

    The dimensions default as the shape specification defines them: a unit
    box, a sphere of radius 0.5, and a capsule or cylinder 0.5 high with
    radii of 0.25. A ``plane`` bounds no volume, so it is not a zone's shape.
    """
    if not isinstance(entry, dict):
        return None
    kind = entry.get('type')
    data = entry.get(kind) if isinstance(kind, str) else None
    data = data if isinstance(data, dict) else {}
    try:
        if kind == BOX:
            size = data.get('size', (1.0, 1.0, 1.0))
            return ShapeSpec(BOX, size=tuple(float(v) for v in size[:3]))  # type: ignore[arg-type]
        if kind == SPHERE:
            return ShapeSpec(SPHERE, radius=float(data.get('radius', 0.5)))
        if kind in (CAPSULE, CYLINDER):
            return ShapeSpec(kind, height=float(data.get('height', 0.5)),
                             radius_top=float(data.get('radiusTop', 0.25)),
                             radius_bottom=float(data.get('radiusBottom', 0.25)))
    except (TypeError, ValueError, IndexError):
        return None
    return None


def document_shapes(g: Any) -> List[Optional[ShapeSpec]]:
    """Every shape the document declares, by index; None where one is unusable."""
    return [read_shape(entry) for entry in (_raw_table(g) or ())]


def shape_at(g: Any, index: Any,
             table: Optional[List[Optional[ShapeSpec]]] = None) -> Optional[ShapeSpec]:
    """The shape at ``index``, or None where the index names nothing usable."""
    shapes = document_shapes(g) if table is None else table
    if not isinstance(index, int) or isinstance(index, bool):
        return None
    if not 0 <= index < len(shapes):
        return None
    return shapes[index]
