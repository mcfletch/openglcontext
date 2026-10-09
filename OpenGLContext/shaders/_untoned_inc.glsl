// The linear HDR colour the bloom composite (ACES, then sRGB) turns into
// `shown`, a display colour in [0, 1]: what a colour X3D gives as it is
// displayed is written as, where bloom tone-maps afterwards. The ACES curve
// is a ratio of quadratics, so each channel is the root of one. Needs
// sRGBToLinear from _common_inc.glsl. Included by pbr.frag and
// gaussian_splat.vert.
vec3 untoned(vec3 shown) {
    const float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    vec3 y = clamp(sRGBToLinear(clamp(shown, 0.0, 1.0)), 0.0, 1.0);
    vec3 qa = c * y - a, qb = d * y - b, qc = e * y;
    return (-qb - sqrt(max(qb * qb - 4.0 * qa * qc, 0.0))) / (2.0 * qa);
}
