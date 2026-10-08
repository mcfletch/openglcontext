#version 330 core

// A line segment as a quad lineWidth pixels across, facing the screen, for
// X3D's LineProperties. Each output vertex carries how far along the
// polyline it is in pixels, for the dash pattern: the segment's distance
// along the polyline (vAlong) scaled to its length on screen.

layout(lines) in;
layout(triangle_strip, max_vertices = 4) out;

in vec3 vColor[];
in vec3 vEyePosition[];
in float vAlong[];

uniform vec2 viewportSize;   // pixels
uniform float lineWidth;     // pixels

out vec3 gColor;
out vec3 gEyePosition;
out float gAlong;            // pixels along the polyline

// A clip-space point in front of the near plane, so it has a screen position
const float NEAR_W = 1e-4;

void emit(vec4 position, vec2 offset, int corner, float along) {
    gl_Position = position + vec4(offset * position.w, 0.0, 0.0);
    gColor = vColor[corner];
    gEyePosition = vEyePosition[corner];
    gAlong = along;
    EmitVertex();
}

void main() {
    vec4 start = gl_in[0].gl_Position;
    vec4 end = gl_in[1].gl_Position;
    if (start.w < NEAR_W && end.w < NEAR_W) {
        return;
    }
    // The part of the segment in front of the viewer
    if (start.w < NEAR_W) {
        start = mix(start, end, (NEAR_W - start.w) / (end.w - start.w));
    } else if (end.w < NEAR_W) {
        end = mix(end, start, (NEAR_W - end.w) / (start.w - end.w));
    }
    vec2 halfViewport = 0.5 * viewportSize;
    vec2 first = start.xy / start.w * halfViewport;
    vec2 second = end.xy / end.w * halfViewport;
    vec2 along = second - first;
    float pixels = length(along);
    vec2 direction = pixels > 0.0 ? along / pixels : vec2(1.0, 0.0);
    // Half the width either side, in normalised device units
    vec2 offset = vec2(-direction.y, direction.x) * (0.5 * lineWidth) / halfViewport;
    float distance = vAlong[1] - vAlong[0];
    float scale = distance > 0.0 ? pixels / distance : 0.0;
    float startAlong = vAlong[0] * scale;
    float endAlong = startAlong + pixels;
    emit(start, offset, 0, startAlong);
    emit(start, -offset, 0, startAlong);
    emit(end, offset, 1, endAlong);
    emit(end, -offset, 1, endAlong);
    EndPrimitive();
}
