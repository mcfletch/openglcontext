"""Where a zone applies: shape distances, object classification and layering.

A zone is a region of space carrying settings that hold inside it: dimmer
image-based lighting in a room, birdsong in a forest, a reverb in a tunnel.
This module holds the arithmetic of zones with no GL and no scenegraph in it,
so all of it can be tested directly; :mod:`OpenGLContext.scenegraph.zone` is
the node a scene carries, and ``docs/zones.rst`` is the guide.

A zone's region is one of the implicit shapes glTF defines (a ``box``,
``sphere``, ``capsule`` or ``cylinder``, all centred on the origin with
their round axis along +Y) placed by a world matrix. :func:`place` turns a
shape and a matrix into a :class:`PlacedShape`: a rigid frame and the shape's
dimensions in metres, with the matrix's scale folded into the dimensions, so
every distance measured against it is in world metres.

Three questions are asked of a placed shape:

* How far a point is from it (:meth:`PlacedShape.distance`), negative inside.
  These are exact signed distances for every shape but the ellipsoid a sphere
  becomes under a non-uniform scale, which uses the usual close approximation.
* How much a point is inside it (:func:`weight`): one on and inside the
  surface, falling smoothly to nought ``blend`` metres outside it.
* Whether a box lies wholly inside it, wholly clear of it and its blend band,
  or across its surface (:meth:`PlacedShape.classify`). The PBR pass asks
  this once per draw, so only an object crossing a zone's surface pays for a
  per-fragment weight.

Where zones overlap, each setting is layered on its own (:func:`layers`):
zones are ordered by ``priority``, with ties going to the smaller shape, and
each is laid over the ones below it by its weight. A zone fully inside a
higher-priority one is hidden by it, and at a boundary one fades into the
other over the blend distance.

Matrices are row-vector, as the engine's are: ``point @ matrix``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import (Any, Dict, Hashable, Iterable, List, Mapping, Optional,
                    Sequence, Tuple)

import numpy as np
from numpy.typing import ArrayLike

__all__ = [
    'BOX', 'SPHERE', 'CAPSULE', 'CYLINDER', 'ELLIPSOID', 'SHAPES',
    'OUTSIDE', 'INSIDE', 'STRADDLES', 'ShapeSpec', 'PlacedShape', 'place',
    'weight', 'weights', 'Layer', 'layers', 'shares', 'named_shares',
    'shader_kind',
]

BOX = 'box'
SPHERE = 'sphere'
CAPSULE = 'capsule'
CYLINDER = 'cylinder'
#: What a sphere becomes under a scale that differs between its axes.
ELLIPSOID = 'ellipsoid'
#: The shape types a zone may use, as glTF names them.
SHAPES = (BOX, SPHERE, CAPSULE, CYLINDER)

#: What :meth:`PlacedShape.classify` answers.
OUTSIDE = 'outside'
INSIDE = 'inside'
STRADDLES = 'straddles'

#: The integer each shape is to ``_zone_inc.glsl``.
_SHADER_KIND = {BOX: 1, SPHERE: 2, ELLIPSOID: 3, CAPSULE: 4, CYLINDER: 5}


def shader_kind(kind: str) -> int:
    """The number ``_zone_inc.glsl`` knows a shape type by."""
    return _SHADER_KIND[kind]


@dataclass(frozen=True)
class ShapeSpec:
    """One implicit shape, as a glTF document declares it.

    ``size`` is a box's full extent along x, y and z. ``radius`` is a
    sphere's. A capsule's ``height`` is the distance between the centres of
    its two hemispheres and a cylinder's is its length, both along +Y, with
    ``radius_top`` and ``radius_bottom`` the radii at each end.
    """

    kind: str
    size: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    radius: float = 0.5
    height: float = 0.5
    radius_top: float = 0.25
    radius_bottom: float = 0.25

    def __post_init__(self) -> None:
        if self.kind not in SHAPES:
            raise ValueError('a zone shape is one of %s, not %r'
                             % (', '.join(SHAPES), self.kind))


@dataclass(frozen=True)
class PlacedShape:
    """A shape in the world: a rigid frame and dimensions in metres.

    ``to_local`` takes a world point into the shape's own frame, where it is
    centred on the origin with its round axis along +Y. ``params`` are the
    dimensions that frame measures in, by kind:

    * box: half extents along x, y and z;
    * sphere: radius;
    * ellipsoid: radii along x, y and z;
    * capsule: radius at the bottom, radius at the top, and the distance
      between the hemispheres' centres;
    * cylinder: radius at the bottom, radius at the top, and the length.
    """

    kind: str
    to_local: np.ndarray
    params: Tuple[float, ...]
    #: The frame's translation: where the shape's centre is in the world.
    centre: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: Half extents of a box that encloses the shape in its own frame.
    reach: Tuple[float, float, float] = (0.0, 0.0, 0.0)

    @property
    def volume(self) -> float:
        """The shape's volume in cubic metres, which breaks priority ties."""
        p = self.params
        if self.kind == BOX:
            return 8.0 * p[0] * p[1] * p[2]
        if self.kind == SPHERE:
            return 4.0 / 3.0 * math.pi * p[0] ** 3
        if self.kind == ELLIPSOID:
            return 4.0 / 3.0 * math.pi * p[0] * p[1] * p[2]
        r1, r2, h = p
        frustum = math.pi * h / 3.0 * (r1 * r1 + r1 * r2 + r2 * r2)
        if self.kind == CAPSULE:
            return frustum + 2.0 / 3.0 * math.pi * (r1 ** 3 + r2 ** 3)
        return frustum

    def local(self, points: ArrayLike) -> np.ndarray:
        """World points ``(..., 3)`` in the shape's own frame."""
        pts = np.asarray(points, dtype='d')
        return pts @ self.to_local[:3, :3] + self.to_local[3, :3]

    def distance(self, points: ArrayLike) -> np.ndarray:
        """Signed distance in metres from each world point to the surface.

        Negative inside. ``points`` is ``(..., 3)`` and so is the answer's
        shape less its last axis.
        """
        return _distance(self.kind, self.params, self.local(points))

    def classify(self, minimum: ArrayLike, maximum: ArrayLike,
                 blend: float = 0.0) -> str:
        """Where a world box stands against this shape and its blend band.

        :data:`INSIDE` when every corner is inside the shape: every shape a
        zone uses is convex, so the whole box is then inside too.
        :data:`OUTSIDE` when the box, taken into the shape's frame, does not
        reach the band ``blend`` metres round the shape's enclosing box. That
        test is conservative: a box near a round shape's corner is called
        :data:`STRADDLES` though it stays clear, and its fragments are then
        weighted nought, which is the right answer arrived at the long way.
        """
        corners = _corners(minimum, maximum)
        local = self.local(corners)
        low, high = local.min(axis=0), local.max(axis=0)
        reach = np.asarray(self.reach, dtype='d') + max(float(blend), 0.0)
        if np.any(low > reach) or np.any(high < -reach):
            return OUTSIDE
        if np.all(_distance(self.kind, self.params, local) <= 0.0):
            return INSIDE
        return STRADDLES


def place(shape: ShapeSpec, matrix: Optional[ArrayLike] = None) -> PlacedShape:
    """``shape`` put in the world by the row-vector ``matrix``.

    The matrix's scale along each of its local axes is folded into the
    dimensions, so the frame left is rigid and distances measured in it are
    metres. A box scales exactly. A sphere scaled unevenly becomes an
    ellipsoid. A capsule or cylinder takes its length from the scale along
    +Y and its radii from the mean of the other two, since an elliptical
    section is not one of the shapes; a zone meant to be flattened is best
    authored as a box.

    Shear has no place in a zone's frame and is dropped with the scale.
    """
    m = np.identity(4) if matrix is None else np.asarray(matrix, dtype='d')
    axes = m[:3, :3]
    scale = np.linalg.norm(axes, axis=1)
    scale = np.where(scale > 1e-12, scale, 1.0)
    rotation = _orthonormal(axes / scale[:, None])
    origin = m[3, :3]
    to_world = np.identity(4)
    to_world[:3, :3] = rotation
    to_world[3, :3] = origin
    to_local = np.identity(4)
    to_local[:3, :3] = rotation.T
    to_local[3, :3] = -origin @ rotation.T
    kind = shape.kind
    params: Tuple[float, ...]
    if kind == BOX:
        half = np.abs(np.asarray(shape.size, dtype='d')) * scale / 2.0
        params = tuple(float(v) for v in half)
        reach = params
    elif kind == SPHERE:
        radii = abs(float(shape.radius)) * scale
        if np.allclose(radii, radii[0], rtol=1e-6):
            kind, params = SPHERE, (float(radii[0]),)
        else:
            kind, params = ELLIPSOID, tuple(float(v) for v in radii)
        reach = tuple(float(v) for v in radii)
    else:
        across = float((scale[0] + scale[2]) / 2.0)
        r1 = abs(float(shape.radius_bottom)) * across
        r2 = abs(float(shape.radius_top)) * across
        h = abs(float(shape.height)) * float(scale[1])
        params = (r1, r2, h)
        widest = max(r1, r2)
        tall = h / 2.0 + (widest if kind == CAPSULE else 0.0)
        reach = (widest, tall, widest)
    return PlacedShape(kind, to_local, params,
                       tuple(float(v) for v in origin),   # type: ignore[arg-type]
                       tuple(float(v) for v in reach))    # type: ignore[arg-type]


def weight(distance: ArrayLike, blend: float) -> np.ndarray:
    """How much a point at ``distance`` from a zone's surface is inside it.

    One on and inside the surface, nought ``blend`` metres out and beyond,
    and a smoothstep between, which is what ``_zone_inc.glsl`` computes per
    fragment. With no blend the edge is hard.
    """
    d = np.asarray(distance, dtype='d')
    if blend <= 0.0:
        return np.where(d <= 0.0, 1.0, 0.0)
    t = np.clip(d / float(blend), 0.0, 1.0)
    return 1.0 - t * t * (3.0 - 2.0 * t)


def weights(shape: PlacedShape, points: ArrayLike, blend: float) -> np.ndarray:
    """:func:`weight` for each world point against ``shape``."""
    return weight(shape.distance(points), blend)


@dataclass(frozen=True)
class Layer:
    """One zone's say on one setting, at one place.

    ``key`` identifies the zone to the caller and ``block`` is what the zone
    says for the setting, ``None`` where it switches the setting off.
    ``weight`` is how much the place is inside the zone, and ``share`` how
    much of the setting it decides once the zones above it have taken
    theirs: the shares of all the layers, and what is left for the world
    outside every zone, add up to one.
    """

    key: Hashable
    block: Any
    weight: float
    share: float
    priority: int = 0
    volume: float = 0.0


@dataclass
class _Candidate:
    key: Hashable
    block: Any
    weight: float
    priority: int
    volume: float
    order: int


def layers(candidates: Iterable[Tuple[Hashable, Any, float, int, float]]
           ) -> List[Layer]:
    """The zones deciding one setting, bottom first, each with its share.

    Each candidate is ``(key, block, weight, priority, volume)``. The zones
    are stacked by priority, and within one priority the larger zone goes
    below the smaller, which is the more specific. Candidates of equal
    priority and volume keep the order they came in. Each layer is laid over
    the ones below by its weight, so its share is its weight times what the
    layers above leave: a zone wholly inside a higher-priority one keeps
    nothing, and at the edge of the higher one the two cross-fade.

    Candidates of weight nought are left out.
    """
    stack = [_Candidate(key, block, float(w), int(priority), float(volume), order)
             for order, (key, block, w, priority, volume) in enumerate(candidates)
             if w > 0.0]
    stack.sort(key=lambda c: (c.priority, -c.volume, c.order))
    result: List[Layer] = []
    left = 1.0
    for candidate in reversed(stack):
        share = candidate.weight * left
        left -= share
        result.append(Layer(candidate.key, candidate.block, candidate.weight,
                            share, candidate.priority, candidate.volume))
    result.reverse()
    return result


def shares(stack: Sequence[Layer]) -> Dict[Hashable, float]:
    """Each zone's share of a setting, by key, from :func:`layers`."""
    found: Dict[Hashable, float] = {}
    for layer in stack:
        found[layer.key] = found.get(layer.key, 0.0) + layer.share
    return found


def named_shares(stack: Sequence[Layer], names: Mapping[Hashable, Iterable[Hashable]]
                 ) -> Dict[Hashable, float]:
    """How much each named thing is switched on, from a stack of layers.

    ``names`` gives, for each zone key, the things its block switches on --
    light nodes, emitters, nodes to show. A thing's share is the sum of the
    shares of the layers naming it, at most one. A layer that names nothing,
    or switches the setting off, takes its share from everything below it and
    gives it to nothing.
    """
    found: Dict[Hashable, float] = {}
    for layer in stack:
        if layer.block is None:
            continue
        for name in names.get(layer.key, ()):
            found[name] = min(1.0, found.get(name, 0.0) + layer.share)
    return found


# --------------------------------------------------------------------------
# Signed distances, in a shape's own frame
# --------------------------------------------------------------------------

def _distance(kind: str, params: Sequence[float], p: np.ndarray) -> np.ndarray:
    if kind == BOX:
        return _box(p, np.asarray(params, dtype='d'))
    if kind == SPHERE:
        return np.linalg.norm(p, axis=-1) - params[0]
    if kind == ELLIPSOID:
        return _ellipsoid(p, np.asarray(params, dtype='d'))
    r1, r2, h = params
    if kind == CAPSULE:
        return _round_cone(p, r1, r2, h)
    return _capped_cone(p, r1, r2, h)


def _box(p: np.ndarray, half: np.ndarray) -> np.ndarray:
    q = np.abs(p) - half
    outside = np.linalg.norm(np.maximum(q, 0.0), axis=-1)
    inside = np.minimum(q.max(axis=-1), 0.0)
    return outside + inside


def _ellipsoid(p: np.ndarray, radii: np.ndarray) -> np.ndarray:
    k0 = np.linalg.norm(p / radii, axis=-1)
    k1 = np.linalg.norm(p / (radii * radii), axis=-1)
    safe = np.where(k1 > 1e-12, k1, 1.0)
    return np.where(k1 > 1e-12, k0 * (k0 - 1.0) / safe, -float(radii.min()))


def _round_cone(p: np.ndarray, r1: float, r2: float, h: float) -> np.ndarray:
    """A capsule whose ends may differ: spheres of ``r1`` and ``r2`` ``h`` apart."""
    across = np.hypot(p[..., 0], p[..., 2])
    up = p[..., 1] + h / 2.0
    if h <= 1e-12:
        return np.hypot(across, up) - max(r1, r2)
    b = (r1 - r2) / h
    if abs(b) >= 1.0:
        # One sphere swallows the other: the shape is the larger sphere.
        centre = 0.0 if r1 >= r2 else h
        return np.hypot(across, up - centre) - max(r1, r2)
    a = math.sqrt(1.0 - b * b)
    k = -b * across + a * up
    lower = np.hypot(across, up) - r1
    upper = np.hypot(across, up - h) - r2
    side = across * a + up * b - r1
    return np.where(k < 0.0, lower, np.where(k > a * h, upper, side))


def _capped_cone(p: np.ndarray, r1: float, r2: float, h: float) -> np.ndarray:
    """A cylinder whose ends may differ: radius ``r1`` below, ``r2`` above."""
    half = h / 2.0
    qx = np.hypot(p[..., 0], p[..., 2])
    qy = p[..., 1]
    k1x, k1y = r2, half
    k2x, k2y = r2 - r1, 2.0 * half
    end = np.where(qy < 0.0, r1, r2)
    cax = qx - np.minimum(qx, end)
    cay = np.abs(qy) - half
    k2len = k2x * k2x + k2y * k2y
    t = np.clip(((k1x - qx) * k2x + (k1y - qy) * k2y) / max(k2len, 1e-12), 0.0, 1.0)
    cbx = qx - k1x + k2x * t
    cby = qy - k1y + k2y * t
    sign = np.where((cbx < 0.0) & (cay < 0.0), -1.0, 1.0)
    return sign * np.sqrt(np.minimum(cax * cax + cay * cay, cbx * cbx + cby * cby))


def _orthonormal(axes: np.ndarray) -> np.ndarray:
    """The nearest orthonormal frame to three unit rows, so shear cannot creep in.

    A mirroring frame stays a mirror: it measures distances as truly as a
    rotation does.
    """
    u, _s, vt = np.linalg.svd(axes)
    return u @ vt


#: Which end of each axis each of a box's eight corners takes.
_CORNER_ENDS = np.array([[bool(i & 4), bool(i & 2), bool(i & 1)] for i in range(8)])


def _corners(minimum: ArrayLike, maximum: ArrayLike) -> np.ndarray:
    low = np.asarray(minimum, dtype='d')[:3]
    high = np.asarray(maximum, dtype='d')[:3]
    return np.where(_CORNER_ENDS, high, low)
