// A colour X3D gives as it is displayed (a line, a point, an unlit or
// vertex-coloured surface, a Background), as a document is drawn: times
// `exposure` and through the frame's tone curve (_tonemap_inc.glsl), as X_ITE
// draws one. Elsewhere, and in the VRML97 pass, which leaves documentDisplay
// false, the colour is written as it is.
#include "_tonemap_inc.glsl"

uniform bool documentDisplay;   // a document (OpenGLContext.passes.tonemapping)
uniform float exposure;         // the display's exposure

vec3 displayedX3D(vec3 color) {
    return documentDisplay ? clamp(toneCurve(color * exposure), 0.0, 1.0) : color;
}
