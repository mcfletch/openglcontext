#version 330 core

// Simple unlit fragment shader for selection/picking rendering
// Outputs a solid color (set via uniform)

uniform vec4 solidColor;

out vec4 fragColor;

void main() {
    fragColor = solidColor;
}
