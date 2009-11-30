#! /usr/bin/env python
"""Spinning cube demo, inspired by Pete Shinner's demo...

Well, okay, inspired is a bit much for such a tiny piece of
code :) .
"""
#import OpenGL 
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
import string, time
from OpenGLContext import drawcube

class TestContext( BaseContext ):
    initialPosition = (0,0,2) 
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glTranslatef( 0,0,-1)
        glRotated( (time.time()%4.0/4) * 360, 0,1,0)
        drawcube.drawCube()
    def OnIdle( self, ):
        self.triggerRedraw(1)
        return 1

if __name__ == "__main__":
    TestContext.ContextMainLoop()
