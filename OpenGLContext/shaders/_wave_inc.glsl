// A water surface, moved on the card.
//
// Included by every vertex shader water is drawn with -- the PBR program and
// the shadow depth program alike, so a wave casts the shadow of the shape it
// is in rather than of the plane it was meshed as. It is the same arrangement
// skinning uses, and for the same reason: the mesh is uploaded once and the
// movement is a handful of uniforms.
//
// The field is three crossing sine trains taken from **world position and
// time**, which is what makes two sheets that meet agree along their seam. The
// numbers here are the same numbers
// OpenGLContext.scenegraph.water.surface computes with -- a test holds the two
// together, because a surface that floats a boat at one height and draws it at
// another is worse than one that does neither.
//
// WAVE_STEEPNESS is the ripple that lives in the normal rather than in the
// surface: finer than any mesh a caller will pay for, and what breaks the
// specular highlight into the glitter a still picture reads as water.

#ifndef PBR_WAVE
#define PBR_WAVE 1
#endif

#if PBR_WAVE
uniform bool waveEnabled;
uniform float waveAmplitude;      // metres, trough to crest
uniform float waveLength;         // metres between crests
uniform float waveSpeed;          // metres a second the crests travel
uniform float waveSteepness;      // the ripple in the normal
uniform vec2 waveFlow;            // metres a second the surface drifts
uniform float waveTime;           // seconds

// Each train's turn from the style's heading, its share of the amplitude, and
// how much longer its own wavelength is. Three: one is corrugated iron, two
// beat against each other, three read as water.
const vec3 WAVE_TRAINS[3] = vec3[3](
    vec3( 0.00, 1.00, 1.00),
    vec3( 0.62, 0.55, 0.61),
    vec3(-1.13, 0.34, 1.47)
);

//: Over how many metres the ripple in the normal repeats.
const float WAVE_RIPPLE_SCALE = 11.0;

float waveHeading() {
    return (waveFlow.x != 0.0 || waveFlow.y != 0.0)
        ? atan(waveFlow.y, waveFlow.x) : 0.0;
}

// Displace a model-space position and re-derive its normal. Water is meshed in
// the plane its surface stands on, so the field is read from x and z and the
// displacement is in y -- which is why this runs before anything transforms
// the vertex, exactly as skinning does.
void applyWave(inout vec3 position, inout vec3 normal) {
    if (!waveEnabled) { return; }
    float heading = waveHeading();
    float height = 0.0;
    float slopeX = 0.0;
    float slopeZ = 0.0;
    for (int i = 0; i < 3; ++i) {
        float angle = heading + WAVE_TRAINS[i].x;
        float amplitude = waveAmplitude * WAVE_TRAINS[i].y;
        float number = 6.283185307179586 / max(waveLength * WAVE_TRAINS[i].z, 1e-6);
        float along = position.x * cos(angle) + position.z * sin(angle);
        float phase = number * along - number * waveSpeed * waveTime;
        height += amplitude * sin(phase);
        float rate = amplitude * number * cos(phase);
        slopeX += rate * cos(angle);
        slopeZ += rate * sin(angle);
    }
    position.y += height;
    normal = normalize(vec3(-slopeX, 1.0, -slopeZ));
}

// The fine ripple, from a point on the surface in the plane it lies in.
//
// Kept out of applyWave and given to the *fragment* shader: it repeats over
// a few metres, and a sheet of water is meshed across a whole tile. Sampled
// at the vertices it aliases away to nothing and the surface comes out a
// flat plate; sampled per pixel it is the same ripple at any mesh density,
// which is what makes a lake read as water rather than as concrete.
vec2 waveRipple(vec2 surface) {
    if (!waveEnabled || waveSteepness <= 0.0) { return vec2(0.0); }
    // Carried downstream with the flow, so a river's light travels with it.
    float driftX = surface.x - waveFlow.x * waveTime;
    float driftZ = surface.y - waveFlow.y * waveTime;
    float first = 6.283185307179586 / WAVE_RIPPLE_SCALE;
    float second = 6.283185307179586 / (WAVE_RIPPLE_SCALE * 1.7);
    float slopeX = waveSteepness * cos(first * (driftX + 0.6 * driftZ))
                 + waveSteepness * 0.6 * cos(second * (driftX - 1.3 * driftZ));
    float slopeZ = waveSteepness * 0.6 * sin(first * (driftX + 0.6 * driftZ))
                 - waveSteepness * sin(second * (driftX - 1.3 * driftZ));
    return vec2(slopeX, slopeZ);
}
#else
void applyWave(inout vec3 position, inout vec3 normal) {}
vec2 waveRipple(vec2 surface) { return vec2(0.0); }
#endif
