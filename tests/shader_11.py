#! /usr/bin/env python
'''=Refactoring/Cleanup=

[shader_11.py-screen-0001.png Screenshot]

This tutorial:

    * cleans up and makes our shader code reusable

'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL.shaders import *
from OpenGLContext.scenegraph.basenodes import *
import time

class TestContext( BaseContext ):
    """Demonstrates use of attribute types in GLSL
    """
    shader_constants = dict(
        LIGHT_COUNT = 5,
        LIGHT_SIZE = 7,
        
        AMBIENT = 0,
        DIFFUSE = 1,
        SPECULAR = 2,
        POSITION = 3,
        ATTENUATION = 4,
        # SPOT_PARAMS [ cos_spot_cutoff, spot_exponent, ignored, is_spot ]
        SPOT_PARAMS = 5,
        SPOT_DIR = 6,
    )
    def OnInit( self ):
        """Initialize the context"""
        
        self.lights = [
            DirectionalLight(
                color = (.1,1,.1),
                intensity = 1.0,
                ambientIntensity = 0.1,
                direction = (-8,-20,-8),
            ),
            SpotLight(
                location = (-2.5,2.5,2.5),
                color = (1,.05,.05),
                ambientIntensity = .1,
                direction = (2.5,-5.5,-2.5),
            ),
            PointLight(
                location = (0,-3.06,3.06),
                color = (.05,.05,1),
                ambientIntensity = .1,
            ),
        ]
        self.LIGHTS = reshape( array([
            self.lightAsArray(l)
            for l in self.lights 
        ],'f'), (-1,4))
        self.shader_constants['LIGHT_COUNT'] = len(self.lights)
        print 'light count', len(self.lights)
        
        lightConst = "\n".join([
            "const int %s = %s;"%( k,v )
            for k,v in self.shader_constants.items()
        ]) + """
        uniform vec4 lights[ LIGHT_COUNT*LIGHT_SIZE ];
        
        varying vec3 EC_Light_half[LIGHT_COUNT];
        varying vec3 EC_Light_location[LIGHT_COUNT]; 
        varying float Light_distance[LIGHT_COUNT]; 
        
        varying vec3 baseNormal;
        """
        dLight = """
        vec3 lightPhong( 
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
                    attenuation = spot_effect / (
                            attenuations.x + 
                            (attenuations.y * distance) +
                            (attenuations.z * distance * distance)
                        );
                    n_dot_pos *= attenuation;
                    n_dot_half *= attenuation;
                }
            }
            return vec3( attenuation, n_dot_pos, n_dot_half);
        }
        """
        light_preCalc = """
        // Vertex-shader pre-calculation for lighting...
        void light_preCalc( in vec3 vertex_position ) {
            vec3 light_direction;
            for (int i = 0; i< LIGHT_COUNT; i++ ) {
                int j = i * LIGHT_SIZE;
                if (lights[j+POSITION].w == 0.0) {
                    // directional rather than positional light...
                    EC_Light_location[i] = normalize(
                        gl_NormalMatrix *
                        lights[j+POSITION].xyz
                    );
                    Light_distance[i] = 0.0;
                } else {
                    // positional light, we calculate distance in 
                    // model-view space here, so we take a partial 
                    // solution...
                    vec3 ms_vec = (
                        lights[j+POSITION].xyz -
                        vertex_position
                    );
                    light_direction = gl_NormalMatrix * ms_vec;
                    EC_Light_location[i] = normalize( light_direction );
                    Light_distance[i] = abs(length( ms_vec ));
                }
                
                // half-vector calculation 
                EC_Light_half[i] = normalize(
                    EC_Light_location[i] - vec3( 0,0,-1 )
                );
            }
        }"""
        vertex = compileShader( 
            lightConst + light_preCalc +
        """
        attribute vec3 Vertex_position;
        attribute vec3 Vertex_normal;
        
        void main() {
            gl_Position = gl_ModelViewProjectionMatrix * vec4( 
                Vertex_position, 1.0
            );
            baseNormal = gl_NormalMatrix * normalize(Vertex_normal);
            light_preCalc(Vertex_position);
        }""", GL_VERTEX_SHADER)
        fragment = compileShader( 
            lightConst + dLight + """
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
                j = i * LIGHT_SIZE;
                vec3 weights = lightPhong(
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
                    + (lights[j+DIFFUSE] * material.diffuse * weights.y)
                    + (lights[j+SPECULAR] * material.specular * weights.z)
                );
            }
            gl_FragColor = fragColor;
        }
        """, GL_FRAGMENT_SHADER)
        self.shader = compileProgram(vertex,fragment)
        self.coords,self.indices,self.count = Sphere( 
            radius = 1 
        ).compile()
        self.uniform_locations = {}
        for uniform,value in self.UNIFORM_VALUES:
            location = glGetUniformLocation( self.shader, uniform )
            if location in (None,-1):
                print 'Warning, no uniform: %s'%( uniform )
            self.uniform_locations[uniform] = location
        self.uniform_locations['lights'] = glGetUniformLocation( 
            self.shader, 'lights' 
        )
        for attribute in (
            'Vertex_position','Vertex_normal',
        ):
            location = glGetAttribLocation( self.shader, attribute )
            if location in (None,-1):
                print 'Warning, no attribute: %s'%( uniform )
            setattr( self, attribute+ '_loc', location )
    UNIFORM_VALUES = [
        ('Global_ambient',(.05,.05,.05,1.0)),
        ('material.ambient',(.2,.2,.2,1.0)),
        ('material.diffuse',(.8,.8,.8,1.0)),
        ('material.specular',(.3,.3,.3,1.0)),
        ('material.shininess',(.5,)),
    ]
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        
        BaseContext.Render( self, mode )
        glUseProgram(self.shader)
        try:
            self.coords.bind()
            self.indices.bind()
            stride = self.coords.data[0].nbytes
            try:
                glUniform4fv( 
                    self.uniform_locations['lights'],
                    len(self.LIGHTS),
                    self.LIGHTS
                )
                for uniform,value in self.UNIFORM_VALUES:
                    location = self.uniform_locations.get( uniform )
                    if location not in (None,-1):
                        if len(value) == 4:
                            glUniform4f( location, *value )
                        elif len(value) == 3:
                            glUniform3f( location, *value )
                        elif len(value) == 1:
                            glUniform1f( location, *value )
                glEnableVertexAttribArray( self.Vertex_position_loc )
                glEnableVertexAttribArray( self.Vertex_normal_loc )
                glVertexAttribPointer( 
                    self.Vertex_position_loc, 
                    3, GL_FLOAT,False, stride, self.coords
                )
                glVertexAttribPointer( 
                    self.Vertex_normal_loc, 
                    3, GL_FLOAT,False, stride, self.coords+(5*4)
                )
                glDrawElements(
                    GL_TRIANGLES, self.count,
                    GL_UNSIGNED_SHORT, self.indices
                )
            finally:
                self.coords.unbind()
                self.indices.unbind()
                glDisableVertexAttribArray( self.Vertex_position_loc )
                glDisableVertexAttribArray( self.Vertex_normal_loc )
        finally:
            glUseProgram( 0 )
    
    def lightAsArray( self, light ):
        """Given a single VRML97 light-node, produce light value array"""
        def sk(k):
            return self.shader_constants[k]
        result = zeros( (sk('LIGHT_SIZE'),4), 'f' )
        if light.on:
            color = light.color
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
            
            if not isinstance( light, DirectionalLight ):
                result[P][:3] = light.location
                result[P][3] = 1.0
                result[AT][:3] = light.attenuation
                result[AT][3] = 1.0
                if isinstance( light, SpotLight ):
                    result[sk('SPOT_DIR')][:3] = light.direction 
                    result[sk('SPOT_DIR')][3] = 1.0
                    result[sk('SPOT_PARAMS')] = [
                        cos( light.beamWidth/4.0 ),
                        light.cutOffAngle/light.beamWidth,
                        0,
                        1.0,
                    ]
            else:
                result[P][:3] = -light.direction
                result[P][3] = 0.0
        return result 

if __name__ == "__main__":
    TestContext.ContextMainLoop()
