#! /usr/bin/env python
'''=Point Lights=

[shader_9.py-screen-0001.png Screenshot]

This tutorial builds on earlier tutorials by adding:

    * Point Light Sources (PointLights)
    * Per-vertex angle/direction calculations
    * Per-vertex attenuation (light fall-off) calculations

This tutorial includes rather a lot of changes to our shaders.
We are going to make the shaders capable of rendering either a
directional light source (as we've been doing) or a point light 
source (such as an unshielded lightbulb).  The Point Light 
source is also going to support "attenuation", which is the 
natural effect where the intensity of a light falls off over 
distance due to the spreading of the light rays.
'''
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
    LIGHT_SIZE = 5
    def OnInit( self ):
        """Initialize the context"""
        '''Our common light-model declarations are getting slightly 
        more involved.  We're adding a single field to the light 
        "structure", the attenuation field.  This is a 4-item vector 
        where the first item is a constant attenuation factor, the 
        second is a linear attenuation factor, and the third a quadratic 
        attenuation factor.  The fourth item is ignored, but we are 
        using an array of vec4s for the light parameters, so it is 
        easiest to just ignore the w value.
        '''
        lightConst = """
        const int LIGHT_COUNT = %s;
        const int LIGHT_SIZE = %s;
        
        const int AMBIENT = 0;
        const int DIFFUSE = 1;
        const int SPECULAR = 2;
        const int POSITION = 3;
        const int ATTENUATION = 4;
        
        uniform vec4 lights[ LIGHT_COUNT*LIGHT_SIZE ];
        varying vec3 EC_Light_half[LIGHT_COUNT];
        varying vec3 EC_Light_location[LIGHT_COUNT]; 
        varying float Light_distance[LIGHT_COUNT]; 
        
        varying vec3 baseNormal;
        """%( self.LIGHT_COUNT, self.LIGHT_SIZE )
        '''==Lighting Attenuation=
        
        For the first time in many tutorials we're altering out 
        lighting calculation.  We're adding 2 inputs to the function,
        the first is the distance from the fragment to the light,
        the second is the attenuation vector for the in-process light.
        We are also going to return one extra value, the ambient-light 
        multiplier for this light.  For our directional lights this 
        was always 1.0, but now our light's ambient contribution can 
        be controlled by attenuation.
        
        The core calculation for attenuation looks like this:
        '''
        """attenuation = clamp(
            0.0,
            1.0,
            1.0 / (
                attenuations.x + 
                (attenuations.y * distance) +
                (attenuations.z * distance * distance)
            )
        );"""
        '''The default attenuation for legacy OpenGL was
        (1.0, 0.0, 0.0), which is to say, no attenuation at all.
        The attenuation values are not particularly "human friendly",
        but they give you some control over the distance at which 
        lights cause effects.  Keep in mind when using attenuation
        coefficients that smaller values mean the light goes farther,
        so a coefficient of .5 is "brighter" than a coefficient of 1.0.
        '''
        phong_weightCalc = """
        vec3 phong_weightCalc( 
            in vec3 light_pos, // light position/direction
            in vec3 half_light, // half-way vector between light and view
            in vec3 frag_normal, // geometry normal
            in float shininess, // shininess exponent
            in float distance, // distance for attenuation calculation...
            in vec4 attenuations // attenuation parameters...
        ) {
            // returns vec3( ambientMult, diffuseMult, specularMult )
            float n_dot_pos = max( 0.0, dot( 
                frag_normal, light_pos
            ));
            float n_dot_half = 0.0;
            float attenuation = 1.0;
            if (n_dot_pos > -.05) {
                n_dot_half = pow(
                    max(0.0,dot( 
                        half_light, frag_normal
                    )), 
                    shininess
                );
                if (distance != 0.0) {
                    attenuation = clamp(
                        0.0,
                        1.0,
                        1.0 / (
                            attenuations.x + 
                            (attenuations.y * distance) +
                            (attenuations.z * distance * distance)
                        )
                    );
                    n_dot_pos *= attenuation;
                    n_dot_half *= attenuation;
                }
            }
            return vec3( attenuation, n_dot_pos, n_dot_half);
        }
        """
        '''==Calculating Distance and Direction==
        
        Our new lights are "point sources", that is, they have a 
        model-space location which is not at "infinite distance".
        Because of this, unlike "directional lights", we have to 
        recalculate the light position/location/direction vector 
        for each fragment.  We also need to know the distance of 
        the light from each fragment.
        
        While we could perform those calculations in the fragment 
        shader, the vectors and distances we need vary smoothly 
        across the triangles involved, so we'll calculate them at 
        each vertex and allow the hardware to interpolate them.
        We'll have to normalize the interpolated values, but this 
        is less processor intensive than doing the calculations 
        for each fragment.
        
        We are doing our vector calculations for the light location
        and distance in model-space.  You could do them in view-space 
        as well.
        
        Our vertex calculations are getting complex enough that we're 
        going to split them into a separate function for readability and 
        (eventual) reusability.  We'll create a function which encodes the 
        algorithmic operation (phong_preCalc) and another which takes our 
        particular attributes/uniforms and accumulates the results from 
        that function.
        
        We're defining phong_preCalc inline here, but we'll also store it 
        as a resource we can use from anywhere:
        
            from OpenGLContext.resources.phongprecalc_vert import data as phong_preCalc
        '''
        phong_preCalc = """
        // Vertex-shader pre-calculation for lighting...
        void phong_preCalc( 
            in vec3 vertex_position,
            in vec4 light_position,
            out float light_distance,
            out vec3 ec_light_location,
            out vec3 ec_light_half
        ) {
            // This is the core setup for a phong lighting pass 
            // as a reusable fragment of code.
            
            // vertex_position -- un-transformed vertex position (world-space)
            // light_position -- un-transformed light location (direction)
            // light_distance -- output giving world-space distance-to-light 
            // ec_light_location -- output giving location of light in eye coords 
            // ec_light_half -- output giving the half-vector optimization
            
            if (light_position.w == 0.0) {
                // directional rather than positional light...
                ec_light_location = normalize(
                    gl_NormalMatrix *
                    light_position.xyz
                );
                light_distance = 0.0;
            } else {
                // positional light, we calculate distance in 
                // model-view space here, so we take a partial 
                // solution...
                vec3 ms_vec = (
                    light_position.xyz -
                    vertex_position
                );
                vec3 light_direction = gl_NormalMatrix * ms_vec;
                ec_light_location = normalize( light_direction );
                light_distance = abs(length( ms_vec ));
            }
            // half-vector calculation 
            ec_light_half = normalize(
                ec_light_location + vec3( 0,0,1 )
            );
        }"""
        '''This function is not as generally reusable, so we'll store it 
        to a separate file named '_shader_tut_lightprecalc.vert'.'''
        light_preCalc = """
        void light_preCalc( in vec3 vertex_position ) {
            // This function is dependent on the uniforms and 
            // varying values we've been using, it basically 
            // just iterates over the phong_lightCalc passing in 
            // the appropriate pointers...
            vec3 light_direction;
            for (int i = 0; i< LIGHT_COUNT; i++ ) {
                int j = i * LIGHT_SIZE;
                phong_preCalc(
                    vertex_position,
                    lights[j+POSITION],
                    // following are the values to fill in...
                    Light_distance[i],
                    EC_Light_location[i],
                    EC_Light_half[i]
                );
            }
        }
        """
        vertex = shaders.compileShader( 
            lightConst + phong_preCalc + light_preCalc +
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
        '''Our fragment shader is only slightly modified to use our 
        new phong_weightCalc function.  We need a larger "weights" variable and 
        need to pass in more information.  We also need to multiply 
        the per-light ambient value by the new weight we've added.
        
        You will also notice that since we are using the 'i' variable 
        to directly index the varying arrays, we've introduced a 'j' 
        variable that tracks the offset into the light array which 
        begins the current light.
        '''
        fragment = shaders.compileShader( 
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
                    baseNormal,
                    material.shininess,
                    // some implementations will produce negative values interpolating positive float-arrays!
                    // so we have to do an extra abs call for distance
                    abs(Light_distance[i]),
                    lights[j+ATTENUATION]
                );
                fragColor = (
                    fragColor 
                    + (lights[j+AMBIENT] * material.ambient * weights.x)
                    + (lights[j+DIFFUSE] * material.diffuse * weights.y)
                    + (lights[j+SPECULAR] * material.specular * weights.z)
                );
            }
            //fragColor = vec4(Light_distance[0],Light_distance[1],Light_distance[2],1.0);
            gl_FragColor = fragColor;
        }
        """, GL_FRAGMENT_SHADER)
        '''Our general uniform setup should look familiar by now.'''
        self.shader = shaders.compileProgram(vertex,fragment)
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
        ('material.diffuse',(.5,.5,.5,1.0)),
        ('material.specular',(.8,.8,.8,1.0)),
        ('material.shininess',(2.0,)),
    ]
    '''We've created 3 equal-distance lights here, in red, green and 
    blue.  The green light uses linear attenuation, the red quadratic
    and the blue constant.
    '''
    LIGHTS = array([
        x[1] for x in [
            ('lights[0].ambient',(.05,.05,.05,1.0)),
            ('lights[0].diffuse',(.1,.8,.1,1.0)),
            ('lights[0].specular',(0.0,1.0,0.0,1.0)),
            ('lights[0].position',(2.5,2.5,2.5,1.0)),
            ('lights[0].attenuation',(0.0,.15,0.0,1.0)),
            
            ('lights[1].ambient',(.05,.05,.05,1.0)),
            ('lights[1].diffuse',(.8,.1,.1,1.0)),
            ('lights[1].specular',(1.0,0.0,0.0,1.0)),
            ('lights[1].position',(-2.5,2.5,2.5,1.0)),
            ('lights[1].attenuation',(0.0,0.0,.15,1.0)),
            
            ('lights[2].ambient',(.05,.05,.05,1.0)),
            ('lights[2].diffuse',(.1,.1,.8,1.0)),
            ('lights[2].specular',(0.0,0.0,1.0,1.0)),
            ('lights[2].position',(0.0,-3.06,3.06,1.0)),
            ('lights[2].attenuation',(.15,0.0,0.0,1.0)),
        ]
    ], 'f')
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        if not mode.visible:
            return
        glUseProgram(self.shader)
        try:
            self.coords.bind()
            self.indices.bind()
            stride = self.coords.data[0].nbytes
            try:
                '''Again, we're using the parameterized light size/count 
                to pass in the array.'''
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

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''There is only one light-type missing from the legacy OpenGL 
lighting model, that's the topic of our next tutorial.'''
