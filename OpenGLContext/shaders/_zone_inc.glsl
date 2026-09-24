// Zones: regions whose environment lighting differs from the scene's.
//
// The pass decides per draw which zones reach the object and hands them down
// as layers, bottom first. A layer the object is wholly inside is a constant
// (kind 0); a layer whose surface the object crosses is weighted here, per
// fragment, by the fragment's distance from the zone's shape. Each layer is
// laid over the ones below by its weight, exactly as
// OpenGLContext.scenegraph.zones.layers does on the CPU, and what is left over
// is the scene's own environment.
//
// A draw reaching no zone has zoneLayers == 0, and the only cost left is the
// loop test in zoneShares.

#ifndef MAX_ZONE_LAYERS
#define MAX_ZONE_LAYERS 4
#endif

uniform int zoneLayers;                      // how many of the arrays are in use
uniform int zoneKind[MAX_ZONE_LAYERS];       // 0 whole, 1 box, 2 sphere, 3 ellipsoid,
                                             // 4 capsule, 5 cylinder
uniform mat4 zoneToLocal[MAX_ZONE_LAYERS];   // world -> the shape's rigid frame
uniform vec4 zoneShape[MAX_ZONE_LAYERS];     // the shape's dimensions, by kind
uniform vec4 zoneLight[MAX_ZONE_LAYERS];     // intensity, blend (m), probe layer
                                             // (-1 the scene's, -2 none), unused

// Each layer's share of the environment once scaled by its intensity, for a
// layer read from a probe of its own; and the share read from the scene's
// probe, which gathers the uncovered remainder and every layer that uses the
// scene's environment. zoneAll is the two together, for a path that has only
// the scene's environment to read.
float zoneShare[MAX_ZONE_LAYERS];
float zoneScene = 1.0;
float zoneAll = 1.0;

float zoneDistance(int i, vec3 p) {
    vec4 s = zoneShape[i];
    int kind = zoneKind[i];
    if (kind == 1) {                         // box: half extents
        vec3 q = abs(p) - s.xyz;
        return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0);
    }
    if (kind == 2) {                         // sphere: radius
        return length(p) - s.x;
    }
    if (kind == 3) {                         // ellipsoid: radii
        float k0 = length(p / s.xyz);
        float k1 = length(p / (s.xyz * s.xyz));
        return k1 > 1e-6 ? k0 * (k0 - 1.0) / k1 : -min(s.x, min(s.y, s.z));
    }
    float r1 = s.x;                          // capsule, cylinder: radius below,
    float r2 = s.y;                          // radius above, height
    float h = s.z;
    vec2 q = vec2(length(p.xz), p.y);
    if (kind == 4) {                         // spheres of r1 and r2, h apart
        q.y += 0.5 * h;
        float b = (r1 - r2) / max(h, 1e-6);
        if (abs(b) >= 1.0) {
            return length(q - vec2(0.0, r1 >= r2 ? 0.0 : h)) - max(r1, r2);
        }
        float a = sqrt(1.0 - b * b);
        float k = dot(q, vec2(-b, a));
        if (k < 0.0) return length(q) - r1;
        if (k > a * h) return length(q - vec2(0.0, h)) - r2;
        return dot(q, vec2(a, b)) - r1;
    }
    float half_h = 0.5 * h;                  // capped cone, r1 below, r2 above
    vec2 k1 = vec2(r2, half_h);
    vec2 k2 = vec2(r2 - r1, 2.0 * half_h);
    vec2 ca = vec2(q.x - min(q.x, q.y < 0.0 ? r1 : r2), abs(q.y) - half_h);
    vec2 cb = q - k1 + k2 * clamp(dot(k1 - q, k2) / max(dot(k2, k2), 1e-12), 0.0, 1.0);
    float sgn = (cb.x < 0.0 && ca.y < 0.0) ? -1.0 : 1.0;
    return sgn * sqrt(min(dot(ca, ca), dot(cb, cb)));
}

// One on and inside the surface, nought `blend` metres out.
float zoneWeight(int i, vec3 world) {
    if (zoneKind[i] == 0) return 1.0;
    vec3 p = (zoneToLocal[i] * vec4(world, 1.0)).xyz;
    float d = zoneDistance(i, p);
    float blend = zoneLight[i].y;
    if (blend <= 0.0) return d <= 0.0 ? 1.0 : 0.0;
    return 1.0 - smoothstep(0.0, blend, d);
}

// Work out every layer's share at this fragment. `probes` says whether a
// layer's own probe can be read; where it cannot, the layer reads the
// scene's environment at its own intensity.
void zoneShares(vec3 world, bool probes) {
    zoneScene = 1.0;
    zoneAll = 1.0;
    if (zoneLayers <= 0) return;
    float left = 1.0;
    float scene = 0.0;
    float own = 0.0;
    for (int i = MAX_ZONE_LAYERS - 1; i >= 0; --i) {
        zoneShare[i] = 0.0;
        if (i >= zoneLayers) continue;
        float share = zoneWeight(i, world) * left;
        left -= share;
        vec4 light = zoneLight[i];
        float scaled = share * light.x;
        if (light.z < -1.5) {
            continue;                        // no environment at all
        }
        if (light.z < -0.5 || !probes) {
            scene += scaled;
        } else {
            zoneShare[i] = scaled;
            own += scaled;
        }
    }
    zoneScene = scene + left;
    zoneAll = zoneScene + own;
}
