"""The start/finish gantry: a beam over the road, and a line painted under it.

A lap has to be visible from the driving seat. Timing already knows where the
line is -- it is where the centreline begins -- but a driver cannot see a
number, so a circuit marks it: a chequered banner on a beam spanning the
carriageway, with a chequered line across the tarmac beneath it. Coming the
other way it reads the same, because the banner is a board with two faces.

:func:`gantry_mesh` builds one at the origin with the road running along Z and
the beam spanning X, so a world places it by turning and moving it, the same way
it places a sign. Which way along Z does not matter: a gantry reads the same
from both directions. The legs stand on ground that need not be level with the
road, so each is given its own drop.

**The whole thing reads out of one picture.** Steel, banner and the two road
paints are four corners of one atlas (:func:`gantry_atlas`), so a gantry and its
line are one material and one draw. See
:mod:`OpenGLContext.scenegraph.atlasmesh`.

The legs are solid: :func:`gantry_legs` reports where they stand and how much
room they take, which is what a physics world needs to put a body there without
being handed the geometry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.scenegraph.atlasmesh import (
    Box,
    cell_centre,
    flat_patch,
    merged_mesh,
    pack_cells,
    srgb_bytes,
    textured_mesh,
)
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = ['GantryProfile', 'Leg', 'chequer_texture', 'gantry_atlas',
           'gantry_material', 'gantry_mesh', 'gantry_legs', 'start_line_mesh']

#: Painted steelwork: half a metal, not quite smooth, and darker than a grey
#: chosen by eye. Under a strong sun a mid grey comes out white, and a white
#: frame over a forest road is the most conspicuous object in the scene.
GANTRY_STEEL = (0.17, 0.175, 0.185)
GANTRY_METALLIC = 0.15
GANTRY_ROUGHNESS = 0.5

#: The two colours of the chequer. The light squares are road-paint white rather
#: than paper white, for the same reason the steel is dark.
CHEQUER_DARK = (0.022, 0.022, 0.024)
CHEQUER_LIGHT = (0.70, 0.70, 0.68)

#: How the banner's chequer is divided in its cell of the atlas.
BANNER_SQUARES = (12, 2)

#: How many rows of squares the painted line is deep.
LINE_ROWS = 2


@dataclass
class GantryProfile:
    """The shape of a start/finish gantry, in metres.

    ``clearance`` is the road surface to the underside of the beam -- high
    enough for anything that drives under it. ``beam_depth`` is how deep the
    beam is and ``beam_width`` how far it reaches along the road. The banner
    stands on top of the beam, ``banner_height`` tall and ``banner_depth``
    thick.

    ``margin`` is how far outside the road's running surface each leg stands.
    It is part of the gantry rather than of the placement for the same reason a
    sign's offset is: it is one question -- how far a thing beside a road stands
    from it -- asked once for the world.

    ``line_width`` is how far the painted line reaches along the road and
    ``line_lift`` how far above the surface it is drawn. Paint in the surface
    z-fights with it; paint well above it is a plank.
    """

    clearance: float = 5.4
    leg_radius: float = 0.14
    leg_sides: int = 8
    beam_depth: float = 0.45
    beam_width: float = 0.34
    banner_height: float = 1.0
    banner_depth: float = 0.07
    margin: float = 0.9
    line_width: float = 0.8
    line_lift: float = 0.04

    @property
    def height(self) -> float:
        """Road surface to the top of the banner."""
        return self.clearance + self.beam_depth + self.banner_height


class Leg(NamedTuple):
    """One upright: where it stands across the road, and how much room it takes.

    ``offset`` is its distance from the crown along the beam, signed, and
    ``height`` reaches from its own foot to the top of the beam -- so a leg on
    ground below the road is taller than its neighbour.
    """

    offset: float
    radius: float
    height: float


def chequer_texture(size: int = 256, columns: int = BANNER_SQUARES[0],
                    rows: int = BANNER_SQUARES[1],
                    dark: Sequence[float] = CHEQUER_DARK,
                    light: Sequence[float] = CHEQUER_LIGHT) -> Any:
    """A chequered patch, as an RGBA image ``size`` pixels square.

    The squares are drawn on the cell's own grid, so a caller stretching the
    cell over a wide banner picks ``columns`` to suit: what matters on the road
    is that the squares come out roughly square, not how many there are.
    """
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (size, size), srgb_bytes(light))
    draw = ImageDraw.Draw(image)
    ink = srgb_bytes(dark)
    for row in range(max(int(rows), 1)):
        for column in range(max(int(columns), 1)):
            if (row + column) % 2:
                continue
            draw.rectangle(
                [(column * size / columns, row * size / rows),
                 ((column + 1) * size / columns - 1,
                  (row + 1) * size / rows - 1)], fill=ink)
    return image


def gantry_atlas(cell: int = 256) -> Tuple[Any, Dict[str, Box]]:
    """Steel, banner and road paint in one image.

    Returns the image and ``{name: (u0, v0, u1, v1)}`` for ``steel``,
    ``banner`` and the two paints, so every part of a gantry reads one texture
    and wears one material. The banner carries its chequer as a picture; the
    line on the road is chequered in geometry and reads a flat colour a square
    at a time -- see :func:`start_line_mesh`.
    """
    return pack_cells({
        'steel': flat_patch(GANTRY_STEEL, cell),
        'banner': chequer_texture(cell, *BANNER_SQUARES),
        'paint-light': flat_patch(CHEQUER_LIGHT, cell),
        'paint-dark': flat_patch(CHEQUER_DARK, cell)}, cell)


def gantry_material(image: Any = None, cell: int = 256) -> PBRMaterial:
    """The one material a gantry and its line wear.

    ``image`` overrides the painted atlas -- an
    :class:`~OpenGLContext.loaders.gltf.writer.ExternalImage` for a baked world,
    which writes the picture once beside the tileset rather than into every tile
    that carries part of the gantry.
    """
    face = image if image is not None else PBRTexture(gantry_atlas(cell)[0],
                                                      srgb=True)
    return PBRMaterial(baseColor=(1.0, 1.0, 1.0), metallic=GANTRY_METALLIC,
                       roughness=GANTRY_ROUGHNESS,
                       textures={'baseColor': face}, doubleSided=False)


def gantry_legs(span: float, profile: Optional[GantryProfile] = None,
                drops: Sequence[float] = (0.0, 0.0)) -> List[Leg]:
    """The two uprights of a gantry of this span, left first.

    ``drops`` is how far below the road each leg's ground is, in the same order.
    What :func:`gantry_mesh` draws and what a physics world stands a body up
    from come from here, so the two cannot drift apart.
    """
    profile = profile or GantryProfile()
    reach = float(span) / 2.0
    top = profile.clearance + profile.beam_depth
    return [Leg(offset=side * reach, radius=profile.leg_radius,
                height=top + max(float(drop), 0.0))
            for side, drop in zip((-1.0, 1.0), drops, strict=True)]


def gantry_mesh(span: float, profile: Optional[GantryProfile] = None,
                material: Optional[PBRMaterial] = None,
                cells: Optional[Dict[str, Box]] = None,
                drops: Sequence[float] = (0.0, 0.0)) -> PBRMesh:
    """One whole gantry at the origin, as a single mesh.

    ``span`` is the distance between the leg centres, and the road passes
    between them along Z with its surface at y=0. ``drops`` is how far below
    that surface each leg's own ground lies, left leg first.

    ``cells`` is :func:`gantry_atlas`'s box map; left out, an atlas is made for
    it.
    """
    profile = profile or GantryProfile()
    if float(span) <= profile.leg_radius * 4.0:
        raise ValueError(
            "a gantry of %.2fm cannot span a road: its own legs are %.2fm "
            "across" % (span, profile.leg_radius * 2.0))
    material, cells = _dressed(material, cells)
    steel = cell_centre(cells['steel'])
    reach = float(span) / 2.0
    top = profile.clearance + profile.beam_depth
    pieces = [_tube(offset=leg.offset, radius=leg.radius, sides=profile.leg_sides,
                    bottom=top - leg.height, top=top, material=material,
                    uv=steel)
              for leg in gantry_legs(span, profile, drops)]
    half = profile.beam_width / 2.0
    pieces.append(_box((-reach, profile.clearance, -half), (reach, top, half),
                       material, steel))
    board = profile.banner_depth / 2.0
    pieces.append(_box(
        (-reach, top, -board), (reach, top + profile.banner_height, board),
        material, steel, facing=cells['banner']))
    return merged_mesh(pieces, material)


def start_line_mesh(width: float, profile: Optional[GantryProfile] = None,
                    material: Optional[PBRMaterial] = None,
                    cells: Optional[Dict[str, Box]] = None,
                    crossfall: float = 0.0) -> PBRMesh:
    """The line painted across the carriageway, at the origin, road along Z.

    ``width`` is how far it reaches across the road and ``crossfall`` the
    camber it is painted on, as a fraction. The line follows the camber rather
    than lying flat on it: a flat strip across a cambered road stands proud at
    the crown and sinks into the tarmac at both edges.

    **The chequer is geometry, not a picture.** From a driving seat the line is
    nearly edge-on, and a texture stretched nine times wider than it is deep
    loses its pattern to the mip level that grazing angle asks for -- it reads
    as a plain white bar from the one place anybody looks at it. Each square is
    its own quad reading a flat colour out of the atlas, so it is a chequer at
    any angle and any distance.
    """
    profile = profile or GantryProfile()
    material, cells = _dressed(material, cells)
    paints = (cell_centre(cells['paint-dark']),
              cell_centre(cells['paint-light']))
    half, deep = float(width) / 2.0, profile.line_width / float(LINE_ROWS)
    # An even count, so the crown falls on a joint and the two halves of the
    # line mirror each other; sized off the row depth, so a square is square.
    columns = max(int(round(width / deep / 2.0)), 1) * 2
    positions: List[tuple] = []
    texcoords: List[tuple] = []
    faces: List[int] = []
    for column in range(columns):
        x0 = -half + column * float(width) / columns
        x1 = -half + (column + 1) * float(width) / columns
        for row in range(LINE_ROWS):
            z0 = -profile.line_width / 2.0 + row * deep
            base = len(positions)
            for lateral, reach in ((x0, z0), (x1, z0), (x1, z0 + deep),
                                   (x0, z0 + deep)):
                positions.append((lateral,
                                  profile.line_lift
                                  - abs(lateral) * float(crossfall), reach))
                texcoords.append(paints[(column + row) % 2])
            faces += [base, base + 3, base + 2, base, base + 2, base + 1]
    return textured_mesh(np.asarray(positions, dtype='d'),
                         np.asarray(faces, dtype=np.uint32), material,
                         np.asarray(texcoords, dtype='f'))


def _dressed(material: Optional[PBRMaterial], cells: Optional[Dict[str, Box]]
             ) -> Tuple[PBRMaterial, Dict[str, Box]]:
    """The material and atlas boxes a piece is built against, painting its own
    if the caller has none."""
    if cells is None:
        cells = gantry_atlas()[1]
    if material is None:
        material = gantry_material()
    return material, cells


def _tube(offset: float, radius: float, sides: int, bottom: float, top: float,
          material: PBRMaterial, uv: Tuple[float, float]) -> PBRMesh:
    """One leg: a low-sided tube standing at ``offset`` along the beam.

    Open at both ends -- the foot is in the ground and the head is inside the
    beam, so neither is anywhere a camera can be.
    """
    sides = max(int(sides), 3)
    angle = np.linspace(0.0, 2.0 * np.pi, sides, endpoint=False)
    ring = np.stack([np.cos(angle) * radius + offset, np.zeros(sides),
                     np.sin(angle) * radius], axis=-1)
    lower, upper = ring.copy(), ring.copy()
    lower[:, 1] = bottom
    upper[:, 1] = top
    faces: List[int] = []
    for index in range(sides):
        step = (index + 1) % sides
        faces += [index, step, index + sides, step, step + sides, index + sides]
    positions = np.concatenate([lower, upper])
    return textured_mesh(positions, np.asarray(faces, dtype=np.uint32),
                         material,
                         np.tile(np.asarray(uv, dtype='f'), (len(positions), 1)))


def _box(low: Tuple[float, float, float], high: Tuple[float, float, float],
         material: PBRMaterial, uv: Tuple[float, float],
         facing: Optional[Box] = None) -> PBRMesh:
    """An axis-aligned box, every face its own four corners so it reads flat.

    ``uv`` is the one place in the atlas the box reads. ``facing`` overrides it
    for the two faces looking up and down the road, which is how the banner gets
    its chequer while the frame around it stays steel.
    """
    x0, y0, z0 = low
    x1, y1, z1 = high
    quads = [
        [(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)],   # -Z
        [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],   # +Z
        [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)],   # -X
        [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)],   # +X
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],   # -Y
        [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)],   # +Y
    ]
    positions: List[tuple] = []
    texcoords: List[tuple] = []
    faces: List[int] = []
    for index, quad in enumerate(quads):
        base = len(positions)
        positions += quad
        painted = facing if facing is not None and index < 2 else None
        texcoords += ([_across(point, low, high, painted) for point in quad]
                      if painted else [uv] * 4)
        faces += [base, base + 1, base + 2, base, base + 2, base + 3]
    return textured_mesh(np.asarray(positions, dtype='d'),
                         np.asarray(faces, dtype=np.uint32), material,
                         np.asarray(texcoords, dtype='f'))


def _across(point: Tuple[float, float, float],
            low: Tuple[float, float, float], high: Tuple[float, float, float],
            box: Box) -> Tuple[float, float]:
    """Where one corner of a banner face reads in its cell of the atlas.

    The picture runs the length of the board and stands upright on it, so the
    top of the image is the top of the banner.
    """
    u0, v0, u1, v1 = box
    span = max(high[0] - low[0], 1e-9)
    rise = max(high[1] - low[1], 1e-9)
    return (u0 + (point[0] - low[0]) / span * (u1 - u0),
            v1 - (point[1] - low[1]) / rise * (v1 - v0))
