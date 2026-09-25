"""Procedural surfaces: tileable physically based maps, made with NumPy.

A handful of the materials a room is built from -- checkered marble, veined
marble, brick, plaster, sandstone, and brushed metals -- generated as plain
arrays that repeat seamlessly both ways. :func:`pbr_material` makes one a
:class:`~OpenGLContext.scenegraph.pbrmaterial.PBRMaterial`::

    from OpenGLContext.scenegraph import surfaces

    floor = surfaces.pbr_material(surfaces.checkered_marble(512, tiles=2))
    column = surfaces.pbr_material(surfaces.brushed_metal(256, surfaces.GOLD))

A texture repeats where its geometry's texture coordinates run past 1, so a
surface is sized by the coordinates it is given: coordinates in metres over a
texture's width in metres.

The maps are :class:`Maps`: linear base colour, roughness, metalness and a
height from which :func:`normal_map` derives a tangent-space normal map. The
module imports nothing but NumPy, so a Blender script can load it by path and
bake the same surfaces into a model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, NamedTuple, Sequence, Tuple

import numpy as np

__all__ = [
    'GOLD', 'COPPER', 'STEEL', 'BRONZE', 'SILVER', 'Maps', 'tileable_noise',
    'fbm', 'marble', 'checkered_marble', 'marble_tiles', 'tiles', 'brick', 'plaster',
    'sandstone',
    'brushed_metal', 'normal_map', 'to_srgb', 'images', 'pbr_material',
    'Geometry', 'panel', 'polygon', 'block', 'prism', 'cylinder', 'sphere', 'moved',
    'placed', 'merge', 'shape',
]

#: Metals' reflectance at normal incidence, linear, which is a metal's base
#: colour in a metallic/roughness material.
GOLD = (1.0, 0.766, 0.336)
COPPER = (0.955, 0.638, 0.538)
STEEL = (0.56, 0.57, 0.58)
BRONZE = (0.80, 0.55, 0.30)
SILVER = (0.97, 0.96, 0.91)

Colour = Sequence[float]


@dataclass(frozen=True)
class Maps:
    """One surface's maps, each ``size`` by ``size``, values from 0 to 1.

    ``base`` is linear colour (H, W, 3); ``roughness``, ``metallic`` and
    ``height`` are (H, W). Row 0 is the top of the texture.
    """

    base: np.ndarray
    roughness: np.ndarray
    metallic: np.ndarray
    height: np.ndarray


def _smooth(t: np.ndarray) -> np.ndarray:
    return np.asarray(t * t * (3.0 - 2.0 * t))


def tileable_noise(size: int, cells: int, seed: int = 0) -> np.ndarray:
    """Smooth value noise over a ``cells`` by ``cells`` lattice that wraps.

    ``size`` by ``size``, from 0 to 1, repeating seamlessly both ways.
    """
    lattice = np.random.default_rng(seed).random((cells, cells))
    at = np.arange(size) * (cells / float(size))
    low = np.floor(at).astype(int)
    fraction = _smooth(at - low)
    low %= cells
    high = (low + 1) % cells
    rows0, rows1 = lattice[low], lattice[high]
    top = rows0[:, low] * (1 - fraction) + rows0[:, high] * fraction
    bottom = rows1[:, low] * (1 - fraction) + rows1[:, high] * fraction
    blended: np.ndarray = top * (1 - fraction[:, None]) + bottom * fraction[:, None]
    return blended


def fbm(size: int, cells: int, seed: int = 0, octaves: int = 4) -> np.ndarray:
    """Octaves of :func:`tileable_noise`, each twice as fine and half as strong."""
    total = np.zeros((size, size))
    weight = 0.0
    for octave in range(octaves):
        amplitude = 0.5 ** octave
        total += amplitude * tileable_noise(size, cells * 2 ** octave, seed + octave)
        weight += amplitude
    return total / weight


def _mix(a: Colour, b: Colour, t: np.ndarray) -> np.ndarray:
    first, second = np.asarray(a, 'd'), np.asarray(b, 'd')
    return np.asarray(first + (second - first) * t[..., None])


def _clip(value: np.ndarray) -> np.ndarray:
    return np.asarray(np.clip(value, 0.0, 1.0))


def _grid(size: int) -> Tuple[np.ndarray, np.ndarray]:
    """Texel centres across and down, from 0 to 1."""
    along = (np.arange(size) + 0.5) / float(size)
    return np.meshgrid(along, along)


def marble(size: int = 256, base: Colour = (0.86, 0.85, 0.82),
           vein: Colour = (0.32, 0.33, 0.36), veins: int = 3, polish: float = 0.06,
           seed: int = 1) -> Maps:
    """Veined marble, polished to ``polish`` roughness.

    The veins run diagonally, ``veins`` of them across the texture, bent by
    turbulence; they are slightly rougher than the stone between them.
    """
    x, y = _grid(size)
    turbulence = fbm(size, 4, seed)
    phase = (x + y) * veins + 2.4 * turbulence
    streak = (1.0 - np.abs(np.sin(math.pi * phase))) ** 10
    colour = _mix(base, vein, _clip(streak * 0.9)) * (0.93 + 0.07 * turbulence[..., None])
    return Maps(_clip(colour), _clip(polish + 0.05 * streak + 0.02 * turbulence),
                np.zeros((size, size)), np.full((size, size), 0.6))


def _laid(size: int, count: int, faces: Sequence[Maps], choose: np.ndarray,
          grout: Colour, joint_width: float = 0.012, joint_rough: float = 0.75) -> Maps:
    """Square tiles ``count`` each way, each face from ``faces`` as ``choose`` says,
    in grout that is matte and set below the tiles."""
    x, y = _grid(size)
    column, row = np.floor(x * count), np.floor(y * count)
    picked = choose[row.astype(int) % choose.shape[0], column.astype(int) % choose.shape[1]]
    colour = np.zeros((size, size, 3))
    rough = np.zeros((size, size))
    for index, face in enumerate(faces):
        chosen = picked == index
        colour[chosen] = face.base[chosen]
        rough[chosen] = face.roughness[chosen]
    within = np.minimum(np.minimum(x * count - column, 1 - (x * count - column)),
                        np.minimum(y * count - row, 1 - (y * count - row)))
    joint = _clip(1.0 - within / joint_width)
    colour = colour * (1 - joint[..., None]) + np.asarray(grout) * joint[..., None]
    rough = rough * (1 - joint) + joint_rough * joint
    height = 0.6 * _clip(within / (joint_width * 1.7))
    return Maps(_clip(colour), _clip(rough), np.zeros((size, size)), height)


def checkered_marble(size: int = 512, tiles: int = 2,
                     dark: Colour = (0.025, 0.028, 0.032),
                     light: Colour = (0.80, 0.79, 0.75),
                     grout: Colour = (0.22, 0.21, 0.19),
                     polish: float = 0.05, seed: int = 2) -> Maps:
    """A floor of alternating dark and light marble tiles, ``tiles`` each way.

    ``tiles`` is even, so the checker repeats. The grout between tiles is
    matte and set below the polished stone.
    """
    white = marble(size, light, (0.45, 0.45, 0.47), veins=2 * tiles, polish=polish,
                   seed=seed)
    black = marble(size, dark, (0.55, 0.52, 0.45), veins=3 * tiles, polish=polish,
                   seed=seed + 7)
    checker = (np.add.outer(np.arange(tiles), np.arange(tiles)) % 2).astype(int)
    return _laid(size, tiles, [white, black], checker, grout)


def marble_tiles(size: int = 512, tiles: int = 2,
                 colour: Colour = (0.025, 0.028, 0.032),
                 vein: Colour = (0.62, 0.60, 0.56),
                 grout: Colour = (0.12, 0.12, 0.12),
                 polish: float = 0.05, seed: int = 11) -> Maps:
    """Tiles of one marble, ``tiles`` each way: by default black, veined white.

    Each tile is cut from its own part of the stone, so the veins do not run
    on from one tile to the next. The grout is matte and set below them.
    """
    faces = [marble(size, colour, vein, veins=2 + tiles, polish=polish, seed=seed + index)
             for index in range(2)]
    pattern = (np.add.outer(np.arange(tiles), 2 * np.arange(tiles)) % 2).astype(int)
    return _laid(size, tiles, faces, pattern, grout)


def tiles(size: int = 256, count: int = 8, colour: Colour = (0.12, 0.42, 0.48),
          grout: Colour = (0.78, 0.78, 0.74), glaze: float = 0.12, spread: float = 0.08,
          seed: int = 12) -> Maps:
    """Glazed square tiles, ``count`` each way, in pale grout: a pool, a bathroom.

    Each tile is its own shade within ``spread`` of ``colour``, as a batch of
    glazed tiles is; the glaze has ``glaze`` roughness and the grout is matte.
    """
    rng = np.random.default_rng(seed)
    shades = rng.uniform(1.0 - spread, 1.0 + spread, (count, count))
    grain = fbm(size, 8, seed + 1, octaves=2)
    faces = []
    for shade in np.unique(shades):
        faces.append(Maps(np.broadcast_to(np.asarray(colour) * shade, (size, size, 3))
                          * (0.97 + 0.03 * grain)[..., None],
                          np.full((size, size), glaze) + 0.03 * grain,
                          np.zeros((size, size)), np.zeros((size, size))))
    which = np.searchsorted(np.unique(shades), shades)
    return _laid(size, count, faces, which, grout, joint_width=0.02 * count / 2.0,
                 joint_rough=0.85)


def brick(size: int = 256, courses: int = 8, bricks: int = 4,
          colour: Colour = (0.30, 0.10, 0.055), mortar: Colour = (0.50, 0.47, 0.42),
          seed: int = 3) -> Maps:
    """Running-bond brick: ``courses`` rows of ``bricks``, each row offset half a brick.

    ``courses`` is even, so the bond repeats. Each brick has a colour of its
    own within a range of the given one.
    """
    x, y = _grid(size)
    row = y * courses
    course = np.floor(row)
    across = x * bricks + 0.5 * (course % 2)
    which = np.floor(across) % bricks
    fx, fy = across - np.floor(across), row - course
    joint = (np.minimum(fx, 1 - fx) < 0.045) | (np.minimum(fy, 1 - fy) < 0.08)
    shades = np.random.default_rng(seed).uniform(0.78, 1.18, (courses, bricks))
    shade = shades[course.astype(int), which.astype(int)]
    grain = fbm(size, 16, seed + 1, octaves=3)
    face = np.asarray(colour) * (shade * (0.85 + 0.3 * grain))[..., None]
    base = np.where(joint[..., None], np.asarray(mortar) * (0.9 + 0.2 * grain)[..., None], face)
    rough = np.where(joint, 0.95, 0.75 + 0.15 * grain)
    height = np.where(joint, 0.1, 0.75 + 0.2 * grain)
    return Maps(_clip(base), _clip(rough), np.zeros((size, size)), _clip(height))


def plaster(size: int = 256, colour: Colour = (0.74, 0.70, 0.62), seed: int = 4) -> Maps:
    """Hand-finished plaster: a faint mottle and a gentle bumpiness."""
    mottle = fbm(size, 6, seed)
    bumps = fbm(size, 24, seed + 3, octaves=3)
    base = np.asarray(colour) * (0.9 + 0.12 * mottle)[..., None]
    return Maps(_clip(base), _clip(0.82 + 0.1 * bumps), np.zeros((size, size)),
                _clip(0.35 + 0.3 * bumps))


def sandstone(size: int = 256, colour: Colour = (0.72, 0.58, 0.40), seed: int = 5) -> Maps:
    """Dressed sandstone: fine grain and faint bedding lines across it."""
    _x, y = _grid(size)
    grain = fbm(size, 32, seed, octaves=3)
    bedding = 0.5 + 0.5 * np.sin(2 * math.pi * (y * 6 + 0.6 * fbm(size, 4, seed + 1)))
    base = np.asarray(colour) * (0.82 + 0.12 * bedding + 0.1 * grain)[..., None]
    return Maps(_clip(base), _clip(0.8 + 0.15 * grain), np.zeros((size, size)),
                _clip(0.4 + 0.3 * grain + 0.1 * bedding))


def brushed_metal(size: int = 256, colour: Colour = STEEL, roughness: float = 0.28,
                  seed: int = 6) -> Maps:
    """A metal brushed along one direction: streaks of roughness down its length."""
    rng = np.random.default_rng(seed)
    rows = rng.random(size)
    streak = 0.5 * rows + 0.25 * np.roll(rows, 1) + 0.25 * np.roll(rows, -1)
    wander = tileable_noise(size, 4, seed + 1)
    rough = roughness * (0.7 + 0.6 * streak[:, None] + 0.1 * wander)
    base = np.asarray(colour) * (0.96 + 0.04 * streak[:, None, None])
    return Maps(_clip(np.broadcast_to(base, (size, size, 3)).copy()), _clip(rough),
                np.ones((size, size)), np.full((size, size), 0.5))


def normal_map(height: np.ndarray, strength: float = 2.0) -> np.ndarray:
    """A tangent-space normal map from a height map, encoded 0 to 1.

    Slopes are taken with the edges wrapped, so a tileable height gives a
    tileable normal map. ``strength`` scales the relief.
    """
    rise = np.asarray(height, 'd')
    dx = 0.5 * (np.roll(rise, -1, axis=1) - np.roll(rise, 1, axis=1)) * strength
    dy = 0.5 * (np.roll(rise, 1, axis=0) - np.roll(rise, -1, axis=0)) * strength
    normal = np.stack([-dx, -dy, np.ones_like(rise)], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    encoded: np.ndarray = normal * 0.5 + 0.5
    return encoded


def to_srgb(linear: np.ndarray) -> np.ndarray:
    """Linear colour encoded as sRGB, as a colour texture holds it."""
    value = np.clip(np.asarray(linear, 'd'), 0.0, 1.0)
    encoded: np.ndarray = np.where(value <= 0.0031308, value * 12.92,
                                   1.055 * np.power(value, 1 / 2.4) - 0.055)
    return encoded


def images(maps: Maps, relief: float = 2.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(base colour, metallic-roughness, normal)`` as 8-bit RGB arrays.

    Laid out as glTF has them: base colour sRGB-encoded, roughness in the
    green channel and metalness in the blue, and the normal map linear.
    """
    def eight(value: np.ndarray) -> np.ndarray:
        return np.asarray((np.clip(value, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))

    ones = np.ones_like(maps.roughness)
    packed = np.stack([ones, maps.roughness, maps.metallic], axis=-1)
    return (eight(to_srgb(maps.base)), eight(packed),
            eight(normal_map(maps.height, relief)))


def pbr_material(maps: Maps, relief: float = 2.0, **factors: Any) -> Any:
    """A :class:`~OpenGLContext.scenegraph.pbrmaterial.PBRMaterial` wearing ``maps``.

    ``factors`` are the material's own fields; a factor multiplies its map,
    so the maps say what the surface is and a factor below 1 scales it down.
    """
    from PIL import Image

    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture

    base, packed, normal = images(maps, relief)
    textures = {
        'baseColor': PBRTexture(Image.fromarray(base, 'RGB'), srgb=True),
        'metallicRoughness': PBRTexture(Image.fromarray(packed, 'RGB')),
        'normal': PBRTexture(Image.fromarray(normal, 'RGB')),
    }
    settings = dict(baseColor=(1.0, 1.0, 1.0), metallic=1.0, roughness=1.0)
    settings.update(factors)
    return PBRMaterial(textures=textures, **settings)


# --- geometry that wears a surface at its size -----------------------------------

class Geometry(NamedTuple):
    """A mesh to wear a surface: the arrays a ``PBRMesh`` takes.

    ``texcoords`` are in repeats of the surface, so a surface keeps the size
    it was made for however large the mesh is. u runs across a face and v
    runs down it, as glTF's texture coordinates run: row 0 of a map, its
    top, is at the top of a wall. ``tangents`` run the way u runs, with a
    handedness of 1, so the bitangent points up the face, toward row 0,
    which is the way a normal map's green channel is read. Triangles wind
    counter-clockwise seen from the side the normals face.
    """

    positions: np.ndarray
    normals: np.ndarray
    texcoords: np.ndarray
    tangents: np.ndarray
    indices: np.ndarray


def _down(texcoords: np.ndarray) -> np.ndarray:
    """``texcoords`` whose v was measured up a face, measured down it."""
    turned = np.array(texcoords, 'f')
    turned[:, 1] = -turned[:, 1]
    return turned


def _facing_z(positions: np.ndarray, indices: Sequence[int], repeat: float,
              origin: Tuple[float, float],
              start: Tuple[float, float] = (0.0, 0.0)) -> Geometry:
    """Points in the xy plane, facing +z, textured by the metre from ``origin``,
    which falls ``start`` metres into the surface."""
    count = len(positions)
    at = np.asarray(positions, 'f')
    texcoords = _down((at[:, :2] - np.asarray(origin, 'f') + np.asarray(start, 'f'))
                      / float(repeat))
    return Geometry(at, np.tile(np.array([0.0, 0.0, 1.0], 'f'), (count, 1)), texcoords,
                    np.tile(np.array([1.0, 0.0, 0.0, 1.0], 'f'), (count, 1)),
                    np.asarray(indices, np.uint32))


def panel(width: float, height: float, repeat: float = 1.0,
          start: Tuple[float, float] = (0.0, 0.0)) -> Geometry:
    """A ``width`` by ``height`` rectangle centred in its own xy plane, facing +z.

    The surface repeats every ``repeat`` metres. Its bottom-left corner sits
    ``start`` metres (across, up) into the surface, so pieces cut from one
    wall -- round a window, say -- carry its pattern on in line.
    """
    half_w, half_h = width / 2.0, height / 2.0
    corners = [(-half_w, -half_h, 0.0), (half_w, -half_h, 0.0),
               (half_w, half_h, 0.0), (-half_w, half_h, 0.0)]
    return _facing_z(np.array(corners), [0, 1, 2, 0, 2, 3], repeat, (-half_w, -half_h),
                     (float(start[0]), float(start[1])))


def polygon(radius: float, sides: int = 8, repeat: float = 1.0) -> Geometry:
    """A regular polygon of ``sides`` round its own origin in the xy plane, facing +z.

    Its corners are ``radius`` from the centre, the first a half-step round
    from +x so that an octagon stands on a flat side. The surface repeats
    every ``repeat`` metres.
    """
    angles = [math.pi / sides + index * 2.0 * math.pi / sides for index in range(sides)]
    rim = [(radius * math.cos(angle), radius * math.sin(angle), 0.0) for angle in angles]
    fan = [index for side in range(sides) for index in (0, 1 + side, 1 + (side + 1) % sides)]
    return _facing_z(np.array([(0.0, 0.0, 0.0)] + rim), fan, repeat, (-radius, -radius))


def _turned(geometry: Geometry, rotation: np.ndarray, offset: np.ndarray) -> Geometry:
    turn = rotation.astype('f')
    tangents = geometry.tangents.copy()
    tangents[:, :3] = tangents[:, :3] @ turn.T
    return Geometry((geometry.positions @ turn.T + offset).astype('f'),
                    (geometry.normals @ turn.T).astype('f'), geometry.texcoords,
                    tangents, geometry.indices)


def _about(axis: int, angle: float) -> np.ndarray:
    """The rotation by ``angle`` radians about axis 0, 1 or 2."""
    cos, sin = math.cos(angle), math.sin(angle)
    first, second = [index for index in range(3) if index != axis]
    turn = np.identity(3)
    turn[first, first] = turn[second, second] = cos
    turn[second, first], turn[first, second] = sin, -sin
    if axis == 1:
        turn = turn.T
    return turn


def block(size: Sequence[float], repeat: float = 1.0, chamfer: float = 0.0) -> Geometry:
    """A box of ``size`` (x, y, z) centred on its own origin, each face outward.

    Every face is textured by the metre from its own corner, so a slab or a
    column wears its surface at the surface's size on every side, where a
    ``Box`` stretches one texture across each face. ``chamfer`` cuts the four
    upright edges back by that many metres each way, as a machined column's
    are; the box is then a :func:`prism` of the cut outline.
    """
    x, y, z = (float(value) for value in size)
    if chamfer > 0.0:
        cut, half_x, half_z = float(chamfer), x / 2.0, z / 2.0
        outline = [(-half_x + cut, -half_z), (half_x - cut, -half_z),
                   (half_x, -half_z + cut), (half_x, half_z - cut),
                   (half_x - cut, half_z), (-half_x + cut, half_z),
                   (-half_x, half_z - cut), (-half_x, -half_z + cut)]
        return prism(outline, y, repeat)
    half_pi = math.pi / 2.0
    faces = (
        (panel(x, y, repeat), np.identity(3), (0.0, 0.0, z / 2)),
        (panel(x, y, repeat), _about(1, math.pi), (0.0, 0.0, -z / 2)),
        (panel(z, y, repeat), _about(1, half_pi), (x / 2, 0.0, 0.0)),
        (panel(z, y, repeat), _about(1, -half_pi), (-x / 2, 0.0, 0.0)),
        (panel(x, z, repeat), _about(0, -half_pi), (0.0, y / 2, 0.0)),
        (panel(x, z, repeat), _about(0, half_pi), (0.0, -y / 2, 0.0)),
    )
    parts = [_turned(face, turn, np.asarray(offset, 'f')) for face, turn, offset in faces]
    return Geometry(
        np.concatenate([part.positions for part in parts]),
        np.concatenate([part.normals for part in parts]),
        np.concatenate([part.texcoords for part in parts]),
        np.concatenate([part.tangents for part in parts]),
        np.concatenate([part.indices + 4 * index for index, part in enumerate(parts)]
                       ).astype(np.uint32))


def prism(outline: Sequence[Tuple[float, float]], height: float,
          repeat: float = 1.0) -> Geometry:
    """A convex ``outline`` of (x, z) points stood ``height`` high, centred, and capped.

    The outline may run either way round. Each side is flat, and the surface
    runs on round the sides without a break, so a pattern wraps the corners;
    the caps are textured by the metre in x and z. It repeats every
    ``repeat`` metres.
    """
    points = np.asarray(outline, 'd')
    area = 0.5 * float(np.sum(points[:, 0] * np.roll(points[:, 1], -1)
                              - np.roll(points[:, 0], -1) * points[:, 1]))
    if area < 0.0:
        points = points[::-1]
    count, half = len(points), height / 2.0
    following = np.roll(points, -1, axis=0)
    lengths = np.linalg.norm(following - points, axis=1)
    walked = np.concatenate([[0.0], np.cumsum(lengths)])
    perimeter = walked[-1]
    positions: List[Tuple[float, float, float]] = []
    normals: List[Tuple[float, float, float]] = []
    texcoords: List[Tuple[float, float]] = []
    tangents: List[Tuple[float, float, float, float]] = []
    indices: List[int] = []
    for side in range(count):
        (x0, z0), (x1, z1) = points[side], following[side]
        dx, dz = (x1 - x0) / lengths[side], (z1 - z0) / lengths[side]
        # u runs against the walk, so that it, v up and the outward normal
        # make a right-handed frame.
        u0, u1 = perimeter - walked[side], perimeter - walked[side + 1]
        base = len(positions)
        positions += [(x1, -half, z1), (x0, -half, z0), (x0, half, z0), (x1, half, z1)]
        normals += [(dz, 0.0, -dx)] * 4
        texcoords += [(u1, 0.0), (u0, 0.0), (u0, height), (u1, height)]
        tangents += [(-dx, 0.0, -dz, 1.0)] * 4
        indices += [base + index for index in (0, 1, 2, 0, 2, 3)]
    centre = points.mean(axis=0)
    for y, facing, flip in ((half, 1.0, -1.0), (-half, -1.0, 1.0)):
        base = len(positions)
        ring = [(centre[0], y, centre[1])] + [(px, y, pz) for px, pz in points]
        positions += ring
        normals += [(0.0, facing, 0.0)] * len(ring)
        texcoords += [(px, flip * pz) for px, _y, pz in ring]
        tangents += [(1.0, 0.0, 0.0, 1.0)] * len(ring)
        for side in range(count):
            first, second = base + 1 + side, base + 1 + (side + 1) % count
            indices += [base, second, first] if facing > 0 else [base, first, second]
    return Geometry(np.asarray(positions, 'f'), np.asarray(normals, 'f'),
                    _down(np.asarray(texcoords, 'd') / float(repeat)),
                    np.asarray(tangents, 'f'), np.asarray(indices, np.uint32))


def moved(geometry: Geometry, offset: Sequence[float]) -> Geometry:
    """``geometry`` shifted by ``offset`` metres, its texture where it was."""
    return geometry._replace(
        positions=(geometry.positions + np.asarray(offset, 'f')).astype('f'))


def placed(geometry: Geometry, translation: Sequence[float] = (0.0, 0.0, 0.0),
           rotation: Sequence[float] = (0.0, 1.0, 0.0, 0.0)) -> Geometry:
    """``geometry`` turned and moved into its parent's space, as a ``Transform``
    with that ``translation`` and ``rotation`` (axis and angle) would place it.

    Its normals and tangents turn with it and its texture stays where it was,
    so pieces placed about a room can be merged into one mesh.
    """
    x, y, z, angle = (float(value) for value in rotation)
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    axis = np.array([x, y, z]) / length
    cos, sin = math.cos(angle), math.sin(angle)
    cross = np.array([[0.0, -axis[2], axis[1]], [axis[2], 0.0, -axis[0]],
                      [-axis[1], axis[0], 0.0]])
    turn = cos * np.identity(3) + (1.0 - cos) * np.outer(axis, axis) + sin * cross
    return _turned(geometry, turn, np.asarray(translation, 'f'))


def merge(parts: Sequence[Geometry]) -> Geometry:
    """One mesh of every part, for one shape: a floor's border, a frame's four sides."""
    offsets = np.cumsum([0] + [len(part.positions) for part in parts[:-1]])
    return Geometry(
        np.concatenate([part.positions for part in parts]),
        np.concatenate([part.normals for part in parts]),
        np.concatenate([part.texcoords for part in parts]),
        np.concatenate([part.tangents for part in parts]),
        np.concatenate([part.indices + offset for part, offset in zip(parts, offsets)]
                       ).astype(np.uint32))


def cylinder(radius: float, height: float, sides: int = 16, arc: float = 2.0 * math.pi,
             repeat: float = 1.0) -> Geometry:
    """The curved face of an upright cylinder, centred on its own origin, facing out.

    ``arc`` is how much of the way round it goes, in radians: ``math.pi`` is a
    half column, which runs from -x to +x through +z and so stands with its
    flat back on the plane z = 0. ``sides`` flat faces make up the whole
    circle, and a part of it has its share. The surface repeats every
    ``repeat`` metres round the curve and up it. The ends are open.
    """
    steps = max(1, int(math.ceil(sides * arc / (2.0 * math.pi))))
    columns = steps + 1
    # u runs from -x round through +z, which is angle arc down to 0; that way
    # round a tangent and the up direction make a right-handed frame.
    angles = arc * (1.0 - np.arange(columns) / float(steps))
    around = np.stack([np.cos(angles), np.zeros(columns), np.sin(angles)], axis=-1)
    half = height / 2.0
    positions = np.concatenate([around * radius + (0.0, -half, 0.0),
                                around * radius + (0.0, half, 0.0)])
    normals = np.concatenate([around, around])
    tangent = np.stack([np.sin(angles), np.zeros(columns), -np.cos(angles),
                        np.ones(columns)], axis=-1)
    distance = np.arange(columns) * (arc * radius / steps)
    texcoords = np.concatenate([np.stack([distance, np.zeros(columns)], axis=-1),
                                np.stack([distance, np.full(columns, height)], axis=-1)])
    indices = [index for step in range(steps)
               for index in (step, step + 1, columns + step + 1,
                             step, columns + step + 1, columns + step)]
    return Geometry(positions.astype('f'), normals.astype('f'),
                    _down(texcoords / float(repeat)),
                    np.concatenate([tangent, tangent]).astype('f'),
                    np.asarray(indices, np.uint32))


def sphere(radius: float, sides: int = 24, repeat: float = 1.0) -> Geometry:
    """A sphere centred on its own origin, facing out.

    ``sides`` flat faces go round its equator and half as many from pole to
    pole, so fewer sides is a coarser sphere of the same size -- what the
    levels of detail of one object are made of. The surface repeats every
    ``repeat`` metres round the equator and from pole to pole; it is gathered
    at the poles, as any wrapping of a sphere is.
    """
    around = max(3, int(sides))
    rings = max(2, around // 2)
    columns = around + 1
    # Longitude runs as a cylinder's does (see cylinder), and latitude from
    # the south pole up; v is then turned to run down, as on every face here.
    longitude = 2.0 * math.pi * (1.0 - np.arange(columns) / float(around))
    latitude = math.pi * (np.arange(rings + 1) / float(rings) - 0.5)
    lat, lon = np.meshgrid(latitude, longitude, indexing='ij')
    normals = np.stack([np.cos(lat) * np.cos(lon), np.sin(lat),
                        np.cos(lat) * np.sin(lon)], axis=-1).reshape(-1, 3)
    tangents = np.stack([np.sin(lon), np.zeros_like(lon), -np.cos(lon),
                         np.ones_like(lon)], axis=-1).reshape(-1, 4)
    texcoords = np.stack([(2.0 * math.pi - lon) * radius,
                          (lat + math.pi / 2.0) * radius], axis=-1).reshape(-1, 2)
    indices: List[int] = []
    for ring in range(rings):
        low, high = ring * columns, (ring + 1) * columns
        for step in range(around):
            # A quad at a pole has two corners on the pole itself; only the
            # half of it that has any area is kept.
            if ring > 0:
                indices.extend((low + step, low + step + 1, high + step + 1))
            if ring < rings - 1:
                indices.extend((low + step, high + step + 1, high + step))
    return Geometry((normals * radius).astype('f'), normals.astype('f'),
                    _down(texcoords / float(repeat)), tangents.astype('f'),
                    np.asarray(indices, np.uint32))


def shape(geometry: Geometry, material: Any,
          translation: Sequence[float] = (0.0, 0.0, 0.0),
          rotation: Sequence[float] = (0.0, 1.0, 0.0, 0.0)) -> Any:
    """A ``Transform`` holding ``geometry`` wearing ``material``, placed in the scene.

    ``rotation`` is VRML97's axis and angle in radians.
    """
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh

    mesh = PBRMesh(positions=geometry.positions, normals=geometry.normals,
                   texcoords=geometry.texcoords, tangents=geometry.tangents,
                   indices=geometry.indices, material=material)
    return basenodes.Transform(
        translation=tuple(translation), rotation=tuple(rotation),
        children=[basenodes.Shape(geometry=mesh,
                                  appearance=basenodes.Appearance(material=material))])
