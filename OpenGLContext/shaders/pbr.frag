#version 330 core
// Desktop OpenGL 3.3 only, by design (finding 5.3): no GLSL-ES / WebGL profile.

// Physically-based (metallic/roughness) fragment shader, glTF 2.0 aligned.
// Cook-Torrance BRDF over the shared OpenGLContext light uniforms, with the same
// shadow-mapping subsystem as the VRML97 shader.
//
// This is a single "uber" shader: clearcoat / sheen / transmission are selected
// by uniform-valued branches (coherent across a draw, so cheap on desktop GPUs),
// not per-fragment divergence. Its one real cost is the register/uniform
// footprint every draw pays even when the material uses none of those features.
// On a weak tier (integrated Intel) that hurts occupancy; the escape hatch is the
// USE_CLEARCOAT / USE_SHEEN / USE_TRANSMISSION defines below. These are a FUTURE
// per-platform / per-settings knob (pbrpass.pbr_feature_defines): a constrained
// profile can compile ONE leaner program with some lobes dropped for the whole
// scene -- it is NOT a per-material permutation and never swaps shaders per draw.
// They default ON, so the shipped program (and a standalone compile) is complete.

#define MAX_LIGHTS 8
// MAX_SHADOW_LIGHTS is injected at compile time (derived from the driver's real
// GL_MAX_TEXTURE_IMAGE_UNITS); a default keeps standalone compiles valid.
#ifndef MAX_SHADOW_LIGHTS
#define MAX_SHADOW_LIGHTS 4
#endif
#define MAX_CASCADES 4

#ifndef USE_CLEARCOAT
#define USE_CLEARCOAT 1
#endif
#ifndef USE_SHEEN
#define USE_SHEEN 1
#endif
#ifndef USE_TRANSMISSION
#define USE_TRANSMISSION 1
#endif

// Sampler-budget gate: extension material textures (transmission / iridescence
// thickness) occupy units 16+, past the GL 3.3 16-unit minimum. pbrpass sets this
// to 1 only on a GPU that reports enough samplers; 0 (default) compiles them out so
// the program still fits 16 units on min-spec hardware / llvmpipe.
#ifndef PBR_EXT_TEXTURES
#define PBR_EXT_TEXTURES 0
#endif

// Light/shadow enums, the scene light-uniform block, and encodeObjectId().
#include "_lights_inc.glsl"
// PI / INV_PI + piecewise sRGB transfer functions.
#include "_common_inc.glsl"
// Shared Cook-Torrance BRDF (D_GGX, F_Schlick, Smith visibility) and GGX
// importance sampling -- one definition shared with the IBL precomputes so the
// analytic and image-based paths cannot drift apart.
#include "_brdf_inc.glsl"

in vec3 vNormal;
in vec3 vPosition;
in vec2 vTexCoord;
in vec2 vTexCoord1;      // second UV set (glTF TEXCOORD_1)
in vec3 vTangent;
in float vTangentW;
in vec4 vColor;
in float vModelScale;   // world-space object scale for KHR_materials_volume thickness

uniform bool hasVertexColor;        // glTF COLOR_0 present

// Per-material factors that are constant for a whole frame live in a std140
// uniform block, uploaded once per material and switched with a single buffer
// bind per shape instead of ~20 glUniform calls (per-shape uniform churn
// dominated heavy glTF scenes). The block is an ARRAY of materials so an
// instanced draw can give each instance its own factors (colour/metallic/...)
// while sharing one program and one draw call; the per-instance material index
// selects the element. The non-instanced path uses element 0. The std140 layout
// of one element must match pack_material_block in pbrpass.py (224 bytes / 56 words).
struct Material {
    vec3  baseColorFactor;      float metallicFactor;
    vec3  emissiveFactor;       float roughnessFactor;
    vec3  specularColorFactor;  float occlusionStrength;   // KHR_materials_specular color
    vec3  sheenColorFactor;     float normalScale;         // KHR_materials_sheen color
    vec3  attenuationColor;     float alphaCutoff;         // KHR_materials_volume color
    float emissiveStrength;     float specularFactor;      // KHR_materials_emissive_strength / _specular
    float clearcoatFactor;      float clearcoatRoughness;  // KHR_materials_clearcoat
    float sheenRoughnessFactor; float ior;                 // KHR_materials_sheen / _ior
    float thicknessFactor;      float attenuationDistance; // KHR_materials_volume
    bool  unlitMode;                                       // KHR_materials_unlit
    int   texCoordMask;    // per-channel UV-set bit (1=base 2=MR 4=normal 8=occ 16=emis)
    float anisotropyStrengthM; // KHR_materials_anisotropy (fill the pre-mat3 pad slots)
    float dispersionM;         // KHR_materials_dispersion
    mat3  uvTransform;                                     // KHR_texture_transform
    vec4  iridescence;     // KHR_materials_iridescence: factor, ior, thicknessMin, thicknessMax
    vec4  diffuseTransmissionM; // KHR_materials_diffuse_transmission: rgb colour, a factor
    vec4  anisotropyDirM;       // KHR_materials_anisotropy direction: xy = (cos, sin)
};
// These per-material factors MUST live in the UBO (not loose uniforms) so that an
// INSTANCED draw -- which packs one material per instance and selects by index --
// gives each instance its own value. Loose uniforms are set once per draw, so the
// whole batch shared one value (anisotropy/dispersion/diffuse-transmission test
// GRIDS all rendered with a single material's factor). See pack_material_block.

// Sized to fit the guaranteed 16 KB UBO minimum (73 * 224 B = 16352 B); groups
// with more distinct materials are chunked into several draws (pbrpass.py).
#ifndef MAX_INSTANCE_MATERIALS
#define MAX_INSTANCE_MATERIALS 73
#endif

layout(std140) uniform MaterialBlock {
    Material materials[MAX_INSTANCE_MATERIALS];
};

flat in uint vMaterialIndex;   // per-instance material index (0 when not instancing)
// The active material is copied ONCE from the UBO into this global at the top of
// main(), so the ~20 factor reads below hit a register copy rather than repeating
// a (dynamically-indexed) UBO fetch per access -- the latter measurably slowed the
// fragment shader for ordinary (non-instanced) rendering.
Material _M;

// The shader body uses the bare factor names; map each to the fetched material.
#define baseColorFactor      _M.baseColorFactor
#define metallicFactor       _M.metallicFactor
#define emissiveFactor       _M.emissiveFactor
#define roughnessFactor      _M.roughnessFactor
#define specularColorFactor  _M.specularColorFactor
#define occlusionStrength    _M.occlusionStrength
#define sheenColorFactor     _M.sheenColorFactor
#define normalScale          _M.normalScale
#define attenuationColor     _M.attenuationColor
#define alphaCutoff          _M.alphaCutoff
#define emissiveStrength     _M.emissiveStrength
#define specularFactor       _M.specularFactor
#define clearcoatFactor      _M.clearcoatFactor
#define clearcoatRoughness   _M.clearcoatRoughness
#define sheenRoughnessFactor _M.sheenRoughnessFactor
#define ior                  _M.ior
#define thicknessFactor      _M.thicknessFactor
#define attenuationDistance  _M.attenuationDistance
#define unlitMode            _M.unlitMode
#define texCoordMask         _M.texCoordMask
#define uvTransform          _M.uvTransform
#define iridescenceFactor    _M.iridescence.x
#define iridescenceIor       _M.iridescence.y
#define iridescenceThickMin  _M.iridescence.z
#define iridescenceThickMax  _M.iridescence.w
#define anisotropyStrength   _M.anisotropyStrengthM
#define dispersion           _M.dispersionM
#define anisotropyDirection  _M.anisotropyDirM.xy
#define diffuseTransmissionColor   _M.diffuseTransmissionM.rgb
#define diffuseTransmissionFactor  _M.diffuseTransmissionM.a

// Per-channel UV: pick TEXCOORD_1 when this channel's low mask bit is set, then
// apply the KHR_texture_transform matrix only if this channel's *transform* bit
// (the same bit << 8) is set -- KHR_texture_transform is per-texture, so a material
// may transform e.g. only its emissive map. `bit`: 1=baseColor 2=metallicRoughness
// 4=normal 8=occlusion 16=emissive 32=lightmap.
vec2 uvFor(int bit) {
    vec2 base = ((texCoordMask & bit) != 0) ? vTexCoord1 : vTexCoord;
    if ((texCoordMask & (bit << 8)) != 0)
        base = (uvTransform * vec3(base, 1.0)).xy;
    return base;
}

// --- KHR_materials_iridescence (thin-film interference) ---------------------
// Port of the Khronos reference (glTF-Sample-Viewer): a soap-bubble/oil-slick
// Fresnel whose hue shifts with view angle and film thickness. Replaces the base
// F0 by the iridescence factor.
const mat3 XYZ_TO_REC709 = mat3(
     3.2404542, -0.9692660,  0.0556434,
    -1.5371385,  1.8760108, -0.2040259,
    -0.4985314,  0.0415560,  1.0572252);

float irF0FromIor(float t, float i) { return pow((t - i) / (t + i), 2.0); }
vec3  irF0FromIor(vec3 t, float i)  { return pow((t - i) / (t + i), vec3(2.0)); }
vec3  irIorFromF0(vec3 f) { vec3 s = sqrt(f); return (1.0 + s) / (1.0 - s); }
float irSchlick(float f0, float vh) { return f0 + (1.0 - f0) * pow(1.0 - vh, 5.0); }
vec3  irSchlick(vec3 f0, float vh)  { return f0 + (1.0 - f0) * pow(1.0 - vh, 5.0); }

// Per-channel phase shift is a vec3: XYZ_TO_REC709 mixes all three XYZ channels
// into each output, so the shift must be applied per XYZ channel in ONE call, not
// three scalar calls each keeping a single output channel (which drops the cross
// terms whenever the phase differs across R/G/B -- e.g. a coloured iridescent base).
vec3 irSensitivity(float opd, vec3 shift) {
    float phase = 2.0 * PI * opd * 1.0e-9;
    vec3 val = vec3(5.4856e-13, 4.4201e-13, 5.2481e-13);
    vec3 pos = vec3(1.6810e+06, 1.7953e+06, 2.2084e+06);
    vec3 var = vec3(4.3278e+09, 9.3046e+09, 6.6121e+09);
    vec3 xyz = val * sqrt(2.0 * PI * var) * cos(pos * phase + shift) * exp(-var * phase * phase);
    xyz.x += 9.7470e-14 * sqrt(2.0 * PI * 4.5282e+09) * cos(2.2399e+06 * phase + shift.x) * exp(-4.5282e+09 * phase * phase);
    xyz /= 1.0685e-7;
    return XYZ_TO_REC709 * xyz;
}

// Undo a Schlick Fresnel evaluated at cosTheta, recovering F0 (f90 assumed 1).
// Used so an iridescent reflectance (already angular) can be stored as an F0 the
// BRDF's own Schlick then reproduces, rather than double-applying the angle.
vec3 schlickToF0(vec3 f, float cosTheta) {
    float x = clamp(1.0 - cosTheta, 0.0, 1.0);
    float x5 = clamp(pow(x, 5.0), 0.0, 0.9999);
    return (f - vec3(x5)) / (1.0 - x5);
}

vec3 evalIridescence(float outsideIor, float eta2, float cosTheta1, float thickness, vec3 baseF0) {
    float filmIor = mix(outsideIor, eta2, smoothstep(0.0, 0.03, thickness));
    float sinTheta2Sq = pow(outsideIor / filmIor, 2.0) * (1.0 - cosTheta1 * cosTheta1);
    float cosTheta2Sq = 1.0 - sinTheta2Sq;
    if (cosTheta2Sq < 0.0) return vec3(1.0);
    float cosTheta2 = sqrt(cosTheta2Sq);

    float R0 = irF0FromIor(filmIor, outsideIor);
    float R12 = irSchlick(R0, cosTheta1);
    float T121 = 1.0 - R12;
    float phi12 = filmIor < outsideIor ? PI : 0.0;
    float phi21 = PI - phi12;

    vec3 baseIor = irIorFromF0(clamp(baseF0, 0.0, 0.9999));
    vec3 R1 = irF0FromIor(baseIor, filmIor);
    vec3 R23 = irSchlick(R1, cosTheta2);
    vec3 phi23 = vec3(
        baseIor.x < filmIor ? PI : 0.0,
        baseIor.y < filmIor ? PI : 0.0,
        baseIor.z < filmIor ? PI : 0.0);

    float opd = 2.0 * filmIor * thickness * cosTheta2;
    vec3 phi = vec3(phi21) + phi23;

    vec3 R123 = clamp(vec3(R12) * R23, 1e-5, 0.9999);
    vec3 r123 = sqrt(R123);
    vec3 Rs = (T121 * T121) * R23 / (vec3(1.0) - R123);

    vec3 I = vec3(R12) + Rs;
    vec3 Cm = Rs - vec3(T121);
    for (int m = 1; m <= 2; m++) {
        Cm *= r123;
        vec3 Sm = 2.0 * irSensitivity(float(m) * opd, float(m) * phi);
        I += Cm * Sm;
    }
    return max(I, vec3(0.0));
}

// Frame/pass-dependent, kept as plain uniforms (cheap, and driven by the render
// mode rather than the material): opacity and the transmission gate.
uniform float alphaValue;          // 1 - transparency (blend/transmission adjusts)
uniform int alphaMode;             // 0=OPAQUE 1=MASK 2=BLEND
// When true (bloom pass), emit LINEAR HDR: the tone map + sRGB encode move to the
// bloom composite, so >1 emissive survives to bloom. Default false = tone-map here.
uniform bool hdrOutput;

// KHR_materials_transmission backdrop. The backdrop is the opaque scene captured
// to a mipmapped colour texture; transmissive fragments sample it at the refracted
// screen position (roughness selects the mip -> frosted glass).
uniform float transmissionFactor;
uniform bool  hasTransmissionBackdrop;
uniform sampler2D transmissionTexture; // opaque backdrop (mipmapped)
uniform float transmissionMaxLod;      // highest mip level of the backdrop


#if PBR_EXT_TEXTURES
// KHR extension material textures (only compiled in when the sampler budget fits).
uniform sampler2D transmissionMap;          uniform bool hasTransmissionMap;         // .r scales transmissionFactor
uniform sampler2D iridescenceThicknessMap;  uniform bool hasIridescenceThicknessMap; // .g -> thickness min..max
uniform sampler2D thicknessMap;             uniform bool hasThicknessMap;            // .g scales volume thickness
uniform sampler2D clearcoatMap;             uniform bool hasClearcoatMap;            // .r scales clearcoatFactor
uniform sampler2D clearcoatRoughnessMap;    uniform bool hasClearcoatRoughnessMap;   // .g scales clearcoatRoughness
uniform sampler2D anisotropyMap;            uniform bool hasAnisotropyMap;           // .rg direction, .b strength
uniform sampler2D specularMap;              uniform bool hasSpecularMap;             // .a scales specularFactor
uniform sampler2D specularColorMap;         uniform bool hasSpecularColorMap;        // .rgb tints specularColor (sRGB)
uniform sampler2D sheenColorMap;            uniform bool hasSheenColorMap;           // .rgb sheen colour (sRGB)
uniform sampler2D sheenRoughnessMap;        uniform bool hasSheenRoughnessMap;       // .a sheen roughness
uniform sampler2D iridescenceMap;           uniform bool hasIridescenceMap;          // .r scales iridescence factor
uniform sampler2D clearcoatNormalMap;       uniform bool hasClearcoatNormalMap;      // tangent-space coat normal
uniform sampler2D diffuseTransmissionColorMap; uniform bool hasDiffuseTransmissionColorMap; // .rgb transmitted colour (sRGB)
uniform sampler2D diffuseTransmissionMap;   uniform bool hasDiffuseTransmissionMap;  // .a scales transmission factor
#endif
uniform mat4  projectionMatrix;        // shared with the vertex stage

// PBR texture maps + presence flags
uniform sampler2D baseColorTexture;          uniform bool hasBaseColor;
uniform sampler2D metallicRoughnessTexture;  uniform bool hasMetallicRoughness;
uniform sampler2D normalTexture;             uniform bool hasNormal;
uniform sampler2D occlusionTexture;          uniform bool hasOcclusion;
uniform sampler2D emissiveTexture;           uniform bool hasEmissive;
// Baked static irradiance (the BSP/Quake lightmap workflow): the map compiler
// solved the static lights offline into a texture on a second UV set. Treated as
// an extra ambient irradiance source, so normal mapping, IBL reflection and
// dynamic lights still apply on top of it.
uniform sampler2D lightmapTexture;           uniform bool hasLightmap;
uniform float lightmapStrength;              // exposure of the baked levels

// Environment / image-based lighting. iblMode: 0=off (flat ambient), 1=analytic
// (procedural env + analytic split-sum BRDF), 2=full (prefiltered probe + LUT).
// The probe cubes are world-oriented, sampled via eyeToWorld (declared below).
uniform int iblMode;
uniform float iblIntensity;
uniform samplerCube irradianceMap;   // diffuse irradiance (full)
uniform samplerCube prefilterMap;    // roughness-mip prefiltered specular (full)
uniform sampler2D brdfLUT;           // split-sum (scale, bias) integration (full)
uniform float prefilterMaxLod;       // highest mip level of prefilterMap

uniform mat4 eyeToWorld;

uniform float exposure;           // camera exposure multiplier (default 1.0)

// Fog: aerial perspective over terrain, or a VRML97 Fog node the camera is
// standing inside.  fogMode 0 (default) disables it, so a scene with no fog in
// it is unaffected.  See OpenGLContext/scenegraph/fog.py for the modes.
uniform int fogMode;              // 0 off, 1 density, 2 VRML97 LINEAR, 3 EXPONENTIAL
uniform float fogDensity;         // mode 1: per eye-space unit.  2/3: 1/visibilityRange
uniform vec3 fogColor;            // linear-space horizon/atmosphere colour

uniform uint objectId;
uniform bool instancingEnabled;   // take the id from the per-instance varying
flat in uint vObjectId;
layout(location = 0) out vec4 fragColor;
layout(location = 1) out vec4 fragObjectId;

// The selection id for this fragment: per-instance when instancing, else the
// per-draw uniform.
uint effectiveObjectId() {
    return instancingEnabled ? vObjectId : objectId;
}

// Shadow-map uniforms, samplers and sampling functions, shared verbatim with the
// VRML97 shader (spot/CSM packed into one depth array; point into a cube-array or
// per-slot cubes). Needs the enums (above), the vPosition/vNormal varyings and
// eyeToWorld, all declared before this point.
#include "_shadow_inc.glsl"

// sRGB decode alias kept local so callers read as intent ("decode this texel").
vec3 toLinear(vec3 c) { return sRGBToLinear(c); }

// ACES filmic tone map (Narkowicz fit). Replaces Reinhard, which desaturates
// bright colours toward grey -- that turned saturated metals (gold) muddy/olive
// and plastic-looking. ACES keeps highlight saturation, so metals read as metal.
vec3 acesToneMap(vec3 x) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

// Cheap analytic environment (a sky/ground gradient) standing in for an IBL
// probe, so metals reflect *something* and read as metal rather than plastic.
// (Full image-based lighting is a later phase.)
vec3 envColor(vec3 dir) {
    // High-contrast neutral studio (matches ibl_env.frag's base gradient): bright
    // top, dark floor, so metals show a bright-on-dark reflection (reads as metal)
    // rather than a flat even tint. Neutral hue keeps gold reading as gold.
    float t = clamp(dir.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 sky = vec3(0.55, 0.56, 0.58);
    vec3 horizon = vec3(0.32, 0.32, 0.33);
    vec3 ground = vec3(0.03, 0.03, 0.03);
    vec3 c = mix(horizon, sky, smoothstep(0.45, 1.0, t));
    c = mix(c, ground, smoothstep(0.45, 0.0, t));
    return c;
}

// Karis' analytic environment-BRDF approximation (Siggraph 2014 mobile course):
// the split-sum (scale, bias) without a precomputed LUT. Used by the analytic
// ambient path so its specular has the right energy/roughness response instead
// of bare Fresnel (which omits the geometry/visibility integral).
vec2 envBRDFApprox(float NdotV, float rough) {
    const vec4 c0 = vec4(-1.0, -0.0275, -0.572, 0.022);
    const vec4 c1 = vec4( 1.0,  0.0425,  1.04, -0.04);
    vec4 r = rough * c0 + c1;
    float a004 = min(r.x * r.x, exp2(-9.28 * NdotV)) * r.x + r.y;
    return vec2(-1.04, 1.04) * a004 + r.zw;
}

// Spot cone falloff. smoothstep between the outer cutoff and inner beam gives a
// soft edge (matches most glTF viewers); VRML97 tolerates either shape.
float spotAttenuation(int i, vec3 L) {
    vec3 spotDir = normalize(lightDirection[i]);
    float cosA = dot(-L, spotDir);
    float cutoff = cos(lightCutOffAngle[i]);   // outer cone (half-angle)
    float beam = cos(lightBeamWidth[i]);       // inner cone (half-angle)
    // Reference KHR_lights_punctual angular falloff: a clamped linear ramp squared
    // (t*t), not smoothstep -- a slightly crisper edge that matches the sample viewer.
    float t = clamp((cosA - cutoff) / max(beam - cutoff, 1e-4), 0.0, 1.0);
    return t * t;
}

void main() {
    // Fetch this fragment's material ONCE: the per-instance index when instancing,
    // else element 0 (the single bound material). All factor reads below use the
    // register copy _M, not repeated UBO fetches.
    _M = materials[instancingEnabled ? vMaterialIndex : 0u];

    // --- material inputs (each texture samples its own UV set + transform) ---
    vec4 baseTex = hasBaseColor ? texture(baseColorTexture, uvFor(1)) : vec4(1.0);
    vec3 albedo = baseColorFactor * (hasBaseColor ? toLinear(baseTex.rgb) : vec3(1.0));
    float alpha = alphaValue * (hasBaseColor ? baseTex.a : 1.0);
    if (hasVertexColor) {              // glTF COLOR_0 multiplies base color (linear)
        albedo *= vColor.rgb;
        alpha *= vColor.a;
    }

    if (alphaMode == 1 && alpha < alphaCutoff) discard;  // MASK

    // KHR_materials_unlit: emit base color directly (no lighting)
    if (unlitMode) {
        fragColor = vec4(hdrOutput ? albedo : linearToSRGB(albedo), alpha);
        fragObjectId = encodeObjectId(effectiveObjectId());   // unlit is still pickable
        return;
    }

    float metallic = metallicFactor;
    float roughness = roughnessFactor;
    if (hasMetallicRoughness) {
        vec4 mr = texture(metallicRoughnessTexture, uvFor(2));
        roughness *= mr.g;
        metallic *= mr.b;
    }
    roughness = clamp(roughness, 0.04, 1.0);
    // glTF 2.0 GGX uses alpha = roughness^2 for the NDF/geometry terms; the
    // perceptual roughness itself is kept only for env-map LOD / BRDF-LUT lookup.
    // Feeding perceptual roughness straight into D/G gives the wrong lobe width.
    float alphaR = roughness * roughness;

    float ao = 1.0;
    if (hasOcclusion) {
        float o = texture(occlusionTexture, uvFor(8)).r;
        ao = 1.0 + occlusionStrength * (o - 1.0);
    }

    vec3 emissive = emissiveFactor * emissiveStrength;   // KHR_materials_emissive_strength
    if (hasEmissive) emissive *= toLinear(texture(emissiveTexture, uvFor(16)).rgb);

    // Baked irradiance, read as LINEAR light. A lightmap is not a colour
    // texture: it is a radiosity solution written straight to 8 bits, and the
    // engines that produce them modulate in 8 bits with no gamma step. Decoding
    // it as sRGB would crush the midtones -- a mid-grey luxel would arrive at
    // about a tenth of its intended irradiance and the level would look unlit.
    vec3 lightmap = vec3(0.0);
    if (hasLightmap)
        lightmap = texture(lightmapTexture, uvFor(32)).rgb * lightmapStrength;

    // --- normal (with optional tangent-space normal map) ---
    vec3 Ngeom = normalize(vNormal);
    // Two-sided surfaces: flip the normal on back-facing fragments so they are
    // lit correctly (single-sided back faces are culled, so this is harmless).
    if (!gl_FrontFacing) Ngeom = -Ngeom;
    vec3 N = Ngeom;
    if (hasNormal && length(vTangent) > 0.0) {
        vec3 T = normalize(vTangent - N * dot(N, vTangent));
        vec3 B = cross(N, T) * (vTangentW == 0.0 ? 1.0 : vTangentW);
        vec3 nTex = texture(normalTexture, uvFor(4)).xyz * 2.0 - 1.0;
        nTex.xy *= normalScale;
        N = normalize(mat3(T, B, N) * nTex);
    }
    // KHR_materials_clearcoat normal: the coat is a separate smooth layer, so its
    // lobe must NOT follow the base normal map (a coat over orange-peel would wrongly
    // wobble). Use the geometric normal, perturbed only by clearcoatNormalTexture.
    vec3 Nc = Ngeom;
#if PBR_EXT_TEXTURES
    if (hasClearcoatNormalMap && length(vTangent) > 0.0) {
        vec3 Tc = normalize(vTangent - Ngeom * dot(Ngeom, vTangent));
        vec3 Bc = cross(Ngeom, Tc) * (vTangentW == 0.0 ? 1.0 : vTangentW);
        vec3 cTex = texture(clearcoatNormalMap, uvFor(1)).xyz * 2.0 - 1.0;
        Nc = normalize(mat3(Tc, Bc, Ngeom) * cTex);
    }
#endif
    vec3 V = normalize(-vPosition);
    float NdotV = max(dot(N, V), 1e-4);
    float NcdotV = max(dot(Nc, V), 1e-4);   // clearcoat normal · view

    // KHR_materials_anisotropy frame: a tangent-plane direction (the material
    // rotation, optionally rotated further per-texel by the anisotropyTexture)
    // splits GGX roughness into tangent/bitangent halves so the specular lobe
    // stretches into a band. Needs a tangent (the anisotropy assets supply one).
    float anisotropy = anisotropyStrength;
    vec3 aniT = vec3(0.0);
    vec3 aniB = vec3(0.0);
    bool useAniso = false;
    if (anisotropyStrength != 0.0 && length(vTangent) > 0.0) {
        vec2 dir = anisotropyDirection;
#if PBR_EXT_TEXTURES
        if (hasAnisotropyMap) {
            vec3 aTex = texture(anisotropyMap, uvFor(1)).rgb;
            vec2 tdir = aTex.rg * 2.0 - 1.0;                 // texel direction
            dir = vec2(dir.x * tdir.x - dir.y * tdir.y,      // rotate base by texel
                       dir.y * tdir.x + dir.x * tdir.y);
            anisotropy *= aTex.b;
        }
#endif
        vec3 T0 = normalize(vTangent - N * dot(N, vTangent));
        vec3 B0 = cross(N, T0) * (vTangentW == 0.0 ? 1.0 : vTangentW);
        // A direction texture can encode a zero vector (a 0.5,0.5 texel -> (0,0)),
        // and a degenerate tangent leaves T0 zero; either makes normalize() return
        // NaN, which poisons the reflection vector and renders the whole metal BLACK
        // under a probe. Guard both: fall back to isotropic when the frame collapses.
        vec3 aniTraw = dir.x * T0 + dir.y * B0;
        if (dot(aniTraw, aniTraw) > 1e-8 && dot(T0, T0) > 1e-8) {
            aniT = normalize(aniTraw);
            aniB = normalize(cross(N, aniT));
            useAniso = (anisotropy != 0.0) && dot(aniB, aniB) > 1e-8;
        }
    }

    // F0 from index of refraction (KHR_materials_ior) tinted/weighted by
    // KHR_materials_specular, then blended to albedo for metals.
    // Per-texel KHR extension factors (texture * factor). uvFor(1) reuses the base
    // UV set / transform, matching how the other extension textures are sampled.
    float specularWeight = specularFactor;
    vec3 specularColorEff = specularColorFactor;
    vec3 sheenColorEff = sheenColorFactor;
    float sheenRoughEff = sheenRoughnessFactor;
    float iridescenceEff = iridescenceFactor;
#if PBR_EXT_TEXTURES
    if (hasSpecularMap)       specularWeight  *= texture(specularMap, uvFor(1)).a;
    if (hasSpecularColorMap)  specularColorEff *= toLinear(texture(specularColorMap, uvFor(1)).rgb);
    if (hasSheenColorMap)     sheenColorEff   *= toLinear(texture(sheenColorMap, uvFor(1)).rgb);
    if (hasSheenRoughnessMap) sheenRoughEff   *= texture(sheenRoughnessMap, uvFor(1)).a;
    if (hasIridescenceMap)    iridescenceEff  *= texture(iridescenceMap, uvFor(1)).r;
#endif

    float iorF0 = pow((ior - 1.0) / (ior + 1.0), 2.0);
    // KHR_materials_specular: specularColorFactor tints the dielectric F0, but the
    // scalar specularFactor is the grazing reflectance f90 -- NOT folded into F0.
    // Folding it in (the old code) only dimmed normal incidence and left grazing at
    // 1.0; carrying it as f90 dims the whole Fresnel curve, which is the spec.
    vec3 dielF0 = min(iorF0 * specularColorEff, vec3(1.0));
    vec3 F0 = mix(dielF0, albedo, metallic);
    float specF90 = mix(specularWeight, 1.0, metallic);   // metals keep f90 = 1
    // KHR_materials_iridescence: thin-film Fresnel (hue shifts with view angle; a
    // curved surface shows the soap-film rainbow). evalIridescence returns a
    // reflectance already evaluated at NdotV, so mixing it straight into F0 makes the
    // BRDF's own Schlick a SECOND angular term (over-bright/desaturated off-normal).
    // Convert it back to an F0 first (Schlick_to_F0), then the per-lobe Schlick at
    // VdotH reproduces it -- the reference's approach. Factor is per-texel via .r.
    if (iridescenceEff > 0.0) {
        float irThickness = iridescenceThickMax;
#if PBR_EXT_TEXTURES
        // a thickness texture (.g) lerps min..max, giving the per-texel gradient
        if (hasIridescenceThicknessMap)
            irThickness = mix(iridescenceThickMin, iridescenceThickMax,
                              texture(iridescenceThicknessMap, uvFor(1)).g);
#endif
        vec3 irFresnel = evalIridescence(1.0, iridescenceIor, NdotV, irThickness, F0);
        // Thin-film destructive interference can push the reflectance BELOW a low
        // dielectric baseline (0.04), and schlickToF0 then returns a negative F0 --
        // which blows up kd = (1 - F) and renders the sphere blazing white (the
        // IridescenceDielectricSpheres bug). Clamp the recovered F0 to a valid range.
        vec3 irF0 = clamp(schlickToF0(irFresnel, NdotV), 0.0, 1.0);
        F0 = mix(F0, irF0, iridescenceEff);
    }

    // KHR_materials_clearcoat: effective factor/roughness, optionally per-texel.
    float ccFactorEff = clearcoatFactor;
    float ccRoughEff = clearcoatRoughness;
#if PBR_EXT_TEXTURES
    if (hasClearcoatMap) ccFactorEff *= texture(clearcoatMap, uvFor(1)).r;
    if (hasClearcoatRoughnessMap) ccRoughEff *= texture(clearcoatRoughnessMap, uvFor(1)).g;
#endif

    // KHR_materials_volume Beer-Lambert absorption. Per the spec the volume tints
    // ALL light crossing the medium, so it must weight the diffuse-transmission lobes
    // (below) as well as the specular transmission lobe -- e.g. ScatteringSkull is a
    // full diffuse-transmitter whose teal comes ONLY from the attenuation colour.
    float volumeThickness = thicknessFactor;
#if PBR_EXT_TEXTURES
    if (hasThicknessMap) volumeThickness *= texture(thicknessMap, uvFor(0)).g;
#endif
    volumeThickness *= vModelScale;               // local -> world units (model scale)
    vec3 volumeAttenuation = vec3(1.0);
    if (attenuationDistance > 0.0) {
        vec3 sigma = -log(clamp(attenuationColor, 1e-4, 1.0)) / attenuationDistance;
        volumeAttenuation = exp(-sigma * volumeThickness);
    }
    // The transmitted diffuse tint, reused by the punctual back-lobe and the
    // image-based back-glow. A diffuse transmitter scatters near the surface (path
    // ~ one attenuation length), so its volume tint is a single attenuationColor
    // multiply -- NOT the exponential over the full thickness (which, with a short
    // attenuationDistance, drives the lobe to black). This is what turns the white-
    // transmission ScatteringSkull teal. The specular glass lobe below keeps the
    // exact Beer-Lambert (volumeAttenuation) over its refraction path length.
    // Per-texel diffuse-transmission colour (.rgb, sRGB) + factor (.a) -- the
    // translucent-peel texture. Without the colour texture a full transmitter reads
    // WHITE (its reflected base colour is fully replaced by the transmitted lobe).
    vec3 diffuseTransColor = diffuseTransmissionColor;
    float diffuseTransFactorEff = diffuseTransmissionFactor;
#if PBR_EXT_TEXTURES
    if (hasDiffuseTransmissionColorMap)
        diffuseTransColor *= toLinear(texture(diffuseTransmissionColorMap, uvFor(1)).rgb);
    if (hasDiffuseTransmissionMap)
        diffuseTransFactorEff *= texture(diffuseTransmissionMap, uvFor(1)).a;
#endif
    vec3 diffuseTransmit = diffuseTransColor;
    if (attenuationDistance > 0.0) diffuseTransmit *= attenuationColor;

    // --- per-light shadow factors (shaders/_shadow_inc.glsl) ---
    float lightShadow[MAX_LIGHTS];
    resolveShadows(lightShadow);

    // --- direct lighting (diffuse and specular kept separate so a transmissive
    //     surface can replace its diffuse term with the refracted backdrop) ---
    vec3 LoDiffuse = vec3(0.0);
    vec3 LoSpecular = vec3(0.0);
    vec3 LoSheen = vec3(0.0);          // KHR_materials_sheen, accumulated separately
    for (int i = 0; i < MAX_LIGHTS; i++) {
        if (i >= numLights) break;
        if (lightType[i] == LIGHT_OFF) continue;

        vec3 L; float atten = 1.0;
        if (lightType[i] == LIGHT_DIRECTIONAL) {
            L = normalize(-lightDirection[i]);
        } else {
            vec3 lv = lightPosition[i].xyz - vPosition;
            float dist = length(lv);
            L = lv / max(dist, 1e-4);
            vec3 a = lightAttenuation[i];
            atten = 1.0 / max(a.x + a.y * dist + a.z * dist * dist, 1e-4);
            // KHR_lights_punctual range window: clamp(1-(d/range)^4,0,1)/d^2, applied
            // ONCE (the reference windows the inverse-square a single time, not w*w).
            if (lightRange[i] > 0.0) {
                atten *= clamp(1.0 - pow(dist / lightRange[i], 4.0), 0.0, 1.0);
            }
            if (lightType[i] == LIGHT_SPOT) atten *= spotAttenuation(i, L);
        }
        float NdotL = max(dot(N, L), 0.0);
        if (atten <= 0.0) continue;
        vec3 radianceBase = lightColor[i] * lightIntensity[i] * atten * lightShadow[i];

        // KHR_materials_diffuse_transmission: light entering the far side scatters
        // through and exits toward the camera (thin translucency -- leaves, wax,
        // skin). It is driven by the BACK-facing cosine, so it lights exactly the
        // fragments the reflection lobes below skip; add it before the front-lit
        // guard. Energy leaves the diffuse reflection in proportion (handled below).
        if (diffuseTransFactorEff > 0.0) {
            // Transmitted diffuse is tinted by diffuseTransmissionColor, NOT baseColor
            // (per KHR_materials_diffuse_transmission): light scattering through the
            // sheet takes the transmission colour, so a teal leaf backlit by white env
            // reads white/desaturated as the factor rises, not doubly-teal.
            float NdotLback = max(dot(-N, L), 0.0);
            LoDiffuse += diffuseTransmit * diffuseTransFactorEff
                       * INV_PI * NdotLback * radianceBase;
        }
        if (NdotL <= 0.0) continue;      // the reflection lobes need a front-lit face

        vec3 H = normalize(L + V);
        float NdotH = max(dot(N, H), 0.0);
        float VdotH = max(dot(H, V), 0.0);
        // Cook-Torrance: D * Vis * F, where Vis (height-correlated Smith) already
        // folds in the 1/(4 NdotL NdotV) denominator (shaders/_brdf_inc.glsl).
        float D, Vis;
        if (useAniso) {
            float at = max(alphaR * (1.0 + anisotropy), 1e-5);
            float ab = max(alphaR * (1.0 - anisotropy), 1e-5);
            D = D_GGX_anisotropic(NdotH, dot(aniT, H), dot(aniB, H), at, ab);
            Vis = V_GGX_anisotropic(NdotL, NdotV, dot(aniT, V), dot(aniB, V),
                                    dot(aniT, L), dot(aniB, L), at, ab);
        } else {
            D = D_GGX(NdotH, alphaR);
            Vis = V_SmithGGXCorrelated(NdotV, NdotL, alphaR);
        }
        vec3 F = F_Schlick(VdotH, F0, specF90);
        vec3 spec = D * Vis * F;
        vec3 kd = (vec3(1.0) - F) * (1.0 - metallic);
        // Diffuse reflection gives up its energy to the transmitted lobe above.
        vec3 diffuse = kd * albedo * INV_PI * (1.0 - diffuseTransFactorEff);

#if USE_SHEEN
        // KHR_materials_sheen: retroreflective fabric lobe. Full reference BRDF now
        // -- Charlie distribution * Estévez-Kulla V_Sheen (the visibility carries
        // the 1/(4 NdotL NdotV) normalization the old D-only version dropped, which
        // made sheen far too bright). Accumulated separately so the base layer can
        // be energy-scaled by the sheen albedo (below), then added back on top.
        if (sheenColorEff != vec3(0.0)) {
            float sr = clamp(sheenRoughEff, 0.0, 1.0);
            float sheenD = D_Charlie(sr, NdotH);
            float sheenVis = V_Sheen(NdotL, NdotV, sr);
            LoSheen += sheenColorEff * sheenD * sheenVis * radianceBase * NdotL;
        }
#endif
#if USE_CLEARCOAT
        // KHR_materials_clearcoat: a second smooth GGX lobe over the surface, driven
        // by the COAT normal (Nc) -- its microfacet dots differ from the base layer's
        // whenever a base normal map or a clearcoatNormalTexture is present.
        if (ccFactorEff > 0.0) {
            float ccR = clamp(ccRoughEff, 0.04, 1.0);
            float ccAlpha = ccR * ccR;      // glTF GGX alpha = roughness^2
            float NcdotL = max(dot(Nc, L), 0.0);
            float NcdotH = max(dot(Nc, H), 0.0);
            float ccD = D_GGX(NcdotH, ccAlpha);
            float ccVis = V_SmithGGXCorrelated(NcdotV, NcdotL, ccAlpha);
            float ccF = F_Schlick(VdotH, 0.04);
            float ccSpec = ccD * ccVis * ccF * NcdotL;   // coat lobe cosine (own normal)
            float ccAtt = 1.0 - ccFactorEff * ccF;
            diffuse *= ccAtt;
            // spec is scaled by the base radiance (NdotL) below; the coat carries its
            // own cosine, so divide out the base NdotL it will be multiplied by.
            spec = spec * ccAtt + vec3(ccSpec * ccFactorEff / max(NdotL, 1e-4));
        }
#endif

        vec3 radiance = radianceBase * NdotL;
        LoDiffuse += diffuse * radiance;
        LoSpecular += spec * radiance;
    }

    // --- ambient / environment reflection. Metals are almost entirely their
    //     reflected environment, so this term dominates their appearance. The env
    //     probe is world-oriented; sample it with world-space normal/reflection. ---
    mat3 e2w = mat3(eyeToWorld);
    // The env probe cubes (procedural and loaded) are built +Y up in world space,
    // and faceDir matches the hardware cube-sampling convention, so the world-space
    // normal/reflection sample them directly -- no axis flip. (An earlier flipY hack
    // was validated against a reversed-winding test sphere and actually inverted the
    // reflection on real models; sky landed under the metal, ground on top.)
    vec3 Nw = normalize(e2w * N);
    // KHR_materials_anisotropy bends the reflected direction toward the anisotropy
    // bitangent so the environment reflection stretches (the visible swirl on the
    // metal test balls comes mostly from this IBL term, not the punctual lobe).
    vec3 reflectN = N;
    if (useAniso) {
        // When the anisotropy bitangent aligns with the view, cross(aniB, V) is zero
        // and normalize() would return NaN -- poisoning the reflection vector and
        // rendering the metal BLACK at those view angles (the AnisotropyBarnLamp
        // shade seen head-on). Only bend when the cross product is well-defined.
        vec3 anisoTangent = cross(aniB, V);
        if (dot(anisoTangent, anisoTangent) > 1e-8) {
            vec3 anisoNormal = normalize(cross(anisoTangent, aniB));
            float bendFactor = 1.0 - anisotropy * (1.0 - roughness);
            reflectN = normalize(mix(anisoNormal, N, bendFactor));
        }
    }
    vec3 Rw = normalize(e2w * reflect(-V, reflectN));
    vec3 ambDiffuse;
    vec3 ambSpecular;
    // Irradiance arriving on the BACK hemisphere (-N), for KHR_materials_diffuse_transmission:
    // a thin translucent surface (leaf, lampshade, wax) also scatters the light hitting
    // its far side through to the camera, so it glows with the environment behind it.
    vec3 irrBack = vec3(0.0);
    if (iblMode == 2) {                // full IBL probe (split-sum)
        vec3 irr = texture(irradianceMap, Nw).rgb * iblIntensity;
        vec3 pre = textureLod(prefilterMap, Rw, roughness * prefilterMaxLod).rgb * iblIntensity;
        vec2 ab  = texture(brdfLUT, vec2(NdotV, roughness)).rg;
        ambDiffuse  = irr * albedo * (1.0 - metallic) * ao;
        ambSpecular = pre * (F0 * ab.x + specF90 * ab.y) * ao;
        irrBack = texture(irradianceMap, -Nw).rgb * iblIntensity;
    } else if (iblMode == 1) {         // analytic environment + analytic split-sum
        // envColor is a single radiance sample; a Lambertian surface needs the
        // cosine-weighted hemispherical *irradiance*. Approximate that integral by
        // dividing the radiance by PI (finding 4.4) so the analytic diffuse level
        // matches the prefiltered-probe path instead of being ~PI too bright.
        // iblIntensity scales this path exactly as it scales the probe above.
        // Without it the control works on one machine and not another, and
        // stops working mid-session wherever `auto` degrades full -> analytic.
        vec3 envDiffuse = envColor(Nw) * INV_PI * iblIntensity;
        // fade the reflection toward the average sky tone for rough surfaces
        vec3 envSpec = mix(envColor(Rw), vec3(0.5, 0.52, 0.55),
                           roughness * 0.8) * iblIntensity;
        vec2 ab = envBRDFApprox(NdotV, roughness);
        ambDiffuse  = envDiffuse * albedo * (1.0 - metallic) * ao;
        ambSpecular = envSpec * (F0 * ab.x + specF90 * ab.y) * ao;
        irrBack = envColor(-Nw) * INV_PI * iblIntensity;
    } else {                           // off: flat ambient, no reflection
        ambDiffuse  = sceneAmbient * albedo * (1.0 - metallic) * ao;
        ambSpecular = vec3(0.0);
        irrBack = sceneAmbient;
    }
    // Baked irradiance joins the environment terms: it is light arriving at the
    // surface, so it multiplies albedo for the diffuse lobe and goes through the
    // same split-sum reflectance for the specular one. Without the specular half a
    // glossy lightmapped surface reads flat -- the baked light would never
    // reflect. The direction of the baked light is not recorded, so the specular
    // uses the ambient (view-dependent, normal-independent) approximation.
    if (hasLightmap) {
        vec2 lmAB = envBRDFApprox(NdotV, roughness);
        ambDiffuse += lightmap * albedo * (1.0 - metallic) * ao;
        ambSpecular += lightmap * (F0 * lmAB.x + specF90 * lmAB.y) * ao;
        irrBack += lightmap;
    }
    // Diffuse transmission gives up some reflected-diffuse energy to a back-lit lobe
    // fed by the environment behind the surface (the punctual back lobe is added in
    // the light loop above; this is its image-based counterpart).
    if (diffuseTransFactorEff > 0.0) {
        ambDiffuse *= (1.0 - diffuseTransFactorEff);
        ambDiffuse += diffuseTransmit * diffuseTransFactorEff
                    * (1.0 - metallic) * ao * irrBack;
    }
#if USE_CLEARCOAT
    if (ccFactorEff > 0.0) {           // clearcoat reflects the environment too
        // Reflect about the COAT normal (Nc), and use NcdotV for its Fresnel.
        vec3 Rwc = normalize(e2w * reflect(-V, Nc));
        vec3 ccEnv = (iblMode == 2)
            ? textureLod(prefilterMap, Rwc, ccRoughEff * prefilterMaxLod).rgb * iblIntensity
            : mix(envColor(Rwc), vec3(0.5, 0.52, 0.55),
                  ccRoughEff * 0.8) * iblIntensity;
        float ccFr = F_Schlick(NcdotV, 0.04);
        float ccAtt = 1.0 - ccFactorEff * ccFr;
        ambDiffuse *= ccAtt;
        ambSpecular = ambSpecular * ccAtt + ccEnv * ccFr * ccFactorEff;
    }
#endif

    vec3 diffuseTerm = ambDiffuse + LoDiffuse;
    vec3 specularTerm = ambSpecular + LoSpecular;

#if USE_SHEEN
    // KHR_materials_sheen energy: scale the base layer down by the sheen directional
    // albedo (so sheen isn't pure additive gain -> velvet wouldn't wash out), and add
    // an image-based sheen lobe (fabrics get a probe-lit sheen, not only punctual).
    if (sheenColorEff != vec3(0.0)) {
        float sheenRough = clamp(sheenRoughEff, 0.0, 1.0);
        float sheenE;                 // Charlie directional albedo E(NdotV, roughness)
        vec3 sheenRadiance;
        if (iblMode == 2) {
            sheenE = texture(brdfLUT, vec2(NdotV, sheenRough)).b;
            sheenRadiance = textureLod(prefilterMap, Rw,
                                       sheenRough * prefilterMaxLod).rgb * iblIntensity;
        } else if (iblMode == 1) {
            sheenE = mix(0.04, 0.72, sheenRough) * (1.0 - 0.4 * NdotV);   // analytic fit
            sheenRadiance = mix(envColor(Rw), vec3(0.5, 0.52, 0.55),
                                sheenRough * 0.8) * iblIntensity;
        } else {
            sheenE = mix(0.04, 0.72, sheenRough) * (1.0 - 0.4 * NdotV);
            sheenRadiance = sceneAmbient;
        }
        float sheenMax = max(max(sheenColorEff.r, sheenColorEff.g), sheenColorEff.b);
        float sheenScaling = 1.0 - sheenMax * sheenE;
        diffuseTerm *= sheenScaling;
        specularTerm *= sheenScaling;
        specularTerm += LoSheen + sheenColorEff * sheenRadiance * sheenE * ao;
    }
#endif

#if USE_TRANSMISSION
    // KHR_materials_transmission: the diffuse term is replaced by light refracted
    // through the surface from the backdrop, tinted by albedo and (optionally) the
    // volume's Beer-Lambert absorption. Specular reflection stays on top.
    float transmission = transmissionFactor;
#if PBR_EXT_TEXTURES
    // KHR_materials_transmission transmissionTexture (.r) varies transmission per
    // fragment, so a surface can be transmissive in some regions and opaque in others.
    if (hasTransmissionMap) transmission *= texture(transmissionMap, uvFor(1)).r;
#endif
    if (transmission > 0.0 && hasTransmissionBackdrop) {
        // KHR_materials_volume thickness (world units) drives the refraction offset
        // and Beer-Lambert absorption, both computed once above (volumeThickness /
        // volumeAttenuation) and shared with the diffuse-transmission lobes.
        float thick = volumeThickness;
        // Blur the backdrop by roughness, but scale roughness by IOR the way the
        // reference does (applyIorToRoughness): low-IOR glass refracts weakly and
        // should not over-blur. clamp(ior*2-2,0,1) == 1 at the 1.5 glass default.
        float mip = roughness * clamp(ior * 2.0 - 2.0, 0.0, 1.0) * transmissionMaxLod;
        vec3 bg;
        if (dispersion > 0.0) {
            // KHR_materials_dispersion: IOR varies across the spectrum, so R/G/B
            // refract along slightly different rays and the backdrop splits into a
            // chromatic fringe. Sample each channel at its own refracted exit point.
            float halfSpread = (ior - 1.0) * 0.025 * dispersion;
            vec3 iors = vec3(ior - halfSpread, ior, ior + halfSpread);
            for (int c = 0; c < 3; c++) {
                vec3 refrC = refract(-V, N, 1.0 / max(iors[c], 1.0001));
                vec4 clipC = projectionMatrix * vec4(vPosition + refrC * max(thick, 1e-3), 1.0);
                vec2 uvC = clamp((clipC.xy / clipC.w) * 0.5 + 0.5, 0.0, 1.0);
                bg[c] = toLinear(textureLod(transmissionTexture, uvC, mip).rgb)[c];
            }
        } else {
            vec3 refr = refract(-V, N, 1.0 / max(ior, 1.0001));
            vec3 exitPos = vPosition + refr * max(thick, 1e-3);
            vec4 clip = projectionMatrix * vec4(exitPos, 1.0);
            vec2 backUV = clamp((clip.xy / clip.w) * 0.5 + 0.5, 0.0, 1.0);
            bg = toLinear(textureLod(transmissionTexture, backUV, mip).rgb);
        }
        // Energy conservation: transmitted light is what the specular reflection did
        // NOT take, so weight the backdrop by (1 - specular reflectance). Without this
        // the glass keeps a full backdrop AND adds full specular, reading milky/too
        // bright, and silhouettes stay glassy instead of going reflective-opaque.
        vec2 tab = envBRDFApprox(NdotV, roughness);
        vec3 fss = F0 * tab.x + specF90 * tab.y;
        vec3 transmitted = bg * albedo * volumeAttenuation * (vec3(1.0) - fss);
        diffuseTerm = mix(diffuseTerm, transmitted, transmission);
    }
#endif

    vec3 color = diffuseTerm + specularTerm + emissive;

    // Camera exposure. Defaults to 1.0 (no change); scenes lit by absolute-unit
    // KHR_lights_punctual lights (candela/lux, values in the hundreds/thousands)
    // set it from a light-meter reading so they don't clip to white -- the same
    // job a real camera's aperture/ISO does. See gltf_view exposure handling.
    color *= exposure;

    // Fog in linear HDR (before tone map): distant geometry fades into the fog
    // colour, which dissolves the far edge of a terrain patch and is what being
    // under water looks like from inside it.
    if (fogMode > 0 && fogDensity > 0.0) {
        // How far through the fog this fragment lies: eye distance over the
        // visible range for the VRML97 curves, or distance times density for
        // the aerial-perspective one.  One number, read three ways.
        float reach = fogDensity * length(vPosition);
        float fog;
        if (fogMode == 1) {
            fog = 1.0 - exp(-reach);                    // aerial perspective
        } else if (fogMode == 2) {
            fog = reach;                                // VRML97 LINEAR
        } else {
            // VRML97 EXPONENTIAL: hangs back, then closes in, and reaches
            // total obscurity exactly at the visible range rather than only
            // tending toward it.  Past the range the divisor would go
            // negative, so it is clamped to fully fogged.
            float clear = 1.0 - reach;
            fog = clear > 0.0 ? 1.0 - exp(-reach / clear) : 1.0;
        }
        color = mix(color, fogColor, clamp(fog, 0.0, 1.0));
    }

    // filmic tone map (ACES) + sRGB encode for a non-sRGB framebuffer. Correct
    // ONLY with GL_FRAMEBUFFER_SRGB disabled (the pass forces this); an sRGB draw
    // target would double-encode. See pbrpass framebuffer setup.
    if (!hdrOutput) {                 // default: tone-map + sRGB here
        color = acesToneMap(color);
        color = linearToSRGB(color);
    }                                 // bloom pass: leave linear HDR for the composite
    fragColor = vec4(color, alpha);
    fragObjectId = encodeObjectId(effectiveObjectId());
}
