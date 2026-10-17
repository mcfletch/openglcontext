"""Ground that is bare rock, meshed finely and drawn over the coarse terrain.

A landscape's height function says where the hills are. Where the ground is bare it is
rock, and rock is not a hillside seen close: it is a block with faces scraped flat and a
step at every edge (:class:`~OpenGLContext.scenegraph.terrain.relief.RockRelief`). A
terrain meshed every few metres cannot carry that, so near the camera the rocky cells are
meshed again at a fraction of a metre, with the rock added to the height, and drawn just
over the coarse mesh with a rock material.

:class:`RockGround` is the scene node that streams those cells, as
:class:`~OpenGLContext.scenegraph.rockfield.RockField` streams stones. :class:`RockyGround`
is the same surface as a ground to stand on: the height a walker, a camera, a plant or a
stone is seated at is the height that is drawn.
"""
from dataclasses import dataclass
from typing import Any

import numpy as np

from OpenGLContext.loaders.tiles3d.boundingvolume import BoxBV
from OpenGLContext.noise import smoothstep
from OpenGLContext.scenegraph import surfaces as sf
from OpenGLContext.scenegraph.basenodes import Appearance, Shape, Transform
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.generatedtiles import GeneratedTiles
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.rockfield import cells_near
from OpenGLContext.scenegraph.terrain.relief import RockRelief
from OpenGLContext.scenegraph.vegetation.grid import Ground

__all__ = ['RockGround', 'RockGroundScatter', 'RockyGround', 'beneath']

#: Metres between the vertices of a rocky cell, and how wide a cell is.
STEP = 0.4
CELL = 32.0
#: Metres one repeat of the rock's texture covers.
REPEAT = 2.0
#: The ground is read every this many metres across a cell to say whether any of it is rock.
PROBE = 1.0
#: A triangle whose corners have less rock than this is left out of the fine mesh, since the
#: coarse ground is the same surface there and would only be drawn over.
LEAVE_OUT = 0.03
#: The rock weight at which the fine ground is fully opaque. It fades in below that, so the
#: edge of the fine ground is the coarse ground showing through and not a line.
FADE_IN = 0.35
#: How far below the ground the coarse terrain is drawn where the ground is rock, at most, in
#: metres: see :func:`beneath`.
SINK = 0.3


def beneath(field: Any, rock: RockRelief, depth: float = SINK) -> Any:
    """``field`` lowered by up to ``depth`` metres where ``rock`` has ground, to draw the coarse
    terrain from.

    The rock is drawn over the coarse terrain, and where two surfaces lie together the one
    drawn is whichever the depth buffer rounds towards. Drawing the coarse terrain from this
    field puts it below the rock by ``depth`` times the rock's weight at every point (and the
    rock is never below the field itself), so the rock is always above it by more than depth
    resolution except where there is next to no rock, and there the fine mesh leaves the
    ground out (:data:`LEAVE_OUT`). Walk, plant and collide against ``field`` or
    :class:`RockyGround`, not against this.
    """
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField

    axis = np.linspace(-field.extent / 2.0, field.extent / 2.0, field.res)
    gx, gz = np.meshgrid(axis, axis)
    lowered = np.asarray(field.grid, dtype=float) - depth * rock.weight(gx, gz) / field.relief
    return HeightField(lowered, field.extent, field.relief, base=field.base)


class RockyGround:
    """``ground`` with ``rock`` standing on it: the surface :class:`RockGround` draws.

    It answers what a :class:`~OpenGLContext.scenegraph.terrain.HeightField` answers
    (``sample``, ``height_at`` and ``slope``), and anything else it is asked for it takes
    from ``ground``, so it stands in for the field where a walker, a camera or a scatter is
    bound to one. The field's own ``relief``, the metres its grid spans, is still the
    field's, which is why the rock is ``rock``. ``spacing`` is how far apart the surface is
    sampled where it is drawn; pass the :class:`RockGround`'s ``step``.
    """

    def __init__(self, ground: Ground, rock: RockRelief, spacing: float = STEP) -> None:
        self.ground, self.rock, self.spacing = ground, rock, float(spacing)

    def __getattr__(self, name: str) -> Any:
        if name in ('ground', 'rock', 'spacing'):
            raise AttributeError(name)
        return getattr(self.ground, name)

    def sample(self, x: "float | np.ndarray", z: "float | np.ndarray") -> np.ndarray:
        """Height of the ground and the rock on it at ``(x, z)``."""
        return np.asarray(np.asarray(self.ground.sample(x, z))
                          + self.rock.displacement(x, z, self.spacing))

    def height_at(self, x: float, z: float) -> float:
        """Scalar height at ``(x, z)``."""
        return float(self.sample(x, z))

    def slope(self, x: "float | np.ndarray", z: "float | np.ndarray",
              eps: float = 8.0) -> np.ndarray:
        """Rise over run at ``(x, z)``, measured ``eps`` metres either side."""
        x, z = np.asarray(x, dtype='d'), np.asarray(z, dtype='d')
        sx = (self.sample(x + eps, z) - self.sample(x - eps, z)) / (2.0 * eps)
        sz = (self.sample(x, z + eps) - self.sample(x, z - eps)) / (2.0 * eps)
        return np.asarray(np.hypot(sx, sz))


@dataclass(frozen=True)
class RockTile:
    """What the tile runtime takes of a generated tile: the node to draw."""

    group: Group


class RockGroundScatter:
    """A tile generator that meshes the rocky ground finely.

    ``ground`` is the surface the coarse terrain draws and ``relief`` the rock on it.
    ``material`` is what the rock wears. A cell ``cell`` metres wide is meshed with a vertex
    every ``step`` metres and only where some of it is rock; a cell with none is no tile.
    """

    def __init__(self, ground: Ground, relief: RockRelief, material: Any,
                 cell: float = CELL, step: float = STEP, repeat: float = REPEAT) -> None:
        if step <= 0.0 or cell < 2.0 * step:
            raise ValueError('rock ground meshed every %r m in cells %r m wide' % (step, cell))
        self.ground, self.relief, self.material = ground, relief, material
        self.cell, self.step, self.repeat = float(cell), float(step), float(repeat)
        self._rocky: dict[tuple[int, int], bool] = {}

    # -- the generator protocol --
    def keys_near(self, point: np.ndarray, radius: float) -> list[tuple[int, int]]:
        """The cells with rock in them within ``radius`` metres of ``point``, nearest first."""
        return [key for key in cells_near(point, radius, self.cell) if self.has_rock(key)]

    def has_rock(self, key: tuple[int, int]) -> bool:
        """Whether any of the cell is rock."""
        found = self._rocky.get(key)
        if found is None:
            x0, _, z0 = self.origin(key)
            axis = np.linspace(0.0, self.cell, max(2, int(self.cell / PROBE) + 1))
            gx, gz = np.meshgrid(x0 + axis, z0 + axis)
            found = bool(self.relief.weight(gx, gz).max() > LEAVE_OUT)
            self._rocky[key] = found
        return found

    def origin(self, key: tuple[int, int]) -> tuple[float, float, float]:
        """The corner of a cell: its vertices are built around it so they stay small."""
        return (key[0] * self.cell, 0.0, key[1] * self.cell)

    def bounds(self, key: tuple[int, int]) -> BoxBV:
        """The box that holds the rock of a cell."""
        x0, _, z0 = self.origin(key)
        axis = np.linspace(0.0, self.cell, 9)
        gx, gz = np.meshgrid(x0 + axis, z0 + axis)
        base = np.asarray(self.ground.sample(gx, gz), dtype=float)
        low = float(base.min()) - 0.5
        high = float(base.max()) + self.relief.height * 1.3 + 0.5
        half = self.cell / 2.0
        return BoxBV((x0 + half, (low + high) / 2.0, z0 + half),
                     [(half, 0.0, 0.0), (0.0, (high - low) / 2.0, 0.0), (0.0, 0.0, half)])

    def heights(self, x: np.ndarray, z: np.ndarray) -> np.ndarray:
        """The surface this meshes: the ground and the rock on it."""
        return np.asarray(np.asarray(self.ground.sample(x, z))
                          + self.relief.displacement(x, z, self.step))

    def generate(self, key: tuple[int, int]) -> tuple[RockTile, int]:
        """The cell as a node to draw, and its size in bytes. Runs on a worker."""
        x0, _, z0 = self.origin(key)
        count = int(round(self.cell / self.step))
        axis = np.arange(-1, count + 2) * self.step
        gx, gz = np.meshgrid(x0 + axis, z0 + axis)
        height = self.heights(gx, gz)
        inner = height[1:-1, 1:-1]
        slope_x = (height[1:-1, 2:] - height[1:-1, :-2]) / (2.0 * self.step)
        slope_z = (height[2:, 1:-1] - height[:-2, 1:-1]) / (2.0 * self.step)
        local = axis[1:-1]
        lx, lz = np.meshgrid(local, local)
        positions = np.stack([lx, inner, lz], axis=-1).reshape(-1, 3).astype('f')
        normals = np.stack([-slope_x, np.ones_like(slope_x), -slope_z], axis=-1)
        normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
        texcoords = np.stack([x0 + lx, z0 + lz], axis=-1).reshape(-1, 2) / self.repeat
        tangent = np.stack([np.ones_like(slope_x), slope_x, np.zeros_like(slope_x)], axis=-1)
        tangent /= np.linalg.norm(tangent, axis=-1, keepdims=True)
        tangents = np.concatenate([tangent, np.ones(tangent.shape[:2] + (1,))], axis=-1)
        rock = self.relief.weight(x0 + lx, z0 + lz).reshape(-1)
        mesh = sf.Geometry(positions, normals.reshape(-1, 3).astype('f'),
                           texcoords.astype('f'), tangents.reshape(-1, 4).astype('f'),
                           _indices(count + 1, rock))
        look = Appearance(material=self.material)
        look.alphaMode = 'BLEND'
        fade = np.asarray(smoothstep(np.clip(rock / FADE_IN, 0.0, 1.0)))
        colours = np.ones((len(positions), 4), 'f')
        colours[:, 3] = fade
        shape = Shape(geometry=PBRMesh(
            positions=mesh.positions, normals=mesh.normals, texcoords=mesh.texcoords,
            tangents=mesh.tangents, indices=mesh.indices, colors=colours), appearance=look)
        shape.castShadow = False
        node = Transform(children=[shape])
        size = int(sum(array.nbytes for array in mesh) + colours.nbytes)
        return RockTile(Group(children=[node])), size


def _indices(side: int, rock: np.ndarray) -> np.ndarray:
    """Triangles over a ``side`` by ``side`` grid of vertices, wound to face up, without those
    whose three corners have less than :data:`LEAVE_OUT` of ``rock``."""
    a = (np.arange(side - 1)[:, None] * side + np.arange(side - 1)[None, :]).reshape(-1)
    triangles = np.stack([a, a + side, a + 1, a + 1, a + side, a + side + 1],
                         axis=-1).reshape(-1, 3)
    kept = rock[triangles].max(axis=1) > LEAVE_OUT
    return np.asarray(triangles[kept].reshape(-1).astype(np.uint32))


class RockGround(GeneratedTiles):
    """The rocky ground around the camera, meshed finely: a
    :class:`~OpenGLContext.scenegraph.generatedtiles.GeneratedTiles` node fed by a
    :class:`RockGroundScatter`.

    ``ground``, ``relief``, ``material``, ``cell``, ``step`` and ``repeat`` are the
    scatter's. ``reach`` is how far from the camera, in metres, a cell is meshed. Call
    :meth:`update_for_camera` once a frame with the GL context current. Bind a walker,
    a camera or a scatter to :meth:`ground` so that what stands on the rock stands on
    what is drawn.
    """

    def __init__(self, ground: Ground, relief: RockRelief, material: Any, reach: float = 100.0,
                 cell: float = CELL, step: float = STEP, repeat: float = REPEAT,
                 **named: Any) -> None:
        self.scatter = RockGroundScatter(ground, relief, material, cell, step, repeat)
        super().__init__(self.scatter, reach, **named)

    @property
    def ground(self) -> RockyGround:
        """The surface that is drawn, as a ground."""
        return RockyGround(self.scatter.ground, self.scatter.relief, self.scatter.step)
