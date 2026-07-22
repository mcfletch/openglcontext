// Shared light + shadow enums, the scene light-uniform block, and the selection
// object-id encode -- included by both lit fragment shaders (pbr.frag and
// vrml97_lighting.frag) so the two stay in lock-step with the Python that fills
// these uniforms (VRML97ShaderProgram.set_light). The including shader must
// #define MAX_LIGHTS before pulling this in.

// Light types (matches lightType[] uploaded per light)
#define LIGHT_OFF 0
#define LIGHT_DIRECTIONAL 1
#define LIGHT_POINT 2
#define LIGHT_SPOT 3

// Shadow kinds (matches shadowKind[] in the shadow subsystem)
#define SHADOW_SPOT 0
#define SHADOW_DIR  1
#define SHADOW_POINT 2

// Scene lights, eye space. w=0 directional / w=1 positional in lightPosition.
uniform int   numLights;
uniform int   lightType[MAX_LIGHTS];
uniform vec3  lightColor[MAX_LIGHTS];
uniform vec4  lightPosition[MAX_LIGHTS];
uniform vec3  lightDirection[MAX_LIGHTS];
uniform vec3  lightAttenuation[MAX_LIGHTS];   // constant, linear, quadratic
uniform float lightRange[MAX_LIGHTS];         // KHR_lights_punctual range; 0 = unbounded
uniform float lightBeamWidth[MAX_LIGHTS];     // spot inner cone (radians)
uniform float lightCutOffAngle[MAX_LIGHTS];   // spot outer cone (radians)
uniform float lightIntensity[MAX_LIGHTS];
uniform vec3  sceneAmbient;

// The RGBA8 object-id encode is shared with the unlit/point/line shaders too.
#include "_objectid_inc.glsl"
