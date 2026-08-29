#version 330 core
// Minimal depth-only vertex shader for shadow-map passes. Transforms position
// only -- no normals, texcoords, lighting, or PBR work -- so a shadow pass is
// just a vertex transform + depth write. Position uses the same attribute
// location (2) as pbr.vert so the geometry's cached VAO binds unchanged.
layout(location = 2) in vec3 aPosition;  // required
// Per-instance light-space modelview (divisor 1), locations 5..8; used only when
// instancingEnabled, so an instanced shadow caster writes depth in one draw.
layout(location = 5) in mat4 aInstanceModelView;

#include "_skinning_inc.glsl"
#include "_wave_inc.glsl"

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform bool instancingEnabled;

void main() {
    mat4 mv = instancingEnabled ? aInstanceModelView : modelViewMatrix;
    vec3 position = aPosition;
    applySkin(position);
    vec3 waveNormal = vec3(0.0, 1.0, 0.0);
    applyWave(position, waveNormal);
    gl_Position = projectionMatrix * (mv * vec4(position, 1.0));
}
