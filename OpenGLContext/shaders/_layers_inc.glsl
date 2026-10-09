// X3D's MultiTexture stage chain, and a cube map or 3D texture standing as a
// chain of one (OpenGLContext.scenegraph.texturelayers, which numbers the
// modes, sources, functions, kinds and coordinates as these defines do).
//
// The includer declares, before this file: the varyings vTexCoord,
// vTexCoord1, vTexCoord3D, vLocalPosition, vLocalNormal, vLocalEye,
// vPosition; the uniform eyeToWorld; the texture coordinate generators
// (_texgen_inc.glsl); sRGBToLinear (_common_inc.glsl); and
//     vec4 layerTexture2D(int slot, vec2 uv)
// reading the 2D texture bound for a 2D layer's slot.
//
// TEXTURE_LAYER_SAMPLERS 1 declares the cube map and 3D samplers a layer of
// those kinds reads; at 0 the program has no texture units for them and the
// pass gives such layers no kind, which leaves them out of the chain.

#ifndef TEXTURE_LAYER_SAMPLERS
#define TEXTURE_LAYER_SAMPLERS 0
#endif

#define MAX_TEXTURE_LAYERS 4

#define LAYER_KIND_2D                         1
#define LAYER_KIND_CUBE                       2
#define LAYER_KIND_3D                         3

#define LAYER_COORD_SET                       0
#define LAYER_COORD_GENERATED                 1
#define LAYER_COORD_VOLUME                    2
#define LAYER_COORD_BOX                       3
#define LAYER_COORD_REFLECTION                4

#define LAYER_MODE_MODULATE                   1
#define LAYER_MODE_REPLACE                    2
#define LAYER_MODE_MODULATE_2X                3
#define LAYER_MODE_MODULATE_4X                4
#define LAYER_MODE_ADD                        5
#define LAYER_MODE_ADD_SIGNED                 6
#define LAYER_MODE_ADD_SIGNED_2X              7
#define LAYER_MODE_ADD_SMOOTH                 8
#define LAYER_MODE_SUBTRACT                   9
#define LAYER_MODE_BLEND_DIFFUSE_ALPHA        10
#define LAYER_MODE_BLEND_TEXTURE_ALPHA        11
#define LAYER_MODE_BLEND_FACTOR_ALPHA         12
#define LAYER_MODE_BLEND_CURRENT_ALPHA        13
#define LAYER_MODE_MODULATE_ALPHA_ADD_COLOR   14
#define LAYER_MODE_MODULATE_INV_ALPHA_ADD_COLOR 15
#define LAYER_MODE_MODULATE_INV_COLOR_ADD_ALPHA 16
#define LAYER_MODE_DOT_PRODUCT_3              17
#define LAYER_MODE_SELECT_ARG1                18
#define LAYER_MODE_SELECT_ARG2                19
#define LAYER_MODE_OFF                        20

#define LAYER_SOURCE_DIFFUSE                  1
#define LAYER_SOURCE_SPECULAR                 2
#define LAYER_SOURCE_FACTOR                   3

#define LAYER_FUNCTION_COMPLEMENT             1
#define LAYER_FUNCTION_ALPHA_REPLICATE        2

// How many layers this draw combines; 0 is no chain.
uniform int textureLayerCount;
// Each layer, packed: x the kind (bits 0-1), the coordinate (2-4), the 2D set
// (5) and the generator's mode (6-9); y the colour mode (0-4) and the alpha
// mode (5-9); z the source (0-1) and the function (2-3); w the 2D slot.
uniform ivec4 textureLayer[MAX_TEXTURE_LAYERS];
// Each layer's transform: three rows applied to (s, t, r, q).
uniform vec4 textureLayerRows[3 * MAX_TEXTURE_LAYERS];
// Each layer's generator parameters, eight a layer.
uniform vec4 textureLayerParameter[2 * MAX_TEXTURE_LAYERS];
// The MultiTexture's color and alpha: FACTOR.
uniform vec4 textureLayerFactor;
// The geometry's bounds in its own space, for a 3D texture with no coordinates.
uniform vec3 textureBoxLow;
uniform vec3 textureBoxSize;

#if TEXTURE_LAYER_SAMPLERS
uniform samplerCube textureLayerCube;
uniform sampler3D textureLayer3D;
#endif

// Layer i's coordinates, transformed: (s, t, r).
vec3 layerCoordinate(int i, ivec4 info, vec3 eyeNormal) {
    int coordinate = (info.x >> 2) & 7;
    vec4 raw;
    if (coordinate == LAYER_COORD_GENERATED) {
        raw = vec4(texGenMake((info.x >> 6) & 15, textureLayerParameter[2 * i],
                              textureLayerParameter[2 * i + 1], vLocalPosition,
                              vLocalNormal, vPosition, eyeNormal, vLocalEye), 1.0);
    } else if (coordinate == LAYER_COORD_VOLUME) {
        raw = vTexCoord3D;
    } else if (coordinate == LAYER_COORD_BOX) {
        raw = vec4((vLocalPosition - textureBoxLow) / max(textureBoxSize, vec3(1e-6)), 1.0);
    } else {
        raw = vec4(((info.x >> 5) & 1) == 1 ? vTexCoord1 : vTexCoord, 0.0, 1.0);
    }
    vec3 st = vec3(dot(textureLayerRows[3 * i], raw), dot(textureLayerRows[3 * i + 1], raw),
                   dot(textureLayerRows[3 * i + 2], raw));
    return st / (abs(raw.w) > 1e-6 ? raw.w : 1.0);
}

// Layer i's texel, as it is stored.
vec4 layerSample(int i, ivec4 info, vec3 eyeNormal) {
    int kind = info.x & 3;
#if TEXTURE_LAYER_SAMPLERS
    if (kind == LAYER_KIND_CUBE) {
        // The environment the surface reflects, in world space.
        vec3 reflected = reflect(normalize(vPosition), eyeNormal);
        return texture(textureLayerCube, normalize(mat3(eyeToWorld) * reflected));
    }
    if (kind == LAYER_KIND_3D) {
        return texture(textureLayer3D, layerCoordinate(i, info, eyeNormal));
    }
#endif
    return layerTexture2D(info.w, layerCoordinate(i, info, eyeNormal).xy);
}

// One mode applied to the arguments: the rgb is the colour the mode makes,
// and the alpha the alpha it makes.
vec4 layerOperation(int mode, vec4 arg1, vec4 arg2, vec4 diffuse, vec4 factor) {
    if (mode == LAYER_MODE_REPLACE || mode == LAYER_MODE_SELECT_ARG1) return arg1;
    if (mode == LAYER_MODE_SELECT_ARG2 || mode == LAYER_MODE_OFF) return arg2;
    if (mode == LAYER_MODE_MODULATE_2X) return arg1 * arg2 * 2.0;
    if (mode == LAYER_MODE_MODULATE_4X) return arg1 * arg2 * 4.0;
    if (mode == LAYER_MODE_ADD) return arg1 + arg2;
    if (mode == LAYER_MODE_ADD_SIGNED) return arg1 + arg2 - 0.5;
    if (mode == LAYER_MODE_ADD_SIGNED_2X) return (arg1 + arg2 - 0.5) * 2.0;
    if (mode == LAYER_MODE_ADD_SMOOTH) return arg1 + (1.0 - arg1) * arg2;
    if (mode == LAYER_MODE_SUBTRACT) return arg1 - arg2;
    if (mode == LAYER_MODE_BLEND_DIFFUSE_ALPHA) return mix(arg2, arg1, diffuse.a);
    if (mode == LAYER_MODE_BLEND_TEXTURE_ALPHA) return mix(arg2, arg1, arg1.a);
    if (mode == LAYER_MODE_BLEND_FACTOR_ALPHA) return mix(arg2, arg1, factor.a);
    if (mode == LAYER_MODE_BLEND_CURRENT_ALPHA) return mix(arg2, arg1, arg2.a);
    if (mode == LAYER_MODE_MODULATE_ALPHA_ADD_COLOR) return arg1 + arg1.a * arg2;
    if (mode == LAYER_MODE_MODULATE_INV_ALPHA_ADD_COLOR) return (1.0 - arg1.a) * arg2 + arg1;
    if (mode == LAYER_MODE_MODULATE_INV_COLOR_ADD_ALPHA) {
        return vec4((1.0 - arg1.rgb) * arg2.rgb + arg1.a, (1.0 - arg1.a) * arg2.a + arg1.a);
    }
    if (mode == LAYER_MODE_DOT_PRODUCT_3) {
        return vec4(dot(arg1.rgb * 2.0 - 1.0, arg2.rgb * 2.0 - 1.0));
    }
    return arg1 * arg2;     // MODULATE
}

// The chain applied to `diffuse` (the colour so far as it starts) with
// `alpha`; `specular` is SPECULAR's colour. With `linear` the textures and
// FACTOR's colour are decoded from sRGB, for a renderer lighting in linear
// light. False where this draw has no chain, `result` then unset.
bool textureLayered(vec3 diffuse, float alpha, vec3 specular, bool linear,
                    vec3 eyeNormal, out vec4 result) {
    result = vec4(diffuse, alpha);
    if (textureLayerCount <= 0) return false;
    vec4 start = vec4(diffuse, alpha);
    vec4 factor = linear ? vec4(sRGBToLinear(textureLayerFactor.rgb), textureLayerFactor.a)
                         : textureLayerFactor;
    vec4 current = start;
    for (int i = 0; i < MAX_TEXTURE_LAYERS; ++i) {
        if (i >= textureLayerCount) break;
        ivec4 info = textureLayer[i];
        int source = info.z & 3;
        vec4 arg1;
        if (source == LAYER_SOURCE_DIFFUSE) {
            arg1 = start;
        } else if (source == LAYER_SOURCE_SPECULAR) {
            arg1 = vec4(specular, alpha);
        } else if (source == LAYER_SOURCE_FACTOR) {
            arg1 = factor;
        } else {
            // A layer the program had no sampler for is left out of the chain.
            if ((info.x & 3) == 0) continue;
            arg1 = layerSample(i, info, eyeNormal);
            if (linear) arg1.rgb = sRGBToLinear(arg1.rgb);
        }
        int function = (info.z >> 2) & 3;
        if (function == LAYER_FUNCTION_COMPLEMENT) arg1 = 1.0 - arg1;
        else if (function == LAYER_FUNCTION_ALPHA_REPLICATE) arg1.a = current.a;
        vec4 colour = layerOperation(info.y & 31, arg1, current, start, factor);
        vec4 opacity = layerOperation((info.y >> 5) & 31, arg1, current, start, factor);
        current = clamp(vec4(colour.rgb, opacity.a), 0.0, 1.0);
    }
    result = current;
    return true;
}
