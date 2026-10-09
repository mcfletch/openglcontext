// The HDR colour the bloom composite (the tone curve, then the sRGB encoding
// where the frame is encoded) turns into `shown`, a display colour in
// [0, 1]: what a colour given as displayed is written as, where bloom
// tone-maps afterwards. Needs sRGBToLinear from _common_inc.glsl. Included
// by pbr.frag, volume.frag and gaussian_splat.vert.
#include "_tonemap_inc.glsl"

vec3 untoned(vec3 shown) {
    vec3 y = clamp(shown, 0.0, 1.0);
    if (frameLinear()) y = sRGBToLinear(y);
    return untoneCurve(y);
}
