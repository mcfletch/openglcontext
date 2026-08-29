#version 330 core

// Skybox pass for an equirectangular HDR panorama. The cube vertices double as the
// view direction (the background is drawn at infinity, so only orientation matters);
// the fragment shader maps that direction into the panorama.
layout(location = 2) in vec3 aPosition;  // required

out vec3 vDir;

uniform mat4 mvpMatrix;

void main() {
    vDir = aPosition;
    gl_Position = mvpMatrix * vec4(aPosition, 1.0);
}
