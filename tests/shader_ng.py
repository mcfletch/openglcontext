#! /usr/bin/env python
from shader_11 import TestContext as BaseContext
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph import box

class VertexDefinition( list ):
    """Small utility class to make it easy to define/load shader vertex arrays
    """
    POSITION = NORMAL = ('x','y','z','w')
    COLOR = ('r','g','b','a')
    TEXCOORD = ('u','v','r','z')
    _dtype=None
    def add_vec( self, name, count=3, components = POSITION, type='1f' ):
        components = [(c,type) for c in components][:count]
        record = (name,components)
        self.append(record)
        return record 
    
    @property
    def dtype( self ):
        if not self._dtype:
            self._dtype = dtype( self )
        return self._dtype
    
    def attributes( self, buffer, prefix='vtx' ):
        """Generate ShaderAttribute instances for the given buffer 
        
        buffer -- must be a ShaderBuffer instance pointing to an array of 
            dtype == self.dtype which can be obtained by calling 
            .view( self.dtype) on an array of the appropriate shape/size 
            (i.e. with the right number of floats in each row).
        prefix -- added to name as the attribute name to be used in the 
            shader object
        """
        dtype = self.dtype 
        result = []
        offset = 0
        for i,set in enumerate(self):
            attribute = ShaderAttribute(
                name = "_".join([prefix,set[0]]),
                offset = offset,
                stride = dtype.itemsize, # overall
                buffer = buffer,
                size = len(set[1]), # TODO: assumes 1f sizes, that's *not* necessarily true!
                isCoord = set[0] == 'position',
                bufferKey = set[0],
            )
            offset += dtype[i].itemsize
            result.append( attribute )
        return result

class TestContext( BaseContext ):
    def OnInit( self ):
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
            varying vec2 vtx_texcoord_0_var;
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
                        attribute vec3 vtx_position;
                        attribute vec3 vtx_normal;
                        attribute vec2 vtx_texcoord_0;
                        
                        // modelview matrix and inverse...
                        uniform mat4 mat_modelview; 
                        uniform mat4 inv_modelview;
                        uniform mat4 tps_modelview;
                        uniform mat4 itp_modelview;
                        
                        // projection matrix and inverse...
                        uniform mat4 mat_projection;
                        uniform mat4 inv_projection;
                        uniform mat4 tps_projection;
                        uniform mat4 itp_projection;
                        
                        // combined matrices and inverse
                        uniform mat4 mat_modelproj;
                        uniform mat4 inv_modelproj;
                        uniform mat4 tps_modelproj;
                        uniform mat4 itp_modelproj; // a.k.a. gl_NormalMatrix
                        
                        void main() {
                            mat4 combined = mat_modelproj;
                            //mat4 mat_normal = transpose(inverse(mat_modelview));
                            //mat4 mat_normal = transpose(inv_modelview);
                            mat4 mat_normal = transpose(inv_modelview);
                            vec4 position = combined * vec4(
                                vtx_position, 1.0
                            );
                            //baseNormal = normalize( gl_NormalMatrix * vtx_normal);
                            baseNormal = normalize( mat_normal * vec4(vtx_normal,0.0)).xyz;
                            light_preCalc(vtx_position);
                            vtx_texcoord_0_var = vtx_texcoord_0;
                            gl_Position = position;
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
                                diffuse_texture, vtx_texcoord_0_var
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
        
        vertex_def = VertexDefinition()
        vertex_def.add_vec( 'texcoord_0',2,vertex_def.TEXCOORD)
        vertex_def.add_vec( 'normal' )
        vertex_def.add_vec( 'position' )
        
        '''Generate a simple box model with a "baked in" size...'''
        coords = array(list(
            box.yieldVertices((2,.5,2))
        ),'8f').view( vertex_def.dtype )
        self.coords = ShaderBuffer( buffer = coords )
        
        self.appearance = Appearance(
            material = Material(
                diffuseColor = (1,1,1),
                ambientIntensity = .1,
                shininess = .5,
            ),
        )
        self.sg = Transform(
            rotation = (0,1,0,1.0),# radians
            scale = (1,2,1),
            children = [
                ShaderGeometry(
                    appearance = Shader( 
                        objects = [self.glslObject]
                    ),
                    indices = arange( 36, dtype='I' ),
                    attributes = vertex_def.attributes( self.coords, 'vtx' ),
                ),
            ],
        )
        # set uniform values...
        for i,light in enumerate( self.lights ):
            self.LIGHTS[i] = self.lightAsArray( light )
        self.glslObject.getVariable( 'lights' ).value = self.LIGHTS
        for key,value in self.materialFromAppearance(
            self.appearance
        ).items():
            self.glslObject.getVariable( key ).value = value
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
