#version 330 core

// Background fragment shader - outputs vertex color for sphere gradient backgrounds
// No lighting calculation, just passes through interpolated vertex colors

in vec3 vColor;

out vec4 fragColor;

void main() {
    fragColor = vec4(vColor, 1.0);
}
