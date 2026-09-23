Shadows
=======

.. rst-class:: introduction

OpenGLContext draws dynamic shadows in the core profile. The :doc:`VRML97 core
lighting shader <renderpasses>` and the :doc:`PBR renderer <pbr>` share the
same shadow system, so shadows look the same with either. This page explains
how the shadows are made, how to turn them on and off, how each light type is
shadowed, and what causes and fixes common artefacts.

.. figure:: images/shadow_demo.jpg
   :alt: A red sphere, a green NURBS hill and a blue box casting coloured shadows onto a floor, with a wall rising behind

   The core-profile shadow system in ``tests/shadow_demo.py``: three coloured
   lights cast shadows from moving objects onto the floor and wall. Where an
   object blocks one light, its shadow is tinted by the other two.

How Shadow Mapping Works
------------------------

A surface is in shadow when something blocks the light from reaching it.
OpenGLContext finds these surfaces with *shadow mapping*. Before drawing the
scene from the camera, it draws the scene once from each light's point of view
and keeps only the distance to the nearest surface in each direction. That
depth image is the light's **shadow map**.

.. figure:: images/diagrams/shadows-1.svg
   :alt: The camera and the light each view the scene; a point is in shadow when the light's nearest-depth record shows something closer than that point.
   :class: diagram

   The camera and the light both view the scene. To shade point Q, the
   renderer looks up the nearest depth the light recorded in Q's direction. The
   occluder is nearer, so Q is in shadow. Nothing lies between P and the
   light, so P is lit.

When the scene is drawn from the camera, each lit point is tested: the point
is transformed into the light's view, the stored depth for that direction is
read, and the two are compared. If the stored surface is closer to the light
than the point, the point is in shadow.

The depth pass uses a position-only shader and writes no colour. It still
draws the scene geometry once per shadow-casting light, in addition to the
camera view, so shadow cost grows with the number of shadow-casting lights and
the amount of geometry.

Turning Shadows On and Off
--------------------------

Shadows are on by default in the core profile. These environment variables
control them:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Effect
   * - ``OPENGLCONTEXT_SHADOWS``
     - shadows on or off (default on; ``0``, ``false`` or ``off`` turns them
       off)
   * - ``OPENGLCONTEXT_SHADOWS_SOFT=1``
     - contact-hardening (PCSS) soft shadows for spot lights (default off)
   * - ``OPENGLCONTEXT_SHADOW_CASCADES=n``
     - fix the number of cascades for directional lights; the default, 0,
       adapts it to the frame rate

Each variable sets the default of a ``ContextDefinition`` field
(``shadows``, ``shadowsSoft``, ``shadowCascades``), which a settings screen
can change while the program runs. See :doc:`environment` and
:ref:`overlayui-settings`.

A light casts shadows when its ``castShadows`` field is set. It is set by
default on all three light types. Clear it on a light that should light the
scene without casting shadows. A glTF ``KHR_lights_punctual`` light uses the
extension's ``castShadows`` value where the file gives one; otherwise only a
directional light casts shadows.

.. _optout:

Geometry That Does Not Cast
---------------------------

Clear ``castsShadow`` on a ``Shape`` to leave it out of every shadow map. The
shape still renders, is still lit, and still receives shadows from other
objects. It does not cast a shadow of its own.

.. code-block:: python

   shape = Shape( geometry = ..., appearance = ..., castsShadow = False )

Clear it for these kinds of geometry:

- A shell around a scene lit from outside - for example a hall under a sun.
  If the roof casts, it shadows everything inside, and the hall is lit only by
  the ambient term: evenly, with no shadows to show where the light comes
  from. Clear the flag on the floor, walls and ceiling so the light reaches the
  room. Objects inside the room still cast shadows.
- Dense alpha-tested foliage - drawing a field of grass into every cascade
  costs more than its shadow adds; see :doc:`Vegetation <vegetation>`.
- Geometry that stands in for something absent - a sky drawn as a backdrop, a
  marker, a gizmo.

The flag is on the shape, not on the geometry, because one geometry can be
shared by a shape that casts and a shape that does not. In a glTF file, set it
with :ref:`OGLC_castsShadow <castsshadow>` in a node's ``extras``.

One Technique per Light Type
----------------------------

The three light types cover space differently, so each uses a different kind
of shadow map. The renderer chooses the technique; you do not set it.

Directional light (a sun): cascaded shadow maps
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A sun lights the whole visible scene with parallel rays. One shadow map over
that whole area would spread its texels thinly, and shadows near the camera,
where detail is most visible, would be blocky. Cascaded shadow maps (CSM)
split the camera's view into a few depth slices and give each slice its own
shadow map. The near slice covers a small area at full resolution, so nearby
shadows are sharp. Farther slices cover more ground at lower detail.

.. figure:: images/diagrams/shadows-3.svg
   :alt: The camera view is split into near, mid and far slices; each slice is covered by its own equal-resolution shadow map, so the near slice gets the finest detail.
   :class: diagram

   Cascaded shadow maps give each depth slice of the view a full map, so the
   most resolution is spent close to the camera.

By default the number of slices adapts to the frame rate. Set
``OPENGLCONTEXT_SHADOW_CASCADES`` to fix it when you need identical output on
every run (see :ref:`shadows-reproducible`).

With :doc:`several views <multiview>` in one window, the slices are fitted to
the active view's camera, and every view reads the same maps. In another
view, each point uses the finest cascade that contains it. Ground outside
every cascade is not shadowed in that view. Spot and point maps do not depend
on the camera, so every view reads them in the same way.

.. rst-class:: technical

Directional cascades use a fixed-width soft edge rather than the
contact-hardening PCSS described below. A sun is treated as infinitely far
away with no size, so there is no distance-based penumbra to compute.

Spot light: a single map
~~~~~~~~~~~~~~~~~~~~~~~~

A spot light lights a cone, which fits inside one shadow map pointed along the
light's direction. No cascades are needed. Spot shadows can also soften with
distance (see PCSS below).

Point light: a cube map
~~~~~~~~~~~~~~~~~~~~~~~

A point light (a bare bulb) lights every direction, which one flat map cannot
cover. The renderer surrounds the light with a **cube map**: six shadow maps,
one per face of a cube.

.. figure:: images/diagrams/shadows-4.svg
   :alt: A point light sits inside a cube of six depth maps; a ray through one face measures the distance to an object. The cube unfolds into six faces, one depth render each.
   :class: diagram

   A point light needs six shadow-map faces to cover every direction, so
   raising its resolution multiplies memory and drawing cost by six.

Point-light shadows are the most expensive kind. Per light, a cube map costs
six depth renders per frame and six times the memory of a single map, and the
memory grows with the square of the resolution. To limit the cost, the
renderer packs all point lights' cubes into one cube-map array where the
driver supports it, and limits how many lights cast shadows at once (see
:ref:`budget`).

Shadow Quality
--------------

Blocky edges
~~~~~~~~~~~~

The shadow map is an image with a fixed number of texels, and one map covers
everything its light reaches. When the camera is close to a shadow edge, one
map texel can cover many screen pixels, and the edge shows steps along the
texel boundaries.

There are two ways to reduce this: give the map more texels where they are
needed, or blur the edge when reading it. Cascaded shadow maps (above) do the
first for sun light. PCF and PCSS filtering (below) do the second. More
resolution costs memory and fill time; blurring costs extra samples per
pixel.

Softening the edge: PCF and PCSS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The plain depth test gives one yes-or-no answer per pixel, which produces a
hard, stepped edge. **Percentage-closer filtering** (PCF) tests a few
neighbouring texels and averages the results. The edge becomes a soft band a
few pixels wide. PCF is always on.

Real shadows are sharp where an object touches the ground and blur with
distance from the object that casts them. ``OPENGLCONTEXT_SHADOWS_SOFT=1``
turns on **percentage-closer soft shadows** (PCSS) for spot lights. PCSS first
estimates how far the blocker is from the surface, then widens the blur with
that distance. Contact points stay sharp and distant shadow spreads out.

.. _acne:

Shadow acne, bias and peter-panning
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The depth comparison has limited precision. The stored depths are quantized to
the map's texels, so a lit surface's own depth rarely matches the stored value
exactly. Where the stored value is slightly in front of the surface, the
surface shadows itself. The result is a pattern of dark speckles and stripes
called **shadow acne**.

.. figure:: images/diagrams/shadows-2.svg
   :alt: Without bias a surface self-shadows (acne); a small bias clears it; too much bias detaches the shadow from the object (peter-panning).
   :class: diagram

   Left: the quantized stored depth crosses the true surface, so the surface
   shadows itself. Middle: a small offset in the comparison clears the
   surface. Right: too large an offset separates the shadow from the point
   where the object meets the ground ("peter-panning").

OpenGLContext uses three small offsets instead of one large one, which keeps
each offset small enough to avoid peter-panning:

- Polygon offset (the main control) - while the depth map is drawn, the
  hardware pushes each polygon's stored depth slightly away from the light, so
  surfaces clear their own texels.

- Depth bias - an offset in the receiving shader, measured in shadow-map
  texels. The default is 3 texels. Set a light's own value with its
  ``shadowBias`` field.

- Normal offset - the tested point is moved a short distance (0.02 world
  units) along its surface normal before the lookup. This removes most of the
  remaining acne on surfaces lit at an angle, without the gap under objects
  that a larger depth bias would cause.

The depth bias is measured in texels because the map stores one depth per
texel, so the error to clear is about one texel wide. The map's own depth
units would not work as well. Depth is stored as 1/z in spot and cube maps
and linearly in cascades. A texel covers a fixed width in a cascade and a
width that grows with distance in the other maps. The same bias in depth units
would therefore give a different offset in every map, and at every depth in a
perspective map. Measured in texels, the offset is the same everywhere, does
not change with the scale of the scene, and halves when the map resolution
doubles. It also does not cause peter-panning, because it scales with the same
texel that the shadow's edge is already quantized to.

.. rst-class:: technical

The polygon offset and the normal offset are in ``passes/shadowmixin.py``
(``SHADOW_POLYGON_OFFSET_FACTOR/UNITS``, ``SHADOW_NORMAL_OFFSET``). The depth
bias is ``shadowmath.SHADOW_DEPTH_BIAS``, which is also the default of every
light's ``shadowBias`` field. ``shadowmath.depth_bias_terms`` converts each
light's value against that light's projection, once per map (once per cascade
for a sun), and the result reaches the shader as the three coefficients of
``shadowDepthBias[]``. A light with a larger bias therefore does not loosen
any other light's shadow, and cube maps need no separate allowance. No
slope-scaled bias is applied; the normal offset covers the cases it would
handle. ``tests/unit/test_shadow_bias_gl.py`` holds both failure modes in
check: it renders a lit wall and a pole standing on a floor, and measures the
speckle on the wall and the gap at the base of the pole.

Back faces in the depth pass
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The depth pass draws all faces; face culling is disabled for it. Each geometry
node still applies its own ``solid`` flag, so closed solids cull normally and
open shapes still cast. The depth pass does not use front-face culling, a
common acne fix that draws only back faces into the shadow map. Front-face
culling drops shadows from open or single-sided casters, such as a ground
quad, a leaf card or a one-sided wall, and combined with the offsets above it
over-biases into peter-panning. Where the driver supports it, depth clamping is
on during the depth pass, so a caster that extends past the edge of the
light's view still writes depth instead of being clipped.

.. _budget:

Working Within Hardware Limits
------------------------------

Every shadow map is a texture that the fragment shader samples. Samplers use
texture units, and a GPU has a fixed number of them: as few as 16 on
integrated graphics. Shadow maps share these units with material and
environment textures.

At start-up the renderer reads the number of texture units from the driver
(``GL_MAX_TEXTURE_IMAGE_UNITS``) and works out how many lights can cast
shadows at once within that budget. The number is compiled into the shader as
a constant. The shader therefore links and runs on a 16-unit laptop and on a
32-unit workstation, with a different limit on shadow-casting lights. To use
as few units as possible, spot and directional maps are packed into one array
texture, and point-light cubes into a cube-map array where available.

.. rst-class:: technical

The limit is ``MAX_SHADOW_LIGHTS``, computed by
``ShadowCapabilities.max_shadow_lights()`` (``passes/shadowcaps.py``) and
capped at 4. It is injected into the shader as a ``#define``, together with a
``SHADOW_CUBE_ARRAY`` flag (see :ref:`shader assembly <shader-assembly>`). The
GLSL is in ``shaders/_shadow_inc.glsl``, shared by ``vrml97_lighting.frag`` and
``pbr.frag``; its ``resolveShadows()`` loop is unrolled to the compiled limit.
If a scene has more shadow-casting lights than the limit, only the first ones
cast shadows.

Shadows of Rigged Figures
-------------------------

A skinned body is deformed in the vertex shader using a shared joint palette,
so its vertex buffers hold only the pose it was modelled in. The depth shader
applies the same skinning, and the depth pass gives it the same palette, so a
walking figure casts the shadow of its current pose.

This works whether casters are drawn one at a time or batched into a single
instanced draw. In a batch, each instance stores where its own joints start in
the palette, as in the colour pass. See :doc:`rigged characters <characters>`
and :doc:`instanced drawing <instancing>`.

.. _shadows-reproducible:

Reproducible Shadows for Testing
--------------------------------

The directional cascade count adapts to the frame rate, so by default the same
scene can render with a different number of cascades from run to run. For
reference-image tests, fix the count:

.. code-block:: bash

   OPENGLCONTEXT_SHADOW_CASCADES=3 python your_test.py

This skips the frame-rate check, so the shadow output is the same on every
run. A run started with ``--capture`` also keeps the cascade count fixed.

Tutorials and the Demo
----------------------

Three tutorials cover shadow mapping. The first two build a depth-map shadow
renderer by hand on the fixed-function / ARB path. The third builds the same
scene from scenegraph nodes and uses the shadow system on this page.

- :doc:`Depth-map Shadows: ARB Shadow on the Back Buffer <tutorials/shadow_1>`
  -- render the scene's depth from the light into a depth texture and project
  it back onto the scene, with the depth comparison and the bias/acne
  trade-offs done by hand.

- :doc:`Depth-map Shadows: Shadows in a Frame Buffer Object
  <tutorials/shadow_2>` -- the same technique, rendering the depth map
  off-screen into an FBO so the shadow map can be larger than the window.

- :doc:`Shadows from the Scenegraph <tutorials/shadow_3>` -- the same scene
  built as scenegraph nodes and lit by the shadow pass. It imports no OpenGL
  module and contains no rendering code.

The demo pictured at the top of this page shows the built-in shadow system
with moving objects and moving coloured lights casting shadows onto a floor
and a wall:

.. code-block:: bash

   python tests/shadow_demo.py

Add ``OPENGLCONTEXT_SHADOWS_SOFT=1`` for soft shadows, or
``OPENGLCONTEXT_SHADOWS=0`` to compare with shadows off. The `source
<https://github.com/mcfletch/openglcontext/blob/main/tests/shadow_demo.py>`__
builds a scenegraph with lights and geometry on a core-profile context and
contains no shadow code of its own.

Implementation Notes
--------------------

.. rst-class:: technical

Shadow storage is pooled in immutable depth textures, allocated once with
``glTexStorage*``: a 2D array holding all spot maps and directional cascades
(``ShadowMapArray``), and a cube-map array (or a single-cube fallback) for
point lights (``passes/shadowmap.py``). The depth textures use hardware
comparison sampling (``GL_COMPARE_REF_TO_TEXTURE`` / ``GL_LEQUAL``), so the
sampler does the 2×2 PCF tap and the shader adds only the extra taps. Cascade
fitting (splitting the view frustum and fitting a light-space box to each
slice) is GL-free math in ``passes/shadowmath.py``. The per-frame work and the
adaptive cascade controller are in ``passes/shadowmixin.py``. The VRML97 core
pass and the PBR pass both inherit this through ``ShadowMapMixin``, so their
shadows are identical. The design notes, including techniques not yet
implemented such as variance shadow maps, are in the `shadow-mapping plan
<https://github.com/mcfletch/openglcontext/blob/main/plans/SHADOW-MAPPING.md>`__.

Per-frame cost of casters
~~~~~~~~~~~~~~~~~~~~~~~~~

.. rst-class:: technical

To fit the cascades and the near and far planes of spot and point maps, the
pass needs every caster's bounding points in world space: the corners of its
bounding volume, transformed by its world transform. Two measures keep this
cheap.

.. rst-class:: technical

First, the pass keeps each caster's world bounds separately, not per set of
casters, because they depend only on the caster's bounding volume and world
transform. One car moving through several hundred still trees costs one car's
work. The scenegraph's transform cache returns the same matrix object while a
node is unmoved and a new one after it moves, so an identity check shows
whether a caster's bounds need recomputing. The pass keeps two frames of
results: a caster still present is carried forward, and one that has gone is
dropped a frame later. A world that pages tiles in and out therefore does not
accumulate every tile it has loaded.

.. rst-class:: technical

Second, the bounds that must be recomputed are computed for the whole set at
once. Each caster needs only a matrix product and a minimum and maximum over
eight rows, which is less work than numpy's per-call overhead. The pass groups
the volumes by point count and transforms and boxes each group in one call
(``shadowmath.world_bounds``). A scene of boxes is one group.
