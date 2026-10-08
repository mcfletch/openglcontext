// X3D's TextureCoordinateGenerator: the first texture coordinate set made
// from the vertex rather than read from aTexCoord. The mode numbers are
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

vec2 texGenNoiseAt(vec3 p) {
    vec3 scale = vec3(texGenParameter[0], texGenParameter[1], texGenParameter[2]);
    vec3 at = p * mix(vec3(1.0), scale, step(1e-6, abs(scale)))
              + vec3(texGenParameter[3], texGenParameter[4], texGenParameter[5]);
    return vec2(texGenNoise(at), texGenNoise(at + vec3(17.0, 31.0, 47.0)));
}

// The view direction refracted, then blended toward its reflection.
vec3 texGenRefracted(vec3 view, vec3 normal) {
    float eta = texGenParameter[0] > 0.0 ? texGenParameter[0] : 1.0;
    vec3 bent = refract(view, normal, 1.0 / eta);
    if (dot(bent, bent) < 1e-12) bent = reflect(view, normal);
    return normalize(mix(bent, reflect(view, normal), clamp(texGenParameter[1], 0.0, 1.0)));
}

// The coordinate `texGenMode` makes; `local*` are the vertex in its own space,
// `eye*` in the camera's, and `localEye` the camera in the vertex's own space.
vec2 generatedTexCoord(vec3 localPosition, vec3 localNormal, vec3 eyePosition,
                       vec3 eyeNormal, vec3 localEye) {
    vec3 view = normalize(eyePosition);
    vec3 localView = normalize(localPosition - localEye);
    if (texGenMode == TEXGEN_SPHERE) return texGenSphere(reflect(view, eyeNormal));
    if (texGenMode == TEXGEN_CAMERA_SPACE_NORMAL) return eyeNormal.xy;
    // CAMERA_SPACE_POSITION and COORD_EYE are both the vertex in camera space
    if (texGenMode == TEXGEN_CAMERA_SPACE_POSITION || texGenMode == TEXGEN_COORD_EYE) {
        return eyePosition.xy;
    }
    if (texGenMode == TEXGEN_CAMERA_SPACE_REFLECTION_VECTOR) return reflect(view, eyeNormal).xy;
    if (texGenMode == TEXGEN_SPHERE_LOCAL) {
        return texGenSphere(reflect(localView, normalize(localNormal)));
    }
    if (texGenMode == TEXGEN_COORD) return localPosition.xy;
    if (texGenMode == TEXGEN_NOISE) return texGenNoiseAt(localPosition);
    if (texGenMode == TEXGEN_NOISE_EYE) return texGenNoiseAt(eyePosition);
    if (texGenMode == TEXGEN_SPHERE_REFLECT) return texGenSphere(texGenRefracted(view, eyeNormal));
    if (texGenMode == TEXGEN_SPHERE_REFLECT_LOCAL) {
        return texGenSphere(texGenRefracted(localView, normalize(localNormal)));
    }
    return vec2(0.0);
}
