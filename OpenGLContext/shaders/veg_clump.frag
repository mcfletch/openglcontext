#version 330 core
in vec2 vUV; in vec3 vEyePos; in vec3 vEyeN; in float vShade;
// The camera each fragment is drawn for, in a shared draw of several views.
#include "_viewer_inc.glsl"
// fogMode, fogDensity, fogColor and x3dFogged().
#include "_x3d_fog_inc.glsl"
uniform sampler2D atlas;
uniform vec3 sunDirEye, sunColor, skyAmbient, groundAmbient;
uniform float uFadeStart, uFadeEnd;   // dither-dissolve the clump out across this eye-distance window
uniform float uCutStart, uCutEnd;     // dither the clump IN across this inner window (uCutEnd<=0 disables)
uniform vec3 uUpEye;                  // world +Y in eye space: hemisphere-ambient split axis
out vec4 fragColor;
// The frame's tone curve and exposure (OpenGLContext.passes.tonemapping)
#include "_tonemap_inc.glsl"
uniform float exposure;
void main(){
    vec4 t=texture(atlas,vUV);
    if(t.a<0.33) discard;   // alpha CUTOUT (not blend) -> depth-correct, no foliage bleed
    float d = length(toViewer(vEyePos));
    float dth=fract(gl_FragCoord.x*0.7548776662+gl_FragCoord.y*0.5698402909);  // R2 dither, no sin()
    // inner LOD boundary: a coarse far-clump node dithers IN across [uCutStart, uCutEnd]
    // on exactly the pixels a full-detail near-clump node (same window as its outer
    // fade) dithers OUT, so the geometry-LOD handoff shows no seam or double-draw.
    if(uCutEnd>0.0 && (1.0-smoothstep(uCutStart,uCutEnd,d))>=dth) discard;
    // dithered outer dissolve toward the follow-disc edge: real-geometry clumps fade
    // out across [uFadeStart, uFadeEnd] while the impostor billboards dither IN on the
    // complementary pixels, so there's no hard pop as the disc recentres on the walker.
    float keep = 1.0 - smoothstep(uFadeStart, uFadeEnd, d);
    if(keep<dth) discard;
    vec3 alb=t.rgb;   // sRGB texture: hardware already decoded to linear (no pow)
    vec3 N=normalize(vEyeN); if(!gl_FrontFacing) N=-N;
    float ndl=max(dot(N,-sunDirEye),0.0);
    vec3 amb=mix(groundAmbient,skyAmbient,clamp(dot(N,uUpEye)*0.5+0.5,0.,1.));
    // vShade is how much of the sun this instance stands in: the canopy
    // takes the key light, and leaves the ambient it does not block.
    vec3 col=alb*(amb*mix(0.55,1.0,vShade)+sunColor*ndl*vShade);
    // The aerial haze (mode 1) is mixed in linear light; X3D's Fog (modes 2 and 3) is
    // mixed into the colour as displayed, as pbr.frag does.
    float eyeDistance=length(toViewer(vEyePos));
    if(fogMode==1) col=x3dFogged(col,eyeDistance);
    vec3 shown=pow(toneCurve(col * exposure),vec3(1.0/2.2));
    if(fogMode>1) shown=x3dFogged(shown,eyeDistance);
    fragColor=vec4(shown,1.0);
}
