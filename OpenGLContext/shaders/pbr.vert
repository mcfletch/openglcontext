#version 330 core

// PBR (metallic/roughness) vertex shader. Shares the OpenGLContext attribute
// location convention; tangent at location 3 is used for normal mapping.
layout(location = 0) in vec2 aTexCoord;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec3 aPosition;
layout(location = 3) in vec4 aTangent;   // xyz tangent, w = handedness
layout(location = 4) in vec4 aColor;     // per-vertex color (glTF COLOR_0)

// Instanced draw inputs (one per instance, divisor 1). A single mat4 occupies four
// consecutive attribute locations (5..8). The row-major OpenGLContext modelview
// stored straight into these columns yields the same GL matrix the uniform path
// uploads with GL_FALSE, so no transpose is needed here.
layout(location = 5) in mat4 aInstanceModelView;
layout(location = 9) in uint aInstanceObjectId;
layout(location = 10) in uint aInstanceMaterial;   // index into the material array
layout(location = 11) in vec2 aTexCoord1;          // second UV set (glTF TEXCOORD_1)

uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform mat3 normalMatrix;
uniform bool instancingEnabled;   // read model + id from instance attributes

out vec3 vNormal;        // eye space
out vec3 vPosition;      // eye space
out vec2 vTexCoord;
out vec2 vTexCoord1;     // second UV set
out vec3 vTangent;       // eye space
out float vTangentW;
out vec4 vColor;
out float vModelScale;   // world-space object scale, for KHR_materials_volume thickness
flat out uint vObjectId;       // per-instance picking id (used only when instancing)
flat out uint vMaterialIndex;  // per-instance material-array index

void main() {
    mat4 mv = instancingEnabled ? aInstanceModelView : modelViewMatrix;
    // Normal matrix follows the (per-instance) modelview. The uniform path passes
    // a precomputed inverse-transpose; instancing derives it per vertex, which is
    // costlier but avoids a per-instance uniform.
    mat3 nrm = instancingEnabled ? transpose(inverse(mat3(mv))) : normalMatrix;

    vec4 eyePosition = mv * vec4(aPosition, 1.0);
    vPosition = eyePosition.xyz;
    vNormal = normalize(nrm * aNormal);
    // Tangents are surface-direction vectors, so they transform by the modelview
    // upper-3x3, NOT the inverse-transpose normalMatrix (that is for normals).
    // Guard the normalize: with no tangent attribute location 3 defaults to 0, and
    // normalize(0) is NaN -- emit a zero tangent instead so the fragment's
    // length(vTangent) > 0 test cleanly disables normal mapping (finding 4.1).
    vec3 tEye = mat3(mv) * aTangent.xyz;
    float tLen = length(tEye);
    vTangent = tLen > 0.0 ? tEye / tLen : vec3(0.0);
    vTangentW = aTangent.w;
    vTexCoord = aTexCoord;
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
}
