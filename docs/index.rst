OpenGLContext
=============

A 3D engine for Python, on PyOpenGL.

.. _showcase:

.. gallery:: showcase

.. rst-class:: technical

The engine rendered every picture on this site. `manifest.toml
<https://github.com/mcfletch/openglcontext/blob/main/docs/images/manifest.toml>`__
holds the recipe for each one, and ``tools/doc_images.py`` renders them again.
`ATTRIBUTION.md
<https://github.com/mcfletch/openglcontext/blob/main/docs/images/ATTRIBUTION.md>`__
credits the models and textures they show.

.. _introduction:

Introduction
------------

.. rst-class:: introduction

OpenGLContext is a 3D engine written in Python on top of `PyOpenGL
<https://github.com/mcfletch/pyopengl>`__. It opens a window through one of
several GUI toolkits and loads glTF 2.0, VRML97, OBJ and 3D Tiles content into
a scenegraph. It draws that scenegraph with a physically based renderer on the
OpenGL 3.3 core profile. Physics, spatial audio, an overlay UI and movement
modes are part of the engine, so an application supplies its world and its
game logic.

The :doc:`tutorials <tutorials/index>` show how to use it: loading a model,
animating it, physics, a character walking a route, and an interface over the
frame. PyOpenGL is tested and taught through this project, so the tutorials
and the :ref:`sample code <sample-code>` also serve as an introduction to
OpenGL for people who have not written any.

To see the engine draw the Khronos glTF sample models, run one command. `uv
<https://docs.astral.sh/uv/>`__ fetches the packages into its own cache and
installs nothing into your environment:

.. code-block:: bash

   uv run --with "OpenGLContext[gltf,glfw]>=3.0.0a4" oglc-gltf-demo

To open your own model:

.. code-block:: bash

   uv run --with "OpenGLContext[gltf,glfw]>=3.0.0a4" oglc-view model.glb

:ref:`Installation <installation>` covers a permanent install and the optional
extras: other backends, Draco-compressed glTF, audio playback and video
recording. :doc:`The viewer <viewer>` lists what ``oglc-view`` can open.

.. _features:

Features
--------

.. container:: thumb-row

   .. figure:: images/features/terrain.jpg
      :alt: A forested hillside receding into haze
      :target: terrain.html

      Terrain & vegetation

   .. figure:: images/features/water.jpg
      :alt: Three panels of water: flat, rippled and choppy, with floats riding each
      :target: water.html

      Water

   .. figure:: images/features/roads.jpg
      :alt: A marked road curving away over open ground
      :target: roads.html

      Roads

   .. figure:: images/features/navmesh.jpg
      :alt: A navigation mesh drawn over a level, with a route through it
      :target: navmesh.html

      Navigation meshes

   .. figure:: images/features/extrusions.jpg
      :alt: Swept and lathed shapes: tubes, screws and spirals
      :target: extrusions.html

      Swept geometry

   .. figure:: images/features/particles.jpg
      :alt: Fire, smoke, sparks and an explosion burning side by side in the dark
      :target: particles.html

      Particle effects

   .. figure:: images/features/nurbs.jpg
      :alt: Four coloured NURBS surfaces meeting in a mound
      :target: nurbs.html

      NURBS surfaces

   .. figure:: images/features/text.jpg
      :alt: Rendered text in a 3D scene
      :target: text.html

      Text

   .. figure:: images/features/hud.jpg
      :alt: A HUD of meters and messages over a live scene
      :target: hud.html

      HUD & overlay UI

   .. figure:: images/features/editing.jpg
      :alt: An editor view with a tri-axis handle on a selected point
      :target: editing.html

      Editing

- **Rendering**

  - :doc:`Shader pipeline <flat>` on the OpenGL 3.3 core profile, and a
    fixed-function pipeline on the compatibility profile

  - :doc:`Physically based materials <pbr>`: a metallic/roughness
    :doc:`uber-shader <ubershader>` with image-based lighting

  - :ref:`HDR backgrounds <environment-lighting>`: a Radiance ``.hdr``
    panorama drawn as the sky, tone-mapped with the scene and reflected by
    metallic surfaces

  - :doc:`Dynamic shadows <shadows>` from cascaded shadow maps, shared by the
    core lighting and PBR passes

  - :doc:`Several views of one scene <multiview>` in one window, such as the
    split and quad layouts an editor uses

  - :doc:`Levels of detail <lod>`, chosen by a model's size on screen

  - :doc:`Particle effects <particles>`: fire, smoke, sparks and explosions in
    one instanced draw

  - :doc:`Instanced geometry <instancing>`, frustum culling and a
    scenegraph-wide cache, so repeated shapes cost one draw call

  - Shader scenegraph nodes, for programs you write yourself (see
    :doc:`GLSL in OpenGLContext <glslversions>`)

- **Geometry**

  - Points and point sprites, lines, polygons and indexed face sets

  - Boxes, spheres, cylinders, cones and the Utah teapot

  - :doc:`NURBS surfaces and curves <nurbs>`: rational and trimmed, and
    tessellated more coarsely with distance from the camera

  - :doc:`Extrusions, lathes, screws, spirals and tubes <extrusions>`,
    generated as vertex arrays so they draw in either profile

  - :doc:`Tessellation <tessellation>`: a constrained Delaunay tessellator
    that turns 2D outlines, including holes, into triangles

  - :doc:`Text <text>`: TrueType fonts as 3D polygonal solids or outlines, and
    screen-space text from a built-in texture atlas

  - :doc:`glTF meshes <gltf>`: skinned, morph-target and vertex-deformed

  - :doc:`Rigged characters <characters>`: blended animation clips, weapons
    attached to a hand, and crowds

- **Worlds**

  - :doc:`Terrain <terrain>`: splat-textured height fields you can walk on,
    and :doc:`streamed 3D Tiles <tiles3d>` datasets with screen-space-error LOD
    and per-tile colliders

  - :doc:`Vegetation <vegetation>`: instanced billboards, grass clumps and
    mesh LOD close to the camera

  - :doc:`Water <water>`: lakes, rivers and choppy weather from one wave field,
    and the view from under the surface

  - :doc:`Roads <roads>`: a centreline and a cross-section swept into a
    drivable surface

  - :doc:`Baking <baking>` an authored world into a streamable 3D Tiles octree,
    and :doc:`building an editor <editing>` to author it in

  - :doc:`Content packs <contentpacks>`: levels and art an application
    downloads after it is installed

  - :doc:`GLinting Steel <glisteel>` and its :doc:`track editor
    <glisteel-editor>`, a racing game that uses all of the above

- **Simulation**

  - :doc:`Physics and collision <physics>`: rigid bodies on the OMI glTF model,
    gravity zones, triggers, joints and a character controller

  - :doc:`Navigation mesh <navmesh>` generated from the collision mesh, with
    routes pulled taut through its portals

  - :doc:`Spatial audio <audio>`: sound placed in the scene on glTF's
    ``KHR_audio_emitter`` model, mixed in NumPy

  - Timers, interpolators and the :doc:`event model <eventmodel>` that carries
    a change through the scenegraph

- **Interaction**

  - :doc:`Movement modes <navigation>`: examine, fly, walk, swim and FPS
    mouse-look, with rebindable keys

  - Selection and picking, rendered through unique-colour buffers

  - :doc:`Overlay UI <overlayui>`: panels, a generated settings screen, a
    key-binding editor and a console, scaled to the window

  - :doc:`HUD and debug overlay <hud>`: a reticule, meters and messages over
    the world, and a debug overlay showing frame rate, renderer, audio and any
    numbers the application registers

- **Loading content**

  - :doc:`glTF 2.0 and GLB <gltf>`, and the :doc:`viewer <viewer>` that opens
    them

  - :doc:`OGC 3D Tiles <tiles3d>`, streamed from an octree of glTF tiles

  - :doc:`VRML97 <vrml97>` worlds and Wavefront OBJ models

  - Quake III BSP levels and PK3 archives, through the `twig-bb
    <https://github.com/mcfletch/twig-bb>`__ project

  - Textures through Pillow, and system fonts through TTFQuery

  - :doc:`Limits on what a loaded file can reach <untrusted>`, for content from
    other sources

- **Windowing**

  - GLFW, recommended for core-profile and PBR rendering

  - GLUT, Pygame, Tk and wxPython

  - Qt 6 through PySide6, from the separate `OpenGLContext-qt
    <https://github.com/mcfletch/openglcontext-qt>`__ distribution

  - :doc:`Offscreen rendering <offscreen>` with no window: EGL on Linux and a
    WGL pbuffer on Windows

  - :doc:`A view embedded in a Tk, Qt or wx application <embedding>`

  - One keyboard, mouse and window event model across all of them

- **Shipping an application**

  - :doc:`Testing what you draw <testing>`: a hidden GL context in the test
    process, pytest fixtures that provide one, and pixel comparison against a
    baseline

  - :doc:`Session telemetry <telemetry>`: a whole session recorded to one file,
    to read back or replay

  - :doc:`Video recording <recording>`: a context's frames encoded to H.264 on
    the GPU's own encoder, supported on NVIDIA cards under Linux

  - :doc:`Packaging <packaging>`: a PyInstaller bundle, using hooks the engine
    ships, or a Debian package that carries its own interpreter

  - :ref:`Settings <overlayui-settings>`: each renderer option is a field on
    the context definition. It takes its default from an :doc:`environment
    variable <environment>`, appears on the generated settings screen, and can
    be saved and restored by the application

Documentation
-------------

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   documentation
   viewer
   tutorials/index
   structure
   backends

.. toctree::
   :maxdepth: 2
   :caption: Rendering

   flat
   renderpasses
   pbr
   ubershader
   glslversions
   shadows
   instancing
   lod
   multiview
   particles
   profiles

.. toctree::
   :maxdepth: 2
   :caption: Geometry and text

   extrusions
   tessellation
   nurbs
   text
   characters

.. toctree::
   :maxdepth: 2
   :caption: Worlds and content

   loading
   gltf
   vrml97
   tiles3d
   terrain
   vegetation
   water
   roads
   baking
   osmcity
   contentpacks
   untrusted

.. toctree::
   :maxdepth: 2
   :caption: The application around it

   navigation
   navmesh
   physics
   audio
   audio-internals
   overlayui
   hud
   eventmodel
   editing
   embedding

.. toctree::
   :maxdepth: 2
   :caption: Shipping it

   testing
   telemetry
   capturing
   recording
   packaging
   offscreen

.. toctree::
   :maxdepth: 2
   :caption: Built with it

   glisteel
   glisteel-editor

.. toctree::
   :maxdepth: 2
   :caption: Reference

   environment
   typing
   numeric_arrays
   api/index

Source and support
------------------

.. code-block:: console

   $ git clone https://github.com/mcfletch/openglcontext.git

Report bugs and request features on the `issue tracker
<https://github.com/mcfletch/openglcontext/issues>`__. OpenGLContext is
BSD-licensed. It is built on `PyOpenGL <https://github.com/mcfletch/pyopengl>`__,
`PyVRML97 <https://github.com/mcfletch/pyvrml97>`__, `TTFQuery
<https://github.com/mcfletch/ttfquery>`__, `SimpleParse
<https://github.com/mcfletch/simpleparse>`__ and `PyDispatcher
<https://github.com/mcfletch/pydispatcher>`__; :doc:`the structural overview
<structure>` lists every package underneath it.

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
