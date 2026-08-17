"""Bridges and tunnels: what carries a road where the ground does not.

A road settled for grade and speed does not lie on the land everywhere it goes.
Where it runs high above the ground it is carried on a **deck** standing on
piers; where it runs inside the ground it passes through a **bore** with a
portal at each end. Both are built the way the carriageway is -- a cross-section
swept along the centreline, using the same per-point frame
(:mod:`OpenGLContext.scenegraph.road`) -- so a structure stays under or over its
road through a bend and a climb instead of drifting off it.

Give :func:`bridge_meshes` or :func:`tunnel_meshes` the stretch of centreline the
structure covers and the road profile it carries, and each returns its parts as
``{name: mesh}`` -- ``deck``, ``parapet`` and ``piers`` for a bridge, ``bore``
and ``portals`` for a tunnel. Naming the parts rather than merging them lets a
caller light, cull or write them separately; merging them is a concatenation
away.

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
    'BridgeProfile', 'TunnelProfile',
    'bridge_meshes', 'tunnel_meshes', 'concrete_material',
]

#: Structural concrete: pale, entirely rough, and not a metal. Weathered rather
#: than fresh, because a bridge in a landscape has been there a while.
CONCRETE_ALBEDO = (0.46, 0.45, 0.43)
CONCRETE_ROUGHNESS = 0.85

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

    A pier shorter than ``minimum_pier`` is left out: near an abutment the
    ground is already at the soffit, and a stub of concrete there reads as a
    fault rather than as structure.
    """

    deck_depth: float = 1.8
    parapet_height: float = 1.1
    parapet_width: float = 0.45
    pier_spacing: float = 45.0
    pier_width: float = 4.5
    pier_length: float = 2.2
    abutment_width: float = 2.0
    minimum_pier: float = 2.5


@dataclass
class TunnelProfile:
    """The shape of a bore and its portals, in metres.

    ``clearance`` is the height of the crown above the carriageway and
    ``margin`` how far the springing sits outside the road's total width, which
    together give the arch its radius. ``segments`` is how many facets the arch
    is drawn with.

    ``portal_border`` is how far the portal's face stands out around the arch
    where the bore meets the hillside.
    """

    clearance: float = 7.5
    margin: float = 1.0
    segments: int = 14
    portal_border: float = 1.6


def concrete_material() -> PBRMaterial:
    """The material bridges and tunnels are built from."""
    return PBRMaterial(baseColor=CONCRETE_ALBEDO, metallic=0.0,
                       roughness=CONCRETE_ROUGHNESS, doubleSided=False)


def bridge_meshes(points: Any, profile: Optional[RoadProfile] = None,
                  ground: Optional[HeightFn] = None,
                  bridge: Optional[BridgeProfile] = None,
                  material: Optional[PBRMaterial] = None,
                  ) -> Dict[str, PBRMesh]:
    """A deck, its parapets and its piers, along a stretch of centreline.

    ``points`` is (N,3) at the height the *road surface* runs at -- the same
    line the carriageway is swept along, so the deck arrives directly beneath
    it and the two need no reconciling. ``ground`` is the height of the
    undisturbed land, which is where the piers stop; without it the piers are
    left out and only the deck is built, which is what a caller wants when the
    land under the span is not its business.
    """
    line = _line(points, "a bridge")
    profile = profile or RoadProfile()
    bridge = bridge or BridgeProfile()
    material = material if material is not None else concrete_material()
    right, up = sweep_frames(line)
    half = profile.total_width / 2.0
    # A deck's top is a plane, so it is measured against the road as it runs
    # over a structure -- an edge beam rather than a verge falling away to
    # ground that is not there. The carriageway over the deck is swept with the
    # same section, and the two then meet along their whole length.
    edge = float(profile.on_structure().section()[0, 1])

    parts: Dict[str, PBRMesh] = {}
    # The deck: down the near fascia, along the soffit, up the far one. Left
    # open at the top, where the carriageway closes it.
    soffit = edge - bridge.deck_depth
    parts['deck'] = _swept(line, right, up, material,
                           [(-half, edge), (-half, soffit),
                            (half, soffit), (half, edge)], closed_ends=True)
    inner = half - bridge.parapet_width
    rail = edge + bridge.parapet_height
    parts['parapet'] = _merge([
        _swept(line, right, up, material,
               [(side * half, edge), (side * half, rail),
                (side * inner, rail), (side * inner, edge)], closed_ends=True)
        for side in (-1.0, 1.0)], material)
    if ground is not None:
        piers = _piers(line, right, up, ground, bridge, half, soffit, material)
        if piers is not None:
            parts['piers'] = piers
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
    arch = _arch(profile.total_width / 2.0 + tunnel.margin, tunnel.clearance,
                 tunnel.segments)
    outer = _arch(profile.total_width / 2.0 + tunnel.margin
                  + tunnel.portal_border,
                  tunnel.clearance + tunnel.portal_border, tunnel.segments)
    # Reversed, so the sweep's triangles wind the other way and the lining is
    # lit and drawn from the carriageway side.
    bore = _swept(line, right, up, material, list(reversed(arch)))
    portals = _merge([_ring(line[at], right[at], up[at], arch, outer, material,
                            outwards=facing)
                      for at, facing in ((0, -1.0), (len(line) - 1, 1.0))],
                     material)
    return {'bore': bore, 'portals': portals}


def _line(points: Any, what: str) -> np.ndarray:
    line = np.asarray(points, dtype='d').reshape(-1, 3)
    if len(line) < 2:
        raise ValueError("%s needs a centreline of at least two points" % (what,))
    return line


def _swept(line: np.ndarray, right: np.ndarray, up: np.ndarray,
           material: PBRMaterial, section: Any,
           closed_ends: bool = False) -> PBRMesh:
    """Sweep a (K,2) lateral/vertical section along a framed centreline."""
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
    return _mesh(positions, indices, material)


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


def _arch(half_width: float, clearance: float, segments: int) -> list:
    """A horseshoe section: up one springing, over the crown, down the other.

    A half-ellipse of ``half_width`` by ``clearance``, which gives a bore that
    is as wide as it needs at the road and as tall as it needs at the crown
    without either dimension driving the other.
    """
    angle = np.linspace(np.pi, 0.0, max(int(segments), 3) + 1)
    return [(float(half_width * np.cos(t)), float(clearance * np.sin(t)))
            for t in angle]


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

    The two ends are abutments -- wider, and always built, because that is where
    the deck is carried onto the land. Between them a pier is placed at each
    interval and dropped to whatever the ground is doing beneath it, so a span
    over a sloping valley has piers of the lengths that valley calls for.
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
        if not ends and top - floor < bridge.minimum_pier:
            continue
        blades.append(_blade(line[index], right[index], up[index],
                             min(width, half * 2.0), bridge.pier_length,
                             top, floor, material))
    if not blades:                               # pragma: no cover - all too short
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


def _mesh(positions: np.ndarray, indices: np.ndarray,
          material: PBRMaterial) -> PBRMesh:
    points = np.ascontiguousarray(positions, dtype='f')
    return PBRMesh(positions=points, normals=estimate_normals(points, indices),
                   indices=indices, material=material)
