#version 330 core

// Unlit vertex shader for selection/picking and text rendering
// Uses solid color without lighting, passes texture coordinates for text mode

layout(location = 0) in vec2 aTexCoord;  // optional: sampled in text mode
layout(location = 1) in vec3 aNormal;    // optional: unread; the layout is the lit program's
layout(location = 2) in vec3 aPosition;  // required

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;

out vec2 vTexCoord;

void main() {
    gl_Position = projectionMatrix * modelViewMatrix * vec4(aPosition, 1.0);
    vTexCoord = aTexCoord;
}
