#version 330 core

// Line vertex shader with per-vertex color support
// Used for IndexedLineSet geometry

layout(location = 0) in vec3 aPosition;
layout(location = 1) in vec3 aColor;

// Per-instance model-view (divisor 1), spanning locations 5..8, read only when
// instancingEnabled -- matches the lit/PBR shader convention so the instancing
// pass can batch identical wireframes (e.g. all box collision proxies).
layout(location = 5) in mat4 aInstanceModelView;

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform bool instancingEnabled;

out vec3 vColor;

void main() {
    mat4 mv = instancingEnabled ? aInstanceModelView : modelViewMatrix;
    gl_Position = projectionMatrix * mv * vec4(aPosition, 1.0);
    vColor = aColor;
}
