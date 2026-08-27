# -*- coding: ISO-8859-1 -*-
"""Resource simpleshader_vert_txt (from file simpleshader.vert.txt)"""
# written by resourcepackage: (1, 0, 1)
source = 'simpleshader.vert.txt'
package = 'OpenGLContext.resources'

import zlib
data = (
    b'// The vertex shader a GLSLObject gets when it brings only a'
    b' fragment shader.\n//\n// A core profile has no fixed-function'
    b' vertex stage, so a fragment shader on\n// its own has nothin'
    b"g to draw with.  This one reads the engine's own vertex\n// a"
    b'rrays -- see OpenGLContext/scenegraph/vertexsemantics.py -- '
    b'and passes on\n// the values a fragment shader written agains'
    b't the fixed-function pipeline\n// used to find in gl_TexCoord'
    b'[0], gl_Color and the interpolated normal.\n//\n// Available a'
    b's res://simpleshader_vert_txt.\n#version 330 core\n\n// Supplie'
    b'd by the render pass to any GLSLObject that names them.\nunif'
    b'orm mat4 mat_modelproj;\nuniform mat4 itp_modelview;\n\nin vec3'
    b' aPosition;\nin vec3 aNormal;\nin vec2 aTexCoord;\nin vec4 aCol'
    b'or;\n\nout vec3 baseNormal;\nout vec2 texCoord;\nout vec4 vertex'
    b'Color;\n\nvoid main() {\n\tbaseNormal = mat3( itp_modelview ) * '
    b'aNormal;\n\ttexCoord = aTexCoord;\n\t// Geometry with no colour '
    b'array leaves this attribute unfed, which reads\n\t// as (0,0,0'
    b',1); the shaders below want white in that case.\n\tvertexColor'
    b' = vec4( max( aColor.rgb, vec3(1.0) - sign(aColor.a) ), 1.0 '
    b');\n\tgl_Position = mat_modelproj * vec4( aPosition, 1.0 );\n}\n'
)
