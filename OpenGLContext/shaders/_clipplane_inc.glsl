// X3D's ClipPlane: the planes clipping this draw, in the drawn object's own
// frame (OpenGLContext/passes/clipscope.py). A vertex is kept where each
// plane's a*x + b*y + c*z + d is zero or more. The pass enables
// GL_CLIP_DISTANCE0 .. clipPlaneCount-1; a distance past the count is written
// as 1.0 and is not enabled.
uniform int clipPlaneCount;     // how many of clipPlanes clip the draw
uniform vec4 clipPlanes[8];

float clipDistance(int index, vec4 point) {
    return index < clipPlaneCount ? dot(clipPlanes[index], point) : 1.0;
}

// `position` is the vertex in the object's own frame, as the modelview takes it
void clipByPlanes(vec3 position) {
    vec4 point = vec4(position, 1.0);
    gl_ClipDistance[0] = clipDistance(0, point);
    gl_ClipDistance[1] = clipDistance(1, point);
    gl_ClipDistance[2] = clipDistance(2, point);
    gl_ClipDistance[3] = clipDistance(3, point);
    gl_ClipDistance[4] = clipDistance(4, point);
    gl_ClipDistance[5] = clipDistance(5, point);
    gl_ClipDistance[6] = clipDistance(6, point);
    gl_ClipDistance[7] = clipDistance(7, point);
}
