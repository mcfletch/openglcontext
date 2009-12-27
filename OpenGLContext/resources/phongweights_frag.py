# -*- coding: ISO-8859-1 -*-
"""Resource phongweights_frag (from file phongweights.frag)"""
# written by resourcepackage: (1, 0, 0)
source = 'phongweights.frag'
package = 'OpenGLContext.resources'
data = "vec3 phong_weightCalc( \012    in vec3 light_pos, // light posi\
tion/direction\012    in vec3 half_light, // half-way vector be\
tween light and view\012    in vec3 frag_normal, // geometry no\
rmal\012    in float shininess, // shininess exponent\012    in fl\
oat distance, // distance for attenuation calculation...\012   \
 in vec4 attenuations, // attenuation parameters...\012    in v\
ec4 spot_params, // spot control parameters...\012    in vec4 s\
pot_direction // model-space direction\012) {\012    // Together w\
ith phong_preCalc this is the core blinn/phong \012    // light\
ing algorithm.  The light_pos, half_light, and distance \012   \
 // parameters were calculated by phong_preCalc, frag_normal\
\012    // is normally calculated by the vertex shader (we pass\
 it as \012    // baseNormal).  shininess normally comes from t\
he material, \012    // while attenuations, spot_params and spo\
t_direction come \012    // from the lighting setup.\012    \012    /\
/ returns vec3( ambientMult, diffuseMult, specularMult )\012   \
 \012    float n_dot_pos = max( 0.0, dot( \012        frag_normal,\
 light_pos\012    ));\012    float n_dot_half = 0.0;\012    float att\
enuation = 1.0;\012    if (n_dot_pos > -.05) {\012        float sp\
ot_effect = 1.0;\012        if (spot_params.w != 0.0) {\012       \
     // is a spot...\012            float spot_cos = dot(\012     \
           gl_NormalMatrix * normalize(spot_direction.xyz),\012\
                normalize(-light_pos)\012            );\012       \
     if (spot_cos <= spot_params.x) {\012                // is \
a spot, and is outside the cone-of-light...\012                \
return vec3( 0.0, 0.0, 0.0 );\012            } else {\012         \
       if (spot_cos == 1.0) {\012                    spot_effec\
t = 1.0;\012                } else {\012                    spot_e\
ffect = pow( \012                        (1.0-spot_params.x)/(1\
.0-spot_cos), \012                        spot_params.y \012      \
              );\012                }\012            }\012        }\012 \
       n_dot_half = pow(\012            max(0.0,dot( \012         \
       half_light, frag_normal\012            )), \012            \
shininess\012        );\012        if (distance != 0.0) {\012        \
    attenuation = spot_effect / (\012                    attenu\
ations.x + \012                    (attenuations.y * distance) \
+\012                    (attenuations.z * distance * distance)\
\012                );\015\012            attenuation = clamp( attenu\
ation, 0.0, 1.0 );\012            n_dot_pos *= attenuation;\012   \
         n_dot_half *= attenuation;\015\012        }\012    }\015\012    re\
turn vec3( attenuation, n_dot_pos, n_dot_half);\012}\012"
### end
