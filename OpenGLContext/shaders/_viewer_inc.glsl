// Where the viewer is, for a lit fragment shader. vPosition is in eye space,
// and in a shared multi-view draw that is the reference camera's eye space,
// so the fragment's own view says where its camera stands; drawn for one view,
// the camera is at the origin. Include after vPosition is declared.
#ifdef MULTIVIEW_VIEWS
#include "_multiview_inc.glsl"
flat in int vView;
// From `p` towards the camera the fragment is being drawn for.
vec3 toViewer(vec3 p) { return views[vView].eye.xyz - p; }
// Whether this view reads directional cascades by which map holds a point.
bool viewCascadesByFit() { return views[vView].flags.x != 0; }
#else
vec3 toViewer(vec3 p) { return -p; }
bool viewCascadesByFit() { return false; }
#endif
