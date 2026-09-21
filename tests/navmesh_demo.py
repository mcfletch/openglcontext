#! /usr/bin/env python
'''=Navigation mesh (walkable cells, and a path pulled taut)=

[navmesh_demo.py-screen-0001.png Screenshot]

A room with two walls across it, a route from one corner to the other,
and a fox walking it.  Nothing here is authored: the walls and the floor
are one collision mesh, and `OpenGLContext.nav.navmesh.build` picks the
walkable triangles out of it by slope and joins them up by shared edge.

What is on screen, from the floor up:

 * *grey* -- the collision mesh itself, floor and walls, drawn as it was
   handed to `build`.
 * *green* -- the navmesh: one wireframe triangle per walkable cell.  The
   dark bands under the walls are cells the headroom test removed, which
   is what stops a route being joined straight through a wall.
 * *amber* -- the corridor `NavMesh.corridor` found, drawn cell centre by
   cell centre.  It zigzags because triangle centres do.
 * *cyan* -- the same corridor **string-pulled** through the portals
   between its cells: the line a person would walk, hugging the end of
   each wall and straight everywhere else.
 * *blue and orange spheres* -- where the route starts and where it is
   going.
 * *the fox* -- walking the cyan line.  It plays its walk clip on the way,
   its idle clip on arrival, and after fifteen seconds standing still it
   picks somewhere else on the mesh and sets off again.

Following a route and turning to face it are
:doc:`Walking an NPC along a route <using_npc>`; this page is what the
route is made of.  The model is `Fox` from the Khronos sample catalogue
(CC-BY 4.0, by PixelMannen and tomkranis).

Press `g` to send the fox to the next of four goals, `r` to pick a random
point on the mesh, and `c` to print the numbers again.  Every re-path
prints how many cells the corridor runs through and what the pull saved:

    navmesh 416 walkable cells from 516 triangles (max slope 50.0 degrees, clearance 1.8 m)
    goal (14.0, 14.0) | corridor 77 cells
      centres 79 points 48.82 m -> pulled 6 points 33.34 m (-31.7%)

The usual keys walk around, though the view starts overhead because that
is where a navmesh reads.
'''
import math
import os

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
# The fox is a glTF model with its surfaces described the way the PBR
# renderer reads them, so that is the renderer to draw it with.
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

import numpy as np

from OpenGLContext import testingcontext
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.events.systemtime import systemTime
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.loaders.resolver import fetch_to_cache
from OpenGLContext.nav import navmesh
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Color, Coordinate, DirectionalLight, IndexedFaceSet,
    IndexedLineSet, Material, Shape, Sphere, Transform,
)

BaseContext = testingcontext.getInteractive('glfw')

#: The room, in metres square, meshed as one-metre quads.
ROOM = 16

#: The walls, as ``(x0, z0, x1, z1)`` in metres.  Two of them, overlapping
#: along x and reaching opposite edges, so the way through is a zigzag and
#: the difference between a centre route and a pulled one is a shape rather
#: than a wobble.
WALLS = [
    (5.0, 0.0, 5.0, 11.0),
    (11.0, 5.0, 11.0, 16.0),
]

#: How tall the walls stand, in metres.
WALL_HEIGHT = 2.5

#: Headroom asked of a cell, in metres.  Off by default in the engine --
#: ``navmesh.DEFAULT_CLEARANCE`` is 0.0, since the test is too blunt for a
#: real level -- and asked for here because this geometry is exactly the
#: small axis-aligned kind it is right on.
CLEARANCE = 1.8

#: Where the route starts, and the goals `g` cycles through.
START = (2.0, 0.0, 2.0)
GOALS = [
    (14.0, 0.0, 14.0),
    (14.0, 0.0, 2.0),
    (2.0, 0.0, 14.0),
    (8.0, 0.0, 8.0),
]

#: The walker, and the two clips it plays: one for moving, one for standing
#: still.  ``model.clips`` is where the names come from for a file whose
#: names you do not already know -- this one calls its idle ``Survey``.
MODEL = 'Fox'
WALK, IDLE = 'Walk', 'Survey'

#: The Fox is authored around a hundred units long, so it is scaled to about
#: two metres for a room measured in metres.
MODEL_SCALE = 0.02

#: Metres a second, and how close counts as having reached a waypoint.
SPEED = 2.5
ARRIVED = 0.3

#: Seconds the fox stands at a goal before choosing another.
REST = 15.0

#: How far over the floor each layer is drawn, in metres, so the three of
#: them stack instead of fighting for the same depth.
CELL_LIFT, CENTRE_LIFT, PATH_LIFT = 0.03, 0.10, 0.18

#: The cells are the layer the two routes are read against, so they are drawn
#: a dimmer green than either line.
CELL_COLOUR = (0.16, 0.52, 0.26)
CENTRE_COLOUR = (1.0, 0.62, 0.05)
PATH_COLOUR = (0.25, 0.95, 1.0)


def floor_mesh(size=ROOM):
    """A flat floor of ``size``x``size`` one-metre quads, wound to face up."""
    points, triangles, index = [], [], {}
    for row in range(size + 1):
        for col in range(size + 1):
            index[(row, col)] = len(points)
            points.append((float(col), 0.0, float(row)))
    for row in range(size):
        for col in range(size):
            a, b = index[(row, col)], index[(row, col + 1)]
            c, d = index[(row + 1, col + 1)], index[(row + 1, col)]
            triangles.extend([(a, c, b), (a, d, c)])
    return (np.array(points, dtype='d'), np.array(triangles, dtype='i'))


def wall_mesh(x0, z0, x1, z1, height=WALL_HEIGHT):
    """A vertical face: no walkable triangles of its own, and a blocker."""
    points = np.array([(x0, 0.0, z0), (x0, height, z0),
                       (x1, height, z1), (x1, 0.0, z1)], dtype='d')
    return (points, np.array([(0, 1, 2), (0, 2, 3)], dtype='i'))


def joined(*meshes):
    """Several ``(points, triangles)`` as one, the way a level arrives."""
    points, triangles, offset = [], [], 0
    for part_points, part_triangles in meshes:
        points.append(part_points)
        triangles.append(np.asarray(part_triangles) + offset)
        offset += len(part_points)
    return (np.vstack(points), np.vstack(triangles))


def walked(points):
    """How far a route is, in metres."""
    return sum(float(np.linalg.norm(np.asarray(b) - np.asarray(a)))
               for a, b in zip(points, points[1:], strict=False))


def _polyline(points, colour, lift):
    """One coloured line over the floor, as a node kept for re-pathing."""
    coordinate = Coordinate(point=_lifted(points, lift))
    colours = Color(color=[colour] * max(len(points), 1))
    geometry = IndexedLineSet(coord=coordinate, color=colours,
                              coordIndex=list(range(len(points))))
    return (Shape(geometry=geometry), geometry)


def _lifted(points, lift):
    """Points raised clear of the floor they are drawn over."""
    if not len(points):
        return np.zeros((0, 3), dtype='d')
    raised = np.asarray(points, dtype='d').copy()
    raised[:, 1] += lift
    return raised


def _marker(colour, position):
    """A ball on the floor, glowing enough to read against the wireframe.

    The colour is carried by the emission rather than by the lighting: a
    small sphere under a sky's worth of ambient light reads as white
    whatever its base colour is.
    """
    material = Material(diffuseColor=tuple(part * 0.25 for part in colour),
                        emissiveColor=colour)
    return Transform(translation=(position[0], 0.35, position[2]),
                     children=[Shape(geometry=Sphere(radius=0.3),
                                     appearance=Appearance(material=material))])


class TestContext(BaseContext):
    """A collision mesh, the navmesh built from it, and a route across it."""

    initialPosition = (8.0, 16.0, 17.2)
    initialOrientation = (-1, 0, 0, 1.05)      # pitch down onto the floor

    def OnInit(self):
        BaseContext.OnInit(self)
        floor = floor_mesh()
        walls = [wall_mesh(*wall) for wall in WALLS]
        points, triangles = joined(floor, *walls)
        # The seam the engine offers a game is from_world(): a collision mesh
        # already in a physics world.  build() is the same thing one step
        # earlier, with the triangles in hand.
        self.mesh = navmesh.build(points, triangles, clearance=CLEARANCE)
        self.triangles = len(triangles)
        self.goal = 0
        self.target = GOALS[0]
        self._last = None
        # The walker: where it stands, the route left to walk, and the time it
        # may choose a new goal at.  `rest_until` is None while it is walking.
        self.position = np.array(START, dtype='d')
        self.route = []
        self.rest_until = None
        self._clock = systemTime()
        self.model = CharacterModel.load(fetch_to_cache(sample_model_url(MODEL)))
        self.figure = Transform(
            scale=(MODEL_SCALE, MODEL_SCALE, MODEL_SCALE),
            children=[self.model.group],
        )

        shared = Coordinate(point=points)
        children = [
            DirectionalLight(direction=(-0.3, -0.8, -0.5), intensity=0.9),
            # Nearly level, so the walls have a lit face: a vertical plane
            # under an overhead key is a black silhouette.
            DirectionalLight(direction=(0.75, -0.25, 0.6), intensity=0.6,
                             color=(0.7, 0.78, 1.0)),
            _faces(shared, floor[1], (0.02, 0.022, 0.03), (0.0, 0.0, 0.0)),
            _faces(shared, triangles[len(floor[1]):], (0.12, 0.11, 0.10),
                   (0.01, 0.01, 0.01)),
            self._cells(),
        ]
        centre_shape, self.centre_line = _polyline([], CENTRE_COLOUR,
                                                   CENTRE_LIFT)
        path_shape, self.path_line = _polyline([], PATH_COLOUR, PATH_LIFT)
        self.goal_marker = _marker((0.95, 0.45, 0.1), self.target)
        self.start_marker = _marker((0.2, 0.45, 0.95), START)
        children.extend([centre_shape, path_shape,
                         self.start_marker, self.goal_marker, self.figure])
        self.sg = Transform(children=children)

        self.addEventHandler('keypress', name='g', function=self.OnNextGoal)
        self.addEventHandler('keypress', name='r', function=self.OnRandomGoal)
        self.addEventHandler('keypress', name='c', function=self.OnCounts)
        print(__doc__)
        print('navmesh %d walkable cells from %d triangles '
              '(max slope %.1f degrees, clearance %.1f m)'
              % (len(self.mesh), self.triangles, navmesh.DEFAULT_MAX_SLOPE,
                 CLEARANCE))
        self.repath()

    def _cells(self):
        """Every walkable cell as a wireframe triangle over the floor."""
        index = []
        for cell in self.mesh.cells:
            index.extend([int(cell[0]), int(cell[1]), int(cell[2]),
                          int(cell[0]), -1])
        coordinate = Coordinate(point=_lifted(self.mesh.points, CELL_LIFT))
        return Shape(geometry=IndexedLineSet(
            coord=coordinate, coordIndex=index,
            color=Color(color=[CELL_COLOUR] * len(self.mesh.points))))

    # -- re-pathing ------------------------------------------------------
    def repath(self):
        """Search, pull, draw, walk it, and say what the two routes cost.

        Every route starts from where the fox is standing rather than from a
        fixed point, which is what a game asks for: the question is always
        "from here to there".
        """
        start = tuple(self.position)
        cells = self.mesh.corridor(start, self.target)
        if not cells:
            print('goal (%.1f, %.1f) is off the mesh, or nothing leads to it'
                  % (self.target[0], self.target[2]))
            # Nothing to walk, so the fox stays where it is and asks again
            # when its rest is up.
            self.rest_until = systemTime() + REST
            return
        route = [start] + [tuple(centre) for centre in self.mesh.centres[cells]]
        route.append(self.target)
        pulled = self.mesh.path(start, self.target)
        self._draw(self.centre_line, route, CENTRE_COLOUR, CENTRE_LIFT)
        self._draw(self.path_line, pulled, PATH_COLOUR, PATH_LIFT)
        self.goal_marker.translation = (self.target[0], 0.35, self.target[2])
        self.start_marker.translation = (start[0], 0.35, start[2])
        # The pulled line is the route the fox walks: the corridor and the
        # centre line are drawn to be compared against it, not followed.
        self.route = list(pulled)
        self.rest_until = None
        self.model.play(WALK, loop=True, fade=0.3)
        self._report(route, pulled, len(cells))
        self.triggerRedraw(1)

    def _draw(self, geometry, points, colour, lift):
        geometry.coord.point = _lifted(points, lift)
        geometry.color.color = [colour] * max(len(points), 1)
        geometry.coordIndex = list(range(len(points)))

    def _report(self, route, pulled, corridor):
        raw, taut = walked(route), walked(pulled)
        saved = (100.0 * (raw - taut) / raw) if raw else 0.0
        print('goal (%.1f, %.1f) | corridor %d cells'
              % (self.target[0], self.target[2], corridor))
        print('  centres %d points %.2f m -> pulled %d points %.2f m (-%.1f%%)'
              % (len(route), raw, len(pulled), taut, saved))
        self._last = (route, pulled, corridor)

    # -- walking it ------------------------------------------------------
    def OnIdle(self, event=None):
        """One step of the world: the fox moves, then its body is posed."""
        now = systemTime()
        step = min(now - self._clock, 0.1)
        self._clock = now
        self.advance(step, now)
        self.model.update(step)
        self.triggerRedraw(1)

    def advance(self, step, now):
        """Walk what is left of the route, or wait out a rest at the end.

        Following the route -- walking at the point in front, dropping it on
        arrival, turning to face the way it is going -- is
        :doc:`Walking an NPC along a route <using_npc>`.
        """
        if self.route:
            self.step_along(step)
            if not self.route:
                self.arrive(now)
        elif self.rest_until is not None and now >= self.rest_until:
            self.OnRandomGoal()

    def step_along(self, step):
        """One frame's walk towards the point at the front of the route."""
        towards = np.asarray(self.route[0], dtype='d') - self.position
        towards[1] = 0.0
        distance = float(np.linalg.norm(towards))
        if distance < ARRIVED:
            self.route.pop(0)
            return
        heading = towards / distance
        self.position = self.position + heading * min(SPEED * step, distance)
        self.figure.translation = tuple(self.position)
        self.figure.rotation = (0, 1, 0, math.atan2(heading[0], heading[2]))

    def arrive(self, now):
        """The end of the route: stand still, and note when to move on.

        The idle clip replaces the walk on the same layer, so the fox stops
        moving its legs the moment it stops moving.  ``fade`` blends the two
        over a third of a second rather than switching poses in one frame.

        Nothing counts down here: the time to choose again is recorded, and
        :meth:`advance` compares the clock against it.  A timer a frame reads
        is a timer that survives a paused game and a session replayed at
        another frame rate.
        """
        self.model.play(IDLE, loop=True, fade=0.3)
        self.rest_until = now + REST
        print('arrived at (%.1f, %.1f); idling %.0f s before choosing again'
              % (self.target[0], self.target[2], REST))

    def OnNextGoal(self, event=None):
        self.goal = (self.goal + 1) % len(GOALS)
        self.target = GOALS[self.goal]
        self.repath()

    def OnRandomGoal(self, event=None):
        """Somewhere on the mesh, which is what a bot with no orders picks."""
        point = self.mesh.random_point()
        if point is not None:
            self.target = point
            self.repath()

    def OnCounts(self, event=None):
        if self._last is not None:
            self._report(*self._last)


def _faces(coordinate, triangles, colour, glow):
    """Part of the collision mesh, drawn as the solid it collides as.

    ``solid=False`` because a wall here is one plane rather than a box, and a
    culled plane is a wall you can see through from one side.
    """
    index = []
    for triangle in triangles:
        index.extend([int(triangle[0]), int(triangle[1]), int(triangle[2]), -1])
    return Shape(geometry=IndexedFaceSet(coord=coordinate, coordIndex=index,
                                         solid=False),
                 appearance=Appearance(material=Material(
                     diffuseColor=colour, emissiveColor=glow)))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
