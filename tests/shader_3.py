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
        '''Much like the "varying" values which can be used to 
        pass values between vertex and fragment shaders, "uniform"
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
        
        We replace our "first principles" approach to calculating the 
        vertex position with the optimized built-in function ftransform()
        which has certain performance and repeatability guarantees that 
        the matrix multiplication doesn't necessarily provide.  As with 
        the raw operation, once we have performed the ftransform(),
        gl_Position is the eye-space coordinate of this particular
        vertex.  
        
        The "z" coordinate of the vertex in eye-space represents the
        "depth into the screen".  We perform a few basic math operations
        on the distance value, including one which uses our end_fog
        distance.  We then use the resulting floating-point value to
        control a "mix" of the uniform fog_color and the current vertex'
        gl_Color value.
        '''
        vertex = shaders.compileShader("""
            uniform float end_fog;
            uniform vec4 fog_color;
            void main() {
                float fog; // amount of fog to apply
                float fog_coord; // distance for fog calculation...
                // This function is generally faster and is guaranteed
                // to produce the same result on each run...
                // gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
                gl_Position = ftransform();
                
                fog_coord = abs(gl_Position.z);
                fog_coord = clamp( fog_coord, 0.0, end_fog);
                fog = (end_fog - fog_coord)/end_fog;
                fog = clamp( fog, 0.0, 1.0);
                gl_FrontColor = mix(fog_color, gl_Color, fog);
            }""",GL_VERTEX_SHADER)
        '''Instead of defining a custom varying value to communicate the 
        vertex colours, we have used the built-in (legacy) varying value 
        "gl_FrontColor" in the vertex shader.  The value of gl_FrontColor
        appears (with interpolation) in the similarly built-in (legacy)
        value gl_Color within our fragment shader.
        
        Because we altered the colour of each vertex in the vertex
        shader, the fog is already "baked into" the interpolated colours
        we receive.  We could, instead, have done the distance calculation 
        in the fragment shader, potentially using, for instance, a texture
        lookup to provide more realistic "wisps" of fog, but the fragment 
        shader is called far more than the vertex shader (normally), which 
        means it is normally a good idea of do as much of your calculation 
        as possible in the vertex shader.
        '''
        fragment = shaders.compileShader("""void main() {
                gl_FragColor = gl_Color;
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
            'end_fog': glGetUniformLocation( self.shader, 'end_fog' ),
            'fog_color': glGetUniformLocation( self.shader, 'fog_color' ),
        }
    def Render( self, mode = 0):
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
        '''To make the fog effect more interesting, we'll use some 
        legacy functions to change the model-view matrix so that the 
        geometry appears much bigger and rotated 45 degrees.'''
        glRotate( 45, 0,1,0 )
        glScale( 3,3,3 )
        '''As has become familiar, we enable the VBO, set up our 
        vertex and colour pointers and call our drawing function.'''
        try:
            self.vbo.bind()
            try:
                glEnableClientState(GL_VERTEX_ARRAY);
                glEnableClientState(GL_COLOR_ARRAY);
                glVertexPointer(3, GL_FLOAT, 24, self.vbo )
                glColorPointer(3, GL_FLOAT, 24, self.vbo+12 )
                glDrawArrays(GL_TRIANGLES, 0, 9)
            finally:
                self.vbo.unbind()
                glDisableClientState(GL_VERTEX_ARRAY);
                glDisableClientState(GL_COLOR_ARRAY);
        finally:
            glUseProgram( 0 )
        
if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''You may wish to use the keyboard "arrow" keys to walk around in the 
"foggy" world and see the effect update as your move closer to or further away from the geometry.'''
