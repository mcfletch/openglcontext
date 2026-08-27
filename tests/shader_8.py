#! /usr/bin/env python
'''=Optimizations for Directional Lights=

[shader_8.py-screen-0001.png Screenshot]

This tutorial builds on earlier tutorials by adding:

    * Optimizing the Point-light code using Vertex shader
    * Using constant/common declaration blocks

This very short tutorial simply optimizes the code we created 
in our last tutorial.  Fragment shaders are called for every 
fragment (possible pixel) that is not "culled".  As a result,
they tend to be called far more often than vertex shaders.

Our current code is very wasteful in that it does all of the light 
calculations for every fragment.  We'll split out the calculations 
so that the vertex shader provides interpolated values to the 
fragment shader.
'''
#import OpenGL
#OpenGL.FULL_LOGGING = True
#OpenGL.USE_ACCELERATE = False
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders
from OpenGLContext.scenegraph.basenodes import Sphere

class TestContext( BaseContext ):
    """Demonstrates use of attribute types in GLSL
    """
    LIGHT_COUNT = 3
    LIGHT_SIZE = 4
    def OnInit( self ):
        """Initialize the context"""
        '''==Sharing Declarations=
        
        Since we are going to use these values in both the 
        vertex and fragment shaders, it is handy to separate out 
        the constants we'll use into a separate block of code that 
        we can add to both shaders.  The use of the constants also 
        makes the code far easier to read than using the bare numbers.
        
        The values the vertex shader passes on to the fragment shader
        are declared "out" where they are written and "in" where they
        are read, so those go in a second shared block with the
        direction filled in per shader.  baseNormal is part of the
        lighting calculation, so it travels with them.
        
        We've also parameterized the LIGHT count and size, so that 
        we can use them in both Python and GLSL code.
        '''
        lightConst = """#version 330 core
        const int LIGHT_COUNT = %s;
        const int LIGHT_SIZE = %s;
        
        const int AMBIENT = 0;
        const int DIFFUSE = 1;
        const int SPECULAR = 2;
        const int POSITION = 3;
        
        uniform vec4 lights[ LIGHT_COUNT*LIGHT_SIZE ];
        """%( self.LIGHT_COUNT, self.LIGHT_SIZE )
        lightVarying = """
        %(dir)s vec3 EC_Light_half[LIGHT_COUNT];
        %(dir)s vec3 EC_Light_location[LIGHT_COUNT];

        %(dir)s vec3 baseNormal;
        """
        '''As you can see, we're going to pass two new values from
        the vertex shader to the fragment shader, the EC_Light_half and
        EC_Light_location values.  These are going to hold the
        normalized partial calculations for the lights.  The other
        declarations are the same as before, they are just being shared
        between the shaders.
        
        Our phong_weightCalc calculation hasn't changed.
        '''
        phong_weightCalc = """
        vec2 phong_weightCalc( 
            in vec3 light_pos, // light position
            in vec3 half_light, // half-way vector between light and view
            in vec3 frag_normal, // geometry normal
            in float shininess
        ) {
            // returns vec2( ambientMult, diffuseMult )
            float n_dot_pos = max( 0.0, dot( 
                frag_normal, light_pos
            ));
            float n_dot_half = 0.0;
            if (n_dot_pos > -.05) {
                n_dot_half = pow(max(0.0,dot( 
                    half_light, frag_normal
                )), shininess);
            }
            return vec2( n_dot_pos, n_dot_half);
        }		
        """
        '''Our new vertex shader has a loop in it.  It iterates over the 
        set of lights doing the partial calculations for half-vector 
        and eye-space location.  It stores the results of these in our
        new, varying array values.
        '''
        vertex = shaders.compileShader( 
            lightConst + lightVarying%{'dir':'out'} +
        """
        uniform mat4 modelViewProjection;
        uniform mat3 normalMatrix;

        in vec3 Vertex_position;
        in vec3 Vertex_normal;
        
        void main() {
            gl_Position = modelViewProjection * vec4( 
                Vertex_position, 1.0
            );
            baseNormal = normalMatrix * normalize(Vertex_normal);
            for (int i = 0; i< LIGHT_COUNT; i++ ) {
                EC_Light_location[i] = normalize(
                    normalMatrix * lights[(i*LIGHT_SIZE)+POSITION].xyz
                );
                // half-vector calculation 
                EC_Light_half[i] = normalize(
                    EC_Light_location[i] - vec3( 0,0,-1 )
                );
            }
        }""", GL_VERTEX_SHADER)
        '''Our fragment shader looks much the same, save that we 
        have now moved the complex half-vector and eye-space location 
        calculations out.  We've also separated out the concept of 
        which light we are processing and what array-offset we are 
        using, to make it clearer which value is being accessed.
        '''
        fragment = shaders.compileShader( 
            lightConst + lightVarying%{'dir':'in'} + phong_weightCalc + """
        struct Material {
            vec4 ambient;
            vec4 diffuse;
            vec4 specular;
            float shininess;
        };
        uniform Material material;
        uniform vec4 Global_ambient;
        out vec4 finalColor;
        
        void main() {
            vec4 fragColor = Global_ambient * material.ambient;
            
            int i,j;
            for (i=0;i<LIGHT_COUNT;i++) {
                j = i* LIGHT_SIZE;
                vec2 weights = phong_weightCalc(
                    EC_Light_location[i],
                    EC_Light_half[i],
                    baseNormal,
                    material.shininess
                );
                fragColor = (
                    fragColor 
                    + (lights[j+AMBIENT] * material.ambient)
                    + (lights[j+DIFFUSE] * material.diffuse * weights.x)
                    + (lights[j+SPECULAR] * material.specular * weights.y)
                );
            }
            finalColor = fragColor;
        }
        """, GL_FRAGMENT_SHADER)
        
        '''The rest of our code is very familiar.'''
        self.shader = shaders.compileProgram(vertex,fragment)
        self.coords,self.indices,self.count = Sphere( 
            radius = 1 
        ).compile()
        self.uniform_locations = {}
        for uniform,value in self.UNIFORM_VALUES:
            location = glGetUniformLocation( self.shader, uniform )
            if location in (None,-1):
                print('Warning, no uniform: %s'%( uniform ))
            self.uniform_locations[uniform] = location
        for uniform in ('modelViewProjection','normalMatrix'):
            self.uniform_locations[uniform] = glGetUniformLocation(
                self.shader, uniform
            )
        self.vao = glGenVertexArrays( 1 )
        self.uniform_locations['lights'] = glGetUniformLocation( 
            self.shader, 'lights' 
        )
        for attribute in (
            'Vertex_position','Vertex_normal',
        ):
            location = glGetAttribLocation( self.shader, attribute )
            if location in (None,-1):
                print('Warning, no attribute: %s'%( uniform ))
            setattr( self, attribute+ '_loc', location )
    UNIFORM_VALUES = [
        ('Global_ambient',(.05,.05,.05,1.0)),
        ('material.ambient',(.2,.2,.2,1.0)),
        ('material.diffuse',(.5,.5,.5,1.0)),
        ('material.specular',(.8,.8,.8,1.0)),
        ('material.shininess',(.995,)),
    ]
    LIGHTS = array([
        x[1] for x in [
            ('lights[0].ambient',(.05,.05,.05,1.0)),
            ('lights[0].diffuse',(.3,.3,.3,1.0)),
            ('lights[0].specular',(1.0,0.0,0.0,1.0)),
            ('lights[0].position',(4.0,2.0,10.0,0.0)),
            ('lights[1].ambient',(.05,.05,.05,1.0)),
            ('lights[1].diffuse',(.3,.3,.3,1.0)),
            ('lights[1].specular',(0.0,1.0,0.0,1.0)),
            ('lights[1].position',(-4.0,2.0,10.0,0.0)),
            ('lights[2].ambient',(.05,.05,.05,1.0)),
            ('lights[2].diffuse',(.3,.3,.3,1.0)),
            ('lights[2].specular',(0.0,0.0,1.0,1.0)),
            ('lights[2].position',(-4.0,2.0,-10.0,0.0)),
        ]
    ], 'f')
    def Render( self, mode ):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        if not mode.visible:
            return 
        glUseProgram(self.shader)
        glUniformMatrix4fv(
            self.uniform_locations['modelViewProjection'], 1, GL_FALSE,
            dot( mode.matrix, mode.projection ),
        )
        glUniformMatrix3fv(
            self.uniform_locations['normalMatrix'], 1, GL_FALSE,
            ascontiguousarray( mode.matrix[:3,:3], dtype='f' ),
        )
        glBindVertexArray( self.vao )
        try:
            self.coords.bind()
            stride = self.coords.data[0].nbytes
            try:
                '''Note the use of the parameterized values to specify 
                the size of the light-parameter array.'''
                glUniform4fv( 
                    self.uniform_locations['lights'],
                    self.LIGHT_COUNT * self.LIGHT_SIZE,
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
                self.indices.bind()
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
            glBindVertexArray( 0 )
            glUseProgram( 0 )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''With our shaders now reasonably optimized, we can move on to 
creating point-lights (as opposed to our current directional lights).'''
