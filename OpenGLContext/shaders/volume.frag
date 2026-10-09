#version 330 core
/* An X3D volume, drawn by marching each pixel's ray through its voxels.
 *
 * The ray runs from the near plane to the far one through this fragment. It
 * is clipped to the volume's box and, where the pass has copied the opaque
 * scene's depth (uSceneDepth), to the first opaque surface, so geometry
 * inside or in front of the volume hides what is behind it. Samples are one
 * uStep (in voxels) apart, offset by a fixed per-pixel fraction of a step.
 *
 * The render styles are generated (OpenGLContext.scenegraph.volumestyles) and
 * spliced in at the marker below: volumeStyle(s) is one sample's colour and
 * opacity. VOLUME_MODE says what is done with them:
 *
 *   0  front-to-back compositing; each sample's opacity is for one voxel's
 *      thickness and is corrected for the step;
 *   1  ProjectionVolumeStyle: the voxels' greatest, least or mean intensity
 *      along the ray, or the first local maximum past a threshold;
 *   2  IsoSurfaceVolumeData: where the ray crosses a surface value, that
 *      surface's style, composited front to back.
 *
 * In a pick's draw (uPickPass) the fragment's depth is that of the first
 * sample at which the volume has become half opaque, and a ray that never
 * does is discarded, so a pick reaches the first non-transparent voxel.
 *
 * Colours are X3D's as displayed: fogged by X3D's fog, not tone-mapped, and
 * written as the linear light the bloom composite displays as them where
 * bloom is on. Alpha is straight, for the pass's SRC_ALPHA blend.
 *
 * The volume's slices lie in its XY plane, the first at -Z and each next one
 * further along +Z (19775-1, 41.2.2.1): s, t and r run along X, Y and Z.
 */

#ifndef MAX_LIGHTS
#define MAX_LIGHTS 8
#endif
#ifndef VOLUME_MODE
#define VOLUME_MODE 0
#endif
#ifndef VOLUME_GRADIENT
#define VOLUME_GRADIENT 0
#endif
#ifndef VOLUME_SEGMENTED
#define VOLUME_SEGMENTED 0
#endif
#ifndef VOLUME_SKIP_CLEAR
#define VOLUME_SKIP_CLEAR 0
#endif
#ifndef VOLUME_GRADIENT_TEXTURE
#define VOLUME_GRADIENT_TEXTURE 0
#endif

#include "_common_inc.glsl"
#include "_lights_inc.glsl"
#include "_phong_inc.glsl"
#include "_x3d_fog_inc.glsl"
#include "_untoned_inc.glsl"

layout(location = 0) out vec4 fragColor;
layout(location = 1) out vec4 fragObjectId;

uniform mat4 uProjection;
uniform mat4 uInverseModelView;
uniform mat4 uInverseProjection;
uniform vec3 uDimensions;          // the box's size in the volume's own units
uniform vec3 uVoxels;              // the data's size in voxels: width, height, depth
uniform vec4 uViewport;            // the view's rectangle in the window, pixels
uniform sampler3D uVolume;
uniform sampler2D uSceneDepth;     // the opaque scene's depth, the view's size
uniform bool uHasSceneDepth;
uniform float uStep;               // voxels between samples
uniform int uMaxSteps;
uniform bool hdrOutput;
uniform uint objectId;             // the pick's id for the volume
// A pick's draw: the depth of the first sample where the volume is half opaque,
// and nothing where it never is (19775-1, 41.2.4.3).
uniform bool uPickPass;

// The generated section declares the rest: the styles' values and textures,
// `segments` and `segmentsOff`, `gradients`, the isosurfaces (isoCount,
// isoValues, isoStyles, isoTolerance) and the projection's projectionType
// (0 MAX, 1 MIN, 2 AVERAGE) and projectionThreshold.

// One sample along the ray: what a style is given.
struct VSample {
    vec3 tc;          // texture coordinate
    vec4 voxel;       // the voxel's colour channels (Table 41.6)
    vec3 position;    // eye space
    vec3 V;           // unit vector toward the viewer, eye space
    vec3 normal;      // unit surface normal, eye space
    float gradient;   // |grad f|, value per voxel
    int segment;      // SegmentedVolumeData's identifier
    int surface;      // IsoSurfaceVolumeData's style index
};

mat3 normalMatrix;

vec3 texCoord(vec3 local) {
    return local / uDimensions + 0.5;
}

// `tc` held half a texel inside the texture, so linear filtering never reaches
// across to the opposite face of a repeating texture.
vec3 inside(sampler3D tex, vec3 tc) {
    vec3 half_ = 0.5 / vec3(textureSize(tex, 0));
    return clamp(tc, half_, 1.0 - half_);
}

float valueAt(sampler3D tex, vec3 tc) {
    return textureLod(tex, inside(tex, tc), 0.0).r;
}

// A direction in the volume's own coordinates, as a unit vector in eye space;
// `fallback` where it has no length.
vec3 eyeNormal(vec3 local, vec3 fallback) {
    vec3 eye = normalMatrix * local;
    float size = length(eye);
    return size > 1e-6 ? eye / size : fallback;
}

// The normal and |grad f| at s from the first component of `tex`.
void gradientOf(inout VSample s, sampler3D tex) {
    vec3 size = vec3(textureSize(tex, 0));
    vec3 d = 1.0 / size;
    vec3 g = 0.5 * vec3(
        valueAt(tex, s.tc + vec3(d.x, 0.0, 0.0)) - valueAt(tex, s.tc - vec3(d.x, 0.0, 0.0)),
        valueAt(tex, s.tc + vec3(0.0, d.y, 0.0)) - valueAt(tex, s.tc - vec3(0.0, d.y, 0.0)),
        valueAt(tex, s.tc + vec3(0.0, 0.0, d.z)) - valueAt(tex, s.tc - vec3(0.0, 0.0, d.z)));
    s.gradient = length(g);
    // Per unit length in the volume's own coordinates; the normal points from
    // higher values to lower.
    vec3 local = g * size / uDimensions;
    s.normal = eyeNormal(-local, s.V);
}

// A surfaceNormals texture's normal at `tc`: R, G, B as X, Y, Z from -1 to 1.
vec3 textureNormal(sampler3D tex, vec3 tc) {
    return eyeNormal(textureLod(tex, inside(tex, tc), 0.0).rgb * 2.0 - 1.0, vec3(0.0, 0.0, 1.0));
}

// The unit vector from `position` toward light i; false where the light is
// off, scoped away or out of its radius.
bool towardLight(int i, vec3 position, out vec3 L) {
    L = vec3(0.0, 0.0, 1.0);
    if (i >= numLights || (lightsOff & (1 << i)) != 0 || lightType[i] == LIGHT_OFF) {
        return false;
    }
    if (lightType[i] == LIGHT_DIRECTIONAL) {
        L = normalize(-lightDirection[i]);
        return true;
    }
    vec3 towards = lightPosition[i].xyz - position;
    float distance = length(towards);
    if (lightRadius[i] > 0.0 && distance > lightRadius[i]) {
        return false;
    }
    L = towards / max(distance, 1e-4);
    return true;
}

// ToneMappedVolumeStyle's Gooch shading: each light's mix of warm and cool.
vec3 toneMapped(vec3 n, vec3 position, vec3 warm, vec3 cool) {
    vec3 colour = vec3(0.0);
    for (int i = 0; i < MAX_LIGHTS; i++) {
        vec3 L;
        if (!towardLight(i, position, L)) continue;
        float cc = (1.0 + dot(L, n)) * 0.5;
        colour += cc * warm + (1.0 - cc) * cool;
    }
    return clamp(colour, 0.0, 1.0);
}

// ShadedVolumeStyle's lights: X3D's Phong terms (_phong_inc.glsl) on the side
// of the surface the viewer sees.
vec3 shadedLights(vec3 n, VSample s, vec3 diffuse, vec3 ambient, vec3 specular,
                  float shininess) {
    if (dot(n, s.V) < 0.0) n = -n;
    float shadows[MAX_LIGHTS];
    for (int i = 0; i < MAX_LIGHTS; i++) shadows[i] = 1.0;
    return phongLights(n, s.V, s.position, diffuse, ambient, specular, shininess, shadows);
}

// @VOLUME_STYLES@

vec3 unproject(vec2 ndc, float z) {
    vec4 eye = uInverseProjection * vec4(ndc, z, 1.0);
    return eye.xyz / eye.w;
}

// The ray: from the near plane (t 0) away from the viewer, in eye space and
// in the volume's own coordinates.
vec3 nearEye, rayEye, nearLocal, rayLocal, viewer;

// The sample at t with its voxel read; complete() adds what the styles read
// besides.
VSample voxelAt(float t) {
    VSample s;
    s.tc = inside(uVolume, texCoord(nearLocal + rayLocal * t));
    s.voxel = textureLod(uVolume, s.tc, 0.0);
    s.position = nearEye + rayEye * t;
    s.V = viewer;
    s.normal = viewer;
    s.gradient = 0.0;
    s.segment = 0;
    s.surface = 0;
    return s;
}

void complete(inout VSample s) {
#if VOLUME_GRADIENT
    gradientOf(s, uVolume);
#endif
#if VOLUME_SEGMENTED
    ivec3 size = textureSize(segments, 0);
    ivec3 cell = clamp(ivec3(s.tc * vec3(size)), ivec3(0), size - 1);
    s.segment = int(texelFetch(segments, cell, 0).r * 255.0 + 0.5);
#endif
}

VSample sampleAt(float t) {
    VSample s = voxelAt(t);
    complete(s);
    return s;
}

// One sample's colour as it is composited: fogged by its distance.
vec3 seen(vec3 colour, vec3 position) {
    return x3dFogged(clamp(colour, 0.0, 1.0), length(position));
}

void main() {
    fragObjectId = encodeObjectId(objectId);
    normalMatrix = transpose(mat3(uInverseModelView));
    vec2 ndc = (gl_FragCoord.xy - uViewport.xy) / uViewport.zw * 2.0 - 1.0;
    // The far point is taken half way into the depth range: a projection whose
    // far plane is very far away (or at infinity) unprojects z 1 to no point.
    nearEye = unproject(ndc, -1.0);
    rayEye = unproject(ndc, 0.0) - nearEye;
    viewer = -normalize(rayEye);
    nearLocal = (uInverseModelView * vec4(nearEye, 1.0)).xyz;
    rayLocal = (uInverseModelView * vec4(rayEye, 0.0)).xyz;

    // The box's span along the ray.
    vec3 safe = mix(rayLocal, vec3(1e-12), lessThan(abs(rayLocal), vec3(1e-12)));
    vec3 t0 = (-0.5 * uDimensions - nearLocal) / safe;
    vec3 t1 = (0.5 * uDimensions - nearLocal) / safe;
    vec3 low = min(t0, t1), high = max(t0, t1);
    float enter = max(max(max(low.x, low.y), low.z), 0.0);
    float leave = min(min(high.x, high.y), high.z);
    if (uHasSceneDepth) {
        float depth = texelFetch(uSceneDepth, ivec2(gl_FragCoord.xy - uViewport.xy), 0).r;
        if (depth < 1.0) {
            vec3 opaque = unproject(ndc, depth * 2.0 - 1.0);
            leave = min(leave, dot(opaque - nearEye, rayEye) / dot(rayEye, rayEye));
        }
    }
    if (leave <= enter) {
        discard;
    }
    vec3 voxelSpan = (texCoord(nearLocal + rayLocal * leave)
                      - texCoord(nearLocal + rayLocal * enter)) * uVoxels;
    float voxels = length(voxelSpan);
    int steps = clamp(int(ceil(voxels / uStep)), 1, uMaxSteps);
    float dt = (leave - enter) / float(steps);
    float stepVoxels = voxels / float(steps);
    float jitter = fract(sin(dot(floor(gl_FragCoord.xy), vec2(12.9898, 78.233))) * 43758.5453);

    float hit = -1.0;
#if VOLUME_MODE == 0
    vec4 acc = vec4(0.0);
    for (int i = 0; i < steps; i++) {
        float t = enter + (float(i) + jitter) * dt;
        VSample s = voxelAt(t);
#if VOLUME_SKIP_CLEAR
        // A first component of 0 is transparent whatever these styles do.
        if (s.voxel.r <= 0.0) continue;
#endif
        complete(s);
        vec4 g = volumeStyle(s);
        float a = 1.0 - pow(clamp(1.0 - g.a, 0.0, 1.0), stepVoxels);
        if (a <= 0.0) continue;
        acc.rgb += (1.0 - acc.a) * a * seen(g.rgb, s.position);
        acc.a += (1.0 - acc.a) * a;
        if (hit < 0.0 && acc.a >= 0.5) hit = t;
        if (acc.a >= 0.995) break;
    }
#elif VOLUME_MODE == 1
    float best = projectionType == 1 ? 2.0 : -1.0;
    float bestAlpha = 1.0, bestT = 0.5 * (enter + leave);
    float local_ = -1.0, localAlpha = 1.0, localT = bestT;
    bool rising = false, peaked = false;
    float sum = 0.0, sumAlpha = 0.0;
    for (int i = 0; i < steps; i++) {
        float t = enter + (float(i) + jitter) * dt;
        vec4 voxel = textureLod(uVolume, inside(uVolume, texCoord(nearLocal + rayLocal * t)), 0.0);
        float intensity = (voxel.r + voxel.g + voxel.b) / 3.0;
        sum += intensity;
        sumAlpha += voxel.a;
        if (projectionType == 1 ? intensity < best : intensity > best) {
            best = intensity;
            bestAlpha = voxel.a;
            bestT = t;
        }
        // LMIP: the first maximum past the threshold, once the values fall.
        if (projectionType == 0 && projectionThreshold > 0.0 && !peaked) {
            if (intensity > projectionThreshold && intensity >= local_) {
                rising = true;
                local_ = intensity;
                localAlpha = voxel.a;
                localT = t;
            } else if (rising) {
                peaked = true;
            }
        }
    }
    if (projectionType == 2) {
        best = sum / float(steps);
        bestAlpha = sumAlpha / float(steps);
        bestT = 0.5 * (enter + leave);
    } else if (rising) {
        best = local_;
        bestAlpha = localAlpha;
        bestT = localT;
    }
    vec4 acc = vec4(seen(vec3(best), nearEye + rayEye * bestT) * bestAlpha, bestAlpha);
    if (bestAlpha >= 0.5) hit = bestT;
#else
    vec4 acc = vec4(0.0);
    float tBefore = enter + jitter * dt;
    float before = valueAt(uVolume, texCoord(nearLocal + rayLocal * tBefore));
    for (int i = 1; i < steps + 1; i++) {
        float t = min(enter + (float(i) + jitter) * dt, leave);
        float value = valueAt(uVolume, texCoord(nearLocal + rayLocal * t));
        float nearest = 2.0;
        int which = -1;
        if (value != before) {
            for (int k = 0; k < isoCount; k++) {
                float iso = isoValues[k];
                if ((before - iso) * (value - iso) < 0.0 || (value == iso)) {
                    float share = (iso - before) / (value - before);
                    if (share < nearest) {
                        nearest = share;
                        which = k;
                    }
                }
            }
        }
        if (which >= 0) {
            float tHit = mix(tBefore, t, nearest);
            VSample s = sampleAt(tHit);
#if VOLUME_GRADIENT_TEXTURE
            s.normal = -textureNormal(gradients, s.tc);
#endif
            if (s.gradient > isoTolerance) {
                s.surface = isoStyles[which];
                vec4 g = volumeStyle(s);
                float a = clamp(g.a, 0.0, 1.0);
                acc.rgb += (1.0 - acc.a) * a * seen(g.rgb, s.position);
                acc.a += (1.0 - acc.a) * a;
                if (hit < 0.0 && acc.a >= 0.5) hit = tHit;
                if (acc.a >= 0.995) break;
            }
        }
        before = value;
        tBefore = t;
    }
#endif
    if (uPickPass) {
        if (hit < 0.0) {
            discard;
        }
        vec4 clip = uProjection * vec4(nearEye + rayEye * hit, 1.0);
        gl_FragDepth = 0.5 * clip.z / clip.w + 0.5;
        fragColor = vec4(0.0);
        return;
    }
    gl_FragDepth = gl_FragCoord.z;
    vec3 colour = acc.a > 0.0 ? acc.rgb / acc.a : vec3(0.0);
    fragColor = vec4(hdrOutput ? untoned(colour) : colour, acc.a);
}
