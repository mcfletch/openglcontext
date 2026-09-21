Core-Profile Rendering
======================

.. rst-class:: introduction

OpenGLContext can render the same scenegraph two ways: through the legacy
fixed-function pipeline (the compatibility profile), or through GLSL shaders
on an OpenGL 3.3 core-profile context. This document describes the
core-profile path: how it is selected, the passes it runs, the shader programs
it manages, and the conventions a geometry node must follow to draw through
it. The :doc:`physically based renderer <pbr>` is a specialization of this
same path.

Choosing a Profile
------------------

``core`` is what a context asks for when nothing says otherwise: it requests
an OpenGL 3.3 core-profile context and uses the shader-based render pass. It
is the only path that works on platforms that have dropped fixed-function
support, such as macOS, and the only one that draws the geometry nodes the
glTF loader and the generators produce.

``compatibility`` gives the fixed-function pipeline, for a program that draws
with ``glBegin``, the matrix stack, display lists, ``glMaterial``/``glLight``
or GLSL's ``gl_ModelViewProjectionMatrix``. A program that needs it declares
so on its Context class, where the requirement travels with the code:

.. code-block:: python

   class MyContext( BaseContext ):
       profile = 'compatibility'

The environment variable settles the profile for a whole run instead, which is
what a CI job or a one-off comparison wants:

.. code-block:: bash

   OPENGLCONTEXT_PROFILE=compatibility python your_script.py

Either way the profile is read once, before the window exists. See
:ref:`Saying which profile your program needs <core-profile>`. All five
backends create a core context.

.. rst-class:: technical

The dispatch lives in ``passes/renderpass.py``. When the context definition
reports ``profile == 'core'``, the renderer instantiates the core ``FlatPass``
(from ``passes/flatcore.py``); otherwise it uses the compatibility
``FlatPass`` (from ``passes/flatcompat.py``). The choice is made per context,
not per frame.

Compatibility vs. Core, side by side
------------------------------------

Both profiles run through a ``FlatPass`` (see :doc:`Flat Rendering <flat>`).
The base class in ``passes/_flat.py`` carries both code paths; the single flag
``use_shaders`` selects between them. The core pass sets ``use_shaders =
True``; the compatibility pass leaves it ``False``.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - 
     - Compatibility (``flatcompat.py``)
     - Core (``flatcore.py``)
   * - Selected by
     - ``profile = 'compatibility'``, or ``OPENGLCONTEXT_PROFILE=compatibility``
     - default
   * - Lighting
     - fixed-function ``glLight*``, ``glEnable(GL_LIGHTING)``
     - VRML97 lighting model in GLSL; light properties uploaded as uniforms
   * - Materials
     - ``glMaterial*``, ``glColorMaterial``
     - material uniforms set on the shader program
   * - Matrices
     - ``glMatrixMode`` / ``glLoadMatrixf`` / ``glPushMatrix``
     - client-side node-path matrices uploaded as ``mat4`` uniforms
   * - Geometry
     - vertex pointers, display lists
     - VAOs and VBOs at fixed attribute locations
   * - Selection / picking
     - ``glColor4ubv`` back-buffer colour codes
     - object-id written to a second render target (MRT), or the unlit program

Watching the Scenegraph
-----------------------

The flat pass does not traverse the scenegraph every frame. It observes the
graph and keeps a flat list of paths to every renderable node. The
``SGObserver`` base class (in ``passes/_flat.py``) connects to the
scenegraph's change signals -- child added, child removed, Switch changed --
and rebuilds a ``NodePath`` for each affected node. A ``NodePath`` caches the
combined transform matrix for the route from the root to that node, so
per-frame rendering is a small number of iterations over a prepared list
rather than a recursive traversal. This is the same mechanism described in
:doc:`Flat Rendering <flat>`; the core pass reuses it unchanged.

A path lives exactly as long as the route it names. When a subtree leaves the
graph its paths are invalidated and dropped from both records the pass keeps:
the draw set it iterates, and the per-node index it uses to turn a change
somewhere in the graph back into the paths running through it. That index
holds a path for every integrated node, including nodes the pass draws nothing
for, so the two are maintained together. A path left behind would keep alive
every transform matrix cached against it, and each of those caches stays
registered for the fields it depends on -- content streaming in and out of a
world would then widen the set of receivers every change has to notify, and a
frame would cost more the longer the session had run.

The Switch signal reports a *change of child*, not an assignment.
``whichChoice`` is commonly written every frame -- level-of-detail sets it
from the viewer's distance -- and an assignment naming the child already being
drawn is not a change: the signal is not sent, and a pass that hears one keeps
the path it has rather than walking the subtree again. A node that switches
its own children should follow the same rule, so that observers are woken for
changes rather than for writes.

One walk of the scene per frame
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Three questions are asked of every renderable path each frame: which node it
ends at, where that node is in the world, and what bounds it. The frustum cull
wants all three, the shadow pass's caster pool wants all three, and the draw
reads them again. None of them is free — each goes through a scenegraph cache,
and a scene has as many of them as it has shapes — so they are asked once.
``gatherPaths()`` walks the scene and publishes a ``GatheredPaths`` table;
``takeGather()`` is how the rest of the frame reads it.

It is a handoff, not a cache. The table describes the scene as it stood when
it was walked, so it may be read in the frame that built it and nowhere else —
one left lying about would answer next frame's questions with last frame's
transforms, and nothing would say so. Taking it is what makes that impossible:
the gather publishes one, whoever needs it takes it, and a caller that finds
none walks the scene itself. A depth pass driven on its own through
``renderGeometry()`` is such a caller.

The table holds the world transforms twice: stacked into one ``(N,4,4)`` array
for the arithmetic the whole scene goes through at once, and as the individual
objects the scenegraph's transform cache handed over. The second form is what
anything remembering a per-object answer between frames keys on — that cache
returns the same object while a node is unmoved and a fresh one once it moves,
so identity alone says whether a remembered answer still stands. A row of the
stacked array carries the same numbers but is a new object every frame.

What a render record holds
~~~~~~~~~~~~~~~~~~~~~~~~~~

The gather's output is a list of records, one per shape that survived the
frustum, each ``(sortKey, mvmatrix, tmatrix, bvolume, path, node)``. The last
of those is the node at the end of ``path``, and it is carried rather than
looked up because almost everything that reads a record wants it — to key an
instanced batch on, to ask whether it casts a shadow, to sort its material, to
draw it. ``path[-1]`` is a Python call, and a frame of a few thousand objects
was making tens of thousands of them to reach a node the gather already had in
hand.

So a pass reads ``record[5]``, and the hooks that used to be handed a path are
handed the node instead: ``_instanceKey(node)``, ``_instanceable(node)``, the
``key`` argument of ``build_instance_groups``, ``_shapePickable(node)`` and
``applyLightGrid(shader, node, ...)``. The path stays in the record for the
things that genuinely want the route rather than its end — a stable pick id, a
world transform.

The Passes
----------

On each visible frame the core ``FlatPass`` runs these steps in order:

- **Shadow maps** -- if shadows are enabled, render each shadow-casting light's
  depth into its map first (see :doc:`Shadows <shadows>`). On by default in core
  profile.

- **Background** -- sky/ground gradient or cube background.

- **Lights** -- upload the scene's light uniforms, bind shadow samplers, and set
  the default material and scene ambient.

- **Opaque** -- draw non-transparent geometry, grouped by material and sorted
  front-to-back.

- **Transmissive** -- glass-like surfaces (:doc:`PBR <pbr>` only); the opaque
  backdrop is captured first so it can be sampled through the surface.

- **Transparent** -- draw blended geometry back-to-front with depth writes
  disabled.

- **Selection** -- resolve mouse-pick events, either from the object-id render
  target (MRT) or with the unlit program.

- **Overlay** -- the frame counter and any HUD elements, drawn to the screen
  rather than into the object-id buffer.

.. rst-class:: technical

The compatibility pass runs the analogous fixed-function sequence: legacy
background, legacy lights, opaque, transparent.

sRGB Output
-----------

The shaders write colour that is already sRGB-encoded, so the framebuffer must
not encode it a second time. On the first frame (with the context current) the
pass disables ``GL_FRAMEBUFFER_SRGB`` once and leaves it off. It is a one-time
call: nothing in OpenGLContext ever enables it, and some backends hand the
application an sRGB-capable default framebuffer that would otherwise
double-encode and wash the frame out.

Shader Programs
---------------

Core-profile rendering is managed by ``VRML97ShaderProgram`` (in
``passes/shaderpass.py``), which compiles and owns a small family of programs,
each for a different kind of geometry:

- ``program`` -- the main lit shader (``vrml97_lighting.vert/frag``),
  implementing the VRML97 Phong lighting model.

- ``unlit_program`` -- unlit drawing, selection and text (``vrml97_unlit.*``).

- ``vertex_color_program`` -- per-vertex coloured geometry such as NURBS output
  (``vrml97_vertex_color.*``).

- ``point_program`` -- ``PointSet`` / particles with per-vertex colour
  (``vrml97_point.*``).

- ``line_program`` -- ``IndexedLineSet`` (``vrml97_line.*``).

- ``depth_program`` -- position-only, used for the shadow depth passes
  (``shadow_depth.*``).

Background nodes carry their own small shader (``vrml97_background.*``). The
:doc:`PBR pass <pbr>` subclasses ``VRML97ShaderProgram`` and replaces only the
main lit program with its Cook-Torrance shader, inheriting the rest.

Fixed Attribute Locations
~~~~~~~~~~~~~~~~~~~~~~~~~

A geometry node and a shader program meet at an attribute location number, and
``OpenGLContext/scenegraph/vertexsemantics.py`` is where that number is
decided for the whole engine. The keys are glTF's vertex semantics, the
vocabulary the loaders already speak:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Location
     - Semantic
     - Shader name
   * - 0
     - ``TEXCOORD_0``
     - ``aTexCoord`` (vec2)
   * - 1
     - ``NORMAL``
     - ``aNormal`` (vec3)
   * - 2
     - ``POSITION``
     - ``aPosition`` (vec3)
   * - 3
     - ``TANGENT``
     - ``aTangent`` (vec4, w = handedness)
   * - 4
     - ``COLOR_0``
     - ``aColor`` (vec4)
   * - 5–10, 14
     - —
     - reserved for the :doc:`per-instance inputs <instancing>`
   * - 11
     - ``TEXCOORD_1``
     - ``aTexCoord1`` (vec2)
   * - 12, 13
     - ``JOINTS_0``, ``WEIGHTS_0``
     - ``aJoints``, ``aWeights`` (vec4 each, skinning)

A shader of your own may put an input the engine has no name for at
location 15 or above (``vertexsemantics.FIRST_FREE_LOCATION``).

Which of those arrays a program has to have
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

An input nothing feeds is not a GL error: the draw goes ahead and every vertex
reads the same default value. Most of those defaults mean something. The PBR
program declares a tangent, a vertex colour, a second UV set and a skin, and
reads each only where a uniform says the geometry brought it, so a box
carrying a position, a normal and a texture coordinate draws correctly. The
inputs whose default means nothing are the ones a geometry must supply, and
each shader says which of its inputs those are at the declaration:

.. code-block:: python

   layout(location = 1) in vec3 aNormal;    // required: shading has no direction without it
   layout(location = 3) in vec4 aTangent;   // optional: zero disables normal mapping

The first word of the declaration's own comment is the marker; ``required`` is
the one that is read, and every other input carries ``optional`` and what its
default means. ``shadersource.required_inputs(filename)`` collects them, a
shader program answers for whichever of its programs is bound
(``VRML97ShaderProgram.required_inputs()`` — the depth pass asks for a
position and nothing else), and ``geometryarrays.report_missing_inputs`` names
a geometry that cannot feed one. It is said once per program and geometry
rather than once a frame, and goes out through the same log as everything else
that could not draw:

.. code-block:: bash

   WARNING OpenGLContext.passes.renderfailures: Rendering finished with 1 node that could not draw:
       Sphere ?: MissingVertexInput: the shader cannot draw without aNormal, which this geometry does not supply (1 time, opaque pass)

An appearance's own GLSL is outside this. What a program can be drawn without
is a fact about its source, and the engine has that only for the shaders it
compiled, so nothing is reported against a ``Shader`` node's program.

A Shape whose appearance brings its own shader
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Shader`` is a programmable substitute for ``Appearance``: it carries a GLSL
program instead of a material and a texture.

.. code-block:: python

   Shape(
       geometry = Sphere( radius=2 ),
       appearance = Shader( objects=[ GLSLObject( shaders=[ ... ] ) ] ),
   )

The geometry and the program are written by different people, so something has
to say which vertex array feeds which input, and that something is the table
above. ``GLSLObject.compile`` binds the engine’s own attribute names to those
locations before it links, so a shader that declares ``in vec3 aPosition;``
receives positions with nothing else said. A shader that calls an input
something else says so with a ``ShaderInput``:

.. code-block:: python

   GLSLObject(
       shaders = [ ... ],
       attributes = [
           ShaderInput( semantic='POSITION', name='vertexInput' ),
           ShaderInput( semantic='NORMAL',   name='surfaceNormal' ),
       ],
   )

Entries apply *over* the engine’s own names, so renaming only the position
still leaves normals and texture coordinates arriving by their usual names. A
``layout(location = ...)`` qualifier in the source outranks both (GLSL 3.30
4.3.8.2), so a shader that states its own locations keeps them.

The pass supplies its camera to any ``GLSLObject`` that names one of its
matrices — ``mat_modelproj``, ``mat_modelview``, their inverses and transposes
— so a shader declaring ``uniform mat4 mat_modelproj;`` gets one with nothing
to upload; ``itp_modelview`` is the inverse-transpose model-view, whose
upper-left 3×3 is the normal matrix. Everything else in the program is the
shader author’s own, and the pass leaves it alone. During the selection pass
the shape draws with the pass’s own program instead, so picking paints an id
colour rather than whatever the appearance’s shader would.

.. rst-class:: technical

Locations rather than names, because a Vertex Array Object records locations.
A VAO built by looking each name up in one program is valid only for that
program, so a mesh drawn by the lit program, the unlit program and the shadow
depth pass would need three of them; with the locations fixed, one VAO per
geometry serves every program that follows the table. A program that owns both
its geometry and its shader — the overlay UI batcher, the particle system, the
vegetation layers — is outside the agreement and numbers its own inputs, but
it must not spell one of the names above and mean something else by it.

How Shaders Are Assembled
-------------------------

The shaders are not monolithic files. Common code lives in include files
(``_common_inc.glsl``, ``_brdf_inc.glsl``, ``_lights_inc.glsl``,
``_shadow_inc.glsl``, ``_cubemap_inc.glsl``) that are spliced in at compile
time. The preprocessing in ``shaderpass.py`` does two things:

- ``#include "file.glsl"`` directives are resolved recursively from the shader
  directory, each file spliced at most once per program (an include guard).
  Included files carry no ``#version`` of their own; the top-level shader owns
  it.

- Compile-time ``#define``\ s are injected immediately after the ``#version``
  line. This is how per-driver limits are baked in -- for example the number of
  shadow-casting lights the driver can support (``MAX_SHADOW_LIGHTS``) and
  whether cube-map arrays are available.

Assembling shaders this way keeps a single source of truth for the lighting
math and lets the same shader compile correctly across drivers with very
different texture-unit budgets. See :doc:`Physically Based Rendering <pbr>`
for the BRDF include and the shadow budget in detail.

Drawing Through the Core Pass (for geometry nodes)
--------------------------------------------------

A geometry node checks ``mode.shader_mode`` and, when true, draws with
VAOs/VBOs instead of fixed-function calls:

.. code-block:: python

   def render(self, mode=None, **kwargs):
       if getattr(mode, 'shader_mode', False):
           return self._render_shader(mode)
       # ... legacy fixed-function path ...

   def _render_shader(self, mode):
       program = mode.shader_program
       program.use(lit=True)                 # or use_point(), use(lit=False), ...
       program.set_matrices(mode.matrix, mode.projection)
       # bind a VAO with attributes at the fixed locations above, then:
       glDrawArrays(GL_TRIANGLES, 0, count)

The ``Shape`` node sets up material and texture before calling the geometry's
``render()``, so the geometry only has to supply vertex data and issue the
draw. See :doc:`the structural overview <structure>` for how Shape, Appearance
and geometry interact.
