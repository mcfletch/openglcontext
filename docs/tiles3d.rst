Streamed 3D Tiles
=================

.. rst-class:: introduction

A world too big to load streams as an **OGC 3D Tiles** octree of **glTF**
tiles: a screen-space-error traversal refines detail toward the camera,
frustum culling keeps the resident set a moving window around the view, and
tiles page in and out under a memory budget on background threads. The same
tiles carry per-tile collision meshes, so a character *walks on exactly what
it sees* and a car drives on it. The indented technical notes point at the
code, all under ``OpenGLContext/loaders/tiles3d/``.

This is the path a large world takes. :doc:`GLinting Steel <glisteel>` drives
one, and :doc:`Baking a World <baking>` is how one is written. A landscape
that fits in memory whole needs none of it: see :ref:`Terrain & Landscapes
<terrain-heightfield>` for the height-field path, which the :doc:`forest demo
<terrain>` runs on.

.. figure:: images/gallery/showcase/tiles-toronto.jpg
   :alt: A city of blocky buildings stretching to the horizon under a clear sky
   :class: shot

   An OGC 3D Tiles dataset streamed from an octree, refined by screen-space error
   as the camera moves. City of Toronto 3D massing, Open Government Licence.

Quick start — walk a world
--------------------------

The viewer is the ``oglc-terrain`` command (installed with the package) or,
from a checkout, ``python -m OpenGLContext.bin.terrain_view``:

.. code-block:: bash

   oglc-terrain                         # walk the default procedural world
   oglc-terrain --fly                   # start in free-fly
   oglc-terrain --extent 4096 --levels 4   # a bigger, deeper-LOD world (85 tiles)
   oglc-terrain --dem heightmap.png --height-scale 600   # a real heightmap
   oglc-terrain path/to/tileset.json    # view an existing 3D Tiles tileset
   oglc-terrain --size 1280x720 --sse 12 --memory 512    # window + quality/budget

**Controls:** ``W A S D`` move, ``Q E`` turn, ``Shift`` (hold) sprint,
``Space`` jump, ``G`` toggles walk / fly, ``R F`` rise / descend while flying,
and ``-``\  / \ ``=`` slow down / speed up (fly & sprint). Fly is fast, for
covering a big world quickly.

A dense forest of instanced conifers and knee-high grass surrounds you,
refreshed as you move so it stays dense wherever you walk, with the sun
casting shadows through the canopy. Trees and grass are **alpha-cut textured
cards** (procedural bark, pine-needle and grass-blade textures) rather than
solid geometry, so they read as foliage. Tune density with ``--density``
(lower is faster) or drop it with ``--no-vegetation``. :doc:`Vegetation
<vegetation>` is the whole subject.

.. rst-class:: technical

For a procedural/DEM world the close-up ground is a detailed camera-following
**textured patch** (photographic CC0 material) rather than the coarse streamed
tiles, so it can carry real detail; the streamed tiles are used only to view a
raw ``tileset.json``. Materials come from **ambientCG** (CC0, cached under the
per-user app-data directory with a provenance manifest) via
``loaders/cc0.py``, with a procedural fallback offline. The download and each
map taken out of its archive are size-capped (``cc0.MAX_ARCHIVE_BYTES``,
``cc0.MAX_MEMBER_BYTES``). Foliage textures and textured glTF prototypes are
in ``loaders/tiles3d/foliage.py`` (grass/bark/needle generators, CC0-bark
option, alpha-MASK cards, instanced); shadows are the engine's cascaded shadow
maps (``OPENGLCONTEXT_SHADOWS``, see :doc:`Shadow Mapping <shadows>`).

.. rst-class:: technical

The viewer is ``bin/terrain_view.py``. It needs the **PBR renderer** (it sets
``OPENGLCONTEXT_RENDERER=pbr`` and the GLFW backend itself), because terrain
tiles are PBR glTF and their per-vertex colours only render under the PBR
pass. Input is bound on both key-down and character events (some Wayland/GLFW
setups deliver only the latter), and the character controller drives the
camera from ``OnIdle`` with the default free-fly navigator unbound so the two
don't fight. **Ground collision is analytic**: the avatar is clamped to
``height_fn(x, z)`` each frame — exact, matching the visible tiles, and
impossible to tunnel through at any frame rate — so no separate collision mesh
is needed for the floor. Vegetation is instanced (one shared prototype per
layer) with a full-mesh-near / single-cone-far LOD, in two camera-following
fields (frequent grass, occasional trees). Water is a translucent plane at the
water level.

.. _tiles3d:

Viewing real 3D Tiles datasets (experimental)
---------------------------------------------

.. rst-class:: technical

**3D Tiles support is experimental.** A city-sized dataset loads, streams and
is walkable, and the known faults are recorded in
``plans/TILES3D-CITY-VIEWING.md``: tiles whose geometry floats above its
ground, an initial load that fetches far more of the dataset at once than the
view needs, and a frame rate around 30 fps at city scale. The APIs here may
change while those are dealt with.

``oglc-terrain`` above is the procedural/DEM playground. To load and stream a
**real, third-party OGC 3D Tiles dataset** — a photogrammetry capture, a city
model, a GIS terrain — open it with ``oglc-view``. It is the interactive front
end for the ``loaders/tiles3d`` runtime and is built for the parts real data
actually uses:

.. code-block:: bash

   oglc-view path/to/tileset.json           # a local tileset
   oglc-view https://host/path/tileset.json     # stream a tileset straight from the web
   oglc-view tileset.json --sse 8           # more detail (lower screen-space error)
   oglc-view tileset.json --memory 1024     # bigger tile memory budget (MiB)
   oglc-view tileset.json --capture shot.png    # render one offscreen still, then exit

The ``source`` is a local path *or* an ``http(s)://`` URL; with a URL the
root, its tile content, and any external tilesets are fetched over the network
and cached on disk (under ``~/.cache/openglcontext/tiles3d``, or
``--cache-dir``), so each tile downloads once. It auto-frames the whole
tileset at startup and lets you **free-fly** with the mouse and ``W A S D``/
arrow keys; tiles stream in and out by screen-space error as you move.
Supported today:

What a tileset is allowed to reach
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A ``tileset.json`` names its own tile payloads and nested tilesets, so for a
tileset from anywhere but this machine those URIs are chosen by whoever wrote
it. They are held to the same rules as a glTF document's external references:

- a tileset served over ``http(s)`` may reference only the **same origin** — the
  scheme, host and port it was fetched from — re-checked on every redirect, so a
  tile URI cannot name another host or an address on the local network;

- a tileset loaded from disk may read only files **under its own directory**;
  and

- every payload is **size-capped** (``tiles3d.fetch.DEFAULT_MAX_TILE_BYTES``,
  256 MiB by default; pass ``max_bytes`` to ``read_bytes`` for a dataset that
  genuinely ships larger tiles).

*\ *What is unrestricted is which URI you may *\ name\ *, not what the
document at it may do.*\ * Naming a URL is a decision only you can make — the
viewer fetches what you point it at, as ``curl`` would — and from there the
file is untrusted like any other: the payload is size-capped, redirects on
that first fetch are locked to the origin you named (so a server cannot bounce
it to a link-local address), and every URI the document goes on to name is
confined by the rules above. A dataset split across two hosts needs its own
resolver passed to ``build_runtime_tileset``. The policy itself lives in
``loaders/resolver.py``, which is the one place it is written down.

.. rst-class:: technical

Not yet bounded: the *number* of tiles a tileset may name. Each payload is
capped and the resident set is held to the memory budget, but a hostile
tileset can still name unboundedly many tiles and fill the on-disk fetch
cache. Recorded in ``plans/TILES3D-CITY-VIEWING.md``.

- local files and ``http(s)://`` URLs for the root, tile content and nested
  tilesets, with an on-disk fetch cache.

- glTF/GLB and ``b3dm`` tile content (the Batched-3D-Model wrapper is unwrapped
  to its embedded GLB and rendered by the normal glTF loader).

- box, sphere and geodetic ``region`` bounding volumes (regions convert to
  WGS 84 ECEF, as used by Cesium ion / Google Photorealistic / most GIS
  tilesets).

- **external (nested) tilesets** — a tile whose content is another ``.json`` is
  loaded and grafted into the tree.

- **The dataset's own frame, brought into the viewer's.** 3D Tiles places tiles
  in a Z-up frame and this renderer draws a Y-up world, so a dataset is turned
  to match: an **Earth-centred** one is recentred to the origin (32-bit float
  precision) and **levelled** at that reference point, so the ground lies in the
  XZ plane instead of tilting off toward the globe's centre; a **local** one is
  turned the same quarter turn its content is. Both are what ``--no-recenter``
  switches off, which gives the dataset exactly as written. Non-identity tile
  transforms are honoured.

- **The glTF up-axis convention**: 3D Tiles frames are Z-up while glTF content
  is Y-up, so content is rotated a quarter turn into its tile's frame, as
  ``asset.gltfUpAxis`` asks (``Y`` when a tileset does not say; ``Z`` means the
  content is already in the tile frame, which is what the bakers here write).
  Without this a conforming export renders on its side.

- **multiple contents per tile** (3D Tiles 1.1 ``contents``), e.g. buildings and
  trees as separate glTF combined into one tile.

.. rst-class:: technical

Tested against Cesium's ``TilesetWithDiscreteLOD`` sample (a ``tileset.json``
with an ECEF root transform and a ``low→medium→high`` ``b3dm`` LOD chain): the
framed view selects the coarse tile and flying closer (or ``--sse 0.02``)
refines to the finest. Like ``oglc-terrain`` it forces the core profile + PBR
renderer. A known limitation: a hard camera teleport can hole for a few
frames, because REPLACE refinement keeps no standing coarse-LOD fallback
resident; gradual flight sharpens in cleanly.

.. _samples:

Sample datasets to try
~~~~~~~~~~~~~~~~~~~~~~

The **CesiumGS 3D Tiles sample tilesets**
(`github.com/CesiumGS/3d-tiles-samples
<https://github.com/CesiumGS/3d-tiles-samples>`__, Apache 2.0) are small and
self-contained, and served over raw GitHub with no authentication — so you can
stream them **straight from the URL, no download step**. These are verified to
load:

.. code-block:: python

   # Cesium "dragon" — b3dm, an ECEF transform and a low/medium/high LOD chain
   oglc-view https://raw.githubusercontent.com/CesiumGS/3d-tiles-samples/main/1.0/TilesetWithDiscreteLOD/tileset.json
   #   add --sse 0.02 to pull the finest LOD over the network

   # 1.1 glTF-native scene — houses and trees, several glTF contents per tile
   oglc-view https://raw.githubusercontent.com/CesiumGS/3d-tiles-samples/main/1.1/MetadataGranularities/tileset.json

   # 1.1 multiple-contents plane
   oglc-view https://raw.githubusercontent.com/CesiumGS/3d-tiles-samples/main/1.1/MultipleContents/tileset.json

Each tile is cached under ``~/.cache/openglcontext/tiles3d`` on first fetch,
so re-runs are offline and instant. Prefer a local copy? Clone the repo (``git
clone https://github.com/CesiumGS/3d-tiles-samples``) and pass a path to
``…/1.0/TilesetWithDiscreteLOD/tileset.json`` instead — identical result. You
can also point the viewer at any tileset you bake yourself with
``oglc-terrain`` (see :ref:`Making a world <making>`), at a world :doc:`baked
from an authored description <baking>`, at :doc:`a city exported from
OpenStreetMap <osmcity>`, or at your own captures exported to 3D Tiles
(RealityCapture, Cesium ion, py3dtiles, etc.).

.. rst-class:: technical

**Not yet loadable** (the viewer skips or errors on these): point clouds
(``.pnts``), instanced models (``.i3dm``), composite tiles (``.cmpt``), and
implicit tiling (``.subtree``) — so Cesium's ``TilesetWithTreeBillboards``
(i3dm), ``TilesetWithRequestVolume`` (pnts) and the ``SparseImplicit*``
samples don't render yet. Plain ``http(s)://`` tilesets stream fine (above);
only **API-key services** (Cesium ion, Google Photorealistic 3D Tiles) need
auth headers / token handling that isn't wired up — for those, export or
download the tiles first.

How it works
------------

Terrain is an OGC 3D Tiles dataset: a ``tileset.json`` bounding-volume
hierarchy whose leaves are glTF meshes. Every frame the runtime walks the
tree, converts each tile's *geometric error* to a *screen-space error*
(pixels) against the live camera, and refines a tile into its children only
while that error exceeds a threshold — so detail concentrates near the viewer.
Frustum culling prunes tiles outside the view, which is what bounds the
working set.

.. rst-class:: technical

``screenspaceerror.py`` (the perspective SSE), ``tileset.py`` (the parsed
world-space tree; we parse box/sphere ourselves because py3dtiles rejects
sphere volumes), ``traversal.py`` (``select_tiles`` → a render set and a
speculative *want* set), and ``frustum.py`` (Gribb-Hartmann plane extraction +
``bounding_sphere`` tests).

Streaming is what the traversal *decides*: wanted tiles that are not resident
are queued for background loading (priority by distance); finished loads are
uploaded to GL, throttled per frame; and tiles that fall out of the want set
are evicted least-recently-wanted-first once the resident bytes exceed the
budget. A tile still loading falls back to its nearest resident ancestor, so
the world sharpens in rather than popping holes.

.. rst-class:: technical

``loadmanager.py`` (priority queue + worker pool, cancellable),
``residency.py`` (lifecycle ``UNLOADED→LOADING→READY→RENDERABLE``, LRU
eviction under a byte budget), and ``runtime.py`` (``TilesetRuntime.update``
ties it together each frame). Loading and glTF parsing run off the render
thread; only the cheap mount and draw are on the GL thread.

The runtime is mounted as a scenegraph node, ``TilesTerrain``, so it renders,
shadows and picks like any other geometry. Each resident tile also registers
its mesh as a static *trimesh* collider in a physics world, which is what
makes the terrain walkable.

.. rst-class:: technical

``scenegraph/tilesterrain.py`` (the node; call ``update_for_camera(camera,
viewport_height, view_projection=…)`` each frame before rendering) and
``physics_colliders.py`` (streams colliders via the runtime's
``on_renderable``/``on_evicted`` hooks). See :doc:`Physics & Collision
<physics>` for the character controller.

.. _making:

Making a world
--------------

Three sources feed one baker. Each writes a ``tileset.json`` plus its ``.glb``
tiles and returns the tileset path.

.. code-block:: python

   from OpenGLContext.loaders.tiles3d import procedural, dem

   # 1. Procedural: hills, canyon, lake, mountains (per-vertex coloured, with skirts).
   procedural.build_terrain_tileset("world/", extent=2048, levels=3, tile_res=33)

   # 2. A real heightmap (grayscale DEM from QGIS/USGS/SRTM, any format PIL reads):
   dem.build_dem_tileset("dem.png", "world/", extent=4096,
                         height_scale=600, base=-40, levels=4)

   # 3. Your own function y = f(x, z) (numpy arrays in, heights out):
   procedural.build_terrain_tileset("world/", height_fn=my_height_fn)

Mount the result and drive it from the camera each frame:

.. code-block:: python

   from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
   terrain = TilesTerrain("world/tileset.json", max_sse=16.0,
                          physics_world=world)          # physics_world optional
   # in your render/idle callback, before the pass runs:
   terrain.update_for_camera(eye_xyz, viewport_height, view_projection=vp_matrix)

.. rst-class:: technical

A ``quadtree`` of depth *L* has ``sum(4**l)`` tiles; each is meshed at
``tile_res`` vertices per edge, so deeper tiles cover less ground at the same
vertex count (finer detail). The procedural field (value-noise fBM + ridged
mountains + a carved canyon + a lake basin) is ``procedural.terrain_height``;
colours come from height and slope in ``terrain_colors``. A **skirt** is
dropped around every tile edge (``terrain_patch(skirt_depth=…)``) so seams
between adjacent LOD tiles show no gaps.

What the shipped landscape is made of, and how to describe another one, is
:ref:`a terrain profile <terrainprofile>`. A world with roads, water,
vegetation tables and placed props in it is written by the octree baker
instead — see :doc:`Baking a World <baking>`.

Refining & tuning
-----------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Knob
     - Effect
   * - ``--sse`` / ``max_sse``
     - screen-space-error target in pixels; *lower = more detail* (more tiles, higher
       cost)
   * - ``--memory`` / ``memory_budget``
     - resident tile byte budget; smaller forces more aggressive eviction/streaming
   * - ``--extent``, ``--levels``, ``--tile-res``
     - world size, LOD depth (tile count), and per-tile mesh resolution
   * - ``prefetch_factor``
     - how far ahead finer tiles load before they are strictly needed (hides pop-in
       when moving)
   * - ``hysteresis``
     - sticky refinement so LOD does not flicker at the threshold
   * - ``--dem``, ``--height-scale``, ``--base``
     - ingest a real heightmap; ``base``\ <0 sinks low areas below the water level so
       they read as lakes/sea

.. rst-class:: technical

The runtime exposes these on ``TilesetRuntime``/ ``TilesTerrain``
constructors. Frustum culling is enabled by passing a ``view_projection`` to
``update_for_camera``; without it, tiles are considered by distance only
(useful for tests, wasteful for a real view).

Caves, overhangs & arbitrary 3D
-------------------------------

Because tiles are ordinary glTF meshes, terrain is not limited to a height
surface: a cave, arch or overhang is just a tile with arbitrary geometry,
placed in the octree and streamed, culled and collided like any other. A
heightfield cannot express the solid-air-solid column of an overhang; a glTF
tile can.

.. rst-class:: technical

``sample.build_overhang_tileset`` bakes an elevated slab over ground (genuine
solid-air-solid) that streams, renders and yields a walkable collider — the
pattern a procedural voxel/Transvoxel cave baker would follow.

Demos & validation
------------------

- ``oglc-terrain`` — the procedural/DEM interactive viewer (above).

- ``oglc-view`` — stream and fly a real OGC 3D Tiles ``tileset.json`` (b3dm,
  region volumes, external + ECEF tilesets).

- ``tests/tiles_landscape.py`` — aerial showcase (terrain + vegetation).

- ``tests/tiles_walk.py`` — first-person walk/fly.

- :doc:`GLinting Steel <glisteel>` — the path at full size: a baked world
  streamed in around a car, its tiles becoming the surface it drives on.

.. rst-class:: technical

The behaviour is pinned by ``tests/tiles3d/`` (SSE, traversal, residency, load
manager, runtime, frustum, procedural terrain, DEM, scatter/vegetation,
geomorph/skirts, and **navigation**: gravity settles the avatar on the
surface, walking follows it, flying ascends, fly→walk drops to the surface —
including on the actual streamed colliders) plus offscreen render regressions
(``tests/test_tiles_*_render.py``). Run them with ``python -m pytest
tests/tiles3d/``.
