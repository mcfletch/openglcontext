OpenGLContext Documentation
===========================

.. rst-class:: introduction

This document collects :doc:`OpenGLContext <index>`-specific documentation.
 The main `PyOpenGL documentation collection
<https://github.com/mcfletch/pyopengl>`__ includes links to both PyOpenGL and
OpenGL documentation which will be of use to the OpenGLContext programmer as
well.

.. gallery:: conformance

.. rst-class:: technical

These are Khronos glTF sample models drawn by the PBR pass. Each is a render
the :doc:`regression suite <testing>` compares against, so what is on this
page is what the engine is held to. :doc:`Loading glTF <gltf>` covers the
format and what of it is supported; :doc:`physically based rendering <pbr>`
covers the material model these exercise. Every model is credited in
`ATTRIBUTION.md
<https://github.com/mcfletch/openglcontext/blob/main/docs/images/ATTRIBUTION.md>`__.

.. _installation:

Installation
------------

OpenGLContext needs Python 3.10 or newer. Install it and its core dependencies
(NumPy, PyOpenGL, Pillow, PyVRML97, TTFQuery, SimpleParse, PyDispatcher,
pygltflib, omi_audio and omi_physics) from PyPI:

.. code-block:: bash

   pip install OpenGLContext

Optional extras pull in the pieces you need for particular features:

- ``OpenGLContext[glfw]`` -- the GLFW backend (recommended for core-profile and
  PBR rendering)

- ``OpenGLContext[draco]`` -- Draco-compressed glTF geometry (pulls in DracoPy).
  The :doc:`glTF loader <gltf>` itself is core, so the :doc:`oglc-view <viewer>`
  viewer reads ``.gltf``/``.glb`` out of the base install

- ``OpenGLContext[audio]`` -- the playback backend that reaches a sound card.
  :doc:`Audio <audio>` is core and mixes without it; this is what makes it
  audible

- ``OpenGLContext[video]`` -- :doc:`recording what the engine draws <recording>`
  to an H.264 file, using the video encoder in the graphics driver

- ``OpenGLContext[pygame]``, ``OpenGLContext[wx]`` -- the PyGame and wxPython
  backends

- ``OpenGLContext[all]`` -- every backend, plus Draco and audio playback

Using ``uv``
~~~~~~~~~~~~

`uv <https://docs.astral.sh/uv/>`__ resolves and installs the whole dependency
set (including SimpleParse, PyVRML97 and TTFQuery) from PyPI. In a checkout:

.. code-block:: bash

   uv venv
   uv pip install -e ".[glfw,gltf]"

or, to run a script without managing a virtual environment yourself:

.. code-block:: bash

   uv run --with "OpenGLContext[glfw,gltf]" oglc-view model.glb

Console commands
~~~~~~~~~~~~~~~~

Installing the package puts these on your path:

``oglc-view``
   The viewer — open and walk around a glTF, VRML97, OBJ or 3D Tiles scene. The
   format is chosen from the source, so one command opens all four. See :doc:`The
   viewer <viewer>`.
``oglc-terrain``
   Generate and walk a streamed terrain world: rolling hills, a river canyon, a
   lake and snow-capped mountains, with gravity, collision against the surface
   you can see, distance-LOD conifers and a translucent water surface. Takes a
   real heightmap with ``--dem``, or an existing 3D Tiles tileset. See
   :doc:`Streamed 3D Tiles <tiles3d>`.
``oglc-gltf-demo``
   Browse the Khronos glTF sample models — a gallery of the conformance roster,
   each shown by its own picture, over the same viewer. See :ref:`Sample Gallery
   <gallery>`.
``oglc-gltf-regression``
   Render every glTF demo and diff it against a verified baseline, for checking
   that a rendering change moved only what it meant to.
``oglc-ui-demo``
   The overlay UI, demonstrated: the settings screen, the key-binding editor, the
   console and a skin. See :doc:`The overlay UI <overlayui>`.
``oglc-character-sheet``
   Every clip a rigged character plays, as one picture — a row per view and a
   column per moment of the cycle, with an overview sheet and an ``index.html``
   over the set. A bad silhouette, a foot through the floor or an arm through the
   ribs shows up at a glance where scrubbing a viewer finds one at a time. Drawn
   through the ordinary PBR pass, so the sheet shows what a game gets. See
   :doc:`Rigged characters <characters>`.
``oglc-test``
   Run a context's automated tests — the test runner behind the visual-regression
   suite.
``oglc-deb``
   Build a Debian package for an application on the engine: the application and
   the Python that runs it, under ``/opt``, with nothing for the machine to
   install. See :doc:`Packaging an application <packaging>`.
``oglc-lorentz``
   A Lorentz attractor drawn as a ten-thousand-point line set. A small standing
   demonstration of animated line geometry.

.. rst-class:: technical

``oglc-gltf``, ``oglc-vrml`` and ``oglc-tiles`` are deprecated aliases for
``oglc-view``, kept for one release cycle; each prints a notice and forwards.
Use ``oglc-view`` in anything new.

OpenGLContext-Specific Documentation
------------------------------------

Start with the **Rendering** documents if you want to understand how a frame
is drawn, **Supporting Features** for the systems that run beside the renderer
— how the player moves, what the world does, what it sounds like — and
**Content** for loading and displaying models and worlds. The NeHe tutorial
translations are a good starting point for beginning OpenGL programmers.

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

- :doc:`Tutorials <tutorials/index>` -- Documentation for users unfamiliar with
  OpenGL

  - **NeHe** translations

  - **Introduction to Shaders**

  - Special Effects

- Rendering

  - :doc:`Flat Rendering <flat>` -- The current client-side "flat" rendering pass
    used for both profiles

  - :doc:`Core-Profile Rendering <renderpasses>` -- The shader-based core-profile
    pass, its shader programs and passes

  - :doc:`Physically Based Rendering <pbr>` -- The PBR metallic/roughness pass,
    materials and image-based lighting

  - :doc:`The PBR Uber-Shader <ubershader>` -- Line-by-line walkthrough of the
    fragment shader: textures, uniforms and lobes

  - :doc:`GLSL in OpenGLContext <glslversions>` -- What the engine supplies a
    shader, and how to move one between GLSL 1.20 and the 330 the engine ships

  - :doc:`Shadows <shadows>` -- Dynamic shadow mapping shared by the core lighting
    and PBR passes

  - :doc:`Instanced Geometry <instancing>` -- Collapsing many copies of one shape
    into a single draw call: how grouping, per-instance data, picking, caching and
    cluster culling work

  - :doc:`Levels of detail <lod>` -- Drawing a model at the detail its size on
    screen is worth: how a level is chosen, how copies at one level collapse into
    a single draw, authoring a chain in Blender, and the bust-gallery demo

  - :doc:`Overlay UI <overlayui>` -- Panels drawn over a live frame and driven by
    the pointer: a settings screen generated from the ContextDefinition's fields,
    key rebinding, dialogs, a scrolling licence notice, a console, and nine-slice
    skinning. The whole interface scales with the window, so it stays readable and
    hittable at 4K -- plus the ``oglc-ui-demo`` demo

  - :doc:`HUD & Developer Overlay <hud>` -- Screen furniture drawn over a live
    world and never taking an event: a reticule that belongs to the weapon, meters
    that colour themselves from thresholds, an icon-and-number readout and a
    fading message queue -- plus the developer overlay, fed by registered
    providers, where the frame rate is now drawn

  - :doc:`Session Telemetry <telemetry>` -- Recording a whole session to one file
    -- every input, every frame time, every exception with its traceback, and the
    application's own description of itself -- then reading it back with ``python
    -m OpenGLContext.telemetry`` or **replaying** it, so a failure somebody else
    met runs again here

  - :doc:`Recording Video <recording>` -- Writing the frames a context draws to an
    H.264 file, straight from the framebuffer to the GPU's video encoder, on a
    clock that counts frames

  - :doc:`Packaging an Application <packaging>` -- Handing somebody a game with no
    Python to install: freezing a bundle with PyInstaller, which the engine's own
    hooks make work, and building a Debian package that carries its own
    interpreter under ``/opt`` with ``oglc-deb``

  - :doc:`Swept Geometry <extrusions>` -- Lathes, spirals, screws, tubes and
    VRML97's ``Extrusion``, generated as vertex arrays and drawn in a core
    profile: join styles and miter limits, spline paths sampled to a curvature
    tolerance, rotation-minimizing frames and closed loops

  - :doc:`Tessellation <tessellation>` -- The constrained
    Delaunay tessellator: winding rules, refinement by minimum angle or maximum
    area, and what it makes of an outline that crosses itself, has holes, or
    meets itself at a T-junction

  - :doc:`NURBS Surfaces & Curves <nurbs>` -- Surfaces, trimmed surfaces and
    curves from control nets and knot vectors, evaluated to indexed triangle
    meshes with no GL involved: rational weights, per-control-point colour,
    trimming loops triangulated to the sampling rate, and a coarser tessellation
    for a surface far from the camera

  - :doc:`Particle Systems <particles>` -- Fire, smoke, sparks, explosions and
    trails as camera-facing quads in one instanced draw: the emitter node and
    its fields, six presets, bursting at a point, and how the numpy pool, the
    step and the renderer work

  - :doc:`Terrain & Landscapes <terrain>` -- Which of the two paths a landscape
    wants, and the one that needs no streaming: a :ref:`height field
    <terrain-heightfield>` drawn as one splat-textured mesh, the control map
    deciding which ground material shows where, chunked colliders a car drives on,
    and the mix-in that walks it

  - :doc:`Loading Tiles3D (Streamed) <tiles3d>` -- A world too big to load, as an octree of
    glTF tiles: screen-space-error LOD, frustum-culled paging under a memory
    budget, per-tile walkable colliders, procedural & DEM heightmaps, caves and
    overhangs, and the ``oglc-terrain`` viewer -- plus what a third-party
    ``tileset.json`` is allowed to reach (support is :ref:`experimental
    <tiles3d>`)

  - :doc:`Content Packs <contentpacks>` -- Data an application fetches rather than
    ships: the registry it declares its levels, worlds and art in, consent and
    progress for a download the frame loop must not block on, digests, the base
    pack a first run needs before its menu, thumbnails so a chooser can show
    third-party content *before* downloading it, and ``OPENGLCONTEXT_CONTENT`` for
    a packaged, offline or CI run

  - :doc:`A city from OpenStreetMap <osmcity>` -- Building footprints extruded to
    a 3D Tiles dataset and streamed: the vector tiles the generator reads, laying
    the output out so its URIs resolve, giving it ground to stand on, and walking
    the result

  - :doc:`Vegetation <vegetation>` -- A quarter of a million trees as a table and
    an instanced set chosen against the view, ground cover scattered on a
    world-anchored grid rather than stored, the canopy shade everything standing
    on the ground reads, and where a plant meets that ground

  - :doc:`Baking a World <baking>` -- Writing glTF from the scenegraph, and
    turning an authored world -- terrain, scattered vegetation, placed meshes --
    into a streamable 3D Tiles octree

  - :doc:`Roads <roads>` -- A centreline and a cross-section profile swept into a
    drivable surface, with a wet/dry tarmac material, and how a baked road carries
    its centreline to the game that streams it

  - :doc:`Water <water>` -- Lakes, rivers and choppy weather from one wave field
    taken from world position and time, moved on the card by the vertex shader,
    with glints as a river's level of detail -- and water as a medium you are
    inside, closing the view in and muffling the mix

  - :doc:`Building an Editor <editing>` -- Tool modes that get the pointer before
    the camera does, the point on the world under the cursor, dragging against a
    plane, a tri-axis handle that holds a drag to one axis, and an orthographic
    plan view to draw on

- Supporting Features

  - :doc:`Movement Modes & Navigation <navigation>` -- Walking, flying, swimming
    and mouse-look as declared nodes: sampled input, key bindings a settings
    screen can rewrite, world-imposed modes and pointer capture

  - :doc:`Navigation Mesh <navmesh>` -- Where a character can walk, worked out
    from the collision mesh at load time rather than baked beside the level:
    walkable cells by slope, a corridor found by A\* across them, and the route
    pulled taut through the portals so it is the line a person would take

  - :doc:`Physics & Collision <physics>` -- Real-time rigid-body physics built on
    the OMI glTF model: collision, gravity zones, triggers, joints, shape cooking,
    a character controller with safe viewpoint binding, a motion debug overlay,
    and :ref:`walking <walking>` as a capability of every interactive context

  - :doc:`Spatial Audio <audio>` -- Sound placed in the scene on glTF's
    ``KHR_audio_emitter`` model: distance curves, directional cones, equal-power
    panning, a fixed voice pool with priority stealing, an underwater muffle, and
    silence as a first-class backend. The engine is the standalone ``omi_audio``
    package; OpenGLContext supplies the scenegraph nodes and the per-context
    engine

- Content

  - :doc:`The viewer <viewer>` -- ``oglc-view``: one command that opens a glTF
    model, a VRML97 world, an OBJ or a streamed 3D Tiles dataset, its library of
    samples, its screens and controls, :ref:`embedding it <viewer-embedding>` as a
    component and :ref:`adding a format <adapters>`

  - :doc:`Embedding a view <embedding>` -- The engine as one widget in a Tk, Qt or
    wx application: which call puts the view in the layout, which of the two loops
    does the driving, the scenegraph as a tree beside it, following a scene that
    changes on a worker thread, and a sample program in each toolkit

  - :doc:`Loading glTF <gltf>` -- The glTF 2.0 loader: what it supports, using it
    from your own code, :ref:`driving a model by the names it was authored under
    <names>`, and the :ref:`library a package's own art loads through <assets>`

  - :doc:`Loading content you did not write <untrusted>` -- What a model, world or
    texture from somewhere else is allowed to reach: the one containment core
    every loader resolves references through, what each loader confines, and what
    is left to the application

  - :doc:`Rigged characters <characters>` -- Which joint is which bone, playing
    more than one clip at once, hanging a weapon on a hand, and
    ``oglc-character-sheet`` for looking at every clip at once

  - :doc:`Rendering Text <text>` -- The Text and FontStyle nodes, the font
    providers, and extruded solid text

  - :doc:`Loading VRML97 <vrml97>` -- Using the (partial) VRML97 loader and the
    nodes it creates

- Built with it

  - :doc:`GLinting Steel <glisteel>` -- A racing game on a world too big to load:
    which engine capability each part of it uses, what is left over that makes it
    a game, and how a picture of it is taken twice the same

  - :doc:`The GLinting Steel track editor <glisteel-editor>` -- Drawing a circuit
    on a landscape and baking a world to drive: a route as a plan rather than a
    road, sculpting the ground the road settles onto, reading relief off a map,
    and what a project holds

- :doc:`Event Model <eventmodel>` -- The event model which manages changes to
  the VRML97 scenegraph

- :doc:`Testing What You Draw <testing>` -- A hidden GL context in the test
  process, the pytest fixtures that hand one over, running the suite with no
  window at all, running a whole application in a child process, and comparing
  the pixels that came back

- :doc:`Rendering Offscreen <offscreen>` -- A GL context with no window and no
  display server: an EGL device on Linux and a pbuffer on Windows, which one a
  platform has, driving a scene with events nobody typed, and what to use
  instead where there is neither

- **Reference**

  - :doc:`Type Declarations <typing>` -- What a checker sees of the engine: the
    ``py.typed`` marker that has a project's calls into the engine checked, the
    generated stub that declares the node namespace, regenerating it after adding
    a node, and what stays ``Any``

  - :doc:`Environment Variables <environment>` -- Every switch that changes what a
    frame looks like or how it is produced, in one table: what it does, what it
    accepts, what it defaults to, and which page explains the feature behind it.
    Also how a value that is neither a yes nor a no is treated, and how to build a
    clean environment for a render that has to be reproducible

- PyDoc References (Automatically generated documentation)

  - :py:mod:`OpenGLContext <OpenGLContext>`

    - :py:mod:`OpenGLContext_qt <OpenGLContext_qt>` (PyQt4 context, a separate
      module due to licensing restrictions)

  - :py:mod:`PyVRML97 <vrml>` (module vrml)

  - :py:mod:`TTFQuery <ttfquery>` (module ttfquery)

  - :py:mod:`PyOpenGL <OpenGL>` (module OpenGL)

- :doc:`Structural Overview <structure>` -- OpenGLContext's architecture and
  implementation

- :doc:`Rendering Text <text>` -- Overview of the Text and FontStyle scenegraph
  nodes, general notes regarding support of text in OpenGLContext

- :doc:`Using NumPy Arrays <numeric_arrays>` -- Array math within OpenGLContext
  and PyOpenGL: creating arrays, the dtypes that match each GL type, slicing,
  the vector utilities, and handing an array to the driver as geometry

Sample Code (Where to Look)
---------------------------

The râison d'ętre (apologies for my rusty French) for `OpenGLContext
<https://github.com/mcfletch/openglcontext>`__ is to provide a platform for
testing and sample code, so you'll find a lot of it lurking about in the
project. In particular, in the source-code release, you can find sample code
for:

- Shader-Based Drawing

  - `Instanced Rendering Sample
    <https://github.com/mcfletch/openglcontext/blob/main/tests/shader_instanced.py>`__

  - `Shader-based Geometry Scenegraph Nodes
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/shaders.py>`__

- GLU polygon tessellation

  - `Scenegraph Node
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/polygontessellator.py>`__

  - `Usage Sample
    <https://github.com/mcfletch/openglcontext/blob/main/tests/glu_tess.py>`__

- Polygon-sorting by screen depth

  - passes sub-package, flat.py and passes.py

- `Multi-texturing
  <https://github.com/mcfletch/openglcontext/blob/main/tests/nehe6_multi.py>`__

- `Saving buffers to disk
  <https://github.com/mcfletch/openglcontext/blob/main/tests/saveimage.py>`__
  (screen capture)

- `Select render mode
  <https://github.com/mcfletch/openglcontext/blob/main/tests/selectrendermode.py>`__
  (mouse interactions)

- `Particle-systems
  <https://github.com/mcfletch/openglcontext/blob/main/tests/particles_simple.py>`__

- `Display Lists
  <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/displaylist.py>`__

- Geometry Drawing

  - `Box
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/box.py>`__

  - `Sphere, Cone and Cylinder
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/quadrics.py>`__

  - :doc:`Non-Uniform Rational B-Splines (NURBS) <nurbs>`, including surfaces and
    curves, with trimming

    - `Scenegraph Node
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/nurbs.py>`__

    - `Usage Sample
      <https://github.com/mcfletch/openglcontext/blob/main/tests/molehill.py>`__

  - Array Based Geometry

    - `Basic
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/arraygeometry.py>`__

    - `IndexedFaceSet
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/indexedfaceset.py>`__

    - `IndexPolygons
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/indexedpolygons.py>`__

    - `IndexLineSet
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/indexedlineset.py>`__

    - `Pointset
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/pointset.py>`__
      including sprite
      support`https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/pointset.py
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/pointset.py>`__

    - `GLUT Teapot
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/teapot.py>`__

    - `Gear
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/gear.py>`__

    - :doc:`Swept geometry <extrusions>` — lathes, spirals, screws, tubes and
      VRML97's ``Extrusion``, generated as vertex arrays

  - Text

    - `Solid/3D Font
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/text/toolsfont.py>`__
      Extraction with TTFQuery

    - `Pygame Bitmap Font
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/text/pygamefont.py>`__

- Scene Setup

  - `SphereBackground
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/spherebackground.py>`__
    spherical gradiant backgrounds

  - `CubeBackground
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/cubebackground.py>`__
    skybox implementation

  - `Lights
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/light.py>`__

- Material Properties

  - `Material
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/material.py>`__

  - `Appearance
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/appearance.py>`__

  - `Textures
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/texture.py>`__
    with PIL/Pillow
