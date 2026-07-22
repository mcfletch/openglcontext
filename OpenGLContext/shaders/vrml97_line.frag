#version 330 core

// Line fragment shader with per-vertex color support
// Used for IndexedLineSet geometry

#include "_objectid_inc.glsl"

in vec3 vColor;

// Object ID for selection buffer (MRT)
uniform uint objectId;

// Output color (attachment 0)
layout(location = 0) out vec4 fragColor;
// Output object ID (attachment 1) - for selection buffer
layout(location = 1) out vec4 fragObjectId;

void main() {
    fragColor = vec4(vColor, 1.0);

    // Output object ID to selection buffer (encode as RGBA8)
    fragObjectId = encodeObjectId(objectId);
}
