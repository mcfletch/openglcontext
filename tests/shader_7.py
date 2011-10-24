#! /usr/bin/env python
'''=Multiple Lights, GLSL Arrays and Structures=

[shader_7.py-screen-0001.png Screenshot]

This tutorial builds on earlier tutorials by adding:

    * Multiple Lights
    * GLSL Structures (for defining a Material)
    * GLSL Arrays/Looping (for processing multiple lights)

Until now, our tutorials have had a single light.  This tutorial
is going to demonstrate how to use simple looping in GLSL to
iterate over a set of lights applying our existing rendering
algorithm to each defined light.

We're also going to quickly demonstrate the use of GLSL structures
to bind together similar information into namespaces for easier
reference.
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
    def OnInit( self ):
        """Initialize the context"""
        '''==GLSL Structures==

        We have previously been using values named Material_ambient,
        Material_diffuse, etceteras to specify our Material's properties.
        GLSL allows us to bind these kinds of values together into a
        structure.  The structure doesn't provide many benefits other
        than keeping the namespaces of your code clean and allowing for
        declaring multiple uniforms of the same type, such as a "front"
        and "back" material.

        We are going to define a very simple Material struct which is
        a subset of the built-in gl_MaterialParameters structure
        (which also has an "emission" parameter).  GLSL defines two
        built-in Material uniforms gl_FrontMaterial and gl_BackMaterial.
        It is possible (though seldom done) to fill in these uniform
        values with glUniform calls rather than the legacy glMaterial
        calls.
        '''
        materialStruct = """
        struct Material {
            vec4 ambient;
            vec4 diffuse;
            vec4 specular;
            float shininess;
        };
        """
        '''Note that each sub-element must be terminated with a semi-colon
        ';' character, and that qualifiers (in, out, uniform, etceteras)
        are not allowed within the structure definition.  This statement
        has to occur *before* any use of the structure to declare a
        variable as being of this type.

        Our light-weighting code has not changed from the previous
        tutorial.  It is still a Blinn-Phong calculation based on the
        half-vector of light and view vector.
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
        '''Our vertex shader is also unchanged.  We could move many
        of the operations currently done in our fragment shader here
        to reduce the processing load for our shader.
        '''
        vertex = shaders.compileShader(
        """
        attribute vec3 Vertex_position;
        attribute vec3 Vertex_normal;

        varying vec3 baseNormal;
        void main() {
            gl_Position = gl_ModelViewProjectionMatrix * vec4(
                Vertex_position, 1.0
            );
            baseNormal = gl_NormalMatrix * normalize(Vertex_normal);
        }""", GL_VERTEX_SHADER)
        '''To create a uniform with a structure type, we simply use
        the structure as the data-type declaration for the uniform.
        As opposed to using e.g. vec4 or vec3, we use Material (our
        structure name defined above) and give the uniform a name.
        '''
        """uniform Material material;"""
        '''==GLSL Arrays==

        Each light we have defined (so far) is composed to 4 4-component
        vectors, ambient, diffuse and specular colour, along with the
        "position" (direction) vector.  If we wanted to provide, for
        instance, 3 lights of this type, we *could* create 12 different
        uniform values, and set each of these uniforms individually.

        GLSL, however, provides for array data-types.  The array types
        must be "sized" (have a specific, final size) in order to be
        usable, so no "pointer" types are available, but we don't need
        them for this type of operation.  We can define a "lights"
        uniform which is declared as a sized array of 12 vec4 elements:'''
        """uniform vec4 lights[ 12 ];"""
        '''And we can loop over "lights" using 0-indexed [i] indices,
        where i must be an integer.  The for loop will be familiar to
        those who have used C looping:'''
        """for (i=0;i<12;i=i+4) { blah; }"""
        '''Note that you must declare the iterator variable ("i" here)

        We iterate over each light in our array of lights accumulating
        the results into the fragColor variable we've defined.  The
        global component is used to initialize the variable, with the
        contribution of each light added to the result.
        '''
        fragment = shaders.compileShader(
            phong_weightCalc + materialStruct + """
        uniform Material material;
        uniform vec4 Global_ambient;
        uniform vec4 lights[ 12 ]; // 3 possible lights 4 vec4's each

        varying vec3 baseNormal;
        void main() {
            vec4 fragColor = Global_ambient * material.ambient;

            int AMBIENT = 0;
            int DIFFUSE = 1;
            int SPECULAR = 2;
            int POSITION = 3;

            int i;
            for (i=0;i<12;i=i+4) {
                // normalized eye-coordinate Light location
                vec3 EC_Light_location = normalize(
                    gl_NormalMatrix * lights[i+POSITION].xyz
                );
                // half-vector calculation
                vec3 Light_half = normalize(
                    EC_Light_location - vec3( 0,0,-1 )
                );
                vec2 weights = phong_weightCalc(
                    EC_Light_location,
                    Light_half,
                    baseNormal,
                    material.shininess
                );
                fragColor = (
                    fragColor
                    + (lights[i+AMBIENT] * material.ambient)
                    + (lights[i+DIFFUSE] * material.diffuse * weights.x)
                    + (lights[i+SPECULAR] * material.specular * weights.y)
                );
            }
            gl_FragColor = fragColor;
        }
        """, GL_FRAGMENT_SHADER)
        '''===Why not an Array of Structures?===

        Originally this tutorial was going to use an array of LightSource
        structures as a Uniform, with the components of the structures
        specified with separate calls to glUniform4f.  Problem is, that
        doesn't actually *work*.  While glUniform *should* be able to
        handle array-of-structure indexing, it doesn't actually support
        this type of operation in the real world. The built-in
        gl_LightSourceParameters are an array-of-structures, but
        apparently the GL implementations consider this a special case,
        rather than a generic type of functionality to be supported.

        An array-of-structures value looks like this when declared in GLSL:
        '''
        lightStruct = """
        // NOTE: this does not work, it compiles, but you will
        // not be able to fill in the individual members...
        struct LightSource {
            vec4 ambient;
            vec4 diffuse;
            vec4 specular;
            vec4 position;
        };
        uniform LightSource lights[3];
        """
        '''When you attempt to retrieve the location for the Uniform
        via:

            glGetUniformLocation( shader, 'lights[0].ambient' )

        you will always get a -1 (invalid) location.

        OpenGL 3.1 introduced the concept of Uniform Buffers, which allow
        for packing Uniform data into VBO storage, but it's not yet clear
        whether they will support array-of-structure specification.
        '''
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
        '''There's no real reason to treat the "lights" uniform specially,
        other than that we want to call attention to it.  We get the
        uniform as normal.  Note that we *could* also retrieve a
        sub-element of the array by specifying 'lights[3]' or the like.
        '''
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
    '''Our individually-specified uniform values'''
    UNIFORM_VALUES = [
        ('Global_ambient',(.05,.05,.05,1.0)),
        ('material.ambient',(.2,.2,.2,1.0)),
        ('material.diffuse',(.5,.5,.5,1.0)),
        ('material.specular',(.8,.8,.8,1.0)),
        ('material.shininess',(.995,)),
    ]
    '''The parameters we use to specify our lights, note that
    the first item in the tuples is dropped, it is the value
    that *should* work in glGetUniformLocation, but does not.
    What actually gets passed in is a single float array with
    12 4-float values representing all of the data-values for
    all of the enabled lights.

    You'll notice that we're using 0.0 as the 'w' coordinate
    for the light positions.  We're using this to flag that the
    position is actually a *direction*.  This will become useful
    in later tutorials where we have multiple light-types.
    '''
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
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glUseProgram(self.shader)
        try:
            self.coords.bind()
            self.indices.bind()
            stride = self.coords.data[0].nbytes
            try:
                '''Here's our only change to the rendering process,
                we pass in the entire array of light-related data with
                a single call to glUniform4fv.  The 'v' forms of
                glUniform all allow for passing arrays of values,
                and all require that you specify the number of elements
                being passed (here 12).

                Aside: Incidentally, Uniforms are actually stored with
                the shader until the shader is re-linked, so specifying
                the uniforms on each rendering pass (as we do here) is
                not necessary.  The shader merely needs to be "in use"
                during the glUniform call, and this is a convenient,
                if inefficient, way to ensure it is in use at the time
                we are calling glUniform.
                '''
                glUniform4fv(
                    self.uniform_locations['lights'],
                    12,
                    self.LIGHTS
                )
                test_lights = (GLfloat * 12)()
                glGetUniformfv( self.shader, self.uniform_locations['lights'], test_lights )
                print 'Lights', list(test_lights)
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
'''Our next tutorial will optimize the directional light code here
so that it is less wasteful of GPU resources.'''
