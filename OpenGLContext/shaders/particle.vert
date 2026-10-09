#version 330 core
/* Particles: one instanced draw for a whole system, in one of four shapes.
 *
 * uShape chooses what each particle is drawn as:
 *
 *   0  a sprite: a quad facing the camera, turned by the particle's rotation.
 *      The billboard is built in eye space: the centre goes through
 *      uModelView and the corner is then added to its x and y, so the quad
 *      faces the camera at any camera orientation with no per-particle matrix.
 *   1  a quad in the system's own XY plane, facing +Z.
 *   2  a line along the particle's velocity, as long as the size's height.
 *   3  a point, uPointSize pixels across.
 *
 * uModelView is the view matrix for a world-space system (whose particles are
 * already in world coordinates) and the full model-view for a local-space one
 * (whose particles are in the system's own frame). The node picks which to
 * send, so there is no branch on it here.
 *
 * A particle's colour is its own (aColor, white where the system has no colour
 * ramp) times the system's colour at its age, interpolated between two ends;
 * its size is the system's size times its own factor times the size at its
 * age. A system with texture frames reads its four texture coordinates from
 * uFrames at the frame the particle shows; uTexRows transforms them.
 *
 * A line wider than a pixel (uLineWidth) is a strip of the quad's four
 * corners, its ends where a line's are and its sides uLineWidth pixels apart
 * across the line as it is seen.
 *
 * vEyePosition and vEyeNormal are for a lit system: a quad's normal is the
 * system's +z, a sprite's faces the viewer. The clip planes are in eye space.
 */

layout(location = 0) in vec2 aCorner;     // the unit quad, -0.5 .. 0.5
layout(location = 1) in vec4 aParticle;   // xyz position, w base size
layout(location = 2) in vec4 aParams;     // rotation, life fraction, random, frame
layout(location = 3) in vec4 aParticleColor;  // optional: white where there is no ramp
layout(location = 4) in vec3 aVelocity;   // optional: read by the line shape only

const int MAX_FRAMES = 16;

uniform mat4 uModelView;
uniform mat4 uProjection;
uniform int uShape;
uniform vec2 uSize;                       // width and height in world units
uniform vec2 uSizeRange;                  // size multiplier at birth, at death
uniform vec4 uStartColor;
uniform vec4 uEndColor;
uniform int uFrameCount;                  // 0: the quad's own texture coordinates
uniform vec2 uFrames[MAX_FRAMES * 4];     // lower left, lower right, upper right, upper left
uniform vec3 uPointSize;                  // pixels: scale, least, most
uniform vec3 uPointAttenuation;           // constant, linear, quadratic in eye distance
uniform float uLineWidth;                 // pixels; a strip where above 1
uniform vec2 uViewport;                   // pixels, width and height
uniform mat3 uNormalMatrix;               // the system's frame's normals into eye space
uniform vec3 uTexRows[2];                 // the texture transform's rows for s and t

out vec2 vCorner;
out vec3 vEyePosition;
out vec3 vEyeNormal;
out vec2 vTexCoord;
out vec4 vColor;
out float vRandom;

#include "_clipplane_inc.glsl"

/* Which of the four frame corners each vertex of the strip is. */
const int FRAME_CORNER[4] = int[4](0, 1, 3, 2);

void main() {
    float life = clamp(aParams.y, 0.0, 1.0);
    vec2 size = uSize * aParticle.w * mix(uSizeRange.x, uSizeRange.y, life);
    vec4 centre;

    /* GL_FALSE on the upload plus a C-contiguous numpy array means GLSL sees
     * the transpose of this renderer's row-vector matrix, so the ordinary
     * column-vector product here is the row-vector product intended. */
    if (uShape == 1) {
        centre = uModelView * vec4(aParticle.xyz + vec3(aCorner * size, 0.0), 1.0);
    } else if (uShape == 2) {
        float speed = length(aVelocity);
        vec3 along = speed > 0.0 ? aVelocity / speed : vec3(0.0);
        centre = uModelView * vec4(aParticle.xyz + along * (aCorner.y * size.y), 1.0);
    } else {
        centre = uModelView * vec4(aParticle.xyz, 1.0);
        if (uShape == 0) {
            float c = cos(aParams.x);
            float s = sin(aParams.x);
            vec2 corner = aCorner * size;
            centre.xy += vec2(corner.x * c - corner.y * s,
                              corner.x * s + corner.y * c);
        }
    }
    if (uShape == 3) {
        float distance = length(centre.xyz);
        float divisor = uPointAttenuation.x + uPointAttenuation.y * distance
                      + uPointAttenuation.z * distance * distance;
        float pixels = divisor > 0.0 ? uPointSize.x / divisor : uPointSize.z;
        gl_PointSize = clamp(pixels, uPointSize.y, uPointSize.z);
    }

    gl_Position = uProjection * centre;
    if (uShape == 2 && uLineWidth > 1.0) {
        /* Across the line as it lies on the screen, half the width each side */
        float speed = length(aVelocity);
        vec3 along = speed > 0.0 ? aVelocity / speed : vec3(0.0, 1.0, 0.0);
        vec4 start = uProjection * uModelView * vec4(aParticle.xyz - along * (0.5 * size.y), 1.0);
        vec4 end = uProjection * uModelView * vec4(aParticle.xyz + along * (0.5 * size.y), 1.0);
        vec2 seen = (end.xy / end.w - start.xy / start.w) * uViewport;
        vec2 side = length(seen) > 0.0 ? normalize(vec2(-seen.y, seen.x)) : vec2(1.0, 0.0);
        gl_Position.xy += side * (aCorner.x * uLineWidth * 2.0) / uViewport * gl_Position.w;
    }
    vEyePosition = centre.xyz;
    vEyeNormal = uShape == 1 ? normalize(uNormalMatrix * vec3(0.0, 0.0, 1.0)) : vec3(0.0, 0.0, 1.0);
    clipByPlanes(centre.xyz);
    vCorner = aCorner;
    vec2 st = aCorner + 0.5;
    if (uFrameCount > 0) {
        int frame = clamp(int(aParams.w + 0.5), 0, uFrameCount - 1);
        st = uFrames[frame * 4 + FRAME_CORNER[gl_VertexID % 4]];
    }
    vTexCoord = vec2(dot(uTexRows[0], vec3(st, 1.0)), dot(uTexRows[1], vec3(st, 1.0)));
    vColor = aParticleColor * mix(uStartColor, uEndColor, life);
    vRandom = aParams.z;
}
