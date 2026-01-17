#version 330 core

// Background vertex shader - uses vertex colors for sphere gradient backgrounds
// Transforms vertices and passes through vertex colors

layout(location = 0) in vec3 aPosition;
layout(location = 1) in vec3 aColor;

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;

out vec3 vColor;

void main() {
    gl_Position = projectionMatrix * modelViewMatrix * vec4(aPosition, 1.0);
    vColor = aColor;
}
