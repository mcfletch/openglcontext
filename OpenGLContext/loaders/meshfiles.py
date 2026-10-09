"""STL, PLY and OFF models, read into the scenegraph.

Three formats that carry one mesh and nothing else: no cameras, lights or
materials. Each reads into a :class:`MeshFile` of glTF-shaped arrays, and
:class:`MeshFileHandler` puts that in a scene as a ``Shape`` holding a
``PBRMesh`` in a light grey ``PhysicalMaterial`` (white where the file gives
vertex colours, which the colours then tint)::

    from OpenGLContext.loaders.loader import Loader
    scene = Loader.load('bracket.stl')         # or .ply, .off; .gz as well

- STL, ASCII and binary. Each facet's three corners are its own, with the
  facet's normal; a zero normal is worked out from the corners. A binary file
  is told from an ASCII one by its size, so one whose header begins with
  ``solid`` reads as binary.
- PLY, ASCII and binary of either byte order (Paul Bourke's description of
  the format). ``vertex`` properties ``x``, ``y``, ``z``; ``nx``, ``ny``, ``nz``;
  ``red``, ``green``, ``blue``, ``alpha`` (integers scaled by their type's
  maximum, floats as they are); ``s``/``t``, ``u``/``v`` or
  ``texture_u``/``texture_v``. A ``face`` element's ``vertex_indices`` (or
  ``vertex_index``) lists. Other elements are read past. A file with no faces
  is a point cloud.
- A PLY whose vertices carry ``f_dc_0`` to ``f_dc_2``, ``opacity``,
  ``scale_0`` to ``scale_2`` and ``rot_0`` to ``rot_3`` is a set of 3D
  Gaussian splats and reads as a ``GaussianSplats`` node; the layout is in
  ``specs/gaussian-splats.md``.
- OFF, with the ``ST``, ``C`` and ``N`` prefixes (texture coordinates, vertex
  colours, vertex normals). A face may end in its own colour, in which case
  every face has corners of its own. ``4OFF`` and ``nOFF`` are not read.

Polygons are cut into triangles as fans from their first corner, which is
right for the convex polygons these formats are written with. A file that
does not hold what its header declares raises ValueError naming what is
wrong.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional, Union

import numpy as np

from OpenGLContext.loaders import base
from OpenGLContext.loaders.resolver import DEFAULT_MAX_RESOURCE_BYTES, gunzipped

__all__ = ['MeshFile', 'MeshFileHandler', 'read_off', 'read_ply', 'read_stl',
           'stlHandler', 'plyHandler', 'offHandler']

log = logging.getLogger(__name__)


@dataclass
class MeshFile:
    """One mesh as glTF-shaped arrays: ``(N, 3)`` positions, optional normals,
    RGBA colours and texture coordinates, and triangle indices (None for a
    point cloud, or for triangles whose corners are in order)."""
    positions: np.ndarray
    normals: Optional[np.ndarray] = None
    colors: Optional[np.ndarray] = None
    texcoords: Optional[np.ndarray] = None
    indices: Optional[np.ndarray] = None
    #: Whether the mesh is a point cloud rather than a surface.
    points: bool = False


# --------------------------------------------------------------------------- #
# STL
# --------------------------------------------------------------------------- #
_STL_RECORD = np.dtype([('normal', '<f4', 3), ('corners', '<f4', (3, 3)),
                        ('attribute', '<u2')])
_NUMBER = rb'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
_STL_FACET = re.compile(
    rb'facet\s+normal\s+(%s)\s+(%s)\s+(%s)\s+outer\s+loop\s+'
    rb'vertex\s+(%s)\s+(%s)\s+(%s)\s+vertex\s+(%s)\s+(%s)\s+(%s)\s+'
    rb'vertex\s+(%s)\s+(%s)\s+(%s)\s+endloop\s+endfacet' % ((_NUMBER,) * 12))


def read_stl(data: bytes) -> MeshFile:
    """An STL file, ASCII or binary, as a :class:`MeshFile` of separate facets."""
    data = bytes(data)
    if len(data) >= 84:
        count = int.from_bytes(data[80:84], 'little')
        if len(data) == 84 + count * _STL_RECORD.itemsize:
            records = np.frombuffer(data, _STL_RECORD, count=count, offset=84)
            return _facets(records['corners'], records['normal'])
    if not data.lstrip().startswith(b'solid'):
        raise ValueError("not an STL file: neither 'solid' nor a binary record count "
                         "matching its size")
    found = _STL_FACET.findall(data)
    if len(found) != data.count(b'endfacet') or not found:
        raise ValueError("ASCII STL holds %d facets of three vertices but %d endfacet"
                         % (len(found), data.count(b'endfacet')))
    values = np.array(found, dtype=np.float64).astype(np.float32)
    return _facets(values[:, 3:].reshape(-1, 3, 3), values[:, :3])


def _facets(corners: np.ndarray, normals: np.ndarray) -> MeshFile:
    """Separate triangles with their facet normals; a zero normal is computed."""
    corners = np.ascontiguousarray(corners, np.float32)
    normals = np.array(normals, np.float32)
    computed = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    lengths = np.linalg.norm(computed, axis=1, keepdims=True)
    computed = np.divide(computed, lengths, out=np.zeros_like(computed),
                         where=lengths > 0)
    missing = ~np.any(normals != 0, axis=1)
    normals[missing] = computed[missing]
    return MeshFile(positions=corners.reshape(-1, 3),
                    normals=np.repeat(normals, 3, axis=0))


# --------------------------------------------------------------------------- #
# PLY
# --------------------------------------------------------------------------- #
_PLY_TYPES = {
    'char': 'i1', 'int8': 'i1', 'uchar': 'u1', 'uint8': 'u1',
    'short': 'i2', 'int16': 'i2', 'ushort': 'u2', 'uint16': 'u2',
    'int': 'i4', 'int32': 'i4', 'uint': 'u4', 'uint32': 'u4',
    'float': 'f4', 'float32': 'f4', 'double': 'f8', 'float64': 'f8',
}
_PLY_FORMATS = {'ascii': None, 'binary_little_endian': '<', 'binary_big_endian': '>'}
_SPLAT_PROPERTIES = ('f_dc_0', 'f_dc_1', 'f_dc_2', 'opacity', 'scale_0', 'scale_1',
                     'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3')


@dataclass
class _Property:
    name: str
    type: str
    #: The count's type, for a list property; None for a scalar.
    count_type: Optional[str] = None


@dataclass
class _Element:
    name: str
    count: int
    properties: list[_Property]


def _ply_type(name: str) -> str:
    try:
        return _PLY_TYPES[name]
    except KeyError:
        raise ValueError("PLY property type %r is not one PLY defines" % (name,)) from None


def _ply_header(data: bytes) -> tuple[Optional[str], list[_Element], int]:
    """The byte order (None for ASCII), the elements, and where the body starts."""
    end = data.find(b'end_header')
    if not data.startswith(b'ply') or end < 0:
        raise ValueError("not a PLY file: no 'ply' magic or no end_header")
    body = data.index(b'\n', end) + 1 if b'\n' in data[end:] else len(data)
    order: Optional[str] = None
    formatted = False
    elements: list[_Element] = []
    for line in data[:end].decode('latin-1').splitlines()[1:]:
        words = line.split()
        if not words or words[0] in ('comment', 'obj_info'):
            continue
        if words[0] == 'format':
            if len(words) < 2 or words[1] not in _PLY_FORMATS:
                raise ValueError("PLY format %r is not ascii or binary" % (line,))
            order, formatted = _PLY_FORMATS[words[1]], True
        elif words[0] == 'element' and len(words) == 3 and words[2].isdigit():
            elements.append(_Element(words[1], int(words[2]), []))
        elif words[0] == 'property' and elements and len(words) == 5 and words[1] == 'list':
            elements[-1].properties.append(
                _Property(words[4], _ply_type(words[3]), _ply_type(words[2])))
        elif words[0] == 'property' and elements and len(words) == 3:
            elements[-1].properties.append(_Property(words[2], _ply_type(words[1])))
        else:
            raise ValueError("PLY header line %r is not one PLY defines" % (line,))
    if not formatted:
        raise ValueError("PLY header has no format line")
    return order, elements, body


def read_ply(data: bytes) -> Union[MeshFile, Any]:
    """A PLY file as a :class:`MeshFile`, or a ``GaussianSplats`` node where its
    vertices are 3D Gaussian splats."""
    data = bytes(data)
    order, elements, start = _ply_header(data)
    if order is None:
        columns = _ply_ascii(data[start:], elements)
    else:
        columns = _ply_binary(data, start, order, elements)
    vertex = columns.get('vertex')
    if vertex is None or not all(axis in vertex for axis in 'xyz'):
        raise ValueError("PLY file has no vertex element with x, y and z")
    if all(name in vertex for name in _SPLAT_PROPERTIES):
        return _splats(vertex)
    positions = np.stack([vertex[axis] for axis in 'xyz'], axis=1).astype(np.float32)
    mesh = MeshFile(positions=positions)
    if all(name in vertex for name in ('nx', 'ny', 'nz')):
        mesh.normals = np.stack([vertex[n] for n in ('nx', 'ny', 'nz')], 1).astype(np.float32)
    channels = [vertex.get(name) for name in ('red', 'green', 'blue', 'alpha')]
    if all(channel is not None for channel in channels[:3]):
        mesh.colors = _rgba([_unit(c) for c in channels if c is not None])
    for u, v in (('s', 't'), ('u', 'v'), ('texture_u', 'texture_v')):
        if u in vertex and v in vertex:
            mesh.texcoords = np.stack([vertex[u], vertex[v]], 1).astype(np.float32)
            break
    face = columns.get('face', {})
    polygons = face.get('vertex_indices', face.get('vertex_index'))
    if polygons is None:
        mesh.points = True
    else:
        mesh.indices = _fans(polygons, len(positions))
    return mesh


def _unit(channel: np.ndarray) -> np.ndarray:
    """A colour channel in [0, 1]: an integer one scaled by its type's maximum."""
    if np.issubdtype(channel.dtype, np.integer):
        return channel.astype(np.float32) / float(np.iinfo(channel.dtype).max)
    return channel.astype(np.float32)


def _rgba(channels: list[np.ndarray]) -> np.ndarray:
    out = np.ones((len(channels[0]), 4), np.float32)
    for index, channel in enumerate(channels):
        out[:, index] = channel
    return out


def _ply_ascii(text: bytes, elements: list[_Element]) -> dict[str, dict[str, Any]]:
    """Each element's properties, by name: a scalar as an array, a list as a list."""
    lines = iter(line for line in text.split(b'\n') if line.strip())
    columns: dict[str, dict[str, Any]] = {}
    for element in elements:
        rows = []
        for _ in range(element.count):
            try:
                rows.append(next(lines).split())
            except StopIteration:
                raise ValueError("PLY %s element declares %d rows; the file ends sooner"
                                 % (element.name, element.count)) from None
        values: dict[str, Any] = {}
        if all(p.count_type is None for p in element.properties):
            table = np.array([[float(word) for word in row[:len(element.properties)]]
                              for row in rows], np.float64).reshape(
                                  element.count, len(element.properties))
            for column, prop in enumerate(element.properties):
                values[prop.name] = table[:, column].astype(prop.type)
        else:
            for prop in element.properties:
                values[prop.name] = []
            for row in rows:
                position = 0
                for prop in element.properties:
                    if prop.count_type is None:
                        values[prop.name].append(float(row[position]))
                        position += 1
                    else:
                        length = int(row[position])
                        values[prop.name].append(
                            [int(float(word)) for word in row[position + 1:position + 1 + length]])
                        position += 1 + length
        columns[element.name] = values
    return columns


def _ply_binary(data: bytes, start: int, order: str,
                elements: list[_Element]) -> dict[str, dict[str, Any]]:
    """Each element's properties, by name, from a binary body."""
    columns: dict[str, dict[str, Any]] = {}
    position = start
    for element in elements:
        if all(p.count_type is None for p in element.properties):
            dtype = np.dtype([(p.name, order + p.type) for p in element.properties])
            if position + dtype.itemsize * element.count > len(data):
                raise ValueError("PLY %s element declares %d rows; the file ends sooner"
                                 % (element.name, element.count))
            table = np.frombuffer(data, dtype, count=element.count, offset=position)
            columns[element.name] = {name: np.asarray(table[name]) for name in dtype.names or ()}
            position += dtype.itemsize * element.count
        else:
            values, position = _ply_list_rows(data, position, order, element)
            columns[element.name] = values
    return columns


def _ply_list_rows(data: bytes, position: int, order: str,
                   element: _Element) -> tuple[dict[str, Any], int]:
    """An element with list properties: every row the same length, read as one
    array, or else one row at a time."""
    uniform = _ply_uniform_rows(data, position, order, element)
    if uniform is not None:
        return uniform
    values: dict[str, Any] = {p.name: [] for p in element.properties}
    for _ in range(element.count):
        for prop in element.properties:
            if prop.count_type is None:
                item = np.dtype(order + prop.type)
                values[prop.name].append(_ply_take(data, position, item, 1)[0])
                position += item.itemsize
                continue
            counter = np.dtype(order + prop.count_type)
            length = int(_ply_take(data, position, counter, 1)[0])
            position += counter.itemsize
            item = np.dtype(order + prop.type)
            values[prop.name].append(_ply_take(data, position, item, length).tolist())
            position += item.itemsize * length
    return values, position


def _ply_take(data: bytes, position: int, dtype: np.dtype, count: int) -> np.ndarray:
    if position + dtype.itemsize * count > len(data):
        raise ValueError("PLY file ends inside an element's rows")
    return np.frombuffer(data, dtype, count=count, offset=position)


def _ply_uniform_rows(data: bytes, position: int, order: str,
                      element: _Element) -> Optional[tuple[dict[str, Any], int]]:
    """The rows read as one array where every list in them has the length the
    first row's lists have, or None where they do not."""
    if element.count == 0:
        return {p.name: [] for p in element.properties}, position
    fields: list[tuple[Any, ...]] = []
    cursor = position
    for prop in element.properties:
        if prop.count_type is None:
            fields.append((prop.name, order + prop.type))
            cursor += np.dtype(prop.type).itemsize
            continue
        counter = np.dtype(order + prop.count_type)
        length = int(_ply_take(data, cursor, counter, 1)[0])
        fields.append((prop.name + '#', counter.str))
        fields.append((prop.name, order + prop.type, (length,)))
        cursor += counter.itemsize + np.dtype(prop.type).itemsize * length
    dtype = np.dtype(fields)
    if position + dtype.itemsize * element.count > len(data):
        return None
    table = np.frombuffer(data, dtype, count=element.count, offset=position)
    for prop in element.properties:
        if prop.count_type is not None and np.any(
                table[prop.name + '#'] != table[prop.name].shape[-1]):
            return None
    values = {prop.name: np.asarray(table[prop.name]) for prop in element.properties}
    return values, position + dtype.itemsize * element.count


def _fans(polygons: Any, vertex_count: int) -> np.ndarray:
    """Polygons (a 2D array of equal ones, or a list of lists) as triangle fans."""
    if isinstance(polygons, np.ndarray) and polygons.ndim == 2:
        sides = polygons.shape[1]
        if sides < 3:
            raise ValueError("a face of %d corners is no polygon" % sides)
        fans = [np.stack([polygons[:, 0], polygons[:, k], polygons[:, k + 1]], 1)
                for k in range(1, sides - 1)]
        indices = np.stack(fans, 1).reshape(-1).astype(np.int64)
    else:
        triangles: list[int] = []
        for polygon in polygons:
            polygon = list(polygon)
            if len(polygon) < 3:
                raise ValueError("a face of %d corners is no polygon" % len(polygon))
            for k in range(1, len(polygon) - 1):
                triangles.extend((polygon[0], polygon[k], polygon[k + 1]))
        indices = np.asarray(triangles, np.int64)
    if len(indices) and (indices.min() < 0 or indices.max() >= vertex_count):
        raise ValueError("a face index is out of range for %d vertices" % vertex_count)
    return indices.astype(np.uint32)


def _splats(vertex: dict[str, Any]) -> Any:
    """A 3D Gaussian splat PLY's vertices as a GaussianSplats node.

    The file holds the values the splats were optimised as: scales as
    logarithms, opacity before its sigmoid, the rotation as an unnormalised
    (w, x, y, z), and the higher harmonics channel by channel.
    """
    from OpenGLContext.scenegraph.gaussiansplats import from_arrays  # noqa: PLC0415 the node imports GL
    from OpenGLContext.scenegraph import splatmath  # noqa: PLC0415 imported with the node
    count = len(vertex['x'])

    def stacked(*names: str) -> np.ndarray:
        return np.stack([np.asarray(vertex[name], np.float64) for name in names], 1)

    rotations = stacked('rot_1', 'rot_2', 'rot_3', 'rot_0')
    lengths = np.linalg.norm(rotations, axis=1, keepdims=True)
    rotations = np.divide(rotations, lengths, out=np.tile([0.0, 0, 0, 1], (count, 1)),
                          where=lengths > 0)
    with np.errstate(over='ignore'):
        scales = np.exp(stacked('scale_0', 'scale_1', 'scale_2'))
        opacities = 1.0 / (1.0 + np.exp(-np.asarray(vertex['opacity'], np.float64)))
    harmonics = [stacked('f_dc_0', 'f_dc_1', 'f_dc_2')]
    rest = sorted((int(name[7:]) for name in vertex if name.startswith('f_rest_')))
    per_channel = len(rest) // 3
    degree = 0
    while (degree + 2) ** 2 - 1 <= per_channel and degree < len(splatmath.SH_COEFFICIENTS) - 1:
        degree += 1
    used = (degree + 1) ** 2 - 1
    for coefficient in range(used):
        harmonics.append(stacked(*('f_rest_%d' % (channel * per_channel + coefficient)
                                   for channel in range(3))))
    return from_arrays(positions=stacked('x', 'y', 'z'), rotations=rotations,
                       scales=scales, opacities=opacities, harmonics=harmonics)


# --------------------------------------------------------------------------- #
# OFF
# --------------------------------------------------------------------------- #
_OFF_KEYWORD = re.compile(r'^(ST)?(C)?(N)?(4)?(n)?OFF$')


def read_off(data: bytes) -> MeshFile:
    """An OFF file (with any of the ST, C and N prefixes) as a :class:`MeshFile`."""
    lines = [line.split('#', 1)[0].split() for line in
             bytes(data).decode('latin-1').splitlines()]
    words = [line for line in lines if line]
    if not words:
        raise ValueError("not an OFF file: it is empty")
    keyword = _OFF_KEYWORD.match(words[0][0])
    if keyword is None and not words[0][0].isdigit():
        raise ValueError("not an OFF file: it begins %r" % (words[0][0],))
    textured, coloured, normalled, homogeneous, dimensioned = (
        bool(group) for group in (keyword.groups() if keyword else (None,) * 5))
    if homogeneous or dimensioned:
        raise ValueError("OFF files of other than three dimensions are not read")
    if keyword is not None and words[0][1:2] == ['BINARY']:
        raise ValueError("binary OFF files are not read")
    # The keyword is optional, and the counts may share its line.
    counted = words[0][1:] if keyword is not None else words[0]
    if keyword is not None and not counted:
        words = words[1:]
        counted = words[0] if words else []
    body = words[1:]
    if len(counted) < 2:
        raise ValueError("OFF header has no vertex and face counts")
    vertex_count, face_count = int(counted[0]), int(counted[1])
    if len(body) < vertex_count + face_count:
        raise ValueError("OFF file declares %d vertices and %d faces; it holds %d lines"
                         % (vertex_count, face_count, len(body)))
    vertices = body[:vertex_count]
    # Each vertex is x y z, then its normal, colour and texture coordinates in
    # that order where the prefixes say so; a colour is three or four values.
    least = 3 + 3 * normalled + 2 * textured + 3 * coloured
    if any(len(row) < least for row in vertices):
        raise ValueError("OFF vertices hold fewer than %d values" % least)
    mesh = MeshFile(positions=np.array([[float(w) for w in row[:3]] for row in vertices],
                                       np.float32).reshape(vertex_count, 3))
    if normalled:
        mesh.normals = np.array([[float(w) for w in row[3:6]] for row in vertices],
                                np.float32).reshape(vertex_count, 3)
    if coloured:
        first = 3 + 3 * normalled
        mesh.colors = _off_colours([row[first:len(row) - 2 * textured] for row in vertices])
    if textured:
        mesh.texcoords = np.array([[float(w) for w in row[-2:]] for row in vertices],
                                  np.float32).reshape(vertex_count, 2)
    polygons = []
    face_colours = []
    for row in body[vertex_count:vertex_count + face_count]:
        corners = int(row[0])
        polygons.append([int(word) for word in row[1:1 + corners]])
        face_colours.append(row[1 + corners:])
    mesh.indices = _fans(polygons, vertex_count)
    if any(len(colour) >= 3 for colour in face_colours):
        _unshare_by_face(mesh, polygons, _off_colours(face_colours, _OFF_FACE_DEFAULT))
    return mesh


#: The colour a face without one takes where other faces have one.
_OFF_FACE_DEFAULT = (0.666, 0.666, 0.666, 0.666)


def _off_colours(rows: list[list[str]],
                 default: tuple[float, ...] = (1.0, 1.0, 1.0, 1.0)) -> np.ndarray:
    """OFF colours as RGBA: three or four integers out of 255, or floats out of
    1. A row holding fewer than three values (none, or a colour-map index)
    takes ``default``."""
    out = np.tile(np.asarray(default, np.float32), (len(rows), 1))
    for index, row in enumerate(rows):
        if len(row) < 3:
            continue
        values = [float(word) for word in row[:4]]
        if all(word.lstrip('-+').isdigit() for word in row[:4]):
            values = [value / 255.0 for value in values]
        out[index, :len(values)] = values
        if len(values) == 3:
            out[index, 3] = 1.0
    return out


def _unshare_by_face(mesh: MeshFile, polygons: list[list[int]], colours: np.ndarray) -> None:
    """Give every face corners of its own, so each can carry its face's colour."""
    face_of = np.repeat(np.arange(len(polygons)),
                        [len(polygon) - 2 for polygon in polygons]).repeat(3)
    corners = mesh.indices
    assert corners is not None
    mesh.positions = mesh.positions[corners]
    for name in ('normals', 'texcoords'):
        values = getattr(mesh, name)
        if values is not None:
            setattr(mesh, name, values[corners])
    mesh.colors = colours[face_of]
    mesh.indices = None


# --------------------------------------------------------------------------- #
# Scenes
# --------------------------------------------------------------------------- #
#: The base colour of a model whose file gives it none.
GREY = (0.8, 0.8, 0.8)


def scene_of(read: Union[MeshFile, Any]) -> Any:
    """A scene holding what a file read as: a Shape, or a GaussianSplats node."""
    from OpenGLContext.scenegraph import basenodes  # noqa: PLC0415 the scenegraph imports GL
    if not isinstance(read, MeshFile):
        return basenodes.sceneGraph(children=[read])
    from OpenGLContext.loaders.gltf.meshes import estimate_normals  # noqa: PLC0415 as above
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh  # noqa: PLC0415 as above
    from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial  # noqa: PLC0415 as above
    normals = read.normals
    if normals is None and not read.points:
        normals = estimate_normals(read.positions, read.indices)
    mesh = PBRMesh(positions=read.positions, normals=normals, colors=read.colors,
                   texcoords=read.texcoords, indices=read.indices,
                   draw_mode=0 if read.points else 4)
    material = PhysicalMaterial(baseColor=(1.0, 1.0, 1.0) if read.colors is not None else GREY,
                                metallic=0.0, roughness=0.6)
    appearance = basenodes.Appearance(material=material)
    mesh.appearance = appearance
    return basenodes.sceneGraph(children=[basenodes.Shape(geometry=mesh, appearance=appearance)])


class MeshFileHandler(base.BaseHandler):
    """The loader handler for one of the three formats; gzip is read through."""

    def __init__(self, reader: Any) -> None:
        self.reader = reader

    def parse(self, data: Any, baseURL: str, *args: Any, **named: Any) -> tuple[bool, Any]:
        """The scene the file builds; ValueError, naming the file, where it is malformed"""
        data = gunzipped(bytes(data), DEFAULT_MAX_RESOURCE_BYTES, baseURL or 'document')
        try:
            return True, scene_of(self.reader(data))
        except ValueError as err:
            raise ValueError('%s: %s' % (baseURL, err)) from err


def stlHandler() -> MeshFileHandler:
    """The handler `plugins.Loader` registers for STL"""
    return MeshFileHandler(read_stl)


def plyHandler() -> MeshFileHandler:
    """The handler `plugins.Loader` registers for PLY"""
    return MeshFileHandler(read_ply)


def offHandler() -> MeshFileHandler:
    """The handler `plugins.Loader` registers for OFF"""
    return MeshFileHandler(read_off)
