#version 330 core

// Cosine-weighted hemisphere convolution of the environment cube -> diffuse
// irradiance for one output cube face (Lambertian ambient).

#include "_common_inc.glsl"    // PI
#include "_cubemap_inc.glsl"   // faceDir

// Ceiling on a single env-radiance sample (see ibl_prefilter.frag): an outdoor
// HDR's sun can be +Inf, which overflows this sum to NaN and blacks out the probe.
#define IBL_RADIANCE_CLAMP 50.0

in vec2 vUV;
out vec4 fragColor;

uniform samplerCube envMap;
uniform int faceIndex;

void main() {
    vec3 N = normalize(faceDir(faceIndex, vUV));
    vec3 up = abs(N.y) < 0.999 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
    vec3 right = normalize(cross(up, N));
    up = normalize(cross(N, right));

    vec3 irradiance = vec3(0.0);
    float samples = 0.0;
    const float dPhi = 0.025;
    const float dTheta = 0.025;
    for (float phi = 0.0; phi < 2.0 * PI; phi += dPhi) {
        for (float theta = 0.0; theta < 0.5 * PI; theta += dTheta) {
            vec3 tangent = cos(phi) * right + sin(phi) * up;
            vec3 sampleVec = cos(theta) * N + sin(theta) * tangent;
            vec3 rad = min(texture(envMap, sampleVec).rgb, vec3(IBL_RADIANCE_CLAMP));
            irradiance += rad * cos(theta) * sin(theta);
            samples += 1.0;
        }
    }
    irradiance = PI * irradiance / max(samples, 1.0);
    fragColor = vec4(irradiance, 1.0);
}
