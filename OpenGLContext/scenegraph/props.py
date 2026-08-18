"""Things standing in a world that something can run into.

A world has more in it than ground, road and trees: boulders on the verge, a
car that broke down, a fence, whatever a game puts in the way. What they have
in common is that they are *placed* -- a mesh and a body at one spot, neither of
which moves -- and that is the part an engine can own. :class:`Prop` is that:
what kind of thing it is, where it stands, which way it faces, and how much room
it takes up, so a viewer can draw it and a physics world can collide with it
without either having to look at the other's copy.

What each one *looks like* is art, and the toolkit ships none. The exception is
the kind a landscape supplies for free: :func:`rock_mesh` grows a boulder out of
a subdivided icosahedron, so a world can be strewn with stone without an asset
pipeline.

Where a prop belongs is authoring, and lives in
``OpenGLContext_editor.bake.props``; standing them up in a physics world is
:mod:`OpenGLContext.physics.props`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np

from OpenGLContext.loaders.gltf.meshes import estimate_normals
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = ['Prop', 'RockProfile', 'rock_mesh', 'rock_material']

#: Weathered granite: grey, faintly warm, entirely rough, and not a metal.
#: Dark, because a boulder is: a stone quoted at the reflectance of a paving slab
#: comes out white in sun and reads as a polystyrene prop.
ROCK_ALBEDO = (0.14, 0.135, 0.125)
ROCK_ROUGHNESS = 0.92


@dataclass
class RockProfile:
    """The shape of a boulder.

    ``roughness`` is how far a vertex may move from the sphere it started as,
    as a fraction of the radius; ``facets`` how many times the icosahedron is
    subdivided. ``settled`` is how much of the bottom is pressed into the
    ground: a boulder that has been lying there for a few thousand years is not
    a ball resting on a point.
    """

    roughness: float = 0.32
    facets: int = 2
    settled: float = 0.34


def rock_material() -> PBRMaterial:
    """What a boulder is made of."""
    return PBRMaterial(baseColor=ROCK_ALBEDO, metallic=0.0,
                       roughness=ROCK_ROUGHNESS, doubleSided=False)


def rock_mesh(radius: float = 1.0, seed: int = 0,
              profile: Optional[RockProfile] = None,
              material: Optional[PBRMaterial] = None) -> PBRMesh:
    """A boulder of about ``radius`` metres, with its base at y=0.

    A subdivided icosahedron with every vertex pushed in or out by a smooth
    function of where it is, then squashed and lifted so it sits on the ground
    rather than floating over it. ``seed`` picks which boulder; the same seed
    is always the same rock, so a world re-bakes to itself.
    """
    profile = profile or RockProfile()
    points, faces = _icosphere(max(int(profile.facets), 0))
    points = points * _lumps(points, seed, profile.roughness)
    points[:, 1] *= 1.0 - min(max(profile.settled, 0.0), 0.9)
    points *= float(radius)
    points[:, 1] -= float(points[:, 1].min())
    return _mesh(points, faces, material if material is not None
                 else rock_material())


@dataclass(frozen=True)
class Prop:
    """One placed thing: what it is, where it stands, and how much room it takes.

    ``position`` is where its base sits, ``yaw`` its rotation about the vertical
    in radians and ``scale`` a uniform multiplier on the prototype. ``radius``
    and ``height`` are what it occupies once placed, in metres -- the numbers a
    physics world needs to stand a body up without being handed the geometry,
    and the numbers a scatter needs to keep two of them out of each other.
    """

    kind: str
    position: Any
    yaw: float = 0.0
    scale: float = 1.0
    radius: float = 0.5
    height: float = 1.0

    def __repr__(self) -> str:
        return 'Prop(%s at %s)' % (
            self.kind, ', '.join('%.1f' % v for v in self.position))

    @classmethod
    def of(cls, mesh: PBRMesh, kind: str, position: Any, yaw: float = 0.0,
           scale: float = 1.0) -> 'Prop':
        """A prop measured from the mesh it is drawn as.

        The radius is taken across the widest of the two horizontal axes rather
        than as the diagonal: a body that encloses the mesh's corners is a body
        wider than anything a player can see, and a car stopping short of thin
        air is worse than one clipping a rock.
        """
        points = np.asarray(mesh.positions, dtype='d')
        wide = max(float(np.ptp(points[:, 0])), float(np.ptp(points[:, 2])))
        return cls(kind=kind, position=tuple(float(v) for v in position),
                   yaw=float(yaw), scale=float(scale),
                   radius=wide / 2.0 * float(scale),
                   height=float(np.ptp(points[:, 1])) * float(scale))

    def to_json(self) -> Dict[str, Any]:
        """This prop as a baked world carries it."""
        return {'kind': self.kind,
                'at': [round(float(v), 3) for v in self.position],
                'yaw': round(float(self.yaw), 4),
                'scale': round(float(self.scale), 4),
                'radius': round(float(self.radius), 4),
                'height': round(float(self.height), 4)}

    @classmethod
    def from_json(cls, record: Any) -> 'Prop':
        """A prop read back out of a baked world."""
        return cls(kind=record['kind'],
                   position=tuple(float(v) for v in record['at']),
                   yaw=float(record.get('yaw', 0.0)),
                   scale=float(record.get('scale', 1.0)),
                   radius=float(record.get('radius', 0.5)),
                   height=float(record.get('height', 1.0)))


#: The twelve vertices of an icosahedron, and the twenty faces over them.
_PHI = (1.0 + math.sqrt(5.0)) / 2.0
_CORNERS = np.array([
    (-1, _PHI, 0), (1, _PHI, 0), (-1, -_PHI, 0), (1, -_PHI, 0),
    (0, -1, _PHI), (0, 1, _PHI), (0, -1, -_PHI), (0, 1, -_PHI),
    (_PHI, 0, -1), (_PHI, 0, 1), (-_PHI, 0, -1), (-_PHI, 0, 1)], dtype='d')
_FACES = np.array([
    (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
    (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
    (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
    (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)], dtype=np.int64)


def _icosphere(facets: int) -> Tuple[np.ndarray, np.ndarray]:
    """A unit sphere as a subdivided icosahedron: even facets, no poles."""
    points = list(_CORNERS / np.linalg.norm(_CORNERS, axis=1, keepdims=True))
    faces = [tuple(face) for face in _FACES]
    for _round in range(facets):
        middles: Dict[Tuple[int, int], int] = {}
        split = []
        for a, b, c in faces:
            ab = _between(points, middles, a, b)
            bc = _between(points, middles, b, c)
            ca = _between(points, middles, c, a)
            split += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = split
    return np.asarray(points, dtype='d'), np.asarray(faces, dtype=np.uint32)


def _between(points: list, middles: Dict[Tuple[int, int], int],
             a: int, b: int) -> int:
    """The index of the point halfway along an edge, made once per edge.

    Kept by edge rather than per face, or the two faces sharing an edge each
    make their own copy of its midpoint and the sphere comes apart at every
    seam.
    """
    key = (min(a, b), max(a, b))
    if key not in middles:
        point = points[a] + points[b]
        points.append(point / np.linalg.norm(point))
        middles[key] = len(points) - 1
    return middles[key]


def _lumps(points: np.ndarray, seed: int, roughness: float) -> np.ndarray:
    """A smooth per-vertex multiplier on the radius, in (1-r, 1+r).

    A sum of a few sinusoids in the vertex's own direction: neighbouring
    vertices move together, so the result is a lumpy stone rather than a ball
    of noise, and it depends on the direction alone, so the seams of the
    subdivision close.
    """
    rng = np.random.default_rng(seed)
    total = np.zeros(len(points))
    weight = 0.0
    for octave in range(3):
        frequency = 1.7 ** octave * 2.1
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        phase = rng.random() * 2.0 * np.pi
        share = 0.55 ** octave
        total += np.sin(points @ axis * frequency + phase) * share
        weight += share
    return (1.0 + total / max(weight, 1e-9) * roughness)[:, None]


def _mesh(points: np.ndarray, faces: np.ndarray,
          material: PBRMaterial) -> PBRMesh:
    #: Flat-shaded: a boulder is facets, and smoothing them makes it a balloon.
    corners = np.ascontiguousarray(points[faces.ravel()], dtype='f')
    indices = np.arange(len(corners), dtype=np.uint32)
    return PBRMesh(positions=corners,
                   normals=estimate_normals(corners, indices),
                   indices=indices, material=material)

