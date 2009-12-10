#! /usr/bin/env python
'''=Practicality Beats Purity (Legacy Interaction)=

[shader_12.py-screen-0001.png Screenshot]

This tutorial:

    * use scenegraph GLSL shader nodes to simplify the code


'''
#import OpenGL 
#OpenGL.FULL_LOGGING = True 
from shader_11 import TestContext as BaseContext
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL.shaders import *
from OpenGLContext.scenegraph.basenodes import *

class TestContext( BaseContext ):
    """Demonstrates use of attribute types in GLSL
    """
    def OnInit( self ):
        """Initialize the context"""
        self.lights = self.createLights()
        self.LIGHTS = array([
            self.lightAsArray(l)
            for l in self.lights 
        ],'f')
        '''Now we take the set of lights and turn them into an array of 
        lighting parameters to be passed into the shader.'''
        self.LIGHTS = array([
            self.lightAsArray(l)
            for l in self.lights 
        ],'f')
        self.shader_constants['LIGHT_COUNT'] = len(self.lights)
        
        '''Load our shader functions that we've stored in resources and files.'''
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
            ],
            shaders = [
                GLSLShader( 
                    imports = [
                        lightConst,
                        phong_preCalc,
                        light_preCalc,
                    ],
                    source = [
                        """
                        attribute vec3 Vertex_position;
                        attribute vec3 Vertex_normal;
                        attribute vec2 Vertex_texture_coordinate;
                        void main() {
                            gl_Position = gl_ModelViewProjectionMatrix * vec4( 
                                Vertex_position, 1.0
                            );
                            baseNormal = gl_NormalMatrix * normalize(Vertex_normal);
                            light_preCalc(Vertex_position);
                            Vertex_texture_coordinate_var = Vertex_texture_coordinate;
                        }"""
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
                                    Light_distance[i],
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
        
        coords,indices = Sphere( 
            radius = 1 
        ).compileArrays()
        self.coords = ShaderBuffer( buffer = coords )
        self.indices = ShaderIndexBuffer( buffer = indices )
        self.count = len(indices)
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

        
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        # Update lights on each frame...
        for i,light in enumerate( self.lights ):
            # update in case there's a change...
            self.LIGHTS[i] = self.lightAsArray( light )
        self.glslObject.getVariable( 'lights' ).value = self.LIGHTS
        # Same for material...
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
            glDrawElements(
                GL_TRIANGLES, self.count,
                GL_UNSIGNED_INT, vbo
            )
        finally:
            for attribute,token in tokens:
                attribute.renderPost( self.glslObject, mode, token )
            self.glslObject.renderPost( token, mode )
            vbo.unbind()

    def lightAsArray( self, light ):
        """Given a single VRML97 light-node, produce light value array"""
        def sk(k):
            return self.shader_constants[k]
        key = 'uniform-array'
        result = self.cache.getData(light, key= key )
        if result is None:
            result = zeros( (sk('LIGHT_SIZE'),4), 'f' )
            depends_on = ['on']
            if light.on:
                color = light.color
                depends_on.append( 'color' )
                D,A,S,P,AT = (
                    sk('DIFFUSE'),
                    sk('AMBIENT'),
                    sk('SPECULAR'),
                    sk('POSITION'),
                    sk('ATTENUATION')
                )
                result[ D ][:3] = color * light.intensity
                result[ D ][3] = 1.0
                result[ A ][:3] = color * light.ambientIntensity
                result[ A ][3] = 1.0
                result[ S ][:3] = color
                result[ S ][3] = 1.0
                depends_on.append( 'intensity' )
                depends_on.append( 'ambientIntensity' )
                
                if not isinstance( light, DirectionalLight ):
                    result[P][:3] = light.location
                    result[P][3] = 1.0
                    result[AT][:3] = light.attenuation
                    result[AT][3] = 1.0
                    depends_on.append( 'location' )
                    depends_on.append( 'attenuation' )
                    if isinstance( light, SpotLight ):
                        result[sk('SPOT_DIR')][:3] = light.direction 
                        result[sk('SPOT_DIR')][3] = 1.0
                        result[sk('SPOT_PARAMS')] = [
                            cos( light.beamWidth/4.0 ),
                            light.cutOffAngle/light.beamWidth,
                            0,
                            1.0,
                        ]
                        depends_on.append( 'direction' )
                        depends_on.append( 'cutOffAngle' )
                        depends_on.append( 'beamWidth' )
                else:
                    result[P][:3] = -light.direction
                    result[P][3] = 0.0
                    depends_on.append( 'direction' )
            holder = self.cache.holder( 
                light,result,key=key
            )
            for field in depends_on:
                holder.depend( light, field )
        return result 



if __name__ == "__main__":
    TestContext.ContextMainLoop()
