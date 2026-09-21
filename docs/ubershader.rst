PBR Uber-Shader
===============

.. rst-class:: introduction

This is a walkthrough of the PBR fragment shader (``shaders/pbr.frag``) as it
actually runs: what data reaches it, what it reads from each texture, uniform
and buffer, how each material lobe is computed and sampled, and how they
combine into the final colour of one fragment. It assumes you have read
:doc:`Physically Based Rendering <pbr>` for the concepts; here we ground those
concepts in the real code. Theory is included where it helps, but always tied
to the line that does it.

.. rst-class:: technical

The shader is one *program* used for the whole scene -- a single "uber-shader"
-- but it is not one file. ``shaders/pbr.frag`` is the top level; at compile
time its ``#include`` directives splice in the shared files
``_common_inc.glsl`` (sRGB + PI), ``_brdf_inc.glsl`` (the BRDF terms),
``_lights_inc.glsl`` (the light uniforms) and ``_shadow_inc.glsl``
(:doc:`shadows <shadows>`), and per-driver ``#define``\ s are injected, before
it is compiled once. The vertex stage is ``shaders/pbr.vert``.
Those includes are shared with other shaders -- ``_brdf_inc.glsl``, for
instance, is also compiled into the IBL precompute shaders -- so there is one
definition of the BRDF rather than several that could drift apart. (How the
assembly works is described in :doc:`Core-Profile Rendering <renderpasses>`.)
Optional lobes (clearcoat, sheen, transmission) are branches on uniforms that
are constant for a draw call, so a GPU takes them coherently.

What Reaches the Shader
-----------------------

Before the fragment shader runs a single line, the pass has set up five kinds
of input. Knowing them makes the rest of the walkthrough concrete.

1. Per-vertex data (from the vertex shader)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``pbr.vert`` transforms each vertex into eye space and passes these varyings
to the fragment stage:

- ``vPosition`` -- eye-space position (used for the view vector, distance
  attenuation and the transmission projection).

- ``vNormal`` -- eye-space normal (via the ``normalMatrix``, the
  inverse-transpose of the modelview upper 3×3).

- ``vTangent``, ``vTangentW`` -- eye-space tangent and its handedness, for
  building the normal-map frame. The tangent transforms by the plain modelview
  3×3, not the normal matrix; with no tangent attribute it is emitted as zero so
  the fragment shader can detect its absence.

- ``vTexCoord`` -- the first UV set (``TEXCOORD_0``).

- ``vColor`` -- per-vertex colour (glTF ``COLOR_0``).

The vertex attributes arrive at fixed locations: 0 = texcoord, 1 = normal, 2 =
position, 3 = tangent, 4 = colour.

2. The material, as a std140 uniform buffer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Everything constant about a material for the frame is packed into one uniform
buffer object, ``MaterialBlock``, and bound with a single call per shape. That
is what keeps a heavy glTF scene off the CPU: the same data sent field by
field is around twenty ``glUniform`` calls per shape, and a scene with
hundreds of shapes spends its frame in them. Its members -- read directly by
name in the shader -- are:

.. code-block:: python

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
   mat3  uvTransform;

The byte layout matches the Python packer (``pbrpass.pack_material_block``);
the buffer is built once per material and reused across frames.

3. Texture maps (samplers on fixed units)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each map is a sampler with a companion ``has…`` flag, so a material can omit
any of them. The pass assigns fixed texture units so the samplers and
shadow/IBL textures never collide within the 16-unit fragment budget:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Sampler
     - Unit
     - Read as
   * - ``baseColorTexture``
     - 1
     - sRGB colour (decoded to linear)
   * - ``metallicRoughnessTexture``
     - 2
     - linear; green = roughness, blue = metalness
   * - ``normalTexture``
     - 3
     - linear tangent-space normal
   * - ``occlusionTexture``
     - 10
     - linear; red channel
   * - ``emissiveTexture``
     - 11
     - sRGB (decoded to linear)
   * - ``transmissionTexture``
     - 12
     - the captured opaque backdrop (mipmapped)
   * - ``irradianceMap`` / ``prefilterMap`` / ``brdfLUT``
     - 13 / 14 / 15
     - the IBL probe (see below)
   * - shadow samplers
     - 4-6
     - see :doc:`Shadows <shadows>`

4. Scene lighting (plain uniforms)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

From ``_lights_inc.glsl``: ``numLights`` and, per light, ``lightType``,
``lightColor``, ``lightPosition``, ``lightDirection``, ``lightAttenuation``,
``lightBeamWidth``/``lightCutOffAngle`` (spot cone) and ``lightIntensity``,
plus a flat ``sceneAmbient``. All are in eye space, matching the varyings.

5. Environment and frame state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``iblMode`` and ``iblIntensity`` select and scale the environment lighting;
``eyeToWorld`` rotates eye-space vectors into the world orientation of the
probe cubes; ``projectionMatrix`` is reused for the transmission projection;
``alphaMode``/``alphaValue`` and the ``transmission…`` uniforms come from the
render mode, not the material. ``objectId`` is the pickable id for the
selection buffer.

The Fragment Shader, Top to Bottom
----------------------------------

Here is ``main()`` in order, with what each step reads and produces.

Sampling the material
~~~~~~~~~~~~~~~~~~~~~

The UV is transformed once by ``uvTransform`` (``KHR_texture_transform``).
Base colour is sampled and, because it is an sRGB texture, decoded to linear;
the material's ``baseColorFactor`` and any per-vertex colour multiply in.
Alpha is assembled the same way, and in ``MASK`` mode a fragment below
``alphaCutoff`` is ``discard``\ ed. An ``unlitMode`` material returns the base
colour immediately, skipping all lighting.

Metalness and roughness start from their factors and are multiplied by the
blue and green channels of the metallic-roughness texture. Roughness is
clamped to ``[0.04, 1.0]``, then squared into the value the BRDF actually
uses:

.. code-block:: python

   float alphaR = roughness * roughness;   // glTF GGX uses alpha = roughness^2

.. rst-class:: technical

This squaring happens exactly once. The perceptual ``roughness`` is kept
separately for indexing the environment map LOD and the BRDF lookup; the
microfacet functions all take ``alphaR``. Keeping the two straight -- and
identical between the direct and image-based paths -- is what stops a material
looking subtly wrong.

Occlusion (red channel, scaled by ``occlusionStrength``) and emissive
(``emissiveFactor × emissiveStrength``, times the decoded emissive texel) are
read next.

Building the shading normal
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The interpolated normal is normalized and flipped on back faces
(``!gl_FrontFacing``) so two-sided surfaces light correctly. If a normal map
and a valid tangent are present, a tangent-basis (TBN) matrix is built and the
sampled normal (remapped from ``[0,1]`` to ``[-1,1]``, scaled by
``normalScale``) is rotated into eye space:

.. code-block:: bash

   vec3 T = normalize(vTangent - N * dot(N, vTangent));
   vec3 B = cross(N, T) * (vTangentW == 0.0 ? 1.0 : vTangentW);
   vec3 nTex = texture(normalTexture, uv).xyz * 2.0 - 1.0;
   nTex.xy *= normalScale;
   N = normalize(mat3(T, B, N) * nTex);

The view vector ``V`` is ``normalize(-vPosition)`` (the camera is at the
origin in eye space), and ``NdotV`` is clamped away from zero.

The reflectance at normal incidence (F0)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

How reflective a surface is head-on is ``F0``. For non-metals it comes from
the index of refraction (with the ``KHR_materials_specular`` tint and weight);
for metals it is the base colour. Metalness blends between them:

.. code-block:: python

   float iorF0 = pow((ior - 1.0) / (ior + 1.0), 2.0);
   vec3 dielF0 = min(iorF0 * specularColorFactor * specularFactor, vec3(1.0));
   vec3 F0 = mix(dielF0, albedo, metallic);

This single value is why metalness changes a surface so completely: at
``metallic = 1`` the reflection takes the base colour and the diffuse term
(below) is switched off.

Shadows
~~~~~~~

Per-light shadow factors are resolved once into an array by
``resolveShadows()`` from ``_shadow_inc.glsl``, shared verbatim with the
VRML97 shader. Each factor (0 = fully shadowed, 1 = lit) multiplies that
light's contribution in the loop below. The mechanism is covered in
:doc:`Shadows <shadows>`.

Direct Lighting, Lobe by Lobe
-----------------------------

The shader loops over the scene lights, accumulating diffuse and specular
separately (kept apart so a transmissive surface can later swap out its
diffuse term). For each light it computes the light direction ``L`` and an
attenuation: directional lights use ``-lightDirection``; point and spot lights
use the vector to ``lightPosition`` with the constant/linear/quadratic
``lightAttenuation``, and spot lights multiply in a smooth cone falloff
(``spotAttenuation``, a ``smoothstep`` between the outer cutoff and inner
beam).

The specular lobe: Cook-Torrance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With the half-vector ``H = normalize(L + V)``, the specular reflection is the
product of three functions (all defined in ``_brdf_inc.glsl``):

.. code-block:: python

   float D   = D_GGX(NdotH, alphaR);
   float Vis = V_SmithGGXCorrelated(NdotV, NdotL, alphaR);
   vec3  F   = F_Schlick(VdotH, F0);
   vec3  spec = D * Vis * F;

- **D_GGX** -- the microfacet distribution ``a2 / (π ((NdotH²)(a2-1)+1)²)`` with
  ``a2 = alphaR²``: how many microfacets point toward the half-vector. Low
  roughness makes this a tight, bright spike.

- **V_SmithGGXCorrelated** -- the height-correlated Smith visibility. It is the
  geometry term *and* the ``1 / (4·NdotL·NdotV)`` denominator folded into one
  function, which is why the code multiplies ``D * Vis * F`` with no separate
  divisor.

- **F_Schlick** -- Fresnel: reflectance rising from ``F0`` toward 1 at grazing
  angles.

The diffuse lobe: Lambert
~~~~~~~~~~~~~~~~~~~~~~~~~

Energy not reflected specularly and not absorbed by metal is diffuse:

.. code-block:: python

   vec3 kd = (vec3(1.0) - F) * (1.0 - metallic);
   vec3 diffuse = kd * albedo * INV_PI;

The ``(1 - F)`` factor takes only the light the specular term did not reflect;
``(1 - metallic)`` removes diffuse for metals; ``INV_PI`` is the Lambertian
normalization.

The sheen lobe (fabric)
~~~~~~~~~~~~~~~~~~~~~~~

.. rst-class:: technical

When ``sheenColorFactor`` is non-zero, a Charlie distribution term is added to
the specular for the soft grazing-angle glow of cloth. It is applied to the
direct lobes only (not the ambient path), which is adequate for fabric demos:

.. code-block:: python

   float sr = clamp(sheenRoughnessFactor, 0.07, 1.0);
   float sheenD = (2.0 + 1.0/(sr*sr)) * pow(max(1.0 - NdotH*NdotH, 0.0), 0.5/(sr*sr)) / (2.0*PI);
   spec += sheenColorFactor * sheenD;

The clearcoat lobe
~~~~~~~~~~~~~~~~~~

.. rst-class:: technical

When ``clearcoatFactor > 0``, a second smooth GGX lobe (fixed ``F0 = 0.04``,
its own roughness) is computed and the layers beneath are attenuated by the
clearcoat's Fresnel, so the base darkens where the coat reflects:

.. code-block:: python

   float ccAlpha = clearcoatRoughness * clearcoatRoughness;
   float ccSpec = D_GGX(NdotH, ccAlpha) * V_SmithGGXCorrelated(NdotV, NdotL, ccAlpha) * F_Schlick(VdotH, 0.04);
   float ccAtt = 1.0 - clearcoatFactor * F_Schlick(VdotH, 0.04);
   diffuse *= ccAtt;
   spec = spec * ccAtt + vec3(ccSpec * clearcoatFactor);

Each light's contribution is finally scaled by its colour, intensity, distance
attenuation, ``NdotL`` and its shadow factor, and added to the running diffuse
and specular totals:

.. code-block:: python

   vec3 radiance = lightColor[i] * lightIntensity[i] * atten * NdotL * lightShadow[i];
   LoDiffuse  += diffuse * radiance;
   LoSpecular += spec    * radiance;

Ambient and Environment (Image-Based Lighting)
----------------------------------------------

Direct lights alone leave shadows pitch black and metals with nothing to
reflect. The ambient term supplies light from the surrounding environment. The
material's eye-space normal and reflection vector are first rotated into the
probe's world orientation with ``eyeToWorld``, then one of three paths runs
depending on ``iblMode``.

iblMode 2 -- the prefiltered probe (split-sum)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The full path samples three precomputed textures and combines them by the
split-sum approximation:

.. code-block:: python

   vec3 irr = texture(irradianceMap, Nw).rgb * iblIntensity;                       // diffuse
   vec3 pre = textureLod(prefilterMap, Rw, roughness * prefilterMaxLod).rgb * iblIntensity; // specular
   vec2 ab  = texture(brdfLUT, vec2(NdotV, roughness)).rg;                          // scale, bias
   ambDiffuse  = irr * albedo * (1.0 - metallic) * ao;
   ambSpecular = pre * (F0 * ab.x + ab.y) * ao;

- ``irradianceMap`` (a cube) holds the environment already convolved over a
  cosine hemisphere, so one lookup along the world normal gives the whole
  diffuse ambient.

- ``prefilterMap`` (a cube with a mip chain) holds the environment pre-blurred
  per roughness; ``textureLod`` at ``roughness × prefilterMaxLod`` picks the
  right blur, so a rough surface reflects a soft environment and a smooth one a
  sharp reflection.

- ``brdfLUT`` (a 2D table indexed by ``NdotV`` and roughness) returns the scale
  and bias that turn the prefiltered colour into the correct specular energy for
  this ``F0``.

.. rst-class:: technical

These three textures are built once, offline, by ``passes/ibl.py`` from a
procedural studio environment (``ibl_env.frag``). The prefilter and LUT
precomputes use the very same ``importanceSampleGGX`` / Hammersley machinery
in ``_brdf_inc.glsl`` that the direct path's terms come from, so the baked
probe and the real-time shading share one definition of the BRDF and cannot
drift apart.

iblMode 1 -- analytic environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. rst-class:: technical

A fallback (used on software rasterizers) with no probe: ``envColor()`` gives
a cheap sky/ground gradient, divided by ``π`` for the diffuse irradiance, and
``envBRDFApprox()`` (Karis' analytic fit) supplies the split-sum scale/bias
without a LUT. It has the right energy and roughness response, just from a
simpler environment.

iblMode 0 -- off
~~~~~~~~~~~~~~~~

.. rst-class:: technical

Flat ``sceneAmbient × albedo`` for diffuse and no specular reflection.

When clearcoat is active it also reflects the environment: a second
prefiltered/analytic sample scaled by the coat's Fresnel is added on top, and
the layers beneath are attenuated, mirroring the direct-lighting case.

Transmission (Glass)
--------------------

.. rst-class:: technical

If the material transmits and the pass has captured a backdrop
(``hasTransmissionBackdrop``), the diffuse term is replaced by light coming
*through* the surface. The view is refracted through the surface by the index
of refraction, the exit point is projected to screen space with the shared
``projectionMatrix``, and the captured opaque scene is sampled there --
roughness choosing a blurrier mip for frosted glass:

.. code-block:: python

   vec3 refr    = refract(-V, N, 1.0 / max(ior, 1.0001));
   vec3 exitPos = vPosition + refr * max(thicknessFactor, 1e-3);
   vec4 clip    = projectionMatrix * vec4(exitPos, 1.0);
   vec2 backUV  = clamp((clip.xy / clip.w) * 0.5 + 0.5, 0.0, 1.0);
   vec3 bg      = toLinear(textureLod(transmissionTexture, backUV, roughness * transmissionMaxLod).rgb);

.. rst-class:: technical

The transmitted colour is tinted by ``albedo`` and, if the material has volume
(``attenuationDistance > 0``), by Beer-Lambert absorption over
``thicknessFactor``. It is mixed into the diffuse term by
``transmissionFactor``; the specular reflection stays on top, so glass still
shows a highlight. The backdrop itself is the opaque scene copied into a
mipmapped texture between the opaque and transmissive passes -- see :doc:`the
pass sequence <renderpasses>`.

Producing the Final Fragment
----------------------------

The three contributions are summed, tone-mapped and encoded:

.. code-block:: python

   vec3 color = diffuseTerm + specularTerm + emissive;
   color = acesToneMap(color);       // filmic curve: keeps highlight saturation
   color = linearToSRGB(color);      // encode for a non-sRGB framebuffer
   fragColor    = vec4(color, alpha);
   fragObjectId = encodeObjectId(objectId);

- All shading up to this point is in **linear** light. The ACES filmic curve
  compresses the high dynamic range into displayable values while keeping
  saturated colours (a gold highlight stays gold rather than going white/grey).

- ``linearToSRGB`` applies the sRGB transfer function in the shader, because the
  framebuffer's own sRGB encoding is deliberately left off (turning it on would
  double-encode). See the one-time setup in :doc:`Core-Profile Rendering
  <renderpasses>`.

- The shader writes two render targets: the shaded colour to attachment 0, and
  the packed object id to attachment 1 for mouse picking (``encodeObjectId``
  spreads a 32-bit id across RGBA8).

Why One Shader for the Whole Scene
----------------------------------

.. rst-class:: technical

Compiling a different shader per material means switching programs (and
re-validating uniforms) many times per frame -- CPU work that dominates a
naive renderer. Instead this is a single program: the material is a uniform
buffer swapped with one bind, and clearcoat/sheen/transmission are branches on
uniforms that hold the same value across a draw call, so every fragment in the
draw takes the same path (a coherent branch, nearly free on desktop GPUs). The
one cost is the register/uniform footprint every draw pays even when a
material uses no optional lobe. On a weak GPU tier that can hurt occupancy, so
the three lobes are also behind compile-time ``USE_CLEARCOAT`` / ``USE_SHEEN``
/ ``USE_TRANSMISSION`` defines: a constrained platform can compile one leaner
program with some lobes dropped for the entire scene. That is a per-platform
build choice, never a per-material shader swap -- the scene always binds
exactly one program.
