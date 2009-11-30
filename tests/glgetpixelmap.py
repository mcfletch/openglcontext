#! /usr/bin/env python
"""Retrieve OpenGL pixel-map state values and print to console"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
import string

##from arraystuff import *
from OpenGL.GL import *

class TestContext( BaseContext ):
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        for param, name in parameters:
            print name, glGetPixelMapfv(param )
parameters = [
    (GL_PIXEL_MAP_I_TO_I, "GL_PIXEL_MAP_I_TO_I"),
    (GL_PIXEL_MAP_S_TO_S, "GL_PIXEL_MAP_S_TO_S"),
    (GL_PIXEL_MAP_I_TO_R, "GL_PIXEL_MAP_I_TO_R"),
    (GL_PIXEL_MAP_I_TO_G, "GL_PIXEL_MAP_I_TO_G"),
    (GL_PIXEL_MAP_I_TO_B, "GL_PIXEL_MAP_I_TO_B"),
    (GL_PIXEL_MAP_I_TO_A, "GL_PIXEL_MAP_I_TO_A"),
    (GL_PIXEL_MAP_R_TO_R, "GL_PIXEL_MAP_R_TO_R"),
    (GL_PIXEL_MAP_G_TO_G, "GL_PIXEL_MAP_G_TO_G"),
    (GL_PIXEL_MAP_B_TO_B, "GL_PIXEL_MAP_B_TO_B"),
    (GL_PIXEL_MAP_A_TO_A, "GL_PIXEL_MAP_A_TO_A"),
]
        
if __name__ == "__main__":
    TestContext.ContextMainLoop()
