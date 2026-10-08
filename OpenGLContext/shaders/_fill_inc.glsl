// X3D's FillProperties (19775-1, 12.4.4): hatch lines over a polygon, and
// whether the polygon is filled. OpenGLContext.scenegraph.drawproperties
// reads the node into these uniforms.

uniform int hatchStyle;      // 0: none; 1 to 6 are ISO/IEC 9973's first six
uniform vec3 hatchColor;
uniform bool unfilled;       // FillProperties.filled false

// Pixels between a hatch's lines; drawproperties.HATCH_SPACING
const float HATCH_SPACING = 8.0;

bool hatchLine(float coordinate) {
    return mod(coordinate, HATCH_SPACING) < 1.0;
}

bool onHatch(vec2 pixel) {
    bool horizontal = hatchLine(pixel.y);
    bool vertical = hatchLine(pixel.x);
    bool rising = hatchLine(pixel.x - pixel.y);
    bool falling = hatchLine(pixel.x + pixel.y);
    if (hatchStyle == 1) return horizontal;
    if (hatchStyle == 2) return vertical;
    if (hatchStyle == 3) return rising;
    if (hatchStyle == 4) return falling;
    if (hatchStyle == 5) return horizontal || vertical;
    if (hatchStyle == 6) return rising || falling;
    return false;
}

// True where this fragment is on a hatch line, its colour then in `color`.
// A fragment of an unfilled polygon off the hatch lines is discarded.
bool x3dHatch(out vec4 color) {
    color = vec4(hatchColor, 1.0);
    if (hatchStyle > 0 && onHatch(floor(gl_FragCoord.xy))) {
        return true;
    }
    if (unfilled) {
        discard;
    }
    return false;
}
