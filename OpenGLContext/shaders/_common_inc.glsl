// Shared constants and colour-space helpers, pulled into the lit and IBL
// shaders so each has exactly one definition. No #version / #extension / precision
// lines here -- the including translation unit owns those (and the compile-time
// defines injected right after its #version). See shaderpass.preprocess_shader.

const float PI     = 3.14159265359;
const float INV_PI = 0.31830988618;

// Accurate piecewise sRGB transfer functions (finding 5.1). pow(c, 2.2) only
// approximates the sRGB curve; the piecewise form has the correct linear segment
// near black, so dark base-colour / emissive texels decode -- and the final
// frame encodes -- without the slight shadow crush the gamma-2.2 shortcut adds.
// step(c, edge) is 1.0 where c <= edge, selecting the linear (toe) segment.
vec3 sRGBToLinear(vec3 c) {
    vec3 lo = c / 12.92;
    vec3 hi = pow((c + 0.055) / 1.055, vec3(2.4));
    return mix(hi, lo, step(c, vec3(0.04045)));
}
vec3 linearToSRGB(vec3 c) {
    c = clamp(c, 0.0, 1.0);
    vec3 lo = c * 12.92;
    vec3 hi = 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055;
    return mix(hi, lo, step(c, vec3(0.0031308)));
}
