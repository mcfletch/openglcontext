#version 330 core
in vec2 vUV; in vec3 vEyePos; in float vH; in float vShade;
uniform sampler2D pine;
uniform vec3 sunColor, skyAmbient, groundAmbient;
uniform float fogDensity; uniform vec3 fogColor; uniform float uNearFade; uniform float uFarFade; uniform float uNearCut;
uniform float uLodStart, uLodEnd;   // mesh->impostor cross-fade window, shared with veg_mesh.frag so the handoff stays seamless
uniform float uSunLevel;   // flat sun term for this billboard set; low for grass (near-vertical blades barely face the sun) so impostors match the dark, per-fragment-lit geometry clumps instead of reading as bright flat lumps
out vec4 fragColor;
vec3 aces(vec3 x){const float a=2.51,b=0.03,c=2.43,d=0.59,e=0.14;return clamp((x*(a*x+b))/(x*(c*x+d)+e),0.,1.);}
void main(){
    vec4 t = texture(pine, vUV);
    if(t.a < 0.4) discard;
    float dth=fract(gl_FragCoord.x*0.7548776662+gl_FragCoord.y*0.5698402909);  // R2 dither, no sin()
    if(uNearFade>0.5){   // tree impostor: dithered cross-fade with the near-mesh.
        // Near the camera it is fully dithered OUT (no translucent card in front of
        // the near-mesh); it dithers IN as the near-mesh dithers out with distance.
        float lodf=smoothstep(uLodStart,uLodEnd,length(vEyePos));
        if(lodf<dth) discard;
    } else if(uFarFade>0.5){   // grass: dissolve across a distance WINDOW so tufts
        // don't pop as the follow-disc recenters on the walking camera.
        float dd=length(vEyePos);
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
    if(fogDensity>0.0){ float f=1.-exp(-fogDensity*length(vEyePos)); col=mix(col,fogColor,clamp(f,0.,1.)); }
    col = aces(col);
    fragColor = vec4(pow(col, vec3(1.0/2.2)), 1.0);
}
