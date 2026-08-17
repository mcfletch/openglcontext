#version 330 core
layout(location=0) in vec3 aPos;     // quad: x in [-0.5,0.5], y in [0,1]
layout(location=1) in vec2 aUV;
layout(location=2) in vec4 aInst;    // x,y,z, yaw
layout(location=3) in float aScale;  // height
layout(location=4) in float aShade;  // sun reaching this instance, 0..1
uniform mat4 uModelView, uProjection;
uniform float uWidth;                // width/height aspect
out vec2 vUV; out vec3 vEyePos; out float vH; out float vShade;
void main(){
    // cylindrical (upright) billboard: quad's horizontal axis faces the camera
    vec3 camRight = vec3(uModelView[0][0], uModelView[1][0], uModelView[2][0]);
    vec3 right = normalize(vec3(camRight.x, 0.0, camRight.z));
    vec3 world = aInst.xyz + right*(aPos.x*uWidth*aScale) + vec3(0.0,1.0,0.0)*(aPos.y*aScale);
    vec4 eye = uModelView*vec4(world,1.0);
    vEyePos=eye.xyz; vUV=aUV; vH=aPos.y; vShade=aShade;
    gl_Position=uProjection*eye;
}
