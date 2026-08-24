"""Generated geometry into the scenegraph, without a file in between.

A mesh generator hands back vertex arrays named the way glTF names them --
``POSITION``, ``NORMAL``, ``TEXCOORD_0``. :class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh`
takes exactly those arrays as its constructor arguments, so the two meet with
nothing between them: no file written, no bytes parsed, no loader involved.

    from opengl_extrusions import extrude, circle
    from OpenGLContext.scenegraph.frommesh import shape_from_mesh

    pipe = extrude(circle(0.1, 16), [(0, 0, 0), (0, 1, 0), (1, 2, 0)])
    scene.children.append(shape_from_mesh(pipe, appearance=steel))

**Nothing is copied at the boundary.** ``PBRMesh`` normalises attributes with
``asarray(..., float32)`` and ``ascontiguousarray``, both of which are no-ops on
an array that is already C-contiguous float32 -- which is what these generators
produce. The array the generator filled is the array the VBO uploads.

The reading is **structural**: anything exposing ``attributes`` and ``indices``
works, whether or not it came from ``opengl_extrusions``. Nothing here imports
that package, so a procedural mesh from an editor, a script or another library
reaches the scenegraph the same way.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional

from OpenGLContext.scenegraph.pbrmesh import PBRMesh

#: glTF attribute semantic -> the keyword ``PBRMesh`` takes it under.
ATTRIBUTE_KEYWORDS = {
    'POSITION': 'positions',
    'NORMAL': 'normals',
    'TEXCOORD_0': 'texcoords',
    'TEXCOORD_1': 'texcoords1',
    'TANGENT': 'tangents',
    'COLOR_0': 'colors',
}


def mesh_from_primitive(primitive: Any, **named: Any) -> PBRMesh:
    """One glTF-shaped primitive as a :class:`PBRMesh`.

    ``primitive`` needs an ``attributes`` mapping of glTF semantic names to
    arrays and an ``indices`` array (or ``None``). Attributes the engine has no
    use for are ignored rather than refused, so a generator that adds its own is
    still usable here.
    """
    attributes = getattr(primitive, 'attributes', None)
    if attributes is None:
        raise TypeError('expected a primitive with an `attributes` mapping, got %r'
                        % (type(primitive).__name__,))
    if 'POSITION' not in attributes:
        raise ValueError('primitive has no POSITION attribute')
    arrays = {ATTRIBUTE_KEYWORDS[name]: value
              for name, value in attributes.items() if name in ATTRIBUTE_KEYWORDS}
    arrays['indices'] = getattr(primitive, 'indices', None)
    mode = getattr(primitive, 'mode', None)
    if mode is not None:
        arrays['draw_mode'] = int(mode)
    arrays.update(named)
    return PBRMesh(**arrays)


def meshes_from_mesh(mesh: Any, **named: Any) -> List[PBRMesh]:
    """Every primitive of a generated mesh, as :class:`PBRMesh` nodes."""
    primitives = getattr(mesh, 'primitives', None)
    if primitives is None:
        raise TypeError('expected a mesh with a `primitives` list, got %r'
                        % (type(mesh).__name__,))
    return [mesh_from_primitive(p, **named) for p in primitives]


def shape_from_mesh(mesh: Any, appearance: Optional[Any] = None,
                    name: Optional[str] = None, **named: Any) -> Any:
    """A generated mesh as one renderable ``Shape``.

    A mesh of several primitives is merged first where it can be, since the
    scenegraph draws one geometry per ``Shape``; a mesh whose primitives cannot
    be merged uses its first. Use :func:`shapes_from_mesh` to keep them apart.
    """
    from OpenGLContext.scenegraph.basenodes import Shape

    merged = mesh.merged() if hasattr(mesh, 'merged') else mesh
    geometry = meshes_from_mesh(merged, **named)
    if not geometry:
        raise ValueError('mesh has no primitives to draw')
    shape = Shape(geometry=geometry[0])
    if appearance is not None:
        shape.appearance = appearance
    if name:
        shape.DEF = name
    return shape


def shapes_from_mesh(mesh: Any, appearance: Optional[Any] = None,
                     **named: Any) -> List[Any]:
    """One ``Shape`` per primitive, sharing an appearance."""
    from OpenGLContext.scenegraph.basenodes import Shape

    out = []
    for geometry in meshes_from_mesh(mesh, **named):
        shape = Shape(geometry=geometry)
        if appearance is not None:
            shape.appearance = appearance
        out.append(shape)
    return out


def _unused(value: Iterable) -> None:            # pragma: no cover
    """Kept out of the public surface."""
