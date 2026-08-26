#version 330 core

// Point vertex shader with per-vertex color support
// Used for PointSet geometry (particles, point clouds, etc.)

layout(location = 2) in vec3 aPosition;
layout(location = 4) in vec3 aColor;

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform float pointSize;

out vec3 vColor;

void main() {
    gl_Position = projectionMatrix * modelViewMatrix * vec4(aPosition, 1.0);
    vColor = aColor;
    // gl_PointSize is set per-vertex; can be used for size attenuation
    // For now, just use the uniform point size
    gl_PointSize = pointSize;
}
