#version 330 core
layout(location=0) in vec3 aPosition;   // world-space terrain vertex
layout(location=1) in vec3 aNormal;     // world-space normal
uniform mat4 uModelView;
uniform mat4 uProjection;
uniform mat3 uNormalMatrix;             // world-normal -> eye-normal
out vec3 vEyePos;
out vec3 vWorldPos;
out vec3 vWorldNormal;
void main(){
    vec4 eye = uModelView * vec4(aPosition,1.0);
    vEyePos = eye.xyz;
    vWorldPos = aPosition;
    vWorldNormal = normalize(aNormal);
    gl_Position = uProjection * eye;
}
