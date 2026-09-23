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
uniform float waveRippleScale;    // metres the ripple in the normal repeats over
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

// The trains the fine ripple is made of: each one's turn from the heading,
// its share of the steepness, and its wavelength as a share of
// waveRippleScale. Six, of lengths no two of which divide evenly: two
// crossing trains tile the surface like hammered metal.
const vec3 RIPPLE_TRAINS[6] = vec3[6](
    vec3( 0.00, 1.00, 1.00),
    vec3( 0.90, 0.80, 0.73),
    vec3(-0.70, 0.60, 0.53),
    vec3( 2.10, 0.50, 1.37),
    vec3(-1.90, 0.45, 0.41),
    vec3( 0.35, 0.35, 1.83)
);

// Metres a second squared: each ripple train travels as water's own waves of
// its length do, so the pattern changes as it moves.
const float WAVE_GRAVITY = 9.81;

// The fine ripple, from a point on the surface in the plane it lies in.
//
// Kept out of applyWave and given to the *fragment* shader: it repeats over
// the style's waveRippleScale, from a hand's breadth on a pond to metres on
// open water, and a sheet of water is meshed across a whole tile. Sampled
// at the vertices it aliases away to nothing and the surface comes out a
// flat plate; sampled per pixel it is the same ripple at any mesh density,
// which is what makes a lake read as water rather than as concrete.
vec2 waveRipple(vec2 surface) {
    if (!waveEnabled || waveSteepness <= 0.0) { return vec2(0.0); }
    // Still water's ripple holds still; water that moves carries its ripple
    // downstream with the flow, each train at its own speed.
    bool moving = (waveAmplitude != 0.0 && waveSpeed != 0.0)
               || waveFlow.x != 0.0 || waveFlow.y != 0.0;
    float when = moving ? waveTime : 0.0;
    vec2 drift = surface - waveFlow * when;
    float heading = waveHeading();
    float scale = max(waveRippleScale, 1e-6);
    vec2 slope = vec2(0.0);
    for (int i = 0; i < 6; ++i) {
        float angle = heading + RIPPLE_TRAINS[i].x;
        float number = 6.283185307179586 / (scale * RIPPLE_TRAINS[i].z);
        float along = drift.x * cos(angle) + drift.y * sin(angle);
        float tilt = waveSteepness * RIPPLE_TRAINS[i].y
                   * cos(number * along - sqrt(WAVE_GRAVITY * number) * when);
        slope += tilt * vec2(cos(angle), sin(angle));
    }
    return slope;
}
#else
void applyWave(inout vec3 position, inout vec3 normal) {}
vec2 waveRipple(vec2 surface) { return vec2(0.0); }
#endif
