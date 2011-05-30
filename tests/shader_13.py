#! /usr/bin/env python
'''=Instanced Geometry Extension=

This tutorial:

    * uses an instanced geometry rendering extension to draw lots of geometry

ARB_draw_instanced is an extremely common extension available on most modern 
discrete OpenGL cards.  It defines a mechanism whereby you can generate a large 
number of "customized" instances of a given piece of geometry using a single call 
to the GL.  It requires the use of shaders, as the only difference between the 
calls is a shader variable:

    gl_InstanceIDARB

which is incremented by one for each instance.
'''
from shader_11 import TestContext as BaseContext
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL.shaders import *
'''OpenGLContext registers the shader nodes as "core" VRML97 nodes, so
we can just import the base node-set.'''
from OpenGLContext.scenegraph.basenodes import *
'''The ARB_draw_instanced extension is part of core OpenGL 3.3, so the entry 
points are available from the OpenGL.GL namespace by default (for all versions 
of PyOpenGL >= 3.0.2), thus you could omit this line with a newer PyOpenGL.'''
from OpenGL.GL.ARB.draw_instanced import *
'''For our sample code, we'll create an array of N spheres to render.  We'll 
use the standard Python module "random" to generate a few offsets.  Note that 
the size of uniform objects in OpenGL tends to be limited, and you will often 
see malloc failures if you attempt to create extremely large arrays this way.
'''
from numpy import random
offsets = (
    # we require RGBA to be compatible with < OpenGL 4.x
    random.random( size=(200,4 ) ) * [40,40,40,0] + [-20,-20,-40,1]
).astype('f')

class TestContext( BaseContext ):
    def OnInit( self ):
        """Initialize the context"""
        '''Our basic setup is the same as our previous tutorial...'''
        self.lights = self.createLights()
        self.LIGHTS = array([
            self.lightAsArray(l)
            for l in self.lights
        ],'f')
        self.shader_constants['LIGHT_COUNT'] = len(self.lights)
        light_preCalc = GLSLImport( url='_shader_tut_lightprecalc.vert' )
        phong_preCalc = GLSLImport( url="res://phongprecalc_vert" )
        phong_weightCalc = GLSLImport( url="res://phongweights_frag" )
        lightConst = GLSLImport( source = "\n".join([
                "const int %s = %s;"%( k,v )
                for k,v in self.shader_constants.items()
            ]) + """
            uniform vec4 lights[ LIGHT_COUNT*LIGHT_SIZE ];

            varying vec3 EC_Light_half[LIGHT_COUNT];
            varying vec3 EC_Light_location[LIGHT_COUNT];
            varying float Light_distance[LIGHT_COUNT];

            varying vec3 baseNormal;
            varying vec2 Vertex_texture_coordinate_var;
            """
        )
        '''To make the instanced geometry do something, we have to pass in a data-array 
        which will be indexed by the gl_InstanceIDARB variable.  For this simple tutorial 
        we will use an array of offsets which are applied to the geometry.  We will use 
        len(offset) values here.
        
        '''
        '''Now our Vertex Shader, which is only a tiny change from our previous shader,
        basically it just addes offsets[gl_InstanceIDARB] to the Vertex_position to get 
        the new position for the vertex being generated.'''
        VERTEX_SHADER = """
        attribute vec3 Vertex_position;
        attribute vec3 Vertex_normal;
        attribute vec2 Vertex_texture_coordinate;
        uniform usamplerBuffer offsets_table;
        void main() {
            vec3 final_position = Vertex_position + texelFetch( offsets_table, gl_InstanceIDARB ).xyz;
            final_position.x += float(gl_InstanceIDARB);
            gl_Position = gl_ModelViewProjectionMatrix * vec4(
                final_position, 1.0
            );
            baseNormal = gl_NormalMatrix * normalize(Vertex_normal);
            light_preCalc(final_position);
            Vertex_texture_coordinate_var = Vertex_texture_coordinate;
        }"""
        '''We set up our GLSLObjects as before, using VERTEX_SHADER as the source 
        for our GLSLShader vertex object.'''
        self.glslObject = GLSLObject(
            uniforms = [
                FloatUniform1f(name="material.shininess", value=.5 ),
                FloatUniform4f(name="material.ambient", value=(.1,.1,.1,1.0) ),
                FloatUniform4f(name="material.diffuse", value=(1.0,1.0,1.0,1.0) ),
                FloatUniform4f(name="material.specular", value=(.4,.4,.4,1.0) ),
                FloatUniform4f(name="Global_ambient", value=(.1,.1,.1,1.0) ),
                FloatUniform4f(name="lights" ),
            ],
            textures = [
                TextureUniform(name="diffuse_texture", value=ImageTexture(
                    url="marbleface.jpeg",
                )),
                TextureBufferUniform(
                    name='offsets_table',
                    format='RGBA32F',
                    value = ShaderBuffer(
                        usage = 'STATIC_DRAW',
                        type = 'TEXTURE',
                        buffer = offsets,
                    ),
                )
            ],
            shaders = [
                GLSLShader(
                    imports = [
                        lightConst,
                        phong_preCalc,
                        light_preCalc,
                    ],
                    source = [
                        VERTEX_SHADER
                    ],
                    type='VERTEX'
                ),
                GLSLShader(
                    imports = [
                        lightConst,
                        phong_weightCalc,
                    ],
                    source = [
                        """
                        struct Material {
                            vec4 ambient;
                            vec4 diffuse;
                            vec4 specular;
                            float shininess;
                        };
                        uniform Material material;
                        uniform vec4 Global_ambient;
                        uniform sampler2D diffuse_texture;

                        void main() {
                            vec4 fragColor = Global_ambient * material.ambient;

                            vec4 texDiffuse = texture2D(
                                diffuse_texture, Vertex_texture_coordinate_var
                            );
                            texDiffuse = mix( material.diffuse, texDiffuse, .5 );

                            // Again, we've moved the "hairy" code into the reusable
                            // function, our loop simply calls the phong calculation
                            // with the values from our uniforms and attributes...
                            int i,j;
                            for (i=0;i<LIGHT_COUNT;i++) {
                                j = i * LIGHT_SIZE;
                                vec3 weights = phong_weightCalc(
                                    normalize(EC_Light_location[i]),
                                    normalize(EC_Light_half[i]),
                                    normalize(baseNormal),
                                    material.shininess,
                                    abs(Light_distance[i]), // see note tutorial 9
                                    lights[j+ATTENUATION],
                                    lights[j+SPOT_PARAMS],
                                    lights[j+SPOT_DIR]
                                );
                                fragColor = (
                                    fragColor
                                    + (lights[j+AMBIENT] * material.ambient * weights.x)
                                    + (lights[j+DIFFUSE] * texDiffuse * weights.y)
                                    + (lights[j+SPECULAR] * material.specular * weights.z)
                                );
                            }
                            gl_FragColor = fragColor;
                        }
                        """
                    ],
                    type='FRAGMENT',
                ),
            ],
        )
        '''We tell our sphere to generate fewer "slices" in its tessellation by reducing it's "phi" 
        parameter.'''
        coords,indices = Sphere(
            radius = 1,
            phi = pi/8.0
        ).compileArrays()
        self.coords = ShaderBuffer( buffer = coords )
        self.indices = ShaderIndexBuffer( buffer = indices )
        '''For interest sake, we print out the number of objects/triangles being rendered'''
        self.count = len(indices)
        print 'Each sphere has %s triangles, total of %s triangles'%( self.count//3, self.count//3 * len(offsets) )
        '''Our attribute setup is unchanged.'''
        stride = coords[0].nbytes
        self.attributes = [
            ShaderAttribute(
                name = 'Vertex_position',
                offset = 0,
                stride = stride,
                buffer = self.coords,
                isCoord = True,
            ),
            ShaderAttribute(
                name = 'Vertex_texture_coordinate',
                offset = 4*3,
                stride = stride,
                buffer = self.coords,
                size = 2,
                isCoord = False,
            ),
            ShaderAttribute(
                name = 'Vertex_normal',
                offset = 4*5,
                stride = stride,
                buffer = self.coords,
                isCoord = False,
            ),
        ]
        self.appearance = Appearance(
            material = Material(
                diffuseColor = (1,1,1),
                ambientIntensity = .1,
                shininess = .5,
            ),
        )
    
    '''The only change to our render method is in the glDrawElements call, which 
    is replaced by a call to glDrawElementsInstancedARB'''
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        if not mode.visible:
            return
        for i,light in enumerate( self.lights ):
            self.LIGHTS[i] = self.lightAsArray( light )
        self.glslObject.getVariable( 'lights' ).value = self.LIGHTS
        for key,value in self.materialFromAppearance(
            self.appearance, mode
        ).items():
            self.glslObject.getVariable( key ).value = value
        token = self.glslObject.render( mode )
        tokens = [  ]
        try:
            vbo = self.indices.bind(mode)
            for attribute in self.attributes:
                token = attribute.render( self.glslObject, mode )
                if token:
                    tokens.append( (attribute, token) )
            '''The final parameter to glDrawElementsInstancedARB simply tells the 
            GL how many instances to generate.  gl_InstanceIDARB values will be 
            generated for range( instance_count ) instances.'''
            glDrawElementsInstancedARB(
                GL_TRIANGLES, self.count,
                GL_UNSIGNED_INT, vbo,
                len(offsets), # number of instances to draw...
            )
        finally:
            for attribute,token in tokens:
                attribute.renderPost( self.glslObject, mode, token )
            self.glslObject.renderPost( token, mode )
            vbo.unbind()

if __name__ == "__main__":
    TestContext.ContextMainLoop()

