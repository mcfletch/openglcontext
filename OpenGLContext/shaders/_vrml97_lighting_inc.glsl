// The VRML97 pass's lighting -- X3D's Phong terms per light (_phong_inc.glsl) --
// included by both vrml97_lighting.frag (material diffuse) and
// vrml97_vertex_color.frag (per-vertex diffuse) so the two stay in lock-step.
// The including shader must first pull in _lights_inc (the light-uniform block
// + enums) and declare the `vPosition` varying and the `shininess` and
// `ambientIntensity` uniforms.
// calcLight takes a per-light shadowFactor, so a shader that resolves shadows
// passes it through and one that doesn't passes 1.0.

#include "_phong_inc.glsl"

// One bit per light slot a zone switches off for the draw: set, the light does
// not light it (OpenGLContext.passes.zonelayers.light_mask).
uniform int lightsOff;

// Contribution of a single light, scaled by its shadow factor (1.0 = fully lit).
vec3 calcLight(int lightIndex, vec3 normal, vec3 viewDir,
               vec3 matDiffuse, vec3 matSpecular, float shadowFactor) {
    return phongLight(lightIndex, normal, viewDir, vPosition, matDiffuse,
                      ambientIntensity * matDiffuse, matSpecular, shininess, shadowFactor);
}
