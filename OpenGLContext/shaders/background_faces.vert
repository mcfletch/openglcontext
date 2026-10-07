#version 330 core

// A Background's image faces: a quad per side, its image's texture coordinates
// as X3D gives them, drawn at the far plane. The modelview carries the
// camera's rotation only.

layout(location = 2) in vec3 aPosition;   // required: the corner on the cube
layout(location = 0) in vec2 aTexCoord;   // required: the corner in the side's image

uniform mat4 mvpMatrix;

out vec2 vTexCoord;

void main() {
    vTexCoord = aTexCoord;
    // At the far plane (z = w) however near or far the view's planes are
    gl_Position = (mvpMatrix * vec4(aPosition, 1.0)).xyww;
}
