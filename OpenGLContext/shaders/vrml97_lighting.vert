#version 330 core

// VRML97-compatible lighting vertex shader
// Transforms vertices and passes data to fragment shader for per-fragment lighting

// Vertex attributes (matching interleaved T2F_N3F_V3F format)
layout(location = 0) in vec2 aTexCoord;  // optional: sampled where a texture is bound
layout(location = 1) in vec3 aNormal;    // required: shading has no direction without it
layout(location = 2) in vec3 aPosition;  // required
layout(location = 4) in vec4 aColor;     // optional: read where hasVertexColor says the mesh carries it
layout(location = 11) in vec2 aTexCoord1;  // optional: second UV set, read where a texture layer says the mesh carries it
layout(location = 15) in vec4 aTexCoord3D; // optional: a 3D texture's (s, t, r, q), read where a layer says the mesh carries it

// Per-instance inputs (divisor 1); a mat4 spans locations 5..8, the packed object
// id at 9. Used only when instancingEnabled -- matches the PBR shader convention.
layout(location = 5) in mat4 aInstanceModelView;
layout(location = 9) in uint aInstanceObjectId;

// Transformation matrices
uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform mat3 normalMatrix;
uniform mat3 textureMatrix;  // For VRML97 TextureTransform
uniform bool instancingEnabled;
uniform vec3 texGenLocalEye;  // the camera in the shape's own space, per draw

// Outputs to fragment shader
out vec3 vNormal;
out vec3 vPosition;  // Position in eye/view space
out vec2 vTexCoord;
out vec4 vColor;
// What a texture layer's coordinates are made from per fragment (_layers_inc.glsl)
out vec2 vTexCoord1;
out vec3 vLocalPosition;
out vec3 vLocalNormal;
flat out vec3 vLocalEye;
out vec4 vTexCoord3D;
flat out uint vObjectId;
#include "_multiview_inc.glsl"

#include "_clipplane_inc.glsl"

void main() {
    mat4 mv = instancingEnabled ? aInstanceModelView : modelViewMatrix;
    // Normal matrix follows the (per-instance) modelview when instancing.
    // mv is affine, so the 3x3 inverse-transpose is exact and ~4x cheaper than
    // inverting the full 4x4 then truncating.
    mat3 nrm = instancingEnabled ? transpose(inverse(mat3(mv))) : normalMatrix;

    // Transform position to eye space (for lighting calculations)
    vec4 eyePosition = mv * vec4(aPosition, 1.0);
    vPosition = eyePosition.xyz;

    // Transform normal to eye space
    vNormal = normalize(nrm * aNormal);
    vObjectId = aInstanceObjectId;

    // Apply texture transform (2D homogeneous coordinates)
    vec3 transformedTex = textureMatrix * vec3(aTexCoord, 1.0);
    vTexCoord = transformedTex.xy;
    vColor = aColor;
    vTexCoord1 = aTexCoord1;
    vLocalPosition = aPosition;
    vLocalNormal = aNormal;
    vLocalEye = instancingEnabled ? (inverse(mv) * vec4(0.0, 0.0, 0.0, 1.0)).xyz
                                  : texGenLocalEye;
    vTexCoord3D = aTexCoord3D;

    // Final clip-space position
    gl_Position = projectionMatrix * eyePosition;
    clipByPlanes(aPosition);
#ifdef MULTIVIEW_VERTEX
    routeToView(vPosition);
#endif
}
