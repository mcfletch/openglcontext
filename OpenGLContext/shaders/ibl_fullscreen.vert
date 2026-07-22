#version 330 core

// Attribute-less fullscreen triangle. vUV spans [0,1] over the visible area and
// drives cube-face direction reconstruction / LUT coordinates in the IBL passes.
out vec2 vUV;

void main() {
    vec2 uv = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    vUV = uv;
    gl_Position = vec4(uv * 2.0 - 1.0, 0.0, 1.0);
}
