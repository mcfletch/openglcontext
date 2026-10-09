#version 330 core

// Line fragment shader with per-vertex color support
// Used for IndexedLineSet geometry

#include "_objectid_inc.glsl"
#include "_x3d_fog_inc.glsl"
#include "_displayed_inc.glsl"

in vec3 vColor;
in vec3 vEyePosition;

// Object ID for selection buffer (MRT)
uniform uint objectId;

// Output color (attachment 0)
layout(location = 0) out vec4 fragColor;
// Output object ID (attachment 1) - for selection buffer
layout(location = 1) out vec4 fragObjectId;

#include "_oit_inc.glsl"

void shadeFragment() {
    fragColor = vec4(displayedX3D(x3dFogged(vColor, length(vEyePosition))), 1.0);

    // Output object ID to selection buffer (encode as RGBA8)
    fragObjectId = encodeObjectId(objectId);
}

void main() {
    shadeFragment();
    oitAccumulate();
}
