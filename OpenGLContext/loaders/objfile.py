"""Wavefront OBJ text read into triangle, line and point arrays.

The reader takes the bytes of an ``.obj`` file and returns an :class:`ObjFile`:
parts (one per ``o`` or ``g`` name), each holding meshes (one per material and
primitive kind) of glTF-shaped NumPy arrays. It imports no scenegraph and no GL,
so the format's rules are tested without either; :mod:`OpenGLContext.loaders.obj`
builds nodes from the result.

Statements read:

- ``v`` with three numbers, an optional weight (ignored), or the three colour
  numbers some exporters append (``v x y z r g b``, scaled by 255 where any
  exceeds 1); ``vt`` (the first two numbers); ``vn``.
- ``f`` in each corner form (``v``, ``v/t``, ``v//n``, ``v/t/n``), with
  positive indices, negative indices counted back from the last element read,
  and indices of elements defined after the face. Faces of more than three
  corners are cut into triangles that cover the polygon exactly, concave ones
  included.
- ``l`` and ``p``, as line segments and points.
- ``o`` and ``g``, the parts; ``usemtl`` and ``mtllib``, the materials; ``s``,
  the smoothing groups.

A face with no ``vn`` is shaded flat unless a smoothing group (``s 1``) says
which of its neighbours share its vertex normals. Normals are accumulated with
each face weighted by the angle it subtends at the vertex, so a polygon cut
into many triangles weighs as one face.

Free-form geometry (``curv``, ``surf`` and the statements that describe them) is
not read, and neither is ``vp``; :attr:`ObjFile.ignored` counts every statement
the reader passed over, by keyword.

A statement that cannot be read raises ``ValueError`` naming the file and the
line.
"""
from __future__ import annotations

import itertools
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional, Union

import numpy as np

__all__ = ['ObjFile', 'ObjMesh', 'ObjPart', 'decode_text', 'logical_lines', 'parse_obj']

#: What a mesh draws: triangles, line segments (index pairs) or points.
TRIANGLES = 'triangles'
LINES = 'lines'
POINTS = 'points'

#: The free-form geometry statements. They describe curves and surfaces this
#: reader does not tessellate.
FREEFORM = frozenset({
    'cstype', 'deg', 'bmat', 'step', 'curv', 'curv2', 'surf', 'parm', 'trim', 'hole',
    'scrv', 'sp', 'end', 'con', 'vp',
})

#: Whether a tolerance on a corner's turn counts it as flat rather than reflex.
_FLAT = 1e-7


@dataclass
class ObjMesh:
    """One run of a primitive kind in one material, within a part.

    ``positions`` is ``(N, 3)`` float32. ``indices`` is uint32: triples for
    triangles, pairs for lines, singles for points. ``normals`` is ``(N, 3)`` for
    triangles and None otherwise; ``texcoords`` is ``(N, 2)`` and ``colors``
    ``(N, 4)`` where the file gave any, None where it gave none.
    """
    kind: str
    material: str
    positions: np.ndarray
    indices: np.ndarray
    normals: Optional[np.ndarray] = None
    texcoords: Optional[np.ndarray] = None
    colors: Optional[np.ndarray] = None


@dataclass
class ObjPart:
    """The meshes of one object or group.

    ``name`` is the ``o`` name, the ``g`` name, or both joined by ``_``; spaces
    in a name become ``_`` as well. It is empty for faces before any name.
    """
    name: str
    meshes: list[ObjMesh] = field(default_factory=list)


@dataclass
class ObjFile:
    """What an OBJ file holds.

    ``libraries`` is the text of each ``mtllib`` line, in file order.
    ``ignored`` counts the statements that were read past, by keyword.
    """
    parts: list[ObjPart] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    ignored: Counter[str] = field(default_factory=Counter)


def parse_obj(data: Union[bytes, str], name: str = 'obj') -> ObjFile:
    """The model an OBJ file describes.

    ``data`` is the file's bytes, UTF-8 (a byte order mark is dropped) or
    Latin-1 where the bytes are not UTF-8. ``name`` is what an error message
    calls the file.
    """
    return _Reader(name).read(decode_text(data))


def decode_text(data: Union[bytes, str]) -> str:
    """The text of ``data``: UTF-8, or Latin-1 where it is not UTF-8"""
    if isinstance(data, str):
        return data.lstrip('﻿')
    data = bytes(data)
    if data.startswith(b'\xef\xbb\xbf'):
        data = data[3:]
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('latin-1')


def logical_lines(text: str) -> Any:
    """``(line number, text)`` for each statement, continuations joined

    A line ending in a backslash continues on the next, and numbers as the line
    it starts on. Carriage returns end lines as line feeds do.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    if '\\' not in text:
        return enumerate(lines, 1)
    joined = []
    start = 1
    held: list[str] = []
    for number, line in enumerate(lines, 1):
        if not held:
            start = number
        if line.endswith('\\'):
            held.append(line[:-1])
            continue
        held.append(line)
        joined.append((start, ' '.join(held)))
        held = []
    if held:
        joined.append((start, ' '.join(held)))
    return joined


def _name_of(parts: list[str]) -> str:
    """The name a statement gives, its words joined by ``_``"""
    return '_'.join(parts[1:])


class _Reader:
    """One file's read: the statements collected, then the arrays built"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.result = ObjFile()

    def error(self, number: int, message: str) -> ValueError:
        return ValueError('%s:%d: %s' % (self.name, number, message))

    def read(self, text: str) -> ObjFile:
        result = self.result
        ignored = result.ignored
        position_tokens: list[str] = []
        colour_tokens: list[str] = []
        colour_rows: list[int] = []
        texcoord_tokens: list[str] = []
        normal_tokens: list[str] = []
        vertices = texcoords = normals = 0

        #: Each emitted mesh: (part name, material, kind).
        mesh_keys: dict[tuple[str, str, str], int] = {}
        part_order: dict[str, int] = {}
        mesh_part: list[int] = []
        object_name = group_name = material = ''
        smooth = 0
        current: dict[str, Optional[int]] = {TRIANGLES: None, LINES: None, POINTS: None}

        face_tokens: list[str] = []
        faces: list[tuple[int, ...]] = []
        line_tokens: list[str] = []
        lines: list[tuple[int, ...]] = []
        point_tokens: list[str] = []
        points: list[tuple[int, ...]] = []

        def mesh_for(kind: str) -> int:
            found = current[kind]
            if found is None:
                if object_name and group_name:
                    part = '%s_%s' % (object_name, group_name)
                else:
                    part = object_name or group_name
                key = (part, material, kind)
                found = mesh_keys.get(key)
                if found is None:
                    found = mesh_keys[key] = len(mesh_keys)
                    mesh_part.append(part_order.setdefault(part, len(part_order)))
                current[kind] = found
            return found

        for number, line in logical_lines(text):
            hash_at = line.find('#')
            if hash_at >= 0:
                line = line[:hash_at]
            parts = line.split()
            if not parts:
                continue
            word = parts[0]
            if word == 'v':
                if len(parts) < 4:
                    raise self.error(number, 'a vertex needs three numbers, not %d' % (len(parts) - 1))
                position_tokens.extend(parts[1:4])
                if len(parts) >= 7:
                    colour_rows.append(vertices)
                    colour_tokens.extend(parts[4:7])
                vertices += 1
            elif word == 'vt':
                if len(parts) < 2:
                    raise self.error(number, 'a texture coordinate needs a number')
                texcoord_tokens.append(parts[1])
                texcoord_tokens.append(parts[2] if len(parts) > 2 else '0')
                texcoords += 1
            elif word == 'vn':
                if len(parts) < 4:
                    raise self.error(number, 'a normal needs three numbers, not %d' % (len(parts) - 1))
                normal_tokens.extend(parts[1:4])
                normals += 1
            elif word == 'f':
                count = len(parts) - 1
                if count < 3:
                    ignored['f (fewer than three corners)'] += 1
                    continue
                face_tokens.extend(parts[1:])
                faces.append((number, mesh_for(TRIANGLES), smooth, vertices, texcoords,
                              normals, count))
            elif word == 'l':
                count = len(parts) - 1
                if count < 2:
                    ignored['l (fewer than two points)'] += 1
                    continue
                line_tokens.extend(parts[1:])
                lines.append((number, mesh_for(LINES), 0, vertices, texcoords, normals, count))
            elif word == 'p':
                count = len(parts) - 1
                if count < 1:
                    ignored['p (no points)'] += 1
                    continue
                point_tokens.extend(parts[1:])
                points.append((number, mesh_for(POINTS), 0, vertices, texcoords, normals, count))
            elif word == 'usemtl' or word == 'usemat':
                material = ' '.join(parts[1:])
                current = dict.fromkeys(current)
            elif word == 'o':
                object_name = _name_of(parts)
                group_name = ''
                current = dict.fromkeys(current)
            elif word == 'g':
                group_name = _name_of(parts)
                if group_name == 'default':
                    group_name = ''
                current = dict.fromkeys(current)
            elif word == 's':
                smooth = 0
                if len(parts) > 1 and parts[1] != 'off':
                    try:
                        smooth = max(0, int(parts[1]))
                    except ValueError:
                        raise self.error(number, 'smoothing group %r is not a number' % (parts[1],)) from None
            elif word == 'mtllib':
                result.libraries.append(' '.join(parts[1:]))
            else:
                ignored[word] += 1

        positions = self.numbers(text, 'v', position_tokens, 3)
        colours = self.colours(colour_tokens, colour_rows, vertices)
        uvs = self.numbers(text, 'vt', texcoord_tokens, 2)
        directions = self.numbers(text, 'vn', normal_tokens, 3)
        counts = (vertices, texcoords, normals)

        corners = _Corners(self, counts)
        face_records = _Records(faces)
        triangle_face, triangle_corner = corners.faces(face_records, face_tokens, positions)
        emissions = [corners.triangles(triangle_face, triangle_corner, face_records),
                     corners.segments(_Records(lines), line_tokens),
                     corners.singles(_Records(points), point_tokens)]
        built = _build(emissions, positions, uvs, directions, colours, len(mesh_keys))
        parts_by_order: dict[int, ObjPart] = {}
        names = {order: part for part, order in part_order.items()}
        keys = sorted(mesh_keys, key=mesh_keys.__getitem__)
        for mesh_id, mesh in built.items():
            part_name, material_name, kind = keys[mesh_id]
            mesh.kind = kind
            mesh.material = material_name
            order = mesh_part[mesh_id]
            parts_by_order.setdefault(order, ObjPart(names[order])).meshes.append(mesh)
        result.parts = [parts_by_order[order] for order in sorted(parts_by_order)]
        return result

    def numbers(self, text: str, word: str, tokens: list[str], width: int) -> np.ndarray:
        """``tokens`` as an ``(n, width)`` float64 array; a bad one names its line"""
        if not tokens:
            return np.zeros((0, width))
        try:
            values = np.array(tokens, dtype=np.float64)
        except ValueError:
            self.find_bad_number(text, word)
            raise
        if not np.isfinite(values).all():
            self.find_bad_number(text, word)
        return values.reshape(-1, width)

    def find_bad_number(self, text: str, word: str) -> None:
        """Raise for the first ``word`` statement holding an unreadable number"""
        width = {'v': 3, 'vt': 2, 'vn': 3}[word]
        for number, line in logical_lines(text):
            parts = line.split('#', 1)[0].split()
            if not parts or parts[0] != word:
                continue
            for token in parts[1:1 + width]:
                try:
                    value = float(token)
                except ValueError:
                    raise self.error(number, 'cannot read %r as a number' % (token,)) from None
                if not math.isfinite(value):
                    raise self.error(number, '%r is not a finite number' % (token,))

    def colours(self, tokens: list[str], rows: list[int], vertices: int) -> Optional[np.ndarray]:
        """Per-vertex RGBA from the ``v`` statements that carried colours, or None"""
        if not rows:
            return None
        rgb = self.colour_values(tokens)
        if rgb.max() > 1.0:
            rgb = rgb / 255.0
        colours = np.ones((vertices, 4))
        colours[rows, :3] = rgb
        return colours

    def colour_values(self, tokens: list[str]) -> np.ndarray:
        try:
            values = np.array(tokens, dtype=np.float64)
        except ValueError as err:
            raise ValueError('%s: a vertex colour is not a number (%s)' % (self.name, err)) from None
        if not np.isfinite(values).all():
            raise ValueError('%s: a vertex colour is not finite' % (self.name,))
        return values.reshape(-1, 3)


class _Records:
    """The statements of one kind (faces, lines or points), as columns

    ``line`` is each statement's line number, ``mesh`` the mesh it draws into,
    ``smooth`` its smoothing group, ``seen`` how many vertices, texture
    coordinates and normals the file had defined before it (what a relative
    index counts back from) and ``size`` its number of corners.
    """

    def __init__(self, rows: list[tuple[int, ...]]) -> None:
        table = np.array(rows, dtype=np.int64).reshape(-1, 7)
        self.line = table[:, 0]
        self.mesh = table[:, 1]
        self.smooth = table[:, 2]
        self.seen = table[:, 3:6]
        self.size = table[:, 6]

    def __len__(self) -> int:
        return len(self.size)


class _Corners:
    """Resolves the corners of faces, lines and points to element indices, and cuts faces into triangles"""

    def __init__(self, reader: _Reader, counts: tuple[int, int, int]) -> None:
        self.reader = reader
        self.counts = counts

    def resolve(self, tokens: list[str], records: '_Records') -> np.ndarray:
        """Each corner's zero-based ``(vertex, texcoord, normal)``, -1 where omitted

        Raises ``ValueError`` for a corner that is not an index, or one outside
        what the file defines.
        """
        sizes = records.size
        raw = self.split(tokens, records, sizes)
        known = np.repeat(records.seen, sizes, axis=0)
        totals = self.counts
        what = ('vertex', 'texture coordinate', 'normal')
        resolved = np.full(raw.shape, -1, dtype=np.int64)
        for column in range(3):
            raw_column = raw[:, column]
            present = raw_column != 0
            index = np.where(raw_column < 0, known[:, column] + raw_column, raw_column - 1)
            bad = present & ((index < 0) | (index >= totals[column]))
            if column == 0:
                bad |= ~present
            if bad.any():
                corner = int(np.flatnonzero(bad)[0])
                record = int(np.searchsorted(np.cumsum(sizes), corner, side='right'))
                shown = int(raw_column[corner])
                raise self.reader.error(
                    int(records.line[record]), '%s index %d is out of range (%d defined)'
                    % (what[column], shown, totals[column]))
            resolved[:, column] = np.where(present, index, -1)
        return resolved

    def split(self, tokens: list[str], records: '_Records', sizes: np.ndarray) -> np.ndarray:
        """``(corners, 3)`` signed one-based indices, 0 where a part is omitted"""
        kinds = set(map(str.count, tokens, itertools.repeat('/')))
        if len(kinds) == 1 and next(iter(kinds)) <= 2:
            slashes = next(iter(kinds))
            flat = ' '.join(tokens).replace('//', '/0/').replace('/', ' ').split()
            try:
                values = np.array(flat, dtype=np.int64).reshape(len(tokens), slashes + 1)
            except ValueError:
                return self.split_slowly(tokens, records, sizes)
            raw = np.zeros((len(tokens), 3), dtype=np.int64)
            raw[:, :slashes + 1] = values
            return raw
        return self.split_slowly(tokens, records, sizes)

    def split_slowly(self, tokens: list[str], records: '_Records', sizes: np.ndarray) -> np.ndarray:
        """:meth:`split` for corners of mixed forms, naming the line of a bad one"""
        raw = np.zeros((len(tokens), 3), dtype=np.int64)
        record_of = np.repeat(np.arange(len(records)), sizes)
        for corner, token in enumerate(tokens):
            number = int(records.line[record_of[corner]])
            pieces = token.split('/')
            if len(pieces) > 3:
                raise self.reader.error(number, 'corner %r has %d parts, at most three' % (token, len(pieces)))
            for column, piece in enumerate(pieces):
                if piece:
                    try:
                        raw[corner, column] = int(piece)
                    except ValueError:
                        raise self.reader.error(number, 'corner %r is not an index' % (token,)) from None
        return raw

    def faces(self, records: '_Records', tokens: list[str],
              positions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Triangles of every face: ``(face of each, (T, 3) corners it uses)``

        The corners index :meth:`resolved` of the faces' corner list, so the
        caller keeps that list beside them in ``self.face_corners``.
        """
        self.face_corners = self.resolve(tokens, records) if records else np.zeros((0, 3), np.int64)
        if not records:
            return np.zeros(0, np.int64), np.zeros((0, 3), np.int64)
        sizes = records.size
        starts = np.cumsum(sizes) - sizes
        corner_positions = positions[self.face_corners[:, 0]]
        face_ids = np.arange(len(records))
        found_faces = []
        found_corners = []

        three = sizes == 3
        if three.any():
            found_faces.append(face_ids[three])
            found_corners.append(starts[three, None] + np.array([0, 1, 2]))
        four = sizes == 4
        if four.any():
            local = _split_quads(corner_positions[starts[four, None] + np.arange(4)])
            found_faces.append(np.repeat(face_ids[four], 2))
            found_corners.append((starts[four, None, None] + local).reshape(-1, 3))
        for size in np.unique(sizes[sizes > 4]).tolist():
            group = np.flatnonzero(sizes == size)
            outlines = corner_positions[starts[group, None] + np.arange(size)]
            convex = ~_reflex(outlines).any(axis=1)
            if convex.any():
                fan = np.stack([np.zeros(size - 2, np.int64), np.arange(1, size - 1),
                                np.arange(2, size)], axis=1)
                found_faces.append(np.repeat(group[convex], size - 2))
                found_corners.append((starts[group[convex], None, None] + fan).reshape(-1, 3))
            for face, outline in zip(group[~convex], outlines[~convex]):
                triangles = np.array(_polygon_triangles(outline), dtype=np.int64)
                found_faces.append(np.full(len(triangles), face))
                found_corners.append(starts[face] + triangles)
        if not found_faces:
            return np.zeros(0, np.int64), np.zeros((0, 3), np.int64)
        triangle_face = np.concatenate(found_faces)
        triangle_corner = np.concatenate(found_corners)
        order = np.argsort(triangle_face, kind='stable')
        return triangle_face[order], triangle_corner[order]

    def triangles(self, triangle_face: np.ndarray, triangle_corner: np.ndarray,
                  records: '_Records') -> '_Emission':
        """The triangles' corners, each tagged with its mesh and smoothing key"""
        if not len(triangle_face):
            return _Emission.empty()
        meshes = records.mesh
        smooth = records.smooth
        flat = triangle_corner.ravel()
        corners = self.face_corners[flat]
        faces = np.repeat(triangle_face, 3)
        group = smooth[faces]
        # A corner that names its own normal needs no group; one without is
        # shared across its smoothing group, or alone with its face's number.
        key = np.where(corners[:, 2] >= 0, 0,
                       np.where(group > 0, group + len(records) + 1, len(records) - faces))
        return _Emission(TRIANGLES, corners, meshes[faces], key)

    def segments(self, records: '_Records', tokens: list[str]) -> '_Emission':
        """The ends of each line segment of every ``l`` statement"""
        if not records:
            return _Emission.empty()
        corners = self.resolve(tokens, records)
        sizes = records.size
        starts = np.cumsum(sizes) - sizes
        pieces = [np.repeat(starts[i] + np.arange(int(sizes[i]) - 1), 2) + np.tile([0, 1], int(sizes[i]) - 1)
                  for i in range(len(records))]
        flat = np.concatenate(pieces)
        meshes = np.repeat(records.mesh, (sizes - 1) * 2)
        corners = corners[flat]
        corners[:, 2] = -1
        return _Emission(LINES, corners, meshes, np.zeros(len(flat), np.int64))

    def singles(self, records: '_Records', tokens: list[str]) -> '_Emission':
        """Each point of every ``p`` statement"""
        if not records:
            return _Emission.empty()
        corners = self.resolve(tokens, records)
        meshes = np.repeat(records.mesh, records.size)
        corners[:, 2] = -1
        return _Emission(POINTS, corners, meshes, np.zeros(len(corners), np.int64))


@dataclass
class _Emission:
    """The corners of one kind of primitive, each with the mesh it draws into and its smoothing key"""
    kind: str
    corners: np.ndarray
    meshes: np.ndarray
    keys: np.ndarray

    @classmethod
    def empty(cls) -> '_Emission':
        return cls('', np.zeros((0, 3), np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64))


def _reflex(outlines: np.ndarray) -> np.ndarray:
    """Whether each corner of each ``(n, k, 3)`` outline turns against the outline's own direction

    Entry ``[n, i]`` is the turn at corner ``i + 1``. A turn within rounding of
    straight is not reflex.
    """
    around = np.roll(outlines, -1, axis=1)
    normal = np.cross(outlines, around).sum(axis=1)
    edges = around - outlines
    turn = np.einsum('nij,nj->ni', np.cross(edges, np.roll(edges, -1, axis=1)), normal)
    scale = np.linalg.norm(normal, axis=1) * (np.square(edges).sum(axis=2).mean(axis=1))
    reflex: np.ndarray = turn < -_FLAT * scale[:, None]
    return reflex


def _split_quads(quads: np.ndarray) -> np.ndarray:
    """``(n, 2, 3)`` local corners of the two triangles that cut each ``(n, 4, 3)`` quad

    A quad with a reflex corner is cut from that corner, the one diagonal inside
    it. A convex quad is cut along its shorter diagonal.
    """
    reflex = _reflex(quads)
    # reflex[i] is the turn at corner i + 1
    corner = (np.argmax(reflex, axis=1) + 1) % 4
    short = np.linalg.norm(quads[:, 0] - quads[:, 2], axis=1) <= np.linalg.norm(quads[:, 1] - quads[:, 3], axis=1)
    corner = np.where(reflex.any(axis=1), corner, np.where(short, 0, 1))
    first = np.stack([corner, (corner + 1) % 4, (corner + 2) % 4], axis=1)
    second = np.stack([corner, (corner + 2) % 4, (corner + 3) % 4], axis=1)
    return np.stack([first, second], axis=1)


def _polygon_triangles(outline: np.ndarray) -> list[tuple[int, int, int]]:
    """Triangles of a polygon of five or more corners, by ear clipping

    The polygon is flattened along its dominant axis. A convex polygon is a fan.
    Where no ear can be cut (a self-intersecting outline), what is left is
    fanned, so every corner is used and the indices stay valid.
    """
    size = len(outline)
    normal = np.cross(outline, np.roll(outline, -1, axis=0)).sum(axis=0)
    axis = int(np.argmax(np.abs(normal)))
    if normal[axis] == 0:
        return [(0, i, i + 1) for i in range(1, size - 1)]
    flat = outline[:, [(axis + 1) % 3, (axis + 2) % 3]].astype(np.float64)
    if normal[axis] < 0:
        flat[:, 0] = -flat[:, 0]
    scale = max(float(np.abs(flat).max()), 1e-30) ** 2 * 1e-12

    def turn(a: int, b: int, c: int) -> float:
        return float((flat[b, 0] - flat[a, 0]) * (flat[c, 1] - flat[a, 1])
                     - (flat[b, 1] - flat[a, 1]) * (flat[c, 0] - flat[a, 0]))

    def coincident(a: int, p: int) -> bool:
        return bool(abs(flat[a, 0] - flat[p, 0]) <= scale ** 0.5 * 1e-6
                    and abs(flat[a, 1] - flat[p, 1]) <= scale ** 0.5 * 1e-6)

    def blocks(a: int, b: int, c: int, p: int) -> bool:
        """Whether corner ``p`` is inside the triangle or on its boundary"""
        if coincident(a, p) or coincident(b, p) or coincident(c, p):
            return False
        return turn(a, b, p) >= -scale and turn(b, c, p) >= -scale and turn(c, a, p) >= -scale

    remaining = list(range(size))
    found: list[tuple[int, int, int]] = []
    while len(remaining) > 3:
        for position in range(len(remaining)):
            a = remaining[position - 1]
            b = remaining[position]
            c = remaining[(position + 1) % len(remaining)]
            if turn(a, b, c) <= scale:
                continue
            if any(blocks(a, b, c, p) for p in remaining if p not in (a, b, c)):
                continue
            found.append((a, b, c))
            del remaining[position]
            break
        else:
            found.extend((remaining[0], remaining[i], remaining[i + 1])
                         for i in range(1, len(remaining) - 1))
            return found
    found.append((remaining[0], remaining[1], remaining[2]))
    return found


def _unique(keys: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """The first row of each distinct combination of ``keys``, and each row's combination

    ``keys`` are non-negative int64 columns, most significant first. The
    combinations come back in key order. Columns are packed into one int64 where
    their ranges allow, which is a single sort; otherwise the rows are sorted
    on every column.
    """
    packed: list[np.ndarray] = []
    current = keys[0].astype(np.int64)
    span = int(current.max()) + 1 if len(current) else 1
    for key in keys[1:]:
        key_span = int(key.max()) + 1 if len(key) else 1
        if span * key_span < 2 ** 62:
            current = current * key_span + key
            span *= key_span
        else:
            packed.append(current)
            current, span = key.astype(np.int64), key_span
    packed.append(current)
    if len(packed) == 1:
        _, first, inverse = np.unique(packed[0], return_index=True, return_inverse=True)
        return first, inverse.reshape(-1)
    order = np.lexsort(packed[::-1])
    columns = np.stack([key[order] for key in packed])
    fresh = np.concatenate([[True], (columns[:, 1:] != columns[:, :-1]).any(axis=0)])
    inverse = np.empty(len(order), np.int64)
    inverse[order] = np.cumsum(fresh) - 1
    return order[np.flatnonzero(fresh)], inverse


def _build(emissions: list[_Emission], positions: np.ndarray, uvs: np.ndarray,
           directions: np.ndarray, colours: Optional[np.ndarray],
           mesh_count: int) -> dict[int, ObjMesh]:
    """The meshes every emitted corner belongs to, one vertex per distinct corner

    Corners that name the same position, texture coordinate, normal (or, with no
    normal, smoothing key) share a vertex. Triangle meshes with corners that
    name no normal get them from their faces, and vertices that then agree on
    position, texture coordinate and normal are merged, so the flat faces of a
    plane share their corners.
    """
    emissions = [emission for emission in emissions if len(emission.meshes)]
    if not emissions:
        return {}
    corners = np.concatenate([emission.corners for emission in emissions])
    meshes = np.concatenate([emission.meshes for emission in emissions])
    smooth = np.concatenate([emission.keys for emission in emissions])
    order = np.argsort(meshes, kind='stable')
    corners, meshes, smooth = corners[order], meshes[order], smooth[order]

    first, inverse = _unique([meshes, corners[:, 0], corners[:, 1] + 1, corners[:, 2] + 1, smooth])
    representative = corners[first]
    vertex_mesh = meshes[first]

    mesh_is_triangles = np.zeros(mesh_count, bool)
    for emission in emissions:
        if emission.kind == TRIANGLES:
            mesh_is_triangles[np.unique(emission.meshes)] = True

    normals = np.zeros((len(first), 3))
    named = representative[:, 2] >= 0
    wanted = ~named & mesh_is_triangles[vertex_mesh]
    if named.any():
        given = directions[representative[named, 2]]
        lengths = np.linalg.norm(given, axis=1, keepdims=True)
        normals[named] = np.divide(given, lengths, out=np.zeros_like(given), where=lengths > 0)
    if wanted.any():
        used = mesh_is_triangles[meshes] & ~named[inverse]
        normals[wanted] = _face_normals(positions[representative[:, 0]].astype(np.float64),
                                        inverse, used, wanted)

    normals32 = normals.astype(np.float32)
    bits = normals32.view(np.int32).astype(np.int64) - np.iinfo(np.int32).min
    keep, merge = _unique([vertex_mesh, representative[:, 0], representative[:, 1] + 1,
                           bits[:, 0], bits[:, 1], bits[:, 2]])
    inverse = merge[inverse]
    representative, vertex_mesh, normals32 = representative[keep], vertex_mesh[keep], normals32[keep]

    vertex_positions = positions[representative[:, 0]].astype(np.float32)
    has_uv = representative[:, 1] >= 0
    vertex_uvs = np.zeros((len(keep), 2), np.float32)
    if has_uv.any():
        vertex_uvs[has_uv] = uvs[representative[has_uv, 1]]
    vertex_colours = colours[representative[:, 0]].astype(np.float32) if colours is not None else None
    uv_present = np.zeros(mesh_count, bool)
    uv_present[np.unique(vertex_mesh[has_uv])] = True

    starts = np.searchsorted(vertex_mesh, np.arange(mesh_count + 1))
    corner_starts = np.searchsorted(meshes, np.arange(mesh_count + 1))
    built = {}
    for mesh_id in range(mesh_count):
        low, high = int(starts[mesh_id]), int(starts[mesh_id + 1])
        if high == low:
            continue
        indices = inverse[corner_starts[mesh_id]:corner_starts[mesh_id + 1]] - low
        built[mesh_id] = ObjMesh(
            kind='', material='',
            positions=vertex_positions[low:high].copy(),
            indices=indices.astype(np.uint32),
            normals=normals32[low:high].copy() if mesh_is_triangles[mesh_id] else None,
            texcoords=vertex_uvs[low:high].copy() if uv_present[mesh_id] else None,
            colors=vertex_colours[low:high].copy() if vertex_colours is not None else None,
        )
    return built


def _face_normals(positions: np.ndarray, inverse: np.ndarray, use: np.ndarray,
                  wanted: np.ndarray) -> np.ndarray:
    """Unit normals of the ``wanted`` vertices, from the triangles at their ``use`` corners

    Each triangle adds its unit face normal to its three vertices weighted by
    the angle it makes there. A vertex no triangle reaches, or only degenerate
    ones, faces +Z.
    """
    corner_vertex = inverse.reshape(-1, 3)
    used = use.reshape(-1, 3)[:, 0]
    corner_vertex = corner_vertex[used]
    corners = positions[corner_vertex]
    edge_ab, edge_bc, edge_ca = (corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 1],
                                 corners[:, 0] - corners[:, 2])
    cross = np.cross(edge_ab, -edge_ca)
    area = np.linalg.norm(cross, axis=1, keepdims=True)
    face = np.divide(cross, area, out=np.zeros_like(cross), where=area > 0)

    def angle(first: np.ndarray, second: np.ndarray) -> np.ndarray:
        lengths = np.linalg.norm(first, axis=1) * np.linalg.norm(second, axis=1)
        cosine = np.divide(np.einsum('ij,ij->i', first, second), lengths,
                           out=np.ones_like(lengths), where=lengths > 0)
        radians: np.ndarray = np.arccos(np.clip(cosine, -1.0, 1.0))
        return radians

    weights = np.stack([angle(edge_ab, -edge_ca), angle(edge_bc, -edge_ab),
                        angle(edge_ca, -edge_bc)], axis=1)
    total = np.zeros((len(positions), 3))
    for corner in range(3):
        for axis in range(3):
            total[:, axis] += np.bincount(corner_vertex[:, corner],
                                          weights=face[:, axis] * weights[:, corner],
                                          minlength=len(positions))
    total = total[wanted]
    lengths = np.linalg.norm(total, axis=1, keepdims=True)
    unit: np.ndarray = np.divide(total, lengths, out=np.zeros_like(total), where=lengths > 1e-12)
    unit[(lengths <= 1e-12)[:, 0]] = (0.0, 0.0, 1.0)
    return unit
