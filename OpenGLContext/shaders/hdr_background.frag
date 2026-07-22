#version 330 core

// Sample an equirectangular HDR panorama for the visible skybox. The direction is
// mapped to longitude/latitude UV (matching ibl_equirect.frag, so the reflected
// environment and the drawn background line up), then exposure-scaled and, for a
// non-sRGB LDR framebuffer, filmic-tone-mapped + sRGB-encoded exactly as pbr.frag
// finishes lit geometry -- so the sky and the objects lit by it share one response.

#include "_common_inc.glsl"   // linearToSRGB
#include "_cubemap_inc.glsl"  // dirToEquirect (shared with ibl_equirect.frag)

in vec3 vDir;
out vec4 fragColor;

uniform sampler2D equirectMap;   // linear-radiance equirectangular panorama
uniform float exposure;          // camera exposure (matches the lit pass)
uniform bool hdrOutput;          // bloom pass: emit linear HDR, defer tone map

vec3 acesToneMap(vec3 x) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

void main() {
    vec3 d = normalize(vDir);
    vec3 color = texture(equirectMap, dirToEquirect(d)).rgb * exposure;
    if (!hdrOutput) {
        color = acesToneMap(color);
        color = linearToSRGB(color);
    }
    fragColor = vec4(color, 1.0);
}
