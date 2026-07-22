// Shared Cook-Torrance BRDF terms and GGX importance-sampling machinery. One
// definition splits across the analytic direct-lighting path (pbr.frag) and the
// offline split-sum precomputes (ibl_brdf.frag, ibl_prefilter.frag), so the LUT,
// the prefiltered probe and the real-time shading can never drift apart -- the
// class of bug that let the direct and IBL geometry terms disagree (findings 1/2).
//
// ROUGHNESS CONVENTION -- read before touching a caller:
//   perceptualRoughness  is the glTF material `roughness` in [0,1], and is what
//                         indexes env-map LOD and the BRDF LUT axis.
//   alpha = roughness*roughness  is what every function BELOW consumes. glTF 2.0
//                         GGX drives the NDF/geometry with alpha, not perceptual
//                         roughness; feeding perceptual roughness straight in
//                         gives the wrong lobe width. ALWAYS pass alpha here.
#include "_common_inc.glsl"

// --- low-discrepancy sampling (Hammersley / Van der Corput) -------------------
float radicalInverse_VdC(uint bits) {
    bits = (bits << 16u) | (bits >> 16u);
    bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
    bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
    bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
    bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
    return float(bits) * 2.3283064365386963e-10;
}
vec2 hammersley(uint i, uint n) {
    return vec2(float(i) / float(n), radicalInverse_VdC(i));
}

// GGX visible-normal importance sample. `alpha` = roughness*roughness (see the
// convention note above); the CDF term is (alpha^2 - 1), i.e. alpha*alpha here.
vec3 importanceSampleGGX(vec2 Xi, vec3 N, float alpha) {
    float phi = 2.0 * PI * Xi.x;
    float cosTheta = sqrt((1.0 - Xi.y) / (1.0 + (alpha * alpha - 1.0) * Xi.y));
    float sinTheta = sqrt(1.0 - cosTheta * cosTheta);
    vec3 H = vec3(cos(phi) * sinTheta, sin(phi) * sinTheta, cosTheta);
    vec3 up = abs(N.z) < 0.999 ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
    vec3 tangent = normalize(cross(up, N));
    vec3 bitangent = cross(N, tangent);
    return normalize(tangent * H.x + bitangent * H.y + N * H.z);
}

// --- Cook-Torrance terms ------------------------------------------------------
// Trowbridge-Reitz (GGX) normal distribution. `alpha` = roughness^2.
float D_GGX(float NdotH, float alpha) {
    float a2 = alpha * alpha;
    float d = NdotH * NdotH * (a2 - 1.0) + 1.0;
    return a2 / max(PI * d * d, 1e-7);
}

// Fresnel-Schlick; cosT is the view/half angle cosine (VdotH).
vec3 F_Schlick(float cosT, vec3 F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosT, 0.0, 1.0), 5.0);
}
// Fresnel with an explicit grazing reflectance f90 (KHR_materials_specular sets
// f90 = specularFactor for dielectrics, so grazing highlights fall off with a
// reduced specular weight instead of always rising to white).
vec3 F_Schlick(float cosT, vec3 F0, float f90) {
    return F0 + (f90 - F0) * pow(clamp(1.0 - cosT, 0.0, 1.0), 5.0);
}
float F_Schlick(float cosT, float F0) {
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosT, 0.0, 1.0), 5.0);
}

// Height-correlated Smith visibility for DIRECT lighting. This is G / (4 NdotL
// NdotV) folded into one term, so the caller multiplies D * V * F with NO extra
// 1/(4 NdotV NdotL) denominator. `alpha` = roughness^2. Replaces the older
// separable Schlick-Smith G, which (a) needed the fragile grazing-angle clamp on
// that denominator and (b) had been fed alpha where it expected perceptual
// roughness, squaring it a second time (finding 1).
float V_SmithGGXCorrelated(float NdotV, float NdotL, float alpha) {
    float a2 = alpha * alpha;
    float ggxV = NdotL * sqrt(NdotV * NdotV * (1.0 - a2) + a2);
    float ggxL = NdotV * sqrt(NdotL * NdotL * (1.0 - a2) + a2);
    return 0.5 / max(ggxV + ggxL, 1e-5);
}

// --- KHR_materials_sheen: Charlie distribution + Estévez-Kulla sheen visibility ---
// D_Charlie and the analytic sheen visibility (V_Sheen) are ported verbatim from
// the glTF-Sample-Renderer reference (brdf.glsl). alphaG = sheenRoughness^2.
float D_Charlie(float sheenRoughness, float NdotH) {
    sheenRoughness = max(sheenRoughness, 0.000001);
    float alphaG = sheenRoughness * sheenRoughness;
    float invR = 1.0 / alphaG;
    float sin2h = max(1.0 - NdotH * NdotH, 0.0078125);   // 1/128 min, per reference
    return (2.0 + invR) * pow(sin2h, invR * 0.5) / (2.0 * PI);
}
float lambdaSheenNumericHelper(float x, float alphaG) {
    float oneMinusAlphaSq = (1.0 - alphaG) * (1.0 - alphaG);
    float a = mix(21.5473, 25.3245, oneMinusAlphaSq);
    float b = mix(3.82987, 3.32435, oneMinusAlphaSq);
    float c = mix(0.19823, 0.16801, oneMinusAlphaSq);
    float d = mix(-1.97760, -1.27393, oneMinusAlphaSq);
    float e = mix(-4.32054, -4.85967, oneMinusAlphaSq);
    return a / (1.0 + b * pow(x, c)) + d * x + e;
}
float lambdaSheen(float cosTheta, float alphaG) {
    if (abs(cosTheta) < 0.5)
        return exp(lambdaSheenNumericHelper(cosTheta, alphaG));
    return exp(2.0 * lambdaSheenNumericHelper(0.5, alphaG)
             - lambdaSheenNumericHelper(1.0 - cosTheta, alphaG));
}
float V_Sheen(float NdotL, float NdotV, float sheenRoughness) {
    sheenRoughness = max(sheenRoughness, 0.000001);
    float alphaG = sheenRoughness * sheenRoughness;
    return clamp(1.0 / ((1.0 + lambdaSheen(NdotV, alphaG) + lambdaSheen(NdotL, alphaG))
        * (4.0 * NdotV * NdotL)), 0.0, 1.0);
}

// --- KHR_materials_anisotropy: GGX with separate tangent/bitangent roughness ---
// `at`/`ab` are alpha (roughness^2) along the anisotropy tangent/bitangent, i.e.
// alphaRoughness*(1 +/- anisotropy). Matches the reference brdf.glsl (Kulla-Conty).
float D_GGX_anisotropic(float NdotH, float TdotH, float BdotH, float at, float ab) {
    float a2 = at * ab;
    vec3 f = vec3(ab * TdotH, at * BdotH, a2 * NdotH);
    float w2 = a2 / max(dot(f, f), 1e-9);
    return a2 * w2 * w2 / PI;
}
float V_GGX_anisotropic(float NdotL, float NdotV,
                        float TdotV, float BdotV, float TdotL, float BdotL,
                        float at, float ab) {
    float ggxV = NdotL * length(vec3(at * TdotV, ab * BdotV, NdotV));
    float ggxL = NdotV * length(vec3(at * TdotL, ab * BdotL, NdotL));
    return clamp(0.5 / max(ggxV + ggxL, 1e-5), 0.0, 1.0);
}
