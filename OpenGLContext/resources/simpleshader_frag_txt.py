# -*- coding: ISO-8859-1 -*-
"""Resource simpleshader_frag_txt (from file simpleshader.frag.txt)"""
# written by resourcepackage: (1, 0, 1)
source = 'simpleshader.frag.txt'
package = 'OpenGLContext.resources'

import zlib
data = (
    b'// The fragment shader a GLSLObject gets when it brings only'
    b' a vertex shader.\n//\n// Available as res://simpleshader_frag'
    b'_txt.\n#version 330 core\n\nout vec4 fragColor;\n\nvoid main() {\n'
    b'\tfragColor = vec4( 0, 1, 0, 1 );\n}\n'
)
