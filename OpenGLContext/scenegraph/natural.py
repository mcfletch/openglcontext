"""Stones, timber and dry-stone walls that look grown rather than modelled. No GL.

:func:`stone` is a rock made by scraping: a sphere has a flat disc pressed into it at several
places, each flattening what lies under it and leaving the rest, and it is then roughened at
three scales. The method is the one the README of ``gl-rock`` (Erkaman, MIT licence; see
``license.txt``) describes; the code here is written from that description. :func:`timber` is
a trunk with a crooked axis, an out-of-round section, fissured bark, knots and sawn ends.
:func:`rubble` is a low wall of lumpy stone along a line.

Each takes the ``numpy`` generator it draws from, so the same generator makes the same piece,
and returns :class:`~OpenGLContext.scenegraph.surfaces.Geometry` to wear a material and to be
placed with :func:`~OpenGLContext.scenegraph.surfaces.placed` and
:func:`~OpenGLContext.scenegraph.surfaces.merge`.

Textures are laid on the geometry rather than wrapped around it: a stone's faces are projected
along their dominant axis so a photograph keeps its scale on every face, and bark runs its
fissures along the trunk. Each function says how many metres one repeat of its texture covers.
"""
import functools
import math

import numpy as np
from OpenGLContext.scenegraph import surfaces as sf
from OpenGLContext.scenegraph.surfaces import Geometry

#: How many scrapes a stone takes, how wide each is (the angle it spans seen from the centre of
#: the stone, in radians) and how deep (as a fraction of the stone's radius), and the least
#: angle between the centres of two scrapes.
SCRAPES = (7, 13)
SCRAPE_SPAN = (0.4, 0.9)
SCRAPE_DEPTH = (0.12, 0.42)
SCRAPE_APART = 0.5
#: Displacement of the surface at each of three scales, as a fraction of the radius: lumps,
#: undulations and grain.
ROUGHNESS = ((1.5, 3.0, 0.06), (4.0, 7.0, 0.022), (9.0, 16.0, 0.006))
TERMS = 5
#: How much of a stone's shading follows each flat face rather than the smooth surface, from 0 to 1.
FACETING = 0.45


@functools.cache
def _icosphere(divisions: int) -> tuple[np.ndarray, np.ndarray]:
    """The unit icosphere of ``divisions`` subdivisions: shared vertices and triangles."""
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    corners = [(-1, phi, 0), (1, phi, 0), (-1, -phi, 0), (1, -phi, 0), (0, -1, phi), (0, 1, phi),
               (0, -1, -phi), (0, 1, -phi), (phi, 0, -1), (phi, 0, 1), (-phi, 0, -1),
               (-phi, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
             (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
             (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    points = np.array(corners, dtype=float)
    points /= np.linalg.norm(points, axis=1, keepdims=True)
    triangles = np.array(faces)
    for _ in range(divisions):
        points, triangles = _subdivided(points, triangles)
    points.flags.writeable = triangles.flags.writeable = False
    return points, triangles


def _subdivided(points: np.ndarray, triangles: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each triangle cut into four, new vertices pushed out onto the unit sphere."""
    made: dict[tuple[int, int], int] = {}
    vertices = list(points)

    def middle(a: int, b: int) -> int:
        key = (a, b) if a < b else (b, a)
        if key not in made:
            mid = (points[a] + points[b]) / 2.0
            vertices.append(mid / np.linalg.norm(mid))
            made[key] = len(vertices) - 1
        return made[key]

    out = []
    for a, b, c in triangles:
        ab, bc, ca = middle(a, b), middle(b, c), middle(c, a)
        out += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
    return np.array(vertices), np.array(out)


def smooth_normals(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """A normal for each vertex: the faces about it, each weighted by its area."""
    corners = points[triangles]
    faces = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    normals = np.zeros_like(points)
    for corner in range(3):
        np.add.at(normals, triangles[:, corner], faces)
    length = np.linalg.norm(normals, axis=1, keepdims=True)
    return np.asarray(normals / np.maximum(length, 1e-12))


def waves(rng: np.random.Generator, points: np.ndarray, low: float, high: float) -> np.ndarray:
    """Smooth noise at each point: a few waves of random direction, phase and frequency.

    ``low`` and ``high`` bound the frequency in cycles across a unit sphere. The result is
    near zero on average and within about one unit.
    """
    total = np.zeros(len(points))
    for _ in range(TERMS):
        direction = rng.normal(size=3)
        direction /= np.linalg.norm(direction)
        frequency = rng.uniform(low, high) * 2.0 * math.pi
        total += np.sin(points @ direction * frequency + rng.uniform(0.0, 2.0 * math.pi))
    return total / math.sqrt(TERMS)


def projected(points: np.ndarray, normals: np.ndarray, triangles: np.ndarray,
               repeat: float) -> Geometry:
    """A triangle soup of the mesh with each face's texture laid along its dominant axis.

    The vertices keep their smooth normals, so the faces light as one surface and the texture
    changes direction only where a face turns from one axis to another.
    """
    corners = points[triangles]
    faces = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    axis = np.argmax(np.abs(faces), axis=1)
    u_axis, v_axis = (axis + 1) % 3, (axis + 2) % 3
    flat = triangles.reshape(-1)
    soup = points[flat]
    face_unit = faces / np.maximum(np.linalg.norm(faces, axis=1, keepdims=True), 1e-12)
    soup_normals = normals[flat] * (1.0 - FACETING) + np.repeat(face_unit, 3, axis=0) * FACETING
    soup_normals /= np.maximum(np.linalg.norm(soup_normals, axis=1, keepdims=True), 1e-12)
    rows = np.arange(len(soup))
    across = np.repeat(u_axis, 3)
    down = np.repeat(v_axis, 3)
    uv = np.stack([soup[rows, across], soup[rows, down]], axis=-1) / repeat
    unit = np.zeros((len(soup), 3))
    unit[rows, across] = 1.0
    tangent = unit - soup_normals * np.sum(unit * soup_normals, axis=1, keepdims=True)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
    toward_v = np.zeros((len(soup), 3))
    toward_v[rows, down] = 1.0
    handed = np.sum(np.cross(soup_normals, tangent) * -toward_v, axis=1)
    sign = np.where(handed >= 0.0, 1.0, -1.0)
    return Geometry(soup.astype('f'), soup_normals.astype('f'), uv.astype('f'),
                    np.concatenate([tangent, sign[:, None]], axis=1).astype('f'),
                    np.arange(len(soup), dtype=np.uint32))


def scrape(rng: np.random.Generator, unit: np.ndarray, count: int) -> np.ndarray:
    """``unit`` (points on a unit sphere) with ``count`` flat discs pressed into it.

    A disc has a centre direction, a span and a depth. Every point within the span whose
    height along the direction is above the disc's plane is moved onto the plane; the points
    beyond the span stay, so each scrape leaves a flat face with a step at its rim.
    """
    shape = unit.copy()
    centres: list[np.ndarray] = []
    for _ in range(count):
        for _try in range(8):
            pick = rng.integers(0, len(unit))
            direction = shape[pick] / max(float(np.linalg.norm(shape[pick])), 1e-9)
            if all(float(np.dot(direction, other)) < math.cos(SCRAPE_APART) for other in centres):
                break
        centres.append(direction)
        span = rng.uniform(*SCRAPE_SPAN)
        plane = 1.0 - rng.uniform(*SCRAPE_DEPTH)
        norms = np.maximum(np.linalg.norm(shape, axis=1), 1e-9)
        under = (shape @ direction) / norms > math.cos(span)
        above = np.maximum(shape @ direction - plane, 0.0)
        shape -= np.outer(np.where(under, above, 0.0), direction)
    return shape


def stone(rng: np.random.Generator, radii: tuple[float, float, float], divisions: int = 2,
          repeat: float = 1.0) -> Geometry:
    """A rock about the origin, ``radii`` across its three axes before it is scraped and roughened.

    Seven to thirteen flat discs are pressed into a sphere, which is then lumped, undulated and
    grained over them. ``divisions`` is how finely the surface is divided: 1 (42 vertices) for
    a stone in the hand, 3 for a boulder. ``repeat`` is the metres one repeat of the texture
    covers.
    """
    unit, triangles = _icosphere(divisions)
    count = int(rng.integers(SCRAPES[0], SCRAPES[1] + 1))
    shape = scrape(rng, unit, count)
    bump = np.zeros(len(shape))
    for low, high, amount in ROUGHNESS:
        bump += amount * waves(rng, shape, low, high)
    shape *= (1.0 + bump)[:, None]
    points = shape * np.asarray(radii, dtype=float)
    normals = smooth_normals(points, triangles)
    return projected(points, normals, triangles, repeat)


def _grid_normals(points: np.ndarray) -> np.ndarray:
    """Normals of a ``(rings, sides, 3)`` grid wrapped around its second axis."""
    along = np.gradient(points, axis=0)
    around = (np.roll(points, -1, axis=1) - np.roll(points, 1, axis=1)) / 2.0
    normals = np.cross(around, along)
    return np.asarray(normals / np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-12))


def timber(rng: np.random.Generator, length: float, radius: float, repeat: float = 0.6,
           rings: int | None = None, sides: int = 20, crook: float = 0.04) -> tuple[Geometry, Geometry]:
    """A trunk lying along X, centred on the origin: ``(bark, ends)`` as two meshes.

    The axis wanders, the section is a little out of round and tapers, the bark is fissured
    along the grain and carries a few knots. ``crook`` is how far the axis may wander from
    straight, as a fraction of the length. ``ends`` is the two sawn faces, textured with
    one picture across each (a growth-ring texture, centred). ``repeat`` is the metres one
    repeat of the bark texture covers.
    """
    rings = rings or max(6, int(length / 0.12))
    along = np.linspace(0.0, 1.0, rings + 1)[:, None]
    angle = np.linspace(0.0, 2.0 * math.pi, sides + 1)[None, :-1]
    fissures = max(5, int(2.0 * math.pi * radius / 0.13))
    wander = rng.uniform(0.0, 2.0 * math.pi, 6)
    width = radius * (1.0 - rng.uniform(0.0, 0.12) * along)
    width = width * (1.0 + 0.05 * np.sin(2.0 * math.pi * along * rng.uniform(0.8, 2.2) + wander[0]))
    width = width * (1.0 + 0.06 * np.cos(2.0 * angle + wander[1]))
    ridge = 1.0 - np.abs(np.sin(fissures * angle / 2.0 + 1.5 * np.sin(2.0 * math.pi * along * 1.3
                                                                          + wander[2])))
    width = width * (1.0 + 0.05 * (ridge - 0.5))
    for _ in range(int(rng.integers(1, 4))):
        where_s, where_a = rng.uniform(0.1, 0.9), rng.uniform(0.0, 2.0 * math.pi)
        spread_a = np.angle(np.exp(1j * (angle - where_a)))
        reach = ((along - where_s) * length / 0.10) ** 2 + (spread_a * radius / 0.08) ** 2
        width = width * (1.0 + rng.uniform(0.08, 0.16) * np.exp(-reach))
    bend = rng.uniform(-crook, crook) * length * np.sin(math.pi * along + wander[3])
    sag = rng.uniform(-crook, crook) / 2.0 * length * np.sin(math.pi * along + wander[4])
    x = (along - 0.5) * length + np.zeros_like(angle)
    y = bend + width * np.cos(angle)
    z = sag + width * np.sin(angle)
    grid = np.stack([x, y, z], axis=-1)
    normals = _grid_normals(grid)

    around = np.roll(grid, -1, axis=1) - np.roll(grid, 1, axis=1)
    around /= np.maximum(np.linalg.norm(around, axis=-1, keepdims=True), 1e-12)
    seam = np.concatenate([grid, grid[:, :1]], axis=1)
    seam_normals = np.concatenate([normals, normals[:, :1]], axis=1)
    seam_tangents = np.concatenate([around, around[:, :1]], axis=1)
    # u runs around the trunk and v along it, so the bitangent that points up the picture
    # (toward row 0) points back along the trunk: handedness -1.
    tangents = np.concatenate([seam_tangents, -np.ones(seam.shape[:2] + (1,))], axis=-1)
    circumference = 2.0 * math.pi * radius
    u = np.linspace(0.0, 1.0, sides + 1)[None, :] * circumference / repeat + np.zeros((rings + 1, 1))
    v = along * length / repeat + np.zeros((1, sides + 1))
    columns = sides + 1
    a = np.arange(rings)[:, None] * columns + np.arange(sides)[None, :]
    quads = np.stack([a, a + 1, a + columns, a + 1, a + columns + 1, a + columns], axis=-1)
    bark = Geometry(seam.reshape(-1, 3).astype('f'), seam_normals.reshape(-1, 3).astype('f'),
                    np.stack([u, v], axis=-1).reshape(-1, 2).astype('f'),
                    tangents.reshape(-1, 4).astype('f'), quads.reshape(-1).astype(np.uint32))
    return bark, _ends(grid, rng)


def _ends(grid: np.ndarray, rng: np.random.Generator) -> Geometry:
    """The two sawn faces of a trunk whose outline is the first and last rows of ``grid``."""
    faces = []
    for row, sign in ((0, -1.0), (-1, 1.0)):
        rim = grid[row]
        centre = rim.mean(axis=0)
        reach = np.maximum(np.linalg.norm(rim[:, 1:] - centre[1:], axis=1).max(), 1e-6)
        dish = rng.uniform(0.004, 0.012)
        hub = centre + np.array([-sign * dish, 0.0, 0.0])
        points = np.concatenate([hub[None, :], rim])
        sides = len(rim)
        uv = 0.5 + (points[:, 1:] - centre[1:]) / (2.0 * reach)
        uv[:, 0] = uv[:, 0] if sign > 0 else 1.0 - uv[:, 0]
        steps = np.arange(sides)
        order = (np.zeros(sides, int), 1 + steps, 1 + (steps + 1) % sides)
        triangles = np.stack(order if sign > 0 else (order[0], order[2], order[1]), axis=1)
        facing = np.array([sign, 0.0, 0.0])
        faces.append(Geometry(
            points.astype('f'), np.tile(facing, (len(points), 1)).astype('f'), uv.astype('f'),
            np.tile(np.array([0.0, sign, 0.0, -1.0]), (len(points), 1)).astype('f'),
            triangles.reshape(-1).astype(np.uint32)))
    return sf.merge(faces)


def rubble(rng: np.random.Generator, line: np.ndarray, width: float, height: float,
           sunk: float = 0.3, repeat: float = 0.8, sections: int = 11) -> Geometry:
    """A low dry-stone wall along ``line`` (points at ground level, in order), lumpy on both
    faces and along its crest, its ends rounded off into the ground.

    The wall is ``width`` across and ``height`` high above the line, and reaches ``sunk``
    below it. ``repeat`` is the metres one repeat of the texture covers.
    """
    count = len(line)
    heading = np.gradient(line, axis=0)
    heading /= np.maximum(np.linalg.norm(heading, axis=1, keepdims=True), 1e-12)
    side = np.stack([heading[:, 2], np.zeros(count), -heading[:, 0]], axis=1)
    side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-12)
    up = np.array([0.0, 1.0, 0.0])

    fraction = np.linspace(0.0, 1.0, sections)
    angle = math.pi * (1.0 - fraction)
    across = 0.5 * width * np.cos(angle)
    rise = height * np.sin(angle) ** 0.45
    rise[0] = rise[-1] = -sunk
    run = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(across), np.diff(rise)))])

    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))])
    length = max(float(along[-1]), 1e-6)
    ends = np.minimum(along, length - along)
    close = np.clip(ends / max(0.3, 0.04 * length), 0.0, 1.0)
    close = 0.03 + 0.97 * close * close * (3.0 - 2.0 * close)

    grid = np.empty((count, sections, 3))
    for i in range(count):
        grid[i] = line[i] + side[i][None, :] * across[:, None] + up * rise[:, None]
    lumps = np.zeros((count, sections))
    for low, high, amount in ((1.5, 3.5, 0.45), (4.0, 9.0, 0.22), (10.0, 20.0, 0.07)):
        lumps += amount * waves(rng, (grid - line[0]).reshape(-1, 3), low, high).reshape(count, sections)
    swell = lumps[..., None] * width
    outward = (grid - (line + up * (0.3 * height))[:, None, :])
    outward /= np.maximum(np.linalg.norm(outward, axis=-1, keepdims=True), 1e-12)
    grid = grid + outward * swell * (rise > -sunk + 1e-9)[None, :, None]
    # Round the ends off: pull each cross-section in toward the wall's axis.
    axis = (line + up * (0.25 * height))[:, None, :]
    grid = axis + (grid - axis) * close[:, None, None]

    toward = np.gradient(grid, axis=1)
    forward = np.gradient(grid, axis=0)
    normals = np.cross(forward, toward)
    normals /= np.maximum(np.linalg.norm(normals, axis=-1, keepdims=True), 1e-12)
    tangent = forward / np.maximum(np.linalg.norm(forward, axis=-1, keepdims=True), 1e-12)
    bitangent = toward / np.maximum(np.linalg.norm(toward, axis=-1, keepdims=True), 1e-12)
    # v grows with the section index, so the bitangent that points up the picture is minus it.
    handed = np.sign(np.sum(np.cross(normals, tangent) * -bitangent, axis=-1))
    handed = np.where(handed == 0.0, 1.0, handed)
    u = np.repeat(along[:, None], sections, axis=1) / repeat
    v = np.repeat(run[None, :], count, axis=0) / repeat
    columns = sections
    a = np.arange(count - 1)[:, None] * columns + np.arange(sections - 1)[None, :]
    quads = np.stack([a, a + columns, a + 1, a + 1, a + columns, a + columns + 1], axis=-1)
    return Geometry(grid.reshape(-1, 3).astype('f'), normals.reshape(-1, 3).astype('f'),
                    np.stack([u, v], axis=-1).reshape(-1, 2).astype('f'),
                    np.concatenate([tangent, handed[..., None]], axis=-1).reshape(-1, 4).astype('f'),
                    quads.reshape(-1).astype(np.uint32))
