# -*- coding: ISO-8859-1 -*-
"""Resource phongprecalc_vert (from file phongprecalc.vert)"""
# written by resourcepackage: (1, 0, 1)
source = 'phongprecalc.vert'
package = 'OpenGLContext.resources'
data = "// Vertex-shader pre-calculation for blinn-phong lighting\012vo\
id phong_preCalc( \012    in vec3 vertex_position,\012    in vec4 \
light_position,\012    out float light_distance,\012    out vec3 e\
c_light_location,\012    out vec3 ec_light_half\012) {\012    // This\
 is the core setup for a phong lighting pass as a reusable f\
ragment of code.\012    \012    // vertex_position -- un-transform\
ed vertex position (world-space)\012    // light_position -- un\
-transformed light location (direction)\012    // light_distanc\
e -- output giving world-space distance-to-light \012    // ec_\
light_location -- output giving location of light in eye coo\
rds \012    // ec_light_half -- output giving the half-vector o\
ptimization\012    \012    if (light_position.w == 0.0) {\012        \
// directional rather than positional light...\012        ec_li\
ght_location = normalize(\012            gl_NormalMatrix *\012    \
        light_position.xyz\012        );\012        light_distance\
 = 0.0;\012    } else {\012        // positional light, we calcula\
te distance in \012        // model-view space here, so we take\
 a partial \012        // solution...\012        vec3 ms_vec = (\012 \
           light_position.xyz -\012            vertex_position\012\
        );\012        vec3 light_direction = gl_NormalMatrix * \
ms_vec;\012        ec_light_location = normalize( light_directi\
on );\012        light_distance = abs(length( ms_vec ));\012    }\012\
    // half-vector calculation \012    ec_light_half = normaliz\
e(\012        ec_light_location - vec3( 0,0,-1 )\012    );\012}\012"
### end
