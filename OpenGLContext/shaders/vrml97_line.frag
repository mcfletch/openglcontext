#version 330 core

// Line fragment shader with per-vertex color support
// Used for IndexedLineSet geometry

#include "_objectid_inc.glsl"
#include "_x3d_fog_inc.glsl"

in vec3 vColor;
in float vEyeDistance;

// Object ID for selection buffer (MRT)
uniform uint objectId;

// Output color (attachment 0)
layout(location = 0) out vec4 fragColor;
// Output object ID (attachment 1) - for selection buffer
layout(location = 1) out vec4 fragObjectId;

void main() {
    fragColor = vec4(x3dFogged(vColor, vEyeDistance), 1.0);

    // Output object ID to selection buffer (encode as RGBA8)
    fragObjectId = encodeObjectId(objectId);
}
