#version 330 core

// Sample an equirectangular HDR panorama for the visible skybox. The direction is
// mapped to longitude/latitude UV (matching ibl_equirect.frag, so the reflected
// environment and the drawn background line up), then exposure-scaled and, for a
// non-sRGB LDR framebuffer, through the frame's tone curve and sRGB-encoded as
// pbr.frag finishes lit geometry, so the sky and the objects lit by it share
// one response.

#include "_common_inc.glsl"   // linearToSRGB
#include "_cubemap_inc.glsl"  // dirToEquirect (shared with ibl_equirect.frag)
#include "_tonemap_inc.glsl"  // toneCurve, frameLinear

in vec3 vDir;
out vec4 fragColor;

uniform sampler2D equirectMap;   // linear-radiance equirectangular panorama
uniform float exposure;          // camera exposure (matches the lit pass)
uniform bool hdrOutput;          // bloom pass: emit linear HDR, defer tone map

void main() {
    vec3 d = normalize(vDir);
    vec3 color = texture(equirectMap, dirToEquirect(d)).rgb * exposure;
    if (!hdrOutput) {
        color = toneCurve(color);
        color = frameLinear() ? linearToSRGB(color) : clamp(color, 0.0, 1.0);
    }
    fragColor = vec4(color, 1.0);
}
