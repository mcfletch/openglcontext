GLinting Steel
==============

.. rst-class:: introduction

GLinting Steel is a racing game built on OpenGLContext. You drive a car along
a forest road through a world too large to load at once; the world streams
in around the car as it moves. The game exercises the engine heavily: a
:doc:`3D Tiles <tiles3d>` world paging under a moving camera, a :doc:`road
<roads>` built over the ground it crosses, :doc:`rigid-body <physics>`
collision against tiles that have just arrived, all within a game's frame
budget. Features the game needs are added to the engine, and the game itself
stays small.

.. figure:: images/gallery/showcase/glisteel-forest-road.jpg
   :alt: A car on a two-lane road through dense forest, seen from behind and above
   :class: shot

   A lap of a baked 3D Tiles world, streamed in around the car as it drives.

Installing and driving
----------------------

.. code-block:: bash

   pip install glisteel glisteel-editor
   glisteel-bake --output /tmp/world      # hill country, half a million trees, an 8 km circuit
   glisteel /tmp/world/tileset.json       # drive it

The circuit is routed through the land. It runs on the ground where the
ground allows, on a walled causeway over low ground, on a viaduct across
valleys, and through a tunnel where none of those works.

``glisteel --autopilot`` drives a lap by itself. It is the quickest way to
see a lap, and it runs the same code as an opponent car.

To draw and bake a circuit of your own, use the :doc:`track editor
<glisteel-editor>`.

.. figure:: images/gallery/showcase/glisteel-viaduct.jpg
   :alt: A car crossing a railed viaduct over a forested valley, mountains beyond
   :class: shot

   The circuit crosses low ground on a walled causeway, valleys on a viaduct,
   and hills through a tunnel.

Engine features the game uses
-----------------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Part of the game
     - Engine feature
   * - The world
     - :doc:`Streamed 3D Tiles <tiles3d>`: tiles refined by screen-space error
       around the car, evicted behind it under a memory budget, and
       registered as static colliders as they arrive, so the car drives on
       the geometry it shows.
   * - The road
     - :doc:`Roads <roads>`: a centreline and a cross-section swept into a
       drivable surface, with earthworks, structures, barriers, banking and
       signs. The baked road stores its centreline in the tileset's
       ``extras``. The starting grid, the lap timing and the autopilot read
       the track from there.
   * - The car
     - :doc:`Physics & Collision <physics>`: a raycast vehicle on
       ``omi_physics``, stepped at a fixed rate, with contacts read in the
       step that produced them.
   * - The car's materials
     - :doc:`PBR <pbr>` and :doc:`the uber-shader <ubershader>`: painted
       metal, and a refractive canopy through
       ``KHR_materials_transmission``, so the cabin is visible through the
       glass.
   * - Reflections on the car
     - Image-based lighting. Painted metal mostly reflects its surroundings,
       so a car lit only by a sky gradient looks like a toy. The road passes
       the renderer a small panorama of the place it runs through: tree
       canopy with sky showing through it in the forest, a lit opening ahead
       and behind in a tunnel, open sky over a treeline on a viaduct.
   * - Trees and ground cover
     - :doc:`Vegetation <vegetation>`: the forest stored as a table beside
       the world, drawn as instanced sets selected for the view.
   * - Driver information
     - :doc:`The HUD <hud>` and :doc:`the overlay UI <overlayui>`: the
       in-world instruments, and the menus, settings and key-binding screens.
   * - Rivers and lakes
     - :doc:`Water <water>`.
   * - Distribution
     - :doc:`Packaging <packaging>`: a frozen bundle and a Debian package
       that carry their own interpreter, built with the engine's hooks.

The game's own code
-------------------

The game itself provides the car's handling, the camera positions, the lap
timing, the rules for what ends a run, and the steering modes.

Steering modes
~~~~~~~~~~~~~~

A keyboard key is either down or up, which carries much less information
than a driver's hands on a wheel. The game offers several ways to interpret
the same keys:

- turn the wheels, and hold the line between key presses;
- turn the wheels with no assistance;
- move the car sideways across the road;
- change lanes;
- let the car drive until you take over.

Each mode gives a different game on the same physics.

Crash detection
~~~~~~~~~~~~~~~

A crash is a contact reported by the physics engine, not a guess from how
close two cars are. Its severity is the speed at which the two bodies were
closing along the contact normal. The game reads this inside the fixed
physics step that produced the contact. Resolving the contact cancels that
closing velocity, so one step later a head-on impact would measure as zero,
and whether a crash registered would depend on frame timing.

Vehicle models
~~~~~~~~~~~~~~

None of the vehicles is modelled by hand. The player's car, its wheels and
the five traffic vehicles are generated by one Blender script, and the
``.glb`` files are build output.

Reproducible screenshots
------------------------

The screenshots of the game on this site come from a :doc:`recorded session
<telemetry>`, not a live drive. A replay drives the engine's clock from the
recorded frame times and restores the session's random state, so the car
reaches the same place on every machine. The screenshot is requested by
frame number rather than after a delay, because in a replay the frame number
is deterministic and the wall clock is not. Two runs write identical files.

.. code-block:: bash

   OPENGLCONTEXT_TELEMETRY_REPLAY=sessions/doc-lap.jsonl \
     glisteel world/tileset.json --view chase --no-hud --autopilot \
     --capture-frame 1297 --capture viaduct.png

Source and further reference
----------------------------

GLinting Steel is a separate distribution with its own repository,
`github.com/mcfletch/glisteel <https://github.com/mcfletch/glisteel>`__. Its
``README.md`` documents the game's modules, its handling constants and its
scenarios. Its worlds are baked by :doc:`glisteel-editor <glisteel-editor>`
using the :doc:`octree baker <baking>`.
