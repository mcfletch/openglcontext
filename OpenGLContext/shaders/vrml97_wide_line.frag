#version 330 core

// A wide line's colour, with its LineProperties dash pattern cut out: the
// dashes alternate drawn and gap, in pixels along the polyline.

#include "_objectid_inc.glsl"
#include "_x3d_fog_inc.glsl"

in vec3 gColor;
in vec3 gEyePosition;
in float gAlong;

const int MAX_DASHES = 8;
uniform int dashCount;                 // 0 for a solid line
uniform float dashes[MAX_DASHES];      // pixels: drawn, gap, drawn, ...
uniform float dashPeriod;              // their sum

uniform uint objectId;

layout(location = 0) out vec4 fragColor;
layout(location = 1) out vec4 fragObjectId;

bool inGap(float along) {
    if (dashCount == 0 || dashPeriod <= 0.0) {
        return false;
    }
    float position = mod(along, dashPeriod);
    for (int index = 0; index < MAX_DASHES; ++index) {
        if (index >= dashCount) {
            break;
        }
        if (position < dashes[index]) {
            return (index % 2) == 1;
        }
        position -= dashes[index];
    }
    return false;
}

void main() {
    if (inGap(gAlong)) {
        discard;
    }
    fragColor = vec4(x3dFogged(gColor, length(gEyePosition)), 1.0);
    fragObjectId = encodeObjectId(objectId);
}
