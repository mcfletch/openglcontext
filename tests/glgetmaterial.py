#! /usr/bin/env python
"""Retrieve OpenGL material state values and print to console"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
import string

##from arraystuff import *
from OpenGL.GL import *

class TestContext( BaseContext ):
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        for param, name in parameters:
            print name, glGetMaterialfv(GL_FRONT, param )
parameters = [
    (GL_AMBIENT, "GL_AMBIENT"),
    (GL_DIFFUSE, "GL_DIFFUSE"),
    (GL_SPECULAR, "GL_SPECULAR"),
    (GL_EMISSION, "GL_EMISSION"),
    (GL_SHININESS, "GL_SHININESS"),
    (GL_COLOR_INDEXES, "GL_COLOR_INDEXES"),
]
        
if __name__ == "__main__":
    TestContext.ContextMainLoop()
