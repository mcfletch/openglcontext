#version 330 core

// A side's image, its alpha blended over the sky and ground drawn first.

in vec2 vTexCoord;

uniform sampler2D faceImage;

out vec4 fragColor;

void main() {
    fragColor = texture(faceImage, vTexCoord);
}
