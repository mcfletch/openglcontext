#version 330 core

// GGX importance-sampled prefilter of the environment cube for one roughness
// level (one mip of the prefiltered specular cube). Split-sum, pre-filtered
// environment map (Karis 2013 / Epic).

#include "_brdf_inc.glsl"      // PI, hammersley, importanceSampleGGX, D_GGX
#include "_cubemap_inc.glsl"   // faceDir

// Ceiling on a single env-radiance sample fed into the probe convolution, so an
// outdoor HDR's sun (which can be +Inf in the .hdr) can't overflow the sum to NaN.
#define IBL_RADIANCE_CLAMP 50.0

in vec2 vUV;
out vec4 fragColor;

uniform samplerCube envMap;
uniform int faceIndex;
uniform float roughness;
uniform float envResolution;   // face size of envMap (for mip selection)

const uint SAMPLE_COUNT = 128u;

void main() {
    vec3 N = normalize(faceDir(faceIndex, vUV));
    vec3 R = N;
    vec3 V = N;
    float a = roughness * roughness;   // GGX alpha

    vec3 prefiltered = vec3(0.0);
    float totalWeight = 0.0;
    for (uint i = 0u; i < SAMPLE_COUNT; i++) {
        vec2 Xi = hammersley(i, SAMPLE_COUNT);
        vec3 H = importanceSampleGGX(Xi, N, a);
        vec3 L = normalize(2.0 * dot(V, H) * H - V);
        float NdotL = max(dot(N, L), 0.0);
        if (NdotL > 0.0) {
            // sample a mip of the env to reduce fireflies (Krivanek/Colbert)
            float NdotH = max(dot(N, H), 0.0);
            float D = D_GGX(NdotH, a);
            float pdf = D * NdotH / (4.0 * max(dot(H, V), 1e-4)) + 1e-4;
            float saTexel = 4.0 * PI / (6.0 * envResolution * envResolution);
            float saSample = 1.0 / (float(SAMPLE_COUNT) * pdf);
            float mip = roughness == 0.0 ? 0.0 : 0.5 * log2(saSample / saTexel);
            // Clamp the sampled radiance: an outdoor HDR's sun/sky can be enormous
            // (even +Inf in the .hdr), which overflows this accumulation to NaN --
            // rendering everything lit by the probe (reflections, transmission) black.
            // A finite ceiling keeps the range while killing the firefly/Inf.
            vec3 rad = min(textureLod(envMap, L, mip).rgb, vec3(IBL_RADIANCE_CLAMP));
            prefiltered += rad * NdotL;
            totalWeight += NdotL;
        }
    }
    prefiltered = prefiltered / max(totalWeight, 1e-4);
    fragColor = vec4(prefiltered, 1.0);
}
