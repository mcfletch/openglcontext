#version 330 core
// Desktop OpenGL 3.3 only, by design (finding 5.3): no GLSL-ES / WebGL profile is
// provided -- OpenGLContext targets desktop core profiles. A GLSL-ES port would
// need precision qualifiers and the array-shadow-sampler fallbacks reworking.

// VRML97-compatible lighting fragment shader
// Implements the VRML97 lighting equation for directional, point, and spot lights

// Maximum number of lights (VRML97 typically allows 8)
#define MAX_LIGHTS 8

// Maximum number of simultaneous shadow-casting lights, and CSM cascades each.
// MAX_SHADOW_LIGHTS is injected at compile time (derived from the driver's real
// GL_MAX_TEXTURE_IMAGE_UNITS); a default keeps standalone compiles valid.
#ifndef MAX_SHADOW_LIGHTS
#define MAX_SHADOW_LIGHTS 4
#endif
#define MAX_CASCADES 4

// Light/shadow enums, the scene light-uniform block (numLights, lightType[],
// lightColor[], ..., sceneAmbient), and encodeObjectId() -- shared with pbr.frag.
#include "_lights_inc.glsl"

// Inputs from vertex shader
in vec3 vNormal;
in vec3 vPosition;
in vec2 vTexCoord;

// Material uniforms (VRML97 Material node properties)
uniform vec3 diffuseColor;
uniform vec3 specularColor;
uniform vec3 emissiveColor;
uniform float ambientIntensity;
uniform float shininess;
uniform float transparency;

// Texture uniforms
uniform sampler2D diffuseTexture;
uniform bool hasDiffuseTexture;

uniform mat4 eyeToWorld;   // inverse camera view (cube shadow direction)

// Shadow-map uniforms, samplers and sampling functions (spot/CSM packed into one
// depth array, point shadows into a cube-array or per-slot cubes). Needs the
// enums (above), the vPosition/vNormal varyings and eyeToWorld, all above here.
#include "_shadow_inc.glsl"

// Object ID for selection buffer (MRT)
uniform uint objectId;
uniform bool instancingEnabled;   // take the id from the per-instance varying
flat in uint vObjectId;

// Output color (attachment 0)
layout(location = 0) out vec4 fragColor;
// Output object ID (attachment 1) - for selection buffer
layout(location = 1) out vec4 fragObjectId;

// Shared VRML97 lighting math (calcAttenuation / calcSpotEffect / calcLight),
// also used by vrml97_vertex_color.frag so the two stay in lock-step (finding 2a).
#include "_vrml97_lighting_inc.glsl"

void main() {
    // Normalize interpolated normal
    vec3 normal = normalize(vNormal);

    // Two-sided lighting: for solid=FALSE geometry the back faces are visible,
    // so flip the normal toward the viewer (as pbr.frag does) instead of leaving
    // back faces dark. Matches the fixed-function GL_LIGHT_MODEL_TWO_SIDE path.
    if (!gl_FrontFacing) normal = -normal;

    // View direction (camera is at origin in eye space)
    vec3 viewDir = normalize(-vPosition);

    // Get base diffuse color (from texture or material)
    vec3 matDiffuse = diffuseColor;
    float alpha = 1.0 - transparency;

    if (hasDiffuseTexture) {
        vec4 texColor = texture(diffuseTexture, vTexCoord);
        matDiffuse *= texColor.rgb;
        alpha *= texColor.a;
    }

    // Ambient contribution
    // VRML97: ambient = ambientIntensity * diffuseColor * sceneAmbient
    vec3 ambient = ambientIntensity * matDiffuse * sceneAmbient;

    // Emissive contribution (glow)
    vec3 emissive = emissiveColor;

    // Resolve a shadow factor per light (shaders/_shadow_inc.glsl).
    float lightShadow[MAX_LIGHTS];
    resolveShadows(lightShadow);

    // Accumulate light contributions
    vec3 lighting = vec3(0.0);
    for (int i = 0; i < MAX_LIGHTS; i++) {
        if (i >= numLights) break;
        lighting += calcLight(i, normal, viewDir, matDiffuse, specularColor, lightShadow[i]);
    }

    // Final color
    vec3 finalColor = emissive + ambient + lighting;

    // Clamp to valid range
    finalColor = clamp(finalColor, 0.0, 1.0);

    fragColor = vec4(finalColor, alpha);
    // Per-instance id when instancing, else the per-draw uniform.
    fragObjectId = encodeObjectId(instancingEnabled ? vObjectId : objectId);
}
