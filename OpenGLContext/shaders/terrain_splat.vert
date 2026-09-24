#version 330 core
// In a shared draw of several views, each copy is sent on to its view.
#include "_multiview_inc.glsl"
layout(location=2) in vec3 aPosition;   // required: the mesh's own vertex
layout(location=1) in vec3 aNormal;     // required: the mesh's own normal
uniform mat4 uModel;                    // where the world puts the mesh
uniform mat4 uModelView;
uniform mat4 uProjection;
uniform mat3 uNormalMatrix;             // world-normal -> eye-normal
out vec3 vEyePos;
out vec3 vWorldPos;
out vec3 vWorldNormal;
void main(){
    vec4 eye = uModelView * vec4(aPosition,1.0);
    vEyePos = eye.xyz;
    // Which layer is on the ground here is read from world XZ, and a tile of a
    // streamed world is placed by the tileset's own transform -- so the world
    // position is the model's, not the mesh's. A field sits at the origin and
    // this is the identity.
    vWorldPos = (uModel * vec4(aPosition,1.0)).xyz;
    vWorldNormal = normalize(mat3(uModel) * aNormal);
    gl_Position = uProjection * eye;
#ifdef MULTIVIEW_VERTEX
    routeToView(eye.xyz);
#endif
}
