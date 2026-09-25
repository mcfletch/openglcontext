OpenGLContext Documentation
===========================

.. rst-class:: introduction

This page covers installing :doc:`OpenGLContext <index>`, the commands it
installs, and every page of its documentation with a line on what each one
covers. For PyOpenGL itself and links to the OpenGL reference, see the
`PyOpenGL documentation <https://mcfletch.github.io/pyopengl/>`__.

.. gallery:: conformance

.. rst-class:: technical

These are Khronos glTF sample models drawn by the PBR pass. The
:doc:`regression suite <testing>` compares each render against a stored
baseline. :doc:`Loading glTF <gltf>` lists the parts of the format the loader
supports, and :doc:`physically based rendering <pbr>` describes the material
model the samples use. `ATTRIBUTION.md
<https://github.com/mcfletch/openglcontext/blob/main/docs/images/ATTRIBUTION.md>`__
credits every model.

.. _installation:

Installation
------------

OpenGLContext needs Python 3.10 or newer. Install it from PyPI:

.. code-block:: bash

   pip install OpenGLContext

This installs the core dependencies: NumPy, PyOpenGL, Pillow, PyVRML97,
TTFQuery, SimpleParse, PyDispatcher, pygltflib, opengl_extrusions, omi_audio
and omi_physics.

Optional extras add the packages for particular features:

``OpenGLContext[glfw]``
   The GLFW backend, recommended for core-profile and PBR rendering.
``OpenGLContext[pygame]``
   The Pygame backend, through ``pygame-ce``.
``OpenGLContext[draco]``
   Draco-compressed glTF geometry, through DracoPy. The :doc:`glTF loader
   <gltf>` itself is part of the core install, so :doc:`oglc-view <viewer>`
   reads ``.gltf`` and ``.glb`` files without any extra.
``OpenGLContext[audio]``
   The playback backend that sends sound to a sound card. :doc:`Audio <audio>`
   is part of the core install and mixes without it, but plays nothing.
``OpenGLContext[video]``
   :doc:`Recording what the engine draws <recording>` to an H.264 file, using
   the video encoder in the graphics driver.
``OpenGLContext[all]``
   GLFW, Pygame, Draco and audio playback together.

The wxPython backend needs ``wxPython`` installed separately. The Tk backend
needs Tcl/Tk, which some Linux distributions package apart from Python
(``apt install python3-tk``). The Qt backend is the separate
``OpenGLContext-qt`` distribution. :ref:`Which backends are supported
<backends>` has the details for each.

Using ``uv``
~~~~~~~~~~~~

`uv <https://docs.astral.sh/uv/>`__ resolves and installs the whole dependency
set from PyPI. In a checkout:

.. code-block:: bash

   uv venv
   uv pip install -e ".[glfw,gltf]"

To run a command without managing a virtual environment yourself:

.. code-block:: bash

   uv run --with "OpenGLContext[glfw,gltf]" oglc-view model.glb

.. _commands-list:

Console commands
~~~~~~~~~~~~~~~~

Installing the package puts these commands on your path:

``oglc-view``
   Opens a glTF, VRML97, OBJ or 3D Tiles scene and lets you walk around it. It
   works out the format from the source. See :doc:`The viewer <viewer>`.
``oglc-terrain``
   Generates a streamed terrain world and lets you walk it: hills, a river
   canyon, a lake and snow-capped mountains, with gravity, collision with the
   ground, distance-LOD conifers and a translucent water surface. ``--dem``
   takes a real heightmap, and it also opens an existing 3D Tiles tileset. See
   :doc:`Streamed 3D Tiles <tiles3d>`.
``oglc-gltf-demo``
   Shows a gallery of the Khronos glTF sample models, each with its own
   picture, and opens the one you choose in the viewer. See :ref:`Sample
   Gallery <gallery>`.
``oglc-gltf-regression``
   Renders every glTF demo and compares it with a verified baseline, to check
   that a rendering change affected only what it was meant to.
``oglc-ui-demo``
   Demonstrates the overlay UI: the settings screen, the key-binding editor,
   the console and a skin. See :doc:`The overlay UI <overlayui>`.
``oglc-mirrors``
   A hall of mirrors: a polished marble floor, a large wall mirror, a corridor
   of small mirrors, a pool and a window that shows only its reflection, with
   keys to switch reflections and change their budget. See
   :doc:`Reflections <reflections>`.
``oglc-audio-demo``
   Demonstrates sound: collisions, events, fading areas and a pitch that
   follows the simulation. See :ref:`Sound <audio-demos>`.
``oglc-physics-events``
   Demonstrates collision subscriptions: crates that thud at any frame rate,
   two panes of glass broken after and before the solve, a hitscan gun and a
   pressure plate that opens a door. See :ref:`Responding to collisions
   <physics-collisions>`.
``oglc-character-sheet``
   Draws every clip a rigged character plays as one picture, with a row per
   view and a column per moment of the cycle, plus an overview sheet and an
   ``index.html`` for the set. Use it to spot a foot through the floor or an
   arm through the body without scrubbing through each clip. It renders
   through the ordinary PBR pass. See :doc:`Rigged characters <characters>`.
``oglc-test``
   Runs a context's automated tests. The visual-regression suite runs through
   it.
``oglc-deb``
   Builds a Debian package for an application built on the engine. The package
   holds the application and the Python that runs it under ``/opt``, and needs
   nothing else installed. See :doc:`Packaging an application <packaging>`.
``oglc-lorentz``
   Draws a Lorentz attractor as a line set of ten thousand points, as a small
   example of animated line geometry.

.. rst-class:: technical

``oglc-gltf``, ``oglc-vrml`` and ``oglc-tiles`` are deprecated aliases for
``oglc-view``. Each prints a notice and runs ``oglc-view``. Use ``oglc-view``
in new scripts.

The documentation pages
-----------------------

The pages are grouped as in the site's navigation. If you are new to OpenGL,
start with the tutorials; the NeHe translations among them teach OpenGL
directly. To understand how a frame is drawn, read :doc:`Core-Profile
Rendering <renderpasses>` and then the other Rendering pages.

Getting started
~~~~~~~~~~~~~~~

- :doc:`The viewer <viewer>` -- ``oglc-view``: one command that opens a glTF
  model, a VRML97 world, an OBJ file or a streamed 3D Tiles dataset. Covers its
  sample library, screens and controls, :ref:`embedding it <viewer-embedding>`
  as a component, and :ref:`adding a format <adapters>`.

- :doc:`Tutorials <tutorials/index>` -- code walkthroughs, each built from a
  runnable script in ``tests/``:

  - Using the Engine: loading a glTF, VRML97 or OBJ model, animating it, clips,
    a crowd, and an NPC on a navigation mesh

  - Physics: a world, materials, joints, triggers, and responding to a
    collision

  - Interface and Tools: panels, the HUD, a settings page, a console, choosing
    a level, picking and dragging, and the editor's tool modes

  - Building a World: water, roads, particles, audio, baking and recording

  - Swept Geometry and Tessellation

  - Introduction to Shaders and the NeHe translations, for writing OpenGL
    directly

- :doc:`Structural Overview <structure>` -- the packages the engine is built
  on and the packages inside it, each with the page that describes it.

- :doc:`Windowing Backends <backends>` -- the six GUI toolkits and the two
  windowless backends, what each runs on, the window-level methods every one
  provides, filling the screen, adding a backend, and what happens when a
  context is destroyed.

Rendering
~~~~~~~~~

- :doc:`Flat Rendering <flat>` -- the "flat" render pass that draws the
  scenegraph in both profiles.

- :doc:`Core-Profile Rendering <renderpasses>` -- the shader-based
  core-profile pass, its shader programs, the fixed attribute locations, and a
  Shape that brings its own shader.

- :doc:`Physically Based Rendering <pbr>` -- the metallic/roughness pass, its
  materials and image-based lighting.

- :doc:`PBR Uber-Shader <ubershader>` -- a line-by-line walkthrough of the PBR
  fragment shader: its textures, uniforms and lobes.

- :doc:`GLSL in OpenGLContext <glslversions>` -- the inputs and uniforms the
  engine gives a shader, and how to convert a shader between GLSL 1.20 and
  GLSL 330.

- :doc:`Shadows <shadows>` -- dynamic shadow mapping, shared by the core
  lighting and PBR passes.

- :doc:`Reflections <reflections>` -- mirrors, polished floors and water that
  reflect the scene: marking a surface in code, in Blender or in a glTF, how
  the reflections are drawn as views of their own, the budget they are drawn
  within, and the ``oglc-mirrors`` demo.

- :doc:`Instanced Geometry <instancing>` -- drawing many copies of one shape in
  a single draw call: grouping, per-instance data, picking, caching and cluster
  culling.

- :doc:`Levels of detail <lod>` -- drawing a model at a detail level chosen by
  its size on screen, drawing copies at one level in a single draw, authoring a
  chain of levels in Blender, and the bust-gallery demo.

- :doc:`Several views on one window <multiview>` -- one scene seen through
  several cameras, each in its own rectangle: split and quad layouts, per-view
  backgrounds and wireframe, picking in the view that was clicked, and the
  work the views share (one scene traversal, one level-of-detail choice, one
  set of shadow maps).

- :doc:`Particle Systems <particles>` -- fire, smoke, sparks, explosions and
  trails as camera-facing quads in one instanced draw: the emitter node and its
  fields, six presets, bursts, and how the NumPy particle pool, the update step
  and the renderer work.

- :doc:`Core vs. Compatibility Contexts <profiles>` -- the two OpenGL
  profiles, which one a program gets, declaring the one it needs, and what
  each pass does differently.

Geometry and text
~~~~~~~~~~~~~~~~~

- :doc:`Swept Geometry <extrusions>` -- lathes, spirals, screws, tubes and
  VRML97's ``Extrusion``, generated as vertex arrays and drawn in a core
  profile: join styles and miter limits, spline paths sampled to a curvature
  tolerance, rotation-minimizing frames and closed loops.

- :doc:`Tessellation <tessellation>` -- the constrained Delaunay tessellator:
  winding rules, refinement by minimum angle or maximum area, and how it treats
  an outline that crosses itself, has holes, or touches itself at a
  T-junction.

- :doc:`NURBS Surfaces & Curves <nurbs>` -- surfaces, trimmed surfaces and
  curves from control nets and knot vectors, evaluated to indexed triangle
  meshes without GL: rational weights, per-control-point colour, trimming
  loops, and coarser tessellation for a surface far from the camera.

- :doc:`Rendering Text <text>` -- the Text and FontStyle nodes, the font
  providers, and extruded solid text.

- :doc:`Rigged characters <characters>` -- mapping joints to bones, playing
  several clips at once, attaching a weapon to a hand, and
  ``oglc-character-sheet`` for viewing every clip at once.

Worlds and content
~~~~~~~~~~~~~~~~~~

- :doc:`Loading Content <loading>` -- loading VRML97, glTF, OBJ and 3D Tiles
  from your own code, what each call returns, and waiting for the textures
  and inlined files a scene names.

- :doc:`Loading glTF <gltf>` -- the glTF 2.0 loader: what it supports, calling
  it from your own code, :ref:`driving a model by its authored names <names>`,
  and :ref:`loading a package's own art <assets>`.

- :doc:`Loading VRML97 <vrml97>` -- the VRML97 loader, which covers part of
  the specification, and the nodes it creates.

- :doc:`Streamed 3D Tiles <tiles3d>` -- a world too large to load at
  once, stored as an octree of glTF tiles: screen-space-error LOD,
  frustum-culled paging within a memory budget, per-tile walkable colliders,
  procedural and DEM heightmaps, caves and overhangs, the ``oglc-terrain``
  viewer, and what a third-party ``tileset.json`` is allowed to reference.
  Support is :ref:`experimental <tiles3d>`.

- :doc:`Terrain & Landscapes <terrain>` -- choosing between a height field and
  streamed tiles, and the :ref:`height field <terrain-heightfield>`: one
  splat-textured mesh, the control map that places each ground material,
  chunked colliders for vehicles, and the mix-in for walking on it.

- :doc:`Vegetation <vegetation>` -- a quarter of a million trees stored as a
  table and drawn as an instanced set chosen for the current view, ground cover
  scattered on a world-anchored grid instead of stored, canopy shade on
  everything under the trees, and how a plant meets the ground.

- :doc:`Zones <zones>` -- regions of space whose settings hold inside them:
  a room lit by an environment captured inside it, lamps that light only
  their room, ambience and reverb heard only in a place, nodes and mirrors
  shown only from inside, and gravity volumes, from code, from glTF's
  ``OGLC_zone`` and in a streamed world.

- :doc:`Zone Internals <zones-internals>` -- how zones are placed, layered
  by priority, weighted per fragment, captured into probe layers, and handed
  to the audio and physics engines.

- :doc:`Water <water>` -- lakes, rivers and choppy weather from one wave field
  computed from world position and time and applied in the vertex shader,
  glints as a river's level of detail, and the view from underwater, where the
  view closes in and sound is muffled.

- :doc:`Roads <roads>` -- a centreline and a cross-section swept into a
  drivable surface with a wet/dry tarmac material, and how a baked road passes
  its centreline to the game that streams it.

- :doc:`Baking a World <baking>` -- writing glTF from the scenegraph, and
  turning an authored world of terrain, scattered vegetation and placed meshes
  into a streamable 3D Tiles octree.

- :doc:`A city from OpenStreetMap <osmcity>` -- building footprints extruded
  into a 3D Tiles dataset: the vector tiles the generator reads, laying out the
  output so its URIs resolve, adding ground, and walking the result.

- :doc:`Content Packs <contentpacks>` -- data an application downloads instead
  of shipping: the registry of levels, worlds and art, consent and progress for
  a download that does not block the frame loop, digests, the base pack a first
  run needs, thumbnails for third-party content before it is downloaded, and
  ``OPENGLCONTEXT_CONTENT`` for packaged, offline or CI runs.

- :doc:`Loading content you did not write <untrusted>` -- what a model, world
  or texture from another source is allowed to reach: the containment every
  loader resolves references through, what each loader confines, and what is
  left to the application.

The application around it
~~~~~~~~~~~~~~~~~~~~~~~~~

- :doc:`Movement Modes & Navigation <navigation>` -- walking, flying,
  swimming and mouse-look as declared nodes: sampled input, key bindings a
  settings screen can change, modes the world imposes, and pointer capture.

- :doc:`Navigation Mesh <navmesh>` -- the walkable area of a level, generated
  from the collision mesh at load time: walkable cells by slope, an A\*
  search for a corridor across them, and the route pulled taut through the
  portals.

- :doc:`Physics & Collision <physics>` -- rigid-body physics on the OMI glTF
  model: collision, :ref:`collision callbacks <physics-collisions>`, gravity
  zones, triggers, joints, shape cooking, a character controller with
  viewpoint binding, a motion debug overlay, and :ref:`walking <walking>` in
  every interactive context. ``oglc-physics-events`` shows the callbacks.

- :doc:`Sound <audio>` -- sound placed in the scene on glTF's
  ``KHR_audio_emitter`` model: file formats, sound in glTF files, and how to
  play a sound on a collision, on an event and for an area; volume, muffling
  and running with no sound device. ``oglc-audio-demo`` shows each of them.

- :doc:`Audio Engine Internals <audio-internals>` -- how ``omi_audio`` and
  OpenGLContext's audio nodes work: the threads, the gain curves, the mixer
  and voice stealing, the clip cache and codec selection, and testing sound
  without a device.

- :doc:`Overlay UI <overlayui>` -- panels drawn over the frame and driven by
  the pointer: a settings screen generated from the ``ContextDefinition``
  fields, key rebinding, dialogs, a scrolling licence notice, a console,
  nine-slice skinning, scaling with the window up to 4K, and the
  ``oglc-ui-demo`` command.

- :doc:`HUD & Developer Overlay <hud>` -- screen elements drawn over the world
  that take no input: a reticule, meters coloured by thresholds, an
  icon-and-number readout and a fading message queue. Also the developer
  overlay, which shows the frame rate and whatever the registered providers
  report.

- :doc:`Event Model <eventmodel>` -- how changes propagate through the VRML97
  scenegraph.

- :doc:`Building an Editor <editing>` -- tool modes that receive the pointer
  before the camera does, finding the point in the world under the cursor,
  dragging against a plane, a tri-axis handle that constrains a drag to one
  axis, and an orthographic plan view to draw on.

- :doc:`Embedding a view <embedding>` -- the engine as one widget in a Tk, Qt
  or wx application: the call that puts the view in the layout, which loop
  drives the frames, the scenegraph shown as a tree, following a scene that a
  worker thread changes, and a sample program for each toolkit.

Shipping it
~~~~~~~~~~~

- :doc:`Testing What You Draw <testing>` -- a hidden GL context in the test
  process, the pytest fixtures that provide one, running the suite with no
  window, running a whole application in a child process, and comparing the
  pixels it produced.

- :doc:`Session Telemetry <telemetry>` -- recording a session to one file
  (every input, every frame time, every exception with its traceback, and the
  application's own marks) and then reading it back with ``python -m
  OpenGLContext.telemetry`` or replaying it to reproduce a failure.

- :doc:`Capturing the Render <capturing>` -- the screenshot key, writing one
  settled frame to a PNG from the viewer or your own code, and recording
  video with pyopengl-video.

- :doc:`Recording Video <recording>` -- writing a context's frames to an H.264
  file, from the framebuffer to the GPU's video encoder, on a clock that
  counts frames.

- :doc:`Packaging an Application <packaging>` -- giving someone a game with no
  Python to install: freezing a bundle with PyInstaller, using the hooks the
  engine ships, and building a Debian package that carries its own interpreter
  under ``/opt`` with ``oglc-deb``.

- :doc:`Rendering Offscreen <offscreen>` -- a GL context with no window and no
  display server: an EGL device on Linux and a pbuffer on Windows, choosing a
  device, driving a scene with synthetic events, and the alternatives where
  neither is available.

Built with it
~~~~~~~~~~~~~

- :doc:`GLinting Steel <glisteel>` -- a racing game on a streamed world: which
  engine feature each part of it uses, the game code on top, and how its
  screenshots are made reproducible.

- :doc:`The GLinting Steel track editor <glisteel-editor>` -- drawing a circuit
  on a landscape and baking a world to drive: a route planned before it becomes
  a road, sculpting the ground under the road, reading relief from a map, and
  the contents of a project.

Reference
~~~~~~~~~

- :doc:`Environment Variables <environment>` -- every variable that changes
  what a frame looks like or how it is produced, in tables giving the accepted
  values, the default, and the page that describes the feature. Also how
  invalid values are handled, and how to build a clean environment for a
  reproducible render.

- :doc:`OGLC_zone <extensions/OGLC_zone>` -- the specification of the glTF
  extension that marks a region and the extensions that apply inside it, for
  glTF 2.0 with ``KHR_implicit_shapes`` and glTF 2.1, with its JSON schema
  and examples.

- :doc:`Type Declarations <typing>` -- the ``py.typed`` marker that lets a
  type checker check a project's calls into the engine, the generated stub
  that declares the node namespace, regenerating it after adding a node, and
  what remains ``Any``.

- :doc:`Using NumPy Arrays <numeric_arrays>` -- array maths in OpenGLContext
  and PyOpenGL: creating arrays, the dtype for each GL type, slicing, the
  vector utilities, and passing an array to OpenGL as geometry.

- :doc:`API reference <api/index>` -- a generated page per module, for
  :py:mod:`OpenGLContext <OpenGLContext>`, :py:mod:`OpenGLContext_qt
  <OpenGLContext_qt>` (the Qt 6 backend, packaged separately so that Qt is not
  a dependency of the engine), :py:mod:`PyVRML97 <vrml>`, :py:mod:`TTFQuery
  <ttfquery>` and :py:mod:`PyOpenGL <OpenGL>`.

.. _sample-code:

Sample code
-----------

`OpenGLContext <https://github.com/mcfletch/openglcontext>`__ exists partly
as a platform for testing PyOpenGL and for sample code, so the source tree
holds many examples. These show particular techniques:

- Shader-based drawing

  - `Instanced rendering sample
    <https://github.com/mcfletch/openglcontext/blob/main/tests/shader_instanced.py>`__

  - `Shader-based geometry scenegraph nodes
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/shaders.py>`__

- GLU polygon tessellation

  - `Scenegraph node
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/polygontessellator.py>`__

  - `Usage sample
    <https://github.com/mcfletch/openglcontext/blob/main/tests/glu_tess.py>`__

- `Sorting transparent polygons by depth
  <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/polygonsort.py>`__

- `Multi-texturing
  <https://github.com/mcfletch/openglcontext/blob/main/tests/nehe6_multi.py>`__

- `Saving buffers to disk
  <https://github.com/mcfletch/openglcontext/blob/main/tests/saveimage.py>`__
  (screen capture)

- `Select render mode
  <https://github.com/mcfletch/openglcontext/blob/main/tests/selectrendermode.py>`__
  (mouse interaction)

- `Particle systems
  <https://github.com/mcfletch/openglcontext/blob/main/tests/particles_simple.py>`__

- `Display lists
  <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/displaylist.py>`__
  (compatibility profile)

- Geometry

  - `Box
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/box.py>`__

  - `Sphere, cone and cylinder
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/quadrics.py>`__

  - :doc:`NURBS <nurbs>` surfaces and curves, with trimming

    - `Scenegraph node
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/nurbs.py>`__

    - `Usage sample
      <https://github.com/mcfletch/openglcontext/blob/main/tests/molehill.py>`__

  - Array-based geometry

    - `ArrayGeometry
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/arraygeometry.py>`__

    - `IndexedFaceSet
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/indexedfaceset.py>`__

    - `IndexedPolygons
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/indexedpolygons.py>`__

    - `IndexedLineSet
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/indexedlineset.py>`__

    - `PointSet
      <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/pointset.py>`__,
      including point sprites

  - `Teapot
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/teapot.py>`__

  - `Gear
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/gear.py>`__

  - :doc:`Swept geometry <extrusions>`: lathes, spirals, screws, tubes and
    VRML97's ``Extrusion``, generated as vertex arrays

- Text

  - `Solid 3D fonts
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/text/toolsfont.py>`__,
    with outlines read through TTFQuery

  - `Pygame bitmap fonts
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/text/pygamefont.py>`__

- Scene setup

  - `SphereBackground
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/spherebackground.py>`__:
    spherical gradient backgrounds

  - `CubeBackground
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/cubebackground.py>`__:
    a skybox

  - `Lights
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/light.py>`__

- Materials

  - `Material
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/material.py>`__

  - `Appearance
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/scenegraph/appearance.py>`__

  - `Textures
    <https://github.com/mcfletch/openglcontext/blob/main/OpenGLContext/texture.py>`__,
    loaded with Pillow
