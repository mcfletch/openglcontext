#version 330 core

// Background vertex shader - uses vertex colors for sphere gradient backgrounds
// Transforms vertices and passes through vertex colors

layout(location = 2) in vec3 aPosition;  // required
layout(location = 4) in vec3 aColor;     // required: the gradient is the vertex colours

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;

out vec3 vColor;

void main() {
    // The background is a camera-locked gradient sphere standing in for infinity.
    // Emit it at the far plane with the skybox trick (z = w -> NDC depth 1): this
    // clamps every vertex inside the clip volume, so a huge scene whose near plane
    // is pushed out past the finite sphere's radius no longer clips it to a floating
    // polygon with black corners. Depth-test is off and the buffer is cleared after,
    // so pinning depth here is harmless.
    vec4 clip = projectionMatrix * modelViewMatrix * vec4(aPosition, 1.0);
    gl_Position = clip.xyww;
    vColor = aColor;
}
