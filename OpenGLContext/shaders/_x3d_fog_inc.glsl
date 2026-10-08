// Fog by distance d from the viewer. fogMode 0 is no fog; 1 the engine's
// aerial-perspective curve, 1 - exp(-fogDensity d), fogDensity per unit; 2 and
// 3 X3D's (19775-1, 17.2.2.3), applied to a colour as it is displayed, with
// fogDensity 1 / range: LINEAR leaves an object (range - d) / range of its own
// colour, EXPONENTIAL exp(-d / (range - d)).

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
