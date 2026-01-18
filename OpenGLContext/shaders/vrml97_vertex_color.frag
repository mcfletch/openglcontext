#version 330 core

// VRML97-compatible fragment shader with per-vertex color support
// Implements the VRML97 lighting equation using vertex colors as diffuse

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
in vec4 vColor;  // Per-vertex color (replaces diffuseColor)

// Material uniforms (VRML97 Material node properties)
// Note: diffuseColor is replaced by vertex color vColor
uniform vec3 specularColor;
uniform vec3 emissiveColor;
uniform float ambientIntensity;
uniform float shininess;
uniform float transparency;

// Light uniforms
uniform int numLights;
uniform int lightType[MAX_LIGHTS];
uniform vec3 lightColor[MAX_LIGHTS];
uniform vec4 lightPosition[MAX_LIGHTS];
uniform vec3 lightDirection[MAX_LIGHTS];
uniform vec3 lightAttenuation[MAX_LIGHTS];
uniform float lightBeamWidth[MAX_LIGHTS];
uniform float lightCutOffAngle[MAX_LIGHTS];
uniform float lightIntensity[MAX_LIGHTS];

// Global ambient (scene ambient)
uniform vec3 sceneAmbient;

// Output color
out vec4 fragColor;

// Calculate attenuation for point/spot lights
float calcAttenuation(int lightIndex, float distance) {
    vec3 atten = lightAttenuation[lightIndex];
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
        lightDir = normalize(-lightDirection[lightIndex]);
    } else {
        vec3 lightVec = lightPosition[lightIndex].xyz - vPosition;
        float distance = length(lightVec);
        lightDir = lightVec / distance;
        attenuation = calcAttenuation(lightIndex, distance);

        if (lightType[lightIndex] == LIGHT_SPOT) {
            attenuation *= calcSpotEffect(lightIndex, lightDir);
        }
    }

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

    // Use vertex color as diffuse (like GL_COLOR_MATERIAL)
    vec3 matDiffuse = vColor.rgb;
    float alpha = vColor.a * (1.0 - transparency);

    // Ambient contribution
    vec3 ambient = ambientIntensity * matDiffuse * sceneAmbient;

    // Emissive contribution
    vec3 emissive = emissiveColor;

    // Accumulate light contributions
    vec3 lighting = vec3(0.0);
    for (int i = 0; i < MAX_LIGHTS; i++) {
        if (i >= numLights) break;
        lighting += calcLight(i, normal, viewDir, matDiffuse, specularColor);
    }

    // Final color
    vec3 finalColor = emissive + ambient + lighting;
    finalColor = clamp(finalColor, 0.0, 1.0);

    fragColor = vec4(finalColor, alpha);
}
