// The table of views a shared multi-view draw reads: one record per view, in
// the std140 layout pack_view_table in OpenGLContext/multiview/strategy.py
// packs. Declared only in a program compiled for several views, which defines
// MULTIVIEW_VIEWS.
//
// A shared draw works in the reference camera's eye space (the active view's):
// the modelviews, lights and shadow matrices are the ones one view would use,
// and each record says how to reach its view from there.
#ifdef MULTIVIEW_VIEWS
struct ViewData {
    mat4 refToClip;   // reference eye space -> this view's clip space
    vec4 eye;         // this view's camera, in reference eye space (w = 1)
    ivec4 flags;      // x: 1 to read directional cascades by containment
};
layout(std140) uniform ViewBlock {
    ViewData views[MULTIVIEW_VIEWS];
};
#endif

// The vertex strategy: the draw is instanced once per view in its list, and
// each copy is routed from here. A per-instance attribute's divisor is the
// view count, so an instance's data serves all of its copies.
#ifdef MULTIVIEW_VERTEX
flat out int vView;
uniform int viewCount;                          // how many views this draw reaches
uniform ivec4 viewList[4];     // their indices, packed: MAX_VIEWS (16) of them
void routeToView(vec3 eye) {
    int slot = gl_InstanceID % viewCount;
    int view = viewList[slot / 4][slot % 4];
    vView = view;
    gl_ViewportIndex = view;
    gl_Position = views[view].refToClip * vec4(eye, 1.0);
}
#endif
