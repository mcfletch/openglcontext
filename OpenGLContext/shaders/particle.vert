#version 330 core
/* Camera-facing particle quads: one instanced draw for a whole system.
 *
 * The billboard is built in *eye* space.  The particle's centre goes through
 * uModelView, and the quad's corner is then added to its x and y.  Offsetting
 * after the view transform is what makes the quad face the camera exactly, at
 * any camera orientation, with no per-particle matrix and no work on the CPU.
 *
 * uModelView is the *view* matrix for a world-space system (whose particles are
 * already in world coordinates) and the full *model-view* for a local-space one
 * (whose particles are in the emitter's own frame).  The node picks which to
 * send, so there is no branch here and none per vertex.
 *
 * A particle's colour and size come from its normalised age rather than from
 * per-instance data: the two ends of each curve are uniforms shared by the whole
 * system, so ageing costs no bandwidth at all.
 */

layout(location = 0) in vec2 aCorner;     // the unit quad, -0.5 .. 0.5
layout(location = 1) in vec4 aParticle;   // xyz position, w base size
layout(location = 2) in vec3 aParams;     // rotation, life fraction, random

uniform mat4 uModelView;
uniform mat4 uProjection;
uniform vec2 uSizeRange;                  // size multiplier at birth, at death
uniform vec4 uStartColor;
uniform vec4 uEndColor;

out vec2 vCorner;
out vec4 vColor;
out float vRandom;

void main() {
    float life = clamp(aParams.y, 0.0, 1.0);

    /* GL_FALSE on the upload plus a C-contiguous numpy array means GLSL sees
     * the transpose of this renderer's row-vector matrix, so the ordinary
     * column-vector product here is the row-vector product intended. */
    vec4 centre = uModelView * vec4(aParticle.xyz, 1.0);

    float size = aParticle.w * mix(uSizeRange.x, uSizeRange.y, life);
    float c = cos(aParams.x);
    float s = sin(aParams.x);
    vec2 corner = vec2(aCorner.x * c - aCorner.y * s,
                       aCorner.x * s + aCorner.y * c) * size;
    centre.xy += corner;

    gl_Position = uProjection * centre;
    vCorner = aCorner;
    vColor = mix(uStartColor, uEndColor, life);
    vRandom = aParams.z;
}
