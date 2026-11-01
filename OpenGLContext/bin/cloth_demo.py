"""oglc-cloth: a banner in a gusting wind, a cloth draped over a stone ball, and a sheet pinned to a beam.

Keys:
    d      drop the drape again from above the ball
    w      the wind: gusting, still, or a gale
    r      release the sheet's lower pins, or pin them again
    space  throw a steel ball at the sheet

Every cloth is a soft body the physics service steps (``Physics.add_soft_mesh``)
and a mesh whose vertices it writes each frame the cloth moves.
"""
from __future__ import annotations

import argparse
import math
from typing import Any

import numpy as np

from OpenGLContext.physics import PhysicsDefinition, Proxy
from OpenGLContext.physics.softbodies import SoftBodySpec
from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = ['ClothYard', 'WINDS', 'definition', 'main']

#: The wind settings ``w`` steps through: (name, mean force, gust share), newtons.
WINDS = (('gusting', 6.0, 0.6), ('still', 0.0, 0.0), ('gale', 16.0, 0.3))
#: The banner, the drape and the sheet: width and depth (m) and vertices a side.
BANNER = (1.6, 1.0, 25, 17)
DRAPE = (2.0, 2.0, 31, 31)
SHEET = (1.4, 1.4, 21, 21)
#: Where the stone ball stands and how big it is, metres.
BALL_CENTRE = (0.0, 0.6, 0.0)
BALL_RADIUS = 0.6
#: The banner's pole: its foot and height, metres.
POLE_FOOT = (-3.0, 0.0, -1.0)
POLE_HEIGHT = 3.2
#: Where the sheet's beam runs, at what height.
BEAM = (3.0, 2.6, -0.5)


def definition() -> PhysicsDefinition:
    """The world the yard runs in: in the frame, so the opening plays the same on every run."""
    return PhysicsDefinition(mode='inline', tickHz=60.0, maxCatchUp=0.1, colliders='explicit')


def cloth_mesh(width: float, depth: float, columns: int, rows: int, repeat: float = 1.0) -> PBRMesh:
    """A flat grid mesh in the y = 0 plane, both sides drawn, texture coordinates by the metre."""
    grid = SoftBodySpec.cloth(width, depth, columns, rows)
    assert grid.faces is not None
    texcoords = (grid.positions[:, [0, 2]] / repeat) + 0.5
    return PBRMesh(positions=grid.positions, normals=np.tile([0.0, 1.0, 0.0], (len(grid), 1)),
                   texcoords=texcoords, indices=grid.faces.ravel(), solid=False)


class Finishes:
    """The yard's materials: marble, sandstone, bronze, steel and three fabrics."""

    def __init__(self) -> None:
        self.floor = surfaces.pbr_material(surfaces.checkered_marble(512, tiles=8))
        self.stone = surfaces.pbr_material(surfaces.sandstone(256))
        self.bronze = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.BRONZE, 0.35))
        self.steel = surfaces.pbr_material(surfaces.brushed_metal(128, surfaces.STEEL, 0.2))
        self.wood = surfaces.pbr_material(surfaces.wood(256))
        self.banner = surfaces.pbr_material(
            surfaces.tiles(256, count=4, colour=(0.55, 0.06, 0.08)), metallic=0.0, roughness=0.8)
        self.drape = surfaces.pbr_material(
            surfaces.plaster(256, colour=(0.16, 0.24, 0.48)), metallic=0.0, roughness=0.9)
        self.sheet = surfaces.pbr_material(
            surfaces.plaster(256, colour=(0.82, 0.76, 0.62)), metallic=0.0, roughness=0.85)


def _shape(geometry: Any, material: Any) -> Any:
    return basenodes.Shape(geometry=geometry, appearance=basenodes.Appearance(material=material))


class ClothYard:
    """The demo's cloths, posts and wind, with no GL and no window.

    ``physics`` is an inline physics service (see :func:`definition`). The
    context puts :meth:`scene` before the camera, calls :meth:`update` once a
    frame and forwards key presses to :meth:`drop`, :meth:`next_wind`,
    :meth:`toggle_sheet` and :meth:`throw`.
    """

    def __init__(self, physics: Any) -> None:
        self.physics = physics
        self.finish = Finishes()
        self.root = basenodes.Group()
        self.time = 0.0
        self.wind = 0
        self._static((20.0, 1.0, 20.0), (0.0, -0.5, 0.0), self.finish.floor)
        ball = basenodes.Transform(translation=BALL_CENTRE, children=[
            _shape(basenodes.Sphere(radius=BALL_RADIUS), self.finish.stone)])
        self.root.children.append(ball)
        physics.add_static(ball, proxy=Proxy.sphere(BALL_RADIUS))
        self._pole()
        self._beam()
        self.banner = self._banner()
        self.drape = self._drape()
        self.sheet, self._sheet_pins = self._sheet()
        self.sheet_pinned = True
        self.balls: list[Any] = []

    # -- building ------------------------------------------------------------
    def _static(self, size: Any, position: Any, material: Any) -> Any:
        node = basenodes.Transform(translation=tuple(position), children=[
            _shape(basenodes.Box(size=tuple(size)), material)])
        self.root.children.append(node)
        return self.physics.add_static(node, proxy=Proxy.box(size))

    def _pole(self) -> None:
        x, y, z = POLE_FOOT
        self.root.children.append(basenodes.Transform(
            translation=(x, y + POLE_HEIGHT / 2, z), children=[
                _shape(basenodes.Cylinder(radius=0.05, height=POLE_HEIGHT), self.finish.bronze)]))
        self.root.children.append(basenodes.Transform(
            translation=(x, y + POLE_HEIGHT + 0.06, z), children=[
                _shape(basenodes.Sphere(radius=0.09), self.finish.bronze)]))

    def _beam(self) -> None:
        x, y, z = BEAM
        for side in (-1.0, 1.0):
            self._static((0.14, y, 0.14), (x + side * 0.85, y / 2, z), self.finish.wood)
        self._static((1.84, 0.14, 0.14), (x, y + 0.07, z), self.finish.wood)

    def _banner(self) -> Any:
        """A banner hung by its edge from the pole, vertical, flying along +x."""
        width, depth, columns, rows = BANNER
        mesh = cloth_mesh(width, depth, columns, rows, repeat=0.4)
        self.root.children.append(_shape(mesh, self.finish.banner))
        x, y, z = POLE_FOOT
        # Turned a quarter about x, so the grid's depth hangs down; its -x edge at the pole.
        turn = (math.sin(math.pi / 4), 0.0, 0.0, math.cos(math.pi / 4))
        centre = (x + width / 2 + 0.06, y + POLE_HEIGHT - depth / 2, z)
        edge = [row * columns for row in range(rows)]
        points = np.array([(x + 0.06, y + POLE_HEIGHT - depth * row / (rows - 1), z)
                           for row in range(rows)])
        return self.physics.add_soft_mesh(mesh, centre, turn, pins=(edge, points), mass=0.4,
                                          linear_damping=0.3, friction=0.4)

    def _drape(self) -> Any:
        width, depth, columns, rows = DRAPE
        mesh = cloth_mesh(width, depth, columns, rows, repeat=0.5)
        self.root.children.append(_shape(mesh, self.finish.drape))
        x, y, z = BALL_CENTRE
        return self.physics.add_soft_mesh(mesh, (x, y + BALL_RADIUS + 0.4, z), mass=1.2,
                                          friction=0.7, vertex_radius=0.012,
                                          linear_damping=0.2)

    def _sheet(self) -> tuple[Any, tuple[list[int], np.ndarray]]:
        """A sheet hung from the beam by its top corners and middle, its bottom corners pinned to the posts."""
        width, depth, columns, rows = SHEET
        mesh = cloth_mesh(width, depth, columns, rows, repeat=0.6)
        self.root.children.append(_shape(mesh, self.finish.sheet))
        x, y, z = BEAM
        turn = (math.sin(math.pi / 4), 0.0, 0.0, math.cos(math.pi / 4))
        top = [0, columns // 2, columns - 1]
        bottom = [(rows - 1) * columns, rows * columns - 1]
        top_points = [(x - width / 2, y, z), (x, y, z), (x + width / 2, y, z)]
        bottom_points = [(x - width / 2, y - depth, z), (x + width / 2, y - depth, z)]
        vertices = top + bottom
        points = np.array(top_points + bottom_points)
        soft = self.physics.add_soft_mesh(mesh, (x, y - depth / 2, z), turn,
                                          pins=(vertices, points), mass=0.6, friction=0.4,
                                          linear_damping=0.3, compliance=1e-4)
        return soft, (vertices, points)

    def scene(self) -> Any:
        """The scenegraph: two lights, a sky and the yard."""
        return basenodes.sceneGraph(children=[
            basenodes.DirectionalLight(direction=(-0.4, -1.0, -0.6), intensity=1.0),
            basenodes.DirectionalLight(direction=(0.5, -0.3, 0.8), intensity=0.35),
            self.root,
            basenodes.SimpleBackground(color=(0.58, 0.66, 0.76)),
        ])

    # -- what happens ----------------------------------------------------------
    def wind_force(self, time: float) -> tuple[float, float, float]:
        """The wind on the banner at ``time``: the setting's mean, gusting on two slow waves."""
        _name, mean, gust = WINDS[self.wind]
        swell = 1.0 + gust * (0.6 * math.sin(time * 1.3) + 0.4 * math.sin(time * 3.1 + 1.0))
        return (mean * swell, 0.0, 0.4 * mean * math.sin(time * 0.7))

    def update(self, dt: float) -> None:
        """Advance the wind by ``dt`` seconds and blow it on the banner and the sheet."""
        self.time += max(0.0, float(dt))
        force = self.wind_force(self.time)
        self.banner.soft.set_wind(force)
        self.sheet.soft.set_wind((0.0, 0.0, 0.3 * force[0]))

    def next_wind(self) -> str:
        """Step to the next wind setting; its name."""
        self.wind = (self.wind + 1) % len(WINDS)
        return WINDS[self.wind][0]

    def drop(self) -> None:
        """Drop a fresh drape from above the ball."""
        self.drape.remove()
        for child in list(self.root.children):
            if getattr(child, 'geometry', None) is self.drape.mesh:
                self.root.children.remove(child)
        self.drape = self._drape()

    def toggle_sheet(self) -> bool:
        """Release the sheet's lower pins, or pin them again; whether it is pinned at the bottom."""
        vertices, points = self._sheet_pins
        self.sheet_pinned = not self.sheet_pinned
        keep = len(vertices) if self.sheet_pinned else 3
        self.sheet.soft.pin(vertices[:keep], points[:keep])
        return self.sheet_pinned

    def throw(self, origin: Any = None, velocity: Any = None) -> Any:
        """Throw a steel ball at the sheet; its body."""
        x, y, z = BEAM
        start = origin if origin is not None else (x, y - 0.7, z + 4.0)
        node = basenodes.Transform(translation=tuple(start), children=[
            _shape(basenodes.Sphere(radius=0.12), self.finish.steel)])
        self.root.children.append(node)
        body = self.physics.add_dynamic(node, proxy=Proxy.sphere(0.12), mass=2.0)
        body.set_velocity(velocity if velocity is not None else (0.0, 1.0, -9.0))
        self.balls.append(body)
        return body


def main() -> int:                              # pragma: no cover - needs a window
    """Open the yard in a window."""
    argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0]).parse_args()
    from OpenGLContext.context import Context as BaseContext
    from OpenGLContext.contextdefinition import ContextDefinition

    class ClothContext(BaseContext):
        renderer = 'pbr'
        initialPosition = (0.0, 2.0, 7.5)
        contextDefinition = ContextDefinition(physics=definition())

        def OnInit(self) -> None:
            self.yard = ClothYard(self.physics)
            self.sg = self.yard.scene()
            self.animate(self.yard.update)
            self.keys = {'d': self.yard.drop, 'w': self.OnWind,
                         'r': self.yard.toggle_sheet, ' ': self.yard.throw}
            for key in self.keys:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(__doc__, flush=True)

        def OnKey(self, event: Any) -> None:
            """Run the action of the key pressed; a handler is held by weak
            reference, so the keys share this method of the context."""
            self.keys[event.name]()

        def OnWind(self) -> None:
            print('wind: %s' % (self.yard.next_wind(),), flush=True)

    ClothContext.ContextMainLoop()
    return 0


if __name__ == '__main__':                      # pragma: no cover - needs a window
    main()
