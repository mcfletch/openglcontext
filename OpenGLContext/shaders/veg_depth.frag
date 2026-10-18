#version 330 core
// A shadow map's depth of an instanced tree: what veg_mesh.frag draws, without the light.
in vec2 vUV; in vec3 vEyePos; in vec3 vEyeN; in float vShade;
uniform sampler2D atlas;
void main(){
    if(texture(atlas, vUV).a < 0.33) discard;   // the same alpha cutout the lit pass draws
}
