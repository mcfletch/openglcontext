Core-Profile Rendering
======================

.. rst-class:: introduction

OpenGLContext renders a scenegraph in one of two ways: with GLSL shaders on an
OpenGL 3.3 core-profile context, or with the legacy fixed-function pipeline on
a compatibility-profile context. This page describes the core-profile path:
how to select it, the steps it runs each frame, the shader programs it
manages, and the rules a geometry node follows to draw through it. The
:doc:`physically based renderer <pbr>` is built on the same path.

Choosing a Profile
------------------

The default profile is ``core``. It requests an OpenGL 3.3 core-profile
context and renders through the shader-based pass. It is the only profile on
platforms without fixed-function support, such as macOS, and the only one that
draws the geometry nodes made by the glTF loader and the generators.

The ``compatibility`` profile gives the fixed-function pipeline. Use it for a
program that draws with ``glBegin``, the matrix stack, display lists,
``glMaterial``/``glLight`` or GLSL's ``gl_ModelViewProjectionMatrix``. Declare
it on the Context class, so the requirement stays with the code:

.. code-block:: python

   class MyContext( BaseContext ):
       profile = 'compatibility'

To set the profile for a whole run instead, for a CI job or a one-off
comparison, use the environment variable:

.. code-block:: bash

   OPENGLCONTEXT_PROFILE=compatibility python your_script.py

The profile is read once, before the window is created. Every backend can
create a core context. See :ref:`Saying which profile your program needs
<core-profile>` for how the class attribute, the variable and an explicit
``ContextDefinition`` combine.

.. rst-class:: technical

The dispatch is in ``passes/renderpass.py``. When the context definition has
``profile == 'core'``, the renderer creates the core ``FlatPass`` from
``passes/flatcore.py``; otherwise it creates the compatibility ``FlatPass``
from ``passes/flatcompat.py``. The choice is made once per context, not per
frame.

Compatibility and Core Compared
-------------------------------

Both profiles render through a ``FlatPass`` (see :doc:`Flat Rendering
<flat>`). The base class in ``passes/_flat.py`` holds both code paths, and the
flag ``use_shaders`` selects one. The core pass sets ``use_shaders = True``;
the compatibility pass leaves it ``False``.

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
     - node-path matrices computed on the CPU and uploaded as ``mat4`` uniforms
   * - Geometry
     - vertex pointers, display lists
     - VAOs and VBOs at fixed attribute locations
   * - Selection / picking
     - ``glColor4ubv`` back-buffer colour codes
     - object id written to a second render target (MRT), or the unlit program

.. _frame-sequence:

The Frame Sequence
------------------

On each visible frame the core ``FlatPass`` runs these steps in order:

- Views - place the context's :doc:`view layout <multiview>` in the window and
  work out each view's camera. A context that sets no layout has one view: its
  own view platform, filling the window.

- Gather - walk the scene once, choose the level of detail for all views at
  once, then cull and sort the result against each view's frustum.

- Selection - resolve mouse-pick events, either from the object-id render
  target (MRT) or with the unlit program, each through the camera of the view
  the event happened in.

- Shadow maps - when shadows are on, render each shadow-casting light's depth
  into its map, once for every view (see :doc:`Shadows <shadows>`). Shadows
  are on by default in the core profile.

- Shared opaque - when the driver allows one submission for every view (the
  ``vertex`` or ``geometry`` strategy), draw each view's background, then draw
  once, for all the views that see them, the opaque shapes that can share a
  draw. The next step draws the rest of each view. See :doc:`Several views on
  one window <multiview>`.

- Each view in turn, inside its own rectangle:

  - Background - the view's flat colour, or the scene's sky/ground gradient or
    cube background.
  - Lights - upload the light uniforms in this view's eye space, bind the
    shadow maps for this view, and set the default material and the scene
    ambient.
  - Opaque - draw non-transparent geometry, grouped by material and sorted
    front to back.
  - Transmissive - glass-like surfaces (:doc:`PBR <pbr>` only). The pass
    captures the opaque backdrop first, so the shader can sample it through the
    surface.
  - Transparent - draw blended geometry back to front for this view's camera,
    with depth writes off.

- Bloom - when bloom is on, blur the bright parts of each view within its own
  rectangle and composite the glow onto the frame.

- Overlay - draw the frame counter and any HUD elements over the whole window.
  The overlay is not written to the object-id buffer, and it is drawn after
  bloom so the interface does not glow.

- Present - hand the finished frame to the context. Screenshots and recordings
  read the frame at this point.

.. rst-class:: technical

The compatibility pass runs the matching fixed-function steps for each view:
legacy background, legacy lights, opaque, transparent.

Shader Programs
---------------

``VRML97ShaderProgram`` (in ``passes/shaderpass.py``) compiles and holds the
core-profile programs, one for each kind of geometry:

- ``program`` -- the main lit shader (``vrml97_lighting.vert/frag``), which
  implements the VRML97 Phong lighting model.

- ``unlit_program`` -- unlit drawing, selection and text (``vrml97_unlit.*``).

- ``vertex_color_program`` -- geometry with per-vertex colour, such as NURBS
  output (``vrml97_vertex_color.*``).

- ``point_program`` -- ``PointSet`` and particles with per-vertex colour
  (``vrml97_point.*``).

- ``line_program`` -- ``IndexedLineSet`` (``vrml97_line.*``).

- ``depth_program`` -- position only, for the shadow depth passes
  (``shadow_depth.*``).

Background nodes have their own small shader (``vrml97_background.*``). The
:doc:`PBR pass <pbr>` subclasses ``VRML97ShaderProgram`` and replaces only the
main lit program with its Cook-Torrance shader. It inherits the others.

.. _fixed-attribute-locations:

Fixed Attribute Locations
~~~~~~~~~~~~~~~~~~~~~~~~~

A geometry node feeds each vertex array to a fixed attribute location, and
every shader reads that array from the same location.
``OpenGLContext/scenegraph/vertexsemantics.py`` defines the locations for the
whole engine. They are keyed by glTF's vertex semantics, the names the loaders
already use:

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

A shader of your own can use location 15 and above
(``vertexsemantics.FIRST_FREE_LOCATION``) for inputs that have no name in this
table.

.. rst-class:: technical

The engine fixes locations rather than looking up names because a Vertex Array
Object records locations. A VAO built from one program's name lookups is valid
only for that program, so a mesh drawn by the lit program, the unlit program
and the shadow depth pass would need three VAOs. With fixed locations, one VAO
per geometry serves every program that follows the table. A component that owns
both its geometry and its shader, such as the overlay UI batcher, the particle
system or the vegetation layers, numbers its own inputs. It must not use one of
the names above for a different meaning.

Required and Optional Inputs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If no array feeds a shader input, GL does not raise an error. The draw goes
ahead and every vertex reads the same default value. For most inputs the
default is usable. The PBR program declares a tangent, a vertex colour, a
second UV set and skinning inputs, and reads each one only when a uniform says
the geometry supplied it. A box with a position, a normal and a texture
coordinate therefore draws correctly.

Some inputs have no usable default, and the geometry must supply them. Each
shader marks this on the input's declaration:

.. code-block:: glsl

   layout(location = 1) in vec3 aNormal;    // required: shading has no direction without it
   layout(location = 3) in vec4 aTangent;   // optional: zero disables normal mapping

The first word of the comment is the marker: ``required`` or ``optional``,
followed by what the default means. The engine reads the markers in three
places:

- ``shadersource.required_inputs(filename)`` collects the required inputs of
  one shader file.
- ``VRML97ShaderProgram.required_inputs()`` returns them for whichever program
  is bound. The depth program requires a position and nothing else.
- ``geometryarrays.report_missing_inputs`` names a geometry that does not
  supply a required input.

A missing input is reported once per program and geometry, not once per frame,
through the same log as other draw failures:

.. code-block:: text

   WARNING OpenGLContext.passes.renderfailures: Rendering finished with 1 node that could not draw:
       Sphere ?: MissingVertexInput: the shader cannot draw without aNormal, which this geometry does not supply (1 time, opaque pass)

This check covers only the shaders the engine compiles. Nothing is reported
for the GLSL of a ``Shader`` node, because the engine has no markers for it.

.. _shape-own-shader:

A Shape With Its Own Shader
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``Shader`` can take the place of ``Appearance`` on a ``Shape``. It carries a
GLSL program instead of a material and a texture:

.. code-block:: python

   Shape(
       geometry = Sphere( radius=2 ),
       appearance = Shader( objects=[ GLSLObject( shaders=[ ... ] ) ] ),
   )

The geometry feeds its arrays to the locations in the :ref:`table above
<fixed-attribute-locations>`. ``GLSLObject.compile`` binds the engine's input
names to those locations before it links the program, so a shader that
declares ``in vec3 aPosition;`` receives positions with no further setup. If
your shader uses a different name for an input, map it with a
``ShaderInput``:

.. code-block:: python

   GLSLObject(
       shaders = [ ... ],
       attributes = [
           ShaderInput( semantic='POSITION', name='vertexInput' ),
           ShaderInput( semantic='NORMAL',   name='surfaceNormal' ),
       ],
   )

These entries override the engine's names one at a time. If you rename only
the position, normals and texture coordinates still arrive under their usual
names. A ``layout(location = ...)`` qualifier in the source takes precedence
over both (GLSL 3.30 section 4.3.8.2), so a shader that states its own
locations keeps them.

The pass uploads its camera matrices to any ``GLSLObject`` that declares them:
``mat_modelproj``, ``mat_modelview``, and their inverses and transposes. A
shader that declares ``uniform mat4 mat_modelproj;`` gets the value without
uploading it. ``itp_modelview`` is the inverse transpose of the model-view
matrix; its upper-left 3×3 is the normal matrix. The pass does not touch any
other uniform in the program. In the selection pass the shape draws with the
pass's own program instead, so picking writes an id colour rather than the
output of the appearance's shader.

.. _shader-assembly:

How Shaders Are Assembled
-------------------------

Shared GLSL code is kept in include files (``_common_inc.glsl``,
``_brdf_inc.glsl``, ``_lights_inc.glsl``, ``_shadow_inc.glsl``,
``_cubemap_inc.glsl``). The preprocessor in ``shaderpass.py`` splices them in
at compile time. It does two things:

- It resolves ``#include "file.glsl"`` directives recursively from the shader
  directory. Each file is spliced at most once per program, like an include
  guard. Included files have no ``#version`` line; the top-level shader
  provides it.

- It injects compile-time ``#define`` lines directly after the ``#version``
  line. These carry per-driver limits, for example the number of
  shadow-casting lights the driver can support (``MAX_SHADOW_LIGHTS``) and
  whether cube-map arrays are available.

The lighting math therefore has one source, and the same shader compiles on
drivers with very different texture-unit budgets. See :doc:`Physically Based
Rendering <pbr>` for the BRDF include and :ref:`budget` for the shadow budget.

Drawing Through the Core Pass
-----------------------------

A geometry node checks ``mode.shader_mode``. When it is true, the node draws
with VAOs and VBOs instead of fixed-function calls:

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

The ``Shape`` node sets up the material and texture before it calls the
geometry's ``render()``, so the geometry only supplies vertex data and issues
the draw. To be drawn in batches, a geometry also provides ``instanceGPU()``
and ``instanceContentKey()``; see :doc:`Instanced Geometry <instancing>`. See
:doc:`the structural overview <structure>` for how Shape, Appearance and
geometry work together.

.. _srgb-output:

sRGB Output
-----------

The shaders write colour that is already sRGB-encoded, so the framebuffer must
not encode it again. On the first frame, with the context current, the pass
disables ``GL_FRAMEBUFFER_SRGB``. No OpenGLContext pass enables it, so it
stays off. Some backends create an sRGB-capable default framebuffer with the
setting on; without this step, colours would be encoded twice and look washed
out.

Scenegraph Observation and the Frame Gather
-------------------------------------------

This section describes how the core pass turns the scenegraph into draw
lists. You do not need it to use the renderer.

Watching the scenegraph
~~~~~~~~~~~~~~~~~~~~~~~

The flat pass does not traverse the scenegraph every frame. It observes the
graph and keeps a flat list of paths to every renderable node. The
``SGObserver`` base class (in ``passes/_flat.py``) connects to the
scenegraph's change signals (child added, child removed, Switch changed) and
builds a ``NodePath`` for each affected node. A ``NodePath`` caches the
combined transform matrix from the root to its node. Each frame then iterates
over this prepared list instead of recursing through the graph. The core pass
uses the same mechanism as :doc:`Flat Rendering <flat>`.

A path exists only as long as the route it describes. When a subtree leaves
the graph, the pass drops its paths from both of its records:

- the draw set, which it iterates each frame;
- the per-node index, which maps a change anywhere in the graph to the paths
  that run through it. This index holds a path for every integrated node,
  including nodes that draw nothing.

A stale path would keep its cached transform matrices alive, and each of those
caches stays registered for the fields it depends on. In a world that streams
content in and out, stale paths would make every change notify more receivers,
and frames would get slower the longer the session ran.

The Switch signal reports a change of child, not an assignment. Code such as
level-of-detail selection often writes ``whichChoice`` every frame. Writing the
child that is already drawn sends no signal, and the pass keeps its existing
paths instead of walking the subtree again. A node that switches its own
children should follow the same rule, so observers run only when the child
actually changes.

One walk of the scene per frame
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each frame needs three values for every renderable path: the node at its end,
its world transform, and its bounding volume. The frustum cull, the shadow
pass's caster pool and the draw all use them. Each value comes through a
scenegraph cache, and a scene has one of each per shape, so the pass reads
them once. ``gatherPaths()`` walks the scene and publishes a ``GatheredPaths``
table, and the rest of the frame reads it with ``takeGather()``.

The table is valid only for the frame that built it. ``takeGather()`` removes
the table as it returns it, so the next frame cannot read last frame's
transforms by mistake. A caller that finds no table walks the scene itself. A
depth pass run on its own through ``renderGeometry()`` is such a caller.

The table stores the world transforms in two forms:

- stacked into one ``(N,4,4)`` array, for arithmetic over the whole scene at
  once;
- as the individual matrix objects from the scenegraph's transform cache.

Code that keeps a per-object result between frames keys it on the second form.
The transform cache returns the same object while a node is unmoved and a new
one after it moves, so an identity check tells whether a stored result is
still valid. A row of the stacked array holds the same numbers but is a new
object every frame.

Render records
~~~~~~~~~~~~~~

The gather produces one record per shape that passes the frustum cull. Each
record is ``(sortKey, mvmatrix, tmatrix, bvolume, path, node)``. ``node`` is
the node at the end of ``path``. The record carries it because almost every
reader needs it: to key an instanced batch, to check whether it casts a
shadow, to sort by material, and to draw. Reading ``record[5]`` avoids a
``path[-1]`` Python call for each of those uses, which adds up to tens of
thousands of calls a frame in a scene of a few thousand objects.

A pass reads ``record[5]``, and these hooks take the node rather than a path:
``_instanceKey(node)``, ``_instanceable(node)``, the ``key`` argument of
``build_instance_groups``, ``_shapePickable(node)`` and
``applyLightGrid(shader, node, ...)``. The path stays in the record for code
that needs the route rather than its end node, such as a stable pick id or a
world transform.
