#version 330 core
// x3d_shaders.x3d's PackagedShader: both stages in one file, each compiled
// with its X3D_<STAGE>_SHADER macro defined.
#ifdef X3D_VERTEX_SHADER
in vec4 x3d_Vertex;
in vec3 x3d_Normal;
uniform mat4 x3d_ModelViewMatrix;
uniform mat4 x3d_ProjectionMatrix;
uniform mat3 x3d_NormalMatrix;
out vec3 local;
out vec3 normal;
void main() {
    local = x3d_Vertex.xyz;
    normal = x3d_NormalMatrix * x3d_Normal;
    gl_Position = x3d_ProjectionMatrix * x3d_ModelViewMatrix * x3d_Vertex;
}
#endif
#ifdef X3D_FRAGMENT_SHADER
uniform vec3 first;
uniform vec3 second;
uniform float width;
uniform x3d_LightSourceParameters x3d_LightSource[x3d_MaxLights];
in vec3 local;
in vec3 normal;
out vec4 colour;
void main() {
    float band = step(0.5, fract((local.x + local.y + local.z) / width));
    float lit = max(dot(normalize(normal), normalize(-x3d_LightSource[0].direction)), 0.0);
    colour = vec4(mix(first, second, band) * (0.25 + 0.75 * lit), 1.0);
}
#endif
