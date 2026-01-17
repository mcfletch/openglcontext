#version 330 core

// VRML97-compatible lighting vertex shader
// Transforms vertices and passes data to fragment shader for per-fragment lighting

// Vertex attributes (matching interleaved T2F_N3F_V3F format)
layout(location = 0) in vec2 aTexCoord;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec3 aPosition;

// Transformation matrices
uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform mat3 normalMatrix;
uniform mat3 textureMatrix;  // For VRML97 TextureTransform

// Outputs to fragment shader
out vec3 vNormal;
out vec3 vPosition;  // Position in eye/view space
out vec2 vTexCoord;

void main() {
    // Transform position to eye space (for lighting calculations)
    vec4 eyePosition = modelViewMatrix * vec4(aPosition, 1.0);
    vPosition = eyePosition.xyz;

    // Transform normal to eye space
    vNormal = normalize(normalMatrix * aNormal);

    // Apply texture transform (2D homogeneous coordinates)
    vec3 transformedTex = textureMatrix * vec3(aTexCoord, 1.0);
    vTexCoord = transformedTex.xy;

    // Final clip-space position
    gl_Position = projectionMatrix * eyePosition;
}
