Water
=====

.. rst-class:: introduction

Water is two things that meet at its surface. From outside it is a **surface**
— a sheet on a lake, a ribbon running down a river, a wave field you can ask
the height of. From inside it is a **medium** — what being in it does to the
view, to the mix and to the body. ``OpenGLContext.scenegraph.water`` holds
both, and they are independent: a game can have lakes and never put anybody in
one, or flood a level whose water is never drawn.

.. code-block:: python

   from OpenGLContext.scenegraph.water import (
       STILL, BREEZE, FLOWING, CHOPPY, LAKE,  # how a body of water moves
       water_surface, water_ribbon, water_glints,   # what it looks like
       wave_height, wave_normal,        # where the surface is, right now
       Volume, Volumes, submerge,       # where the water is, and being in it
   )

How water moves: ``WaterStyle``
-------------------------------

One node covers the range, and five of them are named:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Unit
     - ``STILL``
     - ``BREEZE``
     - ``FLOWING``
     - ``CHOPPY``
     - ``LAKE``
   * - ``amplitude``
     - metres, trough to crest
     - 0.0
     - 0.012
     - 0.09
     - 0.42
     - 0.16
   * - ``wavelength``
     - metres between crests
     - 11.0
     - 1.1
     - 4.5
     - 7.0
     - 9.0
   * - ``speed``
     - metres a second the crests travel
     - 0.0
     - 1.2
     - 1.6
     - 2.4
     - 0.8
   * - ``steepness``
     - radians the ripple tilts the normals, on top of the displacement
     - 0.045
     - 0.081
     - 0.063
     - 0.099
     - 0.059
   * - ``ripple``
     - metres the ripple's longest train repeats over
     - 11.0
     - 0.32
     - 11.0
     - 11.0
     - 11.0
   * - ``flow``
     - metres a second the surface drifts, ``(x, z)``
     - (0, 0)
     - (0, 0)
     - (1, 0)
     - (0, 0)
     - (0, 0)

``STILL`` is a pond: nothing moves, and the ripple is in the light on it.
``BREEZE`` is a pond or a small lake seen from its bank, ruffled by wind:
waves a metre apart and about a centimetre high, and a ripple a hand's breadth
across. ``FLOWING`` is a river, with small crests travelling downstream
and the surface drifting with them. ``CHOPPY`` is weather, with enough height
in it that a shoreline moves. ``LAKE`` is open water seen from a distance: a
long, low swell, sized for a sheet hundreds of metres across. A caller who
wants another writes one — water is a continuum, and the five names are
settings rather than an enumeration.

A style is a scenegraph node, held in the mesh's ``waveStyle`` field. The five
named ones are shared, as a VRML97 ``USE`` shares a node: every sheet built
with ``LAKE`` moves by that one node, so setting ``LAKE.amplitude`` changes
all of them. For a style of one's own, build a ``WaterStyle`` or start from a
named one with ``varied``, which answers a copy and leaves the original alone:

.. code-block:: python

   from OpenGLContext.scenegraph.water import CHOPPY, WaterStyle

   storm = CHOPPY.varied(name='storm', amplitude=1.2)
   millpond = WaterStyle(name='millpond', steepness=0.02, ripple=0.2)

``ripple`` sets the scale the water reads at, and the swell's ``wavelength``
should agree with it. A 20 m pond drawn with ``LAKE`` shows two or three long
rollers and glitter in bands metres wide, which reads as nothing at all; the
same pond with ``BREEZE`` reads as water.

Where ``flow`` is not zero it is also the direction the crests travel.
``style.moving()`` answers whether anything about it changes with time, which
is what a caller advancing the clock only for water that needs it asks.

The field
~~~~~~~~~

The surface is the sum of **three crossing sine trains**, evaluated from
*world* position and time rather than from a mesh's own coordinates. Two
consequences follow, and they are the reason it is built this way:

- **Sheets that meet agree.** A river running into a lake is at the same height
  as the lake along the join, because both asked the same function about the
  same place.

- **A height can be asked for.** ``wave_height(style, x, z, when)`` and
  ``wave_normal(style, x, z, when)`` take scalars or numpy arrays and answer
  what the surface is doing there — which is what buoyancy, a boat's waterline
  or a splash reads.

.. code-block:: python

   from OpenGLContext.scenegraph.water import CHOPPY, wave_height

   lift = wave_height(CHOPPY, boat[0], boat[2], when=context.time)

.. _surfaces:

Drawing it
----------

A lake: ``water_surface``
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   mesh = water_surface(x0, x1, z0, z1, level=12.0,
                        resolution=33, style=CHOPPY, on_gpu=True)

A sheet over a footprint at ``level``. ``resolution`` is how many vertices
across it is meshed at: for still water that carries the ripple in the
normals, and for choppy water it is also how much of the wave the surface can
hold — a sheet meshed coarsely against its own wavelength is a flat sheet with
a strange normal, so keep at least a few vertices per ``wavelength``.

A river: ``water_ribbon``
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   mesh = water_ribbon(course, width=8.0, style=FLOWING, lift=0.15)

``course`` is ``(N,3)`` world points — where the water runs and how high it is
there — and ``width`` is metres across, either one number or one per point so
a river carrying more is wider further down. A lake is one flat plane and a
river is not, which is why this exists: a sheet at a level cannot follow a
course downhill. The surface lies *across the flow* at every point, so a bend
is a bend in plan. ``lift`` raises it above the course, for a caller whose
course is the bed rather than the surface.

.. _glints:

A river seen from far off: ``water_glints``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   mesh = water_glints(course, width=8.0, spacing=60.0, style=FLOWING)

A river a kilometre away is two pixels wide and mostly hidden by whatever
stands over it; what the eye gets is the surface flashing between the trees.
``water_glints`` spends a handful of quads on that instead of a tile's whole
budget on a line nobody can resolve — **this is what a river's level of detail
is**.

``spacing`` is how far apart the glints are, in metres, and it is the LOD
dial: wider with distance. Because a coarser tile is also a bigger tile, a
spacing that grows with the tile's geometric error keeps the number of glints
in a tile roughly constant, which makes it a budget rather than a fade.
``size`` is how much of the river's width each one covers. Where they fall is
a function of position along the course rather than a random draw, so a world
baked twice glints in the same places.

.. _on_gpu:

Moving it: ``on_gpu``
~~~~~~~~~~~~~~~~~~~~~

Every one of the three takes ``on_gpu``. Left out, the wave is built into the
vertices at time ``when`` — right for a still sheet, or for a caller who wants
the mesh to *be* the surface. Set, the mesh is built **flat** and the style is
handed to the card:

.. code-block:: python

   mesh = water_surface(0, 200, 0, 200, level=0.0, style=CHOPPY, on_gpu=True)
   ...
   mesh.wave_time = context.time      # once a frame; nothing is re-uploaded

The vertex shader displaces it, so the mesh is uploaded once and a frame costs
a handful of uniforms. This is the same arrangement skinning uses for a pose,
and the wave is applied in the shadow depth program too, so moving water casts
the shadow of the shape it is in.

Build the wave into the vertices *or* hand it to the card — not both, or the
wave is applied twice. ``Shape`` answers the wave uniforms for every shape it
draws, so the hillside beside a lake does not ripple.

.. _water-reflection:

What it reflects
~~~~~~~~~~~~~~~~

Water reflects the scene standing around it: the far bank, a jetty, a fire on
the shore. Each view with water in it is drawn once more through the camera
mirrored in the water's plane, and the water reads that picture at its own
screen position, pushed by how far its ripple and swell tilt the surface from
flat. Where nothing was mirrored — the sky — it reflects the environment probe
as before. Water's Fresnel weights both, so the reflection is faint looking
straight down and strong across the surface at a glance.

Nothing has to be asked for: any geometry with a ``waveStyle`` is water,
whether ``water_surface`` built it or an ``OGLC_hook`` tag in a glTF did. The
mirrored draw is of the opaque scene, at half the view's width and height, in
a frame with water in view; ``ContextDefinition.waterReflection`` (env
``OPENGLCONTEXT_WATER_REFLECTION``) turns it off, and the water then reflects
the sky alone. It needs a fragment stage with more than 32 texture units, and a
driver with fewer compiles it out.

Its limits:

- One plane a view. Where sheets stand at different levels, the one nearest
  the camera is mirrored and the others reflect the scene as seen in it.
- Transparent things — particles, glass — are not in the reflection.
- A camera under the surface gets none: it is looking up through the water.
- With several views drawing one scene, an opaque water surface drawn once for
  all of them reflects the sky alone.

.. _media:

Being in it: media and volumes
------------------------------

A ``Medium`` is one substance described from the inside. Three are in the
table, and the numbers are the games' own — nothing in any specification says
how far you can see through slime:

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
     - 12 health a second
   * - ``lava``
     - 2 m
     - 0.90
     - 32 health a second

``visibility`` is how many metres it takes the view to close to the medium's
``color``, and both are **linear**: the fog blends in linear HDR before tone
mapping, so the colours in the table are much darker than water looks from
above. Water *absorbs* — it takes the light out of what you are looking at —
where a pale, long-range fog would read as air with something in it.
``muffle`` is how much of the mix's high end goes, and is never 1: total
silence reads as the sound having broken. A name the table has never heard of
is treated as water rather than as dry air, because whatever it is, the body is
inside something.

A ``Medium`` is a scenegraph node, with ``name``, ``color``, ``visibility``,
``muffle`` and ``harm`` as its fields, and ``MEDIA`` holds the three above by
name. A volume names its substance, and every volume naming ``'lava'`` is
inside the one ``MEDIA['lava']``, so tuning that node's fields tunes lava
everywhere. A game adds a substance by putting a node of its own in the table:

.. code-block:: python

   from OpenGLContext.scenegraph.water import MEDIA, Medium

   MEDIA['acid'] = Medium(name='acid', color=(0.02, 0.05, 0.0),
                          visibility=3.0, muffle=0.8, harm=20.0)

Where the water is
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from OpenGLContext.scenegraph.water import Volume, Volumes

   volumes = Volumes([
       Volume.below(minimum=(-40, -40), maximum=(40, 40), level=2.0, depth=30.0),
       Volume(minimum=(10, -8, 10), maximum=(14, -4, 14), medium='lava'),
   ])
   volumes.medium_at(point)               # 'water', 'lava' or '' for dry air

Boxes in world metres, with the boundary counted as inside so a body exactly
at the waterline is in the water. A ``Volume`` is a node whose ``minimum``,
``maximum`` and ``medium`` fields are the box and what fills it; its corners
are world coordinates wherever the node is held. Where boxes overlap, ``rule`` picks the
answer: ``'worst'`` (the default) gives the one that will hurt most, for a
body half in a pool and half in the lava under it; ``'smallest'`` gives the
most specific, which is what a world whose boxes are some partition's own
bounds — a BSP leaf, a tile — wants.

Putting a context under
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from OpenGLContext.scenegraph.water import medium_fog, submerge

   self.fog = medium_fog()                       # once, bound into the scene
   ...
   name = submerge(self, volumes, self.platform.position)   # once a frame

``submerge`` sets the context's fog to what the medium looks like from inside
and the audio engine's whole-mix low-pass to its muffle, then answers the
substance it found so a caller can report it or charge ``harm`` for it. Being
under water is not a coloured pane over the screen: it is a medium with depth
in it, so what is in your hands stays clear while the far wall does not.

Every part is optional. ``volumes`` may be ``None`` for a world with no water;
a context with no ``fog`` is left alone; and a machine with no sound is never
opened just to muffle a silence. ``volumes`` is anything answering
``medium_at(point)``, so a game whose water comes out of a BSP's contents
flags passes its own object rather than converting.

.. _water-demo:

Seeing it work
--------------

.. figure:: images/demos/water_demo.jpg
   :alt: Three rectangular pools cut in sand, each carrying a grid of orange floats: the left grid flat, the middle gently uneven, the right thrown about by large waves, with a river running across behind them

   ``python tests/water_demo.py`` — the three named styles side by side over one
   bed, with a ``water_ribbon`` running across behind them along a course that
   loses height from end to end. Each pool carries a grid of floats put on the
   surface by ``wave_height`` once a frame, which gives the wave field a scale
   the eye can measure: over one pool’s footprint ``STILL`` on the left is flat
   to the millimetre, ``FLOWING`` in the middle spans 0.34 m trough to crest, and
   ``CHOPPY`` on the right spans 1.58 m. Every sheet is built with
   ``on_gpu=True``, so a frame costs four ``wave_time`` writes and nothing is
   re-uploaded. Press ``v`` to put the camera under the middle pool and ``h`` to
   print what the surface is doing. Behind the river is a ``LAKE``: 180 m of open
   water, meshed by ``mesh_across`` from its own wavelength.

How finely a sheet is meshed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A sheet is meshed once across its whole footprint, so a fixed vertex count
cannot be right for both a pond and a lake: the lake samples its own ripple
every few tens of metres, the wave aliases away, and what is left is a flat
plate with a strange normal on it. ``mesh_across(side, style)`` takes the
density from the *wavelength* instead, capped at ``MESH_LIMIT`` because a
sheet is one draw and that is what it costs — in the file of a baked world as
much as in the frame.

Press ``d`` in the demo to mesh its lake the way a sheet used to be and watch
the swell go out of it. Both are measured against the wave field itself, not
asserted:

.. code-block:: python

   lake 180 m across, meshed from its wavelength: 33 vertices, 1.6 samples per wave, keeps 98% of its swell
   lake 180 m across, meshed the old way:          9 vertices, 0.4 samples per wave, keeps 47% of its swell

Nine vertices across 180 m is a vertex every 22 m against a 9 m wave — under
one sample per wave, and so under the Nyquist limit: the wave flattens, and
returns as a longer one that was never in the water.

``MESH_PER_WAVE`` is four. Two is the Nyquist limit itself: enough to
represent a sine in principle, and in practice whether the vertices land on
the crests or on the zero crossings is down to where the sheet happens to
start. Measured over a 12 m sheet, two samples per wave keep 73% of the wave
and four keep 89%; over 40 m, 84% against 96%. On the sheets where it matters
most the two agree, because both are already held at ``MESH_LIMIT``.
``MESH_FLOOR`` is the other end of it: a sheet carrying any swell is never
meshed coarser than the fixed count this rule replaced, which was wrong on a
lake and right on a pond.

The fine ripple does not live in the mesh at all. It is ``waveRipple`` in the
fragment shader, composed as a tilt of whatever normal the surface already
has, so the glitter costs the same at any density and the mesh only has to
carry the swell. It is six trains of lengths between 0.41 and 1.83 times the
style's ``ripple``, at headings spread round the compass, so no two repeat
together and the surface does not tile. On water that moves, each train
travels at the speed water's own waves of its length do, √(g/k), so the long
ones outrun the short and the glitter changes as it goes rather than sliding
as one sheet; still water's ripple holds still.

Its strength varies across the surface in gusts: two long, slow trains, 23 and
37 times the ``ripple`` length, take it from a tenth of ``steepness`` in the
calmest patch to 1.6 times it in the gustiest, and drift at 0.6 of the style's
``speed``. Wind comes over water that way, and a ripple of one strength
everywhere reads as a texture laid over the surface.

Each train is also filtered by the pixel it lands in: it fades out as its
wavelength falls from four pixels across to two, measured per fragment from
the derivative of the surface position. Far water is a smooth mirror because
its ripple is too fine to see, and drawing that ripple anyway draws a grid.
``wave_normal`` is the unfiltered field.

.. rst-class:: technical

The demo runs with ``OPENGLCONTEXT_SHADOWS=0``: a GPU-displaced sheet casts
its shadow map from the flat mesh the CPU still holds, so a moved surface
shadows itself in bands.

What an application writes to get a body of water, and to know when something
is inside it:

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

The demo’s ``h`` key answers the same ``wave_height`` call the floats ride on,
at each pool’s centre:

.. code-block:: python

   STILL    surface at +0.000 m (t=0.05s)
   FLOWING  surface at -0.020 m (t=0.05s)
   CHOPPY   surface at -0.283 m (t=0.05s)

and ``v`` reports what ``submerge`` found as the camera crosses the surface:

.. code-block:: python

   medium under the camera: water
   medium under the camera: air

.. _authoring:

Authoring water in a model
--------------------------

Everything above builds water in Python. An artist can also mark it in the
model: give the lake's material a custom property called ``OGLC_hook``, export,
and the surface loads moving. Nothing registers anything — the ``water`` kind
ships bound — so a tagged file opens in ``oglc-view`` as water.

.. code-block:: javascript

   OGLC_hook = {"kind": "water", "style": "choppy", "depth": 6.0}

In Blender that is a custom property on the material datablock, exported with
**Include ‣ Custom Properties** ticked; no add-on, and Blender 4.x is enough.
The add-on in ``tools/blender/oglc_hook`` is the other way to author it: an
**Engine Hook** panel with a field per parameter below, writing the extension
spelling on export. The shorthand is the kind on its own, ``OGLC_hook =
"water"``, which is a pond. :ref:`Engine hooks <hooks>` is the mechanism
underneath, including how to tag a node rather than a material and how to
register a kind of your own.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Parameter
     - Default
     - What it says
   * - ``style``
     - ``still``
     - ``still``, ``breeze``, ``flowing``, ``choppy`` or ``lake`` — or an
       object naming one as its ``style`` and overriding any ``WaterStyle``
       field (``amplitude``, ``wavelength``, ``speed``, ``steepness``,
       ``ripple``, ``flow``): ``{"style": "breeze", "ripple": 0.3}`` is a finer
       ruffle. A name nothing answers to draws a pond and says so in the log.
   * - ``material``
     - ``keep``
     - ``keep`` shades the surface with the material the file carries, so what
       the artist authored is what is drawn. ``engine`` takes
       ``water_material()`` instead.
   * - ``medium``
     - ``water``
     - ``water``, ``slime`` or ``lava``: what being inside it is like. Lava is
       this kind with another medium and another material, which is why there
       is no second one.
   * - ``depth``
     - ``0.0``
     - How far below the surface the body reaches, in metres. A surface has no
       thickness, so a sheet with no ``depth`` bounds a box nothing is inside of
       except exactly at the waterline.

Each tagged primitive arrives as one ``WaterBody`` in ``scene.hook_data[
'water' ]`` — the mesh whose wave a frame advances, the style it moves with, and
the ``Volume`` saying where it is, in world metres and round *this* copy of the
surface. Two nodes sharing one tagged mesh are two bodies of water, with a box
each.

.. code-block:: python

   scene = gltf.load_gltf( "valley.glb" )
   volumes = Volumes([ body.volume for body in scene.hook_data.get( 'water', () ) ])
   ...
   submerge( self, volumes, self.platform.position )   # once a frame

A wave costs nothing per frame because the card holds the field, but something
has to say what time it is. ``scene.advance( seconds )`` moves every body's
surface and answers whether anything changed; the viewer calls it from its idle,
and a game driving its own loop calls it itself. A scene of ponds answers
``False`` — still water carries its ripple in the normals, and there is nothing
to redraw for. ``oglc-view --anim-time SECONDS`` holds the water at that time as
it holds the animation, so a capture of a tagged lake is the same frame on every
run.

The wave moves the sheet's vertices, so model the surface as a grid rather than
a single quad: a grid add-mesh with a vertex every 30–50 cm moves as water, and
a four-cornered plane only tilts at its corners. Give the shore a bank steeper
than the swell is high, or the troughs uncover it and the crests flood it.

``tools/blender/demos/lakeside.glb`` is a world authored this way, built by
``tools/blender/demos/lakeside.py`` with the add-on's panel: a lake whose
material is tagged ``{"kind": "water", "style": "breeze", "depth": 2.0}`` in a
grass basin, with a jetty, a brazier and a campfire tagged as
:ref:`particle effects <authored-particles>`. ``oglc-view
tools/blender/demos/lakeside.glb`` opens it through its own camera, moving.

Limits
------

- **Not a simulation.** The wave field is analytic — three sine trains — which
  is what makes it cheap, seamless and reproducible. There is no fluid solver,
  and water does not find its own level or pour.

- **Not a physics body.** Buoyancy and drag read ``wave_height``; what a body
  does with that belongs to whatever moves it.

- **Reflection and refraction are the material's.** Water is a PBR material with
  transmission and an index of refraction of 1.33; there is no planar reflection
  pass and no screen-space refraction.

- **A volume is a box.** A sloping river's medium is the boxes a caller cuts it
  into.

- **Shoreline is the mesh's.** Nothing feathers the edge where water meets
  ground, and a sheet that ends inside a hill ends visibly.
