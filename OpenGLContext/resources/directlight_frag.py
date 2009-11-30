# -*- coding: ISO-8859-1 -*-
"""Resource directlight_frag (from file directlight.frag)"""
# written by resourcepackage: (1, 0, 1)
source = 'directlight.frag'
package = 'OpenGLContext.resources'
data = "// Comes (loosely) from the orange book listing 9.6\012vec3 dLi\
ght( \012\011in vec3 light_pos, // light position\012\011in vec3 light_h\
alf, // light's half-vector value\012\011in vec3 normal, // geomet\
ry normal\012\011in float shininess // material shininess\012) {\012\011// \
returns vec3( ambientMult, diffuseMult, specMult )\012\011float n_\
dot_pos = max( 0.0, dot( normal, normalize(light_pos)));\012\011fl\
oat n_dot_half = max( 0.0, dot( normal, light_half ));\012\011floa\
t specular = 0.0;\012\011if (n_dot_pos != 0.0) {\012\011\011specular = pow(\
 n_dot_half, shininess );\012\011}\012\011return vec3( 1.0, n_dot_pos, s\
pecular );\012}\012"
### end