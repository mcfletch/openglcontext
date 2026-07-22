// Cube-face direction for a face index (0=+X 1=-X 2=+Y 3=-Y 4=+Z 5=-Z) and a
// [0,1] face UV. One definition shared by every IBL cube pass (env, irradiance,
// prefilter) so the six-face orientation cannot drift between them.
vec3 faceDir(int face, vec2 uv) {
    vec2 st = uv * 2.0 - 1.0;              // [-1, 1]
    if (face == 0) return vec3( 1.0, -st.y, -st.x);
    if (face == 1) return vec3(-1.0, -st.y,  st.x);
    if (face == 2) return vec3( st.x,  1.0,  st.y);
    if (face == 3) return vec3( st.x, -1.0, -st.y);
    if (face == 4) return vec3( st.x, -st.y,  1.0);
    return              vec3(-st.x, -st.y, -1.0);
}

const vec2 INV_ATAN = vec2(0.1591549, 0.3183099);  // 1/(2pi), 1/pi

// Map a world direction to equirectangular panorama UV. Shared by the visible
// skybox (hdr_background.frag) and the reflection env projection
// (ibl_equirect.frag) so the drawn sky and the metal reflections stay in
// lock-step. Longitude comes from atan(+Z,+X); latitude from the Y axis, with
// v=0 the top row of the panorama (sky, +Y) and v=1 the bottom (ground, -Y),
// matching the decoder, which returns the image top row first.
vec2 dirToEquirect(vec3 d) {
    float u = atan(d.z, d.x) * INV_ATAN.x + 0.5;
    float v = acos(clamp(d.y, -1.0, 1.0)) * INV_ATAN.y;
    return vec2(u, v);
}
