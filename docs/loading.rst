.. _structure-loaders:

Loading Content
===============

.. rst-class:: introduction

OpenGLContext reads these formats into its scenegraph: X3D and VRML97 worlds,
glTF 2.0, GLB and VRM models, Wavefront OBJ, STL, PLY and OFF models, and
streamed OGC 3D Tiles datasets. This page shows the call that loads each from
Python, what it returns, and how to wait for the files a scene names. To open
a file and look at it without writing any code, use :doc:`oglc-view <viewer>`,
which opens all of them.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Format
     - Call
     - Returns
   * - X3D (``.x3d``, ``.x3dz``, ``.x3dv``, ``.x3dvz``, ``.x3dj``, ``.x3djz``,
       ``.x3db``, and each with ``.gz`` appended)
     - ``Loader.load(url)``
     - an ``X3DScene``, a ``sceneGraph``
   * - VRML97 (``.wrl``, ``.wrz``, ``.vrml``, ``.wrl.gz``)
     - ``Loader.load(url)``
     - a ``sceneGraph``
   * - Wavefront OBJ (``.obj``, ``.obj.gz``)
     - ``Loader.load(url)``
     - a ``sceneGraph``
   * - STL, PLY, OFF (``.stl``, ``.ply``, ``.off``, each also ``.gz``)
     - ``Loader.load(url)``
     - a ``sceneGraph``
   * - glTF 2.0 (``.gltf``, ``.glb``, ``.vrm``, ``.gltf.gz``, ``.glb.gz``)
     - ``gltf.load_gltf(path)``, ``gltf.load_gltf_url(url)``
     - a ``GLTFScene``, whose ``group`` is the scenegraph
   * - OGC 3D Tiles (``tileset.json``)
     - ``TilesTerrain(path_or_url)``
     - a node that streams its tiles as the camera moves

Each result is ordinary scenegraph nodes. Add them to a context's ``self.sg``,
or under a ``Transform`` of your own to place, scale or turn what was loaded.
Every loader resolves the files a document names (textures, ``.bin`` buffers,
material libraries, inlined scenes) against that document's own location, and
only there; :doc:`Loading content you did not write <untrusted>` gives the
rules.

Each of these takes the path or URL as a string, checks it once
(``resolver.checked_source``: a local path, or an http(s) URL), and hands the
checked value to the readers below it, which accept nothing else (see
:ref:`checked-types`). A document's JSON is read as a ``JSONObject``, and a
part the format requires that is missing or of the wrong type is a
``DocumentError`` (a ``ValueError``) naming it.

.. _scene-loader:

The scene loader
----------------

Every context holds a ``SceneLoader`` as ``self.sceneLoader``. It reads a file,
a URL or a document in memory on a worker thread and delivers the result on the
render thread, so a model downloads and decodes while the window goes on
drawing:

.. code-block:: python

   class Viewer( Context ):
       def OnInit( self ):
           self.sceneLoader.load( 'model.glb', on_loaded=self.show,
                                  on_failed=self.report )

       def show( self, request ):
           self.sg = sceneGraph( children=[ request.result.group ] )

       def report( self, request ):
           print( 'could not load %s: %s' % ( request.label, request.error ) )

``load()`` takes a path or an ``http(s)`` URL as a string, or the bytes of a
document. The format comes from ``format=`` where given (``'gltf'``,
``'x3d'``, ``'vrml97'``, ``'obj'``, ``'tiles3d'``, or a name registered
since), then from ``content_type=``, then from the source's name, and for a
local ``.json`` from what is inside it: X3D JSON by its ``"X3D"`` key, a
tileset by its ``asset`` and ``root``. Bytes have no name, so ``name='chair.glb'`` says what they
would be called as a file: that chooses the format, and is where a ``.gltf``
looks for the files it names. A source no registered format opens raises
``UnknownSourceType`` at once, naming the suffixes that are known.
``options=`` is given to the format's reader to configure itself with, and
``reader=`` supplies a reader to use instead of choosing one, for a program that
keeps it to ask more of it later.

``request.result`` is what the format's own loader produces: a ``GLTFScene``
for glTF, a ``SceneGraph`` for X3D, VRML97 and OBJ, the streaming ``TilesTerrain``
for 3D Tiles, a game's level for a game's format. The loader does nothing with
it; whether it is mounted, kept or discarded is for the caller. The reader that
read it, which knows how to frame and animate it, is ``request.reader``.

``submit()`` runs any callable the same way, for a result no registered format
reads. The callable takes no arguments and **must not touch GL**.
``load_now()`` reads on the calling thread and returns the finished request, for
a program that has to have the scene before it goes on.

Requests are independent. Any number may be in flight and each is delivered once,
when it finishes; a request that raises reaches its own ``on_failed`` and
disturbs no other. A program that wants only the newest of a sequence keeps the
request it made last and calls ``request.cancel()`` before making the next. A
cancelled request is never delivered, though its worker finishes the read, since
a read cannot be interrupted.

A request is also announced as the signals ``SCENE_LOADING``, ``SCENE_LOADED``
and ``SCENE_FAILED``, sent through ``pydispatch`` with the loader as the sender
and the request as ``request=``, for code other than the caller to hear:

.. code-block:: python

   from pydispatch import dispatcher
   from OpenGLContext.loaders.sceneloader import SCENE_LOADED

   dispatcher.connect( on_scene, signal=SCENE_LOADED, sender=self.sceneLoader )

.. _render-queue:

Calls on the render thread
~~~~~~~~~~~~~~~~~~~~~~~~~~

A worker does not call back into the program itself. When a read finishes it
queues the delivery on the context's ``renderQueue``, and the main loop makes
the queued calls on the render thread, once an iteration, **before** ``OnIdle``
and before anything is drawn. Callbacks and signals therefore run where GL is
current, and what they build is what that frame's idle hook and draw see.

The queue also holds the frame's own work: ``renderQueue.on_frame(function,
first=False)`` has ``function()`` called once an iteration **after** ``OnIdle``
and before the draw, which is where the context runs its physics, audio,
animations and following cameras (:ref:`eventmodel-frame-order`).
``remove_on_frame(function)`` stops it. ``first=True`` puts a function ahead of
those already added, as input that moves the world goes ahead of it.

The queue is for any background work, not only loading:

.. code-block:: python

   def OnInit( self ):
       threading.Thread( target=self.fetchScores ).start()

   def fetchScores( self ):                  # on a worker
       scores = download( ... )
       self.renderQueue.call( self.showScores, scores )

   def showScores( self, scores ):           # on the render thread
       self.table.rows = scores

``call( function, *arguments, **named )`` is safe from any thread, wakes the
loop so an idle window makes the call promptly, and calls are made in the order
they were queued. A call that queues another has that one made on the next
iteration. A call that is not ready returns ``renderqueue.DEFER`` and is made
again on the next. A call that raises propagates out of the loop iteration; the
calls after it stay queued. A program that drives its own loop calls
``context.runRenderQueue()`` once an iteration, then its own idle work, then
``context.runFrameHooks()`` before it draws, and a program with no context
builds ``SceneLoader()``, waits with ``request.wait( timeout )`` and calls
``poll()``.

A bounded run (``OPENGLCONTEXT_AUTO_EXIT_FRAMES``, a capture) does not count a
frame while a request is pending, or while a load on the loader pool -- an
``Inline``, a texture a node's url names -- is under way, and its clock stands
still, so a script that loads in ``OnInit`` is captured with its scene and
what it names mounted. ``context.loadsPending()`` answers whether it is still
waiting, for a program that has to wait for its scenes in the same way. The
wait lasts 30 seconds at most from the first frame
(``OPENGLCONTEXT_LOAD_WAIT``), so a scene that keeps loading, streamed tiles
say, is captured all the same; ``context.loadWait.waited`` says the limit was
reached (``OpenGLContext.events.loadwait``).

Releasing a context's window closes its loader: pending requests are cancelled
and ``load()`` and ``submit()`` raise ``RuntimeError``.

A session recorded with :doc:`telemetry <telemetry>` has each delivery marked,
and a replay delivers each scene on the frame it was delivered on in the
recording. ``loader.sceneWaitSeconds`` (30) is how long a replay waits for a read
the recording had finished.

Formats
~~~~~~~

A format is a *reader*, a ``SceneReader`` (``OpenGLContext.loaders.readers``)
registered under ``OpenGLContext.plugins.Adapter`` against the suffixes and
content types it handles. The engine registers glTF, X3D, VRML97, OBJ and 3D Tiles;
a game registers its own, as twig-bb registers ``.bsp`` and ``.pk3``:

.. code-block:: python

   from OpenGLContext.loaders.readers import SceneReader
   from OpenGLContext.plugins import Adapter

   class LevelReader( SceneReader ):
       name = 'level'
       def configure( self, options ):       # options= from load()
           self.settings = options
       def read( self, source ):             # on a worker: no GL
           return build_level( source, self.settings )

   Adapter( 'level', 'mygame.levels.LevelReader', ['.lvl'] )

   self.sceneLoader.load( 'maps/one.lvl', options=settings, on_loaded=self.play )

A reader that can be read from bytes sets ``accepts_content = True`` and
implements ``read_content( data, name )``. ``nodes( native )`` returns the
scenegraph nodes a result is drawn as when an ``Inline`` mounts it: a scene's
children by default, and the model's ``group`` for glTF. A format a viewer can show is a
``SceneAdapter``, :ref:`described with the viewer <adapters>`.

.. _x3d-worlds:

X3D worlds
----------

An X3D document loads through the same ``Loader``, in any of its encodings:
XML (``.x3d``), ClassicVRML (``.x3dv``), JSON (``.x3dj``, or ``.json`` when
its top-level key is ``"X3D"``) and the compressed binary encoding
(``.x3db``), each also gzip-compressed (``.x3dz``, ``.x3dvz``,
``.x3db.gz``):

.. code-block:: python

   from OpenGLContext.loaders.loader import Loader

   scene = Loader.load( 'world.x3d' )
   self.sg = scene
   for problem in scene.problems:              # what the read found wrong
       print( problem )

``vrml.x3d`` reads the document. Each node is built from the engine's class
for it where the engine implements that X3D node, and from the X3D
declaration where it does not; ``OpenGLContext.loaders.x3d.prototypes()`` is
the map. A node with only its declaration keeps its fields and is not drawn,
and its type is listed once among the scene's ``problems`` at ``info``
severity. The scene is an ``X3DScene``: a ``sceneGraph`` that also holds the
document's ``profile``, ``version``, ``components``, ``units`` and ``meta``.

A document with errors in it loads as far as it reads; each problem is in
``scene.problems`` and is logged at its severity. A document in no X3D
encoding raises ``ValueError``. ``Script`` nodes are read and kept and never
run. pyvrml97's ``vrml.x3d`` documentation covers reading and writing X3D
without the engine.

An ``Inline`` in an X3D or VRML97 world reads any format a registered reader
opens, chosen as the scene loader chooses: another X3D or VRML97 world, an OBJ
model, or a glTF model, which is drawn without its animations. Its ``url`` is
resolved against the inlining document and held to the same directory or
origin. X3D's ``load`` field false leaves the Inline empty until it is set
true. A ``url`` leading back to the inlining document, or to one it is itself
inlined into, is not read, and a warning names the chain of documents.

VRML97 worlds
-------------

``Loader`` (``OpenGLContext.loaders.loader``) chooses a handler by the file's
suffix, reads the file, decompresses it if it is gzipped, parses it and
returns the root of the scenegraph:

.. code-block:: python

   from OpenGLContext.loaders.loader import Loader

   scenegraph = Loader.load( 'world.wrl' )
   self.sg = scenegraph                        # or mount scenegraph.children
   door = scenegraph.getDEF( 'Front-Door' )    # a node by its DEF name

``url`` is a path, a URL, or a list of URLs to try in turn. With
``baseURL=`` given, relative URLs are resolved against it.
``Loader.loads( data, baseURL )`` parses bytes already in memory.

A VRML97 world is read by the same reader as an X3D document in the
ClassicVRML encoding (``vrml.x3d``, whose grammar is built on `SimpleParse
<https://github.com/mcfletch/simpleparse>`__), with VRML97's field names and
defaults. A world that is not well formed loads as far as it reads: what was
wrong, with its line and column, is in the scene's ``problems`` and in the
log. A file that cannot be read raises ``IOError``. The resources a world names (image textures, ``Inline``
scenes, shader sources and HDR panoramas) are fetched afterwards, on the
background pool described :ref:`below <background-loading>`, and a failure
there is logged rather than raised.

:doc:`Loading VRML97 <vrml97>` lists the supported nodes and describes working
with the scenegraph a world becomes: finding and naming nodes, field types,
prototypes and routes. :doc:`tutorials/core_context/using_vrml97` is a complete program.

glTF and GLB models
-------------------

``load_gltf()`` reads a ``.gltf`` or ``.glb`` file, and ``load_gltf_url()``
reads one from a URL, keeping the document's URL so that a multi-file
``.gltf`` finds its ``.bin`` and texture files:

.. code-block:: python

   from OpenGLContext.loaders import gltf

   scene = gltf.load_gltf( 'model.glb' )       # or gltf.load_gltf_url( url )
   self.sg.children.append( scene.group )
   centre, radius = scene.center, scene.radius  # for placing the camera

The ``GLTFScene`` also carries the model's bounds, its cameras and its
animations. The meshes are ``PBRMesh`` nodes, drawn by the :doc:`PBR renderer
<pbr>` in the core profile. :ref:`Loading from Python <gltf-python>` describes
every attribute of the scene and how to load one model many times from a
single parse; :doc:`Loading glTF <gltf>` covers the extensions the loader
reads. :doc:`tutorials/core_context/loading_gltf_model` is a complete program.

.. _loading-obj:

Wavefront OBJ models
--------------------

An OBJ file loads through the same ``Loader`` as VRML97:

.. code-block:: python

   from OpenGLContext.loaders.loader import Loader

   model = Loader.load( 'house.obj' )              # or house.obj.gz
   self.sg.children.append( Transform( scale=(0.01, 0.01, 0.01),
                                       children=list( model.children ) ) )

The scene holds one ``Transform`` for each object or group, in file order. Each
holds a ``Shape`` for every material and kind of primitive the part uses, with a
``PBRMesh`` as its geometry and a ``PhysicalMaterial`` in its appearance, so the
:doc:`PBR renderer <pbr>` draws an OBJ as it draws a glTF model. Faces are
drawn from both sides, since an OBJ does not say which way its triangles face.
``model.getDEF( 'Chimney' )`` finds the part named ``Chimney``. A file with no
geometry loads as an empty scene.

``OpenGLContext.loaders.objfile`` reads the geometry, ``mtlfile`` the material
libraries and ``objmaterials`` turns materials into nodes. The first two
import neither the scenegraph nor GL, and return NumPy arrays and plain
records:

.. code-block:: python

   from OpenGLContext.loaders.objfile import parse_obj

   model = parse_obj( open( 'house.obj', 'rb' ).read(), 'house.obj' )
   for part in model.parts:
       for mesh in part.meshes:
           print( part.name, mesh.material, mesh.kind, len( mesh.indices ) )

Geometry
~~~~~~~~

The reader takes:

- ``v`` with three numbers. A fourth (the weight) is ignored; three more
  (``v x y z r g b``, as scanners write them) are the vertex colour, scaled by
  255 where any of them exceeds 1. ``vt`` takes its first two numbers and
  ``vn`` three.
- ``f`` with each corner form (``1``, ``1/2``, ``1//3``, ``1/2/3``). Indices are
  counted from 1, or from the end with a negative number (``-1`` is the last
  vertex read before the face), and may name an element defined later in the
  file. Corners that name the same position, texture coordinate and normal
  share a vertex.
- ``l`` and ``p``, as line segments and points.
- ``o`` and ``g``, which begin a part. A part is named by its ``o`` name, its
  ``g`` name, or both joined by ``_`` (``House_Wall``); words of a name are
  joined by ``_`` as well. Returning to a name continues its part, and ``g
  default`` is the unnamed group.
- ``usemtl`` and ``mtllib``, the materials. Runs of faces of one material in
  one part are one mesh.
- ``s``, the smoothing groups.

A face of more than three corners is cut into triangles that cover the polygon
exactly: convex polygons as fans, a quad with a reflex corner along its inner
diagonal, and any other concave polygon by ear clipping in the plane of its
outline.

A face with no ``vn`` is flat shaded, as the format says, unless a smoothing
group (``s 1``) names the faces that share vertex normals; ``s off`` and
``s 0`` end the group. Each face adds its normal to its corners weighted by the
angle it makes there, so a polygon cut into many triangles weighs as one face.
Faces of one plane share their vertices.

The reader does not read free-form curves and surfaces (``curv``, ``surf`` and
the statements that describe them) or ``vp``. A load logs one warning counting
the free-form statements, and the other statements it read past at debug level.
A statement that cannot be read, a coordinate that is not finite, or an index
outside what the file defines raises ``ValueError`` naming the file and the
line.

Materials
~~~~~~~~~

Each ``usemtl`` name is looked up in the libraries the file's ``mtllib`` lines
name; a later library wins a name. A library is found beside the model, then by
its file name alone where the name is a path from another machine. A library
that cannot be found is logged, and a ``usemtl`` name no library defines draws
in a light grey ``PhysicalMaterial`` (base colour 0.8, roughness 0.6), or white
under vertex colours. A model's undefined names are logged in one warning that
gives their count and the first six. A library that is malformed raises
``ValueError``.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - MTL
     - ``PhysicalMaterial``
   * - ``Kd``, ``map_Kd``
     - The base colour. A diffuse map replaces ``Kd`` (the colour is white
       under it), as Blender reads it.
   * - ``Pr``; else ``Ns``
     - Roughness. ``Ns`` gives ``1 - sqrt(Ns / 1000)``, to 0 at 1000; a
       material that states neither is half rough.
   * - ``Pm``
     - Metalness, 0 where absent.
   * - ``map_Pr``, ``map_Pm``, ``map_Ns``
     - One metallic-roughness texture, roughness in green and metalness in
       blue. ``map_Ns`` is read as gloss, so roughness is ``1 - sqrt(value)``.
       A factor (``Pr``, ``Pm``) multiplies its map.
   * - ``Ks``, ``illum``
     - The strength of the specular highlight: twice the mean of ``Ks`` to a
       limit of 1, so the usual ``Ks 0.5`` is the full dielectric highlight.
       ``illum 0`` and ``illum 1`` have none.
   * - ``d``, ``Tr``, ``map_d``
     - Opacity. A ``d`` below 1 blends. A ``map_d`` is merged into the
       alpha of the diffuse map (its alpha channel where ``-imfchan`` names
       none and the picture has one, otherwise its luminance). A mask whose
       texels are clear or opaque with only an antialiased edge between is a
       cutout and draws masked at 0.5; any other mask blends. A material
       with no opacity map that is wholly transparent (``d 0`` or ``Tr 1``)
       is drawn opaque and logged.
   * - ``norm``, ``map_Bump``, ``bump``
     - The normal map. A picture that averages to the violet of a tangent-space
       normal map (blue above 0.7, red and green within 0.12 of 0.5) is used as
       one, whichever statement named it. Any other picture under ``map_Bump``
       or ``bump`` is a height map and is converted, tiling at its edges, with
       a slope of 4 per unit height step per texel. ``-bm`` is the strength of
       either.
   * - ``Ke``, ``map_Ke``
     - Emission. An emission map replaces ``Ke``.
   * - ``Ni``
     - Index of refraction, where above 1. An ``Ni`` of 1 is what exporters
       write for "unset" and is left at the default 1.5.
   * - ``Pc``, ``Pcr``, ``map_Pc``, ``map_Pcr``
     - Clearcoat and its roughness.
   * - ``Ps``, ``aniso``, ``anisor``
     - Sheen, anisotropy strength, and anisotropy rotation (a turn is 1).
   * - ``-s``, ``-o``
     - A texture transform: scale, then offset, in the texture's own
       coordinates. Maps with equal values share one transform.
   * - ``-clamp on``
     - The texture does not repeat.

``Ka``, ``map_Ka``, ``refl``, ``disp`` and ``decal`` are read and not used: the
scene's lights and environment light the surface. A texture is looked for
beside its library, then beside the model, by the name written, with ``\`` read
as ``/``, with each part of the name matched to the directory's own spelling of
its case, and by its file name alone. Nothing outside the model's directory is
read. A texture that cannot be found or decoded is logged and its property keeps
the colour or factor the material gives it.

OBJ records no unit, lights, cameras or animation, so the scale of the result is
whatever the author modelled in, and a scene built around it supplies its own
lights. :doc:`tutorials/core_context/using_obj` is a complete program.

The tests are ``tests/unit/test_obj_parse.py``, ``test_mtl_parse.py``,
``test_obj_images.py``, ``test_obj_materials.py``, ``test_obj_scene.py`` and
``test_obj_render.py``. ``test_obj_corpus.py`` reads the files in
``tests/unit/obj_corpus/`` (dialects of Blender, Maya, 3ds Max, MeshLab and
ZBrush) against the triangle counts, areas and bounds stated in the corpus
manifest, and reads damaged copies of each file. ``test_obj_trimesh.py``
compares the corpus and random polygon meshes with trimesh's reader.

.. _loading-meshfiles:

STL, PLY and OFF models
-----------------------

Each of these files holds one mesh, and loads through the same ``Loader``:

.. code-block:: python

   from OpenGLContext.loaders.loader import Loader

   bracket = Loader.load( 'bracket.stl' )      # or .ply, .off, and .gz of each

The scene holds one ``Shape`` with a ``PBRMesh`` in a light grey
``PhysicalMaterial`` (base colour 0.8, roughness 0.6), or white where the file
gives vertex colours. ``OpenGLContext.loaders.meshfiles`` reads them:

- STL, ASCII or binary. Each facet keeps its own corners and normal, so the
  model is drawn faceted; a facet stored with a zero normal has one worked out
  from its corners. A binary file is recognised by its size, so one whose
  header happens to begin with ``solid`` still reads.
- PLY, ASCII or binary of either byte order: positions, normals, colours
  (``red``, ``green``, ``blue``, ``alpha``) and texture coordinates (``s``/``t``,
  ``u``/``v`` or ``texture_u``/``texture_v``) of the ``vertex`` element, and the
  ``face`` element's ``vertex_indices``. A file with no faces is drawn as
  points. A PLY of 3D Gaussian splats (vertices carrying ``f_dc_*``,
  ``f_rest_*``, ``opacity``, ``scale_*`` and ``rot_*``, as splat trainers write
  them) loads as a ``GaussianSplats`` node, drawn as
  :ref:`x3d-gaussian-splats` describes.
- OFF, with the ``ST``, ``C`` and ``N`` prefixes, and a colour on any face; the
  ``OFF`` keyword may be left out. ``4OFF``, ``nOFF`` and binary OFF are not
  read.

A model without normals is given smooth ones. Polygons are cut into triangle
fans from their first corner, which suits the convex polygons these formats
hold. None of the three records a unit, so the result is in whatever unit the
file was modelled in. A file that does not hold what its header declares
raises ``ValueError`` naming the file and the problem.

A gzip-compressed document of any of the formats on this page, named with a
``z`` or a ``.gz`` suffix, is decompressed on reading, up to the same size
limit a document is held to before decompression.

Streamed 3D Tiles
-----------------

A 3D Tiles dataset is larger than memory, so it is not loaded once. A
``TilesTerrain`` node is mounted in the scene and told where the camera is
each frame; it loads the tiles that view needs on background threads and
unloads the ones it no longer needs:

.. code-block:: python

   from OpenGLContext.scenegraph.tilesterrain import TilesTerrain

   terrain = TilesTerrain( 'world/tileset.json', max_sse=16.0,
                           memory_budget=512 * 1024 * 1024 )
   self.sg.children.append( terrain )

   # each frame, before the render pass runs:
   terrain.update_for_camera( eye_xyz, viewport_height,
                              view_projection=view_projection_matrix )

The source is a path or an ``http(s)://`` URL; remote tiles are cached on
disk (``cache_dir=``). ``max_sse`` is the screen-space error, in pixels, a
tile may show before a finer one is fetched, and ``memory_budget`` is the
resident tile memory in bytes. Pass ``physics=context.physics`` to add each
loaded tile to that physics service as a static body. Call ``terrain.shutdown()`` when you are done with it, to
stop its worker threads, and ``terrain.dispose()`` with the context it was
drawn in current, to delete the GL objects of its ground, trees and ground
cover where the context goes on drawing another world.
``instancedgl.dispose_subtree(node)`` does the same for any subtree of
terrain, vegetation or particle nodes. :doc:`Streamed 3D Tiles <tiles3d>` covers the rest:
generating a world, tuning detail and memory, and what the loader supports.

.. _background-loading:

Loading without stopping the frame
----------------------------------

Setting the ``url`` of an ``ImageTexture``, an ``Inline``, a ``GLSLShader`` or
an ``HDRBackground`` returns immediately. The fetch, decode and parse run on
the thread pool in ``OpenGLContext.loaders.background``. The pool has
``background.WORKERS`` daemon threads (four), started as work arrives, so a
scene that names several hundred textures uses four threads. A load that
raises an exception is logged with its url, and the worker continues with the
next load. That includes ``SystemExit`` or ``KeyboardInterrupt`` raised by a
load's own code, since ending the worker would only stop the loads queued
behind it; a worker that stops some other way is replaced by the next load
submitted.

To wait until the scene is complete, for example in a test or a tool, call
``wait_for_idle``:

.. code-block:: python

   from OpenGLContext.loaders import background

   texture = ImageTexture(url=['brick.png'])
   background.wait_for_idle(20)        # True once every load has finished
   print(background.pending())         # how many are still going

``wait_for_idle`` returns ``False`` if the timeout expires first. It also waits
for work submitted while it is waiting, such as the files a scene's first file
names. A fetch that stalls holds its worker until the resolver's timeout, 30
seconds for each connection or read. For loads that should not queue behind
the scenegraph's, such as remote content that may be slow, create a separate
``background.LoadPool`` and call its ``shutdown()`` when you are done with it.
The engine's own pool lasts as long as the process.

The loaders above run on the thread that calls them. To load a whole model
without stopping the frame, use :ref:`the scene loader <scene-loader>`.

.. rst-class:: technical

When a load is submitted with a ``prepare`` callable, ``prepare`` runs **on the
submitting thread**. Each url field uses it to import the modules its load
needs: PIL's per-format plugins, the loader, the format handlers and the
lighting probe. The first import of a module holds CPython's import lock. A
thread waiting for that lock does not respond to ``SIGTERM``,
``KeyboardInterrupt`` or a test runner's timeout. Running first-use imports on
the submitting thread keeps them interruptible, and raises any
``ImportError`` where the caller can handle it. Pass a ``prepare`` callable to
``background.load_in_background`` for your own loads for the same reason.

A load whose work submits more loads runs on a worker when it does so, so it
prepares those loads in its own ``prepare`` with ``background.prepare(...)``:
an ``Inline`` prepares the texture, shader and panorama loads its scene's nodes
will make. A preparation first reached on a worker thread still runs, and is
logged as a warning naming the load.

Adding a format
---------------

``Loader`` finds its handlers in the plugin registry, by suffix and content
type. A handler for another format is registered the same way the built-in
ones are:

.. code-block:: python

   from OpenGLContext.plugins import Loader

   Loader( 'stl', 'mypackage.stl.defaultHandler', ['.stl', 'model/stl'] )

The dotted path names a function that returns the handler, a subclass of
``OpenGLContext.loaders.base.BaseHandler`` whose ``parse( data, baseURL,
...)`` returns ``(True, scenegraph)``. For ``oglc-view`` to open the format as well, register
a viewer adapter for it; see :ref:`Adding a format <adapters>` on the viewer
page.
