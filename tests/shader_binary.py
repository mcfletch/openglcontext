#! /usr/bin/env python
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL.shaders import *
from OpenGLContext.scenegraph.basenodes import Sphere

class TestContext( BaseContext ):
    LIGHT_COUNT = 3
    LIGHT_SIZE = 7
    def OnInit( self ):
        """Initialize the context"""
        lightConst = """
        const int LIGHT_COUNT = %s;
        const int LIGHT_SIZE = %s;
        
        const int AMBIENT = 0;
        const int DIFFUSE = 1;
        const int SPECULAR = 2;
        const int POSITION = 3;
        const int ATTENUATION = 4;
        //SPOT_PARAMS [ cos_spot_cutoff, spot_exponent, ignored, is_spot ]
        const int SPOT_PARAMS = 5;
        const int SPOT_DIR = 6;
        
        uniform vec4 lights[ LIGHT_COUNT*LIGHT_SIZE ];
        varying vec3 EC_Light_half[LIGHT_COUNT];
        varying vec3 EC_Light_location[LIGHT_COUNT]; 
        varying float Light_distance[LIGHT_COUNT]; 
        
        varying vec3 baseNormal;
        """%( self.LIGHT_COUNT, self.LIGHT_SIZE )
        phong_weightCalc = """
        vec3 phong_weightCalc( 
            in vec3 light_pos, // light position/direction
            in vec3 half_light, // half-way vector between light and view
            in vec3 frag_normal, // geometry normal
            in float shininess, // shininess exponent
            in float distance, // distance for attenuation calculation...
            in vec4 attenuations, // attenuation parameters...
            in vec4 spot_params, // spot control parameters...
            in vec4 spot_direction // model-space direction
        ) {
            // returns vec3( ambientMult, diffuseMult, specularMult )
            
            float n_dot_pos = max( 0.0, dot( 
                frag_normal, light_pos
            ));
            float n_dot_half = 0.0;
            float attenuation = 1.0;
            if (n_dot_pos > -.05) {
                float spot_effect = 1.0;
                if (spot_params.w != 0.0) {
                    // is a spot...
                    float spot_cos = dot(
                        gl_NormalMatrix * normalize(spot_direction.xyz),
                        normalize(-light_pos)
                    );
                    if (spot_cos <= spot_params.x) {
                        // is a spot, and is outside the cone-of-light...
                        return vec3( 0.0, 0.0, 0.0 );
                    } else {
                        if (spot_cos == 1.0) {
                            spot_effect = 1.0;
                        } else {
                            spot_effect = pow( 
                                    (1.0-spot_params.x)/(1.0-spot_cos), 
                                    spot_params.y 
                                );
                        }
                    }
                }
                n_dot_half = pow(
                    max(0.0,dot( 
                        half_light, frag_normal
                    )), 
                    shininess
                );
                if (distance != 0.0) {
                    float attenuation = 1.0/(
                        attenuations.x + 
                        (attenuations.y * distance) +
                        (attenuations.z * distance * distance)
                    );
                    n_dot_half *= spot_effect;
                    n_dot_pos *= attenuation;
                    n_dot_half *= attenuation;
                }
            }
            return vec3( attenuation, n_dot_pos, n_dot_half);
        }		
        """
        from OpenGLContext.resources.phongprecalc_vert import data as phong_preCalc
        light_preCalc = open( '_shader_tut_lightprecalc.vert' ).read()
        
        vertex = compileShader( 
            lightConst + phong_preCalc + light_preCalc + 
        """
        attribute vec3 Vertex_position;
        attribute vec3 Vertex_normal;
        void main() {
            gl_Position = gl_ModelViewProjectionMatrix * vec4( 
                Vertex_position, 1.0
            );
            baseNormal = gl_NormalMatrix * normalize(Vertex_normal);
            light_preCalc( Vertex_position );
        }""", GL_VERTEX_SHADER)
        
        '''Our only change for the fragment shader is to pass in the 
        spot components of the current light when calling phong_weightCalc.'''
        fragment = compileShader( 
            lightConst + phong_weightCalc + """
        struct Material {
            vec4 ambient;
            vec4 diffuse;
            vec4 specular;
            float shininess;
        };
        uniform Material material;
        uniform vec4 Global_ambient;
        
        void main() {
            vec4 fragColor = Global_ambient * material.ambient;
            
            int i,j;
            for (i=0;i<LIGHT_COUNT;i++) {
                j = i* LIGHT_SIZE;
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
                    + (lights[j+DIFFUSE] * material.diffuse * weights.y)
                    + (lights[j+SPECULAR] * material.specular * weights.z)
                );
            }
            gl_FragColor = fragColor;
        }
        """, GL_FRAGMENT_SHADER)
        self.shader = compileProgram(vertex,fragment, retrievable=True)
        format,data = self.shader.retrieve()
        print 'Retrieved copiled shader:', format, data 
        self.shader.load( format, data )
        print 'loaded shader from binary'

if __name__ == "__main__":
    TestContext.ContextMainLoop()

