#version 330 core

// VRML97-compatible lighting fragment shader
// Implements the VRML97 lighting equation for directional, point, and spot lights

// Maximum number of lights (VRML97 typically allows 8)
#define MAX_LIGHTS 8

// Light types
#define LIGHT_OFF 0
#define LIGHT_DIRECTIONAL 1
#define LIGHT_POINT 2
#define LIGHT_SPOT 3

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

// Light uniforms
uniform int numLights;
uniform int lightType[MAX_LIGHTS];
uniform vec3 lightColor[MAX_LIGHTS];
uniform vec4 lightPosition[MAX_LIGHTS];   // w=0 for directional, w=1 for positional
uniform vec3 lightDirection[MAX_LIGHTS];  // For directional and spot lights
uniform vec3 lightAttenuation[MAX_LIGHTS]; // constant, linear, quadratic
uniform float lightBeamWidth[MAX_LIGHTS];  // Spot inner cone (radians)
uniform float lightCutOffAngle[MAX_LIGHTS]; // Spot outer cone (radians)
uniform float lightIntensity[MAX_LIGHTS];

// Texture uniforms
uniform sampler2D diffuseTexture;
uniform bool hasDiffuseTexture;

// Global ambient (scene ambient)
uniform vec3 sceneAmbient;

// Output color
out vec4 fragColor;

// Calculate attenuation for point/spot lights
float calcAttenuation(int lightIndex, float distance) {
    vec3 atten = lightAttenuation[lightIndex];
    // VRML97 attenuation: 1 / (constant + linear*d + quadratic*d*d)
    return 1.0 / (atten.x + atten.y * distance + atten.z * distance * distance);
}

// Calculate spot light effect
float calcSpotEffect(int lightIndex, vec3 lightDir) {
    vec3 spotDir = normalize(lightDirection[lightIndex]);
    float cosAngle = dot(-lightDir, spotDir);
    float cutoff = cos(lightCutOffAngle[lightIndex]);
    float beamWidth = cos(lightBeamWidth[lightIndex]);

    if (cosAngle < cutoff) {
        return 0.0;
    } else if (cosAngle > beamWidth) {
        return 1.0;
    } else {
        // Smooth falloff between beam width and cutoff
        return (cosAngle - cutoff) / (beamWidth - cutoff);
    }
}

// Calculate lighting contribution from a single light
vec3 calcLight(int lightIndex, vec3 normal, vec3 viewDir, vec3 matDiffuse, vec3 matSpecular) {
    if (lightType[lightIndex] == LIGHT_OFF) {
        return vec3(0.0);
    }

    vec3 lightDir;
    float attenuation = 1.0;

    if (lightType[lightIndex] == LIGHT_DIRECTIONAL) {
        // Directional light - direction is constant
        lightDir = normalize(-lightDirection[lightIndex]);
    } else {
        // Point or spot light - calculate direction from position
        vec3 lightVec = lightPosition[lightIndex].xyz - vPosition;
        float distance = length(lightVec);
        lightDir = lightVec / distance;
        attenuation = calcAttenuation(lightIndex, distance);

        if (lightType[lightIndex] == LIGHT_SPOT) {
            attenuation *= calcSpotEffect(lightIndex, lightDir);
        }
    }

    // Early exit if no contribution
    if (attenuation <= 0.0) {
        return vec3(0.0);
    }

    vec3 color = lightColor[lightIndex] * lightIntensity[lightIndex];

    // Diffuse component (Lambert)
    float nDotL = max(dot(normal, lightDir), 0.0);
    vec3 diffuse = matDiffuse * color * nDotL;

    // Specular component (Blinn-Phong)
    vec3 specular = vec3(0.0);
    if (nDotL > 0.0 && shininess > 0.0) {
        vec3 halfDir = normalize(lightDir + viewDir);
        float nDotH = max(dot(normal, halfDir), 0.0);
        // VRML97 shininess is 0-1, map to exponent (0.0 -> 1, 1.0 -> 128)
        float specPower = shininess * 128.0;
        specular = matSpecular * color * pow(nDotH, specPower);
    }

    return attenuation * (diffuse + specular);
}

void main() {
    // Normalize interpolated normal
    vec3 normal = normalize(vNormal);

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

    // Accumulate light contributions
    vec3 lighting = vec3(0.0);
    for (int i = 0; i < MAX_LIGHTS; i++) {
        if (i >= numLights) break;
        lighting += calcLight(i, normal, viewDir, matDiffuse, specularColor);
    }

    // Final color
    vec3 finalColor = emissive + ambient + lighting;

    // Clamp to valid range
    finalColor = clamp(finalColor, 0.0, 1.0);

    fragColor = vec4(finalColor, alpha);
}
