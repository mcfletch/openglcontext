#version 330 core
in vec2 vUV; in vec3 vEyePos; in float vH; in float vShade;
// The camera each fragment is drawn for, in a shared draw of several views.
#include "_viewer_inc.glsl"
// fogMode, fogDensity, fogColor and x3dFogged().
#include "_x3d_fog_inc.glsl"
uniform sampler2D pine;
uniform vec3 sunColor, skyAmbient, groundAmbient;
uniform float uNearFade; uniform float uFarFade; uniform float uNearCut;
uniform float uLodStart, uLodEnd;   // mesh->impostor cross-fade window, shared with veg_mesh.frag so the handoff stays seamless
uniform float uSunLevel;   // flat sun term for this billboard set; low for grass (near-vertical blades barely face the sun) so impostors match the dark, per-fragment-lit geometry clumps instead of reading as bright flat lumps
out vec4 fragColor;
// The frame's tone curve and exposure (OpenGLContext.passes.tonemapping)
#include "_tonemap_inc.glsl"
uniform float exposure;
void main(){
    vec4 t = texture(pine, vUV);
    if(t.a < 0.4) discard;
    float dth=fract(gl_FragCoord.x*0.7548776662+gl_FragCoord.y*0.5698402909);  // R2 dither, no sin()
    if(uNearFade>0.5){   // tree impostor: dithered cross-fade with the near-mesh.
        // Near the camera it is fully dithered OUT (no translucent card in front of
        // the near-mesh); it dithers IN as the near-mesh dithers out with distance.
        float lodf=smoothstep(uLodStart,uLodEnd,length(toViewer(vEyePos)));
        if(lodf<dth) discard;
    } else if(uFarFade>0.5){   // grass: dissolve across a distance WINDOW so tufts
        // don't pop as the follow-disc recenters on the walking camera.
        float dd=length(toViewer(vEyePos));
        // outer fade toward the disc edge (1 near -> 0 at edge)
        float fout=smoothstep(uFarFade, uFarFade*0.85, dd);
        // optional inner fade-in for the distant layer (uNearCut=0 disables it), so
        // the coarse far cards ramp in exactly where the fine near grass ramps out.
        float fin=(uNearCut>0.5)?smoothstep(uNearCut*0.6, uNearCut, dd):1.0;
        if(min(fin,fout)<dth) discard;
    }
    vec3 lin = t.rgb;   // sRGB texture: hardware already decoded to linear (no pow)
    vec3 amb = mix(groundAmbient, skyAmbient, clamp(vH,0.,1.));
    // vShade is how much of the sun this instance stands in: the canopy
    // takes the key light, and leaves the ambient it does not block.
    vec3 col = lin * (amb*mix(0.55,1.0,vShade) + sunColor*uSunLevel*vShade);
    // The aerial haze (mode 1) is mixed in linear light; X3D's Fog (modes 2 and 3) is
    // mixed into the colour as displayed, as pbr.frag does.
    float eyeDistance = length(toViewer(vEyePos));
    if(fogMode==1) col = x3dFogged(col, eyeDistance);
    vec3 shown = pow(toneCurve(col * exposure), vec3(1.0/2.2));
    if(fogMode>1) shown = x3dFogged(shown, eyeDistance);
    fragColor = vec4(shown, 1.0);
}
