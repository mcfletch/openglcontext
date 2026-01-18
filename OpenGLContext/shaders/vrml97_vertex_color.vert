#version 330 core

// VRML97-compatible vertex shader with per-vertex color support
// Used for geometry like NURBS surfaces that have per-vertex colors

// Vertex attributes
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec3 aPosition;
layout(location = 3) in vec4 aColor;  // Per-vertex color (RGBA)

// Transformation matrices
uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform mat3 normalMatrix;

// Outputs to fragment shader
out vec3 vNormal;
out vec3 vPosition;  // Position in eye/view space
out vec4 vColor;     // Per-vertex color

void main() {
    // Transform position to eye space (for lighting calculations)
    vec4 eyePosition = modelViewMatrix * vec4(aPosition, 1.0);
    vPosition = eyePosition.xyz;

    // Transform normal to eye space
    vNormal = normalize(normalMatrix * aNormal);

    // Pass through vertex color
    vColor = aColor;

    // Final clip-space position
    gl_Position = projectionMatrix * eyePosition;
}
