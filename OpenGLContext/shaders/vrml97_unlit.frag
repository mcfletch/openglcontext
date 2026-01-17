#version 330 core

// Unlit fragment shader for selection/picking and text rendering
// Supports solid color, textured, and text rendering modes

uniform vec4 solidColor;
uniform sampler2D diffuseTexture;
uniform bool useTexture;

// Text rendering mode uniforms
uniform bool textMode;           // When true, use text rendering logic
uniform vec4 textColor;          // Color for text pixels (where texture alpha > 0)
uniform vec4 backgroundColor;    // Background color (used when textSolidBg is true)
uniform bool textSolidBg;        // When true, render solid background instead of transparent

in vec2 vTexCoord;

out vec4 fragColor;

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
}
