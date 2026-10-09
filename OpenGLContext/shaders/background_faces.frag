#version 330 core

// A side's image, its alpha blended over the sky and ground drawn first.

#include "_displayed_inc.glsl"

in vec2 vTexCoord;

uniform sampler2D faceImage;

out vec4 fragColor;

void main() {
    vec4 color = texture(faceImage, vTexCoord);
    fragColor = vec4(displayedX3D(color.rgb), color.a);
}
