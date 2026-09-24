Baking a world
==============

.. rst-class:: introduction

Baking turns a world description into files the engine can stream. A world
too large for memory is split into a tree of tiles. Each tile holds the detail
that suits the distance it is seen from, and tiles load as the camera comes
near. :doc:`Streamed 3D Tiles <tiles3d>` describes how OpenGLContext streams
such a world. This page describes how to make one.

The work is split across two packages:

- The **glTF writer** is in the engine, OpenGLContext, because writing a model
  is engine machinery and a game's build step may call it.

- The **baker** (the spatial partition, the level of detail per tile, and the
  tileset) is in `OpenGLContext-editor
  <https://github.com/mcfletch/openglcontext-editor>`__, a separate install. A
  shipped game does not need it.

Bake a world now
----------------

``glisteel-bake`` comes with :doc:`the track editor <glisteel-editor>`. It
bakes the world that the editor ships with (hills, a river canyon, a lake, a
conifer forest and a circuit through them) into a directory you can open with
the viewer:

.. code-block:: bash

   pip install glisteel-editor
   glisteel-bake --output /tmp/world
   oglc-view /tmp/world/tileset.json

``glisteel-bake --view`` bakes the world and opens it in the viewer. Options
on the command line set the world's size, the detail of each tile, and how
deep the tree goes:

.. code-block:: bash

   glisteel-bake --output /tmp/world --extent 8192 --depth 5 --resolution 65

``--extent``
   The width of the world in metres, centred on the origin.
``--depth``
   How many times the tree subdivides. Each level has four times as many tiles
   and twice the ground detail, so depth has the largest effect on both quality
   and bake time.
``--resolution``
   Ground samples across each tile: the number of vertices one tile spends.
   Detail is this divided by the tile's size. Raising it instead of
   ``--depth`` gives larger tiles rather than more of them.
``--tree-density``, ``--max-instances``, ``--seed``
   Trees per square metre, the maximum number of instances written into any one
   tile, and the random seed. The same seed bakes the same world.

.. _writing:

Writing glTF from your own code
-------------------------------

``OpenGLContext.loaders.gltf.writer`` is the counterpart of the :doc:`glTF
loader <gltf>`. It takes the same ``PBRMesh`` geometry and ``PBRMaterial``
materials the loader produces, and writes a binary ``.glb``. A written mesh
loads back as the same mesh.

.. code-block:: python

   from OpenGLContext.loaders.gltf import write_glb
   from OpenGLContext.scenegraph.pbrmesh import PBRMesh

   write_glb(PBRMesh(positions=points, normals=normals, indices=indices),
             path='tile.glb')

``write_glb`` takes a mesh, a list of meshes, or ``SceneNode`` objects. A
``SceneNode`` adds a name, a local transform and children. The writer writes
the parts of glTF that the PBR renderer reads:

- position, normal, UV, tangent and colour attributes;
- metallic-roughness materials with their five texture channels and the
  ``KHR_materials_*`` factors;
- embedded images with their samplers.

Index buffers are written as 16-bit values when the vertex count allows.
Skinning, animation and morph targets are not written.

A material's ``DEF`` is written as its glTF material name, so an application
that finds a material by name in one document finds it by the same name in a
document written from it. See :ref:`Driving a model by name <names>`. To set
the name yourself, call ``GLTFWriter.add_material( material, name=... )``.

Many copies of one mesh
~~~~~~~~~~~~~~~~~~~~~~~

An ``InstanceSet`` on a node writes the standard ``EXT_mesh_gpu_instancing``
extension. Thousands of placements of one mesh fit in a single document and
load as one instanced draw:

.. code-block:: python

   from OpenGLContext.loaders.gltf import InstanceSet, SceneNode, write_glb

   write_glb(SceneNode(mesh=tree, instances=InstanceSet(
       translations=positions,        # (N,3)
       rotations=quaternions,         # (N,4) xyzw, optional
       scales=scales)),               # (N,3), optional
       path='trees.glb')

Textures
~~~~~~~~

A material's ``textures`` dictionary is written one channel at a time, with
its PIL images embedded as PNG. To keep a JPEG as a JPEG, wrap it in an
``EncodedImage``. Re-encoding a photographic texture as PNG makes a tile much
larger with no visible gain:

.. code-block:: python

   from OpenGLContext.loaders.gltf.writer import EncodedImage

   material.textures['baseColor'] = EncodedImage.from_path('bark.jpg', srgb=True)

.. _roundtrip:

Example: a round trip
~~~~~~~~~~~~~~~~~~~~~

.. figure:: images/demos/bake_demo.jpg
   :alt: A cairn of grey boulders under a gold capstone, ringed by twelve pebbles on green vertex-coloured ground

   ``python tests/bake_demo.py`` builds a scene in code, writes it to a
   ``.glb``, loads it back and draws it. What you see is the loaded file. Three
   of the boulders share one mesh, the twelve pebbles are one more mesh under an
   ``InstanceSet``, and the ground is a vertex-coloured ``terrain_patch`` placed
   by its node's translation. Press ``r`` to print the counts again. The written
   file stays on disk, so you can open it in another viewer.

The demo counts what it wrote from the document's JSON, and what it loaded
from the resulting scenegraph. The two columns are separate measurements:

.. code-block:: bash

   $ python tests/bake_demo.py
   wrote /tmp/gltf-writer-demo-95gl6ypw/cairn.glb
                     written    read back
   nodes                   7            7
   meshes                  4            4
   materials               3            3
   vertices            4,480        4,480
   triangles           4,002        4,002
   instances              12           12
   bytes             203,692      227,224
   208,260 bytes on disk: that buffer, the JSON describing it, and the
   GLB headers. The loaded arrays weigh more because an index that is 16 bits
   in the file is 32 in the buffer the GPU is handed.

Seven nodes over four meshes shows that sharing survives the round trip. The
boulder mesh is written once and placed three times, and it loads back as one
``PBRMesh`` under three ``Shape`` nodes. The boulders and the pebbles share
the stone material, so three materials cover the four meshes.

The same steps in an application:

.. code-block:: python

   from OpenGLContext.loaders.gltf import GLTFWriter, SceneNode, load_gltf
   from OpenGLContext.scenegraph.props import rock_mesh

   boulder = rock_mesh(radius=1.3, seed=3)                 # one mesh...
   writer = GLTFWriter()
   writer.add_node(SceneNode(name='cairn', children=[
       SceneNode(mesh=boulder, translation=(x, 0.0, z))    # ...placed three times
       for x, z in [(-1.7, 0.4), (1.6, -0.7), (0.3, -2.4)]]))
   writer.write('/tmp/cairn.glb')

   document = writer.document()
   print(len(document['meshes']), 'mesh,', len(document['nodes']), 'nodes')
   scene = load_gltf('/tmp/cairn.glb')                     # mount scene.group to draw

This prints ``1 mesh, 4 nodes``. Everything this code and the demo import
ships with OpenGLContext. The baker, which turns a world into a streamable
tileset, comes with `OpenGLContext-editor
<https://github.com/mcfletch/openglcontext-editor>`__.

Saying what a thing is
~~~~~~~~~~~~~~~~~~~~~~

A material and a ``SceneNode`` each carry two slots for what the geometry alone
cannot say. ``extras`` is written through uninterpreted — the format's own place
for what an application knows — and ``hook`` becomes an :ref:`OGLC_hook <hooks>`
extension block, which is how a baked world says that this surface is water and
that object is a spawn point:

.. code-block:: python

   lake.hook = {'kind': 'water', 'style': 'lake', 'depth': 4.0}
   writer.add_node(SceneNode(mesh=lake, extras={'OGLC_castsShadow': 0}))

Both survive a load and a re-bake, so an editor can open a world, move the lake
and write it out still marked. A reader that has never heard of either draws the
same geometry it always would.

What the baker produces
-----------------------

The baker writes a directory holding one ``tileset.json``, a ``.glb`` per
tile, and a ``CREDITS.txt`` that lists the sources the world was made from.
The tileset is OGC 3D Tiles 1.1, written so that a 1.0 reader can also load
it. ``OpenGLContext.loaders.tiles3d`` streams it.

The partition
~~~~~~~~~~~~~

By default the tree subdivides **in X and Z** only. A world whose content sits
on a surface has one ground level per column, and splitting the empty air
above it only adds tree nodes. For a world with content at several heights,
such as a city with levels or a road tunnelling under a hill, pass
``split_axes=VOLUME_AXES`` to split into eight octants.

A tile's bounding volume is the box around what that tile wrote, joined with
its children's boxes, not the partition cell it came from. This keeps the
volume small enough for the screen-space-error test to be accurate. It also
guarantees what the traversal relies on: if a parent is outside the view,
every descendant is outside it too.

Level of detail
~~~~~~~~~~~~~~~

Refinement is ``REPLACE``: a tile's content is drawn instead of its whole
subtree. Each level must therefore be a coarser *version* of the same ground,
not a different part of it. Two mechanisms do this:

- Terrain is re-sampled for each tile. Every tile is meshed with the same
  vertex count over its own area. A child covers a quarter of its parent's
  ground with the same vertex count, so the ground gets four times finer at
  each level.

- Instances are thinned to a budget. A tile writes at most ``max_instances``
  placements, chosen by an even stride. A coarse tile carries a sparse, even
  sample of the forest, and the tiles below it fill it in. The stride is
  deterministic, so baking again produces the same world.

Each layer also chooses its mesh by the tile's error. A detail ladder of
``(error, mesh)`` pairs lets distant tiles carry a billboard impostor while
near tiles carry the full tree.

Geometric error
~~~~~~~~~~~~~~~

By default, the root's geometric error is its width divided by the terrain's
sampling rate. That is the scale at which drawing the root instead of its
children looks wrong. The error halves at every level. Leaf tiles have an
error of zero, which tells a reader that nothing finer exists. The writer
refuses a tree in which a child has a larger error than its parent, or lies
outside its parent's bounds.

Describing a world of your own
------------------------------

A world is a list of *layers*. For each node of the tree, the baker calls
every layer with the node's region and error, and the layer returns its
content for that region at that detail:

.. code-block:: python

   from OpenGLContext_editor.bake.bounds import BoundingBox
   from OpenGLContext_editor.bake.driver import bake_world
   from OpenGLContext_editor.bake.layers import HeightfieldLayer, InstanceLayer
   from OpenGLContext_editor.world.scatter import scatter_on_heightfield, yaw_quaternions

   ground = BoundingBox((-2048, 0, -2048), (2048, 0, 2048))
   terrain = HeightfieldLayer(height_fn=my_heights, extent=ground, resolution=33,
                              color_fn=my_colours, water_level=0.0)

   trees = scatter_on_heightfield(my_heights, ground, spacing=2.6, seed=11,
                                  slope_limit=38.0, height_range=(2.0, 130.0),
                                  slope_fn=terrain.field().slope)
   forest = InstanceLayer(positions=trees.positions,
                          rotations=yaw_quaternions(trees.yaws),
                          scales=trees.scales,
                          lods=[(0.0, conifer), (8.0, impostor)])

   result = bake_world([terrain, forest], '/tmp/world', depth=4,
                       credits=['Elevation: SRTM, public domain'])
   print(result.summary())

Scattering millions of points
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pass ``spacing`` (how far apart) rather than a density (how many) when the
instances will be thinned to a minimum separation. With a density, the
scatter places random candidates and then discards those too close together.
To fill the area, it needs several times as many candidates as it keeps, and
every candidate costs a height lookup, a distance-to-road query and four more
lookups for the slope. With a spacing, the scatter places points on a
jittered grid at that spacing. On the shipped four-kilometre world, half a
million trees take eight million candidates by density and two and a half
million by spacing, for the same forest.

Two more things keep a large scatter fast:

- The filters run cheapest first, and each one runs only on the points the
  previous one kept.

- ``slope_fn`` gives the slope from a height field that is already sampled. A
  bake builds a height field for the terrain before it scatters anything, so
  the slope is one lookup instead of four evaluations of the height function.
  It is also a better slope for placing trees: a central difference over one
  metre reads every small bump in an earthwork as a cliff, while a tree only
  cares about the hillside.

Layer types
~~~~~~~~~~~

``HeightfieldLayer``
   Ground meshed from a height function, with a per-vertex colour function, an
   optional flat water level, and a skirt (in vertex spacings) that hides the
   seam between a coarse tile and finer tiles beside it.
``InstanceLayer``
   One mesh placed many times, with the detail ladder and the per-tile instance
   budget described above.
``MeshLayer``
   Meshes at fixed positions, such as a building, a bridge deck or a prop.
   ``maximum_error`` leaves the content out of tiles too coarse for it to be
   worth the bandwidth.
``RoadLayer``
   A route through the world as a drivable surface (see :doc:`Roads <roads>`),
   with the embankments and cuttings it needs, and a bridge deck or tunnel bore
   where neither will do. The road is split so that each tile holds the length
   of road inside it, and it is re-sampled more coarsely in coarser tiles.
``FieldTerrainLayer``
   The ground as one height field rather than a tree of tiles. See :ref:`Ground
   as a field <field>` below.
``VegetationLayer``
   The whole forest as one table beside the tileset. See :ref:`A forest as a
   table <vegetation>` below.

A layer is any object with ``bounds()`` and ``content(region, error)``
methods, so a world can define its own layer types. Two more methods are
optional:

``assets()``
   Returns ``{filename: bytes}`` for files written once beside the tileset, for
   anything the content refers to rather than embeds. A road's surface texture
   is 440 KB and a road crosses many tiles. Written once and referred to by
   name, the texture is also loaded once.
``metadata()``
   Returns a dictionary that is merged into the tileset's ``extras``. Use it for
   information about the world that its geometry does not carry. A road puts
   its centreline here, because a game cannot find a track in a set of
   triangles. Two layers may add to the same key when its value is a *list*:
   the props a gantry sets up and the boulders scattered over a landscape are
   all props of one world, and a game reading them wants all of them. If two
   layers set the same key to anything else, the bake stops with an error.
   A value such as where a lap begins has one correct answer, and the bake
   does not pick one silently.

.. _field:

Ground as a field
~~~~~~~~~~~~~~~~~

A tiled ground gets finer as the tree refines, which a world larger than
memory needs. A world a few kilometres across does not: its whole landscape
fits in one height field. Drawn as a :ref:`splat terrain
<terrain-heightfield>` (one mesh, one draw, detail materials blended per
pixel), it costs less than a tree of vertex-coloured tiles and shows sharp
ground up to the camera. Use ``FieldTerrainLayer`` for such a world:

.. code-block:: python

   from OpenGLContext_editor.bake.field import FieldTerrainLayer

   ground = FieldTerrainLayer(height_fn=conformed, height_fn_at=conformed_at,
                              extent=footprint, resolution=1025,
                              layers=['grass', 'forest_floor', 'rock', 'dirt'],
                              rules=my_rules, road=circuit, road_layer=3)

This layer writes no geometry into the tiles. It writes a 16-bit height image
and an RGBA :ref:`splat control map <controlmap>` beside the tileset. In
``extras.terrain`` it writes the four numbers needed to read them back
(``extent``, ``base``, ``relief`` and ``resolution``) and the material names.
``TilesTerrain`` builds the field from these and exposes it as ``.field``, so
a game builds its :ref:`colliders <fieldphysics>` from the same landscape it
draws.

For a world with a road, also pass ``height_fn_at(spacing)``: the same ground
as a function of the spacing it will be sampled at. A road cutting narrower
than the sample grid would otherwise fall between samples and not appear,
however deep the height function says it is at its centre. Given the spacing,
the function widens the cutting's floor at its edges to that spacing, so at
least one sample lands inside it. ``conform_terrain_at`` produces such a
function.

.. _vegetation:

A forest as a table
~~~~~~~~~~~~~~~~~~~

Trees written into tiles load and unload with their tile, and their level of
detail follows the tile's. But how a tree should be drawn depends on its
distance from the *camera*, whichever tile it stands in. Trees baked into
tiles also repeat their bark and leaf data in every level of tile they appear
in.

``VegetationLayer`` writes the forest as a table instead:

.. code-block:: python

   from OpenGLContext.scenegraph.vegetation import TreeSpecies
   from OpenGLContext_editor.bake.vegetation import VegetationLayer

   forest = VegetationLayer(positions=trees.positions, yaws=trees.yaws,
                            heights=heights, species=my_species,
                            species_id=which_kind)

It writes the table as one compressed array file, copies each species' files
into the world under ``trees/``, and lists them in ``extras.vegetation``. The
baked world is self-contained: it refers to no path on the machine that baked
it. ``TilesTerrain`` builds a :ref:`VegetationField <vegetationfield>` from
the table and passes it the camera position each tick.

The scatter is decided at bake time. Where each tree stands, how tall it is
and which species it is are part of the world's design, decided once with the
road's corridor kept clear, and are not re-generated at runtime.

Tree art carries its own licence. The toolkit ships no tree art. If a world is
baked from assets that require attribution, pass the attributions to
``bake_world``'s ``credits``. They are written into the tileset's copyright
and its ``CREDITS.txt``.

.. _cover:

Ground cover as a recipe
~~~~~~~~~~~~~~~~~~~~~~~~

Plants on the ground *between* the trees are not written out one by one.
There are far too many blades of grass to write each one, and none of them is
a design decision, so the bake writes a recipe instead:

.. code-block:: python

   from OpenGLContext.scenegraph.vegetation import CoverSpecies

   forest = VegetationLayer(..., cover=[
                                CoverSpecies(name='grass', card='grass_card.png',
                                             clump='grass.glb', density=11.0,
                                             height=0.15, patchiness=0.25),
                                CoverSpecies(name='fern', card='fern_card.png',
                                             clump='fern.glb', density=0.7,
                                             height=0.43, patchiness=0.7,
                                             canopy=(3.0, 16.0))],
                            cover_on=['grass', 'forest_floor'])

``cover`` takes a list of plants, because a forest floor has several: grass,
fern, nettle, shrub. A single ``CoverSpecies`` is also accepted and means a
list of one. Each species sets how densely it grows (``density``), how much it
gathers into patches (``patchiness``), and the range of tree cover it grows
under (``canopy``). The result has thickets where the trees thin out and a
bare floor under dense trees. ``oglc-bake-plants`` makes cover species from
published plant scans; see :ref:`where the plants come from <coverassets>`.

Their files are copied into the world like a tree species' files. A file that
two species share, such as two variants baked from one scan, is copied once.
``cover_on`` names the ground layers the plants grow on. The viewer places the
clumps around the camera as it moves; see :ref:`what grows between the trees
<groundcover>`. The splat control map decides where cover grows, so **the
control map must be fine enough to show the road**. Grass grows over a road
corridor narrower than one control-map pixel. Set the map's size with
``FieldTerrainLayer(control_size=…)``.

.. _baking-props:

Obstacles
~~~~~~~~~

``OpenGLContext_editor.bake.props.PropLayer`` writes a world's obstacles
twice: as one instanced node per kind in the tiles that contain them, and as
a list in the tileset's ``extras``. The geometry loads and unloads with its
tile, but a physics body must stay in the world, so the body comes from the
list. See :ref:`things in the way <roads-props>`.

.. code-block:: python

   from OpenGLContext.scenegraph.props import Prop, rock_mesh
   from OpenGLContext_editor.bake.props import PropLayer

   PropLayer(props=[Prop.of(stone, kind='rock', position=at, scale=1.3)],
             prototypes={'rock': stone})

``prototypes`` gives the mesh drawn for each kind, at the origin with its base
at y=0. Each placement scales and turns it. ``Prop.of`` measures a prop's
radius and height from that mesh, so a physics world can create a body for it
without the geometry.

.. _baking-gantry:

The start/finish line
~~~~~~~~~~~~~~~~~~~~~

``OpenGLContext_editor.bake.gantry.GantryLayer`` writes a circuit's
start/finish gantry. The frame and the line painted under it go into the tile
that contains them, as one mesh with one texture. The two legs go into the
world's props, so a car can hit them. ``world.gantry.start_finish`` places the
gantry from the road: it finds the road's crown at the line, spans the
carriageway and its shoulders, and measures the ground under each leg:

.. code-block:: python

   from OpenGLContext_editor.bake.gantry import GantryLayer
   from OpenGLContext_editor.world.gantry import start_finish

   GantryLayer(placement=start_finish(circuit, ground=height_fn))

``station`` is the distance along the road at which the line is drawn. The
default is zero, where a lap begins. See :ref:`the start/finish line
<roads-gantry>` for the gantry itself.

Bringing in authored assets
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``meshes_from_gltf`` reads a designer's ``.glb`` and returns its meshes in one
coordinate frame, with the file's transforms applied, ready to place.
``combined_mesh`` merges them into one mesh, so a whole prototype is one
instanced node:

.. code-block:: python

   from OpenGLContext_editor.bake.assets import combined_mesh, meshes_from_gltf

   parts = meshes_from_gltf('assets/conifer.glb', scale=1.2)   # bark, needles
   crate = combined_mesh(meshes_from_gltf('assets/crate.glb'))  # one material

``combined_mesh`` refuses meshes with different materials, because the result
can have only one material. A tree has a bark trunk and alpha-masked needles,
and merging them would paint the needles with bark. Either keep the meshes
separate (a rung of an ``InstanceLayer``'s ladder can hold several meshes,
each written as its own node over the same placements), or pass the material
the merged mesh should use.

.. _manifest:

The world manifest
------------------

A tileset describes how to draw a world, not what the world is. A menu that
offers a choice of worlds needs to show each world's name, the length of its
road, how much of that road is on bridges and in tunnels, and a picture. It
should not have to load each world to find those out.

So a bake writes ``world.json`` beside the tileset, and a chooser reads a
directory of them:

.. code-block:: python

   from OpenGLContext.loaders.tiles3d.manifest import read_manifest

   found = read_manifest( '/worlds/ashdown-forest' )     # or its tileset, or the manifest
   print( found.summary() )                              # 'Ashdown Forest, 8.3 km'

``name`` is the only required field. Every other field is optional, so a
manifest without a field still loads. ``tileset`` and ``picture`` are paths
relative to the manifest, so a world is one directory that can be moved or
copied. ``roadLength`` is in metres. ``structures`` gives the length of road,
in metres, on each kind of structure, which distinguishes a circuit of bridges
and tunnels from a road that follows the land.

.. code-block:: json

   {
     "baked": "2026-08-19",
     "closed": true,
     "extent": 4096.0,
     "name": "Ashdown Forest",
     "picture": "track.png",
     "roadLength": 8306.87,
     "seed": 11,
     "structures": { "bridge": 1529.5, "causeway": 515.9, "tunnel": 795.2 },
     "tileset": "tileset.json"
   }

The file is indented with full key names, so you can rename a world or give it
a picture by editing it. ``read_manifest`` returns ``None`` for a manifest
that does not parse, rather than raising, so a chooser scanning a directory of
worlds skips the broken one and offers the rest.

``glisteel-bake`` writes a manifest for every bake. The world's name is the
output directory's name, unless ``--name`` sets another.

Limits
------

- Content is written in world coordinates, with no per-tile transform.
  Positions are 32-bit floats, which gives sub-millimetre precision within a
  few kilometres of the origin. A world placed at its true position on the
  globe would lose that precision, so baked worlds are not georeferenced.

- Dense grass near the camera is not baked. Grass at the density the eye
  expects, over a whole map, is far more geometry than a tileset can hold. The
  runtime's camera-following vegetation field draws it within a radius of the
  player, reading baked 2D masks for its density. For grass, the baker writes
  only those masks.

- The region a bake partitions defaults to everything the layers cover,
  including their height. If you pass an explicit ``bounds`` with no height,
  the bake partitions a slab of zero height and discards almost all content.
