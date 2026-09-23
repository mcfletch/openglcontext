Water
=====

.. rst-class:: introduction

``OpenGLContext.scenegraph.water`` models water in two independent parts. The
**surface** is what you see from outside: a sheet on a lake, a ribbon down a
river, and a wave field you can query for its height. The **medium** is what
being inside the water does to the view, to the sound mix and to the body. A
game can use either part alone: it can have lakes that nobody enters, or flood
a level whose water is never drawn.

.. figure:: images/demos/water_demo.jpg
   :alt: Three rectangular pools cut in sand, each carrying a grid of orange floats: the left grid flat, the middle gently uneven, the right thrown about by large waves, with a river running across behind them

   ``python tests/water_demo.py``: the three named styles side by side, with a
   river behind them. See :ref:`water-demo`.

.. code-block:: python

   from OpenGLContext.scenegraph.water import (
       STILL, FLOWING, CHOPPY,          # how a body of water moves
       water_surface, water_ribbon, water_glints,   # meshes to draw it
       wave_height, wave_normal,        # the surface at a point and time
       Volume, Volumes, submerge,       # where the water is, and being in it
   )

How water moves: ``WaterStyle``
-------------------------------

A ``WaterStyle`` dataclass describes how a body of water moves. Three styles
are predefined:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Unit
     - ``STILL``
     - ``FLOWING``
     - ``CHOPPY``
   * - ``amplitude``
     - metres, trough to crest
     - 0.0
     - 0.09
     - 0.42
   * - ``wavelength``
     - metres between crests
     - 11.0
     - 4.5
     - 7.0
   * - ``speed``
     - metres per second the crests travel
     - 0.0
     - 1.6
     - 2.4
   * - ``steepness``
     - how far the normals tilt on top of the displacement
     - 0.045
     - 0.063
     - 0.099
   * - ``flow``
     - metres per second the surface drifts, ``(x, z)``
     - (0, 0)
     - (1, 0)
     - (0, 0)

- ``STILL`` is a pond. The surface does not move; the ripple is only in the
  normals, so it shows in the reflected light.
- ``FLOWING`` is a river. Small crests travel downstream and the surface drifts
  with them.
- ``CHOPPY`` is water in wind, with waves high enough to move the shoreline.

``LAKE`` is a fourth style, for open water seen from a distance. To get other
motion, create your own ``WaterStyle`` with different values.

Where ``flow`` is not zero, it also sets the direction the crests travel.
``style.moving()`` returns whether the style changes with time. Use it to skip
updating the clock for water that does not move.

The wave field
~~~~~~~~~~~~~~

The surface is the sum of **three crossing sine waves**, computed from
*world* position and time rather than from a mesh's own coordinates. This has
two results:

- Sheets that meet stay joined. A river flowing into a lake has the same height
  as the lake along the join, because both compute the same function at the
  same place.

- You can query the surface. ``wave_height(style, x, z, when)`` and
  ``wave_normal(style, x, z, when)`` take scalars or NumPy arrays and return the
  surface's height and normal there. Use them for buoyancy, a boat's waterline
  or a splash.

.. code-block:: python

   from OpenGLContext.scenegraph.water import CHOPPY, wave_height

   lift = wave_height(CHOPPY, boat[0], boat[2], when=context.time)

.. _surfaces:

Drawing water
-------------

A lake: ``water_surface``
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   mesh = water_surface(x0, x1, z0, z1, level=12.0,
                        resolution=33, style=CHOPPY, on_gpu=True)

``water_surface`` builds a flat sheet over a rectangle, at height ``level``.
``resolution`` is the number of vertices along each side. For still water the
ripple is in the normals, so resolution matters little. For choppy water it
limits how much of the wave the mesh can show: a mesh that is coarse compared
with the wavelength shows a flat sheet with odd normals. Use at least a few
vertices per ``wavelength``, or let :ref:`mesh_across <water-mesh-density>`
choose.

A river: ``water_ribbon``
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   mesh = water_ribbon(course, width=8.0, style=FLOWING, lift=0.15)

A sheet has one level, so it cannot follow a river downhill.
``water_ribbon`` builds a strip along a course instead. ``course`` is an
``(N, 3)`` array of world points giving where the water runs and how high it
is there. ``width`` is the width in metres: one number, or one per point for a
river that widens downstream. The surface lies *across the flow* at every
point, so a bend in the course is a bend in the ribbon. ``lift`` raises the
surface above the course, for a course that traces the river bed rather than
the water surface.

.. _glints:

A distant river: ``water_glints``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   mesh = water_glints(course, width=8.0, spacing=60.0, style=FLOWING)

A river a kilometre away is two pixels wide and mostly hidden by trees. What
the eye sees is flashes of light from the surface between them.
``water_glints`` draws those flashes as a few small quads, in place of a full
ribbon. It is the river's far level of detail.

``spacing`` is the distance between glints, in metres. Increase it with
distance. A coarser tile also covers more ground, so a spacing that grows
with the tile's geometric error keeps the number of glints per tile roughly
constant. ``size`` is the fraction of the river's width each glint covers. The
glint positions depend on distance along the course, not on random numbers,
so a world baked twice has its glints in the same places.

.. _on_gpu:

Animating on the GPU: ``on_gpu``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All three builders take ``on_gpu``. Without it, the wave is built into the
vertices at time ``when``. Use that for still water, or when you need the
mesh vertices to match the surface. With ``on_gpu=True``, the mesh is built
**flat** and the style is passed to the vertex shader, which displaces it:

.. code-block:: python

   mesh = water_surface(0, 200, 0, 200, level=0.0, style=CHOPPY, on_gpu=True)
   ...
   mesh.wave_time = context.time      # once a frame; nothing is re-uploaded

The mesh is uploaded once, and each frame sets only a few uniforms. Skinning
uses the same approach for a pose.

Do not use both methods on one mesh, or the wave is applied twice. ``Shape``
sets the wave uniforms for every shape it draws, turning the wave off for
shapes that are not water, so the ground beside a lake does not ripple.

A GPU-displaced sheet casts its shadow from the flat mesh, because the shadow
depth pass does not set the wave uniforms. A moving surface can then show
bands of its own shadow. Turn shadows off (``OPENGLCONTEXT_SHADOWS=0``) in
scenes where that shows.

.. _water-mesh-density:

How finely to mesh a sheet
~~~~~~~~~~~~~~~~~~~~~~~~~~

A sheet is meshed once across its whole area, so no single vertex count suits
both a pond and a lake. ``mesh_across(side, style)`` returns a vertex count
for a sheet ``side`` metres across, based on the style's *wavelength*:

- ``MESH_PER_WAVE`` (4) samples per wavelength;
- at most ``MESH_LIMIT`` (33) vertices across, because a sheet is one draw and
  its size counts in the frame and in the file of a baked world;
- at least ``MESH_FLOOR`` (9) vertices across for any style with a non-zero
  amplitude.

With too few vertices per wave, the wave aliases: it flattens, or shows up as
a longer wave that is not in the field. Two samples per wave is the Nyquist
limit. In practice, whether two samples land on the crests or on the zero
crossings depends on where the sheet starts. Measured over a 12 m sheet, two
samples per wave keep 73% of the wave's height and four keep 89%. Over 40 m,
the figures are 84% and 96%. For large sheets both settings reach
``MESH_LIMIT``, so the choice makes no difference there.

The fine ripple is not in the mesh. The fragment shader's ``waveRipple`` tilts
the surface normal, so the glitter looks the same at any mesh density and the
mesh only needs to carry the swell.

.. _media:

Being in the water: media and volumes
-------------------------------------

A ``Medium`` describes one substance from the inside. Three are predefined.
The values are chosen for games; no standard specifies them:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Name
     - ``visibility``
     - ``muffle``
     - ``harm``
   * - ``water``
     - 9 m
     - 0.75
     - 0
   * - ``slime``
     - 4.5 m
     - 0.85
     - 12 health per second
   * - ``lava``
     - 2 m
     - 0.90
     - 32 health per second

- ``visibility`` is the distance, in metres, over which the view fades to the
  medium's ``color``.
- ``color`` is in **linear** RGB. The fog blends in linear HDR before tone
  mapping, so the colours are much darker than water looks from above. Water
  *absorbs* light from what is behind it. A pale, long-range fog would look
  like haze in air.
- ``muffle`` is how much of the sound mix's high frequencies is removed, from
  0 to 1. The predefined values stay below 1, because complete silence sounds
  like a fault.
- ``harm`` is damage per second, for a game to apply.

The substances are in the ``MEDIA`` dictionary in
``OpenGLContext.scenegraph.water.medium``, keyed by name. To add one, add a
``Medium`` to it. A name that is not in ``MEDIA`` is treated as water
(``UNKNOWN``), not as dry air.

Where the water is
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from OpenGLContext.scenegraph.water import Volume, Volumes

   volumes = Volumes([
       Volume.below(minimum=(-40, -40), maximum=(40, 40), level=2.0, depth=30.0),
       Volume(minimum=(10, -8, 10), maximum=(14, -4, 14), medium='lava'),
   ])
   volumes.medium_at(point)               # 'water', 'lava' or '' for dry air

A ``Volume`` is an axis-aligned box in world metres. ``Volume.below`` makes the
box under a water level. The boundary counts as inside, so a body exactly at
the waterline is in the water.

Where boxes overlap, ``medium_at(point, rule=...)`` chooses the result:

- ``'worst'`` (the default) returns the most harmful medium, for a body half in
  a pool and half in the lava beneath it;
- ``'smallest'`` returns the medium of the smallest box. Use it when the boxes
  are the bounds of a spatial partition, such as BSP leaves or tiles.

Putting the camera under water
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from OpenGLContext.scenegraph.water import medium_fog, submerge

   self.fog = medium_fog()                       # once, bound into the scene
   ...
   name = submerge(self, volumes, self.platform.position)   # once a frame

``medium_fog()`` returns a :ref:`Fog <fog>` node that starts switched off.
Call ``submerge`` once a frame with the viewer's position. It sets the
context's ``fog`` to the medium's colour and visibility, and sets the audio
engine's whole-mix :ref:`muffle <mixer>` to the medium's ``muffle``. It
returns the name of the medium, or ``''`` for dry air, so the caller can report
it or apply ``harm``. Because the effect is fog with depth, not a coloured
overlay, nearby objects stay clear while distant ones fade.

Every part is optional:

- ``volumes`` may be ``None``, for a world with no water.
- A context with no ``fog`` attribute gets no fog change.
- On a machine with no sound, the audio device is not opened just to muffle
  silence.

``volumes`` can be any object with a ``medium_at(point)`` method. A game whose
water comes from a BSP's content flags can pass its own object, with no
conversion.

.. _water-demo:

Demo
----

``python tests/water_demo.py`` shows the three named styles side by side over
one bed, with a ``water_ribbon`` running behind them along a course that drops
from one end to the other. Each pool holds a grid of floats placed on the
surface with ``wave_height`` once a frame, so you can see the scale of the
waves. Over one pool, ``STILL`` (left) is flat to the millimetre, ``FLOWING``
(middle) spans 0.34 m from trough to crest, and ``CHOPPY`` (right) spans
1.58 m. Every sheet is built with ``on_gpu=True``, so a frame costs four
``wave_time`` writes and no uploads. Behind the river is a 180 m ``LAKE``,
meshed by ``mesh_across``. The demo runs with ``OPENGLCONTEXT_SHADOWS=0``.

Keys:

- :kbd:`v` moves the camera under the middle pool, and prints the medium
  ``submerge`` found as the camera crosses the surface:

  .. code-block:: text

     medium under the camera: water
     medium under the camera: air

- :kbd:`h` prints the ``wave_height`` at each pool's centre:

  .. code-block:: text

     STILL    surface at +0.000 m (t=0.05s)
     FLOWING  surface at -0.020 m (t=0.05s)
     CHOPPY   surface at -0.283 m (t=0.05s)

- :kbd:`d` switches the lake between ``mesh_across`` and a fixed nine vertices
  across, and prints how much of the swell each keeps, measured against the
  wave field:

  .. code-block:: text

     lake 180 m across, meshed from its wavelength: 33 vertices, 1.6 samples per wave, keeps 98% of its swell
     lake 180 m across, meshed the old way:          9 vertices, 0.4 samples per wave, keeps 47% of its swell

  Nine vertices across 180 m is one every 22 m against a 9 m wave. That is
  less than one sample per wave, below the Nyquist limit, so the wave flattens
  and reappears as a longer wave.

A minimal application with a body of water, and a check for whether the
camera is in it:

.. code-block:: python

   import time

   from OpenGLContext.scenegraph.basenodes import Appearance, Shape, sceneGraph
   from OpenGLContext.scenegraph.water import (
       CHOPPY, Volume, Volumes, medium_fog, submerge, water_surface,
   )

   # Built once: 80 m square at sea level, meshed 65 x 65, moved by the card.
   sheet = water_surface(-40, 40, -40, 40, level=0.0, resolution=65,
                         style=CHOPPY, on_gpu=True)
   lake = Shape(geometry=sheet, appearance=Appearance(material=sheet.material))
   scene = sceneGraph(children=[lake, medium_fog()])

   # Where the water is, for a body that may end up inside it.
   volumes = Volumes([Volume.below(minimum=(-40, -40), maximum=(40, 40),
                                   level=0.0, depth=30.0)])
   start = time.monotonic()


   def step(context):
       """Once a frame: move the surface, and put the camera in or out of it."""
       sheet.wave_time = time.monotonic() - start
       return submerge(context, volumes, context.getViewPlatform().position)

Limits
------

- No fluid simulation. The wave field is analytic (three sine waves), so it is
  cheap to evaluate and gives the same surface on every run. Water does not
  find its own level or pour.

- No physics body. Buoyancy and drag code can read ``wave_height``; the object
  being moved decides what to do with it.

- Reflection and refraction come from the material. Water is a :doc:`PBR
  <pbr>` material with transmission and an index of refraction of 1.33. Its
  reflections come from the :ref:`environment lighting <environment-lighting>`.
  There is no planar reflection pass and no screen-space refraction.

- A volume is a box. To give a sloping river a medium, cut it into several
  boxes.

- The shoreline is where the mesh meets the ground. Nothing blends the edge,
  and a sheet that ends inside a hill shows its edge.
