#version 330 core
in vec2 vUV; in vec3 vEyePos; in vec3 vEyeN;
uniform sampler2D atlas;
uniform vec3 sunDirEye, sunColor, skyAmbient, groundAmbient;
uniform float fogDensity; uniform vec3 fogColor;
uniform vec3 uUpEye;                 // world +Y in eye space: hemisphere-ambient split axis
uniform float uLodStart, uLodEnd;    // mesh->impostor cross-fade window, shared with veg_billboard.frag so the handoff stays seamless
out vec4 fragColor;
vec3 aces(vec3 x){const float a=2.51,b=0.03,c=2.43,d=0.59,e=0.14;return clamp((x*(a*x+b))/(x*(c*x+d)+e),0.,1.);}
void main(){
    vec4 t=texture(atlas,vUV);
    if(t.a<0.33) discard;   // alpha CUTOUT (not blend) -> depth-correct, no foliage bleed
    // dithered LOD cross-fade: the near-mesh dithers OUT with distance while the
    // impostor dithers IN on the complementary pixels (no blended ghosting).
    float lodf=smoothstep(uLodStart,uLodEnd,length(vEyePos));
    float dth=fract(sin(dot(gl_FragCoord.xy,vec2(12.9898,78.233)))*43758.5453);
    if(lodf>dth) discard;
    vec3 alb=pow(t.rgb,vec3(2.2));
    vec3 N=normalize(vEyeN); if(!gl_FrontFacing) N=-N;
    float ndl=max(dot(N,-sunDirEye),0.0);
    vec3 amb=mix(groundAmbient,skyAmbient,clamp(dot(N,uUpEye)*0.5+0.5,0.,1.));
    vec3 col=alb*(amb+sunColor*ndl);
    if(fogDensity>0.0){float f=1.-exp(-fogDensity*length(vEyePos));col=mix(col,fogColor,clamp(f,0.,1.));}
    col=aces(col);
    fragColor=vec4(pow(col,vec3(1.0/2.2)),1.0);
}
