"""Bridges, causeways and tunnels: what carries a road where the ground does not.

A road settled for grade and speed does not lie on the land everywhere it goes.
Where it runs high above the ground it is carried on a **deck** standing on
piers; where it runs a few metres over low ground it rides a **causeway**, which
is fill only as wide as the road with a low wall at each edge; where it runs
inside the ground it passes through a **bore** with a portal at each end. All
three are built the way the carriageway is -- a cross-section swept along the
centreline, using the same per-point frame
(:mod:`OpenGLContext.scenegraph.road`) -- so a structure stays under or over its
road through a bend and a climb instead of drifting off it.

Give :func:`bridge_meshes`, :func:`causeway_meshes` or :func:`tunnel_meshes` the
stretch of centreline the structure covers and the road profile it carries, and
each returns its parts as ``{name: mesh}`` -- ``deck``, ``parapet`` and ``piers``
for a bridge, ``body`` and ``wall`` for a causeway, ``bore`` and ``portals`` for
a tunnel. Naming the parts rather than merging them lets a caller light, cull or
write them separately; merging them is a concatenation away.

This is the runtime half, and it decides nothing. *Where* a bridge or a tunnel
belongs -- which is a question about the terrain the road crosses -- is
authoring, and lives in ``OpenGLContext_editor.world.structures``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import numpy as np

from OpenGLContext.loaders.gltf.meshes import estimate_normals
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.road import RoadProfile, sweep_frames

__all__ = [
    'BridgeProfile', 'CausewayProfile', 'TunnelProfile',
    'bridge_meshes', 'causeway_meshes', 'tunnel_meshes',
    'concrete_material', 'barrier_material',
]

#: Structural concrete: grey, entirely rough, and not a metal. Weathered rather
#: than fresh -- a bridge in a landscape has been there a while, and fresh
#: concrete under a strong sun reads as a whitewashed wall rather than as
#: structure.
CONCRETE_ALBEDO = (0.30, 0.295, 0.285)
CONCRETE_ROUGHNESS = 0.85

#: A parapet is the thing closest to the camera for the whole length of a
#: viaduct, so it is a *barrier* rather than more structure: darker, and a
#: little glossier, the way galvanised steel and traffic-stained concrete are.
BARRIER_ALBEDO = (0.17, 0.175, 0.18)
BARRIER_ROUGHNESS = 0.6

HeightFn = Callable[[Any, Any], Any]


@dataclass
class BridgeProfile:
    """The shape of a deck and what holds it up, in metres.

    ``deck_depth`` is how far the soffit hangs below the road it carries -- the
    structural depth of the girder. ``parapet_height`` and ``parapet_width``
    are the barrier standing on each edge. ``pier_spacing`` is how far apart the
    supports are; ``pier_width`` is across the road and ``pier_length`` along
    it, so a pier is a blade standing square to the deck. ``abutment_width``
    widens the end supports, which carry the deck onto the ground.

    A pier shorter than ``minimum_pier`` is left out, and so is one the ground
    has risen past: a deck running into a hillside meets the ground before the
    soffit does, and a support built there is a block of concrete standing
    across the carriageway.
    """

    deck_depth: float = 1.8
    parapet_height: float = 0.95
    parapet_width: float = 0.28
    pier_spacing: float = 45.0
    pier_width: float = 4.5
    pier_length: float = 2.2
    abutment_width: float = 2.0
    minimum_pier: float = 2.5


@dataclass
class CausewayProfile:
    """The shape of an embankment carried at the width of its road, in metres.

    ``wall_height`` is the wall standing on each edge and ``wall_width`` how
    thick it is. The wall is deliberately low: a causeway is built to cross
    something worth seeing, and one walled to windscreen height turns the
    crossing into a corridor.

    ``batter`` is how far the fill leans out per metre of its depth. A real
    embankment is battered to the angle its material stands at, which for
    anything deep is a slope the width of a field; a causeway is a *retained*
    structure and stands very nearly vertical, so the ground either side is left
    as it was found.

    ``lip`` is how deep the fill is where the road meets the land, so the wall
    always has something under it, and ``embedment`` how far the foot is sunk
    into the ground so no seam of daylight shows along the bottom.
    """

    wall_height: float = 0.8
    wall_width: float = 0.3
    batter: float = 0.09
    lip: float = 0.35
    embedment: float = 0.3


@dataclass
class TunnelProfile:
    """The shape of a bore and its portals, in metres.

    ``clearance`` is the height of the crown above the carriageway and
    ``margin`` how far the springing sits outside the road's total width, which
    together give the arch its radius. ``segments`` is how many facets the arch
    is drawn with.

    ``springing`` is how far below the carriageway the arch's feet sit, and
    ``floor`` closes the lining across the bottom. Both are about what is *not*
    there: the ground a bore runs through has to be cut away for the carriageway
    to pass, so the lining is all there is under the road. An arch springing at
    the crown of the road leaves a slot beside the shoulders to look out
    through, and one open underneath leaves a trench beside it for a wheel to
    drop into.

    ``portal_border`` is how far the portal's face stands out around the arch
    where the bore meets the hillside.

    ``daylight`` is how far into the bore the light from a portal reaches, in
    metres, and ``gloom`` how much of the lining's colour is left past that. A
    bore lit like an open hillside is a concrete tube in daylight; the shade is
    carried on the lining's own vertices, so no light source is involved and a
    driver goes into the dark and comes out the far end.
    """

    clearance: float = 7.5
    margin: float = 0.35
    springing: float = 0.6
    floor: bool = True
    segments: int = 14
    portal_border: float = 1.6
    daylight: float = 55.0
    gloom: float = 0.14


def concrete_material() -> PBRMaterial:
    """The material bridges and tunnels are built from."""
    return PBRMaterial(baseColor=CONCRETE_ALBEDO, metallic=0.0,
                       roughness=CONCRETE_ROUGHNESS, doubleSided=False)


def barrier_material() -> PBRMaterial:
    """What a parapet is made of: darker than the deck it stands on."""
    return PBRMaterial(baseColor=BARRIER_ALBEDO, metallic=0.0,
                       roughness=BARRIER_ROUGHNESS, doubleSided=False)


def bridge_meshes(points: Any, profile: Optional[RoadProfile] = None,
                  ground: Optional[HeightFn] = None,
                  bridge: Optional[BridgeProfile] = None,
                  material: Optional[PBRMaterial] = None,
                  barrier: Optional[PBRMaterial] = None,
                  ) -> Dict[str, PBRMesh]:
    """A deck, its parapets and its piers, along a stretch of centreline.

    ``points`` is (N,3) at the height the *road surface* runs at -- the same
    line the carriageway is swept along, so the deck arrives directly beneath
    it and the two need no reconciling. ``ground`` is the height of the
    undisturbed land, which is where the piers stop; without it the piers are
    left out and only the deck is built, which is what a caller wants when the
    land under the span is not its business.

    ``material`` is the structure and ``barrier`` the parapets, which are a
    different thing standing on it; giving only ``material`` puts everything in
    it, which is what a caller with one material of its own means.
    """
    line = _line(points, "a bridge")
    profile = profile or RoadProfile()
    bridge = bridge or BridgeProfile()
    rail_material = (barrier if barrier is not None
                     else material if material is not None
                     else barrier_material())
    material = material if material is not None else concrete_material()
    right, up = sweep_frames(line)
    # Built to the road as it runs *over* a deck rather than as it runs on the
    # ground: an edge beam rather than a verge falling away to ground that is
    # not there. The carriageway over the deck is swept with the same section,
    # so the two meet along their whole length and the deck is the width of the
    # road on it rather than the width of its grass.
    carried = profile.on_structure()
    half = carried.total_width / 2.0
    edge = float(carried.section()[0, 1])

    parts: Dict[str, PBRMesh] = {}
    # The deck: down the near fascia, along the soffit, up the far one. Left
    # open at the top, where the carriageway closes it.
    soffit = edge - bridge.deck_depth
    parts['deck'] = _swept(line, right, up, material,
                           [(-half, edge), (-half, soffit),
                            (half, soffit), (half, edge)], closed_ends=True)
    parts['parapet'] = _parapet(line, right, up, rail_material, half, edge,
                                bridge.parapet_height, bridge.parapet_width)
    if ground is not None:
        piers = _piers(line, right, up, ground, bridge, half, soffit, material)
        if piers is not None:
            parts['piers'] = piers
    return parts


def causeway_meshes(points: Any, profile: Optional[RoadProfile] = None,
                    ground: Optional[HeightFn] = None,
                    causeway: Optional[CausewayProfile] = None,
                    material: Optional[PBRMaterial] = None,
                    barrier: Optional[PBRMaterial] = None,
                    ) -> Dict[str, PBRMesh]:
    """The fill under a causeway and the low wall along each edge.

    ``points`` is (N,3) at the height the road surface runs at. ``ground`` is
    the land the fill stands on, and is what the body is built down to; without
    it there is nothing to build a body against and only the wall is returned,
    which is what a caller drawing the crossing over its own terrain wants.

    The body is the width of the road *as carried* -- the same cut a deck gets,
    so the verge does not hang over the edge -- leaning out by the profile's
    batter as it goes down. It is open at the top, where the carriageway
    closes it.
    """
    line = _line(points, "a causeway")
    profile = profile or RoadProfile()
    causeway = causeway or CausewayProfile()
    rail_material = (barrier if barrier is not None
                     else material if material is not None
                     else barrier_material())
    material = material if material is not None else concrete_material()
    right, up = sweep_frames(line)
    carried = profile.on_structure()
    half = carried.total_width / 2.0
    edge = float(carried.section()[0, 1])

    parts: Dict[str, PBRMesh] = {
        'wall': _parapet(line, right, up, rail_material, half, edge,
                         causeway.wall_height, causeway.wall_width)}
    if ground is not None:
        parts['body'] = _fill(line, right, up, ground, causeway, half, edge,
                              material)
    return parts


def tunnel_meshes(points: Any, profile: Optional[RoadProfile] = None,
                  tunnel: Optional[TunnelProfile] = None,
                  material: Optional[PBRMaterial] = None,
                  ) -> Dict[str, PBRMesh]:
    """A bore and its two portals, along a stretch of centreline.

    ``points`` is (N,3) at the height the road surface runs at. The lining
    faces inwards, because the only place it is seen from is the carriageway
    inside it.
    """
    line = _line(points, "a tunnel")
    profile = profile or RoadProfile()
    tunnel = tunnel or TunnelProfile()
    material = material if material is not None else concrete_material()
    right, up = sweep_frames(line)
    # Built to the road as it runs *through* a bore rather than as it runs on
    # the ground: the grass verge is an edge beam in there, and a bore sized for
    # the verge would be metres wider than anything needs.
    half = profile.on_structure().total_width / 2.0 + tunnel.margin
    arch = _arch(half, tunnel.clearance, tunnel.segments,
                 foot=tunnel.springing, floor=tunnel.floor)
    outer = _arch(half + tunnel.portal_border,
                  tunnel.clearance + tunnel.portal_border, tunnel.segments,
                  foot=tunnel.springing + tunnel.portal_border,
                  floor=tunnel.floor)
    # Reversed, so the sweep's triangles wind the other way and the lining is
    # lit and drawn from the carriageway side.
    bore = _swept(line, right, up, material, list(reversed(arch)),
                  shade=_gloom(line, tunnel, len(arch)))
    portals = _merge([_ring(line[at], right[at], up[at], arch, outer, material,
                            outwards=facing)
                      for at, facing in ((0, -1.0), (len(line) - 1, 1.0))],
                     material)
    return {'bore': bore, 'portals': portals}


def _parapet(line: np.ndarray, right: np.ndarray, up: np.ndarray,
             material: PBRMaterial, half: float, edge: float,
             height: float, width: float) -> PBRMesh:
    """A wall standing on each edge of the road, along its whole length."""
    inner = half - width
    top = edge + height
    return _merge([
        _swept(line, right, up, material,
               [(side * half, edge), (side * half, top),
                (side * inner, top), (side * inner, edge)], closed_ends=True)
        for side in (-1.0, 1.0)], material)


def _fill(line: np.ndarray, right: np.ndarray, up: np.ndarray,
          ground: HeightFn, causeway: CausewayProfile, half: float,
          edge: float, material: PBRMaterial) -> PBRMesh:
    """The body of a causeway: down one face, under the road, up the other.

    The section is not constant, because the depth is not: each point is taken
    down to whatever the land is doing beneath it, and leans out with that
    depth. So the sweep is built row by row rather than from one profile.
    """
    depth = np.maximum(
        line[:, 1] + edge + causeway.embedment
        - np.asarray(ground(line[:, 0], line[:, 2]), dtype='d').ravel(),
        causeway.lip)
    out = half + causeway.batter * depth
    #: Left top, left foot, right foot, right top -- open where the road closes it.
    lateral = np.stack([np.full(len(line), -half), -out, out,
                        np.full(len(line), half)], axis=-1)
    vertical = np.stack([np.full(len(line), edge), edge - depth,
                         edge - depth, np.full(len(line), edge)], axis=-1)
    positions = (line[:, None, :] + right[:, None, :] * lateral[:, :, None]
                 + up[:, None, :] * vertical[:, :, None]).reshape(-1, 3)
    indices = np.concatenate([
        _strip(len(line), 4),
        _cap(np.arange(4), flip=True),
        _cap(np.arange(4) + (len(line) - 1) * 4, flip=False)])
    return _mesh(positions, indices, material)


def _line(points: Any, what: str) -> np.ndarray:
    line = np.asarray(points, dtype='d').reshape(-1, 3)
    if len(line) < 2:
        raise ValueError("%s needs a centreline of at least two points" % (what,))
    return line


def _swept(line: np.ndarray, right: np.ndarray, up: np.ndarray,
           material: PBRMaterial, section: Any,
           closed_ends: bool = False,
           shade: Optional[np.ndarray] = None) -> PBRMesh:
    """Sweep a (K,2) lateral/vertical section along a framed centreline.

    ``shade`` is an optional per-point brightness the whole ring takes, which is
    how a bore carries its own darkness.
    """
    section = np.asarray(section, dtype='d').reshape(-1, 2)
    ring = len(section)
    lateral = section[:, 0][None, :, None]
    vertical = section[:, 1][None, :, None]
    positions = (line[:, None, :] + right[:, None, :] * lateral
                 + up[:, None, :] * vertical).reshape(-1, 3)
    indices = _strip(len(line), ring)
    if closed_ends:
        indices = np.concatenate([
            indices,
            _cap(np.arange(ring), flip=True),
            _cap(np.arange(ring) + (len(line) - 1) * ring, flip=False)])
    colors = None
    if shade is not None:
        colors = np.ones((len(line) * ring, 4), dtype='f')
        colors[:, :3] = np.repeat(shade, ring)[:, None]
    return _mesh(positions, indices, material, colors=colors)


def _strip(rows: int, ring: int) -> np.ndarray:
    """Triangles joining consecutive rings of a sweep."""
    row = np.arange(rows - 1)[:, None] * ring
    column = np.arange(ring - 1)[None, :]
    a = (row + column).ravel()
    b, c = a + 1, a + ring
    d = c + 1
    return np.stack([a, b, c, b, d, c], axis=-1).ravel().astype(np.uint32)


def _cap(loop: np.ndarray, flip: bool) -> np.ndarray:
    """A fan closing one end of a sweep, over a section of three or more."""
    if len(loop) < 3:                            # pragma: no cover - degenerate
        return np.zeros(0, dtype=np.uint32)
    fan = np.stack([np.full(len(loop) - 2, loop[0]), loop[1:-1], loop[2:]],
                   axis=-1)
    if flip:
        fan = fan[:, ::-1]
    return fan.ravel().astype(np.uint32)


def _arch(half_width: float, clearance: float, segments: int,
          foot: float = 0.0, floor: bool = False) -> list:
    """A bore's section: up one springing, over the crown, down the other.

    A half-ellipse of ``half_width`` by ``clearance``, which gives a bore that
    is as wide as it needs at the road and as tall as it needs at the crown
    without either dimension driving the other, with ``foot`` of straight wall
    under each springing so the lining meets the carriageway rather than
    stopping at it, and ``floor`` closing it across the bottom.
    """
    angle = np.linspace(np.pi, 0.0, max(int(segments), 3) + 1)
    curve = [(float(half_width * np.cos(t)), float(clearance * np.sin(t)))
             for t in angle]
    if foot <= 0.0:
        return curve
    walled = [(-half_width, -foot)] + curve + [(half_width, -foot)]
    # Closed by returning to where it started, which makes the sweep a tube
    # rather than a vault.
    return walled + [walled[0]] if floor else walled


def _ring(centre: np.ndarray, right: np.ndarray, up: np.ndarray,
          inner: list, outer: list, material: PBRMaterial,
          outwards: float) -> PBRMesh:
    """A flat band between two sections, standing square across the road.

    The portal's face: the hillside side of the bore, wide enough around the
    arch to read as a headwall rather than as the cut edge of a hole.
    """
    def place(section: list) -> np.ndarray:
        lateral = np.asarray([p[0] for p in section])[:, None]
        vertical = np.asarray([p[1] for p in section])[:, None]
        placed: np.ndarray = (centre[None, :] + right[None, :] * lateral
                              + up[None, :] * vertical)
        return placed

    positions = np.concatenate([place(inner), place(outer)])
    count = len(inner)
    a = np.arange(count - 1)
    b, c = a + 1, a + count
    d = c + 1
    quads = (np.stack([a, c, b, b, c, d], axis=-1) if outwards > 0
             else np.stack([a, b, c, b, d, c], axis=-1))
    return _mesh(positions, quads.ravel().astype(np.uint32), material)


def _piers(line: np.ndarray, right: np.ndarray, up: np.ndarray,
           ground: HeightFn, bridge: BridgeProfile, half: float,
           soffit: float, material: PBRMaterial) -> Optional[PBRMesh]:
    """A blade of concrete every ``pier_spacing`` from the soffit to the ground.

    The two ends are abutments -- wider, because that is where the deck is
    carried onto the land, and kept however short they are. Between them a pier
    is placed at each interval and dropped to whatever the ground is doing
    beneath it, so a span over a sloping valley has piers of the lengths that
    valley calls for.

    Nothing at all is built where the ground has come up past the soffit: a deck
    landing into a hillside is carried by the hill, and the alternative is a
    block standing in the road.
    """
    steps = np.linalg.norm(np.diff(line, axis=0), axis=1)
    station = np.concatenate([[0.0], np.cumsum(steps)])
    length = float(station[-1])
    wanted = list(np.arange(bridge.pier_spacing, length, bridge.pier_spacing))
    at = np.searchsorted(station, [0.0] + wanted + [length])
    at = np.unique(np.clip(at, 0, len(line) - 1))

    blades = []
    for index in at:
        ends = index in (0, len(line) - 1)
        width = bridge.pier_width + (bridge.abutment_width if ends else 0.0)
        top = float(line[index, 1] + soffit)
        floor = float(np.asarray(ground(np.array([line[index, 0]]),
                                        np.array([line[index, 2]]))).ravel()[0])
        standing = top - floor
        if standing <= 0.0 or (not ends and standing < bridge.minimum_pier):
            continue
        blades.append(_blade(line[index], right[index], up[index],
                             min(width, half * 2.0), bridge.pier_length,
                             top, floor, material))
    if not blades:
        return None
    return _merge(blades, material)


def _blade(centre: np.ndarray, right: np.ndarray, up: np.ndarray,
           width: float, length: float, top: float, floor: float,
           material: PBRMaterial) -> PBRMesh:
    """One pier: a box across the road, from the soffit down to the ground."""
    along = np.cross(right, (0.0, 1.0, 0.0))
    norm = float(np.linalg.norm(along))
    along = along / norm if norm > 1e-9 else np.array([0.0, 0.0, 1.0])
    half_w, half_l = width / 2.0, length / 2.0
    corners = [(-half_w, -half_l), (half_w, -half_l),
               (half_w, half_l), (-half_w, half_l)]
    plan = np.array([centre + right * u + along * v for u, v in corners])
    upper = plan.copy()
    upper[:, 1] = top
    lower = plan.copy()
    lower[:, 1] = floor
    positions = np.concatenate([upper, lower])
    sides = []
    for i in range(4):
        j = (i + 1) % 4
        sides += [i, j, i + 4, j, j + 4, i + 4]
    sides += [0, 2, 1, 0, 3, 2]                  # the top, closing the box
    sides += [4, 5, 6, 4, 6, 7]                  # and the foot
    return _mesh(positions, np.asarray(sides, dtype=np.uint32), material)


def _merge(meshes: list, material: PBRMaterial) -> PBRMesh:
    """Several parts of one structure as a single mesh."""
    positions, indices, offset = [], [], 0
    for mesh in meshes:
        positions.append(mesh.positions)
        indices.append(np.asarray(mesh.indices) + offset)
        offset += len(mesh.positions)
    return _mesh(np.concatenate(positions),
                 np.concatenate(indices).astype(np.uint32), material)


def _gloom(line: np.ndarray, tunnel: TunnelProfile, ring: int) -> np.ndarray:
    """How bright the lining is at each point along a bore.

    Full daylight at either portal, falling to ``gloom`` ``daylight`` metres in.
    A bore shorter than twice that never goes fully dark, because the light from
    each end meets in the middle -- which is what a short one looks like.
    """
    steps = np.linalg.norm(np.diff(line, axis=0), axis=1)
    station = np.concatenate([[0.0], np.cumsum(steps)])
    from_end = np.minimum(station, station[-1] - station)
    reach = max(float(tunnel.daylight), 1e-6)
    lit = np.clip(1.0 - from_end / reach, 0.0, 1.0)
    return np.asarray(tunnel.gloom + (1.0 - tunnel.gloom) * lit, dtype='d')


def _mesh(positions: np.ndarray, indices: np.ndarray,
          material: PBRMaterial, colors: Optional[np.ndarray] = None) -> PBRMesh:
    points = np.ascontiguousarray(positions, dtype='f')
    return PBRMesh(positions=points, normals=estimate_normals(points, indices),
                   indices=indices, material=material, colors=colors)
