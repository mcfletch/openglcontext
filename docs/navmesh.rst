Navigation Meshes
=================

.. rst-class:: introduction

A **navigation mesh** is the walkable part of a level's floor, cut into
cells, with each cell joined to its neighbours. Given two points, it returns a
route between them. ``OpenGLContext.nav.navmesh`` builds one from a level's
*collision mesh* (the triangles the character's capsule is tested against)
and searches it.

.. code-block:: python

   from OpenGLContext.nav import navmesh

   navmesh.build(points, triangles)   # walkable cells out of a triangle soup
   navmesh.from_world(world)          # the same, from a physics world
   mesh.cell_at(point)                # which cell a point stands on
   mesh.path(start, goal)             # the route, pulled taut
   mesh.corridor(start, goal)         # the cells it crosses
   mesh.visible(here, there)          # can a body walk straight between them
   mesh.random_point()                # somewhere to go

.. _using:

Using it
--------

From triangles you already have:

.. code-block:: python

   import numpy as np
   from OpenGLContext.nav import navmesh

   # A four-metre floor, as two triangles wound to face up.
   points = np.array([(0, 0, 0), (4, 0, 0), (4, 0, 4), (0, 0, 4)], dtype='d')
   triangles = np.array([(0, 2, 1), (0, 3, 2)], dtype='i')

   mesh = navmesh.build(points, triangles)
   len(mesh)                             # 2
   mesh.cell_at((1.0, 0.0, 1.0))         # 0
   mesh.cell_at((9.0, 0.0, 9.0))         # None -- off the mesh
   mesh.path((0.5, 0.0, 0.5), (0.5, 0.0, 3.5))
   # [(0.5, 0.0, 0.5), (0.5, 0.0, 3.5)]

From a loaded level's :doc:`physics world <physics>`, which is the usual way:

.. code-block:: python

   from omi_physics import model
   from omi_physics.world import PhysicsWorld
   from OpenGLContext.nav import navmesh

   world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
   shape = world.add_shape(model.Shape.trimesh(points, triangles))
   world.add_body(model.Motion(type=model.STATIC),
                  collider=model.Collider(shape=shape), position=(0, 0, 0))

   mesh = navmesh.from_world(world, max_slope=50.0)
   len(mesh)                             # 2 -- the same floor, found in the world
   mesh.random_point(seed=3)             # (2.6666666666666665, 0.0, 1.3333333333333333)

A bot calls ``mesh.path(bot.position, mesh.random_point())`` when it wants a
new destination. Build the mesh once per level and keep the ``NavMesh``. Call
``path()`` when a bot makes a decision, not every frame: the bot follows the
points it was given until it chooses somewhere else.

Built at load time
------------------

The mesh is built from geometry that is already in memory when the level
loads. It is not read from navigation data shipped with the level. As a
result:

- Every level has a navmesh - any map that loads into a collision world gets
  one, whatever tools it was made with.

- The mesh matches the geometry - change the floor, move a wall or load a
  different map, and the next build describes what is there. There is no
  second file to keep in step.

- No other content is needed - the only input is the collision mesh, which the
  engine already has.

The cost is paid at load time. Build time is proportional to the number of
triangles, and the result is kept in memory as arrays.

.. _building:

Building it
-----------

``build(points, triangles, max_slope, clearance)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``points`` is an ``(N, 3)`` array of world positions in metres, and
``triangles`` is an ``(M, 3)`` array of indices into it: a triangle soup,
which is the form a level's collision geometry takes. ``build`` returns a
``NavMesh``, and ``len(mesh)`` is the number of walkable cells.

A triangle becomes a cell when it faces upward and is no steeper than
``max_slope``. A downward-facing triangle is a ceiling, however level it is,
and is dropped.

Cells are joined to their neighbours **by shared edges, matched by
position**, not by vertex index. In a collision soup the same corner appears
once for each triangle that uses it, each time with a different index, so
matching by index would leave every cell unconnected. Positions are welded on
a 0.1 mm grid: finer than any detail a level has, and coarser than the
rounding error from transforming a mesh into world space. The shared edge
between two neighbours is kept as a **portal**, which the
:ref:`string pull <pull>` draws the route through.

``from_world(world, max_slope, clearance)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Builds a navmesh from an ``omi_physics`` world, which is how a game usually
calls it. It takes every static trimesh collider in the world, offsets each
by its body's position, and builds one mesh from all of them. Characters walk
on the collision mesh, so a navmesh built from the same triangles agrees with
it; a separate description of the geometry could differ.

A world with no static trimesh gives an empty ``NavMesh``, not an error:
``len(mesh) == 0``, ``cell_at()`` and ``random_point()`` return None, and
``path()`` returns an empty list.

.. _numbers:

Parameters and defaults
~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Name
     - Default
     - Unit
     - What it sets
   * - ``DEFAULT_MAX_SLOPE``
     - 50.0
     - degrees from horizontal
     - The steepest triangle that becomes a cell.
   * - ``DEFAULT_CLEARANCE``
     - 0.0
     - metres of headroom
     - The headroom a body needs above a cell; 0 turns the test off.
   * - ``STAND_REACH``
     - 2.5
     - metres
     - How far below a point ``cell_at`` looks for its floor.
   * - ``STAND_TOLERANCE``
     - 0.5
     - metres
     - How far *above* a point its floor may be and still count.

**A navmesh is built for a particular body.** One character can climb a slope
that another cannot, so ``max_slope`` is an argument, not a constant. Pass
the avatar's own ``CharacterCapabilities.maxSlope``. That also defaults to 50
degrees, and it is the limit the walking code uses to decide whether a
surface can be stood on. See :ref:`character` for the rest of the character's
settings.

``clearance`` makes walls into obstacles. A wall contributes no walkable
triangles of its own, so the floor on each side of it is walkable, and
without a headroom test the two sides are joined straight through the wall.
The test compares each cell's bounding box with the bounding boxes of the
unwalkable triangles. (A point test would pass through a wall, because a wall
in a level is a plane with no thickness.) It also removes the floor right
next to a wall, where a body, which has a radius, cannot stand.

The test is **off by default** (``clearance=0.0``), because bounding boxes are
coarse for the large triangles that real level walls are made of. On the
``oa_dm1`` map it removes 1092 of 1220 floor cells, most of them nowhere near
a wall. On small, axis-aligned geometry it is exact. If you know your
geometry suits it, pass the headroom your body needs; otherwise the whole
walkable floor is kept.

.. _asking:

Queries
-------

``cell_at(point, reach, below)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns the cell the point is standing on, as an index into ``mesh.cells``,
or ``None``. This is the cell *under* the point, so where two floors are
stacked, a gallery and the hall beneath it give different answers for the
same ``(x, z)``. A point more than ``reach`` above every floor belongs to no
cell, so a point in the air over a pit does not bind to the bottom of the pit.
A point up to ``below`` under the floor still counts: a capsule's centre is
above the floor, and on a slope a sample taken from the next triangle can fall
slightly under this cell's plane.

``path(start, goal)``
~~~~~~~~~~~~~~~~~~~~~

Returns a list of ``(x, y, z)`` points to walk, from ``start`` to ``goal``.
An A\* search over the cells finds the :ref:`corridor <corridor>`, the
corridor is :ref:`pulled taut <pull>` through its portals, and then every
corner that the mesh lets the line see past is dropped.

An **empty list** means that either end is off the mesh, or that nothing
connects them. This is a normal result, not an error: a bot on a ledge with
no way down has nowhere to walk and should do something else.

.. _corridor:

``corridor(start, goal)``
~~~~~~~~~~~~~~~~~~~~~~~~~

Returns the cells a route crosses, in order, as indices into ``mesh.cells``.
It is empty in the same cases as ``path()``. Each cell shares an edge with
the next, and ``mesh.portals[(here, there)]`` gives the edge between any two
of them. Use it to follow the corridor yourself: to draw the search, to find
which rooms a route passes through, or to keep a bot's corridor and pull it
again as the bot moves. To get points to walk, use ``path()``.

.. _visible:

``visible(start, goal, reach, below)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns whether a body could walk *straight* from one point to the other:
``True`` when an unbroken run of cells covers the line between them. A wall,
a pit or the edge of the floor breaks the run; a ramp does not. The run is
followed across the mesh, not measured in the horizontal plane, so a line
drawn over a floor on a lower storey does not count as a line along it.

A bot can call it before paying for a whole path. ``path()`` calls it to drop
corners that nothing stands behind.

``random_point(seed)``
~~~~~~~~~~~~~~~~~~~~~~

Returns a random cell centre, as a destination for a bot with no orders, or
None for an empty mesh. With a ``seed`` it returns the same point every time,
so a match can be replayed from its inputs. Without one it draws from the
session's navigation entropy stream (see :ref:`randomness`), which advances
with each call.

.. _pull:

The string pull
~~~~~~~~~~~~~~~

A\* returns cells, and the simplest route through cells joins their centres.
That route zigzags. Triangle centres are not on the line a person would walk,
so a bot crossing an empty room follows a staircase and turns at corners that
are not there.

The pull runs a funnel through the portals instead. The two edges of a cone
are narrowed by each portal in turn, and a corner is placed where they cross.
The resulting line touches the geometry only where the geometry turns it, and
on open floor it is just two points, start and goal.

The pull works in the **horizontal** plane. Heights come from the portals the
line passes through, so a route up a ramp climbs with it.

**A funnel is only taut within its corridor**, so the choice of cells affects
the route. Between two cells there are many equally short runs of cells. On a
grid of triangles, a staircase along two sides costs the same as the
diagonal, and a corridor chosen by whichever run the search queue reached
first can cross a room to a wall and then follow the wall. Two measures keep
the line straight:

- Step cost - the search costs each step by how much further a walker has to
  go to reach the portal it leaves by, measured to the *nearest point* on
  that portal. Measured to the middle of the portal, or between cell centres,
  a diagonal would cost the same as its two sides, and ties would decide the
  route.

- Dropping corners - after the pull, every corner that
  :ref:`visible() <visible>` can see past is dropped. A corner is either
  against the geometry or only against the edge of the corridor, and only the
  first kind is a turn a walker has to make. Each corner kept is the furthest
  one still visible from the last, which can only shorten the route.

.. _navmesh-demo:

Seeing it work
--------------

.. figure:: images/demos/navmesh_demo.jpg
   :alt: An overhead view of a square room with two walls across it: the floor is covered in green wireframe triangles, an amber line zigzags from a blue sphere around both walls to an orange sphere, and a straighter cyan line follows the same route

   :doc:`python tests/navmesh_demo.py <tutorials/navmesh_demo>` - a 16 m room
   with two walls that force the route into a zigzag. The green wireframe is
   the navmesh: 416 walkable cells from the 516 triangles of floor and wall
   passed to ``build()``. The dark bands beside each wall are the cells that
   ``clearance=1.8`` removed. Amber is the corridor drawn through the cell
   centres, cyan the same corridor after the string pull. Press ``g`` for the
   next goal and ``r`` for a random one.

Each new path prints the number of cells in the corridor and how much the
pull saved:

.. code-block:: bash

   $ python tests/navmesh_demo.py
   navmesh 416 walkable cells from 516 triangles (max slope 50.0 degrees, clearance 1.8 m)
   goal (14.0, 14.0) | corridor 77 cells
     centres 79 points 48.82 m -> pulled 6 points 33.34 m (-31.7%)

The 79 points of the zigzag become six, and the walk is 15.5 m shorter. The
six points are the two ends and the four corners where the walls turn the
route: out of the left-hand room round the end of the first wall, diagonally
across the channel between the walls, and out round the end of the second.

.. _navmesh-limits:

Limits
------

- One triangle per cell - neighbouring walkable triangles are not merged into
  larger convex regions, so the search runs over as many cells as the floor
  has triangles. Merging them would reduce the cell count without changing
  the interface.

- Static - the mesh describes the geometry it was built from. A door that
  opens, a bridge that falls or a crate that is pushed is not in the mesh
  until it is built again.

- No body radius - routes are kept off the walls only by the ``clearance``
  test removing the cells next to them. That is decided when the mesh is
  built, not by the character asking for a path.

- Bounding-box headroom - the headroom test compares bounding boxes, which is
  exact on small axis-aligned geometry and coarse on the large triangles a
  level's walls are made of. It does not measure each blocker's distance from
  the cell, so ``clearance`` defaults to 0 and the whole walkable floor is
  kept.

- Distance is the only cost - a step is weighted by how far a walker travels
  to reach the portal it leaves by, so the search prefers the shortest walk.
  Danger, cover and terrain a character should avoid are not weighted.

- Short, not proven shortest - the corridor is chosen by a cost measured to the
  nearest point on each portal, and the pulled line then drops the corners it
  can see past. On a floor cut into triangles this gives the line a person
  would take, but it is not a proof of the shortest walk across the room.

- ``cell_at`` checks every cell - it compares the point with every cell's
  footprint box, then tests the few that contain it, so its cost grows
  linearly with the cell count. A level large enough for that to matter needs
  a spatial index over the cells.
