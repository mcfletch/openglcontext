#! /usr/bin/env python
'''=OpenGLContext Timers (NeHe 6 Based)=

[nehe6_timer.py-screen-0001.png Screenshot]

This customization of the original rotating cube demo
uses the Timer class to provide a flexible timing
mechanism for the animation.

In particular, the demo allows you to modify the
"multiplier" value of the internal time frame of
reference compared to real world time.  This allows
for speeding, slowing and reversing the state of
rotation.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string
from OpenGLContext.events.timer import Timer
from OpenGLContext import texture

class TestContext( BaseContext ):
    """Timer-based control of animation (OpenGLContext timers)
    """
    initialPosition = (0,0,0)
    drawPollTimeout = 0.01
    def OnInit( self ):
        """Load the image on initial load of the application"""
        self.image = self.loadImage ()
        print """You should see a slowly rotating textured cube

The animation is provided by a timer, rather than the
crude time-module based animation we use for the other
NeHe tutorials."""
        print '  <r> reverse the time-sequence'
        print '  <s> make time pass more slowly'
        print '  <f> make time pass faster'
        '''Here we will register key-press handlers for the various 
        operations the user can perform.'''
        self.addEventHandler( "keypress", name="r", function = self.OnReverse)
        self.addEventHandler( "keypress", name="s", function = self.OnSlower)
        self.addEventHandler( "keypress", name="f", function = self.OnFaster)
        '''We'll create a Timer object.  The duration is the total 
        cycle length for the timer, the repeating flag tells the 
        timer to continue running.'''
        self.time = Timer( duration = 8.0, repeating = 1 )
        '''The timer generates events for "fractions" as well as for 
        cycles.  We use the fraction value to generate a smooth 
        animation.'''
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        '''Registering and starting the timer are only necessary because
        the node is not part of a scenegraph.'''
        self.time.register (self)
        self.time.start ()
        '''As with the time.time() mechanism, we need to track our 
        current rotation so that the rendering pass can perform the 
        rotation calculated by the timer callback.'''
        self.rotation =  0
    '''Timer callback'''
    def OnTimerFraction( self, event ):
        self.rotation = event.fraction()* -360
    '''Keyboard callbacks.  Each of these simply modifies the timer's 
    internal-timer multiplier.  Each Timer node has an internal timer
    which provides the low-level events that the timer interprets.  By
    changing the multiplier on this internal timer we change the 
    perceived passage of time for the user.'''
    def OnReverse( self, event ):
        self.time.internal.multiplier = -self.time.internal.multiplier
        print "reverse",self.time.internal.multiplier
    def OnSlower( self, event ):
        self.time.internal.multiplier = self.time.internal.multiplier /2.0
        print "slower",self.time.internal.multiplier
    def OnFaster( self, event ):
        self.time.internal.multiplier = self.time.internal.multiplier * 2.0
        print "faster",self.time.internal.multiplier
    def Render( self, mode):
        """Render scene geometry"""
        BaseContext.Render( self, mode )
        glDisable( GL_LIGHTING) # context lights by default
        glTranslatef(1.5,0.0,-6.0);
        glRotated( self.rotation, 1,0,0)
        glRotated( self.rotation, 0,1,0)
        glRotated( self.rotation, 0,0,1)
        self.setupTexture()
        self.drawCube()
    def loadImage( self, imageName = "nehe_wall.bmp" ):
        """Load an image file as a 2D texture using PIL
        """
        try:
            from PIL.Image import open
        except ImportError, err:
            from Image import open
        im = texture.Texture( open(imageName) )
        return im
    def setupTexture( self ):
        # texture-mode setup, was global in original
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_DECAL)
        self.image()
            
    def drawCube( self ):
        """Draw a cube with texture coordinates"""
        glBegin(GL_QUADS);
        glTexCoord2f(0.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
        glTexCoord2f(1.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);

        glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
        glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);

        glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
        glTexCoord2f(0.0, 0.0); glVertex3f(-1.0,  1.0,  1.0);
        glTexCoord2f(1.0, 0.0); glVertex3f( 1.0,  1.0,  1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);

        glTexCoord2f(1.0, 1.0); glVertex3f(-1.0, -1.0, -1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f( 1.0, -1.0, -1.0);
        glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
        glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);

        glTexCoord2f(1.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
        glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);

        glTexCoord2f(0.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
        glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
        glTexCoord2f(1.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);
        glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
        glEnd()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''
Author: [http://nehe.gamedev.net Jeff Molofee (aka NeHe)]

COPYRIGHT AND DISCLAIMER: (c)2000 Jeff Molofee

If you plan to put this program on your web page or a cdrom of
any sort, let me know via email, I'm curious to see where
it ends up :)

If you use the code for your own projects please give me
credit, or mention my web site somewhere in your program 
or it's docs.
'''