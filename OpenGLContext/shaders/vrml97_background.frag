#version 330 core

// Background fragment shader - outputs vertex color for sphere gradient backgrounds
// No lighting calculation, just passes through interpolated vertex colors

in vec3 vColor;

// Output color (attachment 0)
layout(location = 0) out vec4 fragColor;
// Output object ID (attachment 1) - always 0 for background (not selectable)
layout(location = 1) out vec4 fragObjectId;

void main() {
    fragColor = vec4(vColor, 1.0);
    // Background is never selectable - output ID 0
    fragObjectId = vec4(0.0, 0.0, 0.0, 0.0);
}
