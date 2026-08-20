"""Roads: a centreline and a cross-section become a drivable surface.

A road is a 3D polyline through the world plus a *profile* -- the shape of a cut
across it, from the crown of the carriageway out through the shoulder to the
verge that meets the ground. :func:`road_surface` sweeps the profile along the
line and returns the arrays; :func:`road_mesh` wraps them in a
:class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh` with a road material on it,
ready to render or to write into a tile.

This is the runtime half. Nothing here decides *where* a road goes, whether a
valley wants a bridge or a causeway, or how the ground is reshaped to meet the
shoulder -- that is authoring, and it lives in ``OpenGLContext_editor``. A game
that generates a road at runtime, or an editor drawing one under the cursor,
uses what is here and needs nothing else.

The road surface is generated with a **frame per centreline point**: the
tangent along the line, the right vector across it, and the up vector their
cross product gives, so the carriageway banks with a climb and stays the width
it is told through a bend.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Optional, Tuple

import numpy as np

from OpenGLContext.loaders.gltf.meshes import estimate_normals, estimate_tangents
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = [
    'RoadProfile', 'resample_polyline', 'sweep_frames', 'morphed_sections',
    'road_surface', 'road_mesh', 'road_texture', 'tarmac_material',
    'estimate_normals',
]

#: Which way is up when a road has no other opinion. A road banks with its
#: grade but does not roll over, so the frame is built against world up.
WORLD_UP = np.array([0.0, 1.0, 0.0])

#: Albedo of the three surfaces the road texture carries. Asphalt is one of the
#: darkest surfaces outdoors; gravel and the grass verge beside it are several
#: times brighter, which is most of what makes a road read as a road from a
#: distance.
TARMAC_ALBEDO = (0.055, 0.055, 0.058)
GRAVEL_ALBEDO = (0.42, 0.40, 0.36)
VERGE_ALBEDO = (0.24, 0.27, 0.14)
LINE_ALBEDO = (0.86, 0.86, 0.82)

#: How wide the kerb is where a road runs over a structure, in metres -- what
#: the verge becomes when there is no ground beside the road to fall to.
EDGE_BEAM = 0.4

#: Wet, asphalt darkens and turns near-mirror; the environment then does the
#: work a reflection pass would otherwise have to.
DRY_ROUGHNESS = 0.72
WET_ROUGHNESS = 0.12
WET_DARKENING = 0.45


@dataclass
class RoadProfile:
    """The shape of a cut across a road, in metres.

    Measured out from the crown: ``lanes`` lanes of ``lane_width`` make the
    carriageway, a shoulder of ``shoulder_width`` sits ``shoulder_drop`` below
    its edge, and a verge of ``verge_width`` falls a further ``verge_drop`` to
    meet the ground. ``crossfall`` is the camber that drains the carriageway,
    as a fraction -- 2% is the usual figure for a straight road.

    ``texture_length`` is how many metres of road one repeat of the surface
    texture covers, which is what sets the length of the centre-line dashes.
    """

    lane_width: float = 3.7
    lanes: int = 2
    shoulder_width: float = 1.5
    shoulder_drop: float = 0.10
    verge_width: float = 3.0
    verge_drop: float = 1.2
    crossfall: float = 0.02
    texture_length: float = 25.0

    @property
    def carriageway_width(self) -> float:
        return float(self.lane_width * self.lanes)

    @property
    def total_width(self) -> float:
        """Across everything the road occupies, verge to verge."""
        return self.carriageway_width + 2.0 * (self.shoulder_width + self.verge_width)

    def section(self) -> np.ndarray:
        """The cross-section as (K,2) points: lateral offset, vertical offset.

        Left to right, crown at zero. Vertical offsets are at or below zero,
        so the crown is the highest point of the road and everything drains
        away from it.
        """
        half = self.carriageway_width / 2.0
        edge_drop = -self.crossfall * half
        shoulder = half + self.shoulder_width
        verge = shoulder + self.verge_width
        right: list[tuple[float, float]] = [(0.0, 0.0), (half, edge_drop)]
        if self.shoulder_width > 0:
            right.append((shoulder, edge_drop - self.shoulder_drop))
        if self.verge_width > 0:
            right.append((verge, edge_drop - self.shoulder_drop - self.verge_drop))
        left = [(-lateral, vertical) for lateral, vertical in reversed(right[1:])]
        return np.array(left + right, dtype='d')

    def on_structure(self) -> 'RoadProfile':
        """The same road as it runs over a bridge or through a tunnel.

        The verge neither falls nor stays: there is no ground beside a deck for
        it to fall to, and a strip of grass inside a bore is grass inside a
        bore. What is left is an *edge beam* -- the kerb a parapet stands on, or
        the walkway beside a carriageway in a tunnel.

        The section keeps the same points, so the two can be blended and the
        road narrows onto the structure over a taper rather than stepping onto
        it. The carriageway itself is untouched, so the markings run through
        unchanged.
        """
        return replace(self, verge_drop=0.0,
                       verge_width=(EDGE_BEAM if self.verge_width > 0 else 0.0))

    def section_offset(self, across: Any) -> np.ndarray:
        """How far below the crown the road's surface is, that far out.

        ``across`` is one distance from the centreline or an array of them, in
        metres, either side -- the section is symmetrical, so the sign does not
        matter. The answer is at or below zero, since the crown is the highest
        point of the road.

        Beyond the road's own edge it is held at the verge's value: past there
        the surface is the ground rather than the road, and what the road can
        say is the height the ground has to arrive at for the two to meet.

        This is what puts anything *on* the road at the height the road
        actually is -- a vehicle placed by how far along and how far across it
        is, a marker, a sign's foot -- without asking the physics what is under
        it, which answers about whatever else happens to be standing there.
        """
        section = self.section()
        lateral, vertical = section[:, 0], section[:, 1]
        half = float(lateral.max())
        keep = lateral >= 0
        found: np.ndarray = np.interp(
            np.minimum(np.abs(np.asarray(across, dtype='d')), half),
            lateral[keep], vertical[keep])
        return found

    def section_u(self) -> np.ndarray:
        """The texture coordinate across the section, 0 at the left verge to 1.

        One texture spans the whole cut, so the image carries the verge, the
        shoulder and the carriageway markings as bands and no seam falls
        between them.
        """
        lateral: np.ndarray = self.section()[:, 0]
        left = float(lateral[0])
        return (lateral - left) / (float(lateral[-1]) - left)


def resample_polyline(points: Any, spacing: float) -> np.ndarray:
    """A polyline re-sampled to even spacing along its own length.

    The ends are kept exactly and the interval is shrunk to divide the length
    evenly, so a road never finishes with a stub segment. Coarsening a road for
    a distant tile is this function with a bigger ``spacing``.
    """
    line = np.asarray(points, dtype='d').reshape(-1, 3)
    if len(line) < 2:
        raise ValueError("a polyline needs at least two points")
    steps = np.linalg.norm(np.diff(line, axis=0), axis=1)
    distance = np.concatenate([[0.0], np.cumsum(steps)])
    length = float(distance[-1])
    if length <= 0:                              # pragma: no cover - all points equal
        return line[:1]
    count = max(int(math.ceil(length / float(spacing))), 1) + 1
    wanted = np.linspace(0.0, length, count)
    return np.stack([np.interp(wanted, distance, line[:, axis])
                     for axis in range(3)], axis=-1)


def sweep_frames(line: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Per-point (right, up) vectors for a centreline.

    The tangent at a point is the average of the segments meeting there, so the
    frame turns smoothly through a bend instead of stepping at each vertex.
    Anything swept along a road -- the carriageway, a bridge deck, a tunnel
    bore -- is placed with this, which is what keeps them in register with each
    other through a bend and a climb.
    """
    segments = np.diff(line, axis=0)
    lengths = np.linalg.norm(segments, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    directions = segments / lengths
    tangents = np.empty_like(line)
    tangents[0] = directions[0]
    tangents[-1] = directions[-1]
    if len(line) > 2:
        tangents[1:-1] = directions[:-1] + directions[1:]
    norms = np.linalg.norm(tangents, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    tangents = tangents / norms
    right = np.cross(tangents, WORLD_UP)
    norms = np.linalg.norm(right, axis=1, keepdims=True)
    # A perfectly vertical tangent leaves no right vector; a road never climbs
    # that steeply, but the fallback keeps the frame defined rather than NaN.
    vertical = norms[:, 0] < 1e-9
    right[vertical] = (1.0, 0.0, 0.0)
    norms[vertical] = 1.0
    right = right / norms
    up = np.cross(right, tangents)
    return right, up


def morphed_sections(profile: RoadProfile, other: RoadProfile,
                     blend: Any) -> np.ndarray:
    """A cross-section per centreline point, part way between two profiles.

    ``blend`` is (N,) from 0 (all ``profile``) to 1 (all ``other``), so a road
    changes its cut over as many metres as the blend takes to travel rather
    than stepping from one to the next at a vertex. Both profiles must give
    sections of the same shape, which is what
    :meth:`RoadProfile.on_structure` guarantees.
    """
    here, there = profile.section(), other.section()
    if here.shape != there.shape:
        raise ValueError(
            "profiles with %d and %d section points cannot be blended"
            % (len(here), len(there)))
    weight = np.asarray(blend, dtype='d').reshape(-1, 1, 1)
    return here[None] * (1.0 - weight) + there[None] * weight


def road_surface(points: Any, profile: RoadProfile, sections: Any = None
                 ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sweep a profile along a centreline: positions, normals, UVs, indices.

    ``points`` is the centreline as (N,3) world positions, already at the height
    the road runs at. The mesh has one vertex ring of ``len(profile.section())``
    per point, so re-sampling the centreline is the whole of the road's level of
    detail.

    ``sections`` is an optional (N,K,2) array giving the cut at each point, for
    a road whose shape changes along its length -- a verge that flattens onto a
    bridge deck, a shoulder that narrows into a bore. Build one with
    :func:`morphed_sections`. ``profile`` still supplies the texture coordinates
    across the cut, so the markings stay where they belong through the change.
    """
    line = np.asarray(points, dtype='d').reshape(-1, 3)
    if len(line) < 2:
        raise ValueError("a road needs a centreline of at least two points")
    section = profile.section()
    right, up = sweep_frames(line)
    ring = len(section)

    if sections is None:
        lateral = section[:, 0][None, :, None]
        vertical = section[:, 1][None, :, None]
    else:
        cuts = np.asarray(sections, dtype='d')
        if cuts.shape != (len(line), ring, 2):
            raise ValueError(
                "a road of %d points needs sections of shape (%d, %d, 2), not %r"
                % (len(line), len(line), ring, (cuts.shape,)))
        lateral = cuts[:, :, 0][:, :, None]
        vertical = cuts[:, :, 1][:, :, None]
    positions = (line[:, None, :] + right[:, None, :] * lateral
                 + up[:, None, :] * vertical).reshape(-1, 3)

    steps = np.linalg.norm(np.diff(line, axis=0), axis=1)
    along = np.concatenate([[0.0], np.cumsum(steps)]) / profile.texture_length
    u = np.tile(profile.section_u(), len(line))
    v = np.repeat(along, ring)
    texcoords = np.stack([u, v], axis=-1)

    indices = _strip_indices(len(line), ring)
    normals = estimate_normals(positions.astype('f'), indices)
    return (positions.astype('f'), normals, texcoords.astype('f'), indices)


def _strip_indices(rows: int, ring: int) -> np.ndarray:
    """Triangles joining consecutive vertex rings, wound counter-clockwise
    seen from above so the surface faces the sky."""
    row = np.arange(rows - 1)[:, None] * ring
    column = np.arange(ring - 1)[None, :]
    a = (row + column).ravel()
    b = a + 1
    c = a + ring
    d = c + 1
    return np.stack([a, b, c, b, d, c], axis=-1).ravel().astype(np.uint32)


def road_mesh(points: Any, profile: Optional[RoadProfile] = None,
              material: Optional[PBRMaterial] = None,
              spacing: Optional[float] = None,
              sections: Any = None, shade: Any = None) -> PBRMesh:
    """A road's surface as a renderable mesh, with tangents for its normal map.

    ``spacing`` re-samples the centreline to that interval in metres first,
    which is the whole of a road's level of detail: the same route at a coarser
    spacing is the road a distant tile carries. Left out, the points given are
    the points swept -- which is what a caller passing ``sections`` wants, since
    a cut per point has to match the points it is swept over.

    ``sections`` is the per-point cross-section described in
    :func:`road_surface`.

    ``shade`` is how much of the sun reaches each point of the centreline, in
    [0, 1], written into the surface's vertex colours -- so a road through a
    wood carries the wood's shade rather than being a lit strip laid across it.
    It may be an array as long as the *written* points, or a callable taking
    them, which is what a caller re-sampling with ``spacing`` needs since it
    does not know in advance how many points there will be. The whole cut at one
    point takes one figure: a road is one place as far as a canopy is concerned.
    """
    profile = profile or RoadProfile()
    if spacing is not None:
        points = resample_polyline(points, spacing)
    positions, normals, texcoords, indices = road_surface(points, profile,
                                                          sections=sections)
    tangents = estimate_tangents(positions, normals, texcoords, indices)
    return PBRMesh(positions=positions, normals=normals, texcoords=texcoords,
                   tangents=tangents, indices=indices,
                   colors=_road_colors(points, positions, shade),
                   material=material if material is not None else tarmac_material())


def _road_colors(points: Any, positions: Any, shade: Any) -> Any:
    """A surface's vertex colours, from a shade along its centreline."""
    if shade is None:
        return None
    written = np.asarray(points, dtype='d').reshape(-1, 3)
    lit = np.asarray(shade(written) if callable(shade) else shade,
                     dtype='f').reshape(-1)
    if len(lit) != len(written):
        raise ValueError(
            "a road of %d points needs %d shades, not %d"
            % (len(written), len(written), len(lit)))
    ring = len(positions) // len(written)
    colors = np.ones((len(positions), 4), dtype='f')
    colors[:, :3] = np.repeat(lit, ring)[:, None]
    return colors


def road_texture(size: int = 512, seed: int = 0) -> Any:
    """The road surface across its whole section, as one image.

    Bands from the left edge: verge, shoulder, carriageway with its edge lines
    and dashed centre line, shoulder, verge. One image for the whole cut means
    no seam where the materials meet, and the markings arrive with the surface
    rather than as decals on top of it.

    The image is the *width* of the section and repeats along the road, so the
    dashes are as long as the profile's ``texture_length`` makes them.
    """
    from PIL import Image
    rng = np.random.default_rng(seed)
    pixels = np.zeros((size, size, 3), dtype='d')
    across = np.linspace(0.0, 1.0, size)[None, :]

    # The bands, as fractions of the section. These follow the default profile's
    # proportions; a road with an unusual section still reads correctly because
    # the markings stay inside the carriageway band.
    verge = 0.18
    shoulder = 0.10
    grass = np.array(VERGE_ALBEDO)
    gravel = np.array(GRAVEL_ALBEDO)
    tarmac = np.array(TARMAC_ALBEDO)

    band = np.zeros((1, size, 3))
    band += grass * (across < verge)[..., None]
    band += gravel * ((across >= verge) & (across < verge + shoulder))[..., None]
    band += tarmac * ((across >= verge + shoulder)
                      & (across <= 1.0 - verge - shoulder))[..., None]
    band += gravel * ((across > 1.0 - verge - shoulder) & (across <= 1.0 - verge))[..., None]
    band += grass * (across > 1.0 - verge)[..., None]
    pixels += band

    # Aggregate speckle, in proportion to how bright each band is, so the
    # carriageway keeps its darkness instead of being greyed by noise.
    grain = (rng.random((size, size, 1)) - 0.5) * 0.35
    pixels = np.clip(pixels * (1.0 + grain), 0.0, 1.0)

    paint = np.array(LINE_ALBEDO)
    edge = 0.012
    for centre in (verge + shoulder + edge * 1.5, 1.0 - verge - shoulder - edge * 1.5):
        stripe = np.abs(across - centre) < edge
        pixels[:, stripe[0]] = paint

    # The centre line is dashed: three parts painted to five parts gap, the
    # proportion a road marking uses so a dash reads at speed.
    dash = (np.arange(size) % size) < int(size * 0.375)
    middle = np.abs(across - 0.5) < edge
    pixels[np.ix_(dash, middle[0])] = paint
    return Image.fromarray((pixels * 255.0).astype('u1'), 'RGB')


def tarmac_material(wetness: float = 0.0, seed: int = 0,
                    texture_size: int = 512, image: Any = None) -> PBRMaterial:
    """The road surface as a PBR material.

    The colour is the texture's, because one image spans tarmac, gravel and the
    grass verge and no single factor describes all three; the material's own
    base colour is the tint on top of it. ``wetness`` runs from dry asphalt to
    standing water: the surface darkens through that tint and its roughness
    collapses, so a wet road picks up the sky and the scenery beside it through
    the environment path rather than through any reflection pass of its own.
    """
    wetness = float(np.clip(wetness, 0.0, 1.0))
    tint = 1.0 - WET_DARKENING * wetness
    return PBRMaterial(
        baseColor=(tint, tint, tint),
        metallic=0.0,
        roughness=DRY_ROUGHNESS + (WET_ROUGHNESS - DRY_ROUGHNESS) * wetness,
        doubleSided=False,
        textures={'baseColor': image if image is not None
                  else PBRTexture(road_texture(texture_size, seed), srgb=True)},
    )
