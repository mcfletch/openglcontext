#! /usr/bin/env python
'''=Varying Values (Colours)=

[shader_2.py-screen-0001.png Screenshot]

This tutorial builds on the previous tutorial by:

    * using varying values to communicate between 
        vertex and fragment shaders 
    * catching compilation errors in your shaders 
    * packing both vertex and colour values into a single VBO 
    * enabling vertex arrays with strides
    * enabling color arrays (legacy approach)

Our imports for this tutorial look pretty much the same as 
for the last tutorial, so we can ignore them.  If you don't
recognize something, go back to the previous tutorial's 
introduction.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders

class TestContext( BaseContext ):
    """This shader just passes gl_Color from an input array to 
    the fragment shader, which interpolates the values across the 
    face (via a "varying" data type).
    """
    def OnInit( self ):
        """Initialize the context once we have a valid OpenGL environ"""
        '''==Aside: Compilation Errors==
        
        As we get more and more complex shaders, you are inevitably
        going to run into situations where your shaders have compilation 
        errors and need to be debugged.  The PyOpenGL convenience 
        wrappers for shaders will raise a RuntimeError instance when/if 
        shader compilation fails.  The second argument to the RuntimeError
        will be the source-code that was being compiled when the failure 
        occurred.  Normally the Python traceback of this error will be 
        sufficient to help you track down the problem (with the appropriate
        references, of course).'''
        try:
            shaders.compileShader( """ void main() { """, GL_VERTEX_SHADER )
        except RuntimeError, err:
            print 'Example of shader compile error', err 
        else:
            raise RuntimeError( """Didn't catch compilation error!""" )
        '''==Varying Values==
        
        In our previous tutorial, we calculated the colour of each 
        fragment as a constant colour (green).  Now we are going to 
        make each vertex a different colour and allow the GL to 
        interpolate between those colours.
        
        We are going to use the legacy OpenGL colour for our vertices,
        that is, the colour that would normally be provided to the 
        legacy (fixed-function) pipeline.  This value shows up as the 
        built-in vec4 "gl_Color".  Within the vertex shader, each call 
        of the vertex shader will have gl_Color assigned.
        
        To communicate the colour for each vertex to the fragment 
        shader, we need to define a "varying" variable.  A varying 
        variable is interpolated across the triangle for each fragment,
        taking the perspectivally correct blended value for the vertices
        which make up each corner of the triangle.  Thus if we were to 
        define one vertex as being black and another as white, the
        fragments generated for the area between them would fade from 
        black to white (via grey).
        
        You will note that we define the varying value *outside* the main 
        function.  The varying value can be loosely thought of as being 
        declared a "global" so that it can be seen in both shaders.  
        However, the varying value is is being processed by intermediate
        clipping and interpolation processes.
        '''
        vertex = shaders.compileShader(
            """
            varying vec4 vertex_color;
            void main() {
                gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
                vertex_color = gl_Color;
            }""",GL_VERTEX_SHADER)
        '''Our fragment shader, again, declares the vertex_color
        varying value.  Since we would like the final fragment 
        colour to be the interpolated colour between our vertices,
        we can simply assign vertex_color to gl_FragColor.'''
        fragment = shaders.compileShader("""
            varying vec4 vertex_color;
            void main() {
                gl_FragColor = vertex_color;
            }""",GL_FRAGMENT_SHADER)
        self.shader = shaders.compileProgram(vertex,fragment)
        '''Our geometry now has two components for every vertex,
        the first is the vertex position, which is the same set of 
        values as we saw in our previous tutorial.  The first three 
        floats in each vertex (row) are the position.   The last 
        three values represent the colours of each vertex.  Thus 
        the triangle (the first three vertices) will blend from 
        red to yellow to cyan.
        
        As noted in the previous tutorial, this "packed" format 
        tends to be more efficient on modern hardware than having 
        separate data-arrays for each type of data.
        '''
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
    
    def Render( self, mode):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        '''As before, we need to enable the use of our compiled shaders
        and make our VBO active so that array-specification routines 
        will use the VBO as the source for our geometric data.'''
        glUseProgram(self.shader)
        try:
            self.vbo.bind()
            try:
                '''Since we want to provide both position and colour 
                arrays to the shader, we need to enable two different 
                arrays.  These two built-in arrays map to the built-in
                gl_Vertex and gl_Color "attribute" variables we are
                using in our vertex shader.
                
                These "enables" tell OpenGL that for each vertex we 
                render, we would like to read one record from the 
                enabled arrays.  If we were to do this without specifying 
                the arrays, OpenGL would likely seg-fault our program
                as it tried to access NULL memory locations.
                '''
                glEnableClientState(GL_VERTEX_ARRAY);
                glEnableClientState(GL_COLOR_ARRAY);
                '''We are using the "full" form of the array-definition
                calls here, as we want to be able to specify "strides" 
                across the data-arrays.  The arguments to the pointer
                definition calls are:
                
                    * size -- number of values in each record 
                    * type -- constant defining the type of value for 
                        each item in the record 
                    * stride -- number of bytes between the start of 
                        each consecutive record, in our case we have 
                        6 32-bit floating-point values in each record,
                        for a total of 4*6 == 24 bytes between records.
                    * pointer -- reference to the data we wish to use 
                        for this array 
                
                The vertex pointer is passed a reference to our VBO,
                which tells OpenGL to read from the currently-bound VBO.
                Under the covers, the VBO wrapper is simply passing a 
                NULL pointer to the GL.
                '''
                glVertexPointer(3, GL_FLOAT, 24, self.vbo )
                '''The colour pointer also wants to read data from the 
                VBO, but it needs to begin reading each record from a 
                point which is 3 floating-point values (the width of the 
                position information) after where the position pointer 
                gets its value.
                
                Since the definition of the array includes the step
                between elements, we ask OpenGL to begin calculating the
                addresses from which to read the colour information at 
                the beginning of the current VBO + 12 bytes.  Under the 
                covers, the VBO wrapper is simply passing a void pointer 
                to the address 12 to the GL.
                '''
                glColorPointer(3, GL_FLOAT, 24, self.vbo+12 )
                '''We now trigger our drawing operation and cleanup 
                in the same way as we have seen before.'''
                glDrawArrays(GL_TRIANGLES, 0, 9)
            finally:
                self.vbo.unbind()
                glDisableClientState(GL_VERTEX_ARRAY);
                glDisableClientState(GL_COLOR_ARRAY);
        finally:
            glUseProgram( 0 )

if __name__ == "__main__":
    TestContext.ContextMainLoop()

'''
Terms:

    * interpolate -- create new data-values by blending other values 
'''
