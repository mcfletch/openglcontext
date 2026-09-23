#version 330 core

// PBR (metallic/roughness) vertex shader. Shares the OpenGLContext attribute
// location convention; tangent at location 3 is used for normal mapping.
//
// Each input says whether the program can be drawn without it: an ordinary box
// carries a position, a normal and a texture coordinate, and the rest are read
// only where a uniform says the geometry brought them. See
// OpenGLContext/passes/shadersource.py:required_inputs.
layout(location = 0) in vec2 aTexCoord;  // optional: sampled where a map is bound
layout(location = 1) in vec3 aNormal;    // required: shading has no direction without it
layout(location = 2) in vec3 aPosition;  // required
layout(location = 3) in vec4 aTangent;   // optional: xyz tangent, w handedness; zero disables normal mapping
layout(location = 4) in vec4 aColor;     // optional: per-vertex color (glTF COLOR_0), read when hasVertexColor

// Instanced draw inputs (one per instance, divisor 1). A single mat4 occupies four
// consecutive attribute locations (5..8). The row-major OpenGLContext modelview
// stored straight into these columns yields the same GL matrix the uniform path
// uploads with GL_FALSE, so no transpose is needed here.
layout(location = 5) in mat4 aInstanceModelView;
layout(location = 9) in uint aInstanceObjectId;
layout(location = 10) in uint aInstanceMaterial;   // index into the material array
layout(location = 11) in vec2 aTexCoord1;          // optional: second UV set (glTF TEXCOORD_1)

#include "_skinning_inc.glsl"
#include "_wave_inc.glsl"

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform mat3 normalMatrix;
uniform bool instancingEnabled;   // read model + id from instance attributes

// Octahedral impostor: a quad turned to face the viewer, showing the one of
// `impostorGrid` x `impostorGrid` baked views that matches the direction it is
// being looked at from.  0 -- the default -- is every ordinary draw, and costs
// one uniform test.  The whole of it is here rather than in the fragment
// shader because the view is a property of the *object*: which tile of the
// atlas to read is constant across the quad, so selecting it is an affine
// change to the texture coordinate and the fragment shader samples its base
// colour exactly as it always does.  See OpenGLContext/scenegraph/octahedral.py,
// which is the same mapping in Python and is what the baker renders against.
uniform int impostorGrid;
uniform bool impostorHemi;

out vec3 vNormal;        // eye space
out vec3 vPosition;      // eye space
out vec2 vSurface;       // where on the water this is, in its own plane
out vec3 vSurfX;         // that plane's axes in eye space, so the ripple
out vec3 vSurfZ;         // can be composed with whatever normal is there
out vec2 vTexCoord;
out vec2 vTexCoord1;     // second UV set
out vec3 vTangent;       // eye space
out float vTangentW;
out vec4 vColor;
out float vModelScale;   // world-space object scale, for KHR_materials_volume thickness
flat out uint vObjectId;       // per-instance picking id (used only when instancing)
flat out uint vMaterialIndex;  // per-instance material-array index
#include "_multiview_inc.glsl"

// Where on the unit square a direction's baked view lives.  The twin of
// `octahedral.direction_to_uv`; the two have to agree or the impostor shows the
// wrong picture.
vec2 octahedralUV(vec3 direction, bool hemi) {
    vec3 d = normalize(direction);
    if (hemi) { d.y = abs(d.y); }
    d /= (abs(d.x) + abs(d.y) + abs(d.z));
    vec2 uv;
    if (hemi) {
        uv = vec2(d.x + d.z, d.z - d.x);
    } else if (d.y >= 0.0) {
        uv = d.xz;
    } else {
        uv = vec2((1.0 - abs(d.z)) * (d.x >= 0.0 ? 1.0 : -1.0),
                  (1.0 - abs(d.x)) * (d.z >= 0.0 ? 1.0 : -1.0));
    }
    return clamp(uv * 0.5 + 0.5, 0.0, 1.0);
}

void main() {
    mat4 mv = instancingEnabled ? aInstanceModelView : modelViewMatrix;
    // Normal matrix follows the (per-instance) modelview. The uniform path passes
    // a precomputed inverse-transpose; instancing derives it per vertex, which is
    // costlier but avoids a per-instance uniform.
    mat3 nrm = instancingEnabled ? transpose(inverse(mat3(mv))) : normalMatrix;

    // Skinning moves the vertex into the pose before anything transforms it:
    // the joint matrices are built in the skeleton's own space, which is what
    // the model matrix then takes to the world.
    vec3 position = aPosition;
    vec3 normal = aNormal;
    vec4 eyePositionOverride = vec4(0.0);
    vec3 tangent = aTangent.xyz;
    applySkin(position, normal, tangent);
    // Water moves on the card too, and after the mesh's own animation:
    // the wave belongs to the surface rather than to the vertices.
    applyWave(position, normal);
    // Where this fragment stands on the water, and which way that surface's
    // own x and z point once they are in eye space. Read before the modelview,
    // because the field is read in the plane the sheet was meshed in; the axes
    // are what lets the fragment shader tilt whatever normal it has by the
    // ripple's slopes without needing a matrix of its own.
    vSurface = position.xz;
    vSurfX = nrm * vec3(1.0, 0.0, 0.0);
    vSurfZ = nrm * vec3(0.0, 0.0, 1.0);

    vec2 impostorOrigin = vec2(0.0);
    float impostorSpan = 1.0;
    if (impostorGrid > 0) {
        // The quad hangs off the object's own origin, turned flat to the
        // viewer: in eye space the view direction is -z, so a corner offset in
        // x and y is already facing us.  The object's scale is the modelview's,
        // so the card is as big as the model it stands for.
        vec3 origin = (mv * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
        float scale = (length(mat3(mv)[0]) + length(mat3(mv)[1])
                       + length(mat3(mv)[2])) / 3.0;
        position = vec3(0.0);
        // Which way the object is being looked at from, in the object's own
        // space -- the view is rigid, so the modelview's transpose takes an eye
        // vector back into it.
        vec3 toEye = transpose(mat3(mv)) * (-origin);
        vec2 uv = octahedralUV(toEye, impostorHemi);
        float side = 1.0 / float(impostorGrid);
        vec2 cell = floor(min(uv * float(impostorGrid),
                              float(impostorGrid) - 0.001));
        // Half a texel in from the tile's edge, so the bilinear filter cannot
        // reach across into the view next door.
        float inset = 0.5 / float(impostorGrid * 512);
        impostorOrigin = cell * side + inset;
        impostorSpan = side - 2.0 * inset;
        eyePositionOverride = vec4(origin + vec3(aPosition.xy * scale, 0.0), 1.0);
        normal = vec3(0.0, 0.0, 1.0);
    }

    vec4 eyePosition = impostorGrid > 0 ? eyePositionOverride
                                        : mv * vec4(position, 1.0);
    vPosition = eyePosition.xyz;
    vNormal = impostorGrid > 0 ? vec3(0.0, 0.0, 1.0)
                               : normalize(nrm * normal);
    // Tangents are surface-direction vectors, so they transform by the modelview
    // upper-3x3, NOT the inverse-transpose normalMatrix (that is for normals).
    // Guard the normalize: with no tangent attribute location 3 defaults to 0, and
    // normalize(0) is NaN -- emit a zero tangent instead so the fragment's
    // length(vTangent) > 0 test cleanly disables normal mapping (finding 4.1).
    vec3 tEye = mat3(mv) * tangent;
    float tLen = length(tEye);
    vTangent = tLen > 0.0 ? tEye / tLen : vec3(0.0);
    vTangentW = aTangent.w;
    vTexCoord = impostorGrid > 0
        ? impostorOrigin + aTexCoord * impostorSpan
        : aTexCoord;
    vTexCoord1 = aTexCoord1;
    vColor = aColor;
    // The view is rigid (no scale), so the modelview upper-3x3 column lengths are the
    // MODEL scale. KHR_materials_volume thickness is authored in local units; scaling
    // it here puts the refraction offset + Beer-Lambert absorption in world units, so
    // a non-unit-scaled instance absorbs correctly (was treated as already world-scale).
    vModelScale = (length(mat3(mv)[0]) + length(mat3(mv)[1]) + length(mat3(mv)[2])) / 3.0;
    vObjectId = aInstanceObjectId;
    vMaterialIndex = aInstanceMaterial;
    gl_Position = projectionMatrix * eyePosition;
    // Point primitives (glTF POINTS mode) default to 1px, which is invisible on a
    // hi-dpi capture. Give them a fixed screen size scaled down with distance so a
    // point cloud reads. Ignored for triangle/line draws (needs GL_PROGRAM_POINT_SIZE).
    gl_PointSize = clamp(120.0 / max(-eyePosition.z, 0.1), 2.0, 12.0);
#ifdef MULTIVIEW_VERTEX
    routeToView(vPosition);
#endif
}
