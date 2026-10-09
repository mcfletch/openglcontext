#version 330 core
/* One Gaussian splat's falloff (OpenGLContext.scenegraph.gaussiansplats).
 *
 * vCorner is 1 at three deviations along each of the ellipse's axes, so the
 * Gaussian is exp(-4.5 * |vCorner|^2) and the kernel ends at |vCorner| = 1.
 *
 * The colour draw writes premultiplied colour for GL_ONE,
 * GL_ONE_MINUS_SRC_ALPHA blending, back to front. The id and depth draws
 * (uShadeColour false) keep the splat's core, where its opacity reaches one
 * half, so a pick or a shadow sees the splat where it reads as solid.
 */

#include "_objectid_inc.glsl"

in vec2 vCorner;
flat in vec4 vColour;

uniform bool uShadeColour;
uniform uint uObjectId;

layout(location = 0) out vec4 fragColor;
layout(location = 1) out vec4 fragObjectId;

void main() {
    float r2 = dot(vCorner, vCorner);
    if (r2 > 1.0) {
        discard;
    }
    float alpha = min(0.99, vColour.a * exp(-4.5 * r2));
    if (uShadeColour) {
        if (alpha < 1.0 / 255.0) {
            discard;
        }
        fragColor = vec4(vColour.rgb * alpha, alpha);
    } else {
        if (alpha < 0.5) {
            discard;
        }
        fragColor = vec4(0.0);
    }
    fragObjectId = encodeObjectId(uObjectId);
}
