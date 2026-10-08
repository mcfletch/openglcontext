// X3D's texture projectors (OpenGLContext.scenegraph.textureprojector): each
// modulates the diffuse colour where its picture falls, on faces turned
// toward it. The pictures are layers of one array texture
// (OpenGLContext.passes.projectorpass). A projector's scope is a light's: its
// bit, PROJECTOR_SCOPE_BIT plus its slot, of lightsOff is set where it does
// not reach the draw.
//
// The includer declares lightsOff (_lights_inc.glsl) and sets
// TEXTURE_PROJECTORS to 1 where the program has a sampler for the pictures.

#ifndef TEXTURE_PROJECTORS
#define TEXTURE_PROJECTORS 0
#endif

#define MAX_PROJECTORS 4
#define PROJECTOR_SCOPE_BIT 16

uniform int projectorCount;                    // 0: none this frame
uniform mat4 projectorMatrix[MAX_PROJECTORS];   // world to the projector's clip space
uniform vec4 projectorColor[MAX_PROJECTORS];    // rgb its colour, a its intensity
uniform vec4 projectorPlace[MAX_PROJECTORS];    // xyz where it is, w 1 for a perspective
uniform vec4 projectorAim[MAX_PROJECTORS];      // xyz its direction; w bit 0 near-bounded, bit 1 far-bounded
#if TEXTURE_PROJECTORS
uniform sampler2DArray projectorImages;
#endif

// The colour the projectors cast at a world-space point whose world-space
// normal is `normal`: white where none falls.
vec3 projectedColor(vec3 world, vec3 normal) {
    vec3 found = vec3(1.0);
#if TEXTURE_PROJECTORS
    for (int i = 0; i < MAX_PROJECTORS; ++i) {
        if (i >= projectorCount) break;
        if ((lightsOff & (1 << (PROJECTOR_SCOPE_BIT + i))) != 0) continue;
        vec4 clip = projectorMatrix[i] * vec4(world, 1.0);
        if (clip.w <= 0.0) continue;
        vec3 ndc = clip.xyz / clip.w;
        if (any(greaterThan(abs(ndc.xy), vec2(1.0)))) continue;
        int bounds = int(projectorAim[i].w);
        if ((bounds & 1) != 0 && ndc.z < -1.0) continue;
        if ((bounds & 2) != 0 && ndc.z > 1.0) continue;
        vec3 toward = projectorPlace[i].w > 0.5 ? projectorPlace[i].xyz - world
                                                : -projectorAim[i].xyz;
        if (dot(normal, toward) <= 0.0) continue;
        vec4 texel = texture(projectorImages, vec3(ndc.xy * 0.5 + 0.5, float(i)));
        found *= mix(vec3(1.0), texel.rgb * projectorColor[i].rgb,
                     clamp(texel.a * projectorColor[i].a, 0.0, 1.0));
    }
#endif
    return found;
}
