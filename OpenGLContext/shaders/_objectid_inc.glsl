// Shared selection object-id encode. Pulled in by every fragment shader that
// writes the picking (object-id) attachment -- the lit shaders via _lights_inc,
// and the unlit/point/line/vertex-colour shaders directly -- so the RGBA8 packing
// lives in exactly one place instead of being hand-inlined per shader.

// Pack a 32-bit object id into RGBA8 for the selection (picking) attachment.
vec4 encodeObjectId(uint id) {
    return vec4(
        float((id >>  0u) & 0xFFu) / 255.0,
        float((id >>  8u) & 0xFFu) / 255.0,
        float((id >> 16u) & 0xFFu) / 255.0,
        float((id >> 24u) & 0xFFu) / 255.0
    );
}
