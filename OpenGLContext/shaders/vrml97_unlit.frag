#version 330 core

// Unlit fragment shader for selection/picking and text rendering
// Supports solid color, textured, and text rendering modes

#include "_objectid_inc.glsl"

uniform vec4 solidColor;
uniform sampler2D diffuseTexture;
uniform bool useTexture;

// Text rendering mode uniforms
uniform bool textMode;           // When true, use text rendering logic
uniform vec4 textColor;          // Color for text pixels (where texture alpha > 0)
uniform vec4 backgroundColor;    // Background color (used when textSolidBg is true)
uniform bool textSolidBg;        // When true, render solid background instead of transparent

// Object ID for the selection buffer (MRT). Set by the render pass for real
// geometry drawn through this program (e.g. an unlit PointSet); left 0 for text.
uniform uint objectId;

in vec2 vTexCoord;

// Output color (attachment 0)
layout(location = 0) out vec4 fragColor;
// Output object ID (attachment 1)
layout(location = 1) out vec4 fragObjectId;

void main() {
    if (textMode) {
        // Text rendering mode
        vec4 texel = texture(diffuseTexture, vTexCoord);

        if (textSolidBg) {
            // Solid background mode: interpolate between background and text color
            // based on texture alpha (white text on transparent = alpha as mask)
            fragColor = mix(backgroundColor, textColor, texel.a);
        } else {
            // Transparent background mode: text color with texture alpha
            fragColor = vec4(textColor.rgb, textColor.a * texel.a);
        }
    } else if (useTexture) {
        // Standard textured mode (for general unlit textured objects)
        vec4 texel = texture(diffuseTexture, vTexCoord);
        fragColor = texel * solidColor;
    } else {
        // Pure solid color mode (for selection rendering)
        fragColor = solidColor;
    }

    // Text / HUD stays non-pickable (id 0); real unlit geometry writes its id so
    // it selects like lit geometry. objectId defaults to 0 when the pass never
    // sets it (the text path), so guarding on textMode keeps HUD unpickable.
    if (textMode) {
        fragObjectId = vec4(0.0, 0.0, 0.0, 0.0);
    } else {
        fragObjectId = encodeObjectId(objectId);
    }
}
