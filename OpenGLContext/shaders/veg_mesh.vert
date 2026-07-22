#version 330 core
layout(location=0) in vec3 aPos;
layout(location=1) in vec3 aNormal;
layout(location=2) in vec2 aUV;
layout(location=3) in vec4 aInst;    // x,y,z, yaw
layout(location=4) in float aScale;
uniform mat4 uModelView, uProjection;
out vec2 vUV; out vec3 vEyePos; out vec3 vEyeN;
void main(){
    float c=cos(aInst.w), s=sin(aInst.w);
    vec3 lp=aPos*aScale;
    vec3 wp=vec3(c*lp.x+s*lp.z, lp.y, -s*lp.x+c*lp.z)+aInst.xyz;
    vec3 wn=vec3(c*aNormal.x+s*aNormal.z, aNormal.y, -s*aNormal.x+c*aNormal.z);
    vec4 eye=uModelView*vec4(wp,1.0);
    vEyePos=eye.xyz; vEyeN=mat3(uModelView)*wn; vUV=aUV;
    gl_Position=uProjection*eye;
}
