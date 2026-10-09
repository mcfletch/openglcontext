// The tone curves of OpenGLContext.passes.tonemapping, chosen by
// `toneMapping` (0 none, 1 aces_narkowicz, 2 aces_hill,
// 3 aces_hill_exposure_boost, 4 khr_pbr_neutral), and their inverses.
//
// The curves and their constants are those of X_ITE 16.4.3's
// ToneMapping2.glsl (MIT licence, copyright (c) 2009 Holger Seelig and
// other contributors; see license.txt): Narkowicz's ACES fit, Stephen
// Hill's ACES fit with its input and output matrices, the same with the
// colour divided by 0.6, and the Khronos PBR Neutral curve.

uniform int toneMapping;   // the curve, as above; 0 is none
// Which materials are lit in linear light: 0 srgb, 1
// linear_when_physical_material, 2 linear. With 1 or 2 the frame is
// encoded to sRGB as it is written.
uniform int colorSpace;

// Whether the frame's colours are encoded to sRGB as they are written
bool frameLinear() {
    return colorSpace != 0;
}

vec3 toneAcesNarkowicz(vec3 x) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

// Hill's fit works in the ACES colour space; GLSL's mat3 takes columns
const mat3 ACES_INPUT = mat3(0.59719, 0.07600, 0.02840,
                             0.35458, 0.90834, 0.13383,
                             0.04823, 0.01566, 0.83777);
const mat3 ACES_OUTPUT = mat3(1.60475, -0.10208, -0.00327,
                              -0.53108, 1.10813, -0.07276,
                              -0.07367, -0.00605, 1.07602);

vec3 toneAcesHill(vec3 x) {
    vec3 v = ACES_INPUT * x;
    vec3 a = v * (v + 0.0245786) - 0.000090537;
    vec3 b = v * (0.983729 * v + 0.4329510) + 0.238081;
    return clamp(ACES_OUTPUT * (a / b), 0.0, 1.0);
}

const float NEUTRAL_START = 0.8 - 0.04;
const float NEUTRAL_DESATURATION = 0.15;

vec3 toneKhronosNeutral(vec3 color) {
    float low = min(color.r, min(color.g, color.b));
    float offset = low < 0.08 ? low - 6.25 * low * low : 0.04;
    color -= offset;
    float peak = max(color.r, max(color.g, color.b));
    if (peak < NEUTRAL_START) return color;
    const float d = 1.0 - NEUTRAL_START;
    float newPeak = 1.0 - d * d / (peak + d - NEUTRAL_START);
    color *= newPeak / peak;
    float g = 1.0 - 1.0 / (NEUTRAL_DESATURATION * (peak - newPeak) + 1.0);
    return mix(color, vec3(newPeak), g);
}

// `x` through the curve `toneMapping` names
vec3 toneCurve(vec3 x) {
    if (toneMapping == 1) return toneAcesNarkowicz(x);
    if (toneMapping == 2) return toneAcesHill(x);
    if (toneMapping == 3) return toneAcesHill(x / 0.6);
    if (toneMapping == 4) return toneKhronosNeutral(x);
    return x;
}

// The colour toneCurve takes to `y`, for y in [0, 1]
vec3 untoneCurve(vec3 y) {
    y = clamp(y, 0.0, 1.0);
    if (toneMapping == 1) {
        const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
        y = min(y, vec3(1.0 - 1e-6));
        vec3 qa = c * y - a, qb = d * y - b, qc = e * y;
        return (-qb - sqrt(max(qb * qb - 4.0 * qa * qc, 0.0))) / (2.0 * qa);
    }
    if (toneMapping == 2 || toneMapping == 3) {
        vec3 f = clamp(inverse(ACES_OUTPUT) * y, 0.0, 1.0);
        vec3 qa = 1.0 - 0.983729 * f;
        vec3 qb = 0.0245786 - 0.4329510 * f;
        vec3 qc = -(0.000090537 + 0.238081 * f);
        vec3 v = (-qb + sqrt(max(qb * qb - 4.0 * qa * qc, 0.0))) / (2.0 * qa);
        vec3 x = inverse(ACES_INPUT) * v;
        return toneMapping == 3 ? x * 0.6 : x;
    }
    if (toneMapping == 4) {
        y = min(y, vec3(1.0 - 1e-6));
        float newPeak = max(y.r, max(y.g, y.b));
        vec3 color = y;
        if (newPeak >= NEUTRAL_START) {
            const float d = 1.0 - NEUTRAL_START;
            float peak = d * d / (1.0 - newPeak) - d + NEUTRAL_START;
            float g = 1.0 - 1.0 / (NEUTRAL_DESATURATION * (peak - newPeak) + 1.0);
            color = (y - g * newPeak) / (1.0 - g) * (peak / newPeak);
        }
        float low = max(min(color.r, min(color.g, color.b)), 0.0);
        float original = low < 0.04 ? sqrt(low / 6.25) : low + 0.04;
        return color + (original - low);
    }
    return y;
}
