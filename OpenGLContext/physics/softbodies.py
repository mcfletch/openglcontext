"""Soft bodies: cloth, ropes and pressure balls, and the handle a game drives one by.

A :class:`SoftBodySpec` is particles (``positions``, each with a mass) held
by constraints: edges with a ``compliance`` (the inverse of stiffness, m/N;
0 is rigid), shear edges across each quad, bend constraints across each pair
of faces, volume constraints on tetrahedra and long-range attachments that
keep each free particle within reach of the nearest pinned one. A closed
surface may hold a ``pressure`` (n R T, Pa m3). The builders make the common
cases: :meth:`~SoftBodySpec.cloth`, :meth:`~SoftBodySpec.rope`,
:meth:`~SoftBodySpec.ball` and :meth:`~SoftBodySpec.from_mesh`.

:meth:`Physics.add_soft_body <OpenGLContext.physics.service.Physics.add_soft_body>`
puts one in the world and returns a :class:`SoftBody`. It is a body: it meets
rigid bodies by the world's collision filters, sleeps and wakes, and is
removed with :meth:`SoftBody.remove`. Soft bodies do not collide with each
other. Its vertices are read with :meth:`SoftBody.frame`, a
:class:`SoftBodyFrame` whose ``version`` moves only when the world moved
them, so a renderer uploads a still cloth once.

This module holds no engine type: the Jolt engine turns a spec into its own
settings when the body is added.
"""
from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple

import numpy as np

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.service import Physics

__all__ = ['BENDS', 'LONG_RANGE', 'SoftBody', 'SoftBodyFrame', 'SoftBodySpec']

#: The bend constraints a spec can ask for across each pair of faces.
BENDS = ('none', 'distance', 'dihedral')
#: The long-range attachments to the nearest pinned vertex.
LONG_RANGE = ('none', 'euclidean', 'geodesic')


@dataclasses.dataclass(eq=False)
class SoftBodySpec:
    """A soft body's particles, constraints and material.

    ``positions`` (V, 3) are metres in the body's frame. ``mass`` (kg) is
    shared among the vertices equally, or ``masses`` (V,) gives each its own;
    a vertex of mass 0 is fixed where it is placed. ``faces`` (F, 3) are
    counter-clockwise seen from the side their normal faces. Edges, shear and
    bend constraints come from the faces, unless ``edges`` (E, 2) are given
    with ``edge_compliance`` (E,). ``tetrahedra`` (T, 4) hold their volume
    with ``volume_compliance``. Compliances are m/N, 0 rigid and ``inf`` for
    none. ``bend`` is one of :data:`BENDS`; the default distance constraints
    of compliance 0.01 keep a fine cloth whole where it meets a surface.
    ``iterations`` is the solver's per step; None takes enough for the
    shortest edge (5 from 5 cm up, more below). ``linear_damping`` is 1/s,
    ``max_velocity`` m/s and ``vertex_radius`` (m) the distance the vertices
    keep from the surfaces they meet.
    """

    positions: np.ndarray
    faces: np.ndarray | None = None
    edges: np.ndarray | None = None
    edge_compliance: np.ndarray | None = None
    tetrahedra: np.ndarray | None = None
    mass: float = 1.0
    masses: np.ndarray | None = None
    compliance: float = 0.0
    shear_compliance: float = 0.0
    bend_compliance: float = 0.01
    bend: str = 'distance'
    volume_compliance: float = 0.0
    pressure: float = 0.0
    long_range: str = 'none'
    long_range_stretch: float = 1.0
    iterations: int | None = None
    linear_damping: float = 0.1
    max_velocity: float = 500.0
    friction: float = 0.2
    restitution: float = 0.0
    gravity_factor: float = 1.0
    vertex_radius: float = 0.0
    allow_sleep: bool = True
    double_sided: bool = False
    #: A :meth:`cloth`'s (columns, rows) of vertices; None for other shapes.
    grid: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        self.positions = np.ascontiguousarray(self.positions, dtype='d').reshape(-1, 3)
        count = len(self.positions)
        if count == 0:
            raise ValueError('a soft body has at least one vertex')
        if not np.isfinite(self.positions).all():
            raise ValueError('soft body positions are finite')
        for name, width in (('faces', 3), ('edges', 2), ('tetrahedra', 4)):
            value = getattr(self, name)
            if value is not None:
                array = np.ascontiguousarray(value, dtype=np.uint32).reshape(-1, width)
                if array.size and int(array.max()) >= count:
                    raise ValueError('%s name a vertex past the %d there are' % (name, count))
                setattr(self, name, array)
        if self.bend not in BENDS:
            raise ValueError('bend is one of %s, not %r' % (', '.join(BENDS), self.bend))
        if self.long_range not in LONG_RANGE:
            raise ValueError('long_range is one of %s, not %r'
                             % (', '.join(LONG_RANGE), self.long_range))
        if not (math.isfinite(self.mass) and self.mass >= 0.0):
            raise ValueError('mass is finite and not negative, not %r' % (self.mass,))
        if self.masses is not None:
            self.masses = np.ascontiguousarray(self.masses, dtype='d').reshape(count)
            if not (np.isfinite(self.masses).all() and (self.masses >= 0).all()):
                raise ValueError('masses are finite and not negative')
        if self.grid is not None:
            self.grid = (int(self.grid[0]), int(self.grid[1]))

    def __len__(self) -> int:
        return len(self.positions)

    def total_mass(self) -> float:
        """The vertices' mass together, kg."""
        return float(self.masses.sum()) if self.masses is not None else float(self.mass)

    def corner_indices(self) -> tuple[int, int, int, int]:
        """A :meth:`cloth`'s corner vertices: (-x -z, +x -z, -x +z, +x +z)."""
        if self.grid is None:
            raise ValueError('only a cloth made by SoftBodySpec.cloth has corners')
        columns, rows = self.grid
        return (0, columns - 1, (rows - 1) * columns, rows * columns - 1)

    # -- builders ---------------------------------------------------------
    @classmethod
    def cloth(cls, width: float, depth: float, columns: int, rows: int, mass: float = 1.0,
              **values: Any) -> SoftBodySpec:
        """A flat cloth ``width`` (x) by ``depth`` (z) metres in the y = 0 plane, centred.

        ``columns`` by ``rows`` vertices, row major from -x -z; faces up (+y).
        ``values`` are further fields.
        """
        if columns < 2 or rows < 2:
            raise ValueError('a cloth has at least 2 columns and 2 rows of vertices')
        x = np.linspace(-width / 2.0, width / 2.0, columns)
        z = np.linspace(-depth / 2.0, depth / 2.0, rows)
        gx, gz = np.meshgrid(x, z)
        positions = np.stack([gx.ravel(), np.zeros(gx.size), gz.ravel()], axis=1)
        i = (np.arange(rows - 1)[:, None] * columns + np.arange(columns - 1)[None, :]).ravel()
        faces = np.concatenate([np.stack([i, i + columns, i + 1], axis=1),
                                np.stack([i + 1, i + columns, i + columns + 1], axis=1)])
        return cls(positions, faces=faces, mass=mass, grid=(columns, rows), **values)

    @classmethod
    def rope(cls, points: Any, segments: int | None = None, mass: float = 0.1,
             bend_compliance: float = math.inf, **values: Any) -> SoftBodySpec:
        """A rope along the polyline ``points`` (metres in the body's frame).

        ``segments`` resamples it to that many equal segments; None keeps the
        points. Each segment is an edge of compliance ``compliance``; a finite
        ``bend_compliance`` adds an edge across every second vertex.
        """
        polyline = np.asarray(points, dtype='d').reshape(-1, 3)
        if len(polyline) < 2:
            raise ValueError('a rope has at least two points')
        if segments is not None:
            lengths = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(polyline, axis=0), axis=1))]
            at = np.linspace(0.0, lengths[-1], int(segments) + 1)
            polyline = np.stack([np.interp(at, lengths, polyline[:, k]) for k in range(3)],
                                axis=1)
        count = len(polyline)
        stretch = float(values.get('compliance', 0.0))
        edges = [np.stack([np.arange(count - 1), np.arange(1, count)], axis=1)]
        compliance = [np.full(count - 1, stretch)]
        if math.isfinite(bend_compliance) and count > 2:
            edges.append(np.stack([np.arange(count - 2), np.arange(2, count)], axis=1))
            compliance.append(np.full(count - 2, bend_compliance))
        return cls(polyline, edges=np.concatenate(edges),
                   edge_compliance=np.concatenate(compliance).astype(np.float32), mass=mass,
                   bend_compliance=bend_compliance, **values)

    @classmethod
    def ball(cls, radius: float = 0.5, subdivisions: int = 2, pressure: float = 1000.0,
             mass: float = 1.0, **values: Any) -> SoftBodySpec:
        """A closed sphere of ``radius`` held round by ``pressure``.

        An icosahedron with each face split ``subdivisions`` times into four.
        """
        positions, faces = icosphere(subdivisions)
        values.setdefault('bend', 'none')
        return cls(positions * radius, faces=faces, pressure=pressure, mass=mass, **values)

    @classmethod
    def from_mesh(cls, positions: Any, faces: Any, mass: float = 1.0,
                  **values: Any) -> SoftBodySpec:
        """A soft body of a triangle mesh: its vertices, and constraints from its faces."""
        return cls(np.asarray(positions), faces=np.asarray(faces), mass=mass, **values)

    # -- files ------------------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        """The spec as plain data, arrays as lists, for a file or a document's extras."""
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if isinstance(value, np.ndarray):
                value = value.tolist()
            elif isinstance(value, tuple):
                value = list(value)
            elif isinstance(value, float) and not math.isfinite(value):
                value = str(value)
            out[f.name] = value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SoftBodySpec:
        """The spec :meth:`as_dict` wrote; a field it does not name takes its default."""
        values = dict(data)
        for name, value in list(values.items()):
            if isinstance(value, str) and value in ('inf', '-inf', 'nan'):
                values[name] = float(value)
        if values.get('grid') is not None:
            values['grid'] = tuple(values['grid'])
        return cls(**values)


class SoftBodyFrame(NamedTuple):
    """A soft body's vertices as the newest step left them.

    ``origin`` (3,) is the body's centre of mass in metres; ``positions``
    (V, 3) float32 are the vertices relative to it and ``normals`` (V, 3)
    their area-weighted unit normals. ``version`` moves each time the world
    moves the vertices; ``tick`` is the step the frame was read from. The
    arrays are read-only views valid until the next frame is read.
    """
    version: int
    tick: int
    origin: np.ndarray
    positions: np.ndarray
    normals: np.ndarray


class SoftBody:
    """One soft body of a physics service: the commands that hold and push it, and its vertices."""

    def __init__(self, physics: Physics, body: Body, spec: SoftBodySpec) -> None:
        self.physics = physics
        #: The body handle: handlers, removal and the uid.
        self.body = body
        #: The spec the body was made from.
        self.spec = spec
        #: Where the body was placed: position (3,) and quaternion (4,).
        self._pose: tuple[np.ndarray, np.ndarray] = (np.zeros(3), np.array([0.0, 0.0, 0.0, 1.0]))

    def __repr__(self) -> str:
        return 'SoftBody(%d, vertices=%d)' % (self.body.uid, len(self.spec))

    @property
    def uid(self) -> int:
        """The body's uid."""
        return self.body.uid

    @property
    def alive(self) -> bool:
        """False once the body has been removed."""
        return self.body.alive

    def pin(self, vertices: Sequence[int], points: Any,
            bodies: Sequence[Body | None] | Body | None = None) -> None:
        """Replace the pins: each vertex follows its point, in the world or in a body's frame.

        ``points`` (n, 3) are world points, or points in the frame of the
        body at the same index of ``bodies`` (one body for all, or None for
        the world). A pinned vertex is moved to its point every step and does
        not pull on its body. A vertex no longer pinned takes back its mass.
        """
        indices = np.ascontiguousarray(vertices, dtype=np.int64).reshape(-1)
        if len(indices) and (indices.min() < 0 or indices.max() >= len(self.spec)):
            raise ValueError('a pinned vertex is one of the %d the body has' % len(self.spec))
        places = np.asarray(points, dtype='d').reshape(len(indices), 3)
        if not np.isfinite(places).all():
            raise ValueError('pin points are finite')
        if bodies is None or not isinstance(bodies, Sequence):
            owners: list[Body | None] = [bodies] * len(indices)
        else:
            owners = list(bodies)
            if len(owners) != len(indices):
                raise ValueError('one body (or None) a pinned vertex')
        self.physics._soft_command(self, 'soft_pins', indices, places, owners)

    def unpin(self) -> None:
        """Remove every pin; the vertices fall free with their own masses."""
        self.pin([], np.zeros((0, 3)))

    def set_wind(self, force: Any) -> None:
        """A force (N) on the body, shared among its vertices every step until changed."""
        push = np.asarray(force, dtype='d').reshape(3)
        if not np.isfinite(push).all():
            raise ValueError('wind is a finite force')
        self.physics._soft_command(self, 'wind', tuple(float(v) for v in push))

    def remove(self) -> None:
        """Take the body out of the world. Removing twice is harmless."""
        self.physics.remove(self.body)

    def frame(self) -> SoftBodyFrame | None:
        """The vertices as the newest step left them, or None before the world holds the body."""
        return self.physics._soft_frame(self)

    def vertices(self) -> np.ndarray:
        """(V, 3) the vertices in world coordinates, float64 (a copy); the rest pose before the first step."""
        found = self.frame()
        if found is None:
            return self.physics._soft_rest(self)
        out: np.ndarray = found.positions.astype('d') + found.origin
        return out


def icosphere(subdivisions: int) -> tuple[np.ndarray, np.ndarray]:
    """A unit icosphere's vertices (V, 3) and outward faces (F, 3), each face split ``subdivisions`` times."""
    t = (1.0 + math.sqrt(5.0)) / 2.0
    points = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
              (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
             (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
             (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    vertices = [np.array(p, dtype='d') / np.linalg.norm(p) for p in points]
    for _ in range(int(subdivisions)):
        middle: dict[tuple[int, int], int] = {}

        def between(a: int, b: int, middle: dict[tuple[int, int], int] = middle) -> int:
            key = (min(a, b), max(a, b))
            if key not in middle:
                m = vertices[a] + vertices[b]
                vertices.append(m / np.linalg.norm(m))
                middle[key] = len(vertices) - 1
            return middle[key]

        finer = []
        for a, b, c in faces:
            ab, bc, ca = between(a, b), between(b, c), between(c, a)
            finer += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = finer
    return np.array(vertices), np.array(faces, dtype=np.uint32)
