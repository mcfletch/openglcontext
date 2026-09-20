OpenGLContext
=============

A 3D engine for Python, on PyOpenGL.

.. _showcase:

.. gallery:: showcase

.. rst-class:: technical

Every picture on this site is a frame the engine drew. `manifest.toml
<https://github.com/mcfletch/openglcontext/blob/main/docs/images/manifest.toml>`__
holds the recipe for each one and ``tools/doc_images.py`` runs them again;
what is in them is credited in `ATTRIBUTION.md
<https://github.com/mcfletch/openglcontext/blob/main/docs/images/ATTRIBUTION.md>`__.

.. _introduction:

Introduction
------------

.. rst-class:: introduction

OpenGLContext is a 3D engine written in Python on top of `PyOpenGL
<https://github.com/mcfletch/pyopengl>`__. It opens a window on any of five
GUI toolkits, loads glTF 2.0, VRML97, OBJ and 3D Tiles content into a
scenegraph, and draws it with a physically based OpenGL 3.3 core-profile
renderer — with physics, spatial audio, an overlay UI and a movement model
beside it, so that an application is the world you author rather than the
plumbing under it. It is also the environment PyOpenGL itself is exercised and
taught in: the :doc:`tutorials <tutorials/index>` and the :doc:`sample code
<documentation>` are a way into OpenGL for people who have not written any.

One line, and a window opens on the Khronos glTF sample models with the
engine drawing them — `uv <https://docs.astral.sh/uv/>`__ fetches what it
needs and leaves nothing installed:

.. code-block:: bash

   uv run --with "OpenGLContext[gltf,glfw]>=3.0.0a4" oglc-gltf-demo

Your own model, the same way:

.. code-block:: bash

   uv run --with "OpenGLContext[gltf,glfw]>=3.0.0a4" oglc-view model.glb

The :ref:`installation notes <installation>` cover installing it properly and
the optional extras — other backends, Draco-compressed glTF, audio playback
and video recording — and the :doc:`viewer <viewer>` page covers what
``oglc-view`` can open.

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

  - :doc:`Modern shader pipeline <flat>` on the OpenGL 3.3 core profile, and a
    fixed-function pipeline on the compatibility profile

  - :doc:`Physically based materials <pbr>` — a metallic/roughness
    :doc:`uber-shader <ubershader>` with image-based lighting

  - :doc:`Dynamic shadows <shadows>` from cascaded shadow maps, shared by the core
    lighting and PBR passes

  - :doc:`Particle effects <particles>` — fire, smoke, sparks and explosions in
    one instanced draw

  - :doc:`Instanced geometry <instancing>`, frustum culling and a scenegraph-wide
    cache, so repeated shapes cost one draw call

  - Shader scenegraph nodes, for programs you write yourself

- **Geometry**

  - Points and point sprites, lines, polygons and indexed face sets

  - Boxes, spheres, cylinders, cones and the NURBS teapot

  - :doc:`NURBS surfaces and curves <nurbs>` — rational, trimmed, and tessellated
    to the distance they are seen from

  - :doc:`Extrusions, lathes, screws, spirals and tubes <extrusions>` — swept as
    vertex arrays, so they draw in either profile, and filled by a constrained
    Delaunay tessellator that also handles any outline you hand it

  - :doc:`Text <text>` — TrueType, as a screen-space texture atlas, 3-D polygonal
    solids, or 3-D outlines

  - :doc:`glTF meshes <gltf>` — skinned, morph-target and vertex-deformed

  - :doc:`Rigged characters <characters>` — clips blended together, weapons hung
    on a hand, and crowds

- **Worlds**

  - :doc:`Terrain <terrain>` — splat-textured height fields, walked, and
    :doc:`streamed 3D Tiles <tiles3d>` datasets with screen-space-error LOD and
    per-tile colliders

  - :doc:`Vegetation <vegetation>` — instanced billboards, grass clumps and
    near-mesh LOD

  - :doc:`Water <water>` — lakes, rivers and choppy weather from one wave field,
    and water as a medium you are inside

  - :doc:`Roads <roads>` — a centreline and a cross-section swept into a drivable
    surface

  - :doc:`Baking <baking>` an authored world into a streamable 3D Tiles octree,
    and :doc:`building an editor <editing>` to author it in

  - All of it at once in :doc:`GLinting Steel <glisteel>` and its :doc:`track
    editor <glisteel-editor>`

- **Simulation**

  - :doc:`Physics and collision <physics>` — rigid bodies on the OMI glTF model,
    gravity zones, triggers, joints and a character controller

  - :doc:`Navigation mesh <navmesh>` worked out from the collision mesh, with
    routes pulled taut through its portals

  - :doc:`Spatial audio <audio>` — sound placed in the scene on glTF's
    ``KHR_audio_emitter`` model, mixed in numpy

  - Timers, interpolators and the :doc:`event model <eventmodel>` that carries a
    change through the scenegraph

- **Interaction**

  - :doc:`Movement modes <navigation>` — examine, fly, walk, swim and FPS
    mouse-look, with rebindable keys

  - Selection and picking, rendered through unique-colour buffers

  - :doc:`Overlay UI <overlayui>` — panels, a generated settings screen, a
    key-binding editor and a console, scaled to the window

  - :doc:`HUD and debug overlay <hud>` — reticule, meters and messages over a live
    world, and a debug overlay of frame rate, renderer and audio, plus whatever
    numbers a subsystem or the application registers

- **Loading content**

  - :doc:`glTF 2.0 and GLB <gltf>`, with the :doc:`viewer <viewer>` that opens
    them

  - :doc:`OGC 3D Tiles <tiles3d>`, streamed from an octree of glTF tiles

  - :doc:`VRML97 <vrml97>` worlds, and Wavefront OBJ models

  - Quake III BSP levels and PK3 archives, through the `twig-bb
    <https://github.com/mcfletch/twig-bb>`__ project

  - Textures with Pillow, and system fonts through TTFQuery

- **Windowing**

  - GLFW — recommended for core-profile and PBR rendering

  - GLUT, Pygame and wxPython

  - Qt 6 via PySide through the separate `OpenGLContext-qt
    <https://github.com/mcfletch/openglcontext-qt>`__ distribution

  - One keyboard, mouse and window event model across all of them

- **Shipping an application**

  - :doc:`Testing what you draw <testing>` — a hidden GL context in the test
    process, pytest fixtures that hand one over, and pixel comparison against a
    baseline

  - :doc:`Session telemetry <telemetry>` — a whole session recorded to one file,
    read back or replayed

  - :doc:`Video recording <recording>` — the frames a context draws to H.264, on
    the GPU's own encoder, which today is an NVIDIA card on Linux

  - :doc:`Packaging <packaging>` — a PyInstaller bundle, which the engine ships
    the hooks for, or a Debian package carrying its own interpreter

  - :ref:`Settings <overlayui-settings>` — a renderer option is a field on the
    context definition, so it has an :doc:`environment variable <environment>` for
    its default, a control on a generated in-game settings screen, and a value the
    application can store and restore

Documentation
-------------

.. toctree::
   :maxdepth: 2
   :caption: Getting started

   documentation
   viewer
   tutorials/index
   structure

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
   particles

.. toctree::
   :maxdepth: 2
   :caption: Geometry and text

   extrusions
   nurbs
   text
   characters

.. toctree::
   :maxdepth: 2
   :caption: Worlds and content

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
   recording
   packaging
   offscreen
   environment
   typing
   numeric_arrays

.. toctree::
   :maxdepth: 2
   :caption: Built with it

   glisteel
   glisteel-editor

.. toctree::
   :maxdepth: 2
   :caption: Reference

   api/index

Source and support
------------------

.. code-block:: console

   $ git clone https://github.com/mcfletch/openglcontext.git

Bugs and feature requests go to the `issue tracker
<https://github.com/mcfletch/openglcontext/issues>`__.  The engine is built on
`PyOpenGL <https://github.com/mcfletch/pyopengl>`__, `PyVRML97
<https://github.com/mcfletch/pyvrml97>`__, `TTFQuery
<https://github.com/mcfletch/ttfquery>`__, `SimpleParse
<https://github.com/mcfletch/simpleparse>`__ and `PyDispatcher
<https://github.com/mcfletch/pydispatcher>`__, and is BSD-licensed.

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
