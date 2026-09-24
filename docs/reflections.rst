Reflections
===========

.. rst-class:: introduction

A surface marked as a mirror reflects the scene in front of it: a bathroom
mirror, a polished floor, a shop window, a still pool. Every other smooth
surface reflects the :ref:`environment probe <environment-lighting>`, which is
the sky. Marking a surface is how an application opts into the cost, and each
mirror says how much it is worth, so a level can hold a dozen of them.

.. figure:: images/demos/mirrors_demo.jpg
   :alt: A hall with a polished dark floor reflecting four coloured columns and the lamps over them, a large mirror on the far wall showing the room behind the viewer, small mirrors down the left wall, and a pool in a stone rim

   ``oglc-mirrors``: a floor, a wall mirror, a corridor of small mirrors and a
   pool, each reflecting the room. See :ref:`reflections-demo`.

.. code-block:: python

   from OpenGLContext.scenegraph.reflector import PlanarReflector

   material.reflector = PlanarReflector(interval=2)

Making a surface a mirror
-------------------------

A ``PlanarReflector`` on a ``PBRMaterial``'s ``reflector`` field makes every
surface drawn with that material a mirror, each in the plane of its own mesh.
The node's fields are read every frame, so a change takes effect on the next.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Default
     - Meaning
   * - ``scale``
     - 0.5
     - The reflection's resolution as a share of the mirror's rectangle on
       screen, each way. 0.5 is a quarter of the pixels.
   * - ``interval``
     - 3
     - The most frames a visible reflection goes without being drawn again. A
       moving object's reflection lags by up to this many frames.
   * - ``priority``
     - 1.0
     - Weight against the other mirrors in view when a frame cannot draw them
       all.
   * - ``distortion``
     - 0.0
     - How far a unit of the surface normal's tilt from the plane pushes the
       lookup, in view widths: the normal map breaking the reflection up.
   * - ``enabled``
     - True
     - False leaves the node in place and the surface reflecting the probe.
   * - ``replace``
     - False
     - True shows the reflection in place of the surface's shading.

One reflector held by the materials of a set of mirrors tunes them together.
``varied()`` gives one mirror its own:

.. code-block:: python

   corridor = PlanarReflector(interval=3, scale=0.35)
   for material in corridor_materials:
       material.reflector = corridor
   hero.reflector = corridor.varied(interval=1, priority=4.0)

The material shades what is reflected. Its base colour tints the reflection,
and its metalness and roughness weight it through the same split-sum term the
sky's reflection goes through. A silvered mirror is metallic 1, roughness 0.
A polished floor is a dielectric with a low roughness, which reflects faintly
looking straight down and strongly at a glance. Up to a roughness of 0.6 a
rough mirror reads a blurred copy of its reflection; above it the surface
reflects the probe, which is as blurred as that reflection would be.

With ``replace`` set, the surface shows the reflection as drawn and nothing of
its material: no tint, no Fresnel. Where there is nothing to reflect it shows
the sky. That is an object that is only a mirror, such as a magic window.

A mirror must be flat. Its plane is fitted to the mesh: the mean of its points
and the direction they vary least in, turned to the side its triangles face. A
mesh with a point more than 1% of its size off that plane is reported once in
the log and reflects the probe.

Water is a mirror
~~~~~~~~~~~~~~~~~

Geometry with a ``waveStyle`` is water, and water is a mirror whatever its
material. ``water_material()`` and the ``water`` hook give the material
``reflector.WATER``, which is redrawn every frame and broken up by the ripple;
water whose material names no reflector reflects the same way. See
:doc:`water` for the surface itself.

.. _mirror-hook:

Mirrors in a model: the ``mirror`` hook
---------------------------------------

A glTF marks a mirror with the ``OGLC_hook`` tag
(:ref:`hooks <gltf-hooks>`), and the tag means different things in its two
places.

On a **material**, every surface drawn with it is a mirror, shaded by the
material the file carries. On an **object**, every surface of that object
shows only its reflection (``replace``): its own materials are set aside.

.. code-block:: text

   OGLC_hook = {"kind": "mirror", "scale": 0.5, "interval": 2, "priority": 1.0}

``OGLC_hook = "mirror"`` is the shorthand with every default. The parameters
are the node's fields above, all optional: ``scale``, ``interval``,
``priority``, ``distortion``, and ``replace`` where the holder's default is
not the one wanted. The Blender add-on's panel has a field for each
(``tools/blender/README.md``). A material carrying a reflector is written back
out with the tag by the glTF writer, so a world loaded and saved again keeps
its mirrors.

How reflections are drawn
-------------------------

A reflection is the scene seen through another camera: the view mirrored in
the mirror's plane, with a projection cropped to the mirror's rectangle on
screen and a near plane lying on the mirror, which clips what stands behind
it. That is an ordinary view to the :doc:`multi-view <multiview>` machinery,
so the frame's reflections are drawn together, before the views that show
them:

1. For each view and each mirror in it, the mirror's rectangle on screen is
   found and grown by a tenth each side, a guard band for a turn of the head
   between redraws.
2. A schedule chooses which reflections to draw this frame (below).
3. Each is a tile of one texture, the reflection atlas, in linear HDR.
4. Every shape that can serve several views is drawn once for all the mirror
   views that see it, through the ``vertex`` or ``geometry`` strategy. What a
   shared draw refuses -- terrain, vegetation, particles -- is drawn per
   mirror view.
5. Each mirror, drawn in each view, projects its own world position through
   the matrix its tile was drawn with to find its texel.

Step 5 is what lets a reflection be reused. A tile a frame or two old is read
where the old mirrored camera saw each point, so a static object stays put in
the mirror; only parallax between the old eye and the new is off, and a
camera that has moved far enough for that to exceed a texel redraws the tile.

A reflection does not contain other mirrors (one bounce), transparent shapes,
or the sky: where the mirror view drew nothing, the surface reflects the
probe.

The budget
----------

The budget is for a whole frame, across every view.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Setting
     - Environment variable
     - Default
     - Meaning
   * - ``planarReflections``
     - ``OPENGLCONTEXT_PLANAR_REFLECTIONS``
     - on
     - Mirrors and water reflect the scene. Off, every reflector reflects the
       probe. Read every frame, so a settings screen can switch it.
   * - ``reflectionViews``
     - ``OPENGLCONTEXT_REFLECTION_VIEWS``
     - 0
     - The most mirror views drawn in a frame. 0 takes the strategy's own:
       16 under ``vertex`` or ``geometry``, 2 under ``sequential``, where each
       costs a draw of the scene.
   * - ``reflectionSeparateViews``
     - ``OPENGLCONTEXT_REFLECTION_SEPARATE_VIEWS``
     - 4
     - Of those, the most that also draw the shapes a shared draw refuses,
       each of which costs a draw per mirror view.
   * - ``reflectionAtlas``
     - ``OPENGLCONTEXT_REFLECTION_ATLAS``
     - 0.5
     - The atlas's size as a share of the window's pixels. A frame's drawn
       tiles are budgeted to half the atlas, which is what its shelves pack.
   * - ``reflectionMilliseconds``
     - ``OPENGLCONTEXT_REFLECTION_MS``
     - 0 (none)
     - A GPU time the reflections aim to stay under. The texels drawn are
       scaled by the measured time, between a quarter and all of the budget.

The first four are counts and sizes, so a capture or a visual baseline draws
the same reflections every run. The time target adapts to the machine, which
is why it is off unless set.

Each frame, the schedule weighs every mirror in view:

1. A mirror with no tile it can use -- none yet, or one drawn for another view,
   plane or size -- must be drawn.
2. A mirror whose tile has reached its ``interval`` must be drawn.
3. A mirror whose camera has moved far enough that its reused tile would be
   off by more than a texel must be drawn.
4. Every other mirror is optional, and drawn while the budget has room, the
   one with the largest screen area times priority times frames since its last
   draw first.

Where the mirrors that must be drawn do not fit, the highest-scoring go first
and the rest are drawn at half scale before any is left out. A mirror left out
keeps its old tile, or reflects the probe if it has none. The frames since a
mirror's last draw raise its score every frame it is passed over, so none is
left out for long. A tile being drawn outranks one being kept for later: where
the atlas cannot hold both, the kept one gives up its room.

With room to spare every mirror is redrawn every frame. ``interval`` is what a
mirror is allowed when the budget is short, and what lets a corridor of small
mirrors take turns.

Measuring it
~~~~~~~~~~~~

The developer overlay's Render section shows each frame's mirror views, the
draws they took, the texels they filled and their GPU time, measured two
frames late so nothing waits on the GPU. Session :doc:`telemetry` records the
wall-clock time of the mirror views as the ``reflections`` phase of the frame,
and samples the overlay's rows.

.. _reflections-demo:

Demos
-----

``oglc-mirrors`` builds a hall in code with every kind of mirror on this page:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Key
     - What it shows
   * - ``r``
     - Reflections on and off: ``planarReflections``.
   * - ``b``
     - The mirror views a frame may draw: the strategy's own, then 1, 2 and 4.
       With 1, the mirrors take turns and the stale ones are read by
       projection.
   * - ``i``
     - The corridor's shared ``interval``: 3, 1 and 6 frames.
   * - ``o``
     - The round window on the right wall between ``replace`` and a shaded
       glass mirror.

``tools/blender/demos/mirrors.glb`` is the same kind of hall authored in
Blender, every mirror tagged with the add-on's panel: the floor, the far mirror
and the corridor as materials, the pool as ``water``, the window as an object.
Open it with ``oglc-view tools/blender/demos/mirrors.glb``;
``tools/blender/demos/mirrors.py`` builds it again.

Limits
------

- Flat surfaces only. A curved mirror, a chrome sphere or a car body reflects
  the probe.
- One bounce: a mirror seen in a mirror reflects the probe.
- A moving object's reflection lags by its tile's age, up to its ``interval``
  frames. ``interval=1`` on a reflector where that shows.
- Transparent shapes are not drawn into any reflection.
- Where a mirror reflects nothing, it shows the environment probe. The probe is
  the scene's HDR or cubemap sky where it has one, and a procedural one
  otherwise, which a VRML97 ``Background``'s colours do not change.
- Sixteen mirror views per submission; more cost another submission.
- A driver whose fragment stage has 32 texture units or fewer compiles
  reflections out, and every mirror reflects the probe.
