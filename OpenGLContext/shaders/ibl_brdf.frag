#version 330 core

// Split-sum BRDF integration LUT: (scale, bias) for F0 as a function of
// (NdotV, roughness). Environment-independent, so this is computed once.

// PI + Hammersley/GGX importance sampling shared with the prefilter pass and the
// real-time shader, so the LUT integrates the same lobe the probe was filtered
// with (finding 2). The Smith geometry here uses the IBL k = alpha/2, kept local.
#include "_brdf_inc.glsl"

in vec2 vUV;
out vec4 fragColor;

const uint SAMPLE_COUNT = 512u;

// Sheen directional albedo E(NdotV, roughness) for KHR_materials_sheen energy
// compensation + IBL sheen. The Charlie lobe isn't GGX-importance-sampleable, so
// integrate f_sheen*NdotL with uniform-hemisphere sampling (pdf = 1/2pi).
float integrateCharlie(float NdotV, float roughness) {
    vec3 V = vec3(sqrt(1.0 - NdotV * NdotV), 0.0, NdotV);
    vec3 N = vec3(0.0, 0.0, 1.0);
    float r = 0.0;
    for (uint i = 0u; i < SAMPLE_COUNT; i++) {
        vec2 Xi = hammersley(i, SAMPLE_COUNT);
        float cosT = Xi.y;                       // uniform hemisphere
        float sinT = sqrt(max(1.0 - cosT * cosT, 0.0));
        float phi = 2.0 * PI * Xi.x;
        vec3 L = vec3(cos(phi) * sinT, sin(phi) * sinT, cosT);
        float NdotL = L.z;
        if (NdotL > 0.0) {
            vec3 H = normalize(V + L);
            r += D_Charlie(roughness, max(H.z, 0.0))
               * V_Sheen(NdotL, NdotV, roughness) * NdotL;
        }
    }
    return r * 2.0 * PI / float(SAMPLE_COUNT);   // /pdf, averaged
}

// IBL Smith geometry: k = alpha/2, alpha = roughness^2 (distinct from the direct-
// lighting height-correlated visibility in _brdf_inc.glsl -- that is by design).
float geometrySchlickGGX(float NdotV, float roughness) {
    float k = (roughness * roughness) / 2.0;
    return NdotV / (NdotV * (1.0 - k) + k);
}
float geometrySmith(vec3 N, vec3 V, vec3 L, float roughness) {
    return geometrySchlickGGX(max(dot(N, L), 0.0), roughness)
         * geometrySchlickGGX(max(dot(N, V), 0.0), roughness);
}

vec2 integrateBRDF(float NdotV, float roughness) {
    vec3 V = vec3(sqrt(1.0 - NdotV * NdotV), 0.0, NdotV);
    float A = 0.0;
    float B = 0.0;
    vec3 N = vec3(0.0, 0.0, 1.0);
    float alpha = roughness * roughness;   // importanceSampleGGX consumes alpha
    for (uint i = 0u; i < SAMPLE_COUNT; i++) {
        vec2 Xi = hammersley(i, SAMPLE_COUNT);
        vec3 H = importanceSampleGGX(Xi, N, alpha);
        vec3 L = normalize(2.0 * dot(V, H) * H - V);
        float NdotL = max(L.z, 0.0);
        float NdotH = max(H.z, 0.0);
        float VdotH = max(dot(V, H), 0.0);
        if (NdotL > 0.0) {
            float G = geometrySmith(N, V, L, roughness);
            float G_Vis = (G * VdotH) / max(NdotH * NdotV, 1e-6);
            float Fc = pow(1.0 - VdotH, 5.0);
            A += (1.0 - Fc) * G_Vis;
            B += Fc * G_Vis;
        }
    }
    return vec2(A, B) / float(SAMPLE_COUNT);
}

void main() {
    vec2 ab = integrateBRDF(max(vUV.x, 1e-3), max(vUV.y, 1e-3));
    float sheenE = integrateCharlie(max(vUV.x, 1e-3), max(vUV.y, 1e-3));
    fragColor = vec4(ab, sheenE, 1.0);
}
