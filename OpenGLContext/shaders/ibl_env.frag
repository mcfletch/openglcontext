#version 330 core

// Render one face of the environment cube from a procedural *studio* environment:
// a sky/ground gradient plus a few bright soft "softbox" panels. The panels are
// HDR (values > 1), so prefiltering them gives metals crisp studio highlights --
// much closer to the neutral reference environment than a plain sky gradient.

#include "_cubemap_inc.glsl"   // faceDir

in vec2 vUV;
out vec4 fragColor;

uniform int faceIndex;   // 0=+X 1=-X 2=+Y 3=-Y 4=+Z 5=-Z

vec3 studioEnv(vec3 d) {
    // Dark neutral studio with a few big bright soft panels -- the classic product
    // shot that makes metal read as *metal*: the body reflects the dark surround
    // (goes dark) while the soft panels reflect as bright highlights, so the metal
    // shows strong bright-on-dark contrast instead of a flat, evenly-lit wash.
    // Neutral hue keeps a gold metal reading gold rather than olive.
    // Bright upper hemisphere over a dark floor: even when a satin metal blurs the
    // reflection, the bright-top -> dark-bottom gradient survives, so the metal
    // shows a directional sheen rather than a flat wash. Strong soft panels add
    // the bright highlights.
    // Moderate brightness, high *contrast*: what reads as metal is the contrast
    // between bright highlights and dark surround, not overall brightness -- an
    // over-bright env just washes every colour (metal and dielectric) toward
    // white. Moderate hemisphere over a dark floor, plus HDR panels for highlights.
    float t = clamp(d.y * 0.5 + 0.5, 0.0, 1.0);
    vec3 sky = vec3(0.55, 0.56, 0.58);
    vec3 horizon = vec3(0.32, 0.32, 0.33);
    vec3 ground = vec3(0.03, 0.03, 0.03);
    vec3 c = mix(horizon, sky, smoothstep(0.45, 1.0, t));
    c = mix(c, ground, smoothstep(0.45, 0.0, t));

    // broad soft key panels (low cosine power = large area, survives roughness
    // blur as a visible highlight; HDR intensity so highlights stay bright).
    vec3 key = normalize(vec3( 0.45, 0.75,  0.55));   // main, upper-right
    vec3 fill = normalize(vec3(-0.75, 0.35,  0.30));   // softer fill, left
    vec3 rim = normalize(vec3( 0.15, 0.45, -0.90));   // rim, behind
    float k = max(dot(d, key), 0.0);
    float f = max(dot(d, fill), 0.0);
    float r = max(dot(d, rim), 0.0);
    c += 7.0 * pow(k, 60.0) + 1.6 * pow(k, 10.0);
    c += 3.0 * pow(f, 40.0) + 0.7 * pow(f, 8.0);
    c += 4.5 * pow(r, 90.0);
    return c;
}

void main() {
    vec3 dir = normalize(faceDir(faceIndex, vUV));
    fragColor = vec4(studioEnv(dir), 1.0);
}
