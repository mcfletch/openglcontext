"""Road signs: a post, the plates on it, and what is painted on each.

A road that is generated already knows what it is about to do. The alignment
carries its own curvature and its own grade, and the structures along it are
written down, so *what* a sign says and *where* it belongs are derivable rather
than authored -- which is most of the point of generating a road instead of
drawing one. Deciding that is authoring and lives in
``OpenGLContext_editor.world.signs``; what is here is the object itself.

**The signs are Ontario's.** A warning is a black symbol on a yellow diamond; how
fast the hazard is worth goes on a rectangular tab below it; a speed limit is a
white rectangle reading MAXIMUM over the number over km/h. The *shape* carries
as much as the symbol does -- a driver reads a diamond as "take care" and a white
rectangle as "this is the law" before they have read anything on it -- so a sign
is built from an outline as well as a picture, and the plate's geometry is the
shape the picture is.

:func:`sign_mesh` builds one at the origin, facing -Z, because a world has tens
of signs and they are placed rather than modelled one at a time.
:func:`sign_texture` paints a plate, so a world needs no sign artwork to ship
with it.

**Every plate reads out of one image.** A dozen plates as a dozen textures is a
dozen materials and a dozen draws for what is one object with a different
picture on it, so :func:`sign_atlas` puts them -- and the post's own colour -- in
a single image and says where each one lives. A sign is then one mesh with one
material whatever it says, and a world's signs are one draw a tile.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.scenegraph.atlasmesh import (
    cell_centre,
    flat_patch,
    merged_mesh,
    pack_cells,
    textured_mesh,
)
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = ['WARNINGS', 'ADVISORY', 'LIMIT', 'SignFace', 'SignProfile',
           'sign_mesh', 'sign_meshes', 'sign_texture', 'sign_atlas',
           'sign_material', 'atlas_material', 'post_material', 'plate_shape',
           'speed_plate', 'WARNING_FACE', 'REGULATORY_FACE', 'LEGEND']

#: What a sign can warn of. Each is a symbol on the same yellow diamond, which
#: is what a warning sign is: the shape says "take care" and the symbol says
#: what of.
WARNINGS = ('bend-left', 'bend-right', 'double-bend', 'dip', 'crest',
            'tunnel', 'junction')

#: The plate that says how fast a hazard is worth, and the one that says how
#: fast the road is. Both carry a number, so both are named with one
#: (:func:`speed_plate`).
ADVISORY = 'advisory'
LIMIT = 'limit'

#: The colours. Highway yellow for a warning, white for a regulation, and the
#: same near-black for every border and every legend. Held here rather than in
#: the drawing code because a caller repainting a world's signs to another
#: standard changes these and nothing else.
WARNING_FACE = (247, 195, 10, 255)
REGULATORY_FACE = (245, 244, 240, 255)
LEGEND = (22, 22, 24, 255)
PLATE_CLEAR = (0, 0, 0, 0)

#: How wide a plate's border is, against the *shorter* side of that plate. The
#: shorter side, so a letterbox tab does not come out mostly border: a border is
#: read as an edge to the sign, and how thick it looks is against the narrow way
#: across it.
BORDER_FRACTION = 0.075

#: How wide and how tall each kind of plate is, against the size a sign is
#: built to. A diamond is square on its point; a tab is a letterbox under it;
#: a speed limit stands up, because that is what tells it from a warning at the
#: distance a driver picks a sign out at.
DIAMOND_SHAPE = (1.0, 1.0)
ADVISORY_SHAPE = (0.66, 0.34)
LIMIT_SHAPE = (0.62, 0.86)

#: A galvanised post: half a metal, not quite smooth, and darker than it looks
#: like it should be -- under a strong sun a mid grey comes out white, and a
#: white pole beside a forest road is the most conspicuous object in the scene.
POST_ALBEDO = (0.19, 0.196, 0.207)
POST_METALLIC = 0.15
POST_ROUGHNESS = 0.5


def speed_plate(kind: str, speed: int) -> str:
    """What the plate carrying a speed is called: ``'advisory-60'``."""
    return '%s-%d' % (kind, int(speed))


@dataclass(frozen=True)
class SignFace:
    """One sign: what it warns of, and how fast that is worth.

    ``kind`` is one of :data:`WARNINGS`, or :data:`LIMIT` for a speed limit.
    ``speed`` is in km/h: on a warning it adds the advisory tab under the
    diamond, and on a limit it is the number the sign is.

    A sign is a *face* rather than a kind because a plate carrying a number is
    a different picture for every number, and what a world needs painted is
    the ones it actually has.
    """

    kind: str
    speed: int = 0

    @classmethod
    def of(cls, what: "str | SignFace") -> "SignFace":
        """That, as a face: a bare kind is a sign with nothing to say about
        speed."""
        return what if isinstance(what, cls) else cls(str(what))

    def __str__(self) -> str:
        return self.kind if not self.speed else '%s %d' % (self.kind, self.speed)

    @property
    def plates(self) -> Tuple[str, ...]:
        """The plates this sign carries, bottom of the post upwards."""
        if self.kind == LIMIT:
            if self.speed <= 0:
                raise ValueError(
                    'a speed limit sign is the speed it names, and this one '
                    'names none')
            return (speed_plate(LIMIT, self.speed),)
        if self.kind not in WARNINGS:
            raise ValueError('no sign says %r; the kinds are %s, and %s'
                             % (self.kind, ', '.join(WARNINGS), LIMIT))
        if self.speed > 0:
            return (speed_plate(ADVISORY, self.speed), self.kind)
        return (self.kind,)


@dataclass
class SignProfile:
    """The shape of a sign, in metres.

    ``post_height`` is how far the bottom edge of the lowest plate sits above
    the ground -- high enough that a car does not clip it and low enough to read
    from a driving position. ``plate_size`` is how big the diamond is across,
    ``plate_depth`` how thick a plate is, ``plate_gap`` how far apart two on one
    post stand, and ``post_radius`` the post's own.

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
    plate_gap: float = 0.05
    offset: float = 1.4


def plate_shape(name: str) -> Tuple[float, float]:
    """How wide and how tall that plate is, against a sign's own size."""
    if name.startswith(ADVISORY + '-'):
        return ADVISORY_SHAPE
    if name.startswith(LIMIT + '-'):
        return LIMIT_SHAPE
    if name in WARNINGS:
        return DIAMOND_SHAPE
    raise ValueError('there is no plate called %r' % (name,))


def post_material() -> PBRMaterial:
    """What a sign's post is made of."""
    return PBRMaterial(baseColor=POST_ALBEDO, metallic=POST_METALLIC,
                       roughness=POST_ROUGHNESS, doubleSided=False)


def sign_texture(name: str, size: int = 256) -> Any:
    """The face of one plate, as an RGBA image.

    Transparent outside the plate's own outline, so the picture is the shape the
    plate is and a caller may put it on a quad if it would rather. The outline
    is centred in the square: :func:`plate_shape` says how much of it the plate
    fills, and the geometry reads exactly that much
    (:func:`_plate`), so nothing is stretched.
    """
    from PIL import Image, ImageChops, ImageDraw
    wide, tall = plate_shape(name)
    image = Image.new('RGBA', (size, size), PLATE_CLEAR)
    draw = ImageDraw.Draw(image)
    face = WARNING_FACE if not name.startswith(LIMIT + '-') else REGULATORY_FACE
    outline = _outline(name, size)
    draw.polygon(outline, fill=LEGEND)
    inner = _inset(outline, BORDER_FRACTION * _span(name, size) * min(wide, tall))
    draw.polygon(inner, fill=face)
    # The legend is painted on its own layer and let through only where the
    # face is, so nothing runs over the border however big it is asked to be.
    ink = Image.new('RGBA', (size, size), PLATE_CLEAR)
    _paint(ImageDraw.Draw(ink), name, size)
    keep = Image.new('L', (size, size), 0)
    ImageDraw.Draw(keep).polygon(inner, fill=255)
    image.paste(ink, (0, 0), ImageChops.multiply(ink.split()[3], keep))
    return image


def sign_material(name: str, size: int = 256, image: Any = None) -> PBRMaterial:
    """The material for one plate.

    ``image`` overrides the painted face -- an
    :class:`~OpenGLContext.loaders.gltf.writer.ExternalImage` for a baked world,
    which writes the picture once beside the tileset rather than into every tile
    that carries a sign.
    """
    face = image if image is not None else PBRTexture(sign_texture(name, size),
                                                      srgb=True)
    # Opaque, and one-sided. A plate is a prism cut to its own outline with a
    # back of its own, so the picture's transparent corners fall outside the
    # geometry and never reach a fragment. Declared as a cutout instead, every
    # sign in a world joins the sorted alpha pass, which is what a sheet of
    # painted metal is not.
    return PBRMaterial(baseColor=(1.0, 1.0, 1.0), metallic=0.0, roughness=0.55,
                       textures={'baseColor': face}, doubleSided=False)


def plates_of(faces: "Iterable[str | SignFace]") -> Tuple[str, ...]:
    """Every plate the signs need, once each, in a settled order."""
    found: list[str] = []
    for one in faces:
        for plate in SignFace.of(one).plates:
            if plate not in found:
                found.append(plate)
    return tuple(found)


def sign_atlas(faces: "Sequence[str | SignFace]" = WARNINGS, cell: int = 256
               ) -> "Tuple[Any, Dict[str, Tuple[float, float, float, float]]]":
    """Every plate, and the post's colour, in one image.

    Returns the image and ``{name: (u0, v0, u1, v1)}`` -- a box per plate, and
    one called ``post`` holding a flat patch of the post's own colour so the
    whole sign reads out of one texture and is one material.

    Laid out on the smallest square grid that holds them, in the order given, so
    the same signs always make the same atlas and a world re-bakes to itself.
    """
    patches = {name: sign_texture(name, cell) for name in plates_of(faces)}
    patches['post'] = flat_patch(POST_ALBEDO, cell)
    return pack_cells(patches, cell)


def atlas_material(image: Any = None,
                   faces: "Sequence[str | SignFace]" = WARNINGS,
                   cell: int = 256) -> PBRMaterial:
    """The one material a sign built against :func:`sign_atlas` wears.

    ``image`` overrides the painted atlas -- an
    :class:`~OpenGLContext.loaders.gltf.writer.ExternalImage` for a baked world,
    which writes the picture once beside the tileset rather than into every tile
    that carries a sign.
    """
    face = image if image is not None else PBRTexture(
        sign_atlas(faces, cell)[0], srgb=True)
    return PBRMaterial(baseColor=(1.0, 1.0, 1.0), metallic=0.0,
                       roughness=POST_ROUGHNESS, textures={'baseColor': face},
                       doubleSided=False)


def sign_mesh(face: "str | SignFace", profile: Optional[SignProfile] = None,
              material: Optional[PBRMaterial] = None,
              cells: Optional[Dict[str, Any]] = None) -> PBRMesh:
    """One whole sign at the origin, facing -Z, as a single mesh.

    Post and plates together, reading out of one atlas, so a sign is one
    material however much it says. ``cells`` is :func:`sign_atlas`\'s box map;
    left out, an atlas of this one sign is made for it.
    """
    face = SignFace.of(face)
    profile = profile or SignProfile()
    if cells is None:
        _image, cells = sign_atlas((face,))
        if material is None:
            material = atlas_material(faces=(face,))
    if material is None:
        material = atlas_material()
    parts = [_post(profile, material, uv=cell_centre(cells['post']),
                   top=_plate_top(face, profile))]
    parts += [_plate(profile, material, name, foot, box=cells[name])
              for name, foot in _stack(face, profile)]
    return merged_mesh(parts, material)


def sign_meshes(face: "str | SignFace", profile: Optional[SignProfile] = None,
                material: Optional[PBRMaterial] = None,
                post: Optional[PBRMaterial] = None) -> Dict[str, PBRMesh]:
    """One sign at the origin, facing -Z, as ``{'post': …, 'plate': …}``.

    The prototype's frame: the foot is at y=0, the plates look down -Z, and the
    placement turns them to face the traffic. The plates are one mesh and the
    post another, because the post is metal and a plate is a painted picture.
    """
    face = SignFace.of(face)
    profile = profile or SignProfile()
    faces = material if material is not None else sign_material(
        face.plates[-1])
    return {'post': _post(profile, post if post is not None else post_material(),
                          top=_plate_top(face, profile)),
            'plate': merged_mesh(
                [_plate(profile, faces, name, foot)
                 for name, foot in _stack(face, profile)], faces)}


def _stack(face: SignFace, profile: SignProfile) -> "list[Tuple[str, float]]":
    """Each plate and the height its bottom edge sits at, bottom upwards."""
    foot = float(profile.post_height)
    out = []
    for name in face.plates:
        out.append((name, foot))
        foot += plate_shape(name)[1] * profile.plate_size + profile.plate_gap
    return out


def _plate_top(face: SignFace, profile: SignProfile) -> float:
    """How far up the post the topmost plate reaches."""
    name, foot = _stack(face, profile)[-1]
    return foot + plate_shape(name)[1] * profile.plate_size


def _outline(name: str, size: int) -> list:
    """The plate's own shape, in pixels, centred in a square of ``size``.

    A diamond for a warning and a rectangle for anything that carries words,
    each filling the width or the height of the square, whichever its shape
    runs out of first.
    """
    wide, tall = plate_shape(name)
    span = _span(name, size)
    half_wide, half_tall = wide * span / 2.0, tall * span / 2.0
    middle = size / 2.0
    if name in WARNINGS:
        return [(middle, middle - half_tall), (middle + half_wide, middle),
                (middle, middle + half_tall), (middle - half_wide, middle)]
    return [(middle - half_wide, middle - half_tall),
            (middle + half_wide, middle - half_tall),
            (middle + half_wide, middle + half_tall),
            (middle - half_wide, middle + half_tall)]


def _span(name: str, size: int) -> float:
    """How many pixels a plate of size 1 gets in a cell of ``size`` pixels.

    Whichever way the plate is longer decides, so the picture fills the cell in
    that direction and leaves a hair of margin for the border to sit inside.
    """
    return (size - 2.0 * size * 0.03) / max(plate_shape(name))


def _inset(outline: list, by: float) -> list:
    """The same outline, shrunk towards its own centre by ``by`` pixels.

    Towards the centre rather than along each edge's normal: every outline here
    is a convex polygon about its own middle, and for those the two differ by
    less than the border is wide.
    """
    cx = sum(x for x, _y in outline) / len(outline)
    cy = sum(y for _x, y in outline) / len(outline)
    out = []
    for x, y in outline:
        away = math.hypot(x - cx, y - cy)
        keep = max(away - by, 0.0) / max(away, 1e-6)
        out.append((cx + (x - cx) * keep, cy + (y - cy) * keep))
    return out


def _box_of(name: str, size: int = 1000) -> "Tuple[float, float, float, float]":
    """Where in its square cell the plate's picture is, as fractions of it.

    The geometry reads exactly this, so a letterbox tab is not stretched to fill
    a square and a diamond is not squashed into one.
    """
    outline = _outline(name, size)
    xs = [x for x, _y in outline]
    ys = [y for _x, y in outline]
    return (min(xs) / size, min(ys) / size, max(xs) / size, max(ys) / size)


def _paint(draw: Any, name: str, size: int) -> None:
    """Paint what this plate says, inside its own face."""
    if name in WARNINGS:
        _symbol(draw, name, size)
    elif name.startswith(ADVISORY + '-'):
        _advisory(draw, int(name.rsplit('-', 1)[1]), size)
    else:
        _maximum(draw, int(name.rsplit('-', 1)[1]), size)


def _advisory(draw: Any, speed: int, size: int) -> None:
    """A speed to take the hazard at: the number, and the units under it."""
    wide, tall = ADVISORY_SHAPE
    span = size / max(wide, tall)
    half_wide, half_tall = wide * span / 2.0, tall * span / 2.0
    middle = size / 2.0
    _fitted(draw, str(int(speed)),
            (middle - half_wide * 0.9, middle - half_tall * 0.78,
             middle + half_wide * 0.9, middle + half_tall * 0.25))
    _fitted(draw, 'km/h',
            (middle - half_wide * 0.6, middle + half_tall * 0.28,
             middle + half_wide * 0.6, middle + half_tall * 0.82))


def _maximum(draw: Any, speed: int, size: int) -> None:
    """A speed limit: MAXIMUM over the number over km/h."""
    wide, tall = LIMIT_SHAPE
    span = size / max(wide, tall)
    half_wide, half_tall = wide * span / 2.0, tall * span / 2.0
    middle = size / 2.0
    _fitted(draw, 'MAXIMUM',
            (middle - half_wide * 0.82, middle - half_tall * 0.82,
             middle + half_wide * 0.82, middle - half_tall * 0.5))
    _fitted(draw, str(int(speed)),
            (middle - half_wide * 0.8, middle - half_tall * 0.42,
             middle + half_wide * 0.8, middle + half_tall * 0.45))
    _fitted(draw, 'km/h',
            (middle - half_wide * 0.62, middle + half_tall * 0.52,
             middle + half_wide * 0.62, middle + half_tall * 0.84))


def _fitted(draw: Any, text: str, box: "Tuple[float, float, float, float]"
            ) -> None:
    """Draw ``text`` as large as it will go inside ``box``, centred in it.

    Sized by measurement rather than by a rule of thumb: the legends here are
    one to seven characters, and a size that fits MAXIMUM leaves a two-digit
    number too small to read from a car.
    """
    from PIL import ImageFont
    left, top, right, bottom = box
    room_wide, room_tall = max(right - left, 1.0), max(bottom - top, 1.0)
    size = max(int(room_tall), 4)
    while size > 4:
        font = ImageFont.load_default(size=size)
        x0, y0, x1, y1 = font.getbbox(text)
        if x1 - x0 <= room_wide and y1 - y0 <= room_tall:
            draw.text(((left + right) / 2.0 - (x1 + x0) / 2.0,
                       (top + bottom) / 2.0 - (y1 + y0) / 2.0),
                      text, font=font, fill=LEGEND)
            return
        size -= 1


def _symbol(draw: Any, kind: str, size: int) -> None:
    """Paint what this sign warns of, inside the plate's face.

    The drawing is in percentages of the plate, and the middle of a diamond is
    the only part of it that is full width, so a symbol is drawn about the
    middle and kept clear of the corners.
    """
    s = size / 100.0                             # the drawing is in percentages
    width = max(int(round(6 * s)), 2)

    def line(points: list) -> None:
        draw.line([(x * s, y * s) for x, y in points], fill=LEGEND,
                  width=width, joint='curve')

    if kind in ('bend-left', 'bend-right'):
        # A road going away and turning: read from the bottom up.
        bend = [(58, 74), (58, 60), (42, 48), (42, 40)]
        if kind == 'bend-right':
            bend = [(100 - x, y) for x, y in bend]
        line(bend[:-1])
        _arrow(draw, bend[-2], bend[-1], size)
    elif kind == 'double-bend':
        bend = [(50, 78), (50, 70), (40, 60), (40, 52), (57, 42), (57, 36)]
        line(bend[:-1])
        _arrow(draw, bend[-2], bend[-1], size)
    elif kind == 'dip':
        line([(30, 42), (40, 42), (50, 70), (60, 42), (70, 42)])
    elif kind == 'crest':
        line([(30, 66), (40, 66), (50, 38), (60, 66), (70, 66)])
    elif kind == 'tunnel':
        # A portal: an arch standing on the ground. The ground line is kept
        # inside the width the diamond has at that height, which is well short
        # of the width it has across its middle.
        draw.arc([(37 * s, 34 * s), (63 * s, 60 * s)], 180, 360,
                 fill=LEGEND, width=width)
        line([(37, 47), (37, 66)])
        line([(63, 47), (63, 66)])
        line([(31, 66), (69, 66)])
    else:                                        # junction
        line([(50, 76), (50, 34)])
        line([(32, 50), (68, 50)])


def _arrow(draw: Any, tail: tuple, head: tuple, size: int,
           half: float = 8.0) -> None:
    """A head from ``tail`` to ``head``, as wide as ``half`` either side.

    The stroke it finishes stops at ``tail``, so the head is a triangle standing
    on the end of a line rather than a thickening of one -- which at the size a
    sign is read from a moving car is the difference between an arrow and a
    blob.
    """
    s = size / 100.0
    angle = math.atan2(head[1] - tail[1], head[0] - tail[0])
    across = (-math.sin(angle) * half, math.cos(angle) * half)
    draw.polygon([(head[0] * s, head[1] * s),
                  ((tail[0] + across[0]) * s, (tail[1] + across[1]) * s),
                  ((tail[0] - across[0]) * s, (tail[1] - across[1]) * s)],
                 fill=LEGEND)


def _post(profile: SignProfile, material: PBRMaterial,
          uv: "Optional[Tuple[float, float]]" = None,
          top: Optional[float] = None) -> PBRMesh:
    """The post: a low-sided tube from the ground to the top of the sign.

    ``top`` is how far up it goes, which is the top of the highest plate on it.
    ``uv`` is the one place in an atlas every vertex of it reads, so post and
    plates share a texture and a sign is one material.
    """
    sides = max(int(profile.post_sides), 3)
    angle = np.linspace(0.0, 2.0 * np.pi, sides, endpoint=False)
    ring = np.stack([np.cos(angle), np.sin(angle)], axis=-1) * profile.post_radius
    reach = float(profile.post_height + profile.plate_size if top is None
                  else top)
    lower = np.stack([ring[:, 0], np.zeros(sides), ring[:, 1]], axis=-1)
    upper = lower.copy()
    upper[:, 1] = reach
    positions = np.concatenate([lower, upper])
    faces = []
    for index in range(sides):
        step = (index + 1) % sides
        faces += [index, step, index + sides, step, step + sides, index + sides]
    for index in range(1, sides - 1):
        faces += [sides, sides + index + 1, sides + index]
    texcoords = (None if uv is None
                 else np.tile(np.asarray(uv, dtype='f'), (len(positions), 1)))
    return textured_mesh(positions, np.asarray(faces, dtype=np.uint32),
                         material, texcoords)


def _plate(profile: SignProfile, material: PBRMaterial, name: str,
           foot: float,
           box: "Optional[Tuple[float, float, float, float]]" = None) -> PBRMesh:
    """One plate: a thin prism cut to that plate's own outline, facing -Z.

    ``foot`` is where its bottom edge sits above the ground. ``box`` is the
    corner of an atlas its face reads out of; without one it reads the whole
    image, which is what a plate with a texture of its own does.

    The picture sits inside a square cell at the plate's own aspect
    (:func:`_box_of`), and the geometry reads exactly that part of it, so a
    letterbox tab is not stretched to fill a square.
    """
    wide, tall = plate_shape(name)
    span = profile.plate_size
    half = wide * span / 2.0
    height = tall * span
    if name in WARNINGS:
        # A diamond, on its point: bottom, right, top, left.
        corners = [(0.0, foot), (half, foot + height / 2.0),
                   (0.0, foot + height), (-half, foot + height / 2.0)]
        picture = [(0.5, 1.0), (1.0, 0.5), (0.5, 0.0), (0.0, 0.5)]
    else:
        corners = [(-half, foot), (half, foot), (half, foot + height),
                   (-half, foot + height)]
        picture = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
    uv = [_within(box, name, u, v) for u, v in picture]
    depth = profile.plate_depth / 2.0
    positions, texcoords, faces = [], [], []
    for sign in (-1.0, 1.0):                     # the face, then the back
        for (x, y), (u, v) in zip(corners, uv, strict=True):
            positions.append((x, y, sign * depth))
            texcoords.append((u, v))
    count = len(corners)
    for index in range(1, count - 1):            # the face, looking down -Z
        faces += [0, index + 1, index]
        faces += [count, count + index, count + index + 1]
    for index in range(count):
        step = (index + 1) % count
        faces += [index, step, index + count, step, step + count, index + count]
    return textured_mesh(np.asarray(positions, dtype='d'),
                         np.asarray(faces, dtype=np.uint32), material,
                         np.asarray(texcoords, dtype='f'))


def _within(box: "Optional[Tuple[float, float, float, float]]", name: str,
            u: float, v: float) -> "Tuple[float, float]":
    """A point of a plate's own picture, as a point of the atlas.

    Twice narrowed: the cell this plate's picture was packed into, and the part
    of that cell the picture actually fills.
    """
    c0, d0, c1, d1 = box if box is not None else (0.0, 0.0, 1.0, 1.0)
    p0, q0, p1, q1 = _box_of(name)
    return (c0 + (c1 - c0) * (p0 + (p1 - p0) * u),
            d0 + (d1 - d0) * (q0 + (q1 - q0) * v))
