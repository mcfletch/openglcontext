#! /usr/bin/env python
'''=Walking an NPC along a route=

[using_npc.py-screen-0001.png Screenshot]

A figure walks from one corner of a room to another, around a wall in the
middle, playing its walk clip as it goes.  Three pieces do it: a navigation
mesh says which way round the wall to go, the route it returns is followed a
waypoint at a time, and a clip from the model's own file moves the body.

:doc:`Navigation mesh <navmesh_demo>` covers what ``build`` keeps and how a
route is pulled taut; :doc:`Playing a canned animation <using_clips>` covers
the clips.  The model is `Fox` from the Khronos sample catalogue (CC-BY 4.0,
by PixelMannen and tomkranis).

Keys:
    g       send it to the next corner
'''
import os
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

import math

import numpy as np

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.nav import navmesh
from OpenGLContext.events.systemtime import systemTime
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.loaders.resolver import fetch_to_cache
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Coordinate, DirectionalLight, IndexedFaceSet,
    IndexedLineSet, Material, Shape, Transform, sceneGraph,
)

MODEL = 'Fox'
#: The room in metres, and how big one floor triangle is.  A cell is the unit
#: the navmesh works in: routes turn at cell corners, and a cell against a wall
#: is dropped whole.
ROOM = 14.0
CELL = 1.0
#: The wall across the middle: half-length, height, half-thickness.
WALL = (4.0, 2.5, 1.0)
#: Where it walks, in order, as points on the floor.  Each is on the far side
#: of the wall from the one before it, so every route is a way round.
GOALS = [(-3.0, 0.0, -5.0), (3.0, 0.0, 5.0), (3.0, 0.0, -5.0), (-3.0, 0.0, 5.0)]
#: Metres a second, about the pace of the walk clip.
SPEED = 3.0
#: How close counts as having reached a waypoint, in metres.
ARRIVED = 0.3
#: The Fox is authored around a hundred units long, so it is scaled to about
#: two metres before it is put in a room measured in metres.
MODEL_SCALE = 0.02


class TestContext(BaseContext):
    initialPosition = (0, 6.5, 11)
    initialOrientation = (-1, 0, 0, 0.52)          # pitched down at the floor

    def OnInit(self):
        '''The floor and the wall are one triangle mesh, which is what a level
        is.  ``build`` keeps the triangles a body could stand on: ``max_slope``
        drops the wall's own faces, and ``clearance`` -- the room a body needs
        above the floor -- drops the floor cells the wall stands on, so the two
        halves of the room are not joined straight through it.

        A game that has loaded a level has the argument already:
        ``navmesh.from_world(world)`` takes the same triangles out of a physics
        world.'''
        points, triangles = room_mesh()
        self.mesh = navmesh.build(points, triangles, clearance=1.8)
        print('navmesh: %d walkable cells from %d triangles'
              % (len(self.mesh), len(triangles)))

        '''``CharacterModel.load`` reads a rigged glTF file and gives the clips
        in it names.  The walk plays for as long as the figure is walking, and
        nothing else starts it or stops it.'''
        self.model = CharacterModel.load(fetch_to_cache(sample_model_url(MODEL)))
        self.model.play('Walk', loop=True)
        '''The figure is a ``Transform`` with the model under it.  Moving the
        NPC is writing ``translation`` and ``rotation`` on that node; the model
        under it knows nothing about where it is.'''
        self.figure = Transform(
            scale=(MODEL_SCALE, MODEL_SCALE, MODEL_SCALE),
            children=[self.model.group],
        )
        self.position = np.array(GOALS[-1], dtype='d')
        self.goal = 0
        self.route = self.plan()

        self.trail = IndexedLineSet(coord=Coordinate(point=[(0, 0, 0)] * 2),
                                    coordIndex=[0, 1, -1])
        '''The room is drawn from the same triangles the navmesh was built
        from, so what is on screen is what was handed to ``build``.'''
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.13, 0.15, 0.18)]),
            DirectionalLight(direction=(-0.4, -0.8, -0.4)),
            mesh_shape(points, triangles, (0.13, 0.15, 0.14)),
            Shape(geometry=self.trail,
                  appearance=Appearance(material=Material(
                      diffuseColor=(0.2, 0.9, 0.9),
                      emissiveColor=(0.2, 0.9, 0.9)))),
            self.figure,
        ])
        self.addEventHandler('keypress', name='g', function=self.OnGoal)
        self.last = systemTime()
        print(__doc__)

    def plan(self):
        '''``path`` answers the points to walk through.  It answers an empty
        list where the two ends are not connected -- a bot on a ledge with no
        way down -- which is a fact about the level rather than an error, so it
        is worth handling: this one gives up on that goal and takes the next.'''
        route = list(self.mesh.path(self.position, GOALS[self.goal]))
        print('route to %s: %d points' % (GOALS[self.goal], len(route)))
        return route

    def OnGoal(self, event=None):
        self.goal = (self.goal + 1) % len(GOALS)
        self.route = self.plan()
        self.show_route()

    def OnIdle(self, event=None):
        '''One step of the world: where the figure is, then what its body is
        doing.  Both take the same time step.'''
        now = systemTime()
        step = min(now - self.last, 0.1)
        self.last = now
        self.walk(step)
        self.model.update(step)
        self.triggerRedraw(1)

    def walk(self, step):
        '''Following a route is walking towards the point at the front of it
        and dropping that point on arrival.  The navmesh has already done the
        part that needs to know about the level, which is choosing the
        points.'''
        if not self.route:
            self.OnGoal()
            return
        towards = np.asarray(self.route[0], dtype='d') - self.position
        towards[1] = 0.0
        distance = float(np.linalg.norm(towards))
        if distance < ARRIVED:
            self.route.pop(0)
            return
        heading = towards / distance
        self.position = self.position + heading * min(SPEED * step, distance)
        '''``rotation`` is an axis and an angle: turning about Y by the bearing
        of the direction of travel points the figure the way it is going.  The
        Fox model faces +Z, which is what makes this the whole of the turn; a
        model authored facing another way wants that angle added here.'''
        self.figure.translation = tuple(self.position)
        self.figure.rotation = (0, 1, 0, math.atan2(heading[0], heading[2]))
        self.show_route()

    def show_route(self):
        '''The cyan line is what is left of the route, drawn so it can be seen.
        A game would not draw it.'''
        points = [tuple(self.position)] + [tuple(point) for point in self.route]
        self.trail.coord.point = [(x, y + 0.1, z) for x, y, z in points]
        self.trail.coordIndex = list(range(len(points))) + [-1]


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
