#version 330 core

// Line vertex shader with per-vertex color support
// Used for IndexedLineSet geometry

layout(location = 2) in vec3 aPosition;  // required
layout(location = 4) in vec3 aColor;     // required: this program is chosen for the colours

// Per-instance model-view (divisor 1), spanning locations 5..8, read only when
// instancingEnabled -- matches the lit/PBR shader convention so the instancing
// pass can batch identical wireframes (e.g. all box collision proxies).
layout(location = 5) in mat4 aInstanceModelView;

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform bool instancingEnabled;

out vec3 vColor;
out vec3 vEyePosition;    // for the fog: its length, per fragment

void main() {
    mat4 mv = instancingEnabled ? aInstanceModelView : modelViewMatrix;
    vec4 eyePosition = mv * vec4(aPosition, 1.0);
    vEyePosition = eyePosition.xyz;
    gl_Position = projectionMatrix * eyePosition;
    vColor = aColor;
}
