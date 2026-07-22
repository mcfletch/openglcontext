#version 330 core
// Minimal depth-only vertex shader for shadow-map passes. Transforms position
// only -- no normals, texcoords, lighting, or PBR work -- so a shadow pass is
// just a vertex transform + depth write. Position uses the same attribute
// location (2) as pbr.vert so the geometry's cached VAO binds unchanged.
layout(location = 2) in vec3 aPosition;
// Per-instance light-space modelview (divisor 1), locations 5..8; used only when
// instancingEnabled, so an instanced shadow caster writes depth in one draw.
layout(location = 5) in mat4 aInstanceModelView;

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform bool instancingEnabled;

void main() {
    mat4 mv = instancingEnabled ? aInstanceModelView : modelViewMatrix;
    gl_Position = projectionMatrix * (mv * vec4(aPosition, 1.0));
}
