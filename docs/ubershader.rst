PBR Uber-Shader
===============

.. rst-class:: introduction

This page walks through the PBR fragment shader, ``shaders/pbr.frag``: the
data it receives, what it reads from each texture, uniform and buffer, how it
computes each material lobe, and how it combines them into the colour of one
fragment. It assumes you know the concepts in :doc:`Physically Based Rendering
<pbr>`. Each piece of theory is tied to the shader code that implements it.

.. rst-class:: technical

The whole scene uses one shader *program*, the "uber-shader", built from
several files. ``shaders/pbr.frag`` is the top level, and its ``#include``
directives splice in shared files at compile time: ``_common_inc.glsl`` (sRGB
conversion and PI), ``_brdf_inc.glsl`` (the BRDF terms), ``_lights_inc.glsl``
(the light uniforms), ``_shadow_inc.glsl`` (:doc:`shadows <shadows>`),
``_viewer_inc.glsl`` (the viewer position for each :doc:`view <multiview>`)
and ``_wave_inc.glsl`` (the water ripple). Per-driver ``#define`` lines are
injected, and the result is compiled once; see :ref:`shader-assembly`. The
vertex stage is ``shaders/pbr.vert``. Other shaders share the same includes;
for example, the IBL precompute shaders also compile ``_brdf_inc.glsl``, so
the BRDF has one definition.

What Reaches the Shader
-----------------------

Before the fragment shader runs, the pass sets up five kinds of input.

1. Per-vertex data from the vertex shader
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``pbr.vert`` transforms each vertex into eye space and passes these values to
the fragment stage:

- ``vPosition`` -- eye-space position, used for the view vector, distance
  attenuation and the transmission projection.

- ``vNormal`` -- eye-space normal, transformed by ``normalMatrix``, the
  inverse transpose of the upper 3×3 of the modelview.

- ``vTangent``, ``vTangentW`` -- eye-space tangent and its handedness, used to
  build the normal-map frame. The tangent is transformed by the plain
  modelview 3×3, not the normal matrix. When the mesh has no tangent it is
  zero, and the fragment shader treats that as "no tangent".

- ``vTexCoord``, ``vTexCoord1`` -- the first and second UV sets
  (``TEXCOORD_0`` and ``TEXCOORD_1``).

- ``vColor`` -- per-vertex colour (glTF ``COLOR_0``).

- ``vModelScale`` -- the object's world-space scale, which converts the
  volume ``thickness`` from model units to world units.

- ``vObjectId``, ``vMaterialIndex`` -- the picking id and material index of an
  :doc:`instanced <instancing>` draw.

The vertex attributes arrive at the engine's :ref:`fixed attribute locations
<fixed-attribute-locations>`: 0 = texcoord, 1 = normal, 2 = position,
3 = tangent, 4 = colour, 11 = second texcoord, 12 and 13 = skinning.

2. The material, as a std140 uniform buffer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All of a material's constant factors are packed into one uniform buffer
object, ``MaterialBlock``, which the pass binds with one call per shape.
Setting the same data field by field takes about twenty ``glUniform`` calls
per shape, and in a scene with hundreds of shapes those calls take most of
the frame's CPU time. The block holds an array of materials, so an instanced
draw can give each instance its own factors; a non-instanced draw uses
element 0. ``main()`` copies the active element into a local ``_M`` once, and
the shader reads each factor by name:

.. code-block:: glsl

   struct Material {
       vec3  baseColorFactor;      float metallicFactor;
       vec3  emissiveFactor;       float roughnessFactor;
       vec3  specularColorFactor;  float occlusionStrength;
       vec3  sheenColorFactor;     float normalScale;
       vec3  attenuationColor;     float alphaCutoff;
       float emissiveStrength;     float specularFactor;
       float clearcoatFactor;      float clearcoatRoughness;
       float sheenRoughnessFactor; float ior;
       float thicknessFactor;      float attenuationDistance;
       bool  unlitMode;
       int   texCoordMask;
       float anisotropyStrengthM;
       float dispersionM;
       mat3  uvTransform;
       vec4  iridescence;          // factor, ior, thicknessMin, thicknessMax
       vec4  diffuseTransmissionM; // rgb colour, a factor
       vec4  anisotropyDirM;       // xy = (cos, sin) of the rotation
   };
   layout(std140) uniform MaterialBlock {
       Material materials[MAX_INSTANCE_MATERIALS];
   };

One element is 224 bytes, and the byte layout matches the Python packer
(``pbrpass.pack_material_block``). ``MAX_INSTANCE_MATERIALS`` is 73, which
fits the 16 KB uniform-block size every driver guarantees. The pass builds the
buffer once per material and reuses it across frames.

3. Texture maps on fixed units
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each map is a sampler with a matching ``has…`` flag, so a material can omit
any of them. The pass assigns fixed texture units so the material samplers
never collide with the shadow and IBL textures inside the 16 units GL 3.3
guarantees:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Sampler
     - Unit
     - Read as
   * - ``lightmapTexture``
     - 0
     - linear baked light (see :ref:`bakedlight`)
   * - ``baseColorTexture``
     - 1
     - sRGB colour, decoded to linear
   * - ``metallicRoughnessTexture``
     - 2
     - linear; green = roughness, blue = metalness
   * - ``normalTexture``
     - 3
     - linear tangent-space normal
   * - shadow samplers
     - 4–9
     - 4 and 5 for the spot/cascade array, 6 onward for point-light cubes; see
       :doc:`Shadows <shadows>`
   * - ``occlusionTexture``
     - 10
     - linear; red channel
   * - ``emissiveTexture``
     - 11
     - sRGB, decoded to linear
   * - ``transmissionTexture``
     - 12
     - the captured opaque backdrop (mipmapped)
   * - ``irradianceMap`` / ``prefilterMap`` / ``brdfLUT``
     - 13 / 14 / 15
     - the IBL probe (see below)

The textures of the further glTF extensions (clearcoat, sheen, specular,
transmission, volume thickness, iridescence, anisotropy and diffuse
transmission maps) use units 16 to 29. The pass compiles them in only when
the driver reports at least 30 fragment texture units
(``GL_MAX_TEXTURE_IMAGE_UNITS``); otherwise those materials use their plain
factors.

4. Scene lighting (plain uniforms)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``_lights_inc.glsl`` declares ``numLights`` and, for each light,
``lightType``, ``lightColor``, ``lightPosition``, ``lightDirection``,
``lightAttenuation``, ``lightRange``, ``lightBeamWidth`` /
``lightCutOffAngle`` (the spot cone) and ``lightIntensity``, plus a flat
``sceneAmbient``. All are in eye space, like the vertex outputs. A scene with
a :ref:`light grid <bakedlight>` also sets ``lightGridAmbient``,
``lightGridDirectional`` and ``lightGridDirection`` for each object.

5. Environment and frame state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- ``iblMode`` and ``iblIntensity`` select and scale the environment lighting.
- ``eyeToWorld`` rotates eye-space vectors into the world orientation of the
  probe cubes.
- ``projectionMatrix`` is reused for the transmission projection.
- ``alphaMode``, ``alphaValue`` and the ``transmission…`` uniforms come from
  the render mode, not the material.
- ``exposure`` is the camera exposure multiplier (default 1.0).
- ``fogMode``, ``fogDensity`` and ``fogColor`` describe the :ref:`fog <fog>`.
- ``hdrOutput`` is set while :ref:`bloom <frame-sequence>` is on.
- ``objectId`` is the picking id for the selection buffer.

The Fragment Shader, Top to Bottom
----------------------------------

This section follows ``main()`` in order, with what each step reads and
produces.

Sampling the material
~~~~~~~~~~~~~~~~~~~~~

Each texture is sampled through ``uvFor(bit)``, where ``bit`` is the
channel's bit in ``texCoordMask`` (1 base colour, 2 metallic-roughness, 4
normal, 8 occlusion, 16 emissive, 32 lightmap). If the channel's bit is set,
it samples ``TEXCOORD_1``. If the same bit shifted left by 8 is set, it also
applies ``uvTransform`` (``KHR_texture_transform``).

The base colour texel is decoded from sRGB to linear and multiplied by
``baseColorFactor`` and by the per-vertex colour. Alpha is ``alphaValue``
times the texel's alpha, and times the vertex colour's alpha. In ``MASK`` mode
a fragment below ``alphaCutoff`` is discarded. An ``unlitMode`` material
writes its base colour at this point and skips all lighting.

Metalness and roughness start from their factors and are multiplied by the
blue and green channels of the metallic-roughness texture. Roughness is
clamped to ``[0.04, 1.0]``, then squared into the value the BRDF uses:

.. code-block:: glsl

   float alphaR = roughness * roughness;   // glTF GGX uses alpha = roughness^2

.. rst-class:: technical

The squaring happens once. The shader keeps the perceptual ``roughness`` to
pick the environment-map level and the BRDF lookup, and passes ``alphaR`` to
the microfacet functions. The direct and image-based paths use the same
convention. Feeding perceptual roughness into the microfacet functions would
give the wrong lobe width.

Next the shader reads occlusion (the red channel, applied as ``1 +
occlusionStrength * (o - 1)``), emissive (``emissiveFactor ×
emissiveStrength``, times the decoded emissive texel) and the lightmap (the
linear texel times ``lightmapStrength``). When the material's ``bakedLight``
flag is set, the vertex colour is baked light rather than a tint: it is added
to the emission instead of multiplying the base colour, and its alpha scales
the occlusion.

Building the shading normal
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The interpolated normal is normalized and flipped on back faces
(``!gl_FrontFacing``), so two-sided surfaces light correctly. On a water
surface the ripple from ``_wave_inc.glsl`` tilts it. If the material has a
normal map and the mesh has a tangent, the shader builds a tangent-basis (TBN)
matrix and rotates the sampled normal into eye space. The sampled normal is
remapped from ``[0,1]`` to ``[-1,1]`` and scaled by ``normalScale``:

.. code-block:: glsl

   vec3 T = normalize(vTangent - N * dot(N, vTangent));
   vec3 B = cross(N, T) * (vTangentW == 0.0 ? 1.0 : vTangentW);
   vec3 nTex = texture(normalTexture, uvFor(4)).xyz * 2.0 - 1.0;
   nTex.xy *= normalScale;
   N = normalize(mat3(T, B, N) * nTex);

The clearcoat layer has its own normal, ``Nc``: the geometric normal, changed
only by a clearcoat normal map. A normal map on the base layer does not affect
the coat.

The view vector ``V`` points from the fragment to the viewer. With a single
view the camera is at the eye-space origin, so ``V`` is
``normalize(-vPosition)``. ``NdotV`` is clamped away from zero.

The reflectance at normal incidence (F0)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``F0`` is how reflective a surface is when viewed head-on. For a non-metal it
comes from the index of refraction, tinted by the ``KHR_materials_specular``
colour. For a metal it is the base colour. Metalness blends between the two.
The specular weight sets ``specF90``, the reflectance at grazing angles; a
metal keeps ``specF90 = 1``:

.. code-block:: glsl

   float iorF0 = pow((ior - 1.0) / (ior + 1.0), 2.0);
   vec3 dielF0 = min(iorF0 * specularColorEff, vec3(1.0));
   vec3 F0 = mix(dielF0, albedo, metallic);
   float specF90 = mix(specularWeight, 1.0, metallic);

At ``metallic = 1`` the reflection takes the base colour and the diffuse term
(below) is zero, which is why metalness changes the look of a surface so
much. An iridescent material then blends ``F0`` toward a thin-film Fresnel
value that shifts hue with the view angle.

Shadows
~~~~~~~

``resolveShadows()`` from ``_shadow_inc.glsl`` computes a shadow factor for
each light into an array. The VRML97 shader uses the same function. Each
factor (0 = fully shadowed, 1 = lit) multiplies that light's contribution in
the loop below. See :doc:`Shadows <shadows>` for how the factors are made.

Direct Lighting, Lobe by Lobe
-----------------------------

The shader loops over the scene lights and adds up diffuse and specular
separately, so a transmissive surface can later replace its diffuse term. For
each light it computes the light direction ``L`` and an attenuation:

- A directional light uses ``-lightDirection`` and no attenuation.
- Point and spot lights use the vector to ``lightPosition``, and
  ``1 / (constant + linear·d + quadratic·d²)`` from ``lightAttenuation``.
  Where a light has a ``lightRange``, the ``KHR_lights_punctual`` range window
  ``clamp(1 - (d/range)⁴, 0, 1)`` also applies.
- A spot light multiplies in a cone falloff (``spotAttenuation``): a linear
  ramp from the outer cutoff to the inner beam, clamped to ``[0, 1]`` and
  squared, as in the ``KHR_lights_punctual`` reference.

The light's colour, intensity, attenuation and shadow factor combine into
``radianceBase``.

The specular lobe: Cook-Torrance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With the half-vector ``H = normalize(L + V)``, the specular reflection is the
product of three functions, all defined in ``_brdf_inc.glsl``:

.. code-block:: glsl

   D   = D_GGX(NdotH, alphaR);
   Vis = V_SmithGGXCorrelated(NdotV, NdotL, alphaR);
   vec3 F = F_Schlick(VdotH, F0, specF90);
   vec3 spec = D * Vis * F;

- ``D_GGX`` -- the microfacet distribution ``a2 / (π ((NdotH²)(a2-1)+1)²)``
  with ``a2 = alphaR²``: the share of microfacets that face the half-vector.
  Low roughness makes this a tight, bright peak.

- ``V_SmithGGXCorrelated`` -- the height-correlated Smith visibility. It
  combines the geometry term *and* the ``1 / (4·NdotL·NdotV)`` denominator,
  so the code multiplies ``D * Vis * F`` with no separate divisor.

- ``F_Schlick`` -- Fresnel: reflectance rising from ``F0`` toward ``specF90``
  at grazing angles.

When the material has ``anisotropyStrength``, the shader uses anisotropic
versions of ``D`` and ``Vis``. They split ``alphaR`` into different values
along and across the anisotropy direction, which stretches the highlight into
a band.

The diffuse lobe: Lambert
~~~~~~~~~~~~~~~~~~~~~~~~~

Light that is neither reflected specularly nor absorbed by metal becomes
diffuse:

.. code-block:: glsl

   vec3 kd = (vec3(1.0) - F) * (1.0 - metallic);
   vec3 diffuse = kd * albedo * INV_PI * (1.0 - diffuseTransFactorEff);

The ``(1 - F)`` factor keeps only the light that the specular term did not
reflect. ``(1 - metallic)`` removes diffuse for metals. ``INV_PI`` is the
Lambertian normalization. The last factor gives part of the diffuse energy to
diffuse transmission (``KHR_materials_diffuse_transmission``). That lobe is
lit by the light arriving at the back of the surface, for thin translucent
materials such as leaves or wax.

The sheen lobe (fabric)
~~~~~~~~~~~~~~~~~~~~~~~

.. rst-class:: technical

When ``sheenColor`` is non-zero, the shader adds a sheen lobe for the soft
glow of cloth at grazing angles: the Charlie distribution ``D_Charlie`` times
the sheen visibility ``V_Sheen``. The sheen is added up separately from the
other specular light. After the ambient terms, the base layer is scaled down
by the sheen's directional albedo, and the sheen is added back on top, lit by
both the direct lights and the environment:

.. code-block:: glsl

   float sr = clamp(sheenRoughEff, 0.0, 1.0);
   float sheenD = D_Charlie(sr, NdotH);
   float sheenVis = V_Sheen(NdotL, NdotV, sr);
   LoSheen += sheenColorEff * sheenD * sheenVis * radianceBase * NdotL;

The clearcoat lobe
~~~~~~~~~~~~~~~~~~

.. rst-class:: technical

When ``clearcoat`` is above 0, the shader computes a second GGX lobe with a
fixed ``F0 = 0.04``, the coat's own roughness (clamped to ``[0.04, 1.0]``) and
the coat normal ``Nc``. The layers beneath are scaled down by the coat's
Fresnel, so the base is darker where the coat reflects:

.. code-block:: glsl

   float ccSpec = ccD * ccVis * ccF * NcdotL;   // coat lobe with its own cosine
   float ccAtt = 1.0 - ccFactorEff * ccF;
   diffuse *= ccAtt;
   spec = spec * ccAtt + vec3(ccSpec * ccFactorEff / max(NdotL, 1e-4));

Finally each light's contribution is multiplied by ``NdotL`` and added to the
running diffuse and specular totals:

.. code-block:: glsl

   vec3 radiance = radianceBase * NdotL;
   LoDiffuse  += diffuse * radiance;
   LoSpecular += spec    * radiance;

Ambient and Environment (Image-Based Lighting)
----------------------------------------------

Direct lights alone would leave shadows black and give metals nothing to
reflect. The ambient term adds light from the surrounding environment. The
shader first rotates the eye-space normal and reflection vector into the
probe's world orientation with ``eyeToWorld``. It then runs one of three paths,
chosen by ``iblMode``.

iblMode 2 -- the prefiltered probe (split-sum)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The full path samples three precomputed textures and combines them with the
split-sum approximation:

.. code-block:: glsl

   vec3 irr = texture(irradianceMap, Nw).rgb * iblIntensity;                                // diffuse
   vec3 pre = textureLod(prefilterMap, Rw, roughness * prefilterMaxLod).rgb * iblIntensity; // specular
   vec2 ab  = texture(brdfLUT, vec2(NdotV, roughness)).rg;                                  // scale, bias
   ambDiffuse  = irr * albedo * (1.0 - metallic) * ao;
   ambSpecular = pre * (F0 * ab.x + specF90 * ab.y) * ao;

- ``irradianceMap`` is a cube holding the environment already convolved over
  a cosine hemisphere. One lookup along the world normal gives the diffuse
  ambient.

- ``prefilterMap`` is a cube with a mip chain, holding the environment blurred
  for each roughness. ``textureLod`` at ``roughness × prefilterMaxLod`` picks
  the matching blur, so a rough surface reflects a soft environment and a
  smooth one a sharp reflection.

- ``brdfLUT`` is a 2D table indexed by ``NdotV`` and roughness. It returns the
  scale and bias that turn the prefiltered colour into the correct specular
  energy for this ``F0``.

.. rst-class:: technical

``passes/ibl.py`` builds these three textures at run time, from the
procedural studio environment (``ibl_env.frag``) or from the panorama of an
``HDRBackground`` in the scene, and builds them again when that panorama
changes. The prefilter and LUT precomputes use the same
``importanceSampleGGX`` and Hammersley sampling in ``_brdf_inc.glsl`` as the
direct path's terms, so the baked probe and the per-pixel shading use one
definition of the BRDF.

iblMode 1 -- analytic environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rst-class:: technical

This path uses no probe, and ``auto`` selects it on software rasterizers.
``envColor()`` gives a sky/ground gradient, divided by ``π`` for the diffuse
irradiance, and ``envBRDFApprox()`` (Karis' analytic fit) supplies the
split-sum scale and bias without a lookup table. It has the same energy and
roughness response as the full path, with a simpler environment.

iblMode 0 -- off
~~~~~~~~~~~~~~~~

.. rst-class:: technical

Diffuse ambient is ``sceneAmbient × albedo``, and there is no specular
reflection.

Baked light and further ambient terms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After the chosen path, the shader adds these to the ambient terms:

- A lightmap, if the material has one. It adds to diffuse ambient and, through
  ``envBRDFApprox``, to specular ambient.
- The light grid sample, if the scene has a grid and the surface has no
  lightmap. Its directional part is shaded by the normal.
- Diffuse transmission, lit by the environment behind the surface.
- Clearcoat, which also reflects the environment: a second prefiltered or
  analytic sample, scaled by the coat's Fresnel, is added on top, and the
  layers beneath are scaled down as in the direct-lighting case.

Transmission (Glass)
--------------------

.. rst-class:: technical

When the material transmits and the pass has captured a backdrop
(``hasTransmissionBackdrop``), light coming *through* the surface replaces the
diffuse term. The view ray is refracted through the surface by the index of
refraction. The exit point is projected to screen space with the shared
``projectionMatrix``, and the captured opaque scene is sampled there. The
backdrop is a copy of the rectangle of the view being drawn, so the view's
clip space covers all of it, in a window of several views as in a window of
one. Roughness selects a blurrier mip level for frosted glass:

.. code-block:: glsl

   vec3 refr    = refract(-V, N, 1.0 / max(ior, 1.0001));
   vec3 exitPos = vPosition + refr * max(thick, 1e-3);
   vec4 clip    = projectionMatrix * vec4(exitPos, 1.0);
   vec2 backUV  = clamp((clip.xy / clip.w) * 0.5 + 0.5, 0.0, 1.0);
   bg = toLinear(textureLod(transmissionTexture, backUV, mip).rgb);

.. rst-class:: technical

``mip`` is ``roughness × clamp(ior·2 − 2, 0, 1) × transmissionMaxLod``, so
low-IOR glass blurs less. With ``dispersion`` above 0, the red, green and blue
channels are refracted with slightly different indices and sampled at their
own exit points, which gives a coloured fringe. The transmitted colour is
tinted by ``albedo`` and, when the material has a volume
(``attenuationDistance > 0``), by Beer-Lambert absorption over the thickness.
It is weighted by the light the specular reflection did not take, then mixed
into the diffuse term by the transmission factor. The specular reflection
stays on top, so glass still shows a highlight. The backdrop is the opaque
scene, copied into a mipmapped texture between the opaque and transmissive
steps; see :ref:`the frame sequence <frame-sequence>`.

Producing the Final Fragment
----------------------------

The three contributions are added up, then exposure, fog, tone mapping and
encoding are applied:

.. code-block:: glsl

   vec3 color = diffuseTerm + specularTerm + emissive;
   color *= exposure;
   // ... fog, blended in linear HDR ...
   if (!hdrOutput) {
       color = acesToneMap(color);   // filmic curve: keeps highlight saturation
       color = linearToSRGB(color);  // encode for a non-sRGB framebuffer
   }
   fragColor    = vec4(color, alpha);
   fragObjectId = encodeObjectId(effectiveObjectId());

- All shading up to this point is in linear light. ``exposure`` scales scenes
  lit in absolute units, such as ``KHR_lights_punctual`` lights in candela or
  lux.

- :ref:`Fog <fog>` is blended in before tone mapping.

- The ACES filmic curve compresses the high dynamic range into displayable
  values while keeping colours saturated; a gold highlight stays gold instead
  of turning white or grey.

- ``linearToSRGB`` applies the sRGB transfer function in the shader, because
  the framebuffer's own sRGB encoding is off (see :ref:`srgb-output`).

- While bloom is on (``hdrOutput``), the shader skips tone mapping and
  encoding and writes linear HDR colour; the bloom composite applies them
  afterwards.

- The shader writes two render targets: the shaded colour to attachment 0,
  and the packed object id to attachment 1 for mouse picking.
  ``encodeObjectId`` spreads a 32-bit id across RGBA8.

One Shader for the Whole Scene
------------------------------

.. rst-class:: technical

A separate shader per material would mean switching programs, and setting
their uniforms again, many times per frame, and that CPU work grows with the
number of materials. This renderer uses one program. A material is a uniform
buffer switched with one bind. Clearcoat, sheen and transmission are branches
on uniforms that have the same value for a whole draw call, so every fragment
in the draw takes the same branch, which costs little on desktop GPUs. Every
draw still pays for the registers and uniforms of the optional lobes, even
when a material uses none of them. On a weak GPU this can lower occupancy, so
the three lobes are also behind the compile-time defines ``USE_CLEARCOAT``,
``USE_SHEEN`` and ``USE_TRANSMISSION``, all on by default. A constrained
platform can compile one smaller program without some lobes, for the whole
scene. The choice is made per platform, never per material; the scene always
binds exactly one program.
