OpenGLContext Structural Overview
=================================

.. rst-class:: introduction

OpenGLContext is a retained-mode scenegraph engine for games and other 3D
applications. It is built from a number of open source packages, most of them
maintained alongside it. The demos and games at the top of the diagram keep
their reusable code in the engine, so each one is a small application on top
of it. Parts that are useful outside OpenGLContext, such as ``omi_audio``,
``omi_physics``, ``opengl_extrusions`` and ``pyopengl-video``, are separate
packages.

.. mermaid::

   block-beta
       columns 8

       glisteel["GLinting Steel"]:2
       twig["Twitchy GLitchy Bang Bang"]:3
       forest["OpenGLContext Forest Demo"]:3

       editor["OpenGLContext-editor"]:5
       space:3

       oglc["OpenGLContext"]:8

       video["pyopengl-video"]:1
       space:7

       pyopengl["PyOpenGL"]:1
       omip["omi_physics"]:1
       omia["omi_audio"]:1
       ext["opengl_extrusions"]:1
       ttf["TTFQuery"]:1
       vrml["PyVRML97"]:2
       gltflib["pygltflib"]:1

       space:2
       mini["miniaudio"]:1
       space:1
       fonttools["fontTools"]:1
       simple["SimpleParse"]:1
       dispatch["PyDispatcher"]:1
       space:1

       numpy["numpy"]:7
       space:1

       classDef ours fill:#dbe7ff,stroke:#5a7ab5,color:#111
       classDef third fill:#ededed,stroke:#999999,color:#111

       class glisteel,twig,forest,editor,oglc,video,pyopengl,vrml,omip,omia,ext,ttf,simple,dispatch ours
       class mini,fonttools,gltflib,numpy third

.. mermaid::

   block-beta
       columns 2
       legendfirst["Blue: first-party packages"]
       legendthird["Grey: third-party packages"]

       classDef ours fill:#dbe7ff,stroke:#5a7ab5,color:#111
       classDef third fill:#ededed,stroke:#999999,color:#111

       class legendfirst ours
       class legendthird third

The packages it is built on
---------------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Package
     - What it provides
   * - `PyOpenGL <https://mcfletch.github.io/pyopengl/>`__
     - The OpenGL bindings: every entry point of GL, GLU, GLUT, EGL, WGL and
       GLX, the extensions, and the array handling that passes Python data to
       the driver.
   * - `pyopengl-video <https://github.com/mcfletch/pyopengl-video>`__
     - Encodes the colour buffer to H.264 on the GPU's own encoder, without
       copying the frame off the card. An extra: ``OpenGLContext[video]``.
   * - `PyVRML97 <https://github.com/mcfletch/pyvrml97>`__
     - The node, field, route and prototype model the scenegraph is built
       from, and the VRML97 parser that fills it.
   * - `pygltflib <https://gitlab.com/dodgyville/pygltflib>`__
     - Reads and writes glTF 2.0 and GLB, as the typed records the
       specification describes.
   * - `omi_physics <https://github.com/mcfletch/omi_physics>`__
     - Rigid bodies, colliders, joints and gravity zones on the OMI glTF
       physics model, computed in NumPy.
   * - `omi_audio <https://github.com/mcfletch/omi_audio>`__
     - Spatial audio on glTF's ``KHR_audio_emitter`` model: the gain curves,
       the voice pool and the block mixing, in NumPy.
   * - `opengl_extrusions <https://github.com/mcfletch/opengl_extrusions>`__
     - Sweeping, lathing and tubing, and the constrained Delaunay
       tessellator that fills an outline with triangles.
   * - `TTFQuery <https://github.com/mcfletch/ttfquery>`__
     - Finds the fonts installed on the machine and reads their glyph
       outlines.
   * - `SimpleParse <https://mcfletch.github.io/simpleparse/>`__
     - The parser generator the VRML97 grammar is written in.
   * - `PyDispatcher <https://github.com/mcfletch/pydispatcher>`__
     - Signal dispatch. Field changes are sent through it, so code can observe
       changes to the scenegraph.
   * - `fontTools <https://github.com/fonttools/fonttools>`__
     - Reads the tables of a TrueType or OpenType file, for TTFQuery.
   * - `miniaudio <https://github.com/irmen/pyminiaudio>`__
     - Decodes audio files and plays sound through the sound card. An extra:
       ``omi_audio[playback]``. Without it the mixer runs but plays nothing.
   * - `numpy <https://numpy.org/>`__
     - The arrays all of the above compute with, and the memory passed to the
       driver.

The packages inside OpenGLContext
---------------------------------

.. mermaid::

   block-beta
       columns 8

       bin["bin"]:2
       viewer["viewer"]:3
       demos["demos"]:3

       ui["ui"]:2
       edit["edit"]:1
       multiview["multiview"]:1
       testing["testing"]:1
       telemetry["telemetry"]:1
       debug["debug"]:1
       packaging["packaging · __pyinstaller"]:1

       passes["passes"]:2
       physics["physics"]:1
       nav["nav"]:1
       character["character"]:1
       move["move"]:1
       audio["audio"]:1
       video["video"]:1

       scenegraph["scenegraph"]:3
       loaders["loaders"]:2
       shaders["shaders · resources"]:2
       contentpacks["contentpacks"]:1

       context["context"]:3
       events["events"]:2
       resources["contextresources"]:3

Each layer uses the layers below it. At the bottom are the window and its
events. Above them is the scenegraph, which the render passes draw and the
simulation packages update.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Package
     - What it does
     - Described in
   * - ``bin``
     - The console commands: ``oglc-view``, ``oglc-terrain``,
       ``oglc-gltf-demo`` and the rest.
     - :ref:`Console commands <commands-list>`
   * - ``viewer``
     - The embeddable viewer the commands are built on, and the per-format
       adapters it selects between.
     - :doc:`The viewer <viewer>`
   * - ``demos``
     - A GL view inside a Tk or wx application, for a tool with an interface
       around the scene.
     - :doc:`Embedding <embedding>`
   * - ``ui``
     - The overlay: panels, widgets, a generated settings screen, the
       key-binding editor, the console and the in-world HUD.
     - :doc:`Overlay UI <overlayui>`, :doc:`HUD <hud>`
   * - ``edit``
     - The editor toolkit: tool modes, plan and orbit views, the tri-axis
       handle, and a NURBS node's control points.
     - :doc:`Editing <editing>`
   * - ``multiview``
     - Several views of one scene in one window: the views and their layout,
       orthographic cameras, the scene's own cameras as views, the gestures
       that move each, and the quad arrangement.
     - :doc:`Several views <multiview>`
   * - ``testing``
     - The machinery a test suite imports: a hidden GL context, the pytest
       fixtures that provide one, capture and comparison.
     - :doc:`Testing what you draw <testing>`
   * - ``telemetry``
     - Records a whole session (input, frame times, exceptions, marks) to one
       file, to read back or replay.
     - :doc:`Session telemetry <telemetry>`
   * - ``debug``
     - Developer aids: buffer dumps, GL state, leak counts.
     - —
   * - ``packaging``, ``__pyinstaller``
     - Shipping an application: a PyInstaller bundle, or a Debian package
       carrying its own interpreter; ``__pyinstaller`` holds the hooks
       PyInstaller finds by entry point.
     - :doc:`Packaging <packaging>`
   * - ``passes``
     - The render passes: the flat core and compatibility passes, the PBR
       uber-shader, shadows, image-based lighting, planar reflections, zones,
       level of detail and instancing.
     - :doc:`Core-Profile Rendering <renderpasses>`, :doc:`Core vs.
       Compatibility Contexts <profiles>`, :doc:`PBR <pbr>`,
       :doc:`Shadows <shadows>`, :doc:`Reflections <reflections>`,
       :doc:`Zones <zones>`, :doc:`Level of detail <lod>`,
       :doc:`Instancing <instancing>`
   * - ``physics``
     - Rigid bodies, colliders, gravity zones, triggers and the character
       controller, on ``omi_physics``.
     - :doc:`Physics <physics>`
   * - ``nav``
     - The navigation mesh generated from the collision mesh, and routes
       pulled taut through its portals.
     - :doc:`Navigation meshes <navmesh>`
   * - ``character``
     - Rigged characters: the rig, the clips, the mixer, attachments and
       crowds.
     - :doc:`Rigged characters <characters>`
   * - ``move``
     - The camera and the movement modes (examine, fly, walk, swim and
       mouse-look), and the walking model under them.
     - :doc:`Movement <navigation>`
   * - ``audio``
     - The scenegraph's audio nodes and the per-context engine that plays
       them, on ``omi_audio``.
     - :doc:`Spatial audio <audio>`
   * - ``video``
     - H.264 capture of what a context drew, through ``pyopengl-video``.
     - :doc:`Capturing the Render <capturing>`, :doc:`Recording <recording>`
   * - ``scenegraph``
     - Every node type: shapes, materials, lights, text, NURBS, extrusions,
       terrain, water, roads, vegetation, procedural surfaces, zones,
       particles and the PBR mesh.
     - :doc:`VRML97 nodes <vrml97>`, :doc:`PBR materials <pbr>`,
       :doc:`Text <text>`, :doc:`NURBS <nurbs>`, :doc:`Extrusions <extrusions>`,
       :doc:`Terrain <terrain>`, :doc:`Water <water>`, :doc:`Roads <roads>`,
       :doc:`Vegetation <vegetation>`, :doc:`Surfaces <surfaces>`,
       :doc:`Zones <zones>`, :doc:`Particles <particles>`
   * - ``loaders``
     - File formats into the scenegraph: glTF and GLB, VRML97, OBJ and
       streamed 3D Tiles.
     - :doc:`Loading Content <loading>`
   * - ``shaders``, ``resources``
     - The GLSL sources the passes compile, and the icons, font atlases and
       shader text stored as generated modules.
     - :doc:`GLSL in OpenGLContext <glslversions>`
   * - ``contentpacks``
     - Data an application downloads instead of shipping: the registry, the
       store, safe extraction and the polled download.
     - :doc:`Content packs <contentpacks>`
   * - ``context``
     - The window, the main loop, the profile and the context definition,
       with one module per backend.
     - :doc:`Windowing Backends <backends>`
   * - ``events``
     - One keyboard, mouse and window event model across the backends, and
       the dispatch that carries a change through the scenegraph.
     - :doc:`Event Model <eventmodel>`
   * - ``contextresources``
     - The caches that release a GL context's objects when the context is
       destroyed.
     - :ref:`When a context goes away <context-resources>`
