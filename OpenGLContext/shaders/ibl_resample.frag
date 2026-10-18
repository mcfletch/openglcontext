#version 330 core

// One face of one level of the prefiltered map, read from an image-based
// light's own mip chain: the light's cube sampled at a fractional level, turned
// and scaled. Trilinear filtering blends the two mips either side of the
// level's roughness.

#include "_cubemap_inc.glsl"   // faceDir

in vec2 vUV;
out vec4 fragColor;

uniform samplerCube envMap;
// required: the light's turn (its rotation) and scale (its intensity)
uniform mat3 envTurn;
uniform vec3 envScale;
uniform int faceIndex;
uniform float envLod;          // the light's mip level this probe level reads

void main() {
    vec3 N = normalize(faceDir(faceIndex, vUV));
    fragColor = vec4(textureLod(envMap, envTurn * N, envLod).rgb * envScale, 1.0);
}
