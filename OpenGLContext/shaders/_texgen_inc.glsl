// X3D's TextureCoordinateGenerator: the first texture coordinate set made
// from the vertex rather than read from aTexCoord (generatedTexCoord), and a
// MultiTexture layer's made per fragment (texGenMake, _layers_inc.glsl). The mode numbers are
// OpenGLContext.scenegraph.texgen.MODES.
#define TEXGEN_SPHERE                          1
#define TEXGEN_CAMERA_SPACE_NORMAL             2
#define TEXGEN_CAMERA_SPACE_POSITION           3
#define TEXGEN_CAMERA_SPACE_REFLECTION_VECTOR  4
#define TEXGEN_SPHERE_LOCAL                    5
#define TEXGEN_COORD                           6
#define TEXGEN_COORD_EYE                       7
#define TEXGEN_NOISE                           8
#define TEXGEN_NOISE_EYE                       9
#define TEXGEN_SPHERE_REFLECT                 10
#define TEXGEN_SPHERE_REFLECT_LOCAL           11
uniform int texGenMode;            // optional: 0 reads aTexCoord
uniform vec3 texGenLocalEye;       // optional: the camera in the shape's own space, per draw
uniform float texGenParameter[8];  // optional: the generator's parameters

// A sphere map of `direction`, a view reflected or refracted at the surface.
vec2 texGenSphere(vec3 direction) {
    float m = 2.0 * sqrt(direction.x * direction.x + direction.y * direction.y
                         + (direction.z + 1.0) * (direction.z + 1.0));
    return direction.xy / max(m, 1e-6) + 0.5;
}

float texGenHash(vec3 cell) {
    return fract(sin(dot(cell, vec3(127.1, 311.7, 74.7))) * 43758.5453);
}

// Value noise in [0, 1], trilinear between the lattice's corners.
float texGenNoise(vec3 p) {
    vec3 cell = floor(p);
    vec3 f = fract(p);
    vec3 u = f * f * (3.0 - 2.0 * f);
    float x00 = mix(texGenHash(cell), texGenHash(cell + vec3(1, 0, 0)), u.x);
    float x10 = mix(texGenHash(cell + vec3(0, 1, 0)), texGenHash(cell + vec3(1, 1, 0)), u.x);
    float x01 = mix(texGenHash(cell + vec3(0, 0, 1)), texGenHash(cell + vec3(1, 0, 1)), u.x);
    float x11 = mix(texGenHash(cell + vec3(0, 1, 1)), texGenHash(cell + vec3(1, 1, 1)), u.x);
    return mix(mix(x00, x10, u.y), mix(x01, x11, u.y), u.z);
}

// Noise of `p` scaled by p0.xyz (where not zero) and moved by (p0.w, p1.xy):
// a generator's first six parameters.
vec3 texGenNoiseAt(vec3 p, vec4 p0, vec4 p1) {
    vec3 scale = p0.xyz;
    vec3 at = p * mix(vec3(1.0), scale, step(1e-6, abs(scale))) + vec3(p0.w, p1.xy);
    return vec3(texGenNoise(at), texGenNoise(at + vec3(17.0, 31.0, 47.0)),
                texGenNoise(at + vec3(59.0, 3.0, 23.0)));
}

// The view direction refracted with p0.x as the index (1 where not given),
// then blended toward its reflection by p0.y.
vec3 texGenRefracted(vec3 view, vec3 normal, vec4 p0) {
    float eta = p0.x > 0.0 ? p0.x : 1.0;
    vec3 bent = refract(view, normal, 1.0 / eta);
    if (dot(bent, bent) < 1e-12) bent = reflect(view, normal);
    return normalize(mix(bent, reflect(view, normal), clamp(p0.y, 0.0, 1.0)));
}

// The coordinate generator `mode` makes, with its eight parameters in p0 and
// p1; `local*` are the point in its own space, `eye*` in the camera's, and
// `localEye` the camera in the point's own space. A 2D texture reads xy; a
// 3D texture reads all three where the mode makes them (COORD, COORD_EYE,
// CAMERA_SPACE_POSITION, CAMERA_SPACE_NORMAL, CAMERA_SPACE_REFLECTION_VECTOR
// and the noises), and z = 0 for the sphere maps.
vec3 texGenMake(int mode, vec4 p0, vec4 p1, vec3 localPosition, vec3 localNormal,
                vec3 eyePosition, vec3 eyeNormal, vec3 localEye) {
    vec3 view = normalize(eyePosition);
    vec3 localView = normalize(localPosition - localEye);
    if (mode == TEXGEN_SPHERE) return vec3(texGenSphere(reflect(view, eyeNormal)), 0.0);
    if (mode == TEXGEN_CAMERA_SPACE_NORMAL) return eyeNormal;
    // CAMERA_SPACE_POSITION and COORD_EYE are both the point in camera space
    if (mode == TEXGEN_CAMERA_SPACE_POSITION || mode == TEXGEN_COORD_EYE) return eyePosition;
    if (mode == TEXGEN_CAMERA_SPACE_REFLECTION_VECTOR) return reflect(view, eyeNormal);
    if (mode == TEXGEN_SPHERE_LOCAL) {
        return vec3(texGenSphere(reflect(localView, normalize(localNormal))), 0.0);
    }
    if (mode == TEXGEN_COORD) return localPosition;
    if (mode == TEXGEN_NOISE) return texGenNoiseAt(localPosition, p0, p1);
    if (mode == TEXGEN_NOISE_EYE) return texGenNoiseAt(eyePosition, p0, p1);
    if (mode == TEXGEN_SPHERE_REFLECT) {
        return vec3(texGenSphere(texGenRefracted(view, eyeNormal, p0)), 0.0);
    }
    if (mode == TEXGEN_SPHERE_REFLECT_LOCAL) {
        return vec3(texGenSphere(texGenRefracted(localView, normalize(localNormal), p0)), 0.0);
    }
    return vec3(0.0);
}

// The first coordinate set as `texGenMode` makes it in the vertex shader.
vec2 generatedTexCoord(vec3 localPosition, vec3 localNormal, vec3 eyePosition,
                       vec3 eyeNormal, vec3 localEye) {
    vec4 p0 = vec4(texGenParameter[0], texGenParameter[1], texGenParameter[2],
                   texGenParameter[3]);
    vec4 p1 = vec4(texGenParameter[4], texGenParameter[5], texGenParameter[6],
                   texGenParameter[7]);
    return texGenMake(texGenMode, p0, p1, localPosition, localNormal, eyePosition,
                      eyeNormal, localEye).xy;
}
