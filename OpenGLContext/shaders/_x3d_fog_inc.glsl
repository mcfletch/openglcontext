// X3D's fog (19775-1, 17.2.2.3) applied to a colour as it is displayed: LINEAR
// leaves an object (range - d) / range of its own colour, EXPONENTIAL
// exp(-d / (range - d)). fogDensity is 1 / range; fogMode 0 is no fog and 1 the
// engine's density curve, 1 - exp(-density d).

uniform int   fogMode;
uniform float fogDensity;
uniform vec3  fogColor;

vec3 x3dFogged(vec3 color, float eyeDistance) {
    if (fogMode <= 0 || fogDensity <= 0.0) {
        return color;
    }
    float reach = fogDensity * eyeDistance;
    float fog;
    if (fogMode == 1) {
        fog = 1.0 - exp(-reach);
    } else if (fogMode == 2) {
        fog = reach;
    } else {
        float clear = 1.0 - reach;
        fog = clear > 0.0 ? 1.0 - exp(-reach / clear) : 1.0;
    }
    return mix(color, fogColor, clamp(fog, 0.0, 1.0));
}
