#! /usr/bin/env python
'''=Walking an NPC along a route=

[using_npc.py-screen-0001.png Screenshot]

A figure walks from one corner of a room to another, around a wall in the
middle, playing its walk clip as it goes. Three pieces do it: a navigation
mesh says which way round the wall to go, a physics character walks the route
it returns, and a clip map says which of the model's clips shows the walk.
The script has no clock and no per-frame code.

:doc:`Navigation mesh <navmesh_demo>` covers what ``build`` keeps and how a
route is pulled taut; :doc:`A character runs across a landscape
</tutorials/character/character_run>` covers characters and clip maps. The
model is `Fox` from the Khronos sample catalogue (CC-BY 4.0, by PixelMannen
and tomkranis).

Keys:
    g       send it to the next corner
'''
import numpy as np

from OpenGLContext.character.locomotion import ClipMap
from OpenGLContext.context import Context
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.nav import navmesh
from OpenGLContext.physics import CharacterCapabilities
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Coordinate, DirectionalLight, IndexedFaceSet,
    IndexedLineSet, Material, Shape, sceneGraph,
)

MODEL = 'Fox'
#: The room in metres, and how big one floor triangle is. A cell is the unit
#: the navmesh works in: routes turn at cell corners, and a cell against a wall
#: is dropped whole.
ROOM = 14.0
CELL = 1.0
#: The wall across the middle: half-length, height, half-thickness.
WALL = (4.0, 2.5, 1.0)
#: Where it walks, in order, as points on the floor. Each is on the far side
#: of the wall from the one before it, so every route is a way round.
GOALS = [(-3.0, 0.0, -5.0), (3.0, 0.0, 5.0), (3.0, 0.0, -5.0), (-3.0, 0.0, 5.0)]
#: Metres a second, between the speeds of the walk and the run below.
SPEED = 1.8
#: The fox's clips by role. The walk and the run carry the fox 102.7 and 171.9
#: model units a second; the fox stands 79 units high and is scaled to the
#: capsule's 1.1 m, so those are 1.4 and 2.4 metres a second.
FOX = ClipMap(idle='Survey', walk=('Walk', 1.4), run=('Run', 2.4))
#: A capsule 1.1 m high and 0.35 m round: the fox is scaled to its height.
BODY = CharacterCapabilities(standHeight=1.1, crouchHeight=0.7, radius=0.35)


class TestContext(Context):
    initialPosition = (0, 6.5, 11)
    initialOrientation = (-1, 0, 0, 0.52)          # pitched down at the floor

    def OnInit(self):
        '''The floor and the wall are one triangle mesh, which is what a level
        is. ``build`` keeps the triangles a body could stand on: ``max_slope``
        drops the wall's own faces, and ``clearance``, the room a body needs
        above the floor, drops the floor cells the wall stands on, so the two
        halves of the room are not joined straight through it.

        A game that has loaded a level has the argument already:
        ``navmesh.from_scene(scene)`` takes the triangles the level's static
        bodies are made of.'''
        points, triangles = room_mesh()
        self.mesh = navmesh.build(points, triangles, clearance=1.8)
        print('navmesh: %d walkable cells from %d triangles'
              % (len(self.mesh), len(triangles)))

        self.trail = IndexedLineSet(coord=Coordinate(point=[(0, 0, 0)] * 2),
                                    coordIndex=[0, 1, -1])
        '''The room is drawn from the same triangles the navmesh was built
        from, so what is on screen is what was handed to ``build``. Being
        shapes in the scene, they are also what the character stands on and
        is stopped by.'''
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.13, 0.15, 0.18)]),
            DirectionalLight(direction=(-0.4, -0.8, -0.4)),
            mesh_shape(points, triangles, (0.13, 0.15, 0.14)),
            Shape(geometry=self.trail,
                  appearance=Appearance(material=Material(
                      diffuseColor=(0.2, 0.9, 0.9),
                      emissiveColor=(0.2, 0.9, 0.9)))),
        ])
        '''``add_character`` makes the NPC: a capsule of the size ``BODY``
        gives, wearing the fox, which plays the clips ``FOX`` names for how fast
        it goes and turns to face the way it walks.'''
        self.hero = self.physics.add_character(
            capabilities=BODY, model=sample_model_url(MODEL), animations=FOX,
            position=GOALS[-1], parent=self.sg)
        '''``'arrived'`` is told when the character reaches the end of the
        route it was sent along. This handler sends it to the next goal.'''
        self.hero.addEventHandler('arrived', self.OnArrived)
        self.goal = 0
        self.send()
        self.addEventHandler('keypress', name='g', function=self.OnGoal)
        print(__doc__)

    def send(self):
        '''``path`` answers the points to walk through, from where the
        character stands to the goal. It answers fewer than two points where
        the two ends are not connected (a bot on a ledge with no way down),
        which is a fact about the level: this one takes the next goal.

        ``run_along`` takes the points as a course and walks it at ``SPEED``
        metres a second, steering back to the line each frame. The character
        stops at the end and is told ``'arrived'``.'''
        goal = GOALS[self.goal]
        route = [tuple(point) for point in self.mesh.path(self.hero.position, goal)]
        print('route to %s: %d points' % (goal, len(route)))
        if len(route) < 2:
            self.goal = (self.goal + 1) % len(GOALS)
            return
        self.hero.run_along(route, speed=SPEED, mode='walk')
        self.show_route(route)

    def OnArrived(self, hero):
        self.OnGoal()

    def OnGoal(self, event=None):
        self.goal = (self.goal + 1) % len(GOALS)
        self.send()

    def show_route(self, route):
        '''The cyan line is the route, drawn so it can be seen. A game would
        not draw it.'''
        self.trail.coord.point = [(x, y + 0.1, z) for x, y, z in route]
        self.trail.coordIndex = list(range(len(route))) + [-1]


def room_mesh():
    """The room's collision mesh: a grid floor and a wall standing on it."""
    points = []
    triangles = []

    def quad(corners):
        first = len(points)
        points.extend(corners)
        triangles.extend([[first, first + 1, first + 2],
                          [first, first + 2, first + 3]])

    half = ROOM / 2.0
    steps = int(ROOM / CELL)
    for row in range(steps):
        for column in range(steps):
            x, z = -half + column * CELL, -half + row * CELL
            quad([(x, 0, z), (x, 0, z + CELL),
                  (x + CELL, 0, z + CELL), (x + CELL, 0, z)])
    length, height, thickness = WALL
    for side in (-thickness, thickness):
        quad([(-length, 0, side), (-length, height, side),
              (length, height, side), (length, 0, side)])
    quad([(-length, height, -thickness), (-length, height, thickness),
          (length, height, thickness), (length, height, -thickness)])
    return np.array(points, dtype='d'), np.array(triangles, dtype='i')


def mesh_shape(points, triangles, colour):
    """A set of triangles, drawn."""
    index = []
    for triangle in triangles:
        index.extend([int(triangle[0]), int(triangle[1]), int(triangle[2]), -1])
    return Shape(
        geometry=IndexedFaceSet(coord=Coordinate(point=points.tolist()),
                                coordIndex=index, solid=False),
        appearance=Appearance(material=Material(diffuseColor=colour)),
    )


if __name__ == "__main__":
    TestContext.ContextMainLoop()
