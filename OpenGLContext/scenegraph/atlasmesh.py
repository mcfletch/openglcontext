"""One picture and one mesh for a set of small objects that differ by their art.

A world's roadside is full of things that are the same object with a different
picture on it: seven kinds of warning plate, a chequered banner over the start
line, a painted line across the road. Drawn one at a time each is its own
material and its own draw call, which is what the GPU is slowest at switching
between and what a landscape has hundreds of.

Two moves fix it, and they compose. :func:`pack_cells` puts every picture in a
single image and says which corner each one lives in, so the geometry that reads
them all wears one material. :func:`merged_mesh` then concatenates that geometry,
so a tile's worth of them is one render record, one bounding volume, one frustum
test and one entry in each shadow cascade.

:mod:`OpenGLContext.scenegraph.roadsigns` and
:mod:`OpenGLContext.scenegraph.gantry` are built on this; anything else that
places tens of small painted objects can be.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.loaders.gltf.meshes import estimate_normals
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = ['Box', 'pack_cells', 'cell_centre', 'srgb_bytes', 'flat_patch',
           'merged_mesh', 'textured_mesh']

#: A corner of an atlas, as the texture coordinates that reach it.
Box = Tuple[float, float, float, float]


def pack_cells(patches: Mapping[str, Any], cell: int = 256
               ) -> Tuple[Any, Dict[str, Box]]:
    """Square patches on the smallest square grid that holds them.

    ``patches`` maps a name to an image ``cell`` pixels square --
    :func:`flat_patch` makes one of a single colour. Returns the image and
    ``{name: (u0, v0, u1, v1)}``, the corner each patch occupies.

    Laid out in the order given, so the same patches always make the same atlas
    and a world re-bakes to itself.
    """
    from PIL import Image
    names = list(patches)
    columns = max(int(math.ceil(math.sqrt(len(names)))), 1)
    rows = max(int(math.ceil(len(names) / columns)), 1)
    image = Image.new('RGBA', (columns * cell, rows * cell), (0, 0, 0, 0))
    boxes: Dict[str, Box] = {}
    for index, name in enumerate(names):
        column, row = index % columns, index // columns
        image.paste(patches[name], (column * cell, row * cell))
        boxes[name] = (column * cell / image.width, row * cell / image.height,
                       (column + 1) * cell / image.width,
                       (row + 1) * cell / image.height)
    return image, boxes


def cell_centre(box: Box) -> Tuple[float, float]:
    """The middle of an atlas cell, for geometry that wants one flat colour."""
    u0, v0, u1, v1 = box
    return ((u0 + u1) / 2.0, (v0 + v1) / 2.0)


def srgb_bytes(colour: Sequence[float]) -> tuple:
    """A linear albedo as the RGBA bytes an sRGB texture has to hold for it.

    Geometry that reads its colour out of an atlas is asking a texture to stand
    in for a material's ``baseColor``, and the texture is decoded on the way in.
    Writing the linear value straight into the image makes it come out dark.
    """
    def encoded(value: float) -> int:
        low = value * 12.92
        high = 1.055 * (value ** (1.0 / 2.4)) - 0.055
        return int(round(255.0 * (low if value <= 0.0031308 else high)))
    return tuple(encoded(float(v)) for v in colour) + (255,)


def flat_patch(colour: Sequence[float], cell: int = 256) -> Any:
    """An atlas cell of one linear colour, for the parts that carry no picture."""
    from PIL import Image
    return Image.new('RGBA', (cell, cell), srgb_bytes(colour))


def merged_mesh(meshes: Sequence[PBRMesh], material: PBRMaterial) -> PBRMesh:
    """Several meshes of one material as a single mesh.

    Every one of them has to carry texture coordinates, since the whole reason
    they share a material is that they read one atlas.
    """
    if not len(meshes):
        raise ValueError("nothing to merge: a mesh needs some geometry in it")
    positions, texcoords, indices, offset = [], [], [], 0
    for mesh in meshes:
        positions.append(np.asarray(mesh.positions))
        texcoords.append(np.asarray(mesh.texcoords))
        indices.append(np.asarray(mesh.indices) + offset)
        offset += len(positions[-1])
    return textured_mesh(np.concatenate(positions),
                         np.concatenate(indices).astype(np.uint32), material,
                         np.concatenate(texcoords).astype('f'))


def textured_mesh(positions: np.ndarray, indices: np.ndarray,
                  material: PBRMaterial,
                  texcoords: Optional[np.ndarray] = None) -> PBRMesh:
    """A mesh from points, triangles and where in an atlas each point reads.

    The normals are estimated from the triangles, which is what the flat-faced
    geometry built on this wants: a post, a beam and a plate have no curvature
    to preserve.
    """
    points = np.ascontiguousarray(positions, dtype='f')
    return PBRMesh(positions=points, normals=estimate_normals(points, indices),
                   indices=indices, material=material, texcoords=texcoords)
