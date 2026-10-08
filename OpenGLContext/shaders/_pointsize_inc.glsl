// A point's size in pixels at a distance from the viewer, by X3D's
// PointProperties (19775-1, 12.4.6): the scale over a + b r + c r^2,
// between the minimum and the maximum. A constant size is all three equal.
// OpenGLContext.scenegraph.drawproperties.PointSize is the same arithmetic.

uniform float pointSizeScale;
uniform float pointSizeMinimum;
uniform float pointSizeMaximum;
uniform vec3 pointSizeAttenuation;

float x3dPointSize(float distance) {
    float divisor = dot(pointSizeAttenuation, vec3(1.0, distance, distance * distance));
    float size = divisor > 0.0 ? pointSizeScale / divisor : pointSizeMaximum;
    return clamp(size, pointSizeMinimum, pointSizeMaximum);
}
