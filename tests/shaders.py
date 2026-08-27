#! /usr/bin/env python
'''Tests rendering of a quantized ("toon") shader via the scenegraph shader nodes.

This is the same rendering setup as shadergeometry.py: geometry is handed to
ShaderGeometry nodes as raw vertex buffers with a custom Shader appearance,
rather than the legacy glUseProgram / glutSolid* / glRotate calls the original
version of this test used.  The sphere, cube and teapot buffers come from the
scenegraph geometry generators, so no GLUT primitives are needed.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array, concatenate
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.shaders import *
from OpenGLContext.scenegraph.quadrics import Sphere
from OpenGLContext.scenegraph import box
import math, logging
log = logging.getLogger( 'shaderobjects' )

STRIDE = 32  # 8 interleaved floats per vertex

# The rendering pass supplies its camera to any GLSLObject that names one of
# its matrices; the normal matrix is the upper-left 3x3 of the
# inverse-transpose model-view, which the pass calls itp_modelview.
TOON_VERTEX = '''#version 330 core
uniform mat4 mat_modelproj;
uniform mat4 itp_modelview;
in vec3 position;
in vec3 normal;
out vec3 baseNormal;
void main() {
    baseNormal = mat3( itp_modelview ) * normal;
    gl_Position = mat_modelproj * vec4( position, 1.0 );
}'''

TOON_FRAGMENT = '''#version 330 core
uniform vec3 light_location;
in vec3 baseNormal;
out vec4 fragColor;
void main() {
    vec3 n = normalize( baseNormal );
    vec3 l = normalize( light_location );
    // quantize to 5 steps (0, .25, .5, .75 and 1)
    float intensity = (floor(dot(l, n) * 4.0) + 1.0)/4.0;
    fragColor = vec4( intensity, intensity*0.5, intensity*0.5, 1.0 );
}'''


class TestContext( BaseContext ):
    light_location = (0, 10, 5)

    def OnInit( self ):
        """Scene set up and initial processing"""
        appearance = Shader(
            objects=[
                GLSLObject(
                    DEF="toon_shader",
                    uniforms=[
                        FloatUniform3f(
                            name="light_location",
                            value=self.light_location,
                        ),
                    ],
                    shaders=[
                        GLSLShader( source=[TOON_VERTEX], type="VERTEX" ),
                        GLSLShader( source=[TOON_FRAGMENT], type="FRAGMENT" ),
                    ],
                ),
            ],
        )
        self.tumble = Transform(
            children=[
                self.geometry( self.sphereVertices(), appearance,
                               position_offset=0, normal_offset=20 ),
                Transform(
                    translation=(1, 0, 2),
                    children=[
                        self.geometry( self.cubeVertices(), appearance,
                                       position_offset=20, normal_offset=8 ),
                    ],
                ),
                Transform(
                    translation=(3, 0, 2),
                    children=[
                        self.geometry( self.teapotVertices(), appearance,
                                       position_offset=20, normal_offset=8 ),
                    ],
                ),
            ],
        )
        self.pivot = Transform( children=[ self.tumble ] )
        self.sg = sceneGraph( children=[ self.pivot ] )
        self.time = Timer( duration = 2.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()

    def geometry( self, vertices, appearance, position_offset, normal_offset ):
        """Wrap an interleaved vertex array in a ShaderGeometry node.

        The generators interleave texcoord/normal/position in different orders,
        so the caller passes the byte offset of the position and normal
        components within each 8-float record.
        """
        buffer = ShaderBuffer( buffer=vertices )
        return ShaderGeometry(
            slices=[ ShaderSlice( offset=0, count=len(vertices) ) ],
            attributes=[
                ShaderAttribute(
                    name="position",
                    offset=position_offset,
                    stride=STRIDE,
                    size=3,
                    dataType="FLOAT",
                    buffer=buffer,
                    isCoord=True,
                ),
                ShaderAttribute(
                    name="normal",
                    offset=normal_offset,
                    stride=STRIDE,
                    size=3,
                    dataType="FLOAT",
                    buffer=buffer,
                ),
            ],
            appearance=appearance,
        )

    def sphereVertices( self ):
        """Unit sphere as a flat triangle list (position, texcoord, normal)."""
        coords, indices = Sphere( radius=1.0 ).compileArrays( 0 )
        return array( coords, 'f' )[ indices ]

    def cubeVertices( self ):
        """Unit cube as a flat triangle list (texcoord, normal, position)."""
        return array( list( box.yieldVertices( (1, 1, 1) ) ), 'f' )

    def teapotVertices( self ):
        """Teapot shell as a flat triangle list (texcoord, normal, position)."""
        from OpenGLContext.scenegraph.teapot_nurbs import (
            tessellate_teapot, steps_for_level,
        )
        base, lid = tessellate_teapot(
            steps=steps_for_level( 0 ), interior=False,
        )
        return concatenate(
            [ array( base, 'f' ), array( lid, 'f' ) ]
        ).reshape( (-1, 8) )

    def OnTimerFraction( self, event ):
        fraction = event.fraction()
        self.pivot.rotation = (0, 1, 0, fraction * 2 * math.pi)
        self.tumble.rotation = (0.7071, 0, 0.7071, -fraction * 2 * math.pi)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
