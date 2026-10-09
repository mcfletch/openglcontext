#version 330 core
/* One Gaussian splat per instance, as a screen-space quad around its
 * 3-sigma ellipse (OpenGLContext.scenegraph.gaussiansplats).
 *
 * The instance's splat index comes from the back-to-front order the node
 * keeps; the splat itself is read from two buffer textures:
 *
 *   uGeometry   3 RGBA32F texels a splat: centre and opacity, then the
 *               covariance xx, xy, xz, yy and yz, zz in its own frame
 *   uHarmonics  uHarmonicTexels RGBA16F texels a splat: the spherical-
 *               harmonic coefficients r, g, b in turn, degree 0 first
 *
 * The covariance is projected with the Jacobian of the perspective (or
 * orthographic) map at the centre, the EWA approximation of Kerbl et al.
 * 2023, section 4; splatmath.projected and splatmath.footprint are the same
 * arithmetic in NumPy. The quad spans the projected ellipse's two axes at
 * three deviations, so the fragment stage reads the falloff from the corner
 * coordinate alone.
 *
 * Matrices are the engine's row-vector ones uploaded untransposed, so GLSL
 * sees each transposed and the column-vector products below are the
 * row-vector products intended.
 */

#include "_common_inc.glsl"
#include "_untoned_inc.glsl"

layout(location = 0) in uint aSplat;       // required: the splat this instance draws

uniform mat4 uModelView;
uniform mat4 uProjection;
uniform vec2 uViewport;                    // the view's size in pixels
uniform mat3 uTurn;                        // the modelview's rotation, its columns unit
uniform samplerBuffer uGeometry;
uniform samplerBuffer uHarmonics;
uniform int uDegree;                       // 0 to 3
uniform int uHarmonicTexels;
uniform bool uLinearColour;                // colorSpace LIN_REC709_DISPLAY
uniform bool uHdrOutput;                   // bloom composites the frame afterwards
uniform bool uShadeColour;                 // false for the id and depth draws

out vec2 vCorner;                          // -1 .. 1 across the quad: 3 deviations
flat out vec4 vColour;                     // display colour and opacity

const float DILATION = 0.3;                // px^2: a splat is at least a pixel wide
const float MARGIN = 1.3;                  // how far past the frustum a centre is clamped
const float EXTENT = 3.0;                  // deviations the quad reaches

const vec2 CORNERS[4] = vec2[4](vec2(-1.0, -1.0), vec2(1.0, -1.0),
                                vec2(-1.0, 1.0), vec2(1.0, 1.0));

void cull() {
    gl_Position = vec4(0.0, 0.0, 2.0, 1.0);   // beyond the far plane: clipped
    vCorner = vec2(2.0);
    vColour = vec4(0.0);
}

// The colour the coefficients give along `dir` (unit, or zero for degree 0
// alone), in KHR_gaussian_splatting's basis order and constants
// (specs/gaussian-splats.md).
vec3 harmonicColour(int splat, vec3 dir) {
    vec4 texels[12];
    int base = splat * uHarmonicTexels;
    for (int i = 0; i < uHarmonicTexels; ++i) {
        texels[i] = texelFetch(uHarmonics, base + i);
    }
    vec3 c[16];
    for (int k = 0; k < (uDegree + 1) * (uDegree + 1); ++k) {
        int f = 3 * k;
        c[k] = vec3(texels[f / 4][f % 4], texels[(f + 1) / 4][(f + 1) % 4],
                    texels[(f + 2) / 4][(f + 2) % 4]);
    }
    vec3 colour = 0.2820947917738781 * c[0];
    if (uDegree >= 1) {
        float x = dir.x, y = dir.y, z = dir.z;
        colour += 0.4886025119029199 * (-y * c[1] + z * c[2] - x * c[3]);
        if (uDegree >= 2) {
            float xx = x * x, yy = y * y, zz = z * z;
            colour += 1.092548430592079 * x * y * c[4]
                    - 1.092548430592079 * y * z * c[5]
                    + 0.31539156525252005 * (2.0 * zz - xx - yy) * c[6]
                    - 1.092548430592079 * x * z * c[7]
                    + 0.5462742152960395 * (xx - yy) * c[8];
            if (uDegree >= 3) {
                colour += -0.5900435899266435 * y * (3.0 * xx - yy) * c[9]
                        + 2.890611442640554 * x * y * z * c[10]
                        - 0.4570457994644657 * y * (4.0 * zz - xx - yy) * c[11]
                        + 0.3731763325901154 * z * (2.0 * zz - 3.0 * xx - 3.0 * yy) * c[12]
                        - 0.4570457994644657 * x * (4.0 * zz - xx - yy) * c[13]
                        + 1.445305721320277 * z * (xx - yy) * c[14]
                        - 0.5900435899266435 * x * (xx - 3.0 * yy) * c[15];
            }
        }
    }
    return clamp(colour + 0.5, 0.0, 1.0);
}

void main() {
    int splat = int(aSplat);
    vec4 centre = texelFetch(uGeometry, 3 * splat);
    vec4 upper = texelFetch(uGeometry, 3 * splat + 1);
    vec4 lower = texelFetch(uGeometry, 3 * splat + 2);
    float opacity = centre.w;
    vec4 eye = uModelView * vec4(centre.xyz, 1.0);
    vec4 clip = uProjection * eye;
    bool perspective = uProjection[3][3] == 0.0;
    if (opacity <= 0.0 || clip.w <= 0.0) {
        cull();
        return;
    }

    // The covariance in eye space: W V W^T.
    mat3 own = mat3(upper.x, upper.y, upper.z,
                    upper.y, upper.w, lower.x,
                    upper.z, lower.x, lower.y);
    mat3 W = mat3(uModelView);
    mat3 V = W * own * transpose(W);

    // The two rows of the Jacobian from eye space to pixels.
    vec2 focal = vec2(uProjection[0][0], uProjection[1][1]) * uViewport * 0.5;
    vec3 rowX, rowY;
    if (perspective) {
        float w = -eye.z;
        vec2 limit = MARGIN / vec2(uProjection[0][0], uProjection[1][1]);
        vec2 t = clamp(eye.xy / w, -limit, limit);
        rowX = vec3(focal.x / w, 0.0, focal.x * t.x / w);
        rowY = vec3(0.0, focal.y / w, focal.y * t.y / w);
    } else {
        rowX = vec3(focal.x, 0.0, 0.0);
        rowY = vec3(0.0, focal.y, 0.0);
    }
    float a = dot(rowX, V * rowX) + DILATION;
    float b = dot(rowX, V * rowY);
    float c = dot(rowY, V * rowY) + DILATION;

    // The ellipse's axes at three deviations, the major first.
    float middle = 0.5 * (a + c);
    float radius = sqrt(max(middle * middle - (a * c - b * b), 0.0));
    float major = max(middle + radius, 0.0);
    float minor = max(middle - radius, 0.0);
    vec2 along;
    if (abs(b) <= 1e-12 * (abs(a) + abs(c))) {
        along = a >= c ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    } else {
        along = normalize(vec2(b, major - a));
    }
    vec2 axisMajor = along * EXTENT * sqrt(major);
    vec2 axisMinor = vec2(-along.y, along.x) * EXTENT * sqrt(minor);

    // Splats whose whole quad is off screen draw nothing.
    vec2 ndc = clip.xy / clip.w;
    vec2 reach = (abs(axisMajor) + abs(axisMinor)) / (uViewport * 0.5);
    if (any(greaterThan(abs(ndc) - reach, vec2(1.0)))) {
        cull();
        return;
    }

    vec2 corner = CORNERS[gl_VertexID];
    vec2 offset = corner.x * axisMajor + corner.y * axisMinor;
    clip.xy += offset / (uViewport * 0.5) * clip.w;
    gl_Position = clip;
    vCorner = corner;

    vec3 colour = vec3(0.0);
    if (uShadeColour) {
        // From the camera to the splat, turned back into the splats' frame
        // by the rotation alone (splatmath.view_directions).
        vec3 toSplat = perspective ? eye.xyz : vec3(0.0, 0.0, -1.0);
        float distance = length(toSplat);
        vec3 dir = distance > 0.0 ? transpose(uTurn) * (toSplat / distance) : vec3(0.0);
        colour = harmonicColour(splat, dir);
        if (uLinearColour) {
            colour = linearToSRGB(colour);
        }
        if (uHdrOutput) {
            colour = untoned(colour);
        }
    }
    vColour = vec4(colour, opacity);
}
