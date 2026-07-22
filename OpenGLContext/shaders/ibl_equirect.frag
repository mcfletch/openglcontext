#version 330 core

// Render one face of the environment cube by sampling an equirectangular HDR
// panorama (a Radiance .hdr, decoded to a linear float texture). This lets a real
// captured environment drive the same irradiance / prefilter / BRDF chain as the
// procedural studio env, so metals reflect the loaded scene.

#include "_cubemap_inc.glsl"   // faceDir, dirToEquirect

in vec2 vUV;
out vec4 fragColor;

uniform int faceIndex;          // 0=+X 1=-X 2=+Y 3=-Y 4=+Z 5=-Z
uniform sampler2D equirectMap;  // linear-radiance equirectangular panorama

void main() {
    vec3 dir = normalize(faceDir(faceIndex, vUV));
    fragColor = vec4(texture(equirectMap, dirToEquirect(dir)).rgb, 1.0);
}
