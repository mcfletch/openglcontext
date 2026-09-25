Terrain & Landscapes
====================

.. rst-class:: introduction

OpenGLContext draws a landscape in one of two ways. A landscape that fits in
memory is a **height field**: one elevation grid, drawn as one mesh. A
landscape too big for that is a **streamed 3D Tiles** world, paged in and out
around the camera. This page covers the height field.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - What it is
     - Example
   * - :ref:`Height field <terrain-heightfield>` (this page)
     - An elevation grid over a square centred on the origin, drawn as one
       splat-textured mesh. A 4 km square at 513² samples is one draw. The height
       under any point is computed from the grid, with no ray cast. There are no
       tiles, no baking and no streaming.
     - The `forest demo <https://pypi.org/project/openglcontext-forest-demo/>`__:
       Great Smoky Mountains elevation data, walked at eye height.
   * - :doc:`Streamed 3D Tiles <tiles3d>`
     - An octree of glTF tiles, loaded and unloaded around the camera by
       screen-space error within a memory budget. Each tile carries its own
       collision mesh. Use it for a world too big to load at once.
     - :doc:`GLinting Steel <glisteel>`: a circuit :doc:`baked <baking>` into a
       world and streamed around the car.

Both use the same :doc:`vegetation <vegetation>` nodes, the same :doc:`roads
<roads>`, the same :doc:`water <water>` and the same :doc:`movement modes
<navigation>`.

.. figure:: images/gallery/showcase/forest-walk.jpg
   :alt: A hillside of firs over undergrowth, seen from standing height
   :class: shot

   A height field at full size: one splat-textured mesh under half a million
   instanced trees and grass clumps, on a real digital elevation model.

.. _terrain-heightfield:

Height-field terrain
--------------------

``OpenGLContext.scenegraph.terrain`` holds the landscape as a ``HeightField``:
a square elevation grid over a square of the world centred on the origin.
``SplatTerrain`` draws it, blending several ground materials per fragment
according to a control image. A 4 km square at 513² samples is one mesh and
one draw.

A ``HeightField`` has four numbers besides its grid:

- ``extent`` - the side of the square, in world units. The grid spans
  ``-extent/2`` to ``extent/2`` in x and z.
- ``relief`` - the world height of a change from 0 to 1 in the grid.
- ``base`` - the world height of the grid's zero (default 0).
- ``res`` - the number of samples along each side, taken from the grid.

.. _fromfunction:

Building a height field from a function
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A landscape is usually written as a function of ``(x, z)``: procedural noise, a
DEM reader, or terrain with a road's earthworks cut into it. The renderer and
the physics use a grid. ``HeightField.from_function(fn, res, extent)`` samples
the function over the square to make that grid. By default it sets ``base``
and ``relief`` from the lowest and highest heights the function produces, so
the whole 0–1 range of the grid covers the ground that is there.

.. code-block:: python

   from OpenGLContext.scenegraph.terrain import HeightField, LayerRule, control_map
   field = HeightField.from_function(my_ground, res=1025, extent=4096.0)
   field.save_image('terrain-height.png')            # 16-bit, no datum in it
   HeightField.from_image('terrain-height.png', 1025, 4096.0,
                          field.relief, base=field.base)

``save_image`` writes a 16-bit greyscale PNG. The image holds only how far the
ground rises, not where it sits, so store ``base`` and ``relief`` with it and
pass them back to ``from_image``. When two fields describe one landscape, give
both the same ``base`` and ``relief`` explicitly. Otherwise they meet in a
step.

.. _terrainprofile:

Procedural landscapes
~~~~~~~~~~~~~~~~~~~~~

The procedural landscape is the sum of four shapes, and a ``TerrainProfile``
sets how much of each there is:

- ``hills`` - broad rolling hills;
- ``mountains`` - ridged mountains under a mask, so they form ranges rather
  than covering the map;
- ``canyon`` - a meandering canyon cut into whatever is above it;
- ``basin`` - a broad dish in one region, whose floor holds a lake.

.. code-block:: python

   from OpenGLContext.loaders.tiles3d.procedural import TerrainProfile, terrain_height_for

   alps = TerrainProfile(hills=70.0, mountains=900.0, mountain_scale=1400.0,
                         mountain_cover=0.82, canyon=0.0, basin=0.0, datum=60.0)
   height_fn = terrain_height_for(alps)          # an ordinary height function

Every amount is in metres of relief, and every scale is in metres on the
ground. ``seed`` produces a different landscape with the same description:
different ranges, a different course for the river. ``SHIPPED_TERRAIN`` is the
profile behind ``terrain_height``. Its values stay fixed, because baked worlds
were made from them.

``fbm`` and ``ridged``, in ``OpenGLContext.noise``, are the noise functions
the landscape is built from. Use them for anything you add to it, such as a
sculpted hill, a scatter mask or a splat weight, so that the addition has the
same grain.

``terrain_height_for`` returns an ordinary height function. Pass it to
``HeightField.from_function`` above, or use it to build :ref:`a baked tileset
<making>`.

.. _controlmap:

Ground materials: the control map
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The splat's control map is an RGBA image. Red is the weight of the first
material at that spot, green the second, and so on. An artist can paint one,
or ``control_map`` can derive one from the height field. It takes a list of
``LayerRule`` objects, one per layer. Each rule has an elevation band
(``height``, in metres), a slope band (``slope``, as rise over run) and a
``weight``:

.. code-block:: python

   control_map(field, [
       LayerRule(),                                   # grass: the fallback
       LayerRule(slope=(0.16, 0.55), weight=1.5),     # needle litter on the slopes
       LayerRule(slope=(0.5, 1e9), weight=3.0),       # rock where soil will not stay
       LayerRule(weight=0.0),                         # dirt: painted, not derived
   ], size=512, painted=[(3, road_corridor)])

The first layer is the fallback: it covers any ground no other rule claims.
Bands are feathered at their edges, because a hard edge between two ground
materials looks like a painted line. ``painted`` is a list of ``(layer,
mask)`` pairs that force a layer where no rule could place it, such as a
road's corridor, a lake bed or a clearing. Each mask takes its share of the
pixel from the other layers, so the weights still add up to one.

``size`` is the map's resolution in pixels (default 512). Choose it for the
narrowest feature the map must show. The control map also decides where
:ref:`ground cover <groundcover>` grows, and grass grows straight over a
corridor narrower than one pixel. Over four kilometres, 512 pixels are eight
metres each and 2048 pixels are two metres each.

.. _onesurface:

One surface for drawing, collision and placement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Three parts of the engine read a height field, and all three get the same
surface:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Call
     - Used by
   * - ``field.mesh()``
     - ``SplatTerrain``, which draws the ground the player sees
   * - ``HeightFieldColliders``
     - the physics world: trimesh chunks cut from the same grid, for a car to
       drive on
   * - ``field.sample(x, z)``
     - everything computed directly: the walker's floor, the base of every
       scattered plant, the slope that thins a grass mask

The four corners of a grid cell do not lie in a plane, so each cell is drawn
as *two triangles*. The height inside a cell depends on which triangle a point
falls in. ``sample`` reads that same triangulated surface. A camera clamped
with it stands on the drawn ground, and a plant placed with it meets that
ground.

.. rst-class:: technical

Bilinear interpolation of the four corners gives a different surface, one
that nothing draws. It lies above the drawn ground on one diagonal of the cell
and below it on the other, by a quarter of the cell's twist. On a 4 km square
at 513² samples the cells are eight metres wide, and the error reaches metres:
the camera sinks inside a hill, and plants are buried to their tips.
``tests/unit/test_heightfield_is_the_drawn_surface.py`` checks that the three
readers agree.

``sample`` returns a height inside an :ref:`opening <holes>` in the ground as
it does anywhere else, because it reads the grid and the grid has no record of
what was cut from the mesh. Code that places something on the ground must
check ``holes`` as well.

The same rule applies to any surface meshed by sampling a function at its
vertices, such as the :doc:`streamed tiles <tiles3d>` or ``terrain_patch``.
The drawn surface is the triangles between the samples, not the function.
Place objects against those triangles: scatter over the tile mesh with
``scatter_on_mesh``, or use a sampler that reads the mesh. Plants placed by
``scatter_disc`` from the original function sit on a surface that is not
drawn.

.. _fieldphysics:

Colliding with a height field
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A vehicle needs triangles to collide with.
``OpenGLContext.physics.heightfield.HeightFieldColliders`` cuts the field into
square chunks and keeps only the chunks near a given position in the physics
world:

.. code-block:: python

   from OpenGLContext.physics.heightfield import HeightFieldColliders
   ground = HeightFieldColliders(physics_world, field, reach=320.0)
   ground.update(car_position)                        # once a frame

``reach`` is how far from the position ground is kept, in metres (default
320). ``chunk`` is the side of one chunk, in metres (default 128), rounded to
whole grid cells. A four-kilometre field at four-metre spacing is two million
triangles, and a car touches about four of them at a time. Chunks that move
out of reach are removed, so the physics cost stays at what one view of the
world needs, however long the drive. Chunks are cut on the field's own grid
lines and share their edge rows, so neighbouring chunks meet exactly.

.. _holes:

Openings in the ground
~~~~~~~~~~~~~~~~~~~~~~

A height field cannot represent a hole, such as the mouth of a tunnel. The
hill's surface is still drawn over the bore, and in the physics world that
surface is a wall across the road. ``holes`` is a callable,
``holes(x, z) -> mask``, that is true where the ground is absent. Inside the
opening, the vehicle drives on the bore's own lining.

Pass the same callable to ``HeightField.mesh()``, to the colliders and to
anything placed on the ground. The surface the player sees, the surface the
car hits and the surface objects stand on then stay the same:

.. code-block:: python

   from OpenGLContext.scenegraph.roadworks import bore_opening

   mouth = bore_opening(bore_centreline, field.sample, profile=road_profile)
   terrain.holes = mouth                              # what is drawn, and what grows
   ground = HeightFieldColliders(physics_world, field, holes=mouth)

``holes`` may be set at any time; a ``SplatTerrain`` cuts its mesh again at
its next draw. ``oglc-cover`` (:ref:`the ground cover demo <cover-demo>`) cuts
a well into a hillside this way, and its ``o`` key closes and opens it. Setting ``holes`` on a ``TilesTerrain`` also passes it to that
terrain's :ref:`ground cover <wheretheygrow>`. Anything you place yourself using only
``field.sample`` stands in mid-air across the opening, so check ``holes`` for
it too.

``OpenGLContext.scenegraph.terrain.holes.cut`` applies the mask to the mesh
and to the colliders:

- A triangle that the opening's edge crosses is cut along that edge. The
  crossing is found by repeated halving, to under a millimetre on a cell
  metres wide. The ground stops where the opening starts, not a cell to either
  side, and each new corner keeps the surface's normal at that point.
- A crossing belongs to the grid edge, not to the triangle. The two triangles
  that share an edge get the same new corner, so the cut leaves no crack.
- Detail finer than a cell, such as an opening smaller than a cell or a corner
  of the opening inside one, is resolved per triangle: a triangle is removed
  if its centre is inside the opening.

:ref:`Tunnel mouths in the ground <bore-openings>` describes how a road makes
its openings, and why an opening covers only the mouth and not the whole
length of the tunnel.

.. _tiledground:

Ground carried in the tiles
~~~~~~~~~~~~~~~~~~~~~~~~~~~

A world can also carry its ground in its *tiles*. The ground is meshed when
the world is baked, refined by the streamer as the camera approaches, and
drawn as each tile arrives. It is shaded the same way as a height field, with
the same detail materials, control map and baked light. ``GroundShading``
holds that shading apart from the mesh, and ``GroundPatch`` draws one mesh
with it:

.. code-block:: python

   from OpenGLContext.scenegraph.terrain.ground import GroundShading, GroundPatch

   ground = GroundShading(extent=2048.0, layers=layers, control='control.png',
                          shading=field.sun_shadow(sun))
   patch = GroundPatch(ground, vertices, indices, model=tile_transform)

``model`` is in the scenegraph's row-vector form, as ``mode.matrix`` and
``MatrixTransform.localMatrix`` are: a point ``p`` is at ``[*p, 1] @ model``,
with the translation in the last row. A tileset states its transforms the
other way round, so the tile loader passes the transpose of a tile's
transform. ``sun`` is the direction the sunlight travels, pointing down from
the sun, as ``ground.DEFAULT_SUN`` is. The uniforms every patch shares are set
once, when each form of the program is compiled; a patch sends only its
placement and the view.

A bake marks a primitive as ground by **naming its material** ``ground``. The
tile loader mounts those primitives as patches of the world's ground
(``OpenGLContext.scenegraph.terrain.ground.mount_ground``). The material keeps
its vertex colours, so a viewer that does not know this convention still draws
a landscape.

``extras.terrain.drawn`` in the tileset says which form a world uses:
``field`` for one height-field mesh, ``tiles`` for ground that streams. In both
cases the height field is written beside the tileset. The engine collides
against it, clamps the camera to it and places plants on it, because its
resolution does not change under a wheel as tiles refine.

.. _relief:

Small-scale relief
~~~~~~~~~~~~~~~~~~

A height function sets where the hills are. It does not include the hummocks,
ruts and swells a metre or two across that a person standing on a hillside
sees, and sampling the function more finely does not add them.
``OpenGLContext.scenegraph.terrain.Relief`` adds them:

.. code-block:: python

   from OpenGLContext.scenegraph.terrain import Relief, GROUND_RELIEF

   grain = Relief(coarsest=24.0, finest=0.75, roughness=0.09)
   ground = grain.over(height_fn, spacing=tile_spacing, error=tile_error)

``Relief`` is a set of noise bands, one per feature size, from ``coarsest`` to
``finest`` metres (defaults 16 and 0.75). A surface carries only the bands it
is sampled finely enough to show. A band is included only where a feature
spans at least ``samples_per_feature`` vertices (default 8). A tile meshed
every sixty metres carries none of the bands, and one meshed every half metre
carries all of them. The grain therefore appears as a 3D Tiles tree refines,
instead of aliasing into speckle on a coarse tile.

Each band is ``roughness`` times its own width in height. ``roughness`` is in
metres of rise per metre of feature (default 0.03). Keep the coarse bands
small: a 24 m band at a roughness of 0.1 is two and a half metres of swell,
which a car feels as terrain rather than texture. Shape the landscape with the
height function, and use ``Relief`` only for surface texture. ``seed`` selects
a different grain. ``GROUND_RELIEF`` is the default relief for a baked
landscape.

The total displacement is scaled to fit inside the tile's own geometric error,
the distance the streamer already allows between the drawn surface and the
true one.

The height field must carry the same grain, because the car, the camera and
the plants all use it. ``no_finer_than(spacing)`` removes the bands the field's
grid is too coarse to hold, so no band is drawn that a player would walk
through:

.. code-block:: python

   grain = GROUND_RELIEF.no_finer_than(field_spacing)   # what a grid that size can carry
   ground = grain.over(height_fn, spacing=finest_tile_spacing, error=finest_tile_error)

Sample both the field and the finest tiles from ``ground``, so they are the
same surface. Coarser tiles are that surface with its finer bands left off,
which is ordinary level of detail.

The field's grid sets how much grain the physics can feel. At one sample every
two metres, ``no_finer_than`` leaves one band: a swell of about half a metre
across sixteen metres. Ruts are about a metre across. Feeling them needs a
surface sampled a few tens of centimetres apart near the camera, not a finer
grid over the whole world.

``where`` removes the grain from ground that was built on. A road is cleared
and levelled before it is surfaced, so it has no hummocks. Pass ``where`` a
weight that is 0 on the built ground and 1 clear of it. The same weight
applies to both the tiles and the field.

To bake relief into a world, use `openglcontext-editor
<https://github.com/mcfletch/openglcontext-editor>`__:
``HeightfieldLayer(relief=...)`` meshes each tile from the height function
with that tile's bands in it, and ``ProceduralWorld.grain`` puts the same
grain in the height field written beside the tileset.

Walking on a height field
~~~~~~~~~~~~~~~~~~~~~~~~~

``OpenGLContext.move.terrainwalk.TerrainWalkMixin`` lets the player walk on a
height field. It is the terrain form of :ref:`PhysicsWalkMixin
<physics-heightfield>`. It uses the same avatar, the same :doc:`movement
modes <navigation>` and the same keys as walking on a glTF model or an arena
map. The ground comes from the height field. Obstacles such as tree trunks
and rocks are a set of vertical cylinders, resolved analytically.

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

   * - Method or attribute
     - What it does
   * - ``init_walk( field, positions, radii )``
     - Sets the ground and the obstacle cylinders. ``player_radius`` is added to
       each radius. The cylinders are sorted into a hash grid, so a collision test
       checks a few neighbours rather than the whole forest.
   * - ``setupPhysics( enable=True )``
     - Creates the avatar and gives it the camera. Inherited unchanged from
       ``PhysicsWalkMixin``: :kbd:`g` returns the camera to the free-fly
       navigator, and :kbd:`f` flies.
   * - ``add_stream( step, fn, turn=None )``
     - Calls ``fn(x, z)`` each time the walker moves ``step`` world units, or turns
       ``turn`` radians. Use it to refresh the grass and near-mesh trees that
       follow the camera. Give ``turn`` for anything that depends on the facing,
       such as a view-cone cull.
   * - ``eye_height``, ``player_radius``
     - The camera height (default 1.7) and body radius (default 0.25) the scene
       was built for, in world units. They size the avatar in place of the
       physics defaults.

The surface is a **floor**, not a rail. The avatar is lifted onto it from
below and is left alone above it, so a jump rises, a drop from the air falls,
and flight over the canopy works. Trunks stop a walker but not a flier.
Without ``setupPhysics``, the mix-in still holds a free-fly camera above the
terrain. The offscreen capture and benchmark tools use that mode.

Demos and source
----------------

``oglc-forest``, the `forest demo
<https://pypi.org/project/openglcontext-forest-demo/>`__, is a separate
distribution that uses this page's features at full size: Great Smoky
Mountains elevation data, a four-layer splat ground, 230,000 GPU-instanced
trees with impostor LOD, two layers of camera-following grass, and the
overlay :doc:`settings and key-binding screens <overlayui>`, on the same keys
as every other OpenGLContext program. :doc:`Vegetation <vegetation>` describes
the trees and grass.

- ``tests/tiles_terrain.py``, ``tests/tiles_vegetation.py`` - small height-field
  and instanced-vegetation demos.

- ``tests/tiles_walk.py`` - first-person walking and flying.

.. rst-class:: technical

The code is in ``scenegraph/terrain/`` (``heightfield.py``, ``splat.py``,
``control.py``, ``holes.py``, ``ground.py``, ``relief.py``),
``scenegraph/vegetation/`` (instanced clumps, billboards, near meshes and
``field.py``), ``physics/heightfield.py`` and ``move/terrainwalk.py``. The
tests are ``tests/unit/test_terrainwalk_avatar.py`` (where the walker ends
up: on a slope, against a trunk, mid-jump and in the air),
``test_terrainwalk_broadphase.py``, ``test_terrain_vegetation.py``,
``test_heightfield_datum.py``, ``test_terrain_control.py``,
``test_heightfield_colliders.py`` and ``test_vegetation_field.py``.
