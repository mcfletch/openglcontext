The GLinting Steel track editor
===============================

.. rst-class:: introduction

The track editor is where you draw a circuit for :doc:`GLinting Steel
<glisteel>` on a landscape and bake it into a world the game can stream and
drive. As you draw, the road is fitted to the ground under the line. The
editor is the worked example for :doc:`Building an editor <editing>`: the
tool modes, the plan view, surface picking and the handles are engine
features, and the editor is a track editor built from them.

.. figure:: images/gallery/showcase/track-editor.jpg
   :alt: A track editor: a circuit of numbered points drawn on a shaded relief map with contours, a lake and a river, and a tool palette down the left
   :class: shot

   A circuit drawn on a landscape. The designer drew the line; the road
   generator added the two bridges and the tunnel from the ground under it.

Drawing a circuit
-----------------

.. code-block:: bash

   pip install glisteel-editor
   glisteel-editor                    # a fresh landscape to draw on
   glisteel-editor --terrain canyon   # a different landscape to start from
   glisteel-editor --dem N47E008.hgt --centre 47.5,8.5 --datum 0   # real ground

The window shows a **map**: the landscape seen from straight above with an
orthographic projection (see :ref:`the plan view <plan-view>`). A metre
is the same number of pixels everywhere, so the line you draw is the line
the world gets.

1. Click the ground to place a point. Keep clicking until the circuit
   closes.
2. Press :kbd:`p` to see the circuit from an angle, and :kbd:`p` again to
   return to the map.
3. Choose *File → Bake a world* to write the world.
4. Choose *File → Drive it* to drive the circuit.

A :ref:`tool palette <tool-palette>` down the left sets what the pointer does:
drawing the route, setting where a lap starts, sculpting the land, placing
a spring, or panning. Input the current tool does not use goes to the map,
so a right drag pans and the wheel zooms.

:kbd:`ctrl-z` undoes the last change made by the *current tool*. Each tool
keeps its own history, because the tools edit different things; a single
shared history would undo whichever change happened last.

How the road is placed
----------------------

A route is a **plan**: points in world metres, in the order they were
drawn, with no heights. The :doc:`road generator <roads>` works out where
the road actually runs from the ground under that line. It smooths the
line, keeps it within a maximum grade, rounds the corners for the road's
design speed, and raises it onto a causeway where it would otherwise run
below the water line. If you raise the ground under the line, the road
climbs it the next time it is fitted.

Sculpting
~~~~~~~~~

Each sculpting stroke adds fractal detail in proportion to its height, so a
raised hill looks like land rather than a smooth bump. Strokes belong to the
landscape, not the road: they are saved with the project, and the road is
fitted onto them.

Rivers
~~~~~~

The project does not store river courses. It stores the springs where water
rises, and the courses are computed from the springs and the land. A stored
river bed would stay in place when the land under it changed.

Reading the land
----------------

The plan view draws the ground in two ways at once:

- :ref:`Shaded relief <relief-shading>` lights the ground's slope with a fixed low
  sun, so ridges and valleys show as different shades. The slopes are
  steepened before shading, because terrain a road can cross is gentle and
  would otherwise shade almost flat. The ground is still drawn at its true
  height.
- Contours show the height, at 10, 25, 50 or 100 metre intervals. They are
  drawn from the *landscape*, not from the baked ground, so a road's
  earthworks do not change the contours.

:kbd:`p` switches to a three-quarter view of the same scene, starting from
where the map was looking. The switch is immediate and rebuilds nothing.
Draw on the map; use the three-quarter view to judge how the land looks.

Projects
--------

A project is not the world. The world is baked, is large, and is rebuilt
whenever a decision changes. A project stores the decisions that produce the
world, as JSON a designer can read:

- a **base**, which the ground comes from;
- an ordered stack of **edits** on top of the base;
- the springs;
- the routes.

Baking a world
--------------

*File → Bake a world* writes a :doc:`3D Tiles <tiles3d>` world next to the
project file, using the :doc:`octree baker <baking>`. The circuit is stored
in the tileset's ``extras``, where the game reads it for the starting grid,
the lap timing and the autopilot.

``glisteel-bake`` does the same from a shell. With no other arguments it
bakes the circuit world that ships with the editor:

.. code-block:: bash

   glisteel-bake --output /tmp/world
   glisteel /tmp/world/tileset.json

Source and further reference
----------------------------

The editor is a separate distribution with its own repository,
`github.com/mcfletch/glisteel-editor
<https://github.com/mcfletch/glisteel-editor>`__. It contains only the
track-editing code: the landscape, road generation and baking come from
:doc:`OpenGLContext-editor <baking>` and the engine. The editor's
``README.md`` documents its tools and file format.
