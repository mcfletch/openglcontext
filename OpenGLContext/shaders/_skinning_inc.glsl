// Linear-blend skinning, read from the context's shared joint palette.
//
// Included by every vertex shader a skinned figure is drawn with -- the PBR
// program and the shadow depth program alike, so a body casts the shadow of
// the pose it is in rather than of the pose it was modelled in.
//
// The palette is a texture buffer of RGBA32F texels, four per joint matrix,
// each texel one row of the row-vector matrix the renderer composes in. The
// GLSL mat4 constructor takes columns, so mat4(r0, r1, r2, r3) is that
// matrix transposed -- and multiplying a column vector by the transpose is
// the row-vector transform, which is what the rest of the pipeline means.
//
// PBR_SKINNING is 0 on a driver whose combined texture-unit budget has no room
// for the palette; the deform then stays on the CPU and applySkin does nothing.

#ifndef PBR_SKINNING
#define PBR_SKINNING 1
#endif

#if PBR_SKINNING
layout(location = 12) in vec4 aJoints;    // optional: joint indices, read when skinningEnabled
layout(location = 13) in vec4 aWeights;   // optional: weights (normalised at load), read when skinningEnabled

layout(location = 14) in uint aInstanceJointBase;   // per instance, divisor 1

uniform samplerBuffer jointPalette;
uniform int jointBase;          // this figure's first joint in the palette
uniform bool skinningEnabled;
// A batch of figures is one draw and many poses, so each instance carries where
// its own joints start rather than reading the uniform every figure would share.
uniform bool skinningInstanced;

mat4 jointMatrix(float index) {
    int base = skinningInstanced ? int(aInstanceJointBase) : jointBase;
    int texel = (base + int(index)) * 4;
    return mat4(texelFetch(jointPalette, texel),
                texelFetch(jointPalette, texel + 1),
                texelFetch(jointPalette, texel + 2),
                texelFetch(jointPalette, texel + 3));
}

void applySkin(inout vec3 position, inout vec3 normal, inout vec3 tangent) {
    if (!skinningEnabled) {
        return;
    }
    mat4 skin = aWeights.x * jointMatrix(aJoints.x)
              + aWeights.y * jointMatrix(aJoints.y)
              + aWeights.z * jointMatrix(aJoints.z)
              + aWeights.w * jointMatrix(aJoints.w);
    position = (skin * vec4(position, 1.0)).xyz;
    mat3 rotation = mat3(skin);
    // Normalised here, not left to the fragment stage: a vertex normal is
    // interpolated across the triangle before it is normalised again, so two
    // vertices whose skinned normals came out different lengths would weight
    // the interpolation between them. The CPU deform normalises at the same
    // point, and the two have to agree.
    normal = normalize(rotation * normal);
    tangent = rotation * tangent;
}
#else
void applySkin(inout vec3 position, inout vec3 normal, inout vec3 tangent) {
}
#endif

void applySkin(inout vec3 position) {
    vec3 normal = vec3(0.0, 0.0, 1.0);
    vec3 tangent = vec3(1.0, 0.0, 0.0);
    applySkin(position, normal, tangent);
}
