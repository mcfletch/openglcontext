"""Warning signs: a post, a plate, and the symbol painted on the plate.

A road that is generated already knows what it is about to do. The alignment
carries its own curvature and its own grade, and the structures along it are
written down, so *what* a sign says and *where* it belongs are derivable rather
than authored -- which is most of the point of generating a road instead of
drawing one. Deciding that is authoring and lives in
``OpenGLContext_editor.world.signs``; what is here is the object itself.

:func:`sign_mesh` builds one at the origin, facing -Z, because a world has tens
of signs and they are placed rather than modelled one at a time.
:func:`sign_texture` paints the face, so a world needs no sign artwork to ship
with it.

**Every kind reads out of one image.** Seven kinds of plate as seven textures is
seven materials and seven draws for what is one object with a different picture
on it, so :func:`sign_atlas` puts them -- and the post's own colour -- in a
single image and says where each one lives. A sign is then one mesh with one
material whatever it says, and a world's signs are one draw a tile.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.loaders.gltf.meshes import estimate_normals
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = ['WARNINGS', 'SignProfile', 'sign_mesh', 'sign_meshes',
           'sign_texture', 'sign_atlas', 'sign_material', 'atlas_material',
           'post_material']

#: What a sign can warn of. Each is a symbol on the same triangular plate, which
#: is what a warning sign is nearly everywhere: the shape says "take care" and
#: the symbol says what of.
WARNINGS = ('bend-left', 'bend-right', 'double-bend', 'dip', 'crest',
            'tunnel', 'junction')

#: The plate's colours: a white face inside a red border, with the symbol in
#: black. Held here rather than in the drawing code because a caller repainting
#: a world's signs to its own standard changes these and nothing else.
PLATE_FACE = (250, 248, 240, 255)
PLATE_BORDER = (176, 32, 34, 255)
PLATE_SYMBOL = (28, 28, 30, 255)
PLATE_CLEAR = (0, 0, 0, 0)

#: How much of the plate's half-height the red border takes.
BORDER_FRACTION = 0.13

#: A galvanised post: half a metal, not quite smooth, and darker than it looks
#: like it should be -- under a strong sun a mid grey comes out white, and a
#: white pole beside a forest road is the most conspicuous object in the scene.
POST_ALBEDO = (0.19, 0.196, 0.207)
POST_METALLIC = 0.15
POST_ROUGHNESS = 0.5


@dataclass
class SignProfile:
    """The shape of a sign, in metres.

    ``post_height`` is how far the bottom edge of the plate sits above the
    ground -- high enough that a car does not clip it and low enough to read
    from a driving position. ``plate_size`` is the triangle's width across the
    bottom, ``plate_depth`` how thick it is, and ``post_radius`` the post's.

    ``offset`` is how far the post stands outside the road's own edge. It is
    part of the sign rather than of the placement because it is the same
    question -- how far a thing beside a road stands from it -- for every sign
    in a world.
    """

    post_height: float = 1.85
    post_radius: float = 0.045
    post_sides: int = 8
    plate_size: float = 0.9
    plate_depth: float = 0.035
    offset: float = 1.4


def post_material() -> PBRMaterial:
    """What a sign's post is made of."""
    return PBRMaterial(baseColor=POST_ALBEDO, metallic=POST_METALLIC,
                       roughness=POST_ROUGHNESS, doubleSided=False)


def sign_texture(kind: str, size: int = 256) -> Any:
    """The face of one kind of plate, as an RGBA image.

    Transparent outside the triangle, so the plate reads as a triangle however
    it is drawn and a caller can put the image on a quad if it would rather.
    """
    from PIL import Image, ImageChops, ImageDraw
    if kind not in WARNINGS:
        raise ValueError("no warning sign says %r; the kinds are %s"
                         % (kind, ', '.join(WARNINGS)))
    image = Image.new('RGBA', (size, size), PLATE_CLEAR)
    draw = ImageDraw.Draw(image)
    draw.polygon(_triangle(size, 0.0), fill=PLATE_BORDER)
    inner = _triangle(size, BORDER_FRACTION)
    draw.polygon(inner, fill=PLATE_FACE)
    # The symbol is painted on its own layer and let through only where the
    # white face is. A triangle narrows towards its point, so a symbol sized to
    # look right across the bottom runs off the sides at the top.
    ink = Image.new('RGBA', (size, size), PLATE_CLEAR)
    _symbol(ImageDraw.Draw(ink), kind, size)
    face = Image.new('L', (size, size), 0)
    ImageDraw.Draw(face).polygon(inner, fill=255)
    image.paste(ink, (0, 0), ImageChops.multiply(ink.split()[3], face))
    return image


def sign_material(kind: str, size: int = 256, image: Any = None) -> PBRMaterial:
    """The material for a plate of this kind.

    ``image`` overrides the painted face -- an
    :class:`~OpenGLContext.loaders.gltf.writer.ExternalImage` for a baked world,
    which writes the picture once beside the tileset rather than into every tile
    that carries a sign.
    """
    face = image if image is not None else PBRTexture(sign_texture(kind, size),
                                                      srgb=True)
    # Opaque, and one-sided. The plate is a triangular prism with a back of its
    # own, so the picture's transparent corners fall outside the geometry and
    # never reach a fragment. Declared as a cutout instead, every sign in a
    # world joins the sorted alpha pass, which is what a sheet of painted metal
    # is not.
    return PBRMaterial(baseColor=(1.0, 1.0, 1.0), metallic=0.0, roughness=0.55,
                       textures={'baseColor': face}, doubleSided=False)


def sign_atlas(kinds: "Sequence[str]" = WARNINGS, cell: int = 256
               ) -> "Tuple[Any, Dict[str, Tuple[float, float, float, float]]]":
    """Every plate, and the post's colour, in one image.

    Returns the image and ``{name: (u0, v0, u1, v1)}`` -- a box per kind, and
    one called ``post`` holding a flat patch of the post's own colour so the
    whole sign reads out of one texture and is one material.

    Laid out on the smallest square grid that holds them, in the order given, so
    the same kinds always make the same atlas and a world re-bakes to itself.
    """
    from PIL import Image
    wanted = list(kinds)
    for kind in wanted:
        if kind not in WARNINGS:
            raise ValueError("no warning sign says %r; the kinds are %s"
                             % (kind, ", ".join(WARNINGS)))
    names = wanted + ["post"]
    columns = int(math.ceil(math.sqrt(len(names))))
    rows = int(math.ceil(len(names) / columns))
    image = Image.new("RGBA", (columns * cell, rows * cell), PLATE_CLEAR)
    boxes = {}
    for index, name in enumerate(names):
        column, row = index % columns, index // columns
        patch = (Image.new("RGBA", (cell, cell), _srgb(POST_ALBEDO))
                 if name == "post" else sign_texture(name, cell))
        image.paste(patch, (column * cell, row * cell))
        boxes[name] = (column * cell / image.width, row * cell / image.height,
                       (column + 1) * cell / image.width,
                       (row + 1) * cell / image.height)
    return image, boxes


def atlas_material(image: Any = None, kinds: "Sequence[str]" = WARNINGS,
                   cell: int = 256) -> PBRMaterial:
    """The one material a sign built against :func:`sign_atlas` wears.

    ``image`` overrides the painted atlas -- an
    :class:`~OpenGLContext.loaders.gltf.writer.ExternalImage` for a baked world,
    which writes the picture once beside the tileset rather than into every tile
    that carries a sign.
    """
    face = image if image is not None else PBRTexture(
        sign_atlas(kinds, cell)[0], srgb=True)
    return PBRMaterial(baseColor=(1.0, 1.0, 1.0), metallic=0.0,
                       roughness=POST_ROUGHNESS, textures={"baseColor": face},
                       doubleSided=False)


def sign_mesh(kind: str, profile: Optional[SignProfile] = None,
              material: Optional[PBRMaterial] = None,
              cells: Optional[Dict[str, Any]] = None) -> PBRMesh:
    """One whole sign at the origin, facing -Z, as a single mesh.

    Post and plate together, reading out of one atlas, so a sign is one material
    however many kinds a world has. ``cells`` is :func:`sign_atlas`\'s box map;
    left out, an atlas of this one kind is made for it.
    """
    if kind not in WARNINGS:
        raise ValueError("no warning sign says %r; the kinds are %s"
                         % (kind, ", ".join(WARNINGS)))
    profile = profile or SignProfile()
    if cells is None:
        _image, cells = sign_atlas((kind,))
        if material is None:
            material = atlas_material(kinds=(kind,))
    if material is None:
        material = atlas_material()
    return _merged([_post(profile, material, uv=_middle(cells["post"])),
                    _plate(profile, material, box=cells[kind])], material)


def _srgb(colour: "Tuple[float, float, float]") -> tuple:
    """A linear albedo as the bytes an sRGB texture has to hold for it."""
    def encoded(value: float) -> int:
        low = value * 12.92
        high = 1.055 * (value ** (1.0 / 2.4)) - 0.055
        return int(round(255.0 * (low if value <= 0.0031308 else high)))
    return tuple(encoded(float(v)) for v in colour) + (255,)


def _middle(box: Any) -> "Tuple[float, float]":
    """The centre of an atlas cell, for geometry that wants one flat colour."""
    u0, v0, u1, v1 = box
    return ((u0 + u1) / 2.0, (v0 + v1) / 2.0)


def _merged(meshes: list, material: PBRMaterial) -> PBRMesh:
    """Several meshes of one material as a single mesh."""
    positions, texcoords, indices, offset = [], [], [], 0
    for mesh in meshes:
        positions.append(np.asarray(mesh.positions))
        texcoords.append(np.asarray(mesh.texcoords))
        indices.append(np.asarray(mesh.indices) + offset)
        offset += len(mesh.positions)
    return _mesh(np.concatenate(positions),
                 np.concatenate(indices).astype(np.uint32), material,
                 texcoords=np.concatenate(texcoords).astype("f"))


def sign_meshes(kind: str, profile: Optional[SignProfile] = None,
                material: Optional[PBRMaterial] = None,
                post: Optional[PBRMaterial] = None) -> Dict[str, PBRMesh]:
    """One sign at the origin, facing -Z, as ``{'post': …, 'plate': …}``.

    The prototype's frame: the foot is at y=0, the plate's face looks down -Z,
    and the placement turns it to face the traffic. Two meshes rather than one,
    because the post is metal and the plate is a painted picture.
    """
    if kind not in WARNINGS:
        raise ValueError("no warning sign says %r; the kinds are %s"
                         % (kind, ', '.join(WARNINGS)))
    profile = profile or SignProfile()
    return {'post': _post(profile, post if post is not None else post_material()),
            'plate': _plate(profile, material if material is not None
                            else sign_material(kind))}


def _triangle(size: int, inset: float) -> list:
    """An equilateral triangle, point up, inside a square of ``size`` pixels.

    ``inset`` shrinks it towards its own centroid, which is how the border is
    drawn: the same triangle, smaller, painted over the larger one.
    """
    margin = size * 0.04
    span = size - 2 * margin
    points = [(size / 2.0, margin),
              (size - margin, size - margin),
              (margin, size - margin)]
    if inset <= 0.0:
        return points
    cx = sum(p[0] for p in points) / 3.0
    cy = sum(p[1] for p in points) / 3.0
    keep = 1.0 - inset * (size / max(span, 1.0)) * 1.9
    return [(cx + (x - cx) * keep, cy + (y - cy) * keep) for x, y in points]


def _symbol(draw: Any, kind: str, size: int) -> None:
    """Paint what this sign warns of, inside the plate's white face."""
    s = size / 100.0                             # the drawing is in percentages
    width = max(int(round(5 * s)), 2)

    def line(points: list) -> None:
        draw.line([(x * s, y * s) for x, y in points], fill=PLATE_SYMBOL,
                  width=width, joint='curve')

    if kind in ('bend-left', 'bend-right'):
        # A road going away and turning: read from the bottom up.
        bend = [(58, 84), (58, 70), (42, 58), (42, 50)]
        if kind == 'bend-right':
            bend = [(100 - x, y) for x, y in bend]
        line(bend)
        _arrow(draw, bend[-2], bend[-1], size)
    elif kind == 'double-bend':
        bend = [(50, 86), (50, 78), (40, 68), (40, 60), (57, 52), (57, 46)]
        line(bend)
        _arrow(draw, bend[-2], bend[-1], size)
    elif kind == 'dip':
        line([(33, 58), (42, 58), (50, 80), (58, 58), (67, 58)])
    elif kind == 'crest':
        line([(33, 82), (42, 82), (50, 58), (58, 82), (67, 82)])
    elif kind == 'tunnel':
        # A portal: an arch standing on the ground.
        draw.arc([(37 * s, 50 * s), (63 * s, 76 * s)], 180, 360,
                 fill=PLATE_SYMBOL, width=width)
        line([(37, 63), (37, 82)])
        line([(63, 63), (63, 82)])
        line([(28, 82), (72, 82)])
    else:                                        # junction
        line([(50, 86), (50, 52)])
        line([(34, 64), (66, 64)])


def _arrow(draw: Any, tail: tuple, head: tuple, size: int) -> None:
    """A head on the end of a symbol's stroke, pointing away from ``tail``."""
    s = size / 100.0
    angle = math.atan2(head[1] - tail[1], head[0] - tail[0])
    wing = 9.0
    points = [(head[0] * s, head[1] * s)]
    for turn in (2.6, -2.6):
        points.append(((head[0] + math.cos(angle + turn) * wing) * s,
                       (head[1] + math.sin(angle + turn) * wing) * s))
    draw.polygon(points, fill=PLATE_SYMBOL)


def _post(profile: SignProfile, material: PBRMaterial,
          uv: "Optional[Tuple[float, float]]" = None) -> PBRMesh:
    """The post: a low-sided tube from the ground to the plate's bottom edge.

    ``uv`` is the one place in an atlas every vertex of it reads, so post and
    plate share a texture and a sign is one material.
    """
    sides = max(int(profile.post_sides), 3)
    angle = np.linspace(0.0, 2.0 * np.pi, sides, endpoint=False)
    ring = np.stack([np.cos(angle), np.sin(angle)], axis=-1) * profile.post_radius
    top = profile.post_height + profile.plate_size * _PLATE_RISE
    lower = np.stack([ring[:, 0], np.zeros(sides), ring[:, 1]], axis=-1)
    upper = lower.copy()
    upper[:, 1] = top
    positions = np.concatenate([lower, upper])
    faces = []
    for index in range(sides):
        step = (index + 1) % sides
        faces += [index, step, index + sides, step, step + sides, index + sides]
    for index in range(1, sides - 1):
        faces += [sides, sides + index + 1, sides + index]
    texcoords = (None if uv is None
                 else np.tile(np.asarray(uv, dtype='f'), (len(positions), 1)))
    return _mesh(positions, np.asarray(faces, dtype=np.uint32), material,
                 texcoords=texcoords)


def _plate(profile: SignProfile, material: PBRMaterial,
           box: "Optional[Tuple[float, float, float, float]]" = None) -> PBRMesh:
    """The plate: a thin triangular prism, point up, facing -Z.

    ``box`` is the corner of an atlas its face reads out of; without one it
    reads the whole image, which is what a plate with a texture of its own does.
    """
    u0, v0, u1, v1 = box if box is not None else (0.0, 0.0, 1.0, 1.0)
    half = profile.plate_size / 2.0
    rise = profile.plate_size * _PLATE_RISE
    foot = profile.post_height
    corners = [(0.0, foot + rise), (half, foot), (-half, foot)]
    uv = [((u0 + u1) / 2.0, v0), (u1, v1), (u0, v1)]
    depth = profile.plate_depth / 2.0
    positions, texcoords, faces = [], [], []
    for sign in (-1.0, 1.0):                     # the face, then the back
        for (x, y), (u, v) in zip(corners, uv, strict=True):
            positions.append((x, y, sign * depth))
            texcoords.append((u, v))
    faces += [0, 2, 1]                           # the face, looking down -Z
    faces += [3, 4, 5]
    for index in range(3):
        step = (index + 1) % 3
        faces += [index, step, index + 3, step, step + 3, index + 3]
    return _mesh(np.asarray(positions, dtype='d'),
                 np.asarray(faces, dtype=np.uint32), material,
                 texcoords=np.asarray(texcoords, dtype='f'))


#: How tall an equilateral triangle is against its own width.
_PLATE_RISE = math.sqrt(3.0) / 2.0


def _mesh(positions: np.ndarray, indices: np.ndarray, material: PBRMaterial,
          texcoords: Optional[np.ndarray] = None) -> PBRMesh:
    points = np.ascontiguousarray(positions, dtype='f')
    return PBRMesh(positions=points, normals=estimate_normals(points, indices),
                   indices=indices, material=material, texcoords=texcoords)
