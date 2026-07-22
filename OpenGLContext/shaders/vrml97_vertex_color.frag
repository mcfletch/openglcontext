#version 330 core

// VRML97-compatible fragment shader with per-vertex color support.
// Same lighting model as vrml97_lighting.frag but the diffuse term comes from the
// interpolated vertex colour (GL_COLOR_MATERIAL semantics) -- used for NURBS
// surfaces and per-vertex-coloured IndexedFaceSets.

#define MAX_LIGHTS 8

// Shadow budget: MAX_SHADOW_LIGHTS is injected at compile time from the driver's
// texture-unit budget; a default keeps standalone compiles valid.
#ifndef MAX_SHADOW_LIGHTS
#define MAX_SHADOW_LIGHTS 4
#endif
#define MAX_CASCADES 4

// Light enums, the scene light-uniform block and encodeObjectId() -- shared with
// vrml97_lighting.frag / pbr.frag (finding 2a).
#include "_lights_inc.glsl"

// Inputs from vertex shader
in vec3 vNormal;
in vec3 vPosition;
in vec4 vColor;  // Per-vertex color (replaces diffuseColor)

// Material uniforms (diffuse comes from vColor, not a uniform)
uniform vec3 specularColor;
uniform vec3 emissiveColor;
uniform float ambientIntensity;
uniform float shininess;
uniform float transparency;

uniform mat4 eyeToWorld;   // inverse camera view (cube shadow direction)

// Shadow-map uniforms, samplers and resolveShadows() -- needs the enums (above),
// the vPosition/vNormal varyings and eyeToWorld, all declared above here. Folding
// this in is what finally gives per-vertex-coloured / NURBS geometry shadows
// (finding 2a: this shader previously had none).
#include "_shadow_inc.glsl"

// Object ID for selection buffer (MRT)
uniform uint objectId;

// Output color (attachment 0)
layout(location = 0) out vec4 fragColor;
// Output object ID (attachment 1) - for selection buffer
layout(location = 1) out vec4 fragObjectId;

// Shared calcAttenuation / calcSpotEffect / calcLight (finding 2a).
#include "_vrml97_lighting_inc.glsl"

void main() {
    vec3 normal = normalize(vNormal);

    // Two-sided lighting: flip the normal toward the viewer on back faces so
    // solid=FALSE per-vertex-coloured geometry isn't dark on its reverse side
    // (matches pbr.frag and the fixed-function GL_LIGHT_MODEL_TWO_SIDE path).
    if (!gl_FrontFacing) normal = -normal;

    // View direction (camera is at origin in eye space)
    vec3 viewDir = normalize(-vPosition);

    // Use vertex color as diffuse (like GL_COLOR_MATERIAL)
    vec3 matDiffuse = vColor.rgb;
    float alpha = vColor.a * (1.0 - transparency);

    vec3 ambient = ambientIntensity * matDiffuse * sceneAmbient;
    vec3 emissive = emissiveColor;

    // Resolve a shadow factor per light (shaders/_shadow_inc.glsl).
    float lightShadow[MAX_LIGHTS];
    resolveShadows(lightShadow);

    vec3 lighting = vec3(0.0);
    for (int i = 0; i < MAX_LIGHTS; i++) {
        if (i >= numLights) break;
        lighting += calcLight(i, normal, viewDir, matDiffuse, specularColor, lightShadow[i]);
    }

    vec3 finalColor = emissive + ambient + lighting;
    finalColor = clamp(finalColor, 0.0, 1.0);

    fragColor = vec4(finalColor, alpha);
    fragObjectId = encodeObjectId(objectId);
}
