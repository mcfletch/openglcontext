// Shared shadow-map sampling, spliced into vrml97_lighting.frag and pbr.frag at
// their shadow-include marker line so both stay in lock-step.
//
// The including shader must, before the marker, define MAX_LIGHTS,
// MAX_SHADOW_LIGHTS and MAX_CASCADES and SHADOW_SPOT/SHADOW_DIR/SHADOW_POINT,
// declare the varyings vPosition/vNormal, and declare `uniform mat4 eyeToWorld`.
//
// Texture-unit budget (finding 2.3): spot maps and directional cascades are
// packed into ONE sampler2DArrayShadow (layer = slot*MAX_CASCADES + cascade;
// spot lights use cascade 0), with one raw view for the PCSS blocker search.
// Point shadows come from a single samplerCubeArrayShadow when SHADOW_CUBE_ARRAY
// is defined (GL 4.0 / ARB_texture_cube_map_array), else from one
// samplerCubeShadow per slot. That caps the lit program at a handful of fragment
// texture image units instead of the 20 the per-slot layout used to demand.

// resolveShadows() below hand-unrolls slots 0..3 with literal indices, because the
// per-slot cube-sampler fallback needs compile-time-constant sampler indices. That
// unroll and this ceiling must move together: if HARD_MAX_SHADOW_LIGHTS (Python)
// is ever raised past 4, slots >=4 would silently never get a shadow factor. Trip
// the compile instead of shipping missing shadows.
#if MAX_SHADOW_LIGHTS > 4
#error "_shadow_inc.glsl unrolls 4 shadow slots; extend resolveShadows() and the per-slot cube-sampler fallback before raising MAX_SHADOW_LIGHTS."
#endif

uniform int   shadowCount;
uniform int   shadowLightIndex[MAX_SHADOW_LIGHTS];
uniform int   shadowKind[MAX_SHADOW_LIGHTS];
uniform float shadowBias;
uniform float shadowNormalOffset;
uniform float shadowTexel;
uniform int   shadowSoft;
uniform float shadowLightSize;
uniform mat4  shadowMatrix[MAX_SHADOW_LIGHTS * MAX_CASCADES];   // eye -> light clip
uniform int   cascadeCount[MAX_SHADOW_LIGHTS];
uniform float cascadeSplit[MAX_SHADOW_LIGHTS * MAX_CASCADES];   // eye-space -z far per cascade
uniform vec3  cubeLightPos[MAX_SHADOW_LIGHTS];                  // world-space light position
uniform float cubeNear[MAX_SHADOW_LIGHTS];
uniform float cubeFar[MAX_SHADOW_LIGHTS];

uniform sampler2DArrayShadow shadowArray;      // spot + directional depth, hardware PCF
uniform sampler2DArray       shadowArrayRaw;   // same texture, raw depth for PCSS

// Named PCSS / bias tuning constants (finding 5.3).
//
// PCSS_SEARCH_SCALE and PCSS_PENUMBRA_SCALE are unit-conversion calibrations, not
// artistic knobs: they map a normalised depth quantity to a texel count for the
// current shadow-map resolution + light projection. They were tuned empirically
// against the default 1024^2 spot/CSM maps so a normal_offset-biased contact
// shadow hardens at the contact and softens with blocker distance at a plausible
// rate; if you change the shadow-map resolution or the light's frustum, these are
// what re-scale. The artist-facing per-light lever is instead `shadowLightSize`
// (bigger light -> wider penumbra) -- which is currently a single global uniform;
// making penumbra genuinely per-light means promoting shadowLightSize to a
// per-slot array in the Python + here, not per-light-ing these calibrations.
const float PCSS_SEARCH_SCALE   = 300.0;   // blocker-search radius per unit light size (texels)
const float PCSS_PENUMBRA_SCALE = 3000.0;  // penumbra depth -> PCF filter radius (texels)
const float CUBE_BIAS_SCALE     = 2.0;     // cube faces need extra depth bias vs the 2D maps

// PCF kernel bounds (finding: name the bare 2.0 / 12.0 magic radii). pcfArray caps
// the half-kernel at PCF_MAX_RADIUS taps (5x5); a soft penumbra wider than
// PCF_MAX_RADIUS_TEXELS is spread across those same taps, so very wide penumbrae
// undersample and can band. Raising the cap costs taps quadratically -- tune here.
const float PCF_MAX_RADIUS_TEXELS = 12.0;  // widest PCSS penumbra the soft path spans
const int   PCF_MAX_RADIUS        = 2;     // half-kernel tap cap (2 -> 5x5)

// Depth bias is a single flat term (plus normal-offset in shadowSamplePos). There
// is deliberately no slope-scaled bias: on steep grazing surfaces (and lower-
// precision depth on integrated GPUs) that can leave faint acne; the normal-offset
// covers the common cases. Add slope-scaling here if a target needs it.

#ifdef SHADOW_CUBE_ARRAY
uniform samplerCubeArrayShadow shadowCubeArray;   // point shadows, cube layer = slot
#else
#if MAX_SHADOW_LIGHTS > 0
uniform samplerCubeShadow shadowCube_0;
#endif
#if MAX_SHADOW_LIGHTS > 1
uniform samplerCubeShadow shadowCube_1;
#endif
#if MAX_SHADOW_LIGHTS > 2
uniform samplerCubeShadow shadowCube_2;
#endif
#if MAX_SHADOW_LIGHTS > 3
uniform samplerCubeShadow shadowCube_3;
#endif
#endif

// Surface position nudged along the normal to combat shadow acne (normal-offset).
vec3 shadowSamplePos() {
    return vPosition + normalize(vNormal) * shadowNormalOffset;
}

// Variable-radius PCF over one layer of the shared depth array. Both the spot
// and CSM paths funnel through this one function (finding 3.24). The integer tap
// count follows the requested filter radius: a hard shadow does a cheap 3x3
// (9 taps) and only a genuinely soft (PCSS) shadow widens to 5x5 -- instead of
// the old fixed 5x5 (25 taps) regardless of hardness. The sample spacing is set
// so the kernel still spans +/- radiusTexels either way, so a wider penumbra
// stays soft without paying for taps a hard edge doesn't need.
float pcfArray(vec2 uv, float layer, float ref, float radiusTexels) {
    int r = int(clamp(ceil(radiusTexels * 0.5), 1.0, float(PCF_MAX_RADIUS)));  // 1->3x3, 2->5x5
    float spacing = radiusTexels / float(r);
    float sum = 0.0;
    float cnt = 0.0;
    for (int x = -r; x <= r; x++) {
        for (int y = -r; y <= r; y++) {
            vec2 o = vec2(x, y) * spacing * shadowTexel;
            sum += texture(shadowArray, vec4(uv + o, layer, ref));
            cnt += 1.0;
        }
    }
    return sum / cnt;
}

// PCSS blocker search on the raw (non-comparison) view. Returns -1 if no blockers.
float blockerSearch(vec2 uv, float layer, float receiver) {
    float searchTexels = max(2.0, shadowLightSize * PCSS_SEARCH_SCALE);
    float sum = 0.0; float count = 0.0;
    for (int x = -2; x <= 2; x++) {
        for (int y = -2; y <= 2; y++) {
            float d = texture(shadowArrayRaw,
                              vec3(uv + vec2(x, y) * (searchTexels * 0.5) * shadowTexel, layer)).r;
            if (d < receiver - shadowBias) { sum += d; count += 1.0; }
        }
    }
    return count > 0.0 ? sum / count : -1.0;
}

// --- Spot light: one array layer (cascade 0 of the slot's block) --------------
float spotFactor(int slot) {
    float layer = float(slot * MAX_CASCADES);
    vec4 lc = shadowMatrix[slot * MAX_CASCADES] * vec4(shadowSamplePos(), 1.0);
    if (lc.w <= 0.0) return 1.0;
    vec3 p = (lc.xyz / lc.w) * 0.5 + 0.5;
    if (p.z > 1.0 || p.x < 0.0 || p.x > 1.0 || p.y < 0.0 || p.y > 1.0) return 1.0;
    float ref = p.z - shadowBias;
    if (shadowSoft == 1) {
        // PCSS: penumbra grows with blocker-to-receiver distance (contact hardening).
        float blocker = blockerSearch(p.xy, layer, p.z);
        if (blocker < 0.0) return 1.0;                 // fully lit, no occluder
        float penumbra = max(p.z - blocker, 0.0);
        float radius = clamp(3.0 + penumbra * shadowLightSize * PCSS_PENUMBRA_SCALE,
                             3.0, PCF_MAX_RADIUS_TEXELS);
        return pcfArray(p.xy, layer, ref, radius);
    }
    return pcfArray(p.xy, layer, ref, 2.0);
}

// --- Directional light: cascaded shadow maps (this slot's layer block) --------
float csmFactor(int slot) {
    int n = cascadeCount[slot];
    float depth = -vPosition.z;                        // eye-space distance from camera
    int c = n - 1;
    for (int i = 0; i < MAX_CASCADES; i++) {
        if (i >= n) break;
        if (depth <= cascadeSplit[slot * MAX_CASCADES + i]) { c = i; break; }
    }
    float layer = float(slot * MAX_CASCADES + c);
    vec4 lc = shadowMatrix[slot * MAX_CASCADES + c] * vec4(shadowSamplePos(), 1.0);
    if (lc.w <= 0.0) return 1.0;
    vec3 p = (lc.xyz / lc.w) * 0.5 + 0.5;
    if (p.z > 1.0 || p.x < 0.0 || p.x > 1.0 || p.y < 0.0 || p.y > 1.0) return 1.0;
    float ref = p.z - shadowBias;
    // Same bounded PCF as the spot path (finding 3.24): hard -> 3x3, soft -> 5x5.
    // Intentionally a fixed-radius soft kernel, not PCSS contact-hardening like the
    // spot path: a directional light has no finite size / blocker distance to drive
    // penumbra growth, so a constant softening is the right model here.
    float radius = shadowSoft == 1 ? 4.0 : 1.0;
    return pcfArray(p.xy, layer, ref, radius);
}

// --- Point light: omnidirectional cube (array layer, or a per-slot cube) ------
float cubeDepthRef(int slot, out vec3 dir) {
    vec3 worldPos = (eyeToWorld * vec4(shadowSamplePos(), 1.0)).xyz;
    dir = worldPos - cubeLightPos[slot];
    float zc = max(max(abs(dir.x), abs(dir.y)), abs(dir.z));
    if (zc <= 0.0) return -1.0;
    float nearP = cubeNear[slot];
    float farP = cubeFar[slot];
    // Projective depth (0..1) for a fragment at axis-distance zc.
    float ndc = (2.0 * farP * nearP / zc - (farP + nearP)) / (nearP - farP);
    return (0.5 * ndc + 0.5) - shadowBias * CUBE_BIAS_SCALE;
}

#ifdef SHADOW_CUBE_ARRAY
float cubeFactor(int slot) {
    vec3 dir; float ref = cubeDepthRef(slot, dir);
    if (ref < 0.0) return 1.0;
    return texture(shadowCubeArray, vec4(dir, float(slot)), ref);
}
#else
float cubeFactor(int slot, samplerCubeShadow smap) {
    vec3 dir; float ref = cubeDepthRef(slot, dir);
    if (ref < 0.0) return 1.0;
    return texture(smap, vec4(dir, ref));
}
#endif

// One slot resolved to a shadow factor. The cube sampler is passed by the caller
// with a literal slot so its sampler index stays a compile-time constant (a hard
// requirement of the GLSL 3.30 fallback path).
#ifdef SHADOW_CUBE_ARRAY
float shadowForSlotK(int slot) {
    int kind = shadowKind[slot];
    if (kind == SHADOW_SPOT) return spotFactor(slot);
    else if (kind == SHADOW_DIR) return csmFactor(slot);
    else return cubeFactor(slot);
}
#else
float shadowForSlotK(int slot, samplerCubeShadow scube) {
    int kind = shadowKind[slot];
    if (kind == SHADOW_SPOT) return spotFactor(slot);
    else if (kind == SHADOW_DIR) return csmFactor(slot);
    else return cubeFactor(slot, scube);
}
#endif

// Fill a per-light shadow factor array. Slots are unrolled with literal indices
// so the fallback cube samplers keep constant indices.
void resolveShadows(inout float lightShadow[MAX_LIGHTS]) {
    for (int i = 0; i < MAX_LIGHTS; i++) lightShadow[i] = 1.0;
#if MAX_SHADOW_LIGHTS > 0
    if (0 < shadowCount)
#ifdef SHADOW_CUBE_ARRAY
        lightShadow[shadowLightIndex[0]] = shadowForSlotK(0);
#else
        lightShadow[shadowLightIndex[0]] = shadowForSlotK(0, shadowCube_0);
#endif
#endif
#if MAX_SHADOW_LIGHTS > 1
    if (1 < shadowCount)
#ifdef SHADOW_CUBE_ARRAY
        lightShadow[shadowLightIndex[1]] = shadowForSlotK(1);
#else
        lightShadow[shadowLightIndex[1]] = shadowForSlotK(1, shadowCube_1);
#endif
#endif
#if MAX_SHADOW_LIGHTS > 2
    if (2 < shadowCount)
#ifdef SHADOW_CUBE_ARRAY
        lightShadow[shadowLightIndex[2]] = shadowForSlotK(2);
#else
        lightShadow[shadowLightIndex[2]] = shadowForSlotK(2, shadowCube_2);
#endif
#endif
#if MAX_SHADOW_LIGHTS > 3
    if (3 < shadowCount)
#ifdef SHADOW_CUBE_ARRAY
        lightShadow[shadowLightIndex[3]] = shadowForSlotK(3);
#else
        lightShadow[shadowLightIndex[3]] = shadowForSlotK(3, shadowCube_3);
#endif
#endif
}
