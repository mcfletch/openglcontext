#! /usr/bin/env python
'''=Uniform Values (Fog)=

[shader_3.py-screen-0001.png Screenshot]

This tutorial builds on the previous tutorial by:

    * defining uniform values in shaders 
    * passing values to uniform values from Python
    * doing some basic calculations during the vertex 
        shader, including defining local variables
        and using some simple functions
    * creating a "depth cue" via a simple "fog" function 
        which alters the colour of each vertex according
        the the vertex' distance from the eye.

Note: the shader in this example comes (loosely) from the 
[http://www.3dshaders.com/ OpenGL Shading Language (Orange Book)]
Chapter 9.

Our imports are by now quite familiar...
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGL.GL import shaders
from OpenGLContext.arrays import *

class TestContext( BaseContext ):
    """This shader adds a simple linear fog to the shader
    
    Shows use of uniforms, and a few simple calculations 
    within the vertex shader...
    """
    def OnInit( self ):
        '''Much like the "in"/"out" values which pass a value from
        the vertex shader to the fragment shader, "uniform"
        values allow us to pass values into our shaders from 
        our code.  You can think of a uniform value as being used 
        to specify something which is "uniform" (the same) for an 
        entire rendering call.
        
        We'll define two uniforms here:
        
            * end_fog -- distance from the camera at which the 
                fog colour will completely obscure the vertex colour 
            * fog_color -- the colour of the fog that will be mixed 
                into the (vertex) colour
        
        We'll also define 2 local variables within the main function,
        these variables are simple floating-point values in this case,
        but could be any supported type.
        
        The "z" coordinate of the vertex in clip space represents the
        "depth into the screen".  We perform a few basic math operations
        on the distance value, including one which uses our end_fog
        distance.  We then use the resulting floating-point value to
        control a "mix" of the uniform fog_color and the vertex's own
        colour.
        '''
        vertex = shaders.compileShader("""#version 330 core
            uniform mat4 modelViewProjection;
            uniform float end_fog;
            uniform vec4 fog_color;
            in vec3 Vertex_position;
            in vec3 Vertex_color;
            out vec4 vertex_color;
            void main() {
                float fog; // amount of fog to apply
                float fog_coord; // distance for fog calculation...
                gl_Position = modelViewProjection * vec4(
                    Vertex_position, 1.0
                );

                fog_coord = abs(gl_Position.z);
                fog_coord = clamp( fog_coord, 0.0, end_fog);
                fog = (end_fog - fog_coord)/end_fog;
                fog = clamp( fog, 0.0, 1.0);
                vertex_color = mix(
                    fog_color, vec4( Vertex_color, 1.0 ), fog
                );
            }""",GL_VERTEX_SHADER)
        '''The vertex shader hands the fogged colour on to the
        fragment shader in vertex_color, which the fragment shader
        declares under the same name and reads interpolated.
        
        Because we altered the colour of each vertex in the vertex
        shader, the fog is already "baked into" the interpolated colours
        we receive.  We could, instead, have done the distance calculation 
        in the fragment shader, potentially using, for instance, a texture
        lookup to provide more realistic "wisps" of fog, but the fragment 
        shader is called far more than the vertex shader (normally), which 
        means it is normally a good idea of do as much of your calculation 
        as possible in the vertex shader.
        '''
        fragment = shaders.compileShader("""#version 330 core
            in vec4 vertex_color;
            out vec4 fragColor;
            void main() {
                fragColor = vertex_color;
            }""",GL_FRAGMENT_SHADER)
        
        '''We set up our shader and VBO using the same code as in 
        the previous tutorial.'''
        self.shader = shaders.compileProgram(vertex,fragment)
        self.vbo = vbo.VBO(
            array( [
                [  0, 1, 0,  0,1,0 ],
                [ -1,-1, 0,  1,1,0 ],
                [  1,-1, 0,  0,1,1 ],
                
                [  2,-1, 0,  1,0,0 ],
                [  4,-1, 0,  0,1,0 ],
                [  4, 1, 0,  0,0,1 ],
                [  2,-1, 0,  1,0,0 ],
                [  4, 1, 0,  0,0,1 ],
                [  2, 1, 0,  0,1,1 ],
            ],'f')
        )
        '''The purpose of our uniform values is to allow us to 
        pass values into our shaders from our (Python) code.  To do 
        that, we need to have a way to reference the uniform value 
        from Python.  GLSL provides these references via "locations",
        which can be queried from a compiled shader.  We will later 
        use these opaque references to assign values to the uniform 
        values.
        '''
        self.UNIFORM_LOCATIONS = {
            'modelViewProjection': glGetUniformLocation(
                self.shader, 'modelViewProjection'
            ),
            'end_fog': glGetUniformLocation( self.shader, 'end_fog' ),
            'fog_color': glGetUniformLocation( self.shader, 'fog_color' ),
        }
        '''The attribute locations and the vertex array object are set
        up as in the previous tutorial.'''
        self.Vertex_position_loc = glGetAttribLocation(
            self.shader, 'Vertex_position'
        )
        self.Vertex_color_loc = glGetAttribLocation(
            self.shader, 'Vertex_color'
        )
        self.vao = glGenVertexArrays( 1 )
    def Render( self, mode ):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glUseProgram(self.shader)
        '''The glUniform* family of functions allows us to pass values 
        into uniforms by providing the location in which to store the 
        value and the values to store.  There are both vector and
        individual-value forms of glUniform to allow you to use the 
        data-format in which your data is already stored whenever 
        possible.
        
        Here we're specifying that the fog will reach full effect within 
        15 units.  OpenGLContext's default camera is 10 units from the 
        origin.  We also specify that the fog will be white, so that the 
        geometry will fade into the white background.  Our shaders will 
        *not* be called for any fragments where there was no geometry 
        present, so if we were to choose black here, our geometry would 
        appear as largely-black objects on a white plane, instead of 
        appearing to fade into a fog.
        '''
        glUniform1f( self.UNIFORM_LOCATIONS['end_fog'],15)
        glUniform4f(self.UNIFORM_LOCATIONS['fog_color'],1,1,1,1)
        '''To make the fog effect more interesting, we place the
        geometry with a model matrix of our own, so that it appears
        three times bigger and rotated 45 degrees about the vertical.

        A rotation matrix's columns are where the axes end up, and a
        scale is the diagonal, so both are short enough to write out.
        The vertices are row vectors here -- a vertex is multiplied on
        the left -- so the model transform comes first and the camera
        the pass gave us follows it.'''
        angle = pi/4.0
        rotation = array([
            [ cos(angle), 0,-sin(angle), 0],
            [ 0,          1, 0,          0],
            [ sin(angle), 0, cos(angle), 0],
            [ 0,          0, 0,          1],
        ],'f')
        scale = array([
            [3,0,0,0],
            [0,3,0,0],
            [0,0,3,0],
            [0,0,0,1],
        ],'f')
        glUniformMatrix4fv(
            self.UNIFORM_LOCATIONS['modelViewProjection'], 1, GL_FALSE,
            dot( dot( dot( scale, rotation ), mode.matrix ), mode.projection ),
        )
        '''As has become familiar, we enable the VBO, set up our 
        vertex and colour pointers and call our drawing function.'''
        glBindVertexArray( self.vao )
        try:
            self.vbo.bind()
            try:
                glEnableVertexAttribArray( self.Vertex_position_loc )
                glEnableVertexAttribArray( self.Vertex_color_loc )
                glVertexAttribPointer(
                    self.Vertex_position_loc, 3, GL_FLOAT, GL_FALSE, 24,
                    self.vbo
                )
                glVertexAttribPointer(
                    self.Vertex_color_loc, 3, GL_FLOAT, GL_FALSE, 24,
                    self.vbo+12
                )
                glDrawArrays(GL_TRIANGLES, 0, 9)
            finally:
                self.vbo.unbind()
                glDisableVertexAttribArray( self.Vertex_position_loc )
                glDisableVertexAttribArray( self.Vertex_color_loc )
        finally:
            glBindVertexArray( 0 )
            glUseProgram( 0 )
        
if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''You may wish to use the keyboard "arrow" keys to walk around in the 
"foggy" world and see the effect update as your move closer to or further away from the geometry.'''
