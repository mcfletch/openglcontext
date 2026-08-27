#! /usr/bin/env python
'''=Attribute Values (Tweening)=

[shader_4.py-screen-0001.png Screenshot]
[shader_4.py-screen-0002.png Screenshot]

This tutorial builds on the previous tutorial by:

    * defining attribute values in shaders 
    * defining arrays to feed attribute values
    * eliminating most of our remaining legacy code 
    * defining a simple "tween" geometry animation

As we have mentioned a number of times previous, the use 
of glVertexPointer and glColorPointer is part of the "legacy"
OpenGL API.  When using shader-based geometry there is no 
need to restrict oneself to a single position, colour or 
texture for a given vertex.

Just as we have defined arbitrary Uniform values to feed into 
our shaders, we can also define arbitrary "Vertex Attribute"
values which can be fed data from our VBO just as with the 
glVertexPointer/glColorPointer mechanism.

For this tutorial, we're going to define two different "positions"
for each vertex.  The final vertex position will be determined 
by "mixing" the two positions according to a fractional uniform 
value we will pass into our shader.  This kind of "tweening" 
can be used to animate continuous mesh models smoothly.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders
'''This is our only new import, it's a utility Timer object 
from OpenGLContext which will generate events with "fraction()"
values that can be used for animations.'''
from OpenGLContext.events.timer import Timer

class TestContext( BaseContext ):
    """Demonstrates use of attribute types in GLSL
    """
    def OnInit( self ):
        """Initialize the context"""
        '''We've defined a uniform "tween" which represents the current
        fractional mix between the two positions.

        Each per-vertex value the shader reads is declared as an "in"
        variable, and each value that is the same for the whole draw as
        a "uniform".  This tutorial has three of the first -- two
        positions and a colour -- and two of the second, the tween
        fraction and the camera matrix.
        '''
        vertex = shaders.compileShader("""#version 330 core
            uniform mat4 modelViewProjection;
            uniform float tween;
            in vec3 position;
            in vec3 tweened;
            in vec3 color;
            out vec4 baseColor;
            void main() {
                gl_Position = modelViewProjection * mix(
                    vec4( position,1.0),
                    vec4( tweened,1.0),
                    tween
                );
                baseColor = vec4(color,1.0);
            }""",GL_VERTEX_SHADER)
        fragment = shaders.compileShader("""#version 330 core
            in vec4 baseColor;
            out vec4 fragColor;
            void main() {
                fragColor = baseColor;
            }""",GL_FRAGMENT_SHADER)
        self.shader = shaders.compileProgram(vertex,fragment)
        '''Since our VBO now has two position records and one colour 
        record, we have an extra 3 floats for each vertex record.'''
        self.vbo = vbo.VBO(
            array( [
                [  0, 1, 0, 1,3,0,  0,1,0 ],
                [ -1,-1, 0, -1,-1,0,  1,1,0 ],
                [  1,-1, 0, 1,-1,0, 0,1,1 ],
                
                [  2,-1, 0, 2,-1,0, 1,0,0 ],
                [  4,-1, 0, 4,-1,0, 0,1,0 ],
                [  4, 1, 0, 4,9,0, 0,0,1 ],
                [  2,-1, 0, 2,-1,0, 1,0,0 ],
                [  4, 1, 0, 1,3,0, 0,0,1 ],
                [  2, 1, 0, 1,-1,0, 0,1,1 ],
            ],'f')
        )
        '''As with uniforms, we must use opaque "location" values 
        to refer to our attributes when calling into the GL.'''
        self.position_location = glGetAttribLocation( 
            self.shader, 'position' 
        )
        self.tweened_location = glGetAttribLocation(
            self.shader, 'tweened',
        )
        self.color_location = glGetAttribLocation( 
            self.shader, 'color' 
        )
        self.tween_location = glGetUniformLocation(
            self.shader, 'tween',
        )
        self.modelViewProjection_location = glGetUniformLocation(
            self.shader, 'modelViewProjection',
        )
        '''And the vertex array object into which the three attribute
        descriptions will be recorded.'''
        self.vao = glGenVertexArrays( 1 )
        '''The OpenGLContext timer class is setup here to provide 
        a 0.0 -> 1.0 animation event and pass it to the given function.'''
        self.time = Timer( duration = 2.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
    
    def Render( self, mode ):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glUseProgram(self.shader)
        '''We pass in the current (for this frame) value of our 
        animation fraction.  The timer will generate events to update
        this value during idle time.'''
        glUniform1f( self.tween_location, self.tween_fraction )
        glUniformMatrix4fv(
            self.modelViewProjection_location, 1, GL_FALSE,
            dot( mode.matrix, mode.projection ),
        )
        glBindVertexArray( self.vao )
        try:
            '''Each attribute array binds to the VBO which is current
            when its pointer is specified.  Because we are only using
            one VBO, we can bind once.  If our position arrays were
            stored in different VBOs, we would need to bind each one
            before the glVertexAttribPointer call that reads from it.
            '''
            self.vbo.bind()
            try:
                '''We have to explicitly enable the retrieval of
                values; without this, an attribute holds one fixed value
                for every vertex rather than being read from an array.
                '''
                glEnableVertexAttribArray( self.position_location )
                glEnableVertexAttribArray( self.tweened_location )
                glEnableVertexAttribArray( self.color_location )
                '''Our vertex array is now 36 bytes/record, and each
                glVertexAttribPointer call says which attribute location
                the data-array feeds, and where in the record to start
                reading it.
                '''
                stride = 9*4
                glVertexAttribPointer( 
                    self.position_location, 
                    3, GL_FLOAT,False, stride, self.vbo 
                )
                glVertexAttribPointer( 
                    self.tweened_location, 
                    3, GL_FLOAT,False, stride, self.vbo+12
                )
                glVertexAttribPointer( 
                    self.color_location, 
                    3, GL_FLOAT,False, stride, self.vbo+24
                )
                glDrawArrays(GL_TRIANGLES, 0, 9)
            finally:
                self.vbo.unbind()
                '''We clean up our array enabling so that any later
                calls will not read records from these arrays
                (potentially beyond the end of the arrays).'''
                glDisableVertexAttribArray( self.position_location )
                glDisableVertexAttribArray( self.tweened_location )
                glDisableVertexAttribArray( self.color_location )
        finally:
            glBindVertexArray( 0 )
            glUseProgram( 0 )
    '''Our trivial event-handler function simply stores the event's 
    fraction as our tween_fraction value.'''
    tween_fraction = 0.0
    def OnTimerFraction( self, event ):
        frac = event.fraction()
        if frac > .5:
            frac = 1.0-frac 
        frac *= 2
        self.tween_fraction =frac
        self.triggerRedraw()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''On-GPU tweening would be likely to use an extremely large array 
with a character's key-frame poses stored in sequence (as opposed to
being packed into huge vertex records).  The animation code would choose
the two key-frames and enable the data-pointers for those key-frames. 
The code *could* just as store every frame of every animation as part of
the same vertex record, but that would likely cause far more data to be
loaded at render-time than in the sequential cases.'''
