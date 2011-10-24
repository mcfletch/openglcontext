#! /usr/bin/env python
'''=Spot-Lights=

[shader_10.py-screen-0001.png Screenshot]

This tutorial builds on earlier tutorials by adding:

    * Directional shielded Point Lights (Spot Lights)
    
Spot Lights are a commonly seen pattern. They are basically 
Point Light sources which have shields/reflectors which block 
light in most directions, while focussing the light (to some 
degree) in a particular direction.
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
    '''Note that we're going to add 2 new vec4 fields to our light,
    the legacy GL has 2 floats and a direction vector, but we're 
    combining all the values into a uniform vector set.'''
    LIGHT_SIZE = 7
    def OnInit( self ):
        """Initialize the context"""
        '''As you can see, we've created a new 4-element vector 
        called SPOT_PARAMS which holds 3 "meaningful" float values.
        The first element cos_spot_cutoff represents the cosign of 
        the angle beyond which the light is cut off. This angle is 
        measured from the light's spot_direction compared with the 
        light_location vector.  In effect, it is a check to see if 
        the fragment is within the cone of the light.  The use of the 
        *cosine* of the angle is to allow for very fast checks against 
        the dot-product of the normalized vectors.
        
        The second element, spot_exponent, is used to calculate the 
        amount of "spotiness" of the spotlight, that is, the amount 
        to which the spotlight focusses light on the center of the 
        beam versus the outside of the beam.  A higher spot_exponent
        will cause the spotlight to "focus" more, a lower exponent 
        will cause the spotlight to act more like a "shielded" 
        point-light (such as a lamp with blockers rather than reflectors).
        
        The last component of the SPOT_PARAMS is being used as a simple 
        flag to tell us whether to apply the spot calculation.  We could 
        have shaved a whole vec4 by packing the spot_exponent into the 
        ATTENUATION vector's unused .w component, and then packing the 
        spot_cutoff into the spot_direction's unused .w, but that becomes 
        a bit awkward looking.
        '''
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
        '''Our phong_weightCalc function receives its final tweaks here.  We 
        provide the two vec4 spot elements for the current light.
        The spotlight operation modifies the point-light code such that 
        the "attenuation" numerator is either 1.0 (for non-directional 
        point-lights) or a calculated value for spot-lights.
        
        To calculate this value, we take the (cos of the) angle between 
        the light direction (spot_direction) and the vector between 
        the fragment and the light location (-light_pos).  If this value 
        is lower than our spot_cutoff, then we do not want to provide 
        any lighting whatsoever from this light, so we short-circuit and 
        return a null vector of weights. 
        
        If the value is higher than the cutoff, we calculate the
        "spotiness" multiplier.  Here we are *not* using the OpenGL 
        standard method, instead we calculate the fraction of total 
        cosine-space which is displayed and raise it to the power of our 
        spot_exponent value.
        
        This is our last tweak to the blinn-phong lighting model so we'll make 
        this version of the function available like so:
        
        from OpenGLContext.resources.phongweights_frag import data as phong_weightCalc
        '''
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
        '''Nothing needs to change in our vertex shader, save that we're 
        using the functions we stored to external files in the previous 
        tutorial.'''
        from OpenGLContext.resources.phongprecalc_vert import data as phong_preCalc
        light_preCalc = open( '_shader_tut_lightprecalc.vert' ).read()
        
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
            light_preCalc( Vertex_position );
        }""", GL_VERTEX_SHADER)
        
        '''Our only change for the fragment shader is to pass in the 
        spot components of the current light when calling phong_weightCalc.'''
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
        '''Our uniform/geometry handling code is unchanged.'''
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
    '''We'll dial down the shininess on our material a little so that 
    it's easier to see the spotlight cones on the sphere.'''
    UNIFORM_VALUES = [
        ('Global_ambient',(.05,.05,.05,1.0)),
        ('material.ambient',(.8,.8,.8,1.0)),
        ('material.diffuse',(.8,.8,.8,1.0)),
        ('material.specular',(.8,.8,.8,1.0)),
        ('material.shininess',(.8,)),
    ]
    '''Our lights array now has more fields per light.  The spotlight 
    vectors always have to be present, even if we are not using them 
    for a particular light.  We're going to define 3 lights here with 
    fairly high "spotiness" values so that we can see the focussed 
    beam effect on the sphere.  The spot exponents in this case tend to 
    cause an area in the center of the beam to saturate completely.
    '''
    LIGHTS = array([
    
        x[1] for x in [
            ('lights[0].ambient',(.05,.05,.05,1.0)),
            ('lights[0].diffuse',(.1,.8,.1,1.0)),
            ('lights[0].specular',(0.0,.05,0.0,1.0)),
            ('lights[0].position',(2.5,3.5,2.5,1.0)),
            ('lights[0].attenuation',(0.0,1.0,1.0,1.0)),
            ('lights[0].spot_params',(cos(.25),1.0,0.0,1.0)),
            ('lights[0].spot_dir',(-8,-20,-8.0,1.0)),
            
            ('lights[1].ambient',(.05,.05,.05,1.0)),
            ('lights[1].diffuse',(.8,.1,.1,1.0)),
            ('lights[1].specular',(.25,0.0,0.0,1.0)),
            ('lights[1].position',(-2.5,2.5,2.5,1.0)),
            ('lights[1].attenuation',(0.0,0.0,.125,1.0)),
            ('lights[1].spot_params',(cos(.25),1.25,0.0,1.0)),
            ('lights[1].spot_dir',(2.5,-5.5,-2.5,1.0)),
            
            ('lights[2].ambient',(.05,.05,.05,1.0)),
            ('lights[2].diffuse',(.1,.1,1.0,1.0)),
            ('lights[2].specular',(0.0,.25,.25,1.0)),
            ('lights[2].position',(0.0,-3.06,3.06,1.0)),
            ('lights[2].attenuation',(2.0,0.0,0.0,1.0)),
            ('lights[2].spot_params',(cos(.15),.75,0.0,1.0)),
            ('lights[2].spot_dir',(0.0,3.06,-3.06,1.0)),
        ]
    ], 'f')
    '''Nothing else needs to change from the previous tutorial.'''
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
'''We've now built a fairly complete per-pixel Phong renderer.  As an 
exercise, you may wish to modify the spotlight equations above to match 
the legacy OpenGL mechanism.

Further reading:

    The [http://www.lighthouse3d.com/opengl/glsl/index.php?lights Lighthouse GLSL Lighting Tutorial] uses legacy entry points for 
    geometry and tries to precisely reproduce the legacy pipeline.
    The OpenGL Shading Language (Orange Book) Chapter 9 -- Emulating OpenGL Fixed Functionality
'''
