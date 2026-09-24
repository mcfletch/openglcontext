.. _structure-loaders:

Loading Content
===============

.. rst-class:: introduction

OpenGLContext reads four formats into its scenegraph: VRML97 worlds, glTF 2.0
and GLB models, Wavefront OBJ models, and streamed OGC 3D Tiles datasets. This
page shows the call that loads each from Python, what it returns, and how to
wait for the files a scene names. To open a file and look at it without
writing any code, use :doc:`oglc-view <viewer>`, which opens all four.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Format
     - Call
     - Returns
   * - VRML97 (``.wrl``, ``.wrz``, ``.vrml``, ``.wrl.gz``)
     - ``Loader.load(url)``
     - a ``sceneGraph``
   * - Wavefront OBJ (``.obj``)
     - ``Loader.load(url)``
     - a ``sceneGraph``
   * - glTF 2.0 (``.gltf``, ``.glb``)
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

The parser is built on `SimpleParse <https://github.com/mcfletch/simpleparse>`__,
which is installed with OpenGLContext. A file that is not well formed raises
``SyntaxError``, and a file that cannot be read raises ``IOError``; catch both
around the call. The resources a world names (image textures, ``Inline``
scenes, shader sources and HDR panoramas) are fetched afterwards, on the
background pool described :ref:`below <background-loading>`, and a failure
there is logged rather than raised.

:doc:`Loading VRML97 <vrml97>` lists the supported nodes and describes working
with the scenegraph a world becomes: finding and naming nodes, field types,
prototypes and routes. :doc:`tutorials/using_vrml97` is a complete program.

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
reads. :doc:`tutorials/using_gltf_model` is a complete program.

Wavefront OBJ models
--------------------

An OBJ file loads through the same ``Loader`` as VRML97:

.. code-block:: python

   from OpenGLContext.loaders.loader import Loader

   model = Loader.load( 'house.obj' )
   self.sg.children.append( Transform( scale=(0.01, 0.01, 0.01),
                                       children=list( model.children ) ) )

Each ``o`` line becomes a ``Transform`` registered under that name, so
``model.getDEF( 'Chimney' )`` finds it; faces before any ``o`` go in an
unnamed one. Each run of faces after a ``usemtl`` is a ``Shape`` holding an
``IndexedFaceSet``, drawn two-sided. The loader reads:

- ``v``, ``vn``, ``vt`` and ``f`` -- positions, normals, texture coordinates
  and faces;
- ``o`` -- named objects;
- ``mtllib`` -- the material library, found beside the ``.obj`` by the name the
  line gives;
- ``usemtl`` -- the material for the faces that follow. A name the library
  does not define is logged and drawn light grey;
- in the library, ``Kd``, ``Ka``, ``Ks``, ``Ke`` and ``Ns`` (diffuse, ambient,
  specular and emissive colour, and shininess), ``d`` (opacity) or ``Tr``
  (transparency), and ``map_Kd`` (a diffuse texture).

Smoothing groups (``s``) and groups (``g``) are ignored. OBJ records no unit,
lights, cameras or animation, so the scale of the result is whatever the
author modelled in, and a scene built around it supplies its own lights. A
model moved without its ``.mtl`` file loads with every material light grey.
:doc:`tutorials/using_obj` is a complete program.

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
resident tile memory in bytes. Pass ``physics_world=`` to make the loaded
tiles colliders. Call ``terrain.shutdown()`` when you are done with it, to
stop its worker threads. :doc:`Streamed 3D Tiles <tiles3d>` covers the rest:
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
next load.

To wait until the scene is complete, for example in a test or a tool, call
``wait_for_idle``:

.. code-block:: python

   from OpenGLContext.loaders import background

   texture = ImageTexture(url=['brick.png'])
   background.wait_for_idle(20)        # True once every load has finished
   print(background.pending())         # how many are still going

``wait_for_idle`` returns ``False`` if the timeout expires first. It also waits
for work submitted while it is waiting, such as the files a scene's first file
names. For loads that should not queue behind the scenegraph's, create a
separate ``background.LoadPool`` and call its ``shutdown()`` when you are done
with it. The engine's own pool lasts as long as the process.

The loaders above run on the thread that calls them. To load a whole model
without stopping the frame, call them from a worker, as :doc:`the viewer
<viewer>` does, and add the result to the scene on the render thread.

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
