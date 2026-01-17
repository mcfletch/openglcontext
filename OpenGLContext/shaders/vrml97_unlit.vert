#version 330 core

// Simple unlit vertex shader for selection/picking rendering
// Uses solid color without lighting

layout(location = 0) in vec2 aTexCoord;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec3 aPosition;

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;

void main() {
    gl_Position = projectionMatrix * modelViewMatrix * vec4(aPosition, 1.0);
}
