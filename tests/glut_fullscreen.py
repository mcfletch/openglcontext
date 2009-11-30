#! /usr/bin/env python
'''GLUT full screen test (when f is pressed, goes to full-screen)

Based on nehe6
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive( 'glut' )
from OpenGLContext.scenegraph import imagetexture
from OpenGLContext import drawcube
from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGLContext.arrays import array
import string, time

class TestContext( BaseContext ):
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    def Render( self, mode = None):
        BaseContext.Render( self, mode )
        glDisable( GL_LIGHTING) # context lights by default
        glTranslatef(1.5,0.0,-6.0);
        glRotated( time.time()%(8.0)/8 * -360, 1,0,0)

        
        self.texture.render(mode=mode)
        drawcube.drawCube()
        self.texture.renderPost(mode=mode)
    def OnInit( self ):
        """Load the image on initial load of the application"""
        self.texture = imagetexture.ImageTexture(url = [ "nehe_wall.bmp"] )
        print 'Press <f> to switch to full-screen mode'
        self.addEventHandler( 'keypress', name = 'f', function = self.OnFullScreenToggle)
        self.addEventHandler( 'keyboard', name = '<escape>', function = self.OnFullScreenToggle)
        self.returnValues = None
    def OnFullScreenToggle( self, event ):
        """Toggle between full and regular windows"""
        if self.returnValues:
            # return to the previous size
            posx, posy, sizex, sizey = self.returnValues
            glutReshapeWindow( sizex, sizey)
            glutPositionWindow( posx, posy )
            self.returnValues = None
        else:
            self.returnValues = (
                glutGet( GLUT_WINDOW_X ),
                glutGet( GLUT_WINDOW_Y ),
                glutGet( GLUT_WINDOW_WIDTH  ),
                glutGet( GLUT_WINDOW_HEIGHT ),
            )
            glutFullScreen( )
    def OnIdle( self, ):
        self.triggerRedraw(1)
        return 1
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
