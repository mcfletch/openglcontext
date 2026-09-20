Physically Based Rendering
==========================

.. rst-class:: introduction

Physically based rendering (PBR) is a way of describing materials by their
physical properties -- how metallic a surface is, how rough or polished, what
colour -- rather than by hand-tuned lighting numbers. Describe a material once
and it looks right under any lighting. OpenGLContext's PBR renderer uses the
same material model as glTF 2.0 and most modern engines, so models authored in
tools like Blender look the way their authors intended. This document is about
using it: what the material model lets you do, and how to build the look you
want.

.. image:: images/gltf/DamagedHelmet.jpg
   :alt: PBR render of the glTF DamagedHelmet sample

.. rst-class:: technical

The helmet above uses every part of the model at once: a colour map, metal and
roughness, surface-detail (normal) mapping, a glowing (emissive) display,
environment reflections and a cast shadow -- all from a single material.

Turning It On
-------------

The easiest way to see the PBR renderer is the :doc:`oglc-view <viewer>`
viewer, which switches everything on for you:

.. code-block:: bash

   oglc-view path/to/model.glb

To use PBR for your own scene, name the renderer:

.. code-block:: bash

   OPENGLCONTEXT_RENDERER=pbr python your_script.py

The core profile it needs is already the default. If PBR cannot be started for
any reason, the plain :doc:`core renderer <renderpasses>` is used instead.

The Material Model: Two Dials
-----------------------------

Most of a PBR material comes down to a colour and two dials. The image below
is the ``MetalRoughSpheres`` sample: metalness changes along one axis,
roughness along the other.

.. image:: images/gltf/MetalRoughSpheres.jpg
   :alt: A grid of spheres from metal to non-metal and smooth to rough

- **Base colour** -- the surface's own colour. For an ordinary (non-metal)
  surface this is the colour you see; for a metal it tints the reflection (gold
  vs. silver vs. copper).

- **Metalness** (0 to 1) -- is this a metal? Leave it at **0** for everyday
  materials: plastic, wood, stone, skin, cloth. Set it to **1** for bare metal:
  steel, gold, aluminium. Metals reflect their surroundings and have almost no
  colour of their own except through their reflection; non-metals show their
  base colour and a plain white highlight. Values in between are rare and
  usually only appear where a metal meets a coating (rust, paint).

- **Roughness** (0 to 1) -- how polished or matte the surface is. **0** is a
  mirror or clear gloss with sharp reflections and a tight highlight; **1** is
  fully matte, scattering light softly with no visible reflection. Most real
  surfaces sit somewhere between.

That is enough to describe a huge range of materials. A polished chrome ball
is metalness 1, roughness 0. A rubber ball is metalness 0, roughness 0.9. A
glossy plastic toy is metalness 0, roughness 0.2.

Material Recipes
----------------

Starting points for common looks. Adjust to taste, and add a :ref:`normal map
<maps>` for fine surface detail.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Look
     - Metalness
     - Roughness
     - Extras
   * - Polished metal / chrome
     - 1.0
     - 0.05 - 0.15
     - base colour tints it (gold, copper)
   * - Brushed / satin metal
     - 1.0
     - 0.3 - 0.5
     - normal map for the brush lines
   * - Glossy plastic
     - 0.0
     - 0.1 - 0.3
     - bright base colour
   * - Matte plastic / rubber
     - 0.0
     - 0.7 - 1.0
     - —
   * - Polished stone / marble
     - 0.0
     - 0.2 - 0.4
     - normal map; optional clearcoat
   * - Rough stone / concrete
     - 0.0
     - 0.8 - 1.0
     - normal + occlusion maps
   * - Leather
     - 0.0
     - 0.5 - 0.7
     - normal map for the grain
   * - Wood (varnished)
     - 0.0
     - 0.3 - 0.5
     - colour map; optional clearcoat
   * - Car paint
     - 0.0
     - 0.4
     - clearcoat 1.0 (see below)
   * - Velvet / fabric
     - 0.0
     - 0.8
     - sheen (see below)
   * - Glass / water
     - 0.0
     - 0.0 - 0.2
     - transmission (see below)

.. _maps:

Texture Maps: Painting the Dials
--------------------------------

A single colour and two numbers give a whole object one uniform look. To vary
the look across the surface -- rust here, clean metal there, a label on a
bottle -- you paint the properties into *texture maps*. A mesh carries texture
coordinates (UVs) that say where each point of the surface lands on a flat
image; the renderer looks up each map at those coordinates. Each map drives a
specific role:

- **Base colour map** -- the colour and pattern of the surface (the label, the
  paint, the wood grain). Stored as an ordinary (sRGB) image.

- **Metallic-roughness map** -- which parts are metal and how rough each part
  is, packed into one image (roughness in the green channel, metalness in the
  blue). This is how a single object can be shiny metal in one place and matte
  paint in another.

- **Normal map** -- fine surface bumps (pores, scratches, brush lines, fabric
  weave) faked without adding geometry. It makes a flat triangle catch light as
  if it were textured.

- **Occlusion map** -- baked soft shadow in creases and cavities, so recessed
  areas read as darker.

- **Emissive map** -- the parts that glow (a screen, an LED, hot metal).
  Emissive areas are lit from within and do not depend on scene lights.

You do not have to supply every map. A material can be just a base colour and
two dials, or a full set of maps, or anything between. Any property with a map
still has a plain factor too, and the two multiply -- so a white base-colour
map with a red base-colour factor gives a red surface.

.. rst-class:: technical

Each map can name its own UV set. glTF gives every texture reference a
``texCoord`` of 0 or 1; the loader records which channels asked for the second
set in the material's ``texCoordMask``, and the shader samples each channel
from the set it named. That is what lets a wall carry its brick pattern tiled
many times over and its baked lighting stretched once across the whole
surface. The mesh has to supply the second set (``TEXCOORD_1``) for the
channels that ask for it; where it does not, those channels sample at the
origin of their map and the surface comes out one flat colour.

.. rst-class:: technical

``KHR_texture_transform`` (offset/scale/rotate of the coordinates) is
honoured, including its own ``texCoord`` override. One transform is stored per
material and applied to whichever channels carry the extension — see
:ref:`Surfaces that move <animated-surfaces>` for how to choose them. A
material giving two of its textures *different* transforms gets the last one
for both.

Glass, Clearcoat and Fabric
---------------------------

Three optional effects extend the basic model. They are always available; a
material simply sets the relevant properties.

- **Transmission (glass, water)** -- makes a thin surface let light through so
  you can see the scene behind it, refracted. Set ``transmission`` toward 1,
  keep ``metalness`` at 0, and use a low ``roughness`` for clear glass or a
  higher one for frosted glass. ``ior`` (index of refraction, about 1.5 for
  glass, 1.33 for water) controls how much the view bends. This is the effect in
  the olive dish below.

- **Clearcoat** -- a thin glossy layer over the base material, like the lacquer
  on car paint or varnish on wood. Set ``clearcoat`` toward 1 and
  ``clearcoatRoughness`` low for a sharp second highlight on top of the material
  underneath.

- **Sheen** -- the soft rim-glow of cloth: velvet, satin, brushed fabric. Set a
  ``sheenColor`` and a ``sheenRoughness``.

.. image:: images/gltf/IridescentDishWithOlives.jpg
   :alt: A dish of olives under a glass cover, light passing through the glass

Emissive (glow) is part of the basic model: set ``emissiveColor`` for a
surface that gives off light of its own, and ``emissiveStrength`` to push it
brighter than white for a bloomed, hot look.

.. rst-class:: technical

On software rasterizers, or with ``OPENGLCONTEXT_TRANSMISSION=blend``, glass
falls back to simple alpha blending instead of true refraction.

Where Materials Come From
-------------------------

Most PBR materials arrive ready-made inside a :doc:`glTF model <gltf>`
authored in a tool such as Blender -- you load the file and the materials come
with it. You can also build a material in Python with a ``PBRMaterial`` node
and attach it to a ``Shape`` through an ``Appearance``:

.. code-block:: python

   from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
   from OpenGLContext.scenegraph.basenodes import Shape, Appearance

   # brushed gold
   gold = PBRMaterial(
       baseColor = (1.0, 0.78, 0.34),
       metallic  = 1.0,
       roughness = 0.35,
   )

   # glowing green sign
   sign = PBRMaterial(
       baseColor     = (0.1, 0.1, 0.1),
       metallic      = 0.0,
       roughness     = 0.6,
       emissiveColor = (0.1, 1.0, 0.2),
   )

   # clear glass
   glass = PBRMaterial(
       baseColor    = (1.0, 1.0, 1.0),
       metallic     = 0.0,
       roughness    = 0.05,
       transmission = 1.0,
       ior          = 1.5,
   )

   shape = Shape(appearance=Appearance(material=gold), geometry=my_geometry)

The commonly used fields are ``baseColor``, ``metallic``, ``roughness``,
``emissiveColor``, ``emissiveStrength``, ``clearcoat`` /
``clearcoatRoughness``, ``sheenColor`` / ``sheenRoughness``, ``transmission``,
``ior``, and the transparency controls ``alphaMode`` (``OPAQUE``, ``MASK`` or
``BLEND``) and ``alphaCutoff``. Legacy VRML97 ``Material`` nodes are converted
to metallic/roughness automatically, so a mixed scene works without changes.

.. rst-class:: technical

Textures are supplied through a ``textures`` dictionary keyed by channel
(``baseColor``, ``metallicRoughness``, ``normal``, ``occlusion``,
``emissive``), each a ``PBRTexture`` wrapping a PIL image; base colour and
emissive images are sRGB, the rest linear. The glTF loader builds these for
you when it imports a model.

What Feeds the Shader
---------------------

A ``PBRMaterial`` supplies the surface properties; the scene supplies the
lighting. The shader combines them into the final colour of each pixel:

.. image:: images/diagrams/pbr-1.svg
   :alt: Diagram: material properties and scene lighting feed the PBR shader, which produces the shaded pixel
   :class: diagram

Each knob on the left changes one aspect of the surface; the scene's lights,
environment and shadows do the rest. The table below lists every property you
can set.

Every Knob
~~~~~~~~~~

**Surface basics**

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Property
     - Default
     - What it controls
   * - ``baseColor``
     - (1, 1, 1)
     - the surface's own colour; tints a metal's reflection
   * - ``metallic``
     - 1.0
     - metal (1) versus everyday material (0)
   * - ``roughness``
     - 1.0
     - polished/glossy (0) versus matte (1)
   * - ``emissiveColor``
     - (0, 0, 0)
     - colour the surface gives off on its own
   * - ``emissiveStrength``
     - 1.0
     - multiplier to push emissive brighter than white
   * - ``normalScale``
     - 1.0
     - strength of the normal (bump) map
   * - ``occlusionStrength``
     - 1.0
     - strength of the baked occlusion map
   * - ``ior``
     - 1.5
     - index of refraction; base reflectivity and how much glass bends the view
   * - ``specular`` / ``specularColor``
     - 1.0 / (1,1,1)
     - fine control of the non-metal highlight strength and tint

**Optional lobes** (each off at 0)

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Property
     - Default
     - What it controls
   * - ``clearcoat``
     - 0.0
     - strength of a clear glossy layer on top (car paint, varnish)
   * - ``clearcoatRoughness``
     - 0.0
     - how sharp the clearcoat's highlight is
   * - ``sheenColor``
     - (0, 0, 0)
     - colour of the soft fabric rim-glow (velvet, satin)
   * - ``sheenRoughness``
     - 0.0
     - how spread-out the sheen is
   * - ``transmission``
     - 0.0
     - how see-through the surface is (glass, water)
   * - ``thickness``
     - 0.0
     - volume thickness for tinting transmitted light
   * - ``attenuationColor`` / ``attenuationDistance``
     - (1,1,1) / 0
     - colour picked up passing through the volume, and over what distance

**Transparency and rendering**

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Property
     - Default
     - What it controls
   * - ``alphaMode``
     - ``OPAQUE``
     - ``OPAQUE``, ``MASK`` (hard cutout) or ``BLEND`` (see-through)
   * - ``alphaCutoff``
     - 0.5
     - threshold used in ``MASK`` mode
   * - ``transparency``
     - 0.0
     - legacy opacity (1 = fully transparent)
   * - ``doubleSided``
     - false
     - draw back faces as well as front
   * - ``unlit``
     - false
     - show the base colour flat, ignoring lighting

**Texture maps** -- supplied through the ``textures`` dictionary, keyed by
channel: ``baseColor``, ``metallicRoughness``, ``normal``, ``occlusion``,
``emissive``. Each map paints its property across the surface (see
:ref:`Texture Maps <maps>` above); where a map and a factor both exist, they
multiply.

.. rst-class:: technical

Defaults follow the glTF 2.0 spec, which is why ``metallic`` and ``roughness``
default to 1.0: a bare material with no maps is a rough non-reflective metal
until you set them. Authoring tools almost always set both.

You can readily find PBR textures online with CC0 or similar licenses that you
can use in your editor (e.g. Blender). PBR materials are pretty much a base
feature of most 3D engines these days.

Lighting the Scene
------------------

A material only looks right if the scene is lit. The PBR renderer lights
surfaces two ways at once: direct lights (sun, lamps, spotlights) and the
surrounding environment.

.. _environment-lighting:

Environment Lighting (Reflections and Ambient)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Real surfaces reflect their surroundings and pick up soft colour from the
whole scene, not just from direct lights. The renderer supplies this
"image-based lighting" from a built-in studio environment, so metals have
something to reflect and matte surfaces are softly lit even in shadow. It is
on by default. You can adjust or disable it:

- ``OPENGLCONTEXT_IBL_INTENSITY`` -- scale the environment/ambient strength
  (default 1.0). The viewer lowers it to 0.4 so cast shadows stay readable.

- ``OPENGLCONTEXT_IBL`` -- force it ``full``, ``analytic`` (a cheaper
  approximation), or ``off`` (flat ambient, no reflections).

A scene that carries its own sky lights itself with it. ``HDRBackground``
takes a Radiance ``.hdr`` equirectangular panorama — the usual HDRI
interchange format — draws it as the sky, and registers the same panorama as
the environment, so what a metal reflects is what is behind it. The panorama
keeps its values above 1.0 where the sun and the sky are brighter than white,
which is the reason to use one, and the visible sky is exposure-scaled and
tone-mapped the way lit geometry is, so that the two agree. Six LDR JPEG faces
in a ``CubeBackground`` are the cheaper alternative, and light nothing.

Left to itself, environment lighting steps down to the cheaper approximation
when the frame rate sags and climbs back after sustained headroom, so it never
pins a scene below sixty frames a second. That is a courtesy to somebody
watching, and **a capture has nobody watching**: a run started with
``--capture`` holds the mode it began with for the whole run, so what the
image shows does not depend on where the climb had got to when the frame was
taken. The shadow cascades are pinned for a capture for the same reason.

.. _bakedlight:

Baked Lighting: Lightmaps and the Light Grid
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A world whose lighting was solved when it was built carries the answer with it
rather than computing it again every frame. The renderer reads two records of
such a solve, and a scene may use either or both.

A **lightmap** is that light painted onto the surfaces themselves, addressed
by a second UV set. Give the material a ``lightmap`` texture, set bit 32 of
``texCoordMask`` so it samples ``TEXCOORD_1``, and scale its exposure with
``lightmapStrength``. It is read as linear light, not as an sRGB colour: a
baked solution is written straight to eight bits and decoding it would leave
the level looking unlit.

That reaches only the surfaces that existed when the world was built. Anything
that arrives afterwards — a character, a pickup, a door, a projectile —
carries no lightmap coordinate, so in a level that bakes its lighting and
places no lamps it has nothing lighting it at all. A **light grid** is the
same solve recorded a second way for them: a regular grid of samples over the
world, each holding the light arriving at that point as an ambient term and a
directional one. The pass looks each object's own position up in it, so what
an object is lit by is where it is standing.

.. code-block:: python

   from OpenGLContext.scenegraph.lightgrid import LightGrid

   scene.children.append(LightGrid(
       origin=(-40.0, -2.0, -40.0),      # world position of sample (0, 0, 0)
       spacing=(1.6, 3.2, 1.6),          # metres between samples on each axis
       counts=[51, 9, 51],               # samples along x, y and z
       ambient=ambient,                  # one linear colour per sample
       directional=directional,          # one linear colour per sample
       direction=direction,              # a unit vector towards the light
       intensity=2.0,                    # the exposure the lightmaps use
   ))

The sample arrays are flat, with x varying fastest: ``index = ix + counts[0] *
(iy + counts[1] * iz)``. Sampling is trilinear and clamps at the edges, so an
object that walks past the last sample keeps the light of the nearest one
instead of going dark at an invisible line. One grid lights a scene: the first
one found with samples in it is used.

What it costs is one interpolation and three uniforms per object per frame,
and only for scenes that have a grid at all. What it does not cover:

- **A surface with its own lightmap is left alone.** The two are one solve, and
  taking both would light the world's geometry twice.

- **One sample per object**, taken at the middle of its bounding volume, so the
  light does not vary across a single object. For figures and props at the
  spacing a baked grid uses, it does not need to.

- **Instanced draws are not grid-lit.** A group of shapes collapsed into one
  draw could only share one sample, which would be the wrong answer for all but
  one of them.

- The :doc:`VRML97 core shader <renderpasses>` does not read it, as it does not
  read lightmaps either; baked lighting is a PBR path.

twig-bb builds one from a Quake 3 map's lightvol lump, in
``twig_bb/lighting.py``, which is where the arrangement comes from.

.. _shadows:

Shadows
-------

The PBR renderer casts dynamic shadows, on by default. Directional lights (a
sun) shadow the whole scene, spot lights cast a cone, and point lights shadow
in every direction; turn them off with ``OPENGLCONTEXT_SHADOWS=0`` or soften
spot shadows with ``OPENGLCONTEXT_SHADOWS_SOFT=1``.

Shadows are shared with the :doc:`VRML97 core lighting shader <renderpasses>`
-- the same system serves both -- so they have their own document: see
:doc:`Shadows <shadows>` for the full discussion and controls.

Under the Hood: the Shading Math
--------------------------------

.. rst-class:: technical

This section is a short overview for the curious; you do not need it to use
the renderer. For a full line-by-line walkthrough of the fragment shader --
every texture, uniform and buffer it reads, and how each lobe is sampled and
combined -- see :doc:`The PBR Uber-Shader, Step by Step <ubershader>`.

.. rst-class:: technical

Direct light is evaluated with the Cook-Torrance microfacet model: a specular
term plus a Lambertian diffuse term. The specular term is the product of three
functions, ``D * V * F``:

- **D** -- the GGX / Trowbridge-Reitz normal distribution: how microfacets are
  oriented for a given roughness.

- **V** -- the height-correlated Smith visibility term. It folds the geometric
  shadowing/masking *and* the ``1 / (4·NdotL·NdotV)`` denominator into one
  function, so the shader multiplies ``D * V * F`` with no separate denominator.

- **F** -- the Fresnel-Schlick term: the rise in reflectance at grazing angles.

.. rst-class:: technical

The diffuse term is ``albedo / π``, scaled by ``(1 - F)`` to conserve energy
and by ``(1 - metalness)`` because metals have no diffuse reflection. The BRDF
works in terms of ``alpha = roughness²``; the perceptual roughness you set is
squared exactly once, and the same convention is shared between the
direct-lighting and environment-lighting paths (both use one include,
``shaders/_brdf_inc.glsl``) so the two halves integrate the same lobe.

.. rst-class:: technical

Environment lighting uses the split-sum approximation: a prefiltered
environment cube (one blur level per roughness), an irradiance cube for
diffuse ambient, and a BRDF lookup table, all precomputed once from the studio
environment.

.. rst-class:: technical

**Colour.** Lighting is computed in linear colour. Base-colour and emissive
texels are decoded from sRGB on input; the final colour is tone-mapped with an
ACES filmic curve and re-encoded to sRGB. Because the shader encodes sRGB
itself, ``GL_FRAMEBUFFER_SRGB`` is left disabled (see :doc:`Core-Profile
Rendering <renderpasses>`).

.. rst-class:: technical

**One shader for the scene.** Clearcoat, sheen and transmission are branches
inside a single "uber-shader" driven by uniforms that are constant per draw
call, so the whole scene binds one program rather than switching shaders per
material -- the switches are coherent and cheap. The three optional lobes are
gated by compile-time defines (all on today) as a designed-in place to build a
leaner shader for a constrained platform: chosen once per platform, never per
material. Material factors are packed into a std140 uniform buffer, built once
per material and reused across frames.

.. _fog:

Fog: the medium the camera is standing in
-----------------------------------------

Put a ``Fog`` node in the scene and the view fades into its colour with
distance. That is the whole of the interface — the pass finds the bound node
while it is gathering the frame, exactly as it finds the background:

.. code-block:: python

   from OpenGLContext.scenegraph.basenodes import Fog

   Fog(color=(0.06, 0.20, 0.32),     # linear RGB
       visibilityRange=18.0,          # metres to total obscurity; 0 is off
       fogType='EXPONENTIAL')         # or 'LINEAR', the default

It is VRML97's own node, with the fields that specification gives it (`ISO/IEC
14772-1 6.19
<https://www.web3d.org/documents/specifications/14772/V2.0/part1/nodesRef.html#Fog>`__).
Being a node rather than a number on the context is the point: fog is a
property of a *place*, so it binds and stacks like a viewpoint, and being
under water, inside a smoke-filled room and out in clear air are three fogs in
one scene with one in force.

Why there are two curves
~~~~~~~~~~~~~~~~~~~~~~~~

They reach total obscurity at the same range and fade differently on the way,
so choosing between them is choosing the shape and not the extent:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - ``fogType``
     - Fades
     - Suits
   * - ``LINEAR``
     - in proportion to distance, from the very first metre
     - haze, aerial perspective, dissolving the far edge of a terrain patch
   * - ``EXPONENTIAL``
     - hangs back, then closes in
     - a *medium* — water, smoke — where what is right in front of you is clear and
       the far wall is not

That difference matters more than it sounds. A linear fade tints the weapon in
the player's hands as much as it tints the wall behind it, which reads as a
coloured pane of glass laid over the screen rather than as being *inside*
something. This is also why an underwater view should be a fog and not a
full-screen overlay: an overlay has no depth in it at all.

Where it lands in the pipeline
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The blend happens **in linear HDR, before tone mapping**, which is what keeps
a fogged scene from posterising in the highlights. One uniform carries the
scale for every mode: the reciprocal of the visible range, which the shader
multiplies by the fragment's distance. A scene with no ``Fog`` in it — nearly
every scene — is left pixel-identical, because the mode uniform stays at zero.

A transform above a ``Fog`` scales its ``visibilityRange``, since the
specification puts the range in the node's local coordinates; a model authored
with its own fog therefore carries it when placed at a different size.

.. rst-class:: technical

``OpenGLContext/scenegraph/fog.py`` holds the node and the mode codes; the
pass reads it in ``flateffects._FlatEffectsMixin.applyFog`` and it reaches the
shader through ``PBRShaderProgram.set_fog(density, color, mode)``.

.. _animated-surfaces:

Surfaces that move
------------------

Three things can move a PBR surface at run time, and they cost very different
amounts. Reaching for the cheapest one that will do the job is most of the
performance story for animated materials.

1. The UV transform — one uniform
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``PBRMaterial.uv_transform`` is a 3×3 ``KHR_texture_transform`` matrix.
Assigning it bumps the material's upload version, so the pass re-uploads its
uniform block and nothing else happens. A scrolling conveyor belt, a rotating
fan or a stretching liquid costs this and no more, however large the surface
is.

.. code-block:: python

   material.uv_transform = [[1, 0, u_offset],
                            [0, 1, v_offset],
                            [0, 0, 1]]        # translation in the last COLUMN

Which channels it applies to is the high half of ``texCoordMask``: the
channel's low bit shifted by 8. Set it for the base colour and leave it clear
for the lightmap, or a scrolling texture drags the baked lighting along with
it and takes the shadows off the walls.

.. code-block:: python

   material.texCoordMask |= (1 << 8)     # baseColor transformed, lightmap not

2. Colour, opacity and texture — one uniform or one bind
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``baseColor``, ``emissiveColor`` and ``transparency`` are ordinary material
fields; assigning any of them re-uploads the block. Replacing
``material.textures`` with a new dict swaps a map — assign, do not mutate, or
the version is not bumped and the old texture set is served.

3. The vertices — a per-frame CPU pass and a buffer re-upload
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When the movement genuinely cannot be a matrix — a wave that heaves the
geometry, a churn whose offset depends on where each vertex *is* — a mesh
takes a **surface deformer**:

.. code-block:: python

   def churn(positions, normals, texcoords):
       return positions + wave(positions, clock.now), normals, texcoords

   mesh.set_surface_deformer(churn)     # applies at once
   ...
   mesh.refresh_surface()               # each frame; re-reads the deformer

This is a *third* stage on the same pipeline morph targets and skinning
already use: rest arrays are kept, the deform chain is morph → skin → surface,
a version counter bumps, and each per-context GPU object re-uploads the
dynamic vertex buffers. Three properties are worth knowing:

- **The deformer always sees the rest pose**, never its own last output.
  Deforming the previous frame compounds, and a one-unit wave walks the surface
  away over a few seconds.

- **It is handed copies**, so a deformer that writes in place cannot corrupt the
  rest arrays it will be handed next frame.

- **UVs are only made dynamic if the mesh says they move**
  (``deforms_texcoords``, true once a deformer is set). Morphing and skinning
  never move UVs, so a skinned character does not pay to re-upload them — which
  is why the deformer must be set *before* the mesh is first drawn.

A deformer that returns nothing usable leaves the mesh alone: content is not
always well formed, and a bad effect should cost its effect rather than its
surface.

.. rst-class:: technical

``scenegraph/pbrmesh.py``: ``set_surface_deformer``, ``refresh_surface``,
``deforms_texcoords``, and stage 3 of ``_apply_deform``. The twig-bb drives
all three of these from Quake 3 \`.shader\` scripts; ``twig_bb/animator.py``
is a worked example.
