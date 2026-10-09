#version 330 core
/* One particle.
 *
 * With a texture the particle is the texture, multiplied by its colour, so a
 * smoke puff or a flame frame drops in with no change here.
 *
 * Without one, a round particle (uRound) is a soft dot computed here: a radial
 * falloff over the quad, squared so the core reads bright and the edge fades
 * out rather than ending on a visible circle.  That is enough for sparks,
 * embers, glows and explosions, and it means a particle system needs no asset
 * at all.  A particle that is not round is its colour, edge to edge.
 *
 * A lit system (uLit) shades that colour as the diffuse colour by X3D's
 * Phong equation (_phong_inc.glsl), with the material's emissive and
 * specular colours, ambient intensity and shininess.
 */

#define MAX_LIGHTS 8
#include "_lights_inc.glsl"
#include "_phong_inc.glsl"

in vec2 vCorner;
in vec2 vTexCoord;
in vec4 vColor;
in float vRandom;

uniform sampler2D uTexture;
uniform bool uHasTexture;
uniform bool uRound;
uniform float uCutoff;                    // fragments at or below this alpha are discarded
uniform bool uLit;
uniform vec3 uEmissive;
uniform vec3 uSpecular;
uniform float uAmbientIntensity;
uniform float uShininess;

in vec3 vEyePosition;
in vec3 vEyeNormal;

out vec4 fragColor;

void main() {
    vec4 sprite = vec4(1.0);
    if (uHasTexture) {
        sprite = texture(uTexture, vTexCoord);
    } else if (uRound) {
        /* length() of the corner is 0 at the centre and 0.5 at the edge
         * midpoints; scaling by 2 puts the falloff's zero on the inscribed
         * circle, so the quad's corners are fully transparent and the sprite
         * never shows its own square. */
        float radius = clamp(1.0 - length(vCorner) * 2.0, 0.0, 1.0);
        sprite = vec4(1.0, 1.0, 1.0, radius * radius);
    }
    fragColor = sprite * vColor;
    if (uLit) {
        vec3 N = normalize(gl_FrontFacing ? vEyeNormal : -vEyeNormal);
        float lit[MAX_LIGHTS];
        for (int i = 0; i < MAX_LIGHTS; i++) lit[i] = 1.0;
        vec3 diffuse = fragColor.rgb;
        fragColor.rgb = clamp(uEmissive + phongLights(N, normalize(-vEyePosition), vEyePosition,
                                                      diffuse, uAmbientIntensity * diffuse,
                                                      uSpecular, uShininess, lit), 0.0, 1.0);
    }
    /* A fully transparent fragment still costs a blend and, in an alpha-blended
     * system, still writes nothing useful; discarding it is measurably cheaper
     * on the heavy overdraw a particle cloud produces. An opaque system cuts
     * its texture's transparent parts out at one half. */
    if (fragColor.a <= uCutoff) {
        discard;
    }
}
