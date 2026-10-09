#version 330 core

// Point vertex shader with per-vertex color support
// Used for PointSet geometry (particles, point clouds, etc.)

layout(location = 2) in vec3 aPosition;  // required
layout(location = 4) in vec3 aColor;     // required: this program is chosen for the colours

#include "_pointsize_inc.glsl"

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;

out vec3 vColor;
out vec3 vEyePosition;    // for the fog: its length, per fragment

#include "_clipplane_inc.glsl"

void main() {
    vec4 eyePosition = modelViewMatrix * vec4(aPosition, 1.0);
    vEyePosition = eyePosition.xyz;
    gl_Position = projectionMatrix * eyePosition;
    clipByPlanes(aPosition);
    vColor = aColor;
    gl_PointSize = x3dPointSize(length(eyePosition.xyz));
}
