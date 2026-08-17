#version 330 core
in vec2 vUV; in vec3 vEyePos; in vec3 vEyeN; in float vShade;
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
    float dth=fract(gl_FragCoord.x*0.7548776662+gl_FragCoord.y*0.5698402909);  // R2 dither, no sin()
    if(lodf>dth) discard;
    vec3 alb=t.rgb;   // sRGB texture: hardware already decoded to linear (no pow)
    vec3 N=normalize(vEyeN); if(!gl_FrontFacing) N=-N;
    float ndl=max(dot(N,-sunDirEye),0.0);
    vec3 amb=mix(groundAmbient,skyAmbient,clamp(dot(N,uUpEye)*0.5+0.5,0.,1.));
    // vShade is how much of the sun this instance stands in: the canopy
    // takes the key light, and leaves the ambient it does not block.
    vec3 col=alb*(amb*mix(0.55,1.0,vShade)+sunColor*ndl*vShade);
    if(fogDensity>0.0){float f=1.-exp(-fogDensity*length(vEyePos));col=mix(col,fogColor,clamp(f,0.,1.));}
    col=aces(col);
    fragColor=vec4(pow(col,vec3(1.0/2.2)),1.0);
}
