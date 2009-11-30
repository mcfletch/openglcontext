#! /usr/bin/env python
"""Retrieve OpenGL Light state values and print to console"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
import string

##from arraystuff import *
from OpenGL.GL import *

class TestContext( BaseContext ):
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        for param, name in parameters:
            print name, glGetLightfv(GL_LIGHT0, param ) # now requires fully-specified name...
parameters = [
    (GL_AMBIENT, "GL_AMBIENT"),
    (GL_DIFFUSE, "GL_DIFFUSE"),
    (GL_SPECULAR, "GL_SPECULAR"),
    (GL_POSITION, "GL_POSITION"),
    (GL_SPOT_DIRECTION, "GL_SPOT_DIRECTION"),
    (GL_SPOT_EXPONENT,"GL_SPOT_EXPONENT"),
    (GL_SPOT_CUTOFF,"GL_SPOT_CUTOFF"),
    (GL_CONSTANT_ATTENUATION,"GL_CONSTANT_ATTENUATION"),
    (GL_LINEAR_ATTENUATION , "GL_LINEAR_ATTENUATION"),
    (GL_QUADRATIC_ATTENUATION, "GL_QUADRATIC_ATTENUATION"),
]
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
