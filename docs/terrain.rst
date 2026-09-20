Terrain & Landscapes
====================

.. rst-class:: introduction

A landscape reaches the screen one of two ways here, and which one it wants
depends on whether it fits in memory.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Path
     - What it is
     - Running on it
   * - **:ref:`Height field <terrain-heightfield>`** (this page)
     - An elevation grid over a centred world square, drawn as one splat-textured
       mesh. A 4 km square at 513² samples is one draw, and the height under any
       point is arithmetic rather than a ray cast. No tiles, no baking, no streaming.
     - The `forest demo <https://pypi.org/project/openglcontext-forest-demo/>`__ —
       real Great Smoky Mountains elevation, walked at eye height.
   * - **:doc:`Streamed 3D Tiles <tiles3d>`**
     - An octree of glTF tiles paged in and out around the camera by screen-space
       error, under a memory budget, each tile carrying its own collision mesh. What
       a world too big to load needs.
     - :doc:`GLinting Steel <glisteel>` — a circuit :doc:`baked <baking>` into a
       world and streamed in around the car.

The two share what stands on the ground: the same :doc:`vegetation
<vegetation>` nodes, the same :doc:`roads <roads>`, the same :doc:`water
<water>`, and the same :doc:`movement modes <navigation>`.

.. figure:: images/gallery/showcase/forest-walk.jpg
   :alt: A hillside of firs over undergrowth, seen from standing height
   :class: shot

   A height field at full size: one splat-textured mesh under half a million
   instanced trees and grass clumps, on a real digital elevation model.

.. _terrain-heightfield:

Height-field terrain, walked
----------------------------

A landscape that fits in memory whole needs none of the streaming above.
``OpenGLContext.scenegraph.terrain`` holds it as a ``HeightField`` — an
elevation grid over a centred world square — drawn by ``SplatTerrain``, which
blends several ground materials per fragment from a control image. A 4 km
square at 513² samples is one mesh and one draw, and the height under any
point is arithmetic rather than a ray cast.

.. _onesurface:

One surface, three readers
~~~~~~~~~~~~~~~~~~~~~~~~~~

A height field answers about the same ground three ways, and every one of them
gives the same answer:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Reader
     - What asks it
   * - ``field.mesh()``
     - what ``SplatTerrain`` draws — the ground a player sees
   * - ``HeightFieldColliders``
     - the trimesh chunks a car drives on, cut from that same grid
   * - ``field.sample(x, z)``
     - everything analytic: the walker's floor, the seat of every scattered plant,
       the slope a grass mask thins by

Four corner samples do not lie in a plane, so each cell of the grid is drawn
as *two triangles*, and the height inside a cell depends on which of the two a
point falls in. ``sample`` reads that same triangulated surface, so a camera
clamped with it stands on the ground that is drawn, and a plant seated on it
meets that ground.

.. rst-class:: technical

Interpolating the four corners of a cell instead — a bilinear patch — names a
height on a surface nothing draws: it rides a quarter of the cell's twist
above the drawn ground on one diagonal and the same below it on the other.
Over the eight-metre cells of a 4 km square at 513², that is metres — a camera
under the hill looking out through it, and vegetation buried to the tips.
``tests/unit/test_heightfield_is_the_drawn_surface.py`` holds the three
readers to each other.

**A height function is not the ground; the mesh built from it is.** The same
rule applies wherever a surface is meshed by sampling a function at vertices —
the :doc:`streamed tiles <tiles3d>`, ``terrain_patch``. What is drawn there is
the triangles between those samples, so anything placed on that ground has to
be placed against them: scatter over the tile mesh (``scatter_on_mesh``), or
against a sampler that reads it. Feeding the original function to
``scatter_disc`` seats plants on a surface that was never drawn.

.. _fromfunction:

Where a height field comes from
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A landscape is *authored* as a function of ``(x, z)`` — procedural noise, a
DEM reader, terrain with a road's earthworks cut into it — and rendered and
collided against as a grid. ``HeightField.from_function(fn, res, extent)`` is
the step between: it samples the function over the square and takes the datum
and the relief from what the function actually does there, so the grid's whole
0–1 range is spent on the ground that is present.

.. code-block:: python

   from OpenGLContext.scenegraph.terrain import HeightField, LayerRule, control_map
   field = HeightField.from_function(my_ground, res=1025, extent=4096.0)
   field.save_image('terrain-height.png')            # 16-bit, no datum in it
   HeightField.from_image('terrain-height.png', 1025, 4096.0,
                          field.relief, base=field.base)

``base`` is the world height the grid's zero stands at. A landscape's lowest
point is rarely sea level, and the grid says only how far the ground rises,
not where it sits; the two numbers travel with the image. Give ``base`` and
``relief`` explicitly when two fields of one landscape have to agree, or they
meet in a step.

.. _terrainprofile:

Landscapes of your own
~~~~~~~~~~~~~~~~~~~~~~

The shipped field is four things added together, and a ``TerrainProfile`` is
how much of each there is: broad rolling **hills**; ridged **mountains** under
a mask, so they stand in ranges rather than everywhere; a meandering
**canyon** cut into whatever is above it; and a broad **basin** dished out of
one region, whose floor is where a lake sits.

.. code-block:: python

   from OpenGLContext.loaders.tiles3d.procedural import TerrainProfile, terrain_height_for

   alps = TerrainProfile(hills=70.0, mountains=900.0, mountain_scale=1400.0,
                         mountain_cover=0.82, canyon=0.0, basin=0.0, datum=60.0)
   height_fn = terrain_height_for(alps)          # an ordinary height function

Every amount is metres of relief and every scale is metres on the ground, so
what a landscape is can be read off its profile. ``seed`` gives another
landscape of the same description — another set of ranges, another course for
the river — rather than another kind of landscape. ``SHIPPED_TERRAIN`` is the
profile ``terrain_height`` is, and it does not move: worlds already baked came
from those numbers.

``fbm`` and ``ridged`` are the noise the landscape is made of, exposed so that
anything adding to it — a sculpted hill, a scatter mask, a splat weight — can
be made of the same grain rather than of a second kind of noise that does not
match.

The result is an ordinary height function, so it feeds
``HeightField.from_function`` above or :ref:`a baked tileset <making>`
equally.

.. _controlmap:

Which ground material shows where
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The splat's control map is an RGBA image: red is how much of the first
material shows at that spot, green the second, and so on. Painting one is how
a landscape artist works; deriving one from the land is how a generated world
gets its ground. A ``LayerRule`` is an elevation band, a slope band and a
weight, and ``control_map`` turns a height field and a list of them into the
image:

.. code-block:: python

   control_map(field, [
       LayerRule(),                                   # grass: the fallback
       LayerRule(slope=(0.16, 0.55), weight=1.5),     # needle litter on the slopes
       LayerRule(slope=(0.5, 1e9), weight=3.0),       # rock where soil will not stay
       LayerRule(weight=0.0),                         # dirt: painted, not derived
   ], size=512, painted=[(3, road_corridor)])

The first layer is the fallback: ground no rule wants is made of it. Bands
feather at their edges, because a hard edge between two ground materials reads
as a painted line. ``painted`` forces a layer where the rules cannot know to —
a road's corridor, a lake bed, a clearing — taking that fraction of the pixel
away from everything else, so the weights still add to one.

**Size the map to the smallest thing it has to say.** The control map is also
what decides where :ref:`ground cover <groundcover>` grows, so a corridor
thinner than one of its pixels is a corridor the grass grows straight over.
Over four kilometres, 512 pixels is eight metres each and 2048 is two.

.. _fieldphysics:

Standing on one
~~~~~~~~~~~~~~~

A field is a surface, so a vehicle needs triangles.
``OpenGLContext.physics.heightfield.HeightFieldColliders`` cuts it into square
chunks and keeps the ones near whatever is moving in the physics world:

.. code-block:: python

   from OpenGLContext.physics.heightfield import HeightFieldColliders
   ground = HeightFieldColliders(physics_world, field, reach=320.0)
   ground.update(car_position)                        # once a frame

A four-kilometre field at four-metre spacing is two million triangles and a
car touches four of them at a time, so what is out of reach is removed again:
an hour of driving costs what one view of the world costs. Chunks are cut on
the field's own grid lines and share their edge rows, so two neighbours agree
exactly where they meet.

``holes`` is how something that passes *through* the ground says so. A
tunnel's bore runs inside the hill and the hill's surface is still drawn over
it; left in the physics world that surface is a wall across the road.
``holes(x, z) -> mask`` is true where the ground is not there, and the bore's
own lining is what the vehicle then drives through.

The same callable goes to ``HeightField.mesh()`` and to the colliders, so the
surface a player sees and the surface a car meets are one surface:

.. code-block:: python

   from OpenGLContext.scenegraph.roadworks import bore_opening

   mouth = bore_opening(bore_centreline, field.sample, profile=road_profile)
   terrain.holes = mouth                              # what is drawn
   ground = HeightFieldColliders(physics_world, field, holes=mouth)

``OpenGLContext.scenegraph.terrain.holes.cut`` is what both use to apply it.
The triangles the opening's edge crosses are *cut on that edge* — the crossing
is found by halving, to under a millimetre on a cell metres wide — so the
ground stops where the opening starts rather than a cell either side of it,
and a new corner carries the normal the surface already had there. A crossing
belongs to the grid edge rather than to the triangle that asked for it, so the
two triangles sharing an edge are handed the same corner and the cut leaves no
crack. Detail finer than a cell — an opening smaller than one, or a corner
where the edge turns inside one — is resolved to the triangle it falls in,
which goes if its centre is in the opening.

:ref:`Roads <bores>` has what a bore's opening is, and why it is the mouth
rather than the length of the tunnel.

.. _tiledground:

Ground that arrives in the tiles
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A world can carry its ground in its *tiles* instead: meshed when the world was
baked, refined by the streamer as the camera comes in, and drawn as it
arrived. What makes it ground is the same shading — the same detail materials,
the same control map, the same baked light — held apart from the mesh it is
drawn on:

.. code-block:: python

   from OpenGLContext.scenegraph.terrain.ground import GroundShading, GroundPatch

   ground = GroundShading(extent=2048.0, layers=layers, control='control.png',
                          shading=field.sun_shadow(sun))
   patch = GroundPatch(ground, vertices, indices, model=tile_transform)

A bake says which primitive is ground by **naming its material** ``ground``,
and the tile loader mounts those as patches of the world's own ground
(``OpenGLContext.scenegraph.terrain.ground.mount_ground``); the material's
vertex colours stay on it, so a viewer that has never heard of the convention
still draws a landscape. ``extras.terrain.drawn`` in the tileset says which
way round a world is: ``field`` for the one mesh above, ``tiles`` for ground
that streams. Either way the height field is written beside the tileset,
because it is what the world is collided against, clamped to and planted on —
the surface that must not change resolution under a wheel as a tile refines.

.. _relief:

The grain in the ground
~~~~~~~~~~~~~~~~~~~~~~~

A height function says where the hills are. What it does not say is what a
hillside is made of — the hummocks, the ruts and the swells a metre or two
across that someone standing on it sees. Sampling the function more finely
does not produce them, because they are not in it.
``OpenGLContext.scenegraph.terrain.Relief`` is:

.. code-block:: python

   from OpenGLContext.scenegraph.terrain import Relief, GROUND_RELIEF

   grain = Relief(coarsest=24.0, finest=0.75, roughness=0.09)
   ground = grain.over(height_fn, spacing=tile_spacing, error=tile_error)

Relief is a band of noise per feature size, and a surface carries the bands it
is sampled finely enough to show: a band is drawn only where a feature spans
``samples_per_feature`` vertices or more, so a tile meshed every sixty metres
carries none of them and one meshed every half metre carries them all. The
grain therefore *arrives* as a 3D Tiles tree refines rather than aliasing into
a coarse tile as speckle.

**Keep the features small.** A band is as tall as ``roughness`` times its own
width, so a coarse band is not grain but a dune: at 24 m and a roughness of a
tenth it is two and a half metres of swell, which on a landscape a car drives
over is terrain rather than texture. What a landscape is *shaped* like is the
height function's job; this is what a hillside is made of.

The whole displacement is scaled to fit inside the tile's own geometric error
— the distance the streamer is already willing for the drawn surface to stand
from the real one. ``roughness`` is metres of rise per metre of feature;
``seed`` chooses which grain. ``GROUND_RELIEF`` is the one a baked landscape
carries by default.

**What is drawn is what is collided against.** The height field is still the
one surface every reader agrees about — the car, the camera, the seat of a
scattered plant — so the grain goes into *it*, and the tiles are meshed from
the same function. A band the field cannot hold would be relief a player sees
and walks straight through, so ``no_finer_than(spacing)`` cuts those before
anything draws them:

.. code-block:: python

   grain = GROUND_RELIEF.no_finer_than(field_spacing)   # what a grid that size can carry
   ground = grain.over(height_fn, spacing=finest_tile_spacing, error=finest_tile_error)

The field is sampled from ``ground`` and so is the finest tile, so the two are
one surface; the coarser tiles are that surface with its finer bands left off,
which is ordinary level of detail.

**How much can be felt is set by the field's own grid.** The grain goes into
the landscape and the landscape is a grid, so ``no_finer_than`` cuts what it
cannot hold: at a sample every two metres that leaves one swell of about half
a metre across sixteen, which reads as modulation across a hillside. Ruts are
a metre across, and feeling one wants a surface sampled a few tens of
centimetres apart near the camera rather than a finer grid over the whole
world.

The other half of agreeing is ``where``: ground that was *worked* has no grain
left in it. A road is a strip that was cleared and levelled to build it, and a
hummock in the carriageway is one a grader took out — so a caller hands the
relief a weight from 0 on the made ground to 1 clear of it, and the same
weight reaches the tiles and the field alike.

Baking it into a world is `openglcontext-editor
<https://github.com/mcfletch/openglcontext-editor>`__'s
``HeightfieldLayer(relief=...)``, which meshes each tile from the height
function with the tile's own bands already in it, and
``ProceduralWorld.grain``, which puts the same grain in the landscape beside
the tileset.

Walking it
~~~~~~~~~~

``OpenGLContext.move.terrainwalk.TerrainWalkMixin`` is what walks it. It is
the terrain form of :ref:`PhysicsWalkMixin <physics-heightfield>`: the same
avatar, the same declared :doc:`movement modes <navigation>` and the same keys
as a glTF model or an arena map, with the ground taken from the height field
and the obstacles from a field of cylinders — tree trunks, rocks — resolved
analytically.

.. code-block:: python

   class Forest( OverlayMixin, TerrainWalkMixin, BaseContext ):
       def OnInit( self ):
           self.sg = my_scene                          # with the SplatTerrain in it
           self.eye_height = 1.7                       # metres; sizes the avatar
           self.platform.setPosition( where_to_start )
           self.init_walk( height_field, trunk_positions, trunk_radii )
           self.setupPhysics( enable=True )            # binds 'g', starts walking
           self.add_stream( 10.0, refresh_grass )      # follow the walker

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - What it does
   * - ``init_walk( field, positions, radii )``
     - Bind the ground and the cylinders. The radii have ``player_radius`` added, and
       the cylinders are bucketed into a hash grid, so a collision test looks at a
       handful of neighbours rather than at a whole forest.
   * - ``setupPhysics( enable=True )``
     - Stand the avatar up and give it the camera. From ``PhysicsWalkMixin``,
       unchanged — :kbd:`g` hands the camera back to the free-fly navigator, :kbd:`f`
       flies.
   * - ``add_stream( step, fn, turn=None )``
     - Call ``fn(x, z)`` once the walker has moved ``step`` world units, or turned
       ``turn`` radians. What refreshes the grass and the near-mesh trees that follow
       the camera; use ``turn`` for a field that depends on the *facing*, such as a
       view-cone cull.
   * - ``eye_height``, ``player_radius``
     - The camera height and the body radius the scene was written against. They size
       the avatar, rather than the physics defaults.

The surface is a **floor**, not a rail: the avatar is lifted to it from at or
below and left alone above, so a jump rises, an arrival from the air falls,
and flying over the canopy works. Trunks stop a walker and not a flier.
Without ``setupPhysics`` the mix-in still holds a free-fly camera down on the
terrain, which is what the offscreen capture and benchmark tools use.

Demos & validation
------------------

``oglc-forest`` — the `forest demo
<https://pypi.org/project/openglcontext-forest-demo/>`__, a separate
distribution — is this path at full size: real Great Smoky Mountains
elevation, a four-layer splat ground, 230k GPU-instanced trees with impostor
LOD, two layers of camera-following grass, and the overlay :doc:`settings and
key-binding screens <overlayui>` on the same keys every other program here
uses.

- ``tests/tiles_terrain.py``, ``tests/tiles_vegetation.py`` — minimal
  heightfield / instanced-vegetation demos.

- ``tests/tiles_walk.py`` — first-person walk/fly.

.. rst-class:: technical

``scenegraph/terrain/`` (``heightfield.py``, ``splat.py``, ``control.py``),
``scenegraph/vegetation/`` (instanced clumps, billboards, near meshes and
``field.py``), ``physics/heightfield.py`` and ``move/terrainwalk.py``. The
behaviour is pinned by ``tests/unit/test_terrainwalk_avatar.py`` (where the
walker ends up, on a slope, against a trunk, mid-jump and in the air),
``test_terrainwalk_broadphase.py``, ``test_terrain_vegetation.py``,
``test_heightfield_datum.py``, ``test_terrain_control.py``,
``test_heightfield_colliders.py`` and ``test_vegetation_field.py``.
