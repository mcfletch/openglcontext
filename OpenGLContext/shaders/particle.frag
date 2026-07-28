#version 330 core
/* One particle sprite.
 *
 * Without a texture the sprite is a soft round dot computed here: a radial
 * falloff over the quad, squared so the core reads bright and the edge fades
 * out rather than ending on a visible circle.  That is enough for sparks,
 * embers, glows and explosions, and it means a particle system needs no asset
 * at all -- which is what lets an effect be one line of code.
 *
 * With a texture the sprite is the texture, multiplied by the life colour, so
 * a smoke puff or a flame frame drops in with no change here.
 */

in vec2 vCorner;
in vec4 vColor;
in float vRandom;

uniform sampler2D uTexture;
uniform bool uHasTexture;

out vec4 fragColor;

void main() {
    vec4 sprite;
    if (uHasTexture) {
        sprite = texture(uTexture, vCorner + 0.5);
    } else {
        /* length() of the corner is 0 at the centre and 0.5 at the edge
         * midpoints; scaling by 2 puts the falloff's zero on the inscribed
         * circle, so the quad's corners are fully transparent and the sprite
         * never shows its own square. */
        float radius = clamp(1.0 - length(vCorner) * 2.0, 0.0, 1.0);
        sprite = vec4(1.0, 1.0, 1.0, radius * radius);
    }
    fragColor = sprite * vColor;
    /* A fully transparent fragment still costs a blend and, in an alpha-blended
     * system, still writes nothing useful; discarding it is measurably cheaper
     * on the heavy overdraw a particle cloud produces. */
    if (fragColor.a <= 0.002) {
        discard;
    }
}
