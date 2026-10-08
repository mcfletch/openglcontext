#version 330 core

// Point fragment shader with per-vertex color and optional texture (point sprites)
// Used for PointSet geometry (particles, point clouds, etc.)

#include "_objectid_inc.glsl"
#include "_x3d_fog_inc.glsl"

in vec3 vColor;
in vec3 vEyePosition;

uniform bool hasTexture;
uniform sampler2D pointTexture;

// Object ID for selection buffer (MRT)
uniform uint objectId;

// Output color (attachment 0)
layout(location = 0) out vec4 fragColor;
// Output object ID (attachment 1) - for selection buffer
layout(location = 1) out vec4 fragObjectId;

void main() {
    vec4 color = vec4(vColor, 1.0);

    if (hasTexture) {
        // gl_PointCoord provides texture coordinates for point sprites
        // (0,0) at top-left, (1,1) at bottom-right of the point
        vec4 texColor = texture(pointTexture, gl_PointCoord);
        // Multiply vertex color with texture
        color = color * texColor;
    }

    fragColor = vec4(x3dFogged(color.rgb, length(vEyePosition)), color.a);

    // Output object ID to selection buffer (encode as RGBA8)
    fragObjectId = encodeObjectId(objectId);
}
