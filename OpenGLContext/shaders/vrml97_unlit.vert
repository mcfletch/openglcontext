#version 330 core

// Unlit vertex shader for selection/picking and text rendering
// Uses solid color without lighting, passes texture coordinates for text mode

layout(location = 0) in vec2 aTexCoord;  // optional: sampled in text mode
layout(location = 1) in vec3 aNormal;    // optional: unread; the layout is the lit program's
layout(location = 2) in vec3 aPosition;  // required

#include "_pointsize_inc.glsl"

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;

out vec2 vTexCoord;
out vec3 vEyePosition;    // for the fog: its length, per fragment

#include "_clipplane_inc.glsl"

void main() {
    vec4 eyePosition = modelViewMatrix * vec4(aPosition, 1.0);
    vEyePosition = eyePosition.xyz;
    gl_Position = projectionMatrix * eyePosition;
    clipByPlanes(aPosition);
    vTexCoord = aTexCoord;
    // Read only for points, where GL_PROGRAM_POINT_SIZE is on
    gl_PointSize = x3dPointSize(length(eyePosition.xyz));
}
